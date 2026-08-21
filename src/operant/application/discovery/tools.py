"""
One handler per model tool.

Every handler returns a ``ToolOutcome``: a reply string fed back to the
model, or a finished result that ends the run. Action errors never kill
a run - they become tool replies the model must hear about and re-plan
on.

Import as:

import operant.application.discovery.tools as tools
"""

from __future__ import annotations

import dataclasses
import re
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

import operant.application.acting as acting
import operant.application.discovery.bootstrap as bstrap
import operant.application.discovery.config as config
import operant.application.escalation as escal
import operant.application.gateway.learner as gllearne
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.models.actions as actions
import operant.domain.models.digest as digest
import operant.domain.models.graph as graph
import operant.domain.models.targets as targets
import operant.domain.outcomes as outcomes
import operant.domain.profile as profile
import operant.domain.remediation as odremed
import operant.domain.sensitivity as sensv

if TYPE_CHECKING:
    import operant.application.discovery.loop as loop

# An action that fails is a fact the model must hear about, never a dead run.
ACTION_ERRORS = (
    errors.DriverError,
    errors.AllToolsFailedError,
    errors.NoToolAvailableError,
    KeyError,
    RuntimeError,
    TimeoutError,
)

_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://?")


# #############################################################################
# ToolOutcome
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ToolOutcome:
    """
    What a tool handler produced.

    :ivar reply: Text fed back to the model as the tool result.
    :ivar finished: A terminal result that ends the run, when any.
    """

    reply: Optional[str] = None
    finished: Optional[Union[config.DiscoveryResult, config.DiscoveryFailure]] = (
        None
    )


def handle_declare_input(
    session: loop.DiscoverySession, args: Dict[str, Any]
) -> ToolOutcome:
    """
    Register a task parameter the agent derived from the goal.
    """
    state, log = session.state, session.log
    name, value = str(args.get("name", "")).strip(), str(args.get("value", ""))
    if not name or not value:
        return ToolOutcome("declare_input needs a non-empty name and value.")
    if state.params.get(name) == value:
        return ToolOutcome(
            f'{name} = "{state.shown(name, value)}" is ALREADY registered. '
            "Do not declare it again - take the next ACTION toward the goal."
        )
    declared = str(args.get("data_class") or "")
    known = declared if declared in {"pii", "financial", "credential"} else None
    data_class = sensv.classify(name=name, value=value, declared=known)
    if data_class == "credential":
        return ToolOutcome(
            f'"{name}" is a credential - do NOT declare or type it. Call '
            f'request_secret(name="{name}") so a human provides it, then fill '
            f'the field with value="$secret:{name}".'
        )
    state.params[name] = value
    state.input_types[name] = str(args.get("type", "string"))
    state.input_classes[name] = data_class
    if sensv.is_sensitive(data_class):
        log.redactor.add_secret(value)
        log.emit(
            events.SensitiveValueClassified(
                name=name,
                data_class=data_class,
                source="declared" if declared else "detector",
                summary=f"input {name} classified {data_class}",
            )
        )
    if data_class == "credential":
        state.scrub_history(value)
    log.emit(
        events.InputDeclared(
            name=name,
            value=value,
            value_type=state.input_types[name],
            summary=f"agent declared input {name}={value}",
        )
    )
    return ToolOutcome(
        f'Registered input {name} = "{state.shown(name, value)}". '
        "Continue with the task."
    )


def handle_request_secret(
    session: loop.DiscoverySession, args: Dict[str, Any]
) -> ToolOutcome:
    """
    Ask a human for a credential; the model only gets a ``$secret`` handle.
    """
    name = str(args.get("name", "")).strip()
    reason = str(args.get("reason", ""))
    if not name:
        return ToolOutcome("request_secret needs a non-empty name.")
    requester = session.cfg.credential_requester
    if requester is None:
        return ToolOutcome(
            "No credential channel is available; give_up if the task needs one."
        )
    grant = requester.request(name, run_id=session.log.run_id, reason=reason)
    if grant is None:
        return ToolOutcome(
            f'No credential provided for "{name}". Ask again or give_up.'
        )
    if grant.locator is not None:
        try:
            session.secrets.add_reference(name, grant.locator)
            session.secrets.resolve(name)
        except (ValueError, errors.SecretNotFoundError) as err:
            return ToolOutcome(
                f'Could not resolve the source for "{name}": {err}. '
                "Ask again or give_up."
            )
    elif grant.value is not None:
        session.secrets.add_transient(name, grant.value)
    else:
        return ToolOutcome(f'Empty credential for "{name}". Ask again.')
    session.log.emit(
        events.SensitiveValueClassified(
            name=name,
            data_class="credential",
            source="provided",
            summary=f"credential {name} provided by human",
        )
    )
    return ToolOutcome(
        f'Secret "{name}" is ready. Fill the field with '
        f'value="$secret:{name}"; you never see the value.'
    )


def handle_clarify(
    session: loop.DiscoverySession, args: Dict[str, Any]
) -> ToolOutcome:
    """
    Route the agent's question to the clarifier channel, if any.
    """
    question = str(args.get("question", ""))
    if session.cfg.clarifier is None:
        outcome = ToolOutcome(
            "No clarification channel is available. Determine the value "
            "from the goal/screen if at all possible, else give_up."
        )
    else:
        answer = session.cfg.clarifier.ask(question, run_id=session.log.run_id)
        session.log.emit(
            events.Clarify(
                question=question,
                answered=bool(answer),
                summary=(
                    f"clarify: {question} -> "
                    f"{'answered' if answer else '(no answer)'}"
                ),
            )
        )
        outcome = (
            ToolOutcome(f'Human answer: "{answer}"')
            if answer
            else ToolOutcome("No answer provided.")
        )
    return outcome


def handle_extract(
    session: loop.DiscoverySession, args: Dict[str, Any]
) -> ToolOutcome:
    """
    Read one output from the visible text via a one-group regex.
    """
    state, log = session.state, session.log
    name, pattern = str(args.get("name", "")), str(args.get("pattern", ""))
    if state.screen is None:
        return ToolOutcome("No window is bound yet - launch first.")
    try:
        value = outcomes.extract_one(pattern, state.screen.text)
    except re.error as err:
        return ToolOutcome(f"Invalid regex: {err}")
    if value is None:
        return ToolOutcome("Pattern did not match the visible text. Refine it.")
    data_class = sensv.classify(name=name, value=value)
    state.extracted[name] = value
    state.output_classes[name] = data_class
    state.output_origins[name] = (
        state.current_binding[0] if state.current_binding else ""
    )
    if sensv.is_sensitive(data_class):
        log.redactor.add_secret(value)
        log.emit(
            events.SensitiveValueClassified(
                name=name,
                data_class=data_class,
                source="detector",
                summary=f"output {name} classified {data_class}",
            )
        )
    session.recorder.record_extraction(name, pattern)
    log.emit(
        events.ExtractionRecorded(
            name=name,
            pattern=pattern,
            value=value,
            summary=f'extracted {name}="{value}"',
        )
    )
    return ToolOutcome(f'Extracted {name} = "{value}".')


def handle_goal_complete(
    session: loop.DiscoverySession, args: Dict[str, Any], turn: int
) -> ToolOutcome:
    """
    End the run: builds the recording and the effective profile.
    """
    cfg, state, log = session.cfg, session.state, session.log
    log.emit(
        events.GoalComplete(
            outputs=state.extracted,
            inputs=state.params,
            turns=turn,
            summary=str(args.get("summary", "")),
        )
    )
    if cfg.bootstrap and state.primary_boot is None:
        outcome = ToolOutcome(
            finished=config.DiscoveryFailure(
                "goal_complete before any launch - nothing was recorded"
            )
        )
    else:
        effective = _effective_profile(session)
        recording = session.build_recording(effective)
        for edge_id, param, data_class in recording.promoted:
            log.emit(
                events.SensitiveLiteralPromoted(
                    edge=edge_id,
                    param=param,
                    data_class=data_class,
                    summary=(
                        f"{edge_id}: sensitive literal promoted to input "
                        f"{param} ({data_class})"
                    ),
                )
            )
        outcome = ToolOutcome(
            finished=config.DiscoveryResult(
                recording=recording, profile=effective, grants=state.grants
            )
        )
    return outcome


def _effective_profile(
    session: loop.DiscoverySession,
) -> profile.AppProfile:
    """
    Resolve the profile to persist: derived, unchanged, or grant-widened.
    """
    cfg, state = session.cfg, session.state
    if cfg.bootstrap and state.primary_boot is not None:
        # Bootstrap: derive the profile from the first launch.
        effective = bstrap.profile_for(
            state.primary_boot, cfg.profile, state.grants
        )
    elif not state.grants:
        # Nothing was widened: persist the profile unchanged.
        effective = cfg.profile
    else:
        # Fold the run's grants into the existing policy.
        policy = cfg.profile.policy
        app_grants = {g.pattern for g in state.grants if g.kind == "app"}
        url_grants = {g.pattern for g in state.grants if g.kind == "url"}
        effective = cfg.profile.model_copy(
            update={
                "policy": policy.model_copy(
                    update={
                        "allowed_apps": sorted(
                            {*policy.allowed_apps, *app_grants}
                        ),
                        "allowed_url_patterns": sorted(
                            {*policy.allowed_url_patterns, *url_grants}
                        ),
                    }
                )
            }
        )
    return effective


def handle_give_up(
    session: loop.DiscoverySession,
    args: Dict[str, Any],
    screenshot: str,
) -> ToolOutcome:
    """
    Raise a human intervention; resumes or ends per the resolution.
    """
    cfg, state, log = session.cfg, session.state, session.log
    reason = str(args.get("reason", ""))
    log.emit(
        events.AgentGaveUp(reason=reason, summary=f"agent gave up: {reason}")
    )
    resolution = session.broker.raise_intervention(
        escal.InterventionRequest(
            run_id=log.run_id,
            kind="discovery",
            capability=cfg.capability_name,
            goal=cfg.goal,
            reason=f"agent is stuck: {reason}",
            page_title=(
                state.screen.window_title if state.screen else "(no window)"
            ),
            screenshot_file=screenshot or None,
        )
    )
    if resolution.resolution == "abandoned":
        return ToolOutcome(
            finished=config.DiscoveryFailure(
                f"agent stuck ({reason}); operator marked unrecoverable: "
                f"{resolution.note}",
                failure_class="escalated_abandoned",
            )
        )
    session.broker.resume_automation("operator assisted during discovery")
    state.screen = session.snapshot_or_none()
    performed = "; ".join(resolution.human_actions) or "(no recorded actions)"
    if (
        session.remediation is not None
        and state.pending_failure is not None
        and resolution.human_actions
    ):
        situation, error_sig = state.pending_failure
        session.remediation.record(situation, error_sig, "human_steps", performed)
        state.pending_failure = None
    return ToolOutcome(
        "A human operator intervened on the live session and performed: "
        f'{performed}. Note: "{resolution.note}". Continue from the CURRENT '
        "screen (next message)."
    )


# #############################################################################
# _PlannedAct
# #############################################################################


@dataclasses.dataclass(frozen=True)
class _PlannedAct:
    """
    One act, resolved and ready to perform.
    """

    surface_action: actions.SurfaceAction
    recorded: graph.Action
    control: Optional[digest.Control] = None
    click_point: Optional[Tuple[float, float]] = None
    boot: Optional[bstrap.VendorBootstrap] = None


def handle_act(
    session: loop.DiscoverySession,
    args: Dict[str, Any],
    turn: int,
) -> ToolOutcome:
    """
    Perform one UI action through the policy gate and records it.
    """
    kind = str(args.get("action", ""))
    planned = _plan_act(session, args, kind)
    if isinstance(planned, ToolOutcome):
        outcome = planned
    else:
        outcome = _perform_act(session, planned, args, kind, turn)
    return outcome


def _plan_act(
    session: loop.DiscoverySession,
    args: Dict[str, Any],
    kind: str,
) -> Union[_PlannedAct, ToolOutcome]:
    """
    Resolve the target control and route to the right act planner.
    """
    state = session.state
    has_xy = args.get("x") is not None and args.get("y") is not None
    control: Optional[digest.Control] = None
    if args.get("ref") and state.screen is not None:
        control = next(
            (c for c in state.screen.controls if c.ref == args.get("ref")),
            None,
        )
    needs_control = kind in {"fill", "select"} or (kind == "click" and not has_xy)
    if control is None and needs_control:
        # The named control is gone: tell the model to re-read the digest.
        hint = ", or click by x/y coordinates." if kind == "click" else "."
        planned: Union[_PlannedAct, ToolOutcome] = ToolOutcome(
            f'Unknown control ref "{args.get("ref")}". '
            f"Use a ref from the digest{hint}"
        )
    elif kind == "launch":
        # Launch routes through its own vendor-deriving planner.
        planned = _plan_launch(session, args)
    else:
        # Everything else is a control- or coordinate-based act.
        planned = _plan_simple(session, args, kind, control)
    return planned


def _plan_simple(
    session: loop.DiscoverySession,
    args: Dict[str, Any],
    kind: str,
    control: Optional[digest.Control],
) -> Union[_PlannedAct, ToolOutcome]:
    """
    Plan a non-launch act (press, click, fill, select, scroll).
    """
    if kind == "press":
        key = str(args.get("key", "Enter"))
        return _PlannedAct(
            actions.SurfaceAction(kind="press", key=key),
            graph.Action(kind="press", key=key),
        )
    if kind == "click" and control is not None:
        return _PlannedAct(
            actions.SurfaceAction(kind="click", ref=control.ref),
            graph.Action(kind="click"),
            control=control,
        )
    if kind == "click":
        x, y = float(args["x"]), float(args["y"])
        return _PlannedAct(
            actions.SurfaceAction(
                kind="click",
                x=x,
                y=y,
                target_text=str(args.get("intent", "")),
            ),
            graph.Action(kind="click"),
            click_point=(x, y),
        )
    if kind == "fill" and control is not None:
        return _plan_fill(session, args, control)
    if kind == "select" and control is not None:
        option = str(args.get("option") or "")
        data_class = sensv.classify(
            name=control.name,
            label=control.label,
            value=option,
            control_role=control.role,
        )
        return _PlannedAct(
            actions.SurfaceAction(
                kind="select",
                ref=control.ref,
                option=option,
                data_class=data_class,
            ),
            graph.Action(kind="select", option=targets.Value(literal=option)),
            control=control,
        )
    if kind == "scroll":
        direction = "up" if args.get("direction") == "up" else "down"
        amount = int(args.get("amount") or 5)
        return _PlannedAct(
            actions.SurfaceAction(
                kind="scroll",
                ref=control.ref if control else None,
                direction=direction,
                amount=amount,
            ),
            graph.Action(kind="scroll", direction=direction, amount=amount),
            control=control,
        )
    return ToolOutcome(f'Unknown action "{kind}".')


def _plan_fill(
    session: loop.DiscoverySession,
    args: Dict[str, Any],
    control: digest.Control,
) -> Union[_PlannedAct, ToolOutcome]:
    """
    Plan a fill, resolving secrets and classifying the value's sensitivity.
    """
    state = session.state
    fill_value = str(args.get("value", "") or "")
    placeholder = fill_value.removeprefix("$secret:")
    if placeholder != fill_value:
        try:
            resolved = session.secrets.resolve(placeholder)
        except errors.SecretNotFoundError as missing:
            return ToolOutcome(str(missing))
        return _PlannedAct(
            actions.SurfaceAction(
                kind="fill",
                ref=control.ref,
                value=resolved,
                data_class="credential",
                secret_ref=placeholder,
            ),
            graph.Action(
                kind="fill", value=targets.Value(secret_ref=placeholder)
            ),
            control=control,
        )
    from_inputs = [n for n, v in state.params.items() if v == fill_value]
    from_outputs = [n for n, v in state.extracted.items() if v == fill_value]
    fill_class = sensv.strongest(
        *(state.input_classes.get(n) for n in from_inputs),
        *(state.output_classes.get(n) for n in from_outputs),
        sensv.classify(
            name=control.name,
            label=control.label,
            value=fill_value,
            control_role=control.role,
            control_value=control.value,
        ),
    )
    here = state.current_binding[0] if state.current_binding else ""
    export_from = next(
        (
            state.output_origins[n]
            for n in from_outputs
            if state.output_origins.get(n) and state.output_origins[n] != here
        ),
        None,
    )
    return _PlannedAct(
        actions.SurfaceAction(
            kind="fill",
            ref=control.ref,
            value=fill_value,
            data_class=fill_class,
            export_from=export_from,
        ),
        graph.Action(kind="fill", value=targets.Value(literal=fill_value)),
        control=control,
    )


def _plan_launch(
    session: loop.DiscoverySession, args: Dict[str, Any]
) -> Union[_PlannedAct, ToolOutcome]:
    """
    Plan a launch, deriving the vendor for a model-decided target.
    """
    cfg = session.cfg
    app = str(args.get("app") or "").strip()
    url = str(args.get("url") or "").strip() or None
    # Only a real scheme ("https://…", "x-apple…:") or an explicit app is a
    # model-decided target; a bare path like "overview.htm" is relative to
    # the bound profile - retargeting on it once pointed the session at app
    # "" and bricked the whole run.
    has_scheme = bool(url and _SCHEME_RE.match(url) and ":" in url)
    if cfg.bootstrap or app or has_scheme:
        if not app and url and url.startswith("http"):
            app = session.default_browser
        if not app and not has_scheme:
            return ToolOutcome(
                'launch needs an app name (e.g. app="Notes") or a full URL.'
            )
        boot = session.derive_vendor(app, url)
        return _PlannedAct(
            actions.SurfaceAction(
                kind="launch", app=boot.app_name or None, url=url
            ),
            graph.Action(kind="launch", app=boot.app_name or None, url=url),
            boot=boot,
        )
    path = url or session.entry_path or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    return _PlannedAct(
        actions.SurfaceAction(
            kind="launch",
            app=cfg.profile.app_name,
            url=f"{session.base_url}{path}",
        ),
        graph.Action(kind="launch", app=cfg.profile.app_name, url=path),
    )


def _perform_act(
    session: loop.DiscoverySession,
    planned: _PlannedAct,
    args: Dict[str, Any],
    kind: str,
    turn: int,
) -> ToolOutcome:
    """
    Perform a planned act through the policy gate and record the result.
    """
    state, log = session.state, session.log
    intent = str(args.get("intent", ""))
    prev_target = session.retarget_for(planned.boot)
    situation = _situation_sig(state.screen, planned.surface_action)
    try:
        state.screen = acting.perform_and_record(
            session.surface,
            session.cfg.profile.policy,
            planned.surface_action,
            approver=session.approver,
            log=log,
            recorder=session.recorder,
            recorded=planned.recorded,
            description=intent,
            pre_digest=state.screen,
            click_point=planned.click_point,
            on_grant=state.grants.append,
        )
    except errors.ApprovalDeniedError as denied:
        session.undo_retarget(prev_target)
        return _blocked_reply(
            session,
            f"DENIED by human ({denied.request.kind}): "
            f"{denied.request.summary}",
            f"{denied.request.kind} denied by human: {denied.request.summary}",
            "Choose a compliant alternative or give_up.",
        )
    except errors.PolicyViolationError as blocked:
        session.undo_retarget(prev_target)
        return _blocked_reply(
            session,
            f"BLOCKED: {blocked.decision.reason}",
            blocked.decision.reason,
            "Choose a compliant alternative or give_up.",
            prefix="BLOCKED by policy",
        )
    except ACTION_ERRORS as err:
        session.undo_retarget(prev_target)
        log.emit(
            events.SurfaceError(error=str(err), summary=f"action failed: {err}")
        )
        state.screen = session.snapshot_or_none() or state.screen
        hint = _remedy_hint(session, situation, str(err))
        return ToolOutcome(
            f"Action FAILED: {err}. Observe the current screen and try a "
            "different approach (another control, select instead of "
            f"fill, ...).{hint}"
        )
    _record_remedy_if_recovered(session, situation, kind, intent)
    session.commit_binding(planned.boot, args)
    log.emit(
        events.AgentAction(
            turn=turn,
            action=kind,
            intent=intent,
            target=_target_text(planned, args),
            summary=f"{kind}: {intent}",
        )
    )
    return ToolOutcome(f"OK ({kind}). New screen state follows.")


def _situation_sig(
    pre: Optional[digest.ScreenDigest], action: actions.SurfaceAction
) -> str:
    """
    Coarse, value-free signature of an action on the current screen.
    """
    app = pre.app if pre is not None else (action.app or "")
    title = pre.window_title if pre is not None else ""
    sig = gllearne.signature(action, app, title)
    return sig


def _remedy_hint(
    session: loop.DiscoverySession, situation: str, error: str
) -> str:
    """
    Record the failure and surface a remembered fix, if any.
    """
    memory = session.remediation
    hint = ""
    if memory is not None:
        error_sig = odremed.error_signature(error)
        session.state.pending_failure = (situation, error_sig)
        remedy = memory.query(situation, error_sig)
        if remedy is not None:
            hint = (
                " A previous run hit this same error here; the fix that "
                f"worked was: {remedy.hint}"
            )
    return hint


def _record_remedy_if_recovered(
    session: loop.DiscoverySession, situation: str, kind: str, intent: str
) -> None:
    """
    Remember the action that succeeded after a failure on this situation.
    """
    memory = session.remediation
    pending = session.state.pending_failure
    if memory is not None and pending is not None:
        if pending[0] == situation:
            memory.record(
                situation, pending[1], "alternate_action", f"{kind}: {intent}"
            )
        session.state.pending_failure = None


def _blocked_reply(
    session: loop.DiscoverySession,
    log_summary: str,
    reason: str,
    advice: str,
    *,
    prefix: Optional[str] = None,
) -> ToolOutcome:
    """
    Log a policy block and build the reply the model must re-plan on.
    """
    session.log.emit(events.PolicyBlocked(reason=reason, summary=log_summary))
    session.state.screen = session.snapshot_or_none() or session.state.screen
    head = f"{prefix}: {reason}" if prefix else log_summary
    outcome = ToolOutcome(f"{head}. {advice}")
    return outcome


def _target_text(planned: _PlannedAct, args: Dict[str, Any]) -> str:
    """
    Describe the act's target for the action-logged event.
    """
    if planned.control is not None:
        control = planned.control
        text = f'{control.role} "{control.name or control.label}"'
    else:
        text = str(args.get("url") or args.get("key") or args.get("app") or "")
    return text
