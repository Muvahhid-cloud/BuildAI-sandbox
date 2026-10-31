"""AI generation use cases behind the HTTP API: start, read, list (ownership checked here)."""

import re
import uuid
from datetime import timedelta
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import utcnow
from app.core.errors import AppError, NotFoundError
from app.modules.ai.errors import AIProviderError
from app.modules.ai.models import AIGeneration
from app.modules.ai.orchestrator import run_ai_generation
from app.modules.ai.prompts.shared import PROMPT_VERSION
from app.modules.ai.providers import get_ai_provider
from app.modules.ai.repository import AIGenerationRepository
from app.modules.ai.schemas.responses import (
    AIGenerateRequest,
    AIGenerationOut,
    AIGenerationSummaryOut,
    GenerationErrorOut,
)
from app.modules.auth.models import User
from app.modules.building.issues import Issue
from app.modules.building.requirements import requirement_checks
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import ModelSummary
from app.modules.generation.service import GenerationBusyError, project_busy
from app.modules.jobs.runner import job_runner
from app.modules.layout.engine import GFA_WARNING_THRESHOLD
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from app.modules.versions.models import ProjectVersion

NEW_PROJECT_NAME = "New AI design"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class PromptTooLongError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "PROMPT_TOO_LONG"


class AIRateLimitedError(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "AI_RATE_LIMITED"


class AINotConfiguredError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "AI_NOT_CONFIGURED"


def clean_prompt(prompt: str) -> str:
    return _CONTROL_RE.sub("", prompt).strip()


class AIGenerationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AIGenerationRepository(session)
        self.projects = ProjectService(session)

    async def start(self, user: User, request: AIGenerateRequest) -> AIGenerationOut:
        settings = get_settings()
        prompt = clean_prompt(request.prompt)
        if len(prompt) < 3:
            raise PromptTooLongError(
                "Describe the building in a few words",
                details=[{"path": "/prompt", "message": "The description is empty"}],
            )
        if len(prompt) > settings.ai_max_prompt_chars:
            raise PromptTooLongError(
                f"The description is limited to {settings.ai_max_prompt_chars} characters",
                details=[{"path": "/prompt", "message": "Too long"}],
            )
        since = utcnow() - timedelta(hours=1)
        if await self.repo.count_since(user.id, since) >= settings.ai_generations_per_hour:
            raise AIRateLimitedError(
                "Too many AI generations in the last hour. Please try again later."
            )
        try:
            provider = get_ai_provider()
        except AIProviderError as exc:
            raise AINotConfiguredError(exc.user_message) from exc

        if request.project_id is not None:
            project = await self.projects.get(user, request.project_id)  # ownership (404)
            if await project_busy(self.session, project.id):
                raise GenerationBusyError("A generation is already running for this project")
            names_project = False
        else:
            project = await self.projects.create(user, ProjectCreate(name=NEW_PROJECT_NAME))
            names_project = True

        gen = AIGeneration(
            project_id=project.id,
            user_id=user.id,
            kind="building_generation",
            status="queued",
            stage="queued",
            prompt=prompt,
            options=request.options.model_dump(mode="json"),
            provider=provider.name,
            model=provider.model,
            prompt_version=PROMPT_VERSION,
            seed=request.options.seed,
            rules_profile=project.rules_profile_id,
            names_project=names_project,
            warnings=[],
            clarification_questions=[],
        )
        self.repo.add(gen)
        await self.session.commit()
        await self.session.refresh(gen)
        gen_id = gen.id
        job_runner.submit(f"ai-generate:{gen_id}", lambda: run_ai_generation(gen_id))
        return await self._out(gen)

    async def get(self, user: User, generation_id: uuid.UUID) -> AIGenerationOut:
        gen = await self.repo.get(generation_id)
        if gen is None or gen.user_id != user.id:  # 404, not 403: ids can't be probed
            raise NotFoundError("Generation not found")
        await self.projects.get(user, gen.project_id)  # deleted projects hide their history
        return await self._out(gen)

    async def list_for_project(
        self, user: User, project_id: uuid.UUID
    ) -> list[AIGenerationSummaryOut]:
        await self.projects.get(user, project_id)
        rows = await self.repo.list_for_project(project_id)
        numbers = await self._version_numbers([r.version_id for r in rows if r.version_id])
        return [
            AIGenerationSummaryOut(**_summary_fields(r), version_number=numbers.get(r.version_id))
            for r in rows
        ]

    async def _version_numbers(self, ids: list[uuid.UUID]) -> dict[uuid.UUID | None, int]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(ProjectVersion.id, ProjectVersion.number).where(ProjectVersion.id.in_(ids))
        )
        return {row.id: row.number for row in result}

    async def _out(self, gen: AIGeneration) -> AIGenerationOut:
        spec = BuildingSpecification.model_validate(gen.spec) if gen.spec else None
        summary: ModelSummary | None = None
        number: int | None = None
        if gen.version_id is not None:
            row = (
                await self.session.execute(
                    select(ProjectVersion.number, ProjectVersion.summary).where(
                        ProjectVersion.id == gen.version_id
                    )
                )
            ).first()
            if row is not None:
                number = row.number
                summary = ModelSummary.model_validate(row.summary)
        checks = (
            requirement_checks(spec, summary, area_tolerance=GFA_WARNING_THRESHOLD)
            if spec is not None and summary is not None
            else []
        )
        return AIGenerationOut(
            **_summary_fields(gen),
            version_number=number,
            options=gen.options,
            prompt_version=gen.prompt_version,
            seed=gen.seed,
            rules_profile=gen.rules_profile,
            engine_version=gen.engine_version,
            specification=spec,
            assumptions=list(spec.assumptions) if spec else [],
            warnings=[Issue.model_validate(w) for w in gen.warnings or []],
            summary=summary,
            checks=checks,
            input_tokens=gen.input_tokens,
            output_tokens=gen.output_tokens,
            started_at=gen.started_at,
        )


def _summary_fields(gen: AIGeneration) -> dict[str, Any]:
    return {
        "id": gen.id,
        "project_id": gen.project_id,
        "status": gen.status,
        "stage": gen.stage,
        "prompt": gen.prompt,
        "provider": gen.provider,
        "model": gen.model,
        "understanding": gen.understanding,
        "version_id": gen.version_id,
        "clarification_questions": list(gen.clarification_questions or []),
        "error": GenerationErrorOut.model_validate(gen.error) if gen.error else None,
        "repair_count": gen.repair_count,
        "duration_ms": gen.duration_ms,
        "created_at": gen.created_at,
        "finished_at": gen.finished_at,
    }
