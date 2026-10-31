"""Plan editing use cases: preview a batch of operations on a version, or save it as a new one.

The client keeps the list of operations of an editing session (undo/redo is a cursor into that
list) and sends the whole list each time; the server replays it on the stored base version.
Nothing the client renders is trusted: the model it shows is always one the server built and
validated. Saving replays the same list once more and stores the result as an immutable version
(source `manual`, parent = the base version, `operations` = the list).
"""

import asyncio
import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError, NotFoundError
from app.modules.auth.models import User
from app.modules.building.migrations import load_model
from app.modules.building.operations import Operation
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.modules.editing.schemas import EditPreviewOut, EditRejectionOut
from app.modules.projects.service import ProjectService
from app.modules.versions.models import ProjectVersion
from app.modules.versions.repository import VersionRepository
from app.modules.versions.schemas import VersionOut
from app.modules.versions.service import VersionService
from app.shared.data_files import material_ids, rules_profile


class EditRejectedError(AppError):
    status_code = 422
    code = "EDIT_REJECTED"


def _rejection_out(outcome: EditOutcome) -> EditRejectionOut | None:
    r = outcome.rejection
    if r is None:
        return None
    return EditRejectionOut(
        code=r.code,
        message=r.message,
        index=r.index,
        element_id=r.element_id,
        related_ids=r.related_ids,
        issues=r.issues,
    )


class EditingService:
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

    async def _evaluate(self, row: ProjectVersion, operations: Sequence[Operation]) -> EditOutcome:
        data_dir = get_settings().data_dir
        model = load_model(row.model)
        return await asyncio.to_thread(
            evaluate_edits,
            model,
            operations,
            rules_profile(data_dir, row.rules_profile),
            material_ids(data_dir),
            spec=BuildingSpecification.model_validate(row.spec) if row.spec else None,
            cache_key=(str(row.id), row.model_hash),
        )

    async def preview(
        self,
        user: User,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        operations: Sequence[Operation],
    ) -> EditPreviewOut:
        row = await self._base(user, project_id, version_id)
        outcome = await self._evaluate(row, operations)
        return EditPreviewOut(
            valid=outcome.model is not None,
            model=outcome.model,
            summary=summarize(outcome.model) if outcome.model else None,
            warnings=outcome.warnings,
            changed_ids=outcome.changed_ids,
            rejection=_rejection_out(outcome),
        )

    async def save(
        self,
        user: User,
        project_id: uuid.UUID,
        version_id: uuid.UUID,
        operations: Sequence[Operation],
        label: str | None,
    ) -> VersionOut:
        row = await self._base(user, project_id, version_id)
        outcome = await self._evaluate(row, operations)
        rejection = _rejection_out(outcome)
        if outcome.model is None or rejection is not None:
            message = rejection.message if rejection else "The edits could not be applied"
            details = [rejection.model_dump(mode="json")] if rejection else []
            raise EditRejectedError(message, details=details)
        project = await self.projects.get(user, project_id)
        versions = VersionService(self.session)
        n = len(operations)
        version = await versions.create(
            project,
            user,
            model=outcome.model,
            spec=BuildingSpecification.model_validate(row.spec) if row.spec else None,
            source="manual",
            label=label or f"Plan edits on v{row.number} ({n} change{'s' if n != 1 else ''})",
            rules_profile_ref=row.rules_profile,
            prompt=row.prompt,
            operations=[op.model_dump(mode="json") for op in operations],
            parent_version_id=row.id,
        )
        return await versions.get(user, project_id, version.id)
