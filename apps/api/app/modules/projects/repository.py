import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_owner(self, owner_id: uuid.UUID) -> list[Project]:
        result = await self.session.scalars(
            select(Project)
            .where(Project.owner_id == owner_id, Project.deleted_at.is_(None))
            .order_by(Project.updated_at.desc(), Project.id)
        )
        return list(result)

    async def get_active(self, project_id: uuid.UUID) -> Project | None:
        return await self.session.scalar(
            select(Project).where(Project.id == project_id, Project.deleted_at.is_(None))
        )

    def add(self, project: Project) -> None:
        self.session.add(project)
