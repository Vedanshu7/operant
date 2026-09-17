"""
Run-tracking records the run repository stores.

These are the durable rows behind a run: its lifecycle status, the index
of its evidence events, the approvals, interventions, and clarifications
opened during it, and the audit trail. They are plain frozen
dataclasses; the evidence log remains the source of truth and these rows
exist so the API can list and query without reading logs.

Import as:

import operant.domain.models.runs as runs
"""

from __future__ import annotations

import dataclasses
from typing import Dict, FrozenSet, List, Literal, Optional

import operant.domain.models.results as results
import operant.domain.secrets as secrets

RunKind = Literal["discovery", "replay"]

RunStatus = Literal[
    "queued",
    "waiting_driver",
    "running",
    "waiting_approval",
    "waiting_intervention",
    "waiting_clarification",
    "succeeded",
    "business_outcome",
    "escalated",
    "failed",
    "cancelled",
]

TERMINAL_STATUSES: FrozenSet[str] = frozenset(
    {"succeeded", "business_outcome", "escalated", "failed", "cancelled"}
)

InterventionState = Literal[
    "paused", "human", "resumed", "abandoned", "timed_out"
]


# #############################################################################
# RunRecord
# #############################################################################


@dataclasses.dataclass(frozen=True)
class RunRecord:
    """
    One run of discovery or replay.

    :ivar id: run id; also the evidence directory name.
    :ivar kind: ``discovery`` or ``replay``.
    :ivar status: current lifecycle status.
    :ivar vendor_id: application graph the run drives.
    :ivar capability_id: capability replayed or discovered, when known.
    :ivar tenant: tenant binding in use.
    :ivar goal: natural-language goal (discovery) or capability name.
    :ivar evidence_dir: directory holding the run's evidence.
    :ivar created_at: ISO timestamp the run was created.
    :ivar updated_at: ISO timestamp of the last status change.
    :ivar started_at: ISO timestamp the run began executing.
    :ivar finished_at: ISO timestamp the run reached a terminal state.
    :ivar inputs: task inputs as supplied, sensitive values redacted.
    :ivar result: final replay result once the run finished.
    :ivar error: error text when the run stopped on an exception.
    """

    id: str
    kind: RunKind
    status: RunStatus
    vendor_id: str
    capability_id: Optional[str] = None
    tenant: str = ""
    goal: str = ""
    evidence_dir: str = ""
    created_at: str = ""
    updated_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    inputs: Dict[str, str] = dataclasses.field(default_factory=dict)
    result: Optional[results.ReplayResult] = None
    error: Optional[str] = None


# #############################################################################
# RunFilter
# #############################################################################


@dataclasses.dataclass(frozen=True)
class RunFilter:
    """
    Criteria for listing runs; every ``None`` means "any".

    :ivar status: restrict to one lifecycle status.
    :ivar kind: restrict to discovery or replay.
    :ivar vendor_id: restrict to one application.
    :ivar capability_id: restrict to one capability.
    :ivar limit: maximum rows to return.
    :ivar offset: rows to skip, newest first.
    """

    status: Optional[RunStatus] = None
    kind: Optional[RunKind] = None
    vendor_id: Optional[str] = None
    capability_id: Optional[str] = None
    limit: int = 50
    offset: int = 0


# #############################################################################
# StreamedEvent
# #############################################################################


@dataclasses.dataclass(frozen=True)
class StreamedEvent:
    """
    A replayable stream event, rebuilt from the event index.

    :ivar run_id: run the event belongs to.
    :ivar seq: position in the run's stream.
    :ivar type: event type name.
    :ivar at: ISO timestamp the event was logged.
    :ivar summary: one-line human summary.
    :ivar data: structured payload, empty when none was indexed.
    :ivar screenshot: screenshot file name, when the event carries one.
    """

    run_id: str
    seq: int
    type: str
    at: str
    summary: str
    data: Dict[str, object] = dataclasses.field(default_factory=dict)
    screenshot: Optional[str] = None


# #############################################################################
# InterventionRequest
# #############################################################################


@dataclasses.dataclass(frozen=True)
class InterventionRequest:
    """
    What a run asked a human to take over.

    :ivar kind: ``discovery`` or ``replay``.
    :ivar capability: capability id or name the run is working on.
    :ivar goal: what the run is trying to achieve.
    :ivar reason: why a human is needed.
    :ivar page_title: window title when the request was raised.
    :ivar edge_id: edge the run was on, when replaying.
    :ivar screenshot_file: evidence screenshot captured at escalation.
    :ivar raised_at: ISO timestamp the request was raised.
    """

    kind: RunKind
    capability: str
    goal: str
    reason: str
    page_title: str = ""
    edge_id: Optional[str] = None
    screenshot_file: Optional[str] = None
    raised_at: str = ""


# #############################################################################
# AuditEntry
# #############################################################################


@dataclasses.dataclass(frozen=True)
class AuditEntry:
    """
    One line of the governance audit trail.

    :ivar at: ISO timestamp of the action.
    :ivar actor: who acted (user name, ``system``, ``scheduler``).
    :ivar action: what happened, e.g. ``approve_artifact``.
    :ivar subject: what it happened to, e.g. a capability id.
    :ivar run_id: run the action relates to, when any.
    :ivar detail: extra key/value context safe to persist.
    """

    at: str
    actor: str
    action: str
    subject: str
    run_id: Optional[str] = None
    detail: Dict[str, str] = dataclasses.field(default_factory=dict)


# #############################################################################
# SecretRefMeta
# #############################################################################


@dataclasses.dataclass(frozen=True)
class SecretRefMeta:
    """
    A declared secret reference: where a value lives, never the value.

    :ivar name: reference name used by tenant bindings.
    :ivar backend: store that resolves the locator.
    :ivar locator: backend-specific address.
    :ivar description: what the secret is for.
    :ivar updated_at: ISO timestamp of the last change.
    """

    name: str
    backend: secrets.SecretBackend
    locator: str
    description: str = ""
    updated_at: str = ""


ApprovalStatus = Literal["pending", "approved", "denied", "timed_out"]
ClarificationStatus = Literal["pending", "answered", "timed_out"]


# #############################################################################
# ApprovalRecord
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ApprovalRecord:
    """
    A stored approval question and its decision.

    :ivar id: approval id (``<run_id>/approval-<n>``).
    :ivar run_id: run the approval belongs to.
    :ivar kind: approval gate that raised it.
    :ivar summary: one-line description safe to show.
    :ivar step: edge id the request belongs to, when any.
    :ivar action_kind: kind of the action that raised it.
    :ivar app: application the action targets.
    :ivar details: printable context (values already previewed).
    :ivar proposed_grants: grants that would lift a scope block.
    :ivar status: lifecycle status.
    :ivar decided_by: channel that answered, when decided.
    :ivar remember: whether the answer applies once or for the run.
    :ivar note: free-text remark from the approver.
    :ivar raised_at: ISO timestamp raised.
    :ivar decided_at: ISO timestamp decided, when decided.
    """

    id: str
    run_id: str
    kind: str
    summary: str
    action_kind: str
    status: ApprovalStatus
    step: Optional[str] = None
    app: Optional[str] = None
    details: Dict[str, str] = dataclasses.field(default_factory=dict)
    proposed_grants: List[Dict[str, str]] = dataclasses.field(
        default_factory=list
    )
    decided_by: Optional[str] = None
    remember: Optional[str] = None
    note: Optional[str] = None
    raised_at: str = ""
    decided_at: Optional[str] = None


# #############################################################################
# InterventionRecord
# #############################################################################


@dataclasses.dataclass(frozen=True)
class InterventionRecord:
    """
    A stored control-transfer request and its lifecycle.

    :ivar id: intervention id.
    :ivar run_id: run the intervention belongs to.
    :ivar reason: why a human was needed.
    :ivar page_title: window title when raised.
    :ivar edge_id: edge the run was on, when replaying.
    :ivar screenshot_file: evidence screenshot captured at escalation.
    :ivar state: lifecycle state.
    :ivar note: operator remark.
    :ivar human_actions: actions the human took while in control.
    :ivar raised_at: ISO timestamp raised.
    :ivar taken_at: ISO timestamp control was taken, when taken.
    :ivar resolved_at: ISO timestamp resolved, when resolved.
    """

    id: str
    run_id: str
    reason: str
    state: InterventionState
    page_title: Optional[str] = None
    edge_id: Optional[str] = None
    screenshot_file: Optional[str] = None
    note: Optional[str] = None
    human_actions: List[str] = dataclasses.field(default_factory=list)
    raised_at: str = ""
    taken_at: Optional[str] = None
    resolved_at: Optional[str] = None


# #############################################################################
# ClarificationRecord
# #############################################################################


@dataclasses.dataclass(frozen=True)
class ClarificationRecord:
    """
    A stored clarifying question and its answer.

    :ivar id: clarification id.
    :ivar run_id: run the question belongs to.
    :ivar question: what the agent asked.
    :ivar answer: the human's answer, when answered.
    :ivar status: lifecycle status.
    :ivar raised_at: ISO timestamp raised.
    :ivar answered_at: ISO timestamp answered, when answered.
    """

    id: str
    run_id: str
    question: str
    status: ClarificationStatus
    answer: Optional[str] = None
    raised_at: str = ""
    answered_at: Optional[str] = None
