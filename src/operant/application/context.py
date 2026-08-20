"""
Per-run wiring shared by the CLI and the server: log, surface, broker.

``RunContext`` replaces the old monolithic ``Runtime``: it builds the
evidence log, the actuation surface (local or driver-backed), the
control broker, and an approver, and tears them down. It starts no HTTP
server - the operator console is the server layer's job now - so the
same context serves an interactive CLI run and a server-managed one.

Import as:

import operant.application.context as context
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Any, Dict, List, Optional, Protocol

import operant.application.escalation as escal
import operant.domain.approval as approval
import operant.domain.events as events
import operant.domain.models.actions as actions
import operant.domain.profile as dpprofil
import operant.domain.redaction as redact
import operant.helpers.ids as ids
import operant.infra.evidence.run_log as run_log
import operant.infra.settings as issettin
import operant.ports.hitl as hitl
import operant.ports.surface as pssurfac

# #############################################################################
# RunContext
# #############################################################################


@dataclasses.dataclass
class RunContext:
    """
    A wired run: evidence log, surface, broker, and approver.

    :ivar run_id: The run's id and evidence directory name.
    :ivar settings: The settings this run was built from.
    :ivar redactor: Masks secrets before they are logged.
    :ivar log: The evidence sink.
    :ivar surface: The actuation surface (local or driver-backed).
    :ivar health_table: Returns per-tool health rows.
    :ivar broker: Control broker for human hand-offs.
    :ivar approver: Who answers approval questions.
    :ivar approval_cache: Remember-for-run answers, owned by this run.
    """

    run_id: str
    settings: issettin.OperantSettings
    redactor: redact.Redactor
    log: run_log.RunLog
    surface: pssurfac.Surface
    health_table: collections.abc.Callable[[], List[Dict[str, Any]]]
    broker: escal.ControlBroker
    approver: hitl.Approver
    approval_cache: Dict[str, approval.ApprovalDecision] = dataclasses.field(
        default_factory=dict
    )

    def __enter__(self) -> RunContext:
        """
        Enter the context so ``with`` guarantees teardown.
        """
        return self

    def __exit__(self, *exc: object) -> None:
        """
        Tear the run down.
        """
        self.close()

    def close(self) -> None:
        """
        Release the surface; the driver daemon persists deliberately.
        """
        self.surface.close()


# #############################################################################
# ContextBuilder
# #############################################################################


class ContextBuilder(Protocol):
    """
    Anything that can wire a run context; tests supply a fake.
    """

    def build(
        self,
        kind: str,
        profile: dpprofil.AppProfile,
        *,
        approver: Optional[hitl.Approver] = None,
        run_identifier: Optional[str] = None,
    ) -> RunContext:
        """
        Wire a run context for ``profile``.
        """
        ...


# #############################################################################
# RunContextFactory
# #############################################################################


class RunContextFactory:
    """
    Build run contexts from settings, choosing the transport.
    """

    def __init__(self, settings: issettin.OperantSettings) -> None:
        self._settings = settings

    def build(
        self,
        kind: str,
        profile: dpprofil.AppProfile,
        *,
        approver: Optional[hitl.Approver] = None,
        run_identifier: Optional[str] = None,
    ) -> RunContext:
        """
        Wire a run context for ``profile``.

        :param kind: Run kind (``discovery`` / ``replay`` / ``drive``).
        :param profile: The app profile the run executes under.
        :param approver: Overrides the default approver (the server
            injects a UI-backed one); ``None`` uses deny-by-default.
        :param run_identifier: Override the generated run id.
        :return: The wired context.
        """
        import operant.adapters.http.factory as factory

        # Wire the log, surface, broker, and approver for this run.
        run_identifier = run_identifier or ids.run_id(kind)
        redactor = redact.redactor_from_env(_environ())
        log = run_log.RunLog(
            self._settings.paths.evidence_dir, run_identifier, redactor
        )
        surface, health_table = factory.surface_for(
            app_name=profile.app_name,
            window_title_pattern=profile.window_title_pattern,
            policy=profile.policy,
            on_event=lambda event: _log_event(log, event),
            on_decision=lambda decision, action: _log_decision(
                log, decision, action
            ),
            settings=self._settings,
            fault_injection=profile.fault_injection,
        )
        broker = escal.ControlBroker(
            start_human_capture=surface.start_human_capture,
            stop_human_capture=surface.stop_human_capture,
            on_transition=lambda a, b, detail: _log_transition(log, a, b, detail),
        )
        cache: Dict[str, approval.ApprovalDecision] = {}
        context = RunContext(
            run_id=run_identifier,
            settings=self._settings,
            redactor=redactor,
            log=log,
            surface=surface,
            health_table=health_table,
            broker=broker,
            approver=approver or _deny_all(),
            approval_cache=cache,
        )
        return context


def parse_inputs(pairs: List[str]) -> Dict[str, str]:
    """
    Parse ``key=value`` CLI inputs into a mapping.

    :param pairs: The ``key=value`` strings given on the command line.
    :return: The parsed inputs keyed by name.
    :raises ValueError: If a pair has no ``=``.
    """
    parsed: Dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise ValueError(f'--input must be key=value, got "{pair}"')
        parsed[key] = value
    return parsed


def _deny_all() -> hitl.Approver:
    """
    Build the deny-by-default approver.
    """
    import operant.application.approval as aaapprov

    approver = aaapprov.DenyAllApprover()
    return approver


def _environ() -> Dict[str, str]:
    """
    Snapshot the process environment as a plain dict.
    """
    import os

    environ = dict(os.environ)
    return environ


def _log_event(log: run_log.RunLog, event: Dict[str, Any]) -> None:
    """
    Log one gateway action event.
    """
    data = {k: v for k, v in event.items() if k != "type"}
    log.event(
        event.get("type", "gateway_action"),
        **data,
        summary=f"{event.get('tool')}: {event.get('action')} -> "
        f"{event.get('status', event.get('reason', ''))}",
    )


def _log_decision(
    log: run_log.RunLog,
    decision: approval.PolicyDecision,
    action: actions.SurfaceAction,
) -> None:
    """
    Log one policy-check decision.
    """
    log.event(
        "policy_check",
        allowed=decision.allowed,
        risk=decision.risk,
        reason=decision.reason,
        action=action.kind,
        target=action.target_text,
        verdict=decision.verdict,
        approval_kind=decision.approval.kind if decision.approval else None,
        summary=f"policy {decision.verdict} {action.kind} ({decision.risk})",
    )


def _log_transition(
    log: run_log.RunLog, before: str, after: str, detail: str
) -> None:
    """
    Log one control-transfer transition.
    """
    log.emit(
        events.ControlTransition.model_validate(
            {
                "from": before,
                "to": after,
                "detail": detail,
                "summary": f"control: {before} -> {after} ({detail})",
            }
        )
    )
