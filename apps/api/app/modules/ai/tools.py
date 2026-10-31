"""Read-only AI tools (scaffolding for natural-language modification, roadmap Phase 5).

A tool is an approved, typed, read-only operation a model may request: validated input model,
structured output model, and an ownership-checked project scope. Tools never expose the
database, SQL, files or model geometry beyond compact digests (`context.py`).

Phase 3 does not hand tools to a model yet — generation needs one structured call — but the
registry is exercised by tests so Phase 5 can pass `TOOLS` to a provider as-is.
"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.modules.ai.context import (
    ElementDigest,
    ProjectContext,
    RoomDigest,
    VersionDigest,
    build_project_context,
    element_digest,
)
from app.modules.auth.models import User
from app.modules.building.migrations import load_model
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import ModelSummary
from app.modules.projects.service import ProjectService
from app.modules.versions.repository import VersionRepository


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NoInput(ToolInput):
    pass


class RoomInput(ToolInput):
    ref: str = Field(min_length=1, max_length=60)  # short ref ("R3") or room UUID


class ElementInput(ToolInput):
    element_id: uuid.UUID


class ProjectOut(ToolInput):
    id: uuid.UUID
    name: str
    region_code: str
    currency: str
    rules_profile: str
    version: VersionDigest | None


@dataclass
class ToolScope:
    """What a tool may see: one project of one user (ownership already verified)."""

    context: ProjectContext
    model: BuildingModel | None
    selected_id: uuid.UUID | None


@dataclass(frozen=True)
class AITool:
    name: str
    description: str
    input_model: type[ToolInput]
    run: Callable[[ToolScope, Any], Awaitable[BaseModel | None]]

    def input_schema(self) -> dict[str, Any]:
        return self.input_model.model_json_schema()


async def _get_project(scope: ToolScope, _: NoInput) -> ProjectOut:
    c = scope.context
    return ProjectOut(
        id=c.project_id,
        name=c.project_name,
        region_code=c.region_code,
        currency=c.currency,
        rules_profile=c.rules_profile,
        version=c.version,
    )


async def _get_building_summary(scope: ToolScope, _: NoInput) -> ModelSummary | None:
    return scope.context.summary


async def _get_room(scope: ToolScope, data: RoomInput) -> RoomDigest | None:
    return next(
        (r for r in scope.context.rooms if data.ref in (r.ref, str(r.id))),
        None,
    )


async def _get_selected_object(scope: ToolScope, _: NoInput) -> ElementDigest | None:
    return scope.context.selected


async def _get_element(scope: ToolScope, data: ElementInput) -> ElementDigest | None:
    return element_digest(scope.model, data.element_id) if scope.model else None


TOOLS: dict[str, AITool] = {
    t.name: t
    for t in (
        AITool(
            "get_project", "Project name, region, currency, rules profile.", NoInput, _get_project
        ),
        AITool(
            "get_building_summary",
            "Storeys, floor areas and room/element counts of the current version.",
            NoInput,
            _get_building_summary,
        ),
        AITool("get_room", "One room by short ref (R3) or id.", RoomInput, _get_room),
        AITool(
            "get_selected_object",
            "The element the user has selected in the viewer, if any.",
            NoInput,
            _get_selected_object,
        ),
        AITool("get_element", "One element by id (compact digest).", ElementInput, _get_element),
    )
}
# get_cost_summary arrives with the costing engine (roadmap Phase 4).


class UnknownToolError(Exception):
    pass


async def run_tool(scope: ToolScope, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
    """Validate the arguments and run an approved tool. Raises UnknownToolError /
    pydantic.ValidationError on anything else."""
    tool = TOOLS.get(name)
    if tool is None:
        raise UnknownToolError(name)
    data = tool.input_model.model_validate(arguments)
    result = await tool.run(scope, data)
    return result.model_dump(mode="json") if result is not None else None


async def load_scope(
    session: AsyncSession,
    user: User,
    project_id: uuid.UUID,
    *,
    version_id: uuid.UUID | None = None,
    selected_id: uuid.UUID | None = None,
) -> ToolScope:
    """Build the tool scope for a project the user owns (404 otherwise)."""
    project = await ProjectService(session).get(user, project_id)
    vid = version_id or project.current_version_id
    row = await VersionRepository(session).get(project.id, vid) if vid else None
    if vid is not None and row is None:
        raise NotFoundError("Version not found")
    model = load_model(row.model) if row else None
    spec = BuildingSpecification.model_validate(row.spec) if row and row.spec else None
    context = build_project_context(
        project_id=project.id,
        project_name=project.name,
        region_code=project.region_code,
        currency=project.currency,
        rules_profile=project.rules_profile_id,
        version=VersionDigest(
            id=row.id,
            number=row.number,
            label=row.label,
            source=row.source,
            engine_version=row.engine_version,
            seed=row.seed,
        )
        if row
        else None,
        model=model,
        spec=spec,
        selected_id=selected_id,
    )
    return ToolScope(context=context, model=model, selected_id=selected_id)
