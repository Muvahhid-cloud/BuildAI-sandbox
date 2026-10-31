"""Spec -> layout -> checks -> new version: the step shared by the spec-form job (Phase 2) and
AI generation (Phase 3). It never interprets language and contains no layout logic itself.

    selected design system (K3): approved snapshot + its role mapping's type set, or
    approved component types (catalog resolver, K2; none approved = untyped)
      -> type set vs rules profile (invalid types are refused, never resized)
      -> layout patterns (Design Intelligence V1: soft heuristics, drafts included and
         reported with their status; catalog.patterns)
      -> layout engine (tier-3 feasibility + model invariants + evaluation of the built
         candidates against the spec, in a worker thread)
      -> final model validation (errors abort) -> rules findings -> immutable version
"""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.modules.auth.models import User
from app.modules.building.design import DesignCatalog, check_design
from app.modules.building.issues import Issue, errors
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import validate_model
from app.modules.catalog.design_systems import design_catalog, resolve_design
from app.modules.catalog.loader import load_knowledge
from app.modules.catalog.patterns import pattern_library
from app.modules.catalog.resolver import resolve_type_set
from app.modules.layout.engine import LayoutError, LayoutResult, generate_layout
from app.modules.projects.models import Project
from app.modules.rules.model_checks import check_model
from app.modules.rules.type_checks import check_type_set
from app.modules.versions.models import ProjectVersion
from app.modules.versions.schemas import (
    CandidateOut,
    GenerationProvenance,
    GenerationReport,
    PatternUse,
    TopologyOut,
)
from app.modules.versions.service import VersionService
from app.shared.data_files import material_ids, rules_profile

StageCallback = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class PipelineResult:
    version: ProjectVersion
    report: GenerationReport
    layout: LayoutResult


async def _noop(_: str) -> None:
    return None


def available_design_systems() -> DesignCatalog:
    """Usable (approved, complete) design systems and why the others are not usable (K3).

    The only way the rest of the application (spec checks, AI prompt context, the web) learns
    about design systems: plain building-level snapshots, never catalog records."""
    return design_catalog(load_knowledge(get_settings().data_dir))


def check_spec_design(spec: BuildingSpecification) -> list[Issue]:
    """Tier-2 design-system checks of `spec` against the current catalog."""
    return check_design(spec, available_design_systems())


async def layout_and_save(
    session: AsyncSession,
    project: Project,
    user: User | None,
    *,
    spec: BuildingSpecification,
    seed: int,
    label: str,
    source: str,
    spec_warnings: list[Issue],
    extra_warnings: list[Issue] | None = None,
    prompt: str | None = None,
    provenance: GenerationProvenance | None = None,
    on_stage: StageCallback = _noop,
) -> PipelineResult:
    """Run the layout engine for `spec` and store the result as the project's new version.

    Raises LayoutError (LAYOUT_INFEASIBLE / LAYOUT_REQUIREMENTS_UNMET / LAYOUT_INVALID /
    MODEL_INVALID). Commits."""
    data_dir = get_settings().data_dir
    project_id: uuid.UUID = project.id
    profile = rules_profile(data_dir, project.rules_profile_id)
    materials = material_ids(data_dir)
    registry = load_knowledge(data_dir)
    design_system = None
    if spec.style.design_system is not None:
        # Tier-2 checks (check_design) already refused unknown/unapproved systems; this is the
        # last line of defence and never substitutes another system.
        resolution = resolve_design(registry, spec.style.design_system)
        if resolution.snapshot is None or resolution.types is None:
            raise LayoutError(
                "LAYOUT_INFEASIBLE",
                "The selected design system cannot be used",
                [
                    Issue(
                        severity="error",
                        code="DESIGN_SYSTEM_NOT_APPROVED",
                        path="/style/design_system",
                        message=f"{spec.style.design_system}: {resolution.reason}",
                    )
                ],
            )
        design_system = resolution.snapshot
        type_set = resolution.types.type_set
    else:
        type_set = resolve_type_set(registry).type_set
    if type_set is not None:
        type_issues = check_type_set(type_set, profile)
        if type_issues:
            raise LayoutError(
                "LAYOUT_INFEASIBLE",
                "The approved component types do not meet the rules profile",
                type_issues,
            )
    await on_stage("layout")
    result = await asyncio.to_thread(
        generate_layout,
        spec,
        profile,
        id_namespace=project_id,
        seed=seed,
        material_ids=materials,
        type_set=type_set,
        design_system=design_system,
        patterns=pattern_library(registry),
    )
    await on_stage("checking")
    model_errors = errors(validate_model(result.model, material_ids=materials))
    if model_errors:  # the engine validates its candidates; this is a last line of defence
        raise LayoutError(
            "MODEL_INVALID", "The generated building model failed validation", model_errors
        )
    findings = check_model(result.model, profile)
    report = GenerationReport(
        warnings=(extra_warnings or []) + spec_warnings + result.warnings + findings,
        notes=result.notes,
        metrics=asdict(result.metrics) if result.metrics else {},
        generation=provenance,
        evaluation=result.evaluation,
        patterns=[PatternUse(**asdict(p)) for p in result.patterns],
        candidates=[CandidateOut(**asdict(c)) for c in result.candidates],
        topology=TopologyOut(**asdict(result.topology)) if result.topology else None,
    )
    await on_stage("saving")
    version = await VersionService(session).create(
        project,
        user,
        model=result.model,
        spec=spec,
        source=source,
        label=label,
        rules_profile_ref=profile.ref,
        prompt=prompt,
        report=report,
    )
    return PipelineResult(version=version, report=report, layout=result)
