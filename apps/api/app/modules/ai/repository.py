import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.core.db import utcnow
from app.modules.ai.models import AIGeneration, AIRun

ACTIVE = ("queued", "running")


class AIGenerationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, generation_id: uuid.UUID) -> AIGeneration | None:
        return await self.session.get(AIGeneration, generation_id)

    def add(self, row: AIGeneration | AIRun) -> None:
        self.session.add(row)

    async def list_for_project(self, project_id: uuid.UUID, limit: int = 50) -> list[AIGeneration]:
        """Newest first; the spec snapshot is not loaded for lists."""
        result = await self.session.scalars(
            select(AIGeneration)
            .where(AIGeneration.project_id == project_id)
            .options(defer(AIGeneration.spec))
            .order_by(AIGeneration.created_at.desc())
            .limit(limit)
        )
        return list(result)

    async def active_for_project(self, project_id: uuid.UUID) -> AIGeneration | None:
        return await self.session.scalar(
            select(AIGeneration)
            .where(AIGeneration.project_id == project_id, AIGeneration.status.in_(ACTIVE))
            .limit(1)
        )

    async def count_since(self, user_id: uuid.UUID, since: datetime) -> int:
        count = await self.session.scalar(
            select(func.count())
            .select_from(AIGeneration)
            .where(AIGeneration.user_id == user_id, AIGeneration.created_at >= since)
        )
        return int(count or 0)

    async def preview(self, generation_id: uuid.UUID) -> tuple[dict[str, Any], str] | None:
        """(model JSON, model hash) of the generation's preview, if it has one."""
        row = (
            await self.session.execute(
                select(AIGeneration.preview_model, AIGeneration.preview_model_hash).where(
                    AIGeneration.id == generation_id
                )
            )
        ).first()
        if row is None or row[0] is None or row[1] is None:
            return None
        return row[0], row[1]

    async def runs_for(self, generation_id: uuid.UUID) -> list[AIRun]:
        result = await self.session.scalars(
            select(AIRun).where(AIRun.generation_id == generation_id).order_by(AIRun.created_at)
        )
        return list(result)

    async def fail_interrupted(self) -> int:
        """Mark generations left active by a previous process as failed. Returns how many."""
        result = await self.session.execute(
            update(AIGeneration)
            .where(AIGeneration.status.in_(ACTIVE))
            .values(
                status="failed",
                finished_at=utcnow(),
                preview_model=None,
                preview_model_hash=None,
                error={
                    "code": "JOB_INTERRUPTED",
                    "message": "The server restarted while this generation was running. Try again.",
                    "details": [],
                },
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)
