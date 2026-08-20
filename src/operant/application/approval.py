"""
Approvers and the one gated act step every caller uses.

The guard never acts on a ``needs_approval`` decision: it raises
``ApprovalRequiredError`` with a single-use nonce. ``perform_gated``
asks the configured ``Approver`` and retries with the nonce on a yes.
Remember-for-run lives in a caller-owned cache, never a module global,
so concurrent runs never share answers.

Import as:

import operant.application.approval as approval
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Dict, List, Optional, Tuple, Union

import operant.application.escalation as escal
import operant.domain.approval as approval
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.models.actions as actions
import operant.helpers.time as time
import operant.ports.evidence as evidence
import operant.ports.hitl as hitl
import operant.ports.surface as pssurfac

# #############################################################################
# ScriptedApprover
# #############################################################################


class ScriptedApprover:
    """
    A test approver that returns queued answers in order.
    """

    def __init__(
        self,
        answers: collections.abc.Iterable[Union[bool, approval.ApprovalDecision]],
    ) -> None:
        self._answers = list(answers)
        self.asked: List[approval.ApprovalRequest] = []

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Record the request and returns the next scripted answer.
        """
        self.asked.append(request)
        if not self._answers:
            # Script ran out: deny by default.
            decision = approval.ApprovalDecision(
                approved=False, by="scripted", note="script exhausted"
            )
        else:
            # Answers remain: take the next scripted one.
            answer = self._answers.pop(0)
            if isinstance(answer, approval.ApprovalDecision):
                decision = answer
            else:
                decision = approval.ApprovalDecision(
                    approved=answer, by="scripted"
                )
        return decision


# #############################################################################
# DenyAllApprover
# #############################################################################


class DenyAllApprover:
    """
    The library default: denies everything (no channel configured).
    """

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Deny ``request`` with the denied-by-default channel.
        """
        decision = approval.ApprovalDecision(
            approved=False,
            by="denied-by-default",
            note="no approval channel configured",
        )
        return decision


# #############################################################################
# BrokerApprover
# #############################################################################


class BrokerApprover:
    """
    Route the question to the operator console via the control broker.
    """

    def __init__(
        self,
        broker: escal.ControlBroker,
        timeout_s: float,
        *,
        run_id: str = "",
    ) -> None:
        self._broker = broker
        self.timeout_s = timeout_s
        self.run_id = run_id

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Block on the console; a timeout counts as a denial.
        """
        decision = self._broker.request_approval(
            self.run_id, request, self.timeout_s
        )
        if decision is None:
            decision = approval.ApprovalDecision(
                approved=False,
                by="timeout",
                note=f"no answer within {self.timeout_s:.0f}s",
            )
        return decision


# #############################################################################
# RememberingApprover
# #############################################################################


class RememberingApprover:
    """
    Caches "for this process" answers by fingerprint; denials never cache.

    The cache is supplied by the caller (a run owns its own), so answers
    are never shared across concurrent runs.
    """

    def __init__(
        self,
        inner: hitl.Approver,
        cache: Dict[str, approval.ApprovalDecision],
    ) -> None:
        self.inner = inner
        self.cache = cache

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Return a cached yes, else asks ``inner`` and caches a yes.
        """
        hit = self.cache.get(request.fingerprint) if request.fingerprint else None
        if hit is not None and hit.approved:
            # A cached yes: reuse it without asking again.
            decision = approval.ApprovalDecision(
                approved=True,
                remember="process",
                by="cache",
                note=f"remembered ({hit.by})",
            )
        else:
            # No cached yes: ask inner and cache a remembered yes.
            decision = self.inner.ask(request)
            if (
                decision.approved
                and decision.remember == "process"
                and request.fingerprint
            ):
                self.cache[request.fingerprint] = decision
        return decision


# #############################################################################
# GatedOutcome
# #############################################################################


@dataclasses.dataclass
class GatedOutcome:
    """
    The result of a gated action.

    :ivar result: Whatever ``surface.perform`` returned.
    :ivar grants: Scope grants applied during the round-trip.
    :ivar decisions: Every (request, decision) pair, in order.
    :ivar waited_s: Seconds a human held the run; replay deadlines
        exclude this so thinking time never times a run out.
    """

    result: object
    grants: List[approval.ScopeGrant] = dataclasses.field(default_factory=list)
    decisions: List[
        Tuple[approval.ApprovalRequest, approval.ApprovalDecision]
    ] = dataclasses.field(default_factory=list)
    waited_s: float = 0.0


def perform_gated(
    surface: pssurfac.Surface,
    action: actions.SurfaceAction,
    *,
    approver: hitl.Approver,
    log: Optional[evidence.EvidenceSink] = None,
    run_id: str = "",
) -> GatedOutcome:
    """
    Perform ``action`` with the approval round-trip.

    :param surface: The surface to act on.
    :param action: The action to perform.
    :param approver: Who answers an approval question.
    :param log: Evidence sink for the request/resolution events.
    :param run_id: Run id stamped on any scope grant.
    :return: The gated outcome, including any scope grants and wait
        time.
    :raises RuntimeError: If approval never converges after three
        attempts.
    """
    outcome = GatedOutcome(result=None)
    nonce: Optional[str] = None
    for _ in range(3):
        try:
            outcome.result = surface.perform(action, approval=nonce)
            return outcome
        except errors.ApprovalRequiredError as need:
            decision = _ask(need.request, approver, outcome, log)
            if not decision.approved:
                raise errors.ApprovalDeniedError(need.request, decision) from None
            if need.request.kind == "scope":
                _apply_grants(surface, need.request, outcome, log, run_id)
            nonce = need.nonce
    raise RuntimeError(f"approval for {action.kind} did not converge")


def _ask(
    request: approval.ApprovalRequest,
    approver: hitl.Approver,
    outcome: GatedOutcome,
    log: Optional[evidence.EvidenceSink],
) -> approval.ApprovalDecision:
    """
    Ask the approver, logging the request and its resolution.
    """
    if log is not None:
        log.emit(
            events.ApprovalRequested(
                kind=request.kind,
                question=request.summary,
                fingerprint=request.fingerprint,
                step=request.step or None,
                details=dict(request.details),
                summary=f"approval needed ({request.kind}): {request.summary}",
            )
        )
    started = time.monotonic()
    decision = approver.ask(request)
    outcome.waited_s += time.monotonic() - started
    outcome.decisions.append((request, decision))
    if log is not None:
        verb = "APPROVED" if decision.approved else "DENIED"
        note = f": {decision.note}" if decision.note else ""
        log.emit(
            events.ApprovalResolved(
                kind=request.kind,
                approved=decision.approved,
                by=decision.by,
                remembered=decision.remember == "process",
                fingerprint=request.fingerprint,
                note=decision.note,
                summary=f"{request.kind} {verb} by {decision.by}{note}",
            )
        )
    return decision


def _apply_grants(
    surface: pssurfac.Surface,
    request: approval.ApprovalRequest,
    outcome: GatedOutcome,
    log: Optional[evidence.EvidenceSink],
    run_id: str,
) -> None:
    """
    Apply each proposed scope grant and log it.
    """
    now = time.iso_now()
    for proposed in request.proposed_grants:
        grant = proposed.model_copy(
            update={
                "reason": request.summary,
                "run_id": run_id,
                "granted_at": now,
            }
        )
        surface.grant_scope(grant)
        outcome.grants.append(grant)
        if log is not None:
            value = request.details.get("url") or request.details.get("app", "")
            log.emit(
                events.ScopeGranted(
                    kind=grant.kind,
                    pattern=grant.pattern,
                    value=value,
                    reason=request.summary,
                    summary=f"scope granted ({grant.kind}): {grant.pattern}",
                )
            )
