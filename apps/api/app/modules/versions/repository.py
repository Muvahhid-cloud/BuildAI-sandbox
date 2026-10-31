import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from app.modules.versions.models import ProjectVersion


class VersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_project(self, project_id: uuid.UUID) -> list[ProjectVersion]:
        """Newest first; the large spec/model documents are not loaded (docs/database.md §6)."""
        result = await self.session.scalars(
            select(ProjectVersion)
            .where(ProjectVersion.project_id == project_id)
            .options(defer(ProjectVersion.model), defer(ProjectVersion.spec))
            .order_by(ProjectVersion.number.desc())
        )
        return list(result)

    async def get(self, project_id: uuid.UUID, version_id: uuid.UUID) -> ProjectVersion | None:
        return await self.session.scalar(
            select(ProjectVersion).where(
                ProjectVersion.id == version_id, ProjectVersion.project_id == project_id
            )
        )

    async def next_number(self, project_id: uuid.UUID) -> int:
        current = await self.session.scalar(
            select(func.max(ProjectVersion.number)).where(ProjectVersion.project_id == project_id)
        )
        return int(current or 0) + 1

    def add(self, version: ProjectVersion) -> None:
        self.session.add(version)
