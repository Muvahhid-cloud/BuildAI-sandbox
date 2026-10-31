"""Design Intelligence V1.3: footprint shape intent (building/footprint.py, docs/3d-engine.md
§16.12). Equivalent wording maps to the same structured intent; an explicit request is a
requirement; a shape the engine cannot build is recorded and refused with the reason - never
"repaired" away and never replaced by a rectangle."""

import copy
from typing import Any

import pytest

from app.modules.ai.interpreter import InterpretationError
from app.modules.ai.prompts.generation import system_prompt
from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.schemas.generation import SpecificationDraft
from app.modules.ai.structured import AITask
from app.modules.building.footprint import (
    CAPABILITIES,
    find_shape,
    normalize_shape_requirement,
    shape_priority,
    supported_shapes,
    unsupported_reason,
)
from app.modules.building.specification import BuildingSpecification, FootprintShape, Priority
from tests.ai.helpers import ScriptedAIProvider, valid_draft
from tests.ai.test_interpreter import run


def spec_of(prompt: str) -> BuildingSpecification:
    draft = SpecificationDraft.model_validate(interpret_offline(prompt))
    assert draft.specification is not None, draft.clarification_questions
    return draft.specification


# --- vocabulary and priority -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "shape"),
    [
        ("make me a long L designed house with the yellow walls", FootprintShape.L_SHAPE),
        ("Make me a long L-shaped house with yellow walls.", FootprintShape.L_SHAPE),
        ("an L shape bungalow", FootprintShape.L_SHAPE),
        ("an L house", FootprintShape.L_SHAPE),
        ("an L-plan home", FootprintShape.L_SHAPE),
        ("Design a T-shaped villa", FootprintShape.T_SHAPE),
        ("a T shaped house", FootprintShape.T_SHAPE),
        ("A U-shaped house", FootprintShape.U_SHAPE),
        ("a horseshoe plan home", FootprintShape.U_SHAPE),
        ("a courtyard house", FootprintShape.COURTYARD),
        ("a house around an atrium", FootprintShape.COURTYARD),
        ("a rectangular house", FootprintShape.RECTANGULAR),
        ("a house with an L-shaped kitchen", None),
        ("an L-shaped sofa in the living room", None),
        ("a house with a t-shirt print on the wall", None),
    ],
)
def test_equivalent_wording_maps_to_one_shape(text: str, shape: FootprintShape | None) -> None:
    assert find_shape(text) == shape


@pytest.mark.parametrize(
    ("quote", "priority"),
    [
        ("make me a long L designed house", Priority.MUST),
        ("design a T-shaped villa", Priority.MUST),
        ("could you make me an L-shaped house", Priority.MUST),
        ("the L shape is required", Priority.MUST),
        ("prefer an L-shaped house if possible", Priority.SHOULD),
        ("ideally L-shaped", Priority.SHOULD),
        ("an L-shaped bungalow, but a rectangular one is fine too", Priority.SHOULD),
        ("it does not have to be T-shaped", Priority.SHOULD),
    ],
)
def test_explicit_shape_is_required_softened_shape_preferred(quote: str, priority: str) -> None:
    assert shape_priority(quote) == priority


def test_capabilities_are_explicit_and_separate_from_recognition() -> None:
    generated = {c.shape for c in supported_shapes()}
    assert generated == {FootprintShape.RECTANGULAR, FootprintShape.L_SHAPE, FootprintShape.T_SHAPE}
    # Every shape the interpreter can recognise has a capability entry; U and courtyard are
    # recognised but have no generator.
    assert set(CAPABILITIES) == set(FootprintShape)
    for shape in (FootprintShape.U_SHAPE, FootprintShape.COURTYARD):
        assert not CAPABILITIES[shape].generated
        assert unsupported_reason(shape, 1) is not None
    assert unsupported_reason(FootprintShape.T_SHAPE, 1) is None
    assert "single-storey" in (unsupported_reason(FootprintShape.T_SHAPE, 2) or "")
    assert unsupported_reason(FootprintShape.RECTANGULAR, 3) is None


# --- the offline interpreter -------------------------------------------------------------------


def test_the_reported_request_is_a_required_yellow_l() -> None:
    spec = spec_of("make me a long L designed house with the yellow walls")
    assert spec.design.footprint_shape == FootprintShape.L_SHAPE
    assert spec.priority_of("/design/footprint_shape") == Priority.MUST
    assert spec.design.facade_color == "yellow"
    assert spec.targets.storeys == 1


@pytest.mark.parametrize(
    ("prompt", "shape", "priority"),
    [
        ("A rectangular house of 140 m2 with 3 bedrooms.", "rectangular", "must"),
        ("Design a T-shaped villa.", "t_shape", "must"),
        ("A U-shaped house with 3 bedrooms.", "u_shape", "must"),
        ("A courtyard house of 180 m2.", "courtyard", "must"),
        ("A house of 150 m2 with 3 bedrooms; an L shape if possible.", "l_shape", "should"),
    ],
)
def test_shape_requests_are_recorded_with_their_priority(
    prompt: str, shape: str, priority: str
) -> None:
    spec = spec_of(prompt)
    assert spec.design.footprint_shape == shape
    assert spec.priority_of("/design/footprint_shape") == priority


# --- normalization of any interpreter's answer -------------------------------------------------


def test_an_explicit_request_marked_should_by_a_model_becomes_must() -> None:
    """The reported run: the model traced "make me a long L designed house" as should."""
    data = valid_draft()["specification"] | {
        "targets": {"storeys": 1},
        "design": {"footprint_shape": "l_shape", "facade_color": "yellow"},
        "requirements": [
            {
                "path": "/design/footprint_shape",
                "priority": "should",
                "origin": "user_text",
                "quote": "make me a long L designed house",
            }
        ],
    }
    spec = BuildingSpecification.model_validate(data)
    fixed, note = normalize_shape_requirement(spec)
    assert fixed.priority_of("/design/footprint_shape") == Priority.MUST
    assert note is not None and "requirement" in note and "An L-shaped" in note
    again, second = normalize_shape_requirement(fixed)
    assert again == fixed and second is None
    soft = spec.model_copy(
        update={
            "requirements": [
                spec.requirements[0].model_copy(update={"quote": "an L shape if possible"})
            ]
        }
    )
    assert normalize_shape_requirement(soft)[0].priority_of("/design/footprint_shape") == "should"


def _shape_draft(shape: str, priority: str, quote: str, storeys: int = 1) -> dict[str, Any]:
    draft = valid_draft()
    draft["specification"]["targets"]["storeys"] = storeys
    draft["specification"]["targets"]["gross_floor_area_m2"] = 160.0 * storeys
    for room in draft["specification"]["rooms"]:
        room["level"] = None  # the demo draft has an upper floor
    draft["specification"]["features"]["balconies"] = []
    draft["specification"]["design"] = {"footprint_shape": shape}
    draft["specification"]["requirements"] = [
        {
            "path": "/design/footprint_shape",
            "priority": priority,
            "origin": "user_text",
            "quote": quote,
        }
    ]
    return draft


async def test_a_required_unsupported_shape_fails_without_a_repair_call() -> None:
    draft = _shape_draft("u_shape", "must", "build me a U-shaped house")
    provider = ScriptedAIProvider(draft, copy.deepcopy(draft))
    with pytest.raises(InterpretationError) as info:
        await run(provider)
    err = info.value
    assert err.code == "SPEC_UNSUPPORTED"
    assert "U-shaped" in err.message and "cannot generate" in err.message
    assert [a.task for a in err.attempts] == [AITask.GENERATE_SPECIFICATION]  # no repair


async def test_a_should_traced_explicit_unsupported_shape_is_still_refused() -> None:
    """A model's "should" for "design a courtyard house" is read from the user's words: the
    shape is required, so it is refused - never quietly turned into a rectangle."""
    draft = _shape_draft("courtyard", "should", "design a courtyard house")
    with pytest.raises(InterpretationError) as info:
        await run(ScriptedAIProvider(draft))
    assert info.value.code == "SPEC_UNSUPPORTED"


async def test_a_preferred_unsupported_shape_is_accepted_with_a_warning() -> None:
    draft = _shape_draft("u_shape", "should", "a U-shaped house would be nice")
    result, _ = await run(ScriptedAIProvider(draft))
    assert result.spec is not None and result.spec.design.footprint_shape == "u_shape"
    warnings = [i for i in result.spec_warnings if i.code == "SPEC_FOOTPRINT_UNSUPPORTED"]
    assert warnings and "rectangular footprint will be used" in warnings[0].message


async def test_the_shape_priority_note_is_shown() -> None:
    draft = _shape_draft("l_shape", "should", "make me a long L designed house")
    result, _ = await run(ScriptedAIProvider(draft))
    assert result.spec.priority_of("/design/footprint_shape") == "must"
    assert any(w.code == "AI_SHAPE_PRIORITY" for w in result.warnings)


def test_the_prompt_lists_what_can_and_cannot_be_generated() -> None:
    text = system_prompt()
    assert "Generated today: rectangular, l_shape (single-storey only), t_shape" in text
    assert "not generated yet: u_shape, courtyard" in text
    assert "priority must when the user asks for the shape outright" in text
