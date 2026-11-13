import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin, utcnow


class Job(UUIDPrimaryKeyMixin, Base):
    """Tracks long-running work (docs/architecture.md §4.2). The client polls GET /jobs/{id}."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_project_id_created_at", "project_id", "created_at"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # generate
    status: Mapped[str] = mapped_column(String(16))  # queued | running | succeeded | failed
    stage: Mapped[str | None] = mapped_column(String(64))
    progress: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    input: Mapped[dict[str, Any]] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The laid-out model while the rules check and saving still run: the same JSON the
    # version then stores. Cleared when the job ends. Loaded only by the preview endpoint.
    preview_model: Mapped[dict[str, Any] | None] = deferred(mapped_column(JSONB))
    preview_model_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
