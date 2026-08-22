"""
SQLite-backed run, HITL, stability, and audit repository.

Implements ``operant.ports.repositories.RunRepository`` and
``SecretRefRepository``. The engine and discovery loop run on worker
threads and call these synchronously; SQLite serialises writers.

Import as:

import operant.infra.repositories.runs as rrruns
"""

from __future__ import annotations

import collections.abc
import json
from typing import Dict, Optional, Tuple

import sqlalchemy
import sqlalchemy.orm as orm

import operant.domain.approval as approval
import operant.domain.errors as errors
import operant.domain.events as events
import operant.domain.models.artifact as artifact
import operant.domain.models.results as results
import operant.domain.models.runs as runs
import operant.helpers.ids as ids
import operant.helpers.time as time
import operant.infra.db.engine as engine
import operant.infra.db.models as models

_HITL_TYPES = frozenset(
    {
        "approval_requested",
        "approval_resolved",
        "escalation_raised",
        "escalation_resolved",
        "control_transition",
        "clarify",
        "clarification_answered",
        "run_status",
    }
)


# #############################################################################
# SqlRunRepository
# #############################################################################


class SqlRunRepository:
    """
    Run state and human-in-the-loop rows in SQLite.
    """

    def __init__(self, database: engine.Database) -> None:
        self._db = database

    def create(self, run: runs.RunRecord) -> None:
        """
        Insert a new run.
        """
        with self._db.session() as session:
            if session.get(models.RunRow, run.id) is not None:
                raise errors.VersionConflictError(f"run {run.id!r} exists")
            session.add(_row_from_run(run))

    def update_status(
        self,
        run_id: str,
        status: runs.RunStatus,
        *,
        result: Optional[results.ReplayResult] = None,
        error: Optional[str] = None,
    ) -> None:
        """
        Move a run to ``status`` and records its result or error.
        """
        with self._db.session() as session:
            row = self._require(session, run_id)
            row.status = status
            now = time.iso_now()
            if status == "running" and not row.started_at:
                row.started_at = now
            if result is not None:
                row.result_json = result.model_dump_json()
            if error is not None:
                row.error = error
            if status in runs.TERMINAL_STATUSES and not row.finished_at:
                row.finished_at = now

    def get(self, run_id: str) -> runs.RunRecord:
        """
        Load one run.
        """
        with self._db.session() as session:
            record = _run_from_row(self._require(session, run_id))
            return record

    def list(
        self, criteria: runs.RunFilter
    ) -> collections.abc.Sequence[runs.RunRecord]:
        """
        Return runs matching ``criteria``, newest first.
        """
        statement = sqlalchemy.select(models.RunRow)
        statement = _apply_filter(statement, criteria)
        statement = (
            statement.order_by(models.RunRow.created_at.desc())
            .limit(criteria.limit)
            .offset(criteria.offset)
        )
        with self._db.session() as session:
            rows = session.execute(statement).scalars().all()
            records = [_run_from_row(row) for row in rows]
            return records

    def index_event(self, run_id: str, event: events.BaseEvent) -> None:
        """
        Add an evidence event to the queryable index.
        """
        payload = event.model_dump(by_alias=True, exclude={"seq", "at"})
        with self._db.session() as session:
            # Find the last sequence used for this run.
            existing = session.execute(
                sqlalchemy.select(
                    sqlalchemy.func.max(models.RunEventRow.seq)
                ).where(models.RunEventRow.run_id == run_id)
            ).scalar()
            # Append the event at the next sequence.
            session.add(
                models.RunEventRow(
                    run_id=run_id,
                    seq=(existing + 1) if existing is not None else 0,
                    type=event.type,
                    at=time.iso_now(),
                    summary=str(event.summary or ""),
                    screenshot_file=payload.get("file"),
                    payload_json=(
                        json.dumps(payload) if event.type in _HITL_TYPES else None
                    ),
                )
            )

    def open_approval(
        self, run_id: str, request: approval.ApprovalRequest
    ) -> str:
        """
        Record a pending approval and returns its id.
        """
        approval_id = f"{run_id}~{ids.short_id('approval')}"
        with self._db.session() as session:
            session.add(
                models.ApprovalRow(
                    id=approval_id,
                    run_id=run_id,
                    kind=request.kind,
                    summary=request.summary,
                    fingerprint=request.fingerprint,
                    step=request.step or None,
                    action_kind=request.action_kind,
                    app=request.app,
                    details_json=json.dumps(dict(request.details)),
                    proposed_grants_json=json.dumps(
                        [
                            g.model_dump(mode="json")
                            for g in request.proposed_grants
                        ]
                    ),
                    status="pending",
                    raised_at=time.iso_now(),
                )
            )
        return approval_id

    def decide_approval(
        self, approval_id: str, decision: approval.ApprovalDecision
    ) -> None:
        """
        Record the human's decision on a pending approval.
        """
        with self._db.session() as session:
            row = session.get(models.ApprovalRow, approval_id)
            if row is None:
                raise errors.UnknownApprovalError(approval_id)
            row.status = "approved" if decision.approved else "denied"
            row.decided_by = decision.by
            row.remember = decision.remember
            row.note = decision.note
            row.decided_at = time.iso_now()

    def open_intervention(
        self, run_id: str, request: runs.InterventionRequest
    ) -> str:
        """
        Record a pending intervention and returns its id.
        """
        intervention_id = f"{run_id}~{ids.short_id('iv')}"
        with self._db.session() as session:
            session.add(
                models.InterventionRow(
                    id=intervention_id,
                    run_id=run_id,
                    reason=request.reason,
                    page_title=request.page_title or None,
                    edge_id=request.edge_id,
                    screenshot_file=request.screenshot_file,
                    state="paused",
                    raised_at=time.iso_now(),
                )
            )
        return intervention_id

    def update_intervention(
        self,
        intervention_id: str,
        state: runs.InterventionState,
        *,
        note: Optional[str] = None,
        human_actions: Optional[collections.abc.Sequence[str]] = None,
    ) -> None:
        """
        Move an intervention to ``state`` with the human's notes.
        """
        with self._db.session() as session:
            row = session.get(models.InterventionRow, intervention_id)
            if row is None:
                raise errors.UnknownInterventionError(intervention_id)
            row.state = state
            now = time.iso_now()
            if state == "human" and not row.taken_at:
                row.taken_at = now
            if state in {"resumed", "abandoned", "timed_out"}:
                row.resolved_at = now
            if note is not None:
                row.note = note
            if human_actions is not None:
                row.human_actions_json = json.dumps(list(human_actions))

    def open_clarification(self, run_id: str, question: str) -> str:
        """
        Record a pending clarifying question and returns its id.
        """
        clarification_id = f"{run_id}~{ids.short_id('clar')}"
        with self._db.session() as session:
            session.add(
                models.ClarificationRow(
                    id=clarification_id,
                    run_id=run_id,
                    question=question,
                    status="pending",
                    raised_at=time.iso_now(),
                )
            )
        return clarification_id

    def answer_clarification(self, clarification_id: str, answer: str) -> None:
        """
        Record the answer to a clarifying question.
        """
        with self._db.session() as session:
            row = session.get(models.ClarificationRow, clarification_id)
            if row is None:
                raise errors.NotFoundError(clarification_id)
            row.answer = answer
            row.status = "answered"
            row.answered_at = time.iso_now()

    def record_stability(
        self, capability_id: str, run_id: str, *, succeeded: bool
    ) -> artifact.Stability:
        """
        Add one replay to a capability's track record.
        """
        now = time.iso_now()
        with self._db.session() as session:
            # Load or start this capability's record.
            row = session.get(models.StabilityRecordRow, capability_id)
            if row is None:
                row = models.StabilityRecordRow(
                    capability_id=capability_id, runs=0, successes=0
                )
                session.add(row)
            # Fold this replay into the running counters.
            row.runs += 1
            row.successes += 1 if succeeded else 0
            row.last_run_at = now
            row.last_run_id = run_id
            # Record the individual sample and return the totals.
            session.add(
                models.StabilitySampleRow(
                    capability_id=capability_id,
                    run_id=run_id,
                    succeeded=succeeded,
                    at=now,
                )
            )
            stability = artifact.Stability(
                runs=row.runs, successes=row.successes, last_run_at=now
            )
            return stability

    def stability(self, capability_id: str) -> artifact.Stability:
        """
        Return the capability's track record (zeroes when none).
        """
        with self._db.session() as session:
            row = session.get(models.StabilityRecordRow, capability_id)
            if row is None:
                # No record yet: report an empty track record.
                stability = artifact.Stability(runs=0, successes=0)
            else:
                # Fold the stored counters into a track record.
                stability = artifact.Stability(
                    runs=row.runs,
                    successes=row.successes,
                    last_run_at=row.last_run_at,
                )
            return stability

    def audit(self, entry: runs.AuditEntry) -> None:
        """
        Append one line to the governance audit trail.
        """
        with self._db.session() as session:
            session.add(
                models.AuditLogRow(
                    at=entry.at or time.iso_now(),
                    actor=entry.actor,
                    action=entry.action,
                    subject_type="run" if entry.run_id else "artifact",
                    subject_id=entry.subject,
                    detail_json=json.dumps(entry.detail),
                )
            )

    def run_events(
        self, run_id: str, after_seq: int = -1
    ) -> collections.abc.Sequence[runs.RunEventIndex]:
        """
        Return a run's indexed events after ``after_seq``, in order.
        """
        statement = (
            sqlalchemy.select(models.RunEventRow)
            .where(
                models.RunEventRow.run_id == run_id,
                models.RunEventRow.seq > after_seq,
            )
            .order_by(models.RunEventRow.seq)
        )
        with self._db.session() as session:
            rows = session.execute(statement).scalars().all()
            records = [
                runs.RunEventIndex(
                    run_id=row.run_id,
                    seq=row.seq,
                    type=row.type,
                    at=row.at,
                    summary=row.summary,
                )
                for row in rows
            ]
            return records

    def index_sse(
        self,
        run_id: str,
        seq: int,
        type_: str,
        at: str,
        summary: str,
        *,
        data: Dict[str, object],
        screenshot: Optional[str],
    ) -> None:
        """
        Index one streamed event; keeps ``data`` only when non-empty.
        """
        with self._db.session() as session:
            session.add(
                models.RunEventRow(
                    run_id=run_id,
                    seq=seq,
                    type=type_,
                    at=at,
                    summary=summary,
                    screenshot_file=screenshot,
                    payload_json=json.dumps(data) if data else None,
                )
            )

    def stream_events(
        self, run_id: str, after_seq: int = -1
    ) -> collections.abc.Sequence[runs.StreamedEvent]:
        """
        Return replayable stream events after ``after_seq``, in order.
        """
        statement = (
            sqlalchemy.select(models.RunEventRow)
            .where(
                models.RunEventRow.run_id == run_id,
                models.RunEventRow.seq > after_seq,
            )
            .order_by(models.RunEventRow.seq)
        )
        with self._db.session() as session:
            rows = session.execute(statement).scalars().all()
            records = [
                runs.StreamedEvent(
                    run_id=row.run_id,
                    seq=row.seq,
                    type=row.type,
                    at=row.at,
                    summary=row.summary,
                    data=(
                        json.loads(row.payload_json) if row.payload_json else {}
                    ),
                    screenshot=row.screenshot_file,
                )
                for row in rows
            ]
            return records

    def get_approval(self, approval_id: str) -> Optional[runs.ApprovalRecord]:
        """
        Return one approval, or ``None`` when absent.
        """
        with self._db.session() as session:
            row = session.get(models.ApprovalRow, approval_id)
            record = _approval_from_row(row) if row is not None else None
            return record

    def pending_approvals(self) -> collections.abc.Sequence[runs.ApprovalRecord]:
        """
        Return every pending approval across all runs, oldest first.
        """
        statement = (
            sqlalchemy.select(models.ApprovalRow)
            .where(models.ApprovalRow.status == "pending")
            .order_by(models.ApprovalRow.raised_at)
        )
        with self._db.session() as session:
            records = [
                _approval_from_row(row)
                for row in session.execute(statement).scalars().all()
            ]
            return records

    def run_approvals(
        self, run_id: str
    ) -> collections.abc.Sequence[runs.ApprovalRecord]:
        """
        Return a run's approvals, newest first.
        """
        statement = (
            sqlalchemy.select(models.ApprovalRow)
            .where(models.ApprovalRow.run_id == run_id)
            .order_by(models.ApprovalRow.raised_at.desc())
        )
        with self._db.session() as session:
            records = [
                _approval_from_row(row)
                for row in session.execute(statement).scalars().all()
            ]
            return records

    def get_intervention(
        self, intervention_id: str
    ) -> Optional[runs.InterventionRecord]:
        """
        Return one intervention, or ``None`` when absent.
        """
        with self._db.session() as session:
            row = session.get(models.InterventionRow, intervention_id)
            record = _intervention_from_row(row) if row is not None else None
            return record

    def run_interventions(
        self, run_id: str
    ) -> collections.abc.Sequence[runs.InterventionRecord]:
        """
        Return a run's interventions, newest first.
        """
        statement = (
            sqlalchemy.select(models.InterventionRow)
            .where(models.InterventionRow.run_id == run_id)
            .order_by(models.InterventionRow.raised_at.desc())
        )
        with self._db.session() as session:
            records = [
                _intervention_from_row(row)
                for row in session.execute(statement).scalars().all()
            ]
            return records

    def get_clarification(
        self, clarification_id: str
    ) -> Optional[runs.ClarificationRecord]:
        """
        Return one clarification, or ``None`` when absent.
        """
        with self._db.session() as session:
            row = session.get(models.ClarificationRow, clarification_id)
            record = _clarification_from_row(row) if row is not None else None
            return record

    def run_clarifications(
        self, run_id: str
    ) -> collections.abc.Sequence[runs.ClarificationRecord]:
        """
        Return a run's clarifications, newest first.
        """
        statement = (
            sqlalchemy.select(models.ClarificationRow)
            .where(models.ClarificationRow.run_id == run_id)
            .order_by(models.ClarificationRow.raised_at.desc())
        )
        with self._db.session() as session:
            records = [
                _clarification_from_row(row)
                for row in session.execute(statement).scalars().all()
            ]
            return records

    @staticmethod
    def _require(session: orm.Session, run_id: str) -> models.RunRow:
        """
        Load a run row or raise ``NotFoundError``.
        """
        row = session.get(models.RunRow, run_id)
        if row is None:
            raise errors.NotFoundError(f"no run {run_id!r}")
        return row


# #############################################################################
# SqlSecretRefRepository
# #############################################################################


class SqlSecretRefRepository:
    """
    Secret-reference metadata in SQLite; never stores a value.
    """

    def __init__(self, database: engine.Database) -> None:
        self._db = database

    def list(self) -> collections.abc.Sequence[runs.SecretRefMeta]:
        """
        Return every declared reference, by name.
        """
        statement = sqlalchemy.select(models.SecretRefRow).order_by(
            models.SecretRefRow.name
        )
        with self._db.session() as session:
            rows = session.execute(statement).scalars().all()
            records = [_meta_from_row(row) for row in rows]
            return records

    def upsert(self, meta: runs.SecretRefMeta) -> None:
        """
        Create or replaces the reference named ``meta.name``.
        """
        with self._db.session() as session:
            row = session.get(models.SecretRefRow, meta.name)
            if row is None:
                row = models.SecretRefRow(
                    name=meta.name, created_at=time.iso_now()
                )
                session.add(row)
            row.backend = meta.backend
            row.locator = meta.locator
            row.description = meta.description

    def delete(self, name: str) -> None:
        """
        Remove a reference.
        """
        with self._db.session() as session:
            row = session.get(models.SecretRefRow, name)
            if row is None:
                raise errors.NotFoundError(name)
            session.delete(row)

    def mark_presence(self, name: str, present: bool) -> None:
        """
        Record whether the store currently resolves the reference.
        """
        with self._db.session() as session:
            row = session.get(models.SecretRefRow, name)
            if row is None:
                raise errors.NotFoundError(name)
            row.present = present
            row.last_checked_at = time.iso_now()


def _apply_filter(
    statement: sqlalchemy.Select[Tuple[models.RunRow]],
    criteria: runs.RunFilter,
) -> sqlalchemy.Select[Tuple[models.RunRow]]:
    """
    Narrow ``statement`` by the filter's set fields.
    """
    for column, value in (
        (models.RunRow.status, criteria.status),
        (models.RunRow.kind, criteria.kind),
        (models.RunRow.vendor_id, criteria.vendor_id),
        (models.RunRow.capability_id, criteria.capability_id),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return statement


def _row_from_run(run: runs.RunRecord) -> models.RunRow:
    """
    Build a ``RunRow`` from a run record.
    """
    row = models.RunRow(
        id=run.id,
        kind=run.kind,
        status=run.status,
        goal=run.goal or None,
        capability_id=run.capability_id,
        vendor_id=run.vendor_id or None,
        tenant=run.tenant or None,
        inputs_json=json.dumps(run.inputs),
        result_json=run.result.model_dump_json() if run.result else None,
        evidence_dir=run.evidence_dir or None,
        error=run.error,
        created_at=run.created_at or time.iso_now(),
        started_at=None,
        finished_at=None,
    )
    return row


def _run_from_row(row: models.RunRow) -> runs.RunRecord:
    """
    Build a run record from its row.
    """
    result = None
    if row.result_json:
        result = results.result_adapter.validate_json(row.result_json)
    record = runs.RunRecord(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        vendor_id=row.vendor_id or "",
        capability_id=row.capability_id,
        tenant=row.tenant or "",
        goal=row.goal or "",
        evidence_dir=row.evidence_dir or "",
        created_at=row.created_at,
        updated_at=row.finished_at or row.started_at or row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        inputs=json.loads(row.inputs_json),
        result=result,
        error=row.error,
    )
    return record


def _meta_from_row(row: models.SecretRefRow) -> runs.SecretRefMeta:
    """
    Build secret-reference metadata from its row.
    """
    meta = runs.SecretRefMeta(
        name=row.name,
        backend=row.backend,  # type: ignore[arg-type]
        locator=row.locator,
        description=row.description,
        updated_at=row.last_checked_at or row.created_at,
    )
    return meta


def _approval_from_row(
    row: models.ApprovalRow,
) -> runs.ApprovalRecord:
    """
    Build an approval record from its row.
    """
    record = runs.ApprovalRecord(
        id=row.id,
        run_id=row.run_id,
        kind=row.kind,
        summary=row.summary,
        action_kind=row.action_kind,
        status=row.status,  # type: ignore[arg-type]
        step=row.step,
        app=row.app,
        details=json.loads(row.details_json),
        proposed_grants=json.loads(row.proposed_grants_json),
        decided_by=row.decided_by,
        remember=row.remember,
        note=row.note,
        raised_at=row.raised_at,
        decided_at=row.decided_at,
    )
    return record


def _intervention_from_row(
    row: models.InterventionRow,
) -> runs.InterventionRecord:
    """
    Build an intervention record from its row.
    """
    record = runs.InterventionRecord(
        id=row.id,
        run_id=row.run_id,
        reason=row.reason,
        state=row.state,  # type: ignore[arg-type]
        page_title=row.page_title,
        edge_id=row.edge_id,
        screenshot_file=row.screenshot_file,
        note=row.note,
        human_actions=json.loads(row.human_actions_json),
        raised_at=row.raised_at,
        taken_at=row.taken_at,
        resolved_at=row.resolved_at,
    )
    return record


def _clarification_from_row(
    row: models.ClarificationRow,
) -> runs.ClarificationRecord:
    """
    Build a clarification record from its row.
    """
    record = runs.ClarificationRecord(
        id=row.id,
        run_id=row.run_id,
        question=row.question,
        status=row.status,  # type: ignore[arg-type]
        answer=row.answer,
        raised_at=row.raised_at,
        answered_at=row.answered_at,
    )
    return record
