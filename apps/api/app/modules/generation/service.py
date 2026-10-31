"""Spec -> model generation use case: validate, run the layout engine as a job, store a version.

    POST /generate --(tier 1: Pydantic, tier 2: rules spec checks)--> job (queued)
    background: layout engine (tier 3 + model invariants) -> rules findings -> new version

The layout engine is CPU-bound and pure; it runs in a worker thread so the event loop stays free.
"""

import logging
import time
import uuid
from typing import Any

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker, utcnow
from app.core.errors import AppError, ConflictError
from app.modules.ai.repository import AIGenerationRepository
from app.modules.auth.models import User
from app.modules.building.issues import Issue, errors
from app.modules.building.specification import BuildingSpecification
from app.modules.generation.pipeline import check_spec_design, layout_and_save
from app.modules.generation.schemas import GenerateRequest, SpecValidationOut
from app.modules.jobs.models import Job
from app.modules.jobs.repository import JobRepository
from app.modules.jobs.runner import job_runner
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError
from app.modules.projects.models import Project
from app.modules.projects.service import ProjectService
from app.modules.rules.spec_checks import check_spec
from app.shared.data_files import rules_profile

logger = logging.getLogger(__name__)

# Real stages of a generation job, in order (the UI shows them as they happen).
STAGES = ("queued", "layout", "checking", "saving", "done")


class SpecInvalidError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "SPEC_INVALID"


class GenerationBusyError(ConflictError):
    code = "GENERATION_IN_PROGRESS"


async def project_busy(session: AsyncSession, project_id: uuid.UUID) -> bool:
    """A spec-form job or an AI generation is already running for the project."""
    if await JobRepository(session).active_for_project(project_id) is not None:
        return True
    return await AIGenerationRepository(session).active_for_project(project_id) is not None


def _issue_details(issues: list[Issue]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json", exclude_none=True) for i in issues]


class GenerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectService(session)

    async def validate(
        self, user: User, project_id: uuid.UUID, spec: BuildingSpecification
    ) -> SpecValidationOut:
        project = await self.projects.get(user, project_id)
        profile = rules_profile(get_settings().data_dir, project.rules_profile_id)
        issues = check_spec(spec, profile, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
        issues += check_spec_design(spec)
        return SpecValidationOut(valid=not errors(issues), issues=issues, rules_profile=profile.ref)

    async def start(self, user: User, project_id: uuid.UUID, request: GenerateRequest) -> Job:
        validation = await self.validate(user, project_id, request.spec)
        if not validation.valid:
            raise SpecInvalidError(
                "The building specification is not valid",
                details=_issue_details(validation.issues),
            )
        jobs = JobRepository(self.session)
        if await project_busy(self.session, project_id):
            raise GenerationBusyError("A generation is already running for this project")
        job = Job(
            project_id=project_id,
            user_id=user.id,
            kind="generate",
            status="queued",
            stage="queued",
            progress=0.0,
            input={
                "spec": request.spec.model_dump(mode="json"),
                "seed": request.seed,
                "label": request.label,
                "spec_warnings": _issue_details(validation.issues),
            },
        )
        jobs.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        job_id = job.id
        job_runner.submit(f"generate:{job_id}", lambda: run_generation_job(job_id))
        return job


async def _stage(session: AsyncSession, job: Job, stage: str) -> None:
    job.stage = stage
    job.progress = STAGES.index(stage) / (len(STAGES) - 1)
    if stage == "layout":
        job.status = "running"
        job.started_at = utcnow()
    await session.commit()


async def _fail(
    session: AsyncSession, job: Job, code: str, message: str, details: list[dict[str, Any]]
) -> None:
    job.status = "failed"
    job.finished_at = utcnow()
    job.error = {"code": code, "message": message, "details": details}
    await session.commit()


async def run_generation_job(job_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return
        project = await session.get(Project, job.project_id)
        user = await session.get(User, job.user_id)
        if project is None or project.deleted_at is not None:
            await _fail(session, job, "PROJECT_NOT_FOUND", "The project no longer exists", [])
            return
        project_id = project.id  # plain value: attributes expire on rollback
        spec = BuildingSpecification.model_validate(job.input["spec"])
        seed = int(job.input.get("seed", 0))
        label = job.input.get("label") or f"{spec.name} (seed {seed})"
        spec_warnings = [Issue.model_validate(i) for i in job.input.get("spec_warnings", [])]
        started = time.perf_counter()

        async def stage(name: str) -> None:
            await _stage(session, job, name)

        try:
            result = await layout_and_save(
                session,
                project,
                user,
                spec=spec,
                seed=seed,
                label=label,
                source="generation",
                spec_warnings=spec_warnings,
                on_stage=stage,
            )
        except LayoutError as exc:
            logger.info(
                "generation job=%s project=%s status=failed code=%s ms=%d",
                job_id,
                project_id,
                exc.code,
                (time.perf_counter() - started) * 1000,
            )
            await session.rollback()
            await _fail(session, job, exc.code, exc.message, _issue_details(exc.issues))
            return
        except Exception:
            logger.exception("generation job=%s project=%s crashed", job_id, project_id)
            await session.rollback()
            await _fail(
                session, job, "INTERNAL_ERROR", "Generation failed because of a server error", []
            )
            return
        version, metrics = result.version, result.layout.metrics
        job.status = "succeeded"
        job.stage = "done"
        job.progress = 1.0
        job.finished_at = utcnow()
        job.result = {
            "version_id": str(version.id),
            "version_number": version.number,
            "summary": version.summary,
            "warnings": len(result.report.warnings),
        }
        await session.commit()
        logger.info(
            "generation job=%s project=%s status=succeeded version=%s ms=%d candidates=%s",
            job_id,
            project_id,
            version.number,
            (time.perf_counter() - started) * 1000,
            metrics.candidates_evaluated if metrics else "?",
        )
