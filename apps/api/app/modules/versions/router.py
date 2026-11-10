import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.versions.schemas import CompareOut, VersionList, VersionOut
from app.modules.versions.service import VersionService

router = APIRouter(prefix="/projects/{project_id}/versions", tags=["versions"])
project_router = APIRouter(prefix="/projects/{project_id}", tags=["versions"])


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


@router.post("/{version_id}/restore", status_code=status.HTTP_201_CREATED)
async def restore_version(
    project_id: uuid.UUID, version_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> VersionOut:
    """Make an earlier version current again as a NEW version (versions are immutable)."""
    return await VersionService(session).restore(user, project_id, version_id)


@project_router.get("/compare")
async def compare_versions(
    project_id: uuid.UUID, a: uuid.UUID, b: uuid.UUID, user: CurrentUser, session: SessionDep
) -> CompareOut:
    """Measured differences from version `a` to version `b` (elements added/removed/changed,
    rooms, openings, floor area)."""
    return await VersionService(session).compare(user, project_id, a, b)
