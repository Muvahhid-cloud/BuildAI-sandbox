"""AI persistence (docs/database.md): generation history and one row per provider call.

`ai_generations` is the user-visible history of natural-language generations (prompt, status,
real stage, specification snapshot, warnings, resulting version). `ai_runs` records every
provider call (generation or repair) with its raw output and validation issues, for debugging
and evaluation. Neither stores secrets; prompts are stored because they are the user's input.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UUIDPrimaryKeyMixin, utcnow


class AIGeneration(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_generations"
    __table_args__ = (
        Index("ix_ai_generations_project_id_created_at", "project_id", "created_at"),
        Index("ix_ai_generations_user_id_created_at", "user_id", "created_at"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # building_generation
    # queued | running | completed | needs_clarification | failed
    status: Mapped[str] = mapped_column(String(24))
    stage: Mapped[str | None] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[dict[str, Any]] = mapped_column(JSONB)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(40))
    understanding: Mapped[str | None] = mapped_column(Text)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    warnings: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    clarification_questions: Mapped[list[Any]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    error: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("project_versions.id", ondelete="SET NULL")
    )
    seed: Mapped[int] = mapped_column(Integer)
    rules_profile: Mapped[str] = mapped_column(String(80))
    engine_version: Mapped[str | None] = mapped_column(String(64))
    repair_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    # The project was created for this generation: name it after the interpreted spec.
    names_project: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AIRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_runs"
    __table_args__ = (Index("ix_ai_runs_project_id_created_at", "project_id", "created_at"),)

    generation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ai_generations.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task: Mapped[str] = mapped_column(String(32))  # generate_specification | repair_specification
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(16))  # ok | invalid | error
    error_code: Mapped[str | None] = mapped_column(String(64))
    raw_output: Mapped[str | None] = mapped_column(Text)
    parsed_output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    issues: Mapped[list[Any]] = mapped_column(JSONB, default=list, server_default="[]")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow
    )
