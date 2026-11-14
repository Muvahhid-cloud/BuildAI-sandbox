"""live creation: interim facts and the preview model of a running generation

ai_generations.interim_facts      facts read from the AI's answer while it is written
ai_generations.preview_model(+hash)  the laid-out model while checking/saving still run
jobs.preview_model(+hash)         the same for spec-form generation jobs

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_generations",
        sa.Column(
            "interim_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    for table in ("ai_generations", "jobs"):
        op.add_column(
            table,
            sa.Column("preview_model", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
        op.add_column(table, sa.Column("preview_model_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    for table in ("jobs", "ai_generations"):
        op.drop_column(table, "preview_model_hash")
        op.drop_column(table, "preview_model")
    op.drop_column("ai_generations", "interim_facts")
