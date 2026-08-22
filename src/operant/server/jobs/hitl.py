"""
UI-backed approver and clarifier: open a DB row, stream it, block.

Both run on a worker thread. They record the question, emit it to the
run's event stream, move the run to a ``waiting_*`` status, and block on
a ``PendingAnswer`` an HTTP route fulfils. A timeout is a denial
(approver) or an empty answer (clarifier), matching the library
contracts.

Import as:

import operant.server.jobs.hitl as hitl
"""

from __future__ import annotations

import collections.abc
import dataclasses
from typing import Optional

import operant.domain.approval as approval
import operant.domain.models.runs as mrruns
import operant.domain.secrets as odsec
import operant.helpers.ids as ids
import operant.infra.repositories.runs as rrruns
import operant.server.jobs.hub as hub
import operant.server.jobs.pending as pending

Register = collections.abc.Callable[[str], pending.PendingAnswer[object]]
Emit = collections.abc.Callable[[hub.SseEnvelope], None]
SetStatus = collections.abc.Callable[[mrruns.RunStatus], None]


# #############################################################################
# UiApprover
# #############################################################################


class UiApprover:
    """
    Implement ``operant.ports.hitl.Approver`` over the DB and stream.
    """

    def __init__(
        self,
        run_id: str,
        runs: rrruns.SqlRunRepository,
        emit: Emit,
        register: Register,
        set_status: SetStatus,
        *,
        timeout_s: float,
    ) -> None:
        self._run_id = run_id
        self._runs = runs
        self._emit = emit
        self._register = register
        self._set_status = set_status
        self._timeout_s = timeout_s

    def ask(self, request: approval.ApprovalRequest) -> approval.ApprovalDecision:
        """
        Record the request, waits for a human, and returns the answer.
        """
        approval_id = self._runs.open_approval(self._run_id, request)
        answer = self._register(approval_id)
        self._set_status("waiting_approval")
        record = self._runs.get_approval(approval_id)
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="approval_requested",
                summary=f"approval needed ({request.kind}): {request.summary}",
                data={"approval": dataclasses.asdict(record)} if record else {},
                run_status="waiting_approval",
            )
        )
        answered = answer.wait(self._timeout_s)
        if isinstance(answered, approval.ApprovalDecision):
            # A human answered: persist and use their decision.
            self._resolve(approval_id, answered)
            decision = answered
        else:
            # No answer within the timeout: deny.
            decision = self._timeout(approval_id)
        return decision

    def _timeout(self, approval_id: str) -> approval.ApprovalDecision:
        """
        Build and record a denial for an approval that timed out.
        """
        decision = approval.ApprovalDecision(
            approved=False,
            by="timeout",
            note=f"no answer within {self._timeout_s:.0f}s",
        )
        self._resolve(approval_id, decision)
        return decision

    def _resolve(
        self,
        approval_id: str,
        decision: approval.ApprovalDecision,
    ) -> None:
        """
        Persist the decision, resume the run, and emit the resolution.
        """
        self._runs.decide_approval(approval_id, decision)
        self._set_status("running")
        verb = "approved" if decision.approved else "denied"
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="approval_resolved",
                summary=f"approval {verb} by {decision.by}",
                data={"approved": decision.approved, "by": decision.by},
                run_status="running",
            )
        )


# #############################################################################
# UiClarifier
# #############################################################################


class UiClarifier:
    """
    Implement ``operant.ports.hitl.Clarifier`` over the DB and stream.
    """

    def __init__(
        self,
        run_id: str,
        runs: rrruns.SqlRunRepository,
        emit: Emit,
        register: Register,
        set_status: SetStatus,
        *,
        timeout_s: float,
    ) -> None:
        self._run_id = run_id
        self._runs = runs
        self._emit = emit
        self._register = register
        self._set_status = set_status
        self._timeout_s = timeout_s

    def ask(self, question: str, *, run_id: str) -> str:
        """
        Record the question, waits for a human, returns the answer.
        """
        clarification_id = self._runs.open_clarification(self._run_id, question)
        answer = self._register(clarification_id)
        self._set_status("waiting_clarification")
        record = self._runs.get_clarification(clarification_id)
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="clarify",
                summary=f"clarify: {question}",
                data=(
                    {"clarification": dataclasses.asdict(record)}
                    if record
                    else {}
                ),
                run_status="waiting_clarification",
            )
        )
        text = answer.wait(self._timeout_s)
        resolved = text if isinstance(text, str) else ""
        self._runs.answer_clarification(clarification_id, resolved)
        self._set_status("running")
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="clarification_answered",
                summary="clarification answered",
                data={"answered": bool(resolved)},
                run_status="running",
            )
        )
        return resolved


# #############################################################################
# UiCredentialRequester
# #############################################################################


class UiCredentialRequester:
    """
    Implement ``operant.ports.hitl.CredentialRequester`` over the stream.

    The request travels as a live event only; the value the operator
    returns is delivered in-memory to the worker and NEVER persisted -
    not the value, not a locator.
    """

    def __init__(
        self,
        run_id: str,
        emit: Emit,
        register: Register,
        set_status: SetStatus,
        *,
        timeout_s: float,
    ) -> None:
        self._run_id = run_id
        self._emit = emit
        self._register = register
        self._set_status = set_status
        self._timeout_s = timeout_s

    def request(
        self, name: str, *, run_id: str, reason: str
    ) -> Optional[odsec.CredentialGrant]:
        """
        Emit a credential request, waits for the operator, returns a grant.
        """
        request_id = f"{self._run_id}~cred~{ids.nonce()}"
        answer = self._register(request_id)
        self._set_status("waiting_clarification")
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="credential_requested",
                summary=f"credential needed: {name}",
                data={"request_id": request_id, "name": name, "reason": reason},
                run_status="waiting_clarification",
            )
        )
        answered = answer.wait(self._timeout_s)
        grant = answered if isinstance(answered, odsec.CredentialGrant) else None
        self._set_status("running")
        self._emit(
            hub.SseEnvelope(
                run_id=self._run_id,
                type="credential_provided",
                summary=(
                    "credential provided"
                    if grant is not None
                    else "credential skipped"
                ),
                data={"name": name, "provided": grant is not None},
                run_status="running",
            )
        )
        return grant
