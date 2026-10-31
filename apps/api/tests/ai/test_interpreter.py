import copy
from typing import Any

import pytest

from app.modules.ai.errors import AITimeoutError, AIUnavailableError
from app.modules.ai.interpreter import InterpretationError, check_options, interpret
from app.modules.ai.providers.mock import MockAIProvider
from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.ai.structured import AITask
from app.modules.building.specification import BuildingSpecification
from tests.ai.helpers import DEMO_PROMPT, ScriptedAIProvider, context, valid_draft, validate_spec


async def run(provider: Any, **kwargs: Any) -> Any:
    stages: list[str] = []

    async def on_stage(name: str) -> None:
        stages.append(name)

    result = await interpret(
        DEMO_PROMPT,
        provider=provider,
        options=kwargs.pop("options", None),
        context=context(),
        validate_spec=validate_spec,
        on_stage=on_stage,
        **kwargs,
    )
    return result, stages


def with_spec(**changes: Any) -> dict[str, Any]:
    draft = valid_draft()
    draft["specification"].update(changes)
    return draft


async def test_valid_output_is_accepted_without_repair() -> None:
    result, stages = await run(MockAIProvider())
    assert result.spec is not None and result.repair_count == 0
    assert stages == ["interpreting", "validating"]
    assert [a.status for a in result.attempts] == ["ok"]
    assert result.attempts[0].task is AITask.GENERATE_SPECIFICATION


async def test_non_json_answer_is_repaired_once() -> None:
    provider = ScriptedAIProvider(None, valid_draft())
    result, stages = await run(provider)
    assert result.spec is not None and result.repair_count == 1
    assert stages == ["interpreting", "validating", "repairing", "validating"]
    first = result.attempts[0]
    assert first.status == "invalid" and first.issues[0].code == "AI_OUTPUT_NOT_JSON"
    # The repair call sees the rejected output and the issues.
    repair_text = provider.requests[1].messages[0].content
    assert "I cannot do that." in repair_text and "not a single JSON object" in repair_text


async def test_unsupported_room_type_is_a_schema_error_with_a_pointer() -> None:
    bad = valid_draft()
    bad["specification"]["rooms"][0]["type"] = "swimming_pool"
    provider = ScriptedAIProvider(bad, valid_draft())
    result, _ = await run(provider)
    issue = result.attempts[0].issues[0]
    assert issue.code == "AI_SCHEMA_INVALID"
    assert issue.path == "/specification/rooms/0/type"
    assert result.repair_count == 1


async def test_invalid_dimensions_fail_after_one_repair() -> None:
    bad = with_spec(targets={"storeys": 7, "gross_floor_area_m2": 5})
    provider = ScriptedAIProvider(bad, copy.deepcopy(bad))
    with pytest.raises(InterpretationError) as info:
        await run(provider)
    err = info.value
    assert err.code == "AI_INVALID_OUTPUT"
    paths = {i.path for i in err.issues}
    assert {"/specification/targets/storeys", "/specification/targets/gross_floor_area_m2"} <= paths
    assert [a.task for a in err.attempts] == [
        AITask.GENERATE_SPECIFICATION,
        AITask.REPAIR_SPECIFICATION,
    ]


async def test_missing_required_fields_are_rejected() -> None:
    bad = valid_draft()
    del bad["specification"]["targets"]
    del bad["understanding"]
    provider = ScriptedAIProvider(bad)
    with pytest.raises(InterpretationError) as info:
        await run(provider, max_repairs=0)
    paths = {i.path for i in info.value.issues}
    assert {"/specification/targets", "/understanding"} <= paths


async def test_extra_geometry_fields_are_rejected() -> None:
    bad = valid_draft()
    bad["specification"]["rooms"][0]["position"] = {"x": 0, "y": 0}
    bad["walls"] = [{"x": 1}]
    with pytest.raises(InterpretationError) as info:
        await run(ScriptedAIProvider(bad), max_repairs=0)
    assert {"/walls", "/specification/rooms/0/position"} <= {i.path for i in info.value.issues}


async def test_rules_errors_are_repaired_and_reported_as_spec_invalid() -> None:
    bad = valid_draft()
    bad["specification"]["rooms"][0]["open_to"] = ["garden"]  # unknown room key (tier 2)
    provider = ScriptedAIProvider(bad, copy.deepcopy(bad))
    with pytest.raises(InterpretationError) as info:
        await run(provider)
    assert info.value.code == "SPEC_INVALID"
    assert info.value.issues[0].code == "SPEC_UNKNOWN_ROOM_KEY"
    assert info.value.issues[0].path == "/rooms/0/open_to/0"  # spec-relative for the user
    repair_text = provider.requests[1].messages[0].content
    assert "/specification/rooms/0/open_to/0" in repair_text  # answer-relative for the model


async def test_repair_that_changes_the_program_is_reported() -> None:
    first = valid_draft()
    first["specification"]["rooms"][0]["open_to"] = ["garden"]
    repaired = valid_draft()
    bedrooms = next(r for r in repaired["specification"]["rooms"] if r["key"] == "bedroom")
    bedrooms["count"] = 1  # the "fix" silently dropped two bedrooms
    result, _ = await run(ScriptedAIProvider(first, repaired))
    messages = [w.message for w in result.warnings if w.code == "AI_REPAIR_CHANGED"]
    assert messages == ["The automatic correction changed bedrooms from 4 to 2."]


async def test_conflicts_and_unsupported_requests_become_warnings() -> None:
    draft = valid_draft()
    draft["conflicts"] = ["12 bedrooms do not fit in 120 m²."]
    draft["unsupported_requests"] = ["Swimming pool"]
    result, _ = await run(ScriptedAIProvider(draft))
    codes = [(w.code, w.severity) for w in result.warnings]
    assert codes == [
        ("AI_REQUIREMENT_CONFLICT", "warning"),
        ("AI_UNSUPPORTED_REQUEST", "warning"),
    ]


async def test_clarification_outcome_is_returned_without_a_spec() -> None:
    answer = {
        "outcome": "clarification",
        "understanding": "A house.",
        "clarification_questions": ["How many floors?"],
    }
    result, _ = await run(ScriptedAIProvider(answer))
    assert result.spec is None
    assert result.draft.clarification_questions == ["How many floors?"]


async def test_clarification_without_questions_is_invalid() -> None:
    answer = {"outcome": "clarification", "understanding": "A house."}
    with pytest.raises(InterpretationError):
        await run(ScriptedAIProvider(answer), max_repairs=0)


@pytest.mark.parametrize(
    ("exc", "code"),
    [(AIUnavailableError("down"), "AI_UNAVAILABLE"), (AITimeoutError("slow"), "AI_TIMEOUT")],
)
async def test_provider_failures_are_mapped_and_recorded(exc: Exception, code: str) -> None:
    with pytest.raises(InterpretationError) as info:
        await run(ScriptedAIProvider(exc))
    err = info.value
    assert err.code == code
    assert "temporarily unavailable" in err.message or "in time" in err.message
    assert [(a.status, a.error_code) for a in err.attempts] == [("error", code)]


async def test_provider_failure_during_repair_keeps_the_first_attempt() -> None:
    with pytest.raises(InterpretationError) as info:
        await run(ScriptedAIProvider(None, AIUnavailableError("down")))
    assert [a.status for a in info.value.attempts] == ["invalid", "error"]


async def test_form_field_mismatch_triggers_a_repair() -> None:
    options = GenerationOptions(storeys=3)
    provider = ScriptedAIProvider(valid_draft(), lambda _: fixed_storeys(3))

    async def noop(_: str) -> None:
        return None

    result = await interpret(
        DEMO_PROMPT,
        provider=provider,
        options=options,
        context=context(),
        validate_spec=lambda s: validate_spec(s) + check_options(s, options),
        on_stage=noop,
    )
    assert result.repair_count == 1
    assert result.attempts[0].issues[0].code == "SPEC_FORM_FIELD_MISMATCH"
    assert result.spec is not None and result.spec.targets.storeys == 3


def fixed_storeys(storeys: int) -> dict[str, Any]:
    draft = valid_draft()
    draft["specification"]["targets"]["storeys"] = storeys
    for room in draft["specification"]["rooms"]:
        room.pop("level", None)
    return draft


def test_check_options_accepts_a_matching_spec() -> None:
    spec = BuildingSpecification.model_validate(valid_draft()["specification"])
    options = GenerationOptions(storeys=2, gross_floor_area_m2=280, region_code=None)
    assert check_options(spec, options) == []
    assert check_options(spec, None) == []
    bad = check_options(spec, GenerationOptions(region_code="KZ-AST"))
    assert [i.path for i in bad] == ["/site/region_code"]
