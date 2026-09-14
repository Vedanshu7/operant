"""
Agent memory quality: app graph version on plans and lessons, and lessons keyed
by subgoal and failure kind.

Lessons recorded before this revision were saved at every verifier
rejection, including rejections the run later got past; they are
dropped. A person's notes are kept.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22 23:00:00.000000
"""

from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add the version and lesson-key columns; drop pre-revision verifier lessons.
    """
    with op.batch_alter_table("plan_memory", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "graph_version", sa.Integer(), nullable=False, server_default="0"
            )
        )
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("subgoal_key", sa.Text(), nullable=False, server_default="")
        )
        batch_op.add_column(
            sa.Column(
                "failure_kind",
                sa.String(length=32),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "graph_version", sa.Integer(), nullable=False, server_default="0"
            )
        )
    op.execute("DELETE FROM lessons WHERE source = 'verifier'")


def downgrade() -> None:
    """
    Drop the added columns (dropped lessons are not restored).
    """
    with op.batch_alter_table("lessons", schema=None) as batch_op:
        batch_op.drop_column("graph_version")
        batch_op.drop_column("failure_kind")
        batch_op.drop_column("subgoal_key")
    with op.batch_alter_table("plan_memory", schema=None) as batch_op:
        batch_op.drop_column("graph_version")
