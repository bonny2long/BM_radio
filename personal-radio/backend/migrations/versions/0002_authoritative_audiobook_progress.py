"""authoritative audiobook progress

Revision ID: 0002_audiobook_progress
Revises: 0001_current_schema_baseline
Create Date: 2026-08-18
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_audiobook_progress"
down_revision = "0001_current_schema_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve the newest legacy checkpoint before enforcing one row per book.
    op.execute("DELETE FROM audiobook_progress WHERE audiobook_id IS NULL")
    op.execute(
        """
        DELETE FROM audiobook_progress
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY audiobook_id
                           ORDER BY updated_at DESC, id DESC
                       ) AS row_number
                FROM audiobook_progress
            ) ranked
            WHERE row_number = 1
        )
        """
    )
    op.add_column(
        "audiobook_progress",
        sa.Column("checkpointed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE audiobook_progress "
        "SET checkpointed_at = COALESCE(updated_at, CURRENT_TIMESTAMP) "
        "WHERE checkpointed_at IS NULL"
    )
    with op.batch_alter_table("audiobook_progress") as batch:
        batch.alter_column("audiobook_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("checkpointed_at", nullable=False, server_default=sa.func.now())
        batch.create_index("ix_audiobook_progress_checkpointed_at", ["checkpointed_at"])
        batch.create_unique_constraint("uq_audiobook_progress_audiobook_id", ["audiobook_id"])


def downgrade() -> None:
    with op.batch_alter_table("audiobook_progress") as batch:
        batch.drop_constraint("uq_audiobook_progress_audiobook_id", type_="unique")
        batch.drop_index("ix_audiobook_progress_checkpointed_at")
        batch.drop_column("checkpointed_at")
        batch.alter_column("audiobook_id", existing_type=sa.Integer(), nullable=True)
