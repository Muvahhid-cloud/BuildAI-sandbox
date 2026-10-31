"""project_versions, jobs; projects.current_version_id -> project_versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("parent_version_id", sa.Uuid(), nullable=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=True),
        sa.Column("spec", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "operations", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column("schema_version", sa.String(16), nullable=False),
        sa.Column("engine_version", sa.String(64), nullable=False),
        sa.Column("rules_profile", sa.String(80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("model_hash", sa.String(64), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_project_versions_project_id_projects", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["parent_version_id"],
            ["project_versions.id"],
            name="fk_project_versions_parent_version_id_project_versions",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_project_versions_created_by_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_project_versions"),
        sa.UniqueConstraint("project_id", "number", name="uq_project_versions_project_id_number"),
    )
    op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"])
    op.create_index("ix_project_versions_parent_version_id", "project_versions", ["parent_version_id"])
    op.create_index(
        "ix_project_versions_project_id_created_at", "project_versions", ["project_id", "created_at"]
    )

    op.create_foreign_key(
        "fk_projects_current_version_id_project_versions",
        "projects",
        "project_versions",
        ["current_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("stage", sa.String(64), nullable=True),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("input", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_jobs_project_id_projects", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_jobs_user_id_users", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index("ix_jobs_project_id", "jobs", ["project_id"])
    op.create_index("ix_jobs_project_id_created_at", "jobs", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_jobs_project_id_created_at", table_name="jobs")
    op.drop_index("ix_jobs_project_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_constraint("fk_projects_current_version_id_project_versions", "projects", type_="foreignkey")
    op.drop_index("ix_project_versions_project_id_created_at", table_name="project_versions")
    op.drop_index("ix_project_versions_parent_version_id", table_name="project_versions")
    op.drop_index("ix_project_versions_project_id", table_name="project_versions")
    op.drop_table("project_versions")
