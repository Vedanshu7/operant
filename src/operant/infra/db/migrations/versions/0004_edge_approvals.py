"""
People's reviews of unknown steps, so replay asks about each step only once,
and per-version edge outcomes, so rediscovery can retire a broken edge.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-01 02:00:00.000000
"""

from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create the review and outcome tables.
    """
    op.create_table(
        "edge_approvals",
        sa.Column("vendor_id", sa.String(length=128), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("edge_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("approved_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at", sa.String(length=40), nullable=False),
        sa.PrimaryKeyConstraint(
            "vendor_id", "graph_version", "edge_id", "role", "name"
        ),
    )
    op.create_table(
        "edge_outcomes",
        sa.Column("vendor_id", sa.String(length=128), nullable=False),
        sa.Column("graph_version", sa.Integer(), nullable=False),
        sa.Column("edge_id", sa.String(length=128), nullable=False),
        sa.Column("passes", sa.Integer(), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("vendor_id", "graph_version", "edge_id"),
    )


def downgrade() -> None:
    """
    Drop the review and outcome tables.
    """
    op.drop_table("edge_outcomes")
    op.drop_table("edge_approvals")
