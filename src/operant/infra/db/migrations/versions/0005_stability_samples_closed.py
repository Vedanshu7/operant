"""
Stability samples can be closed, so a capability moved to another graph starts
a new track record.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01 04:00:00.000000
"""

from __future__ import annotations

import alembic.op as op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add the closed flag.
    """
    with op.batch_alter_table("stability_samples", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("closed", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    """
    Drop the closed flag.
    """
    with op.batch_alter_table("stability_samples", schema=None) as batch_op:
        batch_op.drop_column("closed")
