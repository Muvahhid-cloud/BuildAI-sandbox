import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.modules.auth.models import User
from app.modules.projects.models import Project
from app.modules.projects.repository import ProjectRepository
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate


class ProjectService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ProjectRepository(session)

    async def list_projects(self, user: User) -> list[Project]:
        return await self.repo.list_for_owner(user.id)

    async def get(self, user: User, project_id: uuid.UUID) -> Project:
        project = await self.repo.get_active(project_id)
        # Non-owners get 404 (not 403) so project ids can't be probed.
        if project is None or project.owner_id != user.id:
            raise NotFoundError("Project not found")
        return project

    async def create(self, user: User, data: ProjectCreate) -> Project:
        settings = get_settings()
        project = Project(
            owner_id=user.id,
            name=data.name.strip(),
            description=data.description,
            building_type=data.building_type,
            region_code=data.region_code or settings.default_region_code,
            currency=data.currency or settings.default_currency,
            rules_profile_id=settings.default_rules_profile,
        )
        self.repo.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update(self, user: User, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        project = await self.get(user, project_id)
        for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(project, field, value.strip() if field == "name" else value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def delete(self, user: User, project_id: uuid.UUID) -> None:
        project = await self.get(user, project_id)
        project.deleted_at = datetime.now(UTC)
        await self.session.commit()
