import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.projects.schemas import ProjectCreate, ProjectList, ProjectOut, ProjectUpdate
from app.modules.projects.service import ProjectService

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(user: CurrentUser, session: SessionDep) -> ProjectList:
    projects = await ProjectService(session).list_projects(user)
    return ProjectList(items=[ProjectOut.model_validate(p) for p in projects])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_project(body: ProjectCreate, user: CurrentUser, session: SessionDep) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(session).create(user, body))


@router.get("/{project_id}")
async def get_project(project_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(session).get(user, project_id))


@router.patch("/{project_id}")
async def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, user: CurrentUser, session: SessionDep
) -> ProjectOut:
    return ProjectOut.model_validate(await ProjectService(session).update(user, project_id, body))


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(project_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    await ProjectService(session).delete(user, project_id)
