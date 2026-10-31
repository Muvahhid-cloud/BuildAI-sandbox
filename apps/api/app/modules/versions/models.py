import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin, utcnow


class ProjectVersion(UUIDPrimaryKeyMixin, Base):
    """An immutable snapshot of a project's design (docs/database.md §3).

    Rows are never updated: edits, regenerations and restores create new versions.
    """

    __tablename__ = "project_versions"
    __table_args__ = (
        UniqueConstraint("project_id", "number", name="uq_project_versions_project_id_number"),
        Index("ix_project_versions_project_id_created_at", "project_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(200))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # generation | modification | manual | restore | fixture
    source: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    model: Mapped[dict[str, Any]] = mapped_column(JSONB)
    operations: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    schema_version: Mapped[str] = mapped_column(String(16))
    engine_version: Mapped[str] = mapped_column(String(64))
    rules_profile: Mapped[str] = mapped_column(String(80))
    seed: Mapped[int | None] = mapped_column(Integer)
    model_hash: Mapped[str] = mapped_column(String(64))
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Generation report: warnings, notes and engine metrics at the time of generation.
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
