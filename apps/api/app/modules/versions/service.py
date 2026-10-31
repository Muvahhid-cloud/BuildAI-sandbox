"""Project versions: immutable snapshots of spec + model (docs/database.md §4)."""

import hashlib
import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import NotFoundError
from app.modules.auth.models import User
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.building.validation import validate_model
from app.modules.demo.service import demo_building_model
from app.modules.projects.models import Project
from app.modules.projects.service import ProjectService
from app.modules.rules.model_checks import check_model
from app.modules.versions.models import ProjectVersion
from app.modules.versions.repository import VersionRepository
from app.modules.versions.schemas import GenerationReport, VersionOut, VersionSummaryOut
from app.shared.data_files import material_ids, rules_profile


def model_hash(model: BuildingModel) -> str:
    """sha256 of the canonical model JSON (dedupe / cache keys)."""
    return hashlib.sha256(model.model_dump_json().encode("utf-8")).hexdigest()


class VersionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = VersionRepository(session)
        self.projects = ProjectService(session)

    async def list(self, user: User, project_id: uuid.UUID) -> list[VersionSummaryOut]:
        await self.projects.get(user, project_id)  # ownership
        rows = await self.repo.list_for_project(project_id)
        return [VersionSummaryOut.model_validate(r) for r in rows]

    async def get(self, user: User, project_id: uuid.UUID, version_id: uuid.UUID) -> VersionOut:
        await self.projects.get(user, project_id)
        row = await self.repo.get(project_id, version_id)
        if row is None:
            raise NotFoundError("Version not found")
        model = load_model(row.model)  # upgrade-on-read; the stored row is never rewritten
        data_dir = get_settings().data_dir
        issues = [
            i
            for i in validate_model(model, material_ids=material_ids(data_dir))
            if i.severity == "warning"
        ]
        issues += check_model(model, rules_profile(data_dir, row.rules_profile))
        base = VersionSummaryOut.model_validate(row).model_dump()
        # Derived data is recomputed from the model on read; the stored copy serves lists.
        base["summary"] = summarize(model)
        return VersionOut(
            **base,
            prompt=row.prompt,
            spec=BuildingSpecification.model_validate(row.spec) if row.spec else None,
            model=model,
            report=GenerationReport.model_validate(row.report) if row.report else None,
            issues=issues,
        )

    async def create(
        self,
        project: Project,
        user: User | None,
        *,
        model: BuildingModel,
        spec: BuildingSpecification | None,
        source: str,
        label: str,
        rules_profile_ref: str,
        prompt: str | None = None,
        report: GenerationReport | None = None,
        operations: Sequence[dict[str, Any]] | None = None,
        parent_version_id: uuid.UUID | None = None,
    ) -> ProjectVersion:
        """Append a version and make it the project's current one. Commits.

        `parent_version_id` defaults to the project's current version; edits pass the version
        they were made on, with the `operations` that turn it into this one."""
        version = ProjectVersion(
            project_id=project.id,
            parent_version_id=parent_version_id or project.current_version_id,
            number=await self.repo.next_number(project.id),
            label=label,
            created_by=user.id if user else None,
            source=source,
            prompt=prompt,
            spec=spec.model_dump(mode="json") if spec else None,
            model=model.model_dump(mode="json"),
            operations=[dict(op) for op in operations or ()],
            schema_version=model.schema_version,
            engine_version=model.engine_version,
            rules_profile=rules_profile_ref,
            seed=model.seed,
            model_hash=model_hash(model),
            summary=summarize(model).model_dump(mode="json"),
            report=report.model_dump(mode="json") if report else None,
        )
        self.repo.add(version)
        await self.session.flush()
        project.current_version_id = version.id
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def import_demo(self, user: User, project_id: uuid.UUID) -> VersionOut:
        """Store the hand-authored demo house as a new version of the project."""
        project = await self.projects.get(user, project_id)
        model = demo_building_model(get_settings().data_dir)
        version = await self.create(
            project,
            user,
            model=model,
            spec=None,
            source="fixture",
            label="Demo house (hand-authored)",
            rules_profile_ref=project.rules_profile_id,
        )
        return await self.get(user, project_id, version.id)
