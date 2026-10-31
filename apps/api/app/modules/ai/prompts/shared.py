"""Pieces shared by the generation and repair prompts.

The vocabulary section is generated from the specification enums, so the prompt can never
offer a room type, style or feature the schema (and the layout engine) does not support.
"""

import json
import re
from functools import cache
from typing import Any

from app.modules.ai.context import GenerationContext
from app.modules.ai.schemas.generation import GenerationOptions, SpecificationDraft
from app.modules.building.appearance import PALETTE
from app.modules.building.enums import RoofType
from app.modules.building.facades import FACADE_SYNONYMS
from app.modules.building.footprint import CAPABILITIES
from app.modules.building.specification import (
    ArchitecturalStyle,
    DesignPriority,
    FacadeMaterial,
    FacadeSide,
    FinishLevel,
    FootprintShape,
    InteriorStyle,
    Priority,
    RequirementOrigin,
    RoomFeature,
    SpecRoomType,
    WindowStyle,
)

PROMPT_VERSION = "building-generation@5"  # @5: any footprint shape is recorded (supported
# or not, building/footprint.py); an explicit shape request is a must
# @4: design.footprint_shape (L-shaped plans)
# @3: priorities, area ranges, separation, traces
# @2 (K3): design systems and design intent
OUTPUT_NAME = "building_specification_draft"
OUTPUT_DESCRIPTION = (
    "The interpreted building request: a BuildingSpecification (intent only, no geometry) "
    "or clarification questions."
)
USER_TAG = "building_request"


def _shape_capabilities() -> str:
    """What the layout engine can generate, from building/footprint.py CAPABILITIES."""
    parts = []
    for cap in CAPABILITIES.values():
        if cap.generated:
            limit = "" if cap.max_storeys >= 3 else " (single-storey only)"
            parts.append(f"{cap.shape.value}{limit}")
    missing = [c.shape.value for c in CAPABILITIES.values() if not c.generated]
    return (
        "Generated today: " + ", ".join(parts) + "; not generated yet: " + ", ".join(missing) + "."
    )


def _values(enum: Any) -> str:
    return ", ".join(e.value for e in enum)


def vocabulary() -> str:
    return "\n".join(
        [
            "- building_type: single_family_house (residential, 1 to 3 storeys, rectilinear).",
            f"- rooms[].type: {_values(SpecRoomType)}.",
            f"- rooms[].features (bedrooms only): {_values(RoomFeature)}.",
            "- Circulation (entrance hall, corridors, stair core) is added by the layout engine;"
            " never request it.",
            "- features.garage: attached, ground floor, 1 to 3 cars.",
            "- features.balconies: on upper floors only (level >= 1); side garden|street.",
            "- features.terrace: one ground-floor terrace on the garden side.",
            f"- style.architectural_style: {_values(ArchitecturalStyle)}.",
            f"- style.interior_style: {_values(InteriorStyle)}.",
            f"- style.roof.type: {_values(RoofType)} (pitch_deg only for pitched roofs).",
            f"- style.window_style: {_values(WindowStyle)}.",
            f"- style.facade_material: {_values(FacadeMaterial)}.",
            f"- style.interior_finish_level: {_values(FinishLevel)}.",
            "- budget: {amount: decimal string, currency: ISO-4217 code}. A constraint only.",
            "- site.region_code: only when the user names a place (e.g. KZ-ALA for Almaty,"
            " KZ-AST for Astana).",
            f"- Facades: {_values(FacadeSide)}. front = street/entrance side; rear = garden/"
            "backyard/back side; left/right as seen from the street. Map "
            + ", ".join(f'"{w}"' for w in sorted(FACADE_SYNONYMS))
            + " to these values.",
            "- design.facade_color: the exterior wall color the user asks for (display color of"
            " the facade finish, not a material change). A palette name: "
            f"{', '.join(PALETTE)}; or #rrggbb when the user gives an exact color."
            " Null when no color is requested.",
            "- design.windows: {emphasis: large|panoramic, preferred_facades: [...],"
            " excluded_facades: [...]} when the user wants large/panoramic windows on particular"
            " facades. preferred_facades get the emphasised windows; excluded_facades never get"
            " them (standard windows there). Keep style.window_style for the other facades"
            " (standard unless the user wants large windows everywhere).",
            "- rooms[].faces: front|rear when a room should face the street or the garden/"
            "backyard (left/right are not supported for rooms).",
            "- rooms[].target_area_m2 is per room; min_area_m2 / max_area_m2 bound the accepted"
            ' range ("at least 20 m²" -> target 20, min 20; "up to 15 m²" -> max 15).'
            " Without a range the engine accepts the target +/-10%.",
            "- rooms[].adjacent_to: rooms that share a wall; open_to: open plan without a wall;"
            " separate_from: rooms that must not share a wall (e.g. bedrooms apart from the"
            " living room). All refer to room keys of this specification.",
            f"- design.priorities (ordered, optional): {_values(DesignPriority)}. What the client"
            " stresses most; it weights the evaluation of layout candidates.",
            f"- design.footprint_shape: {_values(FootprintShape)}, only when the user asks for"
            ' a footprint shape ("L-shaped house", "an L designed house", "T-shaped villa",'
            ' "U-shaped home", "courtyard house"); null otherwise. Record the shape the user'
            " asked for even when it cannot be generated (never substitute another shape and"
            " never move it to unsupported_requests): the engine reports what it cannot build. "
            + _shape_capabilities()
            + " Always add a requirements[] entry for /design/footprint_shape with the user's"
            ' words as quote: priority must when the user asks for the shape outright ("make'
            ' me an L-shaped house", "design a T-shaped villa"), should only when they soften'
            ' it ("prefer an L shape if possible", "ideally L-shaped").',
            "- site.plot_width_m / plot_depth_m: only when the user gives plot dimensions (the"
            " street is on the front); the footprint is kept inside them.",
            "- requirements[]: {path, priority, origin, quote} for each requirement the user"
            " stated: path is the JSON pointer of the value it governs (a room's target_area_m2,"
            " an adjacent_to/open_to/separate_from entry, faces, /design/windows or"
            " /design/footprint_shape); priority"
            f" {_values(Priority)}; origin {_values(RequirementOrigin)}; quote = the user's own"
            " words (at most 200 characters). Use must only when the user states it as"
            " mandatory (must, need, required, exactly, at least) or gives an exact number for a"
            " room; otherwise should. A must is never relaxed: if it cannot be met the"
            " generation fails and says why.",
            "- style.design_system: only an id listed in <project_context> design_systems; null"
            " when the list is empty or the user names no matching direction. With a design"
            " system, every style value must be in that system's allowed lists.",
        ]
    )


@cache
def output_schema_json() -> dict[str, Any]:
    """JSON Schema of the structured output (the SpecificationDraft envelope)."""
    return SpecificationDraft.model_json_schema(mode="validation")


SCHEMA_IN_PROMPT_VERSION = "schema-in-prompt@1"


def schema_in_prompt_block(schema: dict[str, Any]) -> str:
    """System-prompt appendix for providers whose structured outputs cannot compile the schema.

    Used only as a fallback (providers/openrouter.py): the answer is still parsed with
    `json.loads` alone and validated exactly like a structured output. Versioned separately
    (`SCHEMA_IN_PROMPT_VERSION`) because the generation/repair prompts themselves do not change.
    """
    return "\n".join(
        [
            "<response_schema>",
            json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
            "</response_schema>",
            f"The response schema above is the JSON Schema of `{OUTPUT_NAME}`. Answer with"
            " exactly one JSON object that validates against it: no text before or after it,"
            " no Markdown code fences, no comments. Respect every enum, minimum, maximum and"
            " length limit in the schema and omit properties you do not need.",
        ]
    )


_TAG_RE = re.compile(rf"</?\s*{USER_TAG}\s*>", re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def quote_user_text(text: str) -> str:
    """Wrap untrusted user text in its tag so it cannot close the tag or add control chars."""
    cleaned = _CONTROL_RE.sub("", _TAG_RE.sub("", text)).strip()
    return f"<{USER_TAG}>\n{cleaned}\n</{USER_TAG}>"


def form_fields(options: GenerationOptions | None) -> dict[str, Any]:
    """The options the AI must honour (the layout seed is not an AI concern)."""
    if options is None:
        return {}
    return options.model_dump(mode="json", exclude_none=True, exclude={"seed"})


def context_block(context: GenerationContext, options: GenerationOptions | None) -> str:
    project = {
        "region_code": context.region_code,
        "currency": context.currency,
        "rules_profile": context.rules_profile,
        "room_minimums": [m.model_dump() for m in context.room_minimums],
        "max_room_share_of_gross_floor_area": context.max_room_share_of_gfa,
        # Usable (approved) design systems; empty = style.design_system must stay null.
        "design_systems": [d.model_dump() for d in context.design_systems],
    }
    parts = [
        "<project_context>",
        json.dumps(project, ensure_ascii=False, separators=(",", ":")),
        "</project_context>",
    ]
    fields = form_fields(options)
    if fields:
        parts += [
            "<form_fields>",
            json.dumps(fields, ensure_ascii=False, separators=(",", ":")),
            "</form_fields>",
            "The form fields were set explicitly by the user. The specification must use exactly"
            " these values; if the description contradicts them, use the form value and list"
            " the contradiction in `conflicts`.",
        ]
    return "\n".join(parts)
