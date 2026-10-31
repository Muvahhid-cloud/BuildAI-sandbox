import uuid

from fastapi import APIRouter, status

from app.modules.ai.schemas.responses import AIGenerateRequest, AIGenerationList, AIGenerationOut
from app.modules.ai.service import AIGenerationService
from app.modules.auth.dependencies import CurrentUser, SessionDep

router = APIRouter(prefix="/ai", tags=["ai"])
project_router = APIRouter(prefix="/projects/{project_id}", tags=["ai"])


@router.post("/generate-building", status_code=status.HTTP_202_ACCEPTED)
async def generate_building(
    body: AIGenerateRequest, user: CurrentUser, session: SessionDep
) -> AIGenerationOut:
    """Start a natural-language generation (prompt -> AI -> spec -> layout -> new version).

    Without `project_id` a new project is created for the design. Poll
    GET /ai/generations/{id} for the real stage and the result."""
    return await AIGenerationService(session).start(user, body)


@router.get("/generations/{generation_id}")
async def get_generation(
    generation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AIGenerationOut:
    return await AIGenerationService(session).get(user, generation_id)


@project_router.get("/generations")
async def list_generations(
    project_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> AIGenerationList:
    """Generation history of a project, newest first."""
    return AIGenerationList(
        items=await AIGenerationService(session).list_for_project(user, project_id)
    )
