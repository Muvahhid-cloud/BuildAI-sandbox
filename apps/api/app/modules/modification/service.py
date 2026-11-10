"""AI-assisted modification use cases (Phase 5, docs/ai-pipeline.md §11).

`plan`: the AI interprets the request against the digest of the session's current model; the
deterministic resolver turns the interpretation into typed editing operations, asks what is
unclear and validates the candidate. `resolve`: the same resolution again with the user's answers
— no AI call, so answers cannot change the interpretation. Nothing is stored here: applying a
plan is a normal edit save (POST .../edits with source `ai_modification`).
"""

import asyncio
import uuid
from collections.abc import Sequence

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.modules.ai.errors import AIConfigurationError, AIProviderError
from app.modules.ai.modification import (
    ModificationInterpretation,
    ModificationInterpretationError,
    draft_issues,
    interpret_modification,
)
from app.modules.ai.modification_context import build_modification_context
from app.modules.ai.providers import get_ai_provider
from app.modules.ai.schemas.modification import ModificationDraft
from app.modules.ai.service import clean_prompt
from app.modules.auth.models import User
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.operations import Operation
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.editing.evaluate import evaluate_edits
from app.modules.editing.schemas import EditPreviewOut
from app.modules.editing.service import rejection_out
from app.modules.modification.resolve import Resolution, resolve_draft
from app.modules.modification.schemas import (
    ModifyAnswer,
    ModifyPlanOut,
    ModifyPlanRequest,
    ModifyResolveRequest,
    PlanStatus,
)
from app.modules.projects.service import ProjectService
from app.modules.versions.models import ProjectVersion
from app.modules.versions.repository import VersionRepository
from app.shared.data_files import material_ids, rules_profile


class ModificationUnavailableError(AppError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "AI_UNAVAILABLE"


class ModificationTimeoutError(AppError):
    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    code = "AI_TIMEOUT"


class ModificationInvalidError(AppError):
    status_code = status.HTTP_422_UNPROCESSABLE_CONTENT
    code = "AI_MODIFICATION_INVALID"


class SessionInvalidError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "EDIT_SESSION_INVALID"


def _status(resolution: Resolution, unsupported: int) -> PlanStatus:
    if resolution.questions:
        return "needs_clarification"
    planned = sum(1 for c in resolution.changes if c.status == "planned")
    if planned == 0:
        return "nothing_to_apply"
    if planned < len(resolution.changes) or unsupported:
        return "partial"
    return "ready"


class ModificationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.projects = ProjectService(session)
        self.repo = VersionRepository(session)

    async def _base(
        self, user: User, project_id: uuid.UUID, version_id: uuid.UUID
    ) -> ProjectVersion:
        await self.projects.get(user, project_id)  # ownership
        row = await self.repo.get(project_id, version_id)
        if row is None:
            raise NotFoundError("Version not found")
        return row

    def _session_model(
        self, row: ProjectVersion, base: BuildingModel, ops: Sequence[Operation]
    ) -> BuildingModel:
        if not ops:
            return base
        data_dir = get_settings().data_dir
        outcome = evaluate_edits(
            base,
            ops,
            rules_profile(data_dir, row.rules_profile),
            material_ids(data_dir),
            spec=BuildingSpecification.model_validate(row.spec) if row.spec else None,
            cache_key=(str(row.id), row.model_hash),
        )
        if outcome.model is None:
            raise SessionInvalidError(
                "The unsaved plan edits of this session are no longer valid; discard them first."
            )
        return outcome.model

    def _resolve(
        self,
        row: ProjectVersion,
        base: BuildingModel,
        draft: ModificationDraft,
        ops: Sequence[Operation],
        answers: Sequence[ModifyAnswer],
    ) -> Resolution:
        data_dir = get_settings().data_dir
        try:
            return resolve_draft(
                draft,
                base=base,
                session_ops=ops,
                answers=answers,
                profile=rules_profile(data_dir, row.rules_profile),
                materials=material_ids(data_dir),
                spec=BuildingSpecification.model_validate(row.spec) if row.spec else None,
                cache_key=(str(row.id), row.model_hash),
            )
        except ValueError as err:
            raise SessionInvalidError(str(err)) from err

    def _out(
        self,
        prompt: str,
        draft: ModificationDraft,
        answers: Sequence[ModifyAnswer],
        resolution: Resolution,
        interpretation: ModificationInterpretation | None,
    ) -> ModifyPlanOut:
        outcome = resolution.outcome
        preview = None
        if outcome is not None and resolution.operations:
            preview = EditPreviewOut(
                valid=outcome.model is not None,
                model=outcome.model,
                summary=summarize(outcome.model) if outcome.model else None,
                warnings=outcome.warnings,
                changed_ids=outcome.changed_ids,
                rejection=rejection_out(outcome),
            )
        return ModifyPlanOut(
            status=_status(resolution, len(draft.unsupported)),
            prompt=prompt,
            understanding=draft.understanding,
            draft=draft,
            answers=list(answers),
            changes=resolution.changes,
            unsupported=draft.unsupported,
            questions=resolution.questions,
            operations=resolution.operations,
            preview=preview,
            diff=resolution.diff,
            provider=interpretation.provider if interpretation else None,
            model=interpretation.model if interpretation else None,
            prompt_version=interpretation.prompt_version if interpretation else None,
        )

    async def plan(
        self,
        user: User,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        request: ModifyPlanRequest,
    ) -> ModifyPlanOut:
        settings = get_settings()
        prompt = clean_prompt(request.prompt)
        if len(prompt) < 3:
            raise ModificationInvalidError("Describe the change in a few words")
        row = await self._base(user, project_id, version_id)
        base = load_model(row.model)
        session_model = await asyncio.to_thread(self._session_model, row, base, request.operations)
        context = build_modification_context(session_model)
        try:
            provider = get_ai_provider()
            interpretation = await asyncio.wait_for(
                interpret_modification(
                    provider,
                    prompt,
                    context=context,
                    max_tokens=min(settings.ai_max_output_tokens, 8000),
                    max_repairs=settings.ai_max_repairs,
                ),
                timeout=settings.ai_timeout_seconds,
            )
        except AIConfigurationError as exc:
            raise ModificationUnavailableError(exc.user_message) from exc
        except AIProviderError as exc:
            raise ModificationUnavailableError(exc.user_message) from exc
        except TimeoutError as exc:
            raise ModificationTimeoutError(
                "The AI service did not answer in time. Please try again."
            ) from exc
        except ModificationInterpretationError as exc:
            raise ModificationInvalidError(
                exc.message, details=[{"path": "", "message": m} for m in exc.issues[:10]]
            ) from exc
        resolution = await asyncio.to_thread(
            self._resolve, row, base, interpretation.draft, request.operations, []
        )
        return self._out(prompt, interpretation.draft, [], resolution, interpretation)

    async def resolve(
        self,
        user: User,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        request: ModifyResolveRequest,
    ) -> ModifyPlanOut:
        row = await self._base(user, project_id, version_id)
        base = load_model(row.model)
        # The draft comes back from the client: validate its references again.
        session_model = await asyncio.to_thread(self._session_model, row, base, request.operations)
        context = build_modification_context(session_model)
        draft, issues = draft_issues(request.draft.model_dump(mode="json"), context)
        if draft is None:
            raise ModificationInvalidError(
                "The interpretation does not match this design any more; plan the request again.",
                details=[{"path": "/draft", "message": m} for m in issues[:10]],
            )
        resolution = await asyncio.to_thread(
            self._resolve, row, base, draft, request.operations, request.answers
        )
        return self._out(clean_prompt(request.prompt), draft, request.answers, resolution, None)
