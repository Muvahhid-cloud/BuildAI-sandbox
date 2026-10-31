"""Natural language -> validated BuildingSpecification (docs/ai-pipeline.md §3).

    provider call -> JSON object? -> SpecificationDraft (Pydantic, tier 1)
                  -> spec checks (rules profile tier 2 + form fields)   [validate_spec callback]
                  -> errors? one repair call with the issues -> validate again
                  -> still invalid: InterpretationError (never accepted silently)

Before validation the footprint shape's priority is read from the user's own words
(building/footprint.py normalize_shape_requirement), whichever model answered. Issues that
describe what the engine cannot build for the user's request (USER_LIMITS, e.g. a required
U-shaped footprint) are not sent back for repair: a repair could only drop or soften the
request. The interpretation fails with that reason instead (SPEC_UNSUPPORTED).

No database, no layout: the caller passes a `validate_spec` callback, so this module depends
only on the building schemas. Every provider call is recorded as an `AttemptRecord` (persisted
as an `ai_runs` row by the caller), also when the interpretation fails.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from pydantic import ValidationError

from app.modules.ai.context import GenerationContext
from app.modules.ai.errors import AIProviderError
from app.modules.ai.prompts.shared import PROMPT_VERSION
from app.modules.ai.providers.base import AIProvider
from app.modules.ai.schemas.generation import (
    GenerationOptions,
    InterpretationOutcome,
    SpecificationDraft,
)
from app.modules.ai.structured import AITask, RepairInput, StructuredResult
from app.modules.building.footprint import normalize_shape_requirement
from app.modules.building.issues import Issue, errors, pointer
from app.modules.building.requirements import changed_facts, spec_facts
from app.modules.building.specification import BuildingSpecification

SpecValidator = Callable[[BuildingSpecification], list[Issue]]
StageCallback = Callable[[str], Awaitable[None]]

MAX_RAW_OUTPUT_CHARS = 100_000


@dataclass(frozen=True)
class AttemptRecord:
    task: AITask
    provider: str
    model: str
    prompt_version: str
    status: Literal["ok", "invalid", "error"]
    raw_output: str | None = None
    parsed_output: dict[str, Any] | None = None
    issues: list[Issue] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    error_code: str | None = None
    cost_usd: Decimal | None = None  # provider-reported, when available (logged, not stored)


@dataclass(frozen=True)
class Interpretation:
    draft: SpecificationDraft
    # Tier-2 warnings of the accepted spec (paths relative to the spec), for the version report.
    spec_warnings: list[Issue]
    # AI-level warnings: conflicts, unsupported requests, requirements a repair changed.
    warnings: list[Issue]
    attempts: list[AttemptRecord]

    @property
    def spec(self) -> BuildingSpecification | None:
        return self.draft.specification

    @property
    def repair_count(self) -> int:
        return sum(a.task is AITask.REPAIR_SPECIFICATION for a in self.attempts)


class InterpretationError(Exception):
    """The request could not be turned into a valid specification.

    code: AI_UNAVAILABLE | AI_TIMEOUT | AI_NOT_CONFIGURED (provider), AI_INVALID_OUTPUT (no
    usable JSON after repair), SPEC_INVALID (schema or rules errors after repair),
    SPEC_UNSUPPORTED (the request needs something the engine cannot build; no repair)."""

    def __init__(
        self, code: str, message: str, issues: list[Issue], attempts: list[AttemptRecord]
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.issues = issues
        self.attempts = attempts


# Tier-2 error codes that describe the user's request, not a mistake of the model: never
# "repaired" (that could only drop or soften what the user asked for).
USER_LIMITS = frozenset({"SPEC_FOOTPRINT_UNSUPPORTED"})


@dataclass
class _Checked:
    draft: SpecificationDraft | None
    spec_issues: list[Issue]  # tier-2 issues, spec-relative paths
    blocking: list[Issue]  # what must be repaired (paths into the model's answer)
    schema_failure: bool
    notes: list[str] = field(default_factory=list)  # deterministic normalizations applied

    @property
    def user_limits(self) -> list[Issue]:
        return [i for i in errors(self.spec_issues) if i.code in USER_LIMITS]


def check_options(spec: BuildingSpecification, options: GenerationOptions | None) -> list[Issue]:
    """Errors when the spec does not honour the user's explicit form fields."""
    if options is None:
        return []
    issues: list[Issue] = []

    def mismatch(path: str, label: str, wanted: object, got: object) -> None:
        issues.append(
            Issue(
                severity="error",
                code="SPEC_FORM_FIELD_MISMATCH",
                path=path,
                message=f"{label} must be {wanted} (set explicitly by the user), not {got}",
            )
        )

    if options.storeys is not None and spec.targets.storeys != options.storeys:
        mismatch("/targets/storeys", "storeys", options.storeys, spec.targets.storeys)
    gfa = options.gross_floor_area_m2
    if gfa is not None and spec.targets.gross_floor_area_m2 != gfa:
        mismatch(
            "/targets/gross_floor_area_m2",
            "gross_floor_area_m2",
            gfa,
            spec.targets.gross_floor_area_m2,
        )
    style = options.architectural_style
    if style is not None and spec.style.architectural_style != style:
        mismatch(
            "/style/architectural_style",
            "architectural_style",
            style.value,
            spec.style.architectural_style.value,
        )
    if options.budget is not None and spec.budget != options.budget:
        mismatch("/budget", "budget", options.budget.model_dump(mode="json"), spec.budget)
    region = options.region_code
    if region is not None and (spec.site is None or spec.site.region_code != region):
        mismatch(
            "/site/region_code", "site.region_code", region, spec.site and spec.site.region_code
        )
    return issues


def _pydantic_issues(exc: ValidationError) -> list[Issue]:
    return [
        Issue(
            severity="error",
            code="AI_SCHEMA_INVALID",
            path=pointer(*[str(p) for p in err["loc"]]),
            message=err["msg"],
        )
        for err in exc.errors(include_url=False)
    ]


def _check(result: StructuredResult, validate_spec: SpecValidator) -> _Checked:
    if result.data is None:
        reason = f" (stop reason: {result.stop_reason})" if result.stop_reason else ""
        issue = Issue(
            severity="error",
            code="AI_OUTPUT_NOT_JSON",
            path="",
            message=f"The answer was not a single JSON object{reason}",
        )
        return _Checked(None, [], [issue], schema_failure=True)
    try:
        draft = SpecificationDraft.model_validate(result.data)
    except ValidationError as exc:
        return _Checked(None, [], _pydantic_issues(exc), schema_failure=True)
    if draft.outcome is InterpretationOutcome.CLARIFICATION or draft.specification is None:
        return _Checked(draft, [], [], schema_failure=False)
    spec, note = normalize_shape_requirement(draft.specification)
    draft = draft.model_copy(update={"specification": spec})
    spec_issues = validate_spec(spec)
    blocking = [
        i.model_copy(update={"path": "/specification" + i.path}) for i in errors(spec_issues)
    ]
    return _Checked(
        draft, spec_issues, blocking, schema_failure=False, notes=[note] if note else []
    )


def _record(
    provider: AIProvider,
    task: AITask,
    prompt_version: str,
    result: StructuredResult,
    checked: _Checked,
) -> AttemptRecord:
    return AttemptRecord(
        task=task,
        provider=provider.name,
        model=result.model,
        prompt_version=prompt_version,
        status="invalid" if checked.blocking else "ok",
        raw_output=result.raw_output[:MAX_RAW_OUTPUT_CHARS],
        parsed_output=result.data,
        issues=checked.blocking,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
        cost_usd=result.cost_usd,
    )


def _warn(code: str, message: str) -> Issue:
    return Issue(severity="warning", code=code, path="", message=message)


async def interpret(
    prompt: str,
    *,
    provider: AIProvider,
    options: GenerationOptions | None,
    context: GenerationContext,
    validate_spec: SpecValidator,
    max_repairs: int = 1,
    max_tokens: int = 16000,
    on_stage: StageCallback | None = None,
) -> Interpretation:
    attempts: list[AttemptRecord] = []

    async def stage(name: str) -> None:
        if on_stage is not None:
            await on_stage(name)

    async def call(task: AITask, repair: RepairInput | None) -> StructuredResult:
        try:
            if repair is None:
                return await provider.generate_building_specification(
                    prompt, options=options, context=context, max_tokens=max_tokens
                )
            return await provider.repair_building_specification(
                prompt, options=options, context=context, repair=repair, max_tokens=max_tokens
            )
        except AIProviderError as exc:
            attempts.append(
                AttemptRecord(
                    task=task,
                    provider=provider.name,
                    model=provider.model,
                    prompt_version=PROMPT_VERSION,
                    status="error",
                    error_code=exc.code,
                )
            )
            raise InterpretationError(exc.code, exc.user_message, [], attempts) from exc

    await stage("interpreting")
    result = await call(AITask.GENERATE_SPECIFICATION, None)
    await stage("validating")
    checked = _check(result, validate_spec)
    attempts.append(
        _record(provider, AITask.GENERATE_SPECIFICATION, PROMPT_VERSION, result, checked)
    )
    first = checked

    repairs = 0
    while checked.blocking and not checked.user_limits and repairs < max_repairs:
        repairs += 1
        await stage("repairing")
        repair = RepairInput(
            previous_output=result.raw_output,
            issues=tuple(f"{i.path or '/'}: {i.message}" for i in checked.blocking),
        )
        result = await call(AITask.REPAIR_SPECIFICATION, repair)
        await stage("validating")
        checked = _check(result, validate_spec)
        attempts.append(
            _record(provider, AITask.REPAIR_SPECIFICATION, PROMPT_VERSION, result, checked)
        )

    if checked.user_limits:
        raise InterpretationError(
            "SPEC_UNSUPPORTED",
            "The requested building cannot be generated: " + checked.user_limits[0].message,
            checked.user_limits,
            attempts,
        )
    if checked.blocking or checked.draft is None:
        if checked.schema_failure:
            raise InterpretationError(
                "AI_INVALID_OUTPUT",
                "The AI answer could not be turned into a valid building specification.",
                checked.blocking,
                attempts,
            )
        raise InterpretationError(
            "SPEC_INVALID",
            "The requested building specification could not be validated.",
            errors(checked.spec_issues),
            attempts,
        )

    draft = checked.draft
    warnings = [_warn("AI_REQUIREMENT_CONFLICT", c) for c in draft.conflicts]
    warnings += [_warn("AI_UNSUPPORTED_REQUEST", u) for u in draft.unsupported_requests]
    warnings += [_warn("AI_SHAPE_PRIORITY", n) for n in checked.notes]
    if (
        repairs
        and draft.specification is not None
        and first.draft is not None
        and first.draft.specification is not None
    ):
        before = spec_facts(first.draft.specification)
        after = spec_facts(draft.specification)
        warnings += [
            _warn(
                "AI_REPAIR_CHANGED",
                f"The automatic correction changed {label.lower()} from "
                f"{json.dumps(old)} to {json.dumps(new)}.",
            )
            for label, old, new in changed_facts(before, after)
        ]
    return Interpretation(
        draft=draft,
        spec_warnings=[i for i in checked.spec_issues if i.severity == "warning"],
        warnings=warnings,
        attempts=attempts,
    )
