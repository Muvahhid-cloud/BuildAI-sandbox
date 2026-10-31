"""Footprint shapes: what a client can ask for, what the layout engine can generate, and how a
request for a shape is read (Design Intelligence V1.3, docs/3d-engine.md §16.12).

Four separate questions, never collapsed into one:

    requested     design.footprint_shape (any FootprintShape, recorded even when unsupported)
    priority      the requirement trace: an explicit request ("make an L-shaped house",
                  "design a T-shaped villa") is MUST; softened wording ("prefer an L shape if
                  possible") is SHOULD (shape_priority)
    supported     CAPABILITIES: whether a generator exists, and its limits (storeys)
    feasible      decided by the layout engine for this program and site; when no candidate
                  fits it reports why (LAYOUT_INFEASIBLE / LAYOUT_TOPOLOGY_FALLBACK)

A shape name the interpreter recognises is not a supported shape: only CAPABILITIES says so.
Both interpreters (the offline mock and an AI model) use SHAPE_WORDS and shape_priority, so
equivalent requests map to the same structured intent.
"""

import re
from dataclasses import dataclass

from app.modules.building.specification import (
    BuildingSpecification,
    FootprintShape,
    Priority,
    RequirementOrigin,
)


@dataclass(frozen=True)
class ShapeCapability:
    shape: FootprintShape
    label: str  # "L-shaped"
    topology: str | None  # layout generator id ("rect" | "l" | "t"); None = not implemented
    max_storeys: int  # storeys the generator handles (0 when there is no generator)
    limitation: str  # what cannot be generated, in the words reports use

    @property
    def generated(self) -> bool:
        return self.topology is not None

    @property
    def a_label(self) -> str:
        """The label with its article: "an L-shaped", "a T-shaped"."""
        return ("an " if self.label[0] in "AEFHILMNORSXaeiou" else "a ") + self.label

    @property
    def an_label(self) -> str:
        """a_label at the start of a sentence: "An L-shaped", "A T-shaped"."""
        return self.a_label[0].upper() + self.a_label[1:]


CAPABILITIES: dict[FootprintShape, ShapeCapability] = {
    c.shape: c
    for c in (
        ShapeCapability(FootprintShape.RECTANGULAR, "rectangular", "rect", 3, ""),
        ShapeCapability(
            FootprintShape.L_SHAPE,
            "L-shaped",
            "l",
            1,
            "L-shaped footprints are generated for single-storey houses only",
        ),
        ShapeCapability(
            FootprintShape.T_SHAPE,
            "T-shaped",
            "t",
            1,
            "T-shaped footprints are generated for single-storey houses only",
        ),
        ShapeCapability(
            FootprintShape.U_SHAPE,
            "U-shaped",
            None,
            0,
            "the layout engine cannot generate U-shaped footprints yet (rectangular, L- and "
            "T-shaped footprints only)",
        ),
        ShapeCapability(
            FootprintShape.COURTYARD,
            "courtyard",
            None,
            0,
            "the layout engine cannot enclose an inner courtyard yet (rectangular, L- and "
            "T-shaped footprints only; a garden terrace is possible)",
        ),
    )
}

# Measured shapes (building/evaluation.py measure_footprint) -> words for reports.
MEASURED_LABELS = {c.shape.value: c.label for c in CAPABILITIES.values()} | {"other": "other"}


def capability(shape: FootprintShape) -> ShapeCapability:
    return CAPABILITIES[shape]


def unsupported_reason(shape: FootprintShape, storeys: int) -> str | None:
    """Why this shape cannot be generated for a house of `storeys`; None when it can."""
    cap = CAPABILITIES[shape]
    if not cap.generated:
        return cap.limitation
    if storeys > cap.max_storeys:
        return f"{cap.limitation}; this house has {storeys} storeys"
    return None


def supported_shapes() -> list[ShapeCapability]:
    return [c for c in CAPABILITIES.values() if c.generated]


# --- how requests are worded ----------------------------------------------------------------

# A letter shape: "L-shaped", "L shape", "L designed", "L-plan", or the letter before a building
# noun ("an L house"); never an L-shaped sofa, kitchen counter or terrace.
_LETTER_FORM = (
    r"(?:[- ]?(?:shaped?|designed?|form(?:ed)?|plan|type|layout)\b"
    r"|(?=[- ](?:house|home|bungalow|villa|building|footprint|cottage)\b))"
    r"(?![- ]?(?:kitchen|sofa|couch|counter|worktop|desk|bench|stair\w*|balcon\w*|terrace|"
    r"pool|garden|room|wardrobe|closet|island|bar)\b)"
)
# Shape vocabulary (lower-case text). One table for every way of saying the same shape:
# "L-shaped", "L shape", "L designed", "an L house", "L-plan" ... -> l_shape.
SHAPE_WORDS: tuple[tuple[FootprintShape, re.Pattern[str]], ...] = (
    (FootprintShape.COURTYARD, re.compile(r"\bcourtyard\b|\batrium\b|\binner court\b")),
    (FootprintShape.U_SHAPE, re.compile(rf"\bu{_LETTER_FORM}|\bhorseshoe\b")),
    (FootprintShape.T_SHAPE, re.compile(rf"\bt{_LETTER_FORM}")),
    (FootprintShape.L_SHAPE, re.compile(rf"\bl{_LETTER_FORM}")),
    (
        FootprintShape.RECTANGULAR,
        re.compile(r"\brectangular\b|\bbox[- ]shaped\b|\b(?:simple )?rectangle\b"),
    ),
)
# Softened wording: the shape is a preference, not a requirement.
# ("Could you make ..." is a polite request, not a softened one: "could" is not a hedge.)
HEDGES = re.compile(
    r"\b(?:prefer\w*|ideally|if (?:possible|feasible|it fits)|where possible|maybe|perhaps|"
    r"would be nice|nice to have|optional\w*|not essential|or (?:a )?rectangular|"
    r"(?:is )?(?:also )?fine too|either (?:way|is fine)|does(?:n't| not) have to|"
    r"not necessarily|not required)\b"
)


def find_shape(text: str) -> FootprintShape | None:
    """The footprint shape a piece of text asks for (first match in SHAPE_WORDS order)."""
    lowered = text.lower()
    return next((shape for shape, pattern in SHAPE_WORDS if pattern.search(lowered)), None)


def shape_priority(quote: str) -> Priority:
    """MUST for an explicit request ("make me a long L designed house"), SHOULD when the
    wording softens it ("an L shape if possible", "ideally T-shaped")."""
    return Priority.SHOULD if HEDGES.search(quote.lower()) else Priority.MUST


def normalize_shape_requirement(
    spec: BuildingSpecification,
) -> tuple[BuildingSpecification, str | None]:
    """Apply shape_priority to the user's own words for the footprint shape, whichever
    interpreter produced the spec, so "make me a long L designed house" is a requirement and
    "an L shape if possible" a preference. Returns the spec and a note when the priority was
    changed (shown to the user). Without a quoted user_text trace nothing is changed."""
    if spec.design.footprint_shape is None:
        return spec, None
    traces = list(spec.requirements)
    for i, trace in enumerate(traces):
        if (
            trace.path != "/design/footprint_shape"
            or trace.origin != RequirementOrigin.USER_TEXT
            or not trace.quote
        ):
            continue
        wanted = shape_priority(trace.quote)
        if wanted == trace.priority:
            return spec, None
        traces[i] = trace.model_copy(update={"priority": wanted})
        label = CAPABILITIES[spec.design.footprint_shape].an_label
        quote = f"“{trace.quote}”"
        note = (
            f"{label} footprint was asked for explicitly ({quote}), so it is a "
            "requirement: it is generated or the generation stops and says why."
            if wanted == Priority.MUST
            else f"{label} footprint was asked for as a preference ({quote}): another "
            "shape is used when it does not fit."
        )
        return spec.model_copy(update={"requirements": traces}), note
    return spec, None
