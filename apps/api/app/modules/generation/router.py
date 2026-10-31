import uuid

from fastapi import APIRouter, status

from app.modules.auth.dependencies import CurrentUser, SessionDep
from app.modules.building.appearance import PALETTE
from app.modules.generation.pipeline import available_design_systems
from app.modules.generation.schemas import (
    DesignOptionsOut,
    GenerateRequest,
    PaletteColor,
    SpecValidationOut,
    SpecValidationRequest,
)
from app.modules.generation.service import GenerationService
from app.modules.jobs.schemas import JobOut

router = APIRouter(prefix="/projects/{project_id}", tags=["generation"])
design_router = APIRouter(prefix="/design-options", tags=["generation"])


@design_router.get("")
async def design_options(user: CurrentUser) -> DesignOptionsOut:
    """Design systems (usable ones, and why the others are not usable yet) and the facade color
    palette — what the specification form may offer (K3)."""
    catalog = available_design_systems()
    return DesignOptionsOut(
        available=catalog.available,
        unavailable=catalog.unavailable,
        palette=[PaletteColor(name=name, hex=value) for name, value in PALETTE.items()],
    )


@router.post("/spec/validate")
async def validate_spec(
    project_id: uuid.UUID, body: SpecValidationRequest, user: CurrentUser, session: SessionDep
) -> SpecValidationOut:
    """Tier-1 (schema) and tier-2 (rules) validation of a spec, without generating."""
    return await GenerationService(session).validate(user, project_id, body.spec)


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(
    project_id: uuid.UUID, body: GenerateRequest, user: CurrentUser, session: SessionDep
) -> JobOut:
    """Start a generation job (spec -> layout -> new version). Poll GET /jobs/{id}."""
    job = await GenerationService(session).start(user, project_id, body)
    return JobOut.model_validate(job)
