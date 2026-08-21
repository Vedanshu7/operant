"""
The discovery session: observe -> decide -> act, one tool call per turn.

Two modes:

- profile mode: a curated ``AppProfile`` names the app and tenant; the
  entry launch is part of the task definition.
- bootstrap mode: no pre-seeded vendor. The model decides from the goal
  which application or URL to open; the vendor identity, graph binding,
  and a replayable profile are derived from that first launch. Launches
  outside the current policy raise a human scope approval instead of a
  dead end.

The model never sees credential values - it types ``$secret:<name>``
placeholders the runtime resolves after the policy check.

Import as:

import operant.application.discovery.loop as loop
"""

from __future__ import annotations

import base64
import dataclasses
import json
import re
import time
from typing import Dict, FrozenSet, List, Optional, Tuple, Union

import operant.application.approval as approval
import operant.application.discovery.bootstrap as bstrap
import operant.application.discovery.config as config
import operant.application.discovery.prompt as prompt
import operant.application.discovery.state as dsstate
import operant.application.discovery.tools as tools
import operant.application.escalation as escal
import operant.application.recorder.builder as builder
import operant.application.recorder.recording as recdng
import operant.application.remediation as remem
import operant.application.secrets as secrets
import operant.domain.digest as digest
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.graph.localize as localize
import operant.domain.models.actions as actions
import operant.domain.models.artifact as artifact
import operant.domain.models.digest as mddigest
import operant.domain.models.graph as graph
import operant.domain.models.llm as mlllm
import operant.domain.profile as profile
import operant.domain.sensitivity as sensv
import operant.helpers.logging as logging
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.llm as plllm
import operant.ports.secrets as pssecret
import operant.ports.surface as pssurfac

_LOG = logging.get_logger(__name__)

_BLIND_TURN_WARNING = 3
_UNESCAPE = re.compile(r"\\(.)")


def _node_title(node: graph.Node) -> str:
    """
    Recover a node's human-readable title from its title check.
    """
    title = ""
    for check in node.checks:
        if isinstance(check, graph.TitleMatches):
            title = _UNESCAPE.sub(r"\1", check.pattern)
            break
    return title


# #############################################################################
# DiscoveryDeps
# #############################################################################


@dataclasses.dataclass
class DiscoveryDeps:
    """
    What a discovery session is wired with.

    :ivar surface: The actuation surface.
    :ivar broker: Control broker for give-up interventions.
    :ivar log: Evidence sink.
    :ivar llm: The model client.
    :ivar secret_store: Where secret references resolve.
    :ivar model_name: Model id recorded in provenance.
    :ivar approval_timeout_s: Console-approver wait bound.
    :ivar llm_retries: Attempts per model call.
    :ivar retry_base_delay_s: Backoff base between attempts.
    :ivar default_browser: App used when a goal names only a URL.
    :ivar browsers: Lower-cased app names treated as browsers.
    :ivar remediation: Cross-run memory of fixes for repeated errors.
    """

    surface: pssurfac.Surface
    broker: escal.ControlBroker
    log: evidence.EvidenceSink
    llm: plllm.LlmClient
    secret_store: pssecret.SecretStore
    model_name: str = ""
    approval_timeout_s: float = 300.0
    llm_retries: int = 3
    retry_base_delay_s: float = 2.0
    default_browser: str = "Google Chrome"
    browsers: FrozenSet[str] = bstrap.DEFAULT_BROWSERS
    remediation: Optional[remem.RemediationMemory] = None


# #############################################################################
# DiscoverySession
# #############################################################################


@dataclasses.dataclass
class DiscoverySession:
    """
    Run one discovery: the loop, its state, and the tool handlers.

    :ivar cfg: The run's contract.
    :ivar deps: Wiring.
    :ivar state: Per-run accumulation.
    :ivar recorder: Accumulates the recording as actions succeed.
    """

    cfg: config.DiscoveryConfig
    deps: DiscoveryDeps
    state: dsstate.DiscoveryState = dataclasses.field(
        default_factory=dsstate.DiscoveryState
    )
    recorder: recdng.Recorder = dataclasses.field(default_factory=recdng.Recorder)

    def __post_init__(self) -> None:
        """
        Wire the approver, secret resolver, and system prompt.
        """
        self._tenant = self.cfg.profile.tenants.get(self.cfg.tenant)
        self._blind_turns = 0
        self._last_screenshot = ""
        self.approver: hitl.Approver = (
            self.cfg.approver
            or approval.BrokerApprover(
                self.deps.broker,
                self.deps.approval_timeout_s,
                run_id=self.log.run_id,
            )
        )
        binding = self._tenant or None
        self.secrets = secrets.SecretResolver(
            binding or artifact.TenantBinding(base_url=""),
            self.deps.secret_store,
            self.log.redactor,
        )
        self._system_prompt = prompt.build_system_prompt(
            self.secrets.names(), self.deps.default_browser
        )
        self._recognized_node: Optional[str] = None

    # ── conveniences the tool handlers use ─────────────────────────────

    @property
    def surface(self) -> pssurfac.Surface:
        """
        The actuation surface.
        """
        return self.deps.surface

    @property
    def broker(self) -> escal.ControlBroker:
        """
        The control broker.
        """
        return self.deps.broker

    @property
    def log(self) -> evidence.EvidenceSink:
        """
        The evidence sink.
        """
        return self.deps.log

    @property
    def base_url(self) -> str:
        """
        The tenant base URL, trailing slash stripped.
        """
        url = (self._tenant.base_url if self._tenant else "").rstrip("/")
        return url

    @property
    def entry_path(self) -> str:
        """
        The tenant's entry path (e.g. ``/index.htm``); may be empty.
        """
        path = self._tenant.entry_path if self._tenant else ""
        return path

    @property
    def default_browser(self) -> str:
        """
        The browser used when a goal names only a URL.
        """
        return self.deps.default_browser

    @property
    def remediation(self) -> Optional[remem.RemediationMemory]:
        """
        The cross-run remedy memory, when wired.
        """
        return self.deps.remediation

    def derive_vendor(
        self, app: str, url: Optional[str]
    ) -> bstrap.VendorBootstrap:
        """
        Derive a vendor identity from a model-decided launch.
        """
        boot = bstrap.derive_vendor(app, url, browsers=self.deps.browsers)
        return boot

    def snapshot_or_none(self) -> Optional[mddigest.ScreenDigest]:
        """
        Observe the surface, or ``None`` when no window is bound.
        """
        try:
            snap = self.surface.snapshot()
        except Exception:
            # No window is bound yet.
            snap = None
        return snap

    def retarget_for(
        self, boot: Optional[bstrap.VendorBootstrap]
    ) -> Optional[Tuple[str, str]]:
        """
        Retargets the session ahead of an app-switching launch.
        """
        state = self.state
        if (
            boot is None
            or not boot.app_name
            or (
                state.current_binding is not None
                and boot.vendor_id == state.current_binding[0]
            )
        ):
            # Same vendor or no target: nothing to retarget.
            previous = None
        else:
            # Switching apps: point the surface and recorder at the new one.
            previous = self.surface.retarget(
                boot.app_name, boot.window_title_pattern
            )
            self.recorder.set_binding(
                boot.vendor_id, boot.app_name, boot.window_title_pattern
            )
        return previous

    def undo_retarget(self, previous: Optional[Tuple[str, str]]) -> None:
        """
        Restore the binding after a failed app-switching launch.

        A first launch has no prior binding (the session starts unbound,
        so ``previous`` is ``("", "")``); there is nothing to restore,
        and retargeting to an empty app name would itself raise and mask
        the real launch failure.
        """
        if previous is not None and previous[0]:
            self.surface.retarget(*previous)
            if self.state.current_binding is not None:
                self.recorder.set_binding(*self.state.current_binding)

    def commit_binding(
        self,
        boot: Optional[bstrap.VendorBootstrap],
        args: Dict[str, object],
    ) -> None:
        """
        Adopts a successful launch's vendor binding.
        """
        if boot is not None:
            app = boot.app_name or str(args.get("app") or "")
            self.state.current_binding = (
                boot.vendor_id,
                app,
                boot.window_title_pattern,
            )
            if self.state.primary_boot is None:
                self.state.primary_boot = boot

    def build_recording(self, effective: profile.AppProfile) -> recdng.Recording:
        """
        Build the recording from the accumulated state.
        """
        recording = builder.build(
            self.recorder,
            profile=effective,
            capability_id=self.cfg.capability_id,
            capability_name=self.cfg.capability_name,
            goal=self.cfg.goal,
            inputs=self.state.params,
            outputs=self.state.extracted,
            model=self.deps.model_name,
            run_id=self.log.run_id,
            input_classes=self.state.input_classes,
            output_classes=self.state.output_classes,
        )
        return recording

    # ── the loop ───────────────────────────────────────────────────────

    def run(
        self,
    ) -> Union[config.DiscoveryResult, config.DiscoveryFailure]:
        """
        Run the discovery loop to a typed result.
        """
        if self._tenant is None:
            return config.DiscoveryFailure(
                f'unknown tenant "{self.cfg.tenant}"',
                failure_class="precondition_failed",
            )
        self._seed_input_classes()
        if not self.cfg.bootstrap:
            entry_failure = self._entry_launch()
            if entry_failure is not None:
                return entry_failure
        self.log.emit(
            events.DiscoveryStarted(
                goal=self.cfg.goal,
                inputs=self.cfg.inputs,
                model=self.deps.model_name,
                summary=f"goal: {self.cfg.goal}",
            )
        )
        for turn in range(1, self.cfg.max_turns + 1):
            finished = self._turn(turn)
            if finished is not None:
                return finished
        return config.DiscoveryFailure(
            f"max turns ({self.cfg.max_turns}) reached without goal_complete"
        )

    def _seed_input_classes(self) -> None:
        """
        Classify the pre-seeded inputs and redact any that are sensitive.
        """
        self.state.params = dict(self.cfg.inputs)
        for name, value in self.state.params.items():
            data_class = sensv.classify(name=name, value=value)
            self.state.input_classes[name] = data_class
            if sensv.is_sensitive(data_class):
                self.log.redactor.add_secret(value)

    def _entry_launch(self) -> Optional[config.DiscoveryFailure]:
        """
        Profile mode: the entry point is part of the task definition.
        """
        cfg = self.cfg
        self.state.current_binding = (
            cfg.profile.vendor_id,
            cfg.profile.app_name,
            cfg.profile.window_title_pattern,
        )
        self.recorder.set_binding(*self.state.current_binding)
        path = self.entry_path or "/"
        entry_url = f"{self.base_url}{path}" if self.base_url else None
        entry = actions.SurfaceAction(
            kind="launch",
            app=cfg.profile.app_name,
            url=entry_url,
            step="entry",
        )
        try:
            outcome = approval.perform_gated(
                self.surface,
                entry,
                approver=self.approver,
                log=self.log,
                run_id=self.log.run_id,
            )
            self.state.grants.extend(outcome.grants)
        except errors.ApprovalDeniedError as denied:
            return config.DiscoveryFailure(
                f"entry launch not approved ({denied.decision.by}): "
                f"{denied.request.summary}",
                failure_class="approval_denied",
            )
        self.state.screen = self.surface.snapshot()
        self.recorder.start(self.state.screen.window_title)
        self.recorder.record(
            action=graph.Action(
                kind="launch", app=cfg.profile.app_name, url=path
            ),
            target_control=None,
            description=(
                f"open {cfg.profile.vendor_id} in {cfg.profile.app_name}"
            ),
            risk="safe",
            pre_title=self.state.screen.window_title,
            post_title=self.state.screen.window_title,
        )
        return None

    def _turn(
        self, turn: int
    ) -> Optional[Union[config.DiscoveryResult, config.DiscoveryFailure]]:
        """
        Run one observe-decide-act turn; return a result once finished.
        """
        self.state.messages.append(self._user_message(turn))
        completed = self._complete_with_retry()
        if isinstance(completed, config.DiscoveryFailure):
            return completed
        self.state.messages.append(
            mlllm.ChatMessage(
                role="assistant",
                content=completed.content,
                tool_calls=completed.tool_calls,
            )
        )
        calls = list(completed.tool_calls)
        if not calls:
            self.state.messages.append(
                mlllm.ChatMessage(
                    role="user",
                    content="You must call exactly one tool each turn.",
                )
            )
            return None
        outcome = self._dispatch(calls[0], turn)
        replies: List[Tuple[str, str]] = []
        if outcome.reply is not None:
            replies.append((calls[0].id, outcome.reply))
        for extra in calls[1:]:
            replies.append(
                (
                    extra.id,
                    "Not executed: exactly one tool call per turn. "
                    "Re-issue it next turn if needed.",
                )
            )
        for call_id, text in replies:
            self.state.messages.append(
                mlllm.ChatMessage(role="tool", content=text, tool_call_id=call_id)
            )
        return outcome.finished

    def _recognized_state(self) -> str:
        """
        Return a one-line anchor when the screen matches a mapped state.

        Localizes the current screen against the app's existing graph so
        the agent knows where it already is (e.g. past login) and skips
        the steps that lead here. Empty on a first/bootstrap run, or
        when the screen matches nothing known.
        """
        known, screen = self.cfg.known_graph, self.state.screen
        node_id = (
            localize.locate(screen, known, self.cfg.inputs)
            if known is not None and screen is not None
            else None
        )
        title = (
            _node_title(known.node(node_id))
            if node_id is not None and known is not None
            else ""
        )
        line = ""
        if title and node_id is not None and screen is not None:
            steps = self._known_next_steps(node_id)
            self._note_recognition(node_id, screen.window_title, title, steps)
            line = (
                f"RECOGNIZED STATE: this screen matches a mapped state "
                f'"{title}"; you are already here, so skip the steps that '
                "lead to it."
            )
            if steps:
                line += (
                    f" Actions already mapped from here (reuse them for a "
                    f"consistent recording): {steps}."
                )
            line += "\n\n"
        return line

    def _note_recognition(
        self, node_id: str, window: str, title: str, steps: str
    ) -> None:
        """
        Log a localization the first time a mapped state is recognized.

        Makes the agent-facing recognition hint visible in the run's
        evidence, and only once per distinct node so re-observing the
        same state does not flood the timeline.
        """
        if node_id != self._recognized_node:
            self._recognized_node = node_id
            extra = f"; next: {steps}" if steps else ""
            self.log.emit(
                events.Localized(
                    node=node_id,
                    window=window,
                    summary=(
                        f'discovery recognized mapped state "{title}"{extra}'
                    ),
                )
            )

    def _known_next_steps(self, node_id: str) -> str:
        """
        Up to three distinct edge descriptions leaving ``node_id``.

        Hints only - the goal is unknown at discovery, so these are moves
        already recorded from this state, not a claimed route to the goal.
        """
        known = self.cfg.known_graph
        seen: List[str] = []
        if known is not None:
            for edge in known.edges_from(node_id):
                text = edge.description.strip()
                if text and text not in seen:
                    seen.append(text)
                if len(seen) >= 3:
                    break
        steps = "; ".join(seen)
        return steps

    def _user_message(self, turn: int) -> mlllm.ChatMessage:
        """
        Build the per-turn user message: goal, inputs, screen, screenshot.
        """
        state = self.state
        shot = ""
        if self.cfg.screenshots and state.screen is not None:
            shot = self.log.screenshot(self.surface, f"turn-{turn}")
        self._last_screenshot = shot
        screen_text = (
            digest.render_digest(state.screen)
            if state.screen is not None
            else "(no window is bound yet - your first action must be a launch)"
        )
        parts: List[mlllm.ContentPart] = [
            mlllm.ContentPart(
                type="text",
                text=(
                    f"GOAL: {self.cfg.goal}\n{state.inputs_block()}\n\n"
                    f"{self._recognized_state()}"
                    f"Current screen:\n{screen_text}"
                ),
            )
        ]
        if shot:
            # A fresh screenshot: attach it and clear the blind-turn count.
            encoded = base64.b64encode(
                (self.log.dir / shot).read_bytes()
            ).decode()
            parts.append(
                mlllm.ContentPart(
                    type="image_url",
                    image_url=f"data:image/png;base64,{encoded}",
                )
            )
            self._blind_turns = 0
        elif self.cfg.screenshots and state.screen is not None:
            # Wanted a screenshot but got none: track consecutive blind turns.
            self._blind_turns += 1
            if self._blind_turns == _BLIND_TURN_WARNING:
                _LOG.warning(
                    "discovery is running blind - %d turns without a "
                    "screenshot; check Screen Recording permission for the "
                    "driver daemon",
                    _BLIND_TURN_WARNING,
                )
        message = mlllm.ChatMessage(role="user", content=tuple(parts))
        return message

    def _complete_with_retry(
        self,
    ) -> Union[mlllm.LlmTurn, config.DiscoveryFailure]:
        """
        Call the model, retrying retryable errors up to the deps' bound.
        """
        conversation = [
            mlllm.ChatMessage(role="system", content=self._system_prompt),
            *self.state.messages,
        ]
        last_error = ""
        for attempt in range(self.deps.llm_retries):
            try:
                return self.deps.llm.complete(
                    conversation, tools=prompt.TOOL_SCHEMAS
                )
            except errors.LlmError as err:
                last_error = str(err)
                if not err.retryable:
                    break
                self.log.emit(
                    events.SurfaceError(
                        error=last_error,
                        summary=(
                            f"LLM call failed (attempt {attempt + 1}/"
                            f"{self.deps.llm_retries}); retrying"
                        ),
                    )
                )
                time.sleep(self.deps.retry_base_delay_s * (attempt + 1))
        return config.DiscoveryFailure(
            f"LLM call failed after {self.deps.llm_retries} attempts: "
            f"{last_error}",
            failure_class="llm_failed",
        )

    def _dispatch(self, call: mlllm.ToolCall, turn: int) -> tools.ToolOutcome:
        """
        Route one tool call to its handler and return the outcome.
        """
        try:
            args: Dict[str, object] = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as err:
            return tools.ToolOutcome(f"Tool arguments were not valid JSON: {err}")
        if call.name == "declare_input":
            return tools.handle_declare_input(self, args)
        if call.name == "clarify":
            return tools.handle_clarify(self, args)
        if call.name == "request_secret":
            return tools.handle_request_secret(self, args)
        if call.name == "extract":
            return tools.handle_extract(self, args)
        if call.name == "goal_complete":
            return tools.handle_goal_complete(self, args, turn)
        if call.name == "give_up":
            return tools.handle_give_up(self, args, self._last_screenshot)
        if call.name == "act":
            return tools.handle_act(self, args, turn)
        return tools.ToolOutcome(f'Unknown tool "{call.name}".')


def run_discovery(
    cfg: config.DiscoveryConfig, deps: DiscoveryDeps
) -> Union[config.DiscoveryResult, config.DiscoveryFailure]:
    """
    Run one discovery session to a typed result.
    """
    outcome = DiscoverySession(cfg, deps).run()
    return outcome
