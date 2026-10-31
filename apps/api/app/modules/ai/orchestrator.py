"""BuildingGenerationService: natural language -> validated spec -> layout -> new version.

Runs in the background (in-process job runner, ADR-010) and records its real stage on the
`ai_generations` row, which the client polls:

    queued -> interpreting -> validating [-> repairing -> validating] -> layout -> checking
           -> saving -> done        (or needs_clarification / failed at any point)

It orchestrates only: interpretation lives in `interpreter.py`, spatial decisions in the layout
engine, persistence of versions in `generation.pipeline`. Failures are recorded with a distinct
code and a user-safe message; technical detail goes to the server log.
"""

import hashlib
import logging
import time
import uuid
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_sessionmaker, utcnow
from app.modules.ai.context import generation_context
from app.modules.ai.errors import AIProviderError
from app.modules.ai.interpreter import (
    AttemptRecord,
    Interpretation,
    InterpretationError,
    check_options,
    interpret,
)
from app.modules.ai.models import AIGeneration, AIRun
from app.modules.ai.providers import get_ai_provider
from app.modules.ai.schemas.generation import GenerationOptions, InterpretationOutcome
from app.modules.auth.models import User
from app.modules.building.design import check_design
from app.modules.building.issues import Issue
from app.modules.building.specification import BuildingSpecification
from app.modules.generation.pipeline import available_design_systems, layout_and_save
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.layout.engine import LayoutError
from app.modules.projects.models import Project
from app.modules.rules.spec_checks import check_spec
from app.modules.versions.schemas import GenerationProvenance
from app.shared.data_files import rules_profile

logger = logging.getLogger(__name__)

LAYOUT_MESSAGES = {
    "LAYOUT_INFEASIBLE": "The requested requirements could not produce a valid layout.",
    "LAYOUT_REQUIREMENTS_UNMET": "No layout meets every mandatory requirement of this request; "
    "none of them was relaxed.",
    "LAYOUT_INVALID": "The layout engine could not produce a valid building for this request.",
    "MODEL_INVALID": "The layout engine could not produce a valid building for this request.",
}


def _details(issues: list[Issue]) -> list[dict[str, Any]]:
    return [i.model_dump(mode="json", exclude_none=True) for i in issues]


def _run_row(gen: AIGeneration, attempt: AttemptRecord) -> AIRun:
    return AIRun(
        generation_id=gen.id,
        project_id=gen.project_id,
        user_id=gen.user_id,
        task=attempt.task.value,
        provider=attempt.provider,
        model=attempt.model,
        prompt_version=attempt.prompt_version,
        status=attempt.status,
        error_code=attempt.error_code,
        raw_output=attempt.raw_output,
        parsed_output=attempt.parsed_output,
        issues=_details(attempt.issues),
        input_tokens=attempt.input_tokens,
        output_tokens=attempt.output_tokens,
        latency_ms=attempt.latency_ms,
    )


def _record_attempts(
    session: AsyncSession, gen: AIGeneration, attempts: list[AttemptRecord]
) -> None:
    for attempt in attempts:
        session.add(_run_row(gen, attempt))
        # Provider-reported cost is logged only (no billing storage); never includes secrets.
        logger.info(
            "ai_run generation=%s task=%s provider=%s model=%s status=%s code=%s ms=%s "
            "tokens_in=%s tokens_out=%s cost_usd=%s",
            gen.id,
            attempt.task.value,
            attempt.provider,
            attempt.model,
            attempt.status,
            attempt.error_code or "-",
            attempt.latency_ms,
            attempt.input_tokens,
            attempt.output_tokens,
            attempt.cost_usd if attempt.cost_usd is not None else "-",
        )
    gen.repair_count = sum(a.task.value == "repair_specification" for a in attempts)
    gen.input_tokens = sum(a.input_tokens for a in attempts)
    gen.output_tokens = sum(a.output_tokens for a in attempts)
    if attempts:
        gen.model = attempts[-1].model[:100]


class BuildingGenerationService:
    def __init__(self, session: AsyncSession, gen: AIGeneration) -> None:
        self.session = session
        self.gen = gen
        self.started = time.perf_counter()

    async def stage(self, name: str) -> None:
        self.gen.stage = name
        await self.session.commit()

    async def finish(
        self,
        status: str,
        *,
        code: str | None = None,
        message: str | None = None,
        issues: list[Issue] | None = None,
    ) -> None:
        gen = self.gen
        gen.status = status
        gen.finished_at = utcnow()
        gen.duration_ms = round((time.perf_counter() - self.started) * 1000)
        if code is not None:
            gen.error = {
                "code": code,
                "message": message or code,
                "details": _details(issues or []),
            }
        await self.session.commit()
        self._log(code)

    def _log(self, code: str | None) -> None:
        gen = self.gen
        prompt_info = (
            f"prompt={gen.prompt!r}"
            if get_settings().ai_log_prompts
            else f"prompt_chars={len(gen.prompt)} "
            f"prompt_sha={hashlib.sha256(gen.prompt.encode()).hexdigest()[:12]}"
        )
        logger.info(
            "ai_generation id=%s project=%s provider=%s model=%s status=%s code=%s stage=%s "
            "ms=%s repairs=%s tokens_in=%s tokens_out=%s warnings=%s version=%s %s",
            gen.id,
            gen.project_id,
            gen.provider,
            gen.model,
            gen.status,
            code or "-",
            gen.stage,
            gen.duration_ms,
            gen.repair_count,
            gen.input_tokens,
            gen.output_tokens,
            len(gen.warnings or []),
            gen.version_id or "-",
            prompt_info,
        )

    async def run(self, project: Project, user: User | None) -> None:
        gen = self.gen
        settings = get_settings()
        gen.status = "running"
        gen.started_at = utcnow()
        await self.stage("interpreting")

        profile = rules_profile(settings.data_dir, project.rules_profile_id)
        options = GenerationOptions.model_validate(gen.options)
        designs = available_design_systems()  # usable (approved) design systems only (K3)

        def validate_spec(spec: BuildingSpecification) -> list[Issue]:
            return (
                check_spec(spec, profile, floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)
                + check_design(spec, designs)
                + check_options(spec, options)
            )

        try:
            provider = get_ai_provider()
            interpretation = await interpret(
                gen.prompt,
                provider=provider,
                options=options,
                context=generation_context(
                    region_code=project.region_code,
                    currency=project.currency,
                    profile=profile,
                    design_systems=designs,
                ),
                validate_spec=validate_spec,
                max_repairs=settings.ai_max_repairs,
                max_tokens=settings.ai_max_output_tokens,
                on_stage=self.stage,
            )
        except AIProviderError as exc:  # provider could not be created (configuration)
            logger.error("ai_generation id=%s provider error: %s", gen.id, exc.detail)
            await self.finish("failed", code=exc.code, message=exc.user_message)
            return
        except InterpretationError as exc:
            if isinstance(exc.__cause__, AIProviderError):  # technical detail: server log only
                logger.error("ai_generation id=%s provider error: %s", gen.id, exc.__cause__.detail)
            _record_attempts(self.session, gen, exc.attempts)
            await self.finish("failed", code=exc.code, message=exc.message, issues=exc.issues)
            return
        _record_attempts(self.session, gen, interpretation.attempts)
        await self._interpreted(interpretation, project, user)

    async def _interpreted(
        self, interpretation: Interpretation, project: Project, user: User | None
    ) -> None:
        gen = self.gen
        draft = interpretation.draft
        gen.understanding = draft.understanding
        gen.warnings = _details(interpretation.warnings)
        if draft.outcome is InterpretationOutcome.CLARIFICATION or interpretation.spec is None:
            gen.clarification_questions = list(draft.clarification_questions)
            gen.stage = "done"
            await self.finish("needs_clarification")
            return
        spec = interpretation.spec
        gen.spec = spec.model_dump(mode="json")
        if gen.names_project:
            project.name = spec.name[:200]
        await self.session.commit()

        gen_id, project_id = gen.id, project.id
        try:
            result = await layout_and_save(
                self.session,
                project,
                user,
                spec=spec,
                seed=gen.seed,
                label=f"AI · {spec.name}"[:200],
                source="ai_generation",
                spec_warnings=interpretation.spec_warnings,
                extra_warnings=interpretation.warnings,
                prompt=gen.prompt,
                provenance=GenerationProvenance(
                    generation_id=gen.id,
                    provider=gen.provider,
                    model=gen.model,
                    prompt_version=gen.prompt_version,
                ),
                on_stage=self.stage,
            )
        except LayoutError as exc:
            await self._fail_after_rollback(
                gen_id, exc.code, LAYOUT_MESSAGES.get(exc.code, exc.message), exc.issues
            )
            return
        except SQLAlchemyError:
            logger.exception("ai_generation id=%s project=%s database error", gen_id, project_id)
            await self._fail_after_rollback(
                gen_id, "DATABASE_ERROR", "The design could not be saved. Please try again.", []
            )
            return
        gen.version_id = result.version.id
        gen.engine_version = result.version.engine_version
        gen.warnings = _details(result.report.warnings)
        gen.stage = "done"
        await self.finish("completed")

    async def _fail_after_rollback(
        self, gen_id: uuid.UUID, code: str, message: str, issues: list[Issue]
    ) -> None:
        await self.session.rollback()
        gen = await self.session.get(AIGeneration, gen_id)
        if gen is None:
            return
        self.gen = gen
        await self.finish("failed", code=code, message=message, issues=issues)


async def run_ai_generation(generation_id: uuid.UUID) -> None:
    async with get_sessionmaker()() as session:
        gen = await session.get(AIGeneration, generation_id)
        if gen is None:
            return
        service = BuildingGenerationService(session, gen)
        project = await session.get(Project, gen.project_id)
        user = await session.get(User, gen.user_id)
        if project is None or project.deleted_at is not None:
            await service.finish(
                "failed", code="PROJECT_NOT_FOUND", message="The project no longer exists"
            )
            return
        try:
            await service.run(project, user)
        except Exception:
            logger.exception("ai_generation id=%s crashed", generation_id)
            await service._fail_after_rollback(
                generation_id, "INTERNAL_ERROR", "Generation failed because of a server error.", []
            )
