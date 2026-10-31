import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.editing.schemas import EditPreviewOut, EditRequest, EditSaveRequest
from app.modules.editing.service import EditingService
from app.modules.versions.schemas import VersionOut

router = APIRouter(prefix="/projects/{project_id}/versions/{version_id}/edits", tags=["editing"])


@router.post("/preview")
async def preview_edits(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: EditRequest,
    user: CurrentUser,
    session: SessionDep,
) -> EditPreviewOut:
    """Apply operations to a version in memory and validate the result. Nothing is stored; a
    refused edit is a normal answer (`valid: false` with the reason), not an HTTP error."""
    return await EditingService(session).preview(user, project_id, version_id, body.operations)


@router.post("", status_code=status.HTTP_201_CREATED)
async def save_edits(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: EditSaveRequest,
    user: CurrentUser,
    session: SessionDep,
) -> VersionOut:
    """Store the edited model as a new version (422 EDIT_REJECTED if the edits are invalid)."""
    return await EditingService(session).save(
        user, project_id, version_id, body.operations, body.label
    )
