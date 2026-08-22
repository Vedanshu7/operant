import pathlib
import time
from typing import Dict, List, Optional

import pytest

import operant.application.approval
import operant.application.escalation
import operant.domain.approval as daapprov
import operant.domain.errors as errors
import operant.domain.models.actions as actions
import operant.domain.redaction as redact
import operant.infra.evidence.run_log as run_log


def req(
    kind: str = "sensitive_fill", fp: str = "fp1", grants: tuple = ()
) -> daapprov.ApprovalRequest:
    return daapprov.ApprovalRequest(
        kind=kind,
        summary='fill "Password" with [credential, 7 chars]',
        details={"field": "Password", "data_class": "credential"},
        fingerprint=fp,
        action_kind="fill",
        proposed_grants=tuple(grants),
    )


def _broker() -> operant.application.escalation.ControlBroker:
    return operant.application.escalation.ControlBroker(
        start_human_capture=lambda cb: None,
        stop_human_capture=lambda: None,
        on_transition=lambda a, b, d: None,
    )


def _log(tmp_path: pathlib.Path) -> run_log.RunLog:
    return run_log.RunLog(tmp_path, "r", redact.Redactor(), echo=False)


def _lines(tmp_path: pathlib.Path) -> List[dict]:
    return run_log.read_entries(tmp_path / "r" / "run-log.jsonl")


def test_scripted_records_and_denies_when_exhausted() -> None:
    approver = operant.application.approval.ScriptedApprover(
        [
            True,
            daapprov.ApprovalDecision(approved=True, remember="process"),
        ]
    )
    assert approver.ask(req()).approved
    assert approver.ask(req()).remember == "process"
    assert not approver.ask(req()).approved
    assert len(approver.asked) == 3


def test_deny_all_is_the_library_default() -> None:
    decision = operant.application.approval.DenyAllApprover().ask(req())
    assert not decision.approved and decision.by == "denied-by-default"


def test_remembering_caches_only_process_approvals() -> None:
    inner = operant.application.approval.ScriptedApprover(
        [
            daapprov.ApprovalDecision(approved=True, remember="process"),
            True,
            False,
        ]
    )
    cache: Dict[str, daapprov.ApprovalDecision] = {}
    remembering = operant.application.approval.RememberingApprover(
        inner, cache=cache
    )
    assert remembering.ask(req(fp="a")).by == "scripted"
    again = remembering.ask(req(fp="a"))
    assert again.approved and again.by == "cache"
    assert len(inner.asked) == 1
    once = remembering.ask(req(fp="b"))
    assert once.approved and once.remember == "once"
    third = remembering.ask(req(fp="b"))
    assert third.by == "scripted" and not third.approved
    assert list(cache) == ["a"]


def test_broker_resolved_from_the_console() -> None:
    broker = _broker()
    import threading

    def console() -> None:
        while broker.pending_approval is None:
            time.sleep(0.005)
        pending = broker.pending_approval
        broker.resolve_approval(pending.id, True, "process", "looks fine")

    threading.Thread(target=console).start()
    decision = operant.application.approval.BrokerApprover(
        broker, timeout_s=5, run_id="run"
    ).ask(req())
    assert decision.approved and decision.by == "console"
    assert decision.remember == "process" and decision.note == "looks fine"
    assert broker.pending_approval is None


def test_broker_timeout_clears_the_slot() -> None:
    broker = _broker()
    decision = operant.application.approval.BrokerApprover(
        broker, timeout_s=0.05
    ).ask(req())
    assert not decision.approved and decision.by == "timeout"
    with pytest.raises(errors.UnknownApprovalError):
        broker.resolve_approval("approval-1", True)


# #############################################################################
# GateOnce
# #############################################################################


class GateOnce:
    """
    A surface demanding approval until the right nonce comes back.
    """

    def __init__(self, request: daapprov.ApprovalRequest) -> None:
        self.request = request
        self.performed: List[actions.SurfaceAction] = []
        self.grants: List[daapprov.ScopeGrant] = []
        self.seen_approval: List[Optional[str]] = []

    def perform(
        self, action: actions.SurfaceAction, *, approval: Optional[str] = None
    ) -> object:
        self.seen_approval.append(approval)
        if approval != "n1":
            raise errors.ApprovalRequiredError(self.request, "n1", action)
        self.performed.append(action)
        return None

    def grant_scope(self, grant: daapprov.ScopeGrant) -> None:
        self.grants.append(grant)


def test_perform_gated_approved_retries_with_the_nonce(
    tmp_path: pathlib.Path,
) -> None:
    log = _log(tmp_path)
    surface = GateOnce(req())
    out = operant.application.approval.perform_gated(
        surface,
        actions.SurfaceAction(kind="fill", ref="c1", value="secret-value"),
        approver=operant.application.approval.ScriptedApprover([True]),
        log=log,
        run_id="r",
    )
    assert surface.seen_approval == [None, "n1"]
    assert len(surface.performed) == 1 and out.decisions[0][1].approved
    types = [entry["type"] for entry in _lines(tmp_path)]
    assert types[-2:] == ["approval_requested", "approval_resolved"]
    text = (tmp_path / "r" / "run-log.jsonl").read_text()
    assert "secret-value" not in text


def test_perform_gated_denied_performs_nothing(tmp_path: pathlib.Path) -> None:
    log = _log(tmp_path)
    surface = GateOnce(req())
    with pytest.raises(errors.ApprovalDeniedError) as caught:
        operant.application.approval.perform_gated(
            surface,
            actions.SurfaceAction(kind="fill", ref="c1", value="x"),
            approver=operant.application.approval.ScriptedApprover([False]),
            log=log,
        )
    assert caught.value.request.kind == "sensitive_fill"
    assert surface.performed == [] and surface.seen_approval == [None]
    resolved = [e for e in _lines(tmp_path) if e["type"] == "approval_resolved"]
    assert resolved[0]["approved"] is False


def test_perform_gated_scope_grants_then_retries(tmp_path: pathlib.Path) -> None:
    class GrantGate(GateOnce):

        def perform(
            self, action: actions.SurfaceAction, *, approval: Optional[str] = None
        ) -> object:
            self.seen_approval.append(approval)
            if not self.grants:
                raise errors.ApprovalRequiredError(self.request, "n1", action)
            self.performed.append(action)
            return None

    log = _log(tmp_path)
    surface = GrantGate(
        req(
            kind="scope",
            grants=(daapprov.ScopeGrant(kind="app", pattern="WhatsApp"),),
        )
    )
    out = operant.application.approval.perform_gated(
        surface,
        actions.SurfaceAction(kind="launch", app="WhatsApp"),
        approver=operant.application.approval.ScriptedApprover([True]),
        log=log,
        run_id="r",
    )
    assert [g.pattern for g in surface.grants] == ["WhatsApp"]
    assert out.grants[0].run_id == "r" and out.grants[0].granted_at
    assert len(surface.performed) == 1
    assert "scope_granted" in [e["type"] for e in _lines(tmp_path)]


def test_perform_gated_counts_human_wait() -> None:
    class SlowApprover:

        def ask(
            self, request: daapprov.ApprovalRequest
        ) -> daapprov.ApprovalDecision:
            time.sleep(0.02)
            return daapprov.ApprovalDecision(approved=True)

    out = operant.application.approval.perform_gated(
        GateOnce(req()),
        actions.SurfaceAction(kind="fill", ref="c1", value="x"),
        approver=SlowApprover(),
    )
    assert out.waited_s >= 0.02
    assert isinstance(out, operant.application.approval.GatedOutcome)
