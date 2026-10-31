import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import utcnow
from app.modules.jobs.models import Job

ACTIVE = ("queued", "running")


class JobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    def add(self, job: Job) -> None:
        self.session.add(job)

    async def fail_interrupted(self) -> int:
        """Mark jobs left active by a previous process as failed. Returns how many."""
        result = await self.session.execute(
            update(Job)
            .where(Job.status.in_(ACTIVE))
            .values(
                status="failed",
                finished_at=utcnow(),
                error={
                    "code": "JOB_INTERRUPTED",
                    "message": "The server restarted while this job was running. Try again.",
                    "details": [],
                },
            )
        )
        return int(getattr(result, "rowcount", 0) or 0)

    async def active_for_project(self, project_id: uuid.UUID) -> Job | None:
        return await self.session.scalar(
            select(Job)
            .where(Job.project_id == project_id, Job.status.in_(ACTIVE))
            .order_by(Job.created_at.desc())
            .limit(1)
        )
