"""
SQLAlchemy table definitions.

Tables index what the UI queries and hold state that must survive a
process: runs, their human-in-the-loop questions, stability counters,
and the audit trail. Bulk run events stay in the evidence JSONL;
``run_events`` indexes them by sequence and keeps the payload only for
HITL/status rows.
"""

from __future__ import annotations

from typing import Optional

import sqlalchemy
import sqlalchemy.orm

# #############################################################################
# Base
# #############################################################################


class Base(sqlalchemy.orm.DeclarativeBase):
    """
    Declarative base for all Operant tables.
    """


# #############################################################################
# RunRow
# #############################################################################


class RunRow(Base):
    """
    One discovery or replay run.
    """

    __tablename__ = "runs"

    id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), primary_key=True
    )
    kind: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False
    )
    status: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(32), nullable=False, index=True
    )
    goal: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text
    )
    capability_id: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(128), index=True)
    )
    vendor_id: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(128))
    )
    profile_id: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(128))
    )
    tenant: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64)
    )
    bootstrap: sqlalchemy.orm.Mapped[bool] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Boolean, default=False
    )
    inputs_json: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default="{}"
    )
    result_json: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.Text)
    )
    evidence_dir: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.Text)
    )
    error: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text
    )
    created_by: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(128))
    )
    created_at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    started_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )
    finished_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )


# #############################################################################
# RunEventRow
# #############################################################################


class RunEventRow(Base):
    """
    Index of one evidence event.
    """

    __tablename__ = "run_events"
    __table_args__ = (
        sqlalchemy.UniqueConstraint(
            "run_id", "seq", name="uq_run_events_run_seq"
        ),
        sqlalchemy.Index("ix_run_events_run_type", "run_id", "type"),
    )

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True
    )
    run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("runs.id"), nullable=False
    )
    seq: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, nullable=False
    )
    type: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), nullable=False
    )
    at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    summary: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default=""
    )
    screenshot_file: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(255))
    )
    payload_json: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.Text)
    )


# #############################################################################
# ApprovalRow
# #############################################################################


class ApprovalRow(Base):
    """
    A pending or decided approval question.
    """

    __tablename__ = "approvals"

    id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(96), primary_key=True
    )
    run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("runs.id"), nullable=False, index=True
    )
    kind: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(32), nullable=False
    )
    summary: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    fingerprint: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), default=""
    )
    step: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128)
    )
    action_kind: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(32), default=""
    )
    app: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128)
    )
    details_json: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default="{}"
    )
    proposed_grants_json: sqlalchemy.orm.Mapped[str] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.Text, default="[]")
    )
    status: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False, index=True
    )
    decided_by: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(64))
    )
    remember: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16)
    )
    note: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text
    )
    raised_at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    decided_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )


# #############################################################################
# InterventionRow
# #############################################################################


class InterventionRow(Base):
    """
    A control-transfer request and its lifecycle.
    """

    __tablename__ = "interventions"

    id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(96), primary_key=True
    )
    run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("runs.id"), nullable=False, index=True
    )
    reason: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    page_title: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.Text)
    )
    edge_id: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128)
    )
    screenshot_file: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(255))
    )
    state: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False, index=True
    )
    note: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text
    )
    human_actions_json: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default="[]"
    )
    raised_at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    taken_at: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40)
    )
    resolved_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )


# #############################################################################
# ClarificationRow
# #############################################################################


class ClarificationRow(Base):
    """
    A question the agent asked a human.
    """

    __tablename__ = "clarifications"

    id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(96), primary_key=True
    )
    run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.ForeignKey("runs.id"), nullable=False, index=True
    )
    question: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    answer: sqlalchemy.orm.Mapped[Optional[str]] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text
    )
    status: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False, index=True
    )
    raised_at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    answered_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )


# #############################################################################
# StabilityRecordRow
# #############################################################################


class StabilityRecordRow(Base):
    """
    Rolling replay counters per capability.
    """

    __tablename__ = "stability_records"

    capability_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128), primary_key=True
    )
    runs: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, default=0
    )
    successes: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, default=0
    )
    last_run_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )
    last_run_id: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(64))
    )


# #############################################################################
# StabilitySampleRow
# #############################################################################


class StabilitySampleRow(Base):
    """
    One replay's contribution to the counters (audit trail).
    """

    __tablename__ = "stability_samples"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True
    )
    capability_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128), index=True
    )
    run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), nullable=False
    )
    succeeded: sqlalchemy.orm.Mapped[bool] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Boolean, nullable=False
    )
    at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )


# #############################################################################
# AuditFindingRow
# #############################################################################


class AuditFindingRow(Base):
    """
    A finding from ``operant audit``.
    """

    __tablename__ = "audit_findings"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True
    )
    audit_run_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), index=True
    )
    scope: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False
    )
    subject: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    severity: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False
    )
    message: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )


# #############################################################################
# AuditLogRow
# #############################################################################


class AuditLogRow(Base):
    """
    Who did what: approvals, interventions, capability approvals, secrets.
    """

    __tablename__ = "audit_log"

    id: sqlalchemy.orm.Mapped[int] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Integer, primary_key=True, autoincrement=True
    )
    at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False, index=True
    )
    actor: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128), nullable=False
    )
    action: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(64), nullable=False
    )
    subject_type: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(32), nullable=False
    )
    subject_id: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128), nullable=False
    )
    detail_json: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default="{}"
    )


# #############################################################################
# SecretRefRow
# #############################################################################


class SecretRefRow(Base):
    """
    Metadata about a secret reference; never its value.
    """

    __tablename__ = "secret_refs"

    name: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(128), primary_key=True
    )
    backend: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(16), nullable=False
    )
    locator: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, nullable=False
    )
    description: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Text, default=""
    )
    created_at: sqlalchemy.orm.Mapped[str] = sqlalchemy.orm.mapped_column(
        sqlalchemy.String(40), nullable=False
    )
    last_checked_at: sqlalchemy.orm.Mapped[Optional[str]] = (
        sqlalchemy.orm.mapped_column(sqlalchemy.String(40))
    )
    present: sqlalchemy.orm.Mapped[bool] = sqlalchemy.orm.mapped_column(
        sqlalchemy.Boolean, default=False
    )
