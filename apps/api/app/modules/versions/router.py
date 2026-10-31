import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.versions.schemas import VersionList, VersionOut
from app.modules.versions.service import VersionService

router = APIRouter(prefix="/projects/{project_id}/versions", tags=["versions"])


@router.get("")
async def list_versions(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> VersionList:
    return VersionList(items=await VersionService(session).list(user, project_id))


@router.get("/{version_id}")
async def get_version(
    project_id: uuid.UUID, version_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> VersionOut:
    return await VersionService(session).get(user, project_id, version_id)


@router.post("/demo", status_code=status.HTTP_201_CREATED)
async def import_demo_version(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> VersionOut:
    """Store the hand-authored demo house as a new version (Phase 2: fixture as a version)."""
    return await VersionService(session).import_demo(user, project_id)
