"""ai_generations (natural-language generation history), ai_runs (one row per AI call)

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_generations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(32), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("understanding", sa.Text(), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column(
            "clarification_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("version_id", sa.Uuid(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("rules_profile", sa.String(80), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=True),
        sa.Column("repair_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("names_project", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_ai_generations_project_id_projects", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_ai_generations_user_id_users", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["project_versions.id"],
            name="fk_ai_generations_version_id_project_versions",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ai_generations"),
    )
    op.create_index("ix_ai_generations_project_id", "ai_generations", ["project_id"])
    op.create_index(
        "ix_ai_generations_project_id_created_at", "ai_generations", ["project_id", "created_at"]
    )
    op.create_index("ix_ai_generations_user_id_created_at", "ai_generations", ["user_id", "created_at"])

    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("generation_id", sa.Uuid(), nullable=True),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("task", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("parsed_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("issues", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["generation_id"],
            ["ai_generations.id"],
            name="fk_ai_runs_generation_id_ai_generations",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_ai_runs_project_id_projects", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_ai_runs_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ai_runs"),
    )
    op.create_index("ix_ai_runs_generation_id", "ai_runs", ["generation_id"])
    op.create_index("ix_ai_runs_project_id_created_at", "ai_runs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_runs_project_id_created_at", table_name="ai_runs")
    op.drop_index("ix_ai_runs_generation_id", table_name="ai_runs")
    op.drop_table("ai_runs")
    op.drop_index("ix_ai_generations_user_id_created_at", table_name="ai_generations")
    op.drop_index("ix_ai_generations_project_id_created_at", table_name="ai_generations")
    op.drop_index("ix_ai_generations_project_id", table_name="ai_generations")
    op.drop_table("ai_generations")
