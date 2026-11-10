import uuid

from fastapi import APIRouter

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.modification.schemas import ModifyPlanOut, ModifyPlanRequest, ModifyResolveRequest
from app.modules.modification.service import ModificationService

router = APIRouter(
    prefix="/projects/{project_id}/versions/{version_id}/modify", tags=["modification"]
)


@router.post("/plan")
async def plan_modification(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ModifyPlanRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ModifyPlanOut:
    """Natural-language change request -> AI interpretation -> typed editing operations, questions
    for anything unclear, and the validated candidate model. Nothing is stored."""
    return await ModificationService(session).plan(user, project_id, version_id, body)


@router.post("/resolve")
async def resolve_modification(
    project_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ModifyResolveRequest,
    user: CurrentUser,
    session: SessionDep,
) -> ModifyPlanOut:
    """Resolve an earlier interpretation again with the user's answers (no AI call)."""
    return await ModificationService(session).resolve(user, project_id, version_id, body)
