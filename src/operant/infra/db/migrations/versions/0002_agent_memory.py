"""
Agent memory: plans that worked and lessons to avoid repeating.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-21 12:00:00.000000
"""

from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create the plan-memory and lessons tables.
    """
    op.create_table(
        "plan_memory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vendor_id", sa.String(length=128), nullable=False),
        sa.Column("goal_key", sa.Text(), nullable=False),
        sa.Column("goal_text", sa.Text(), nullable=False),
        sa.Column("plan_json", sa.Text(), nullable=False),
        sa.Column("successes", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plan_memory", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_plan_memory_vendor_id"), ["vendor_id"], unique=False
        )
    op.create_table(
        "lessons",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("vendor_id", sa.String(length=128), nullable=False),
        sa.Column("goal_key", sa.Text(), nullable=False),
        sa.Column("lesson", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("reinforcements", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_lessons_vendor_id"), ["vendor_id"], unique=False
        )


def downgrade() -> None:
    """
    Drop the agent-memory tables.
    """
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_lessons_vendor_id"))
    op.drop_table("lessons")
    with op.batch_alter_table("plan_memory", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plan_memory_vendor_id"))
    op.drop_table("plan_memory")
