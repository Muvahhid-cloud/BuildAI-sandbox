"""Requirement traces: which spec values are mandatory and where they came from (spec 1.2.0).

`BuildingSpecification.requirements[]` marks individual values of the spec as MUST or SHOULD and
records their origin (request text, form, assumption) and the user's words. This module gives
those traces a meaning that the layout engine and the evaluation share:

    kind            path                                   checked on the generated model
    room_area       /rooms/<i>/target_area_m2              area within the permissible range
    adjacent        /rooms/<i>/adjacent_to/<j>             the two rooms share an edge
    open            /rooms/<i>/open_to/<j>                 the two rooms share an edge
    separate        /rooms/<i>/separate_from/<j>           the two rooms share no edge
    faces           /rooms/<i>/faces                       the room bounds that facade
    windows         /design/windows                        emphasised windows where asked
    footprint       /design/footprint_shape                the ground floor outline's shape

MUST is accepted only on these kinds (anything else is a tier-2 error: the engine could not
enforce it, so accepting it would be a silent relaxation). Pure functions, no I/O.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.modules.building.footprint import capability, supported_shapes, unsupported_reason
from app.modules.building.issues import Issue, pointer
from app.modules.building.specification import (
    BuildingSpecification,
    Priority,
    RequirementOrigin,
    RoomRequirement,
)

RequirementKind = Literal[
    "room_area", "adjacent", "open", "separate", "faces", "windows", "footprint"
]
ENFORCEABLE_DESIGN_PATHS = frozenset({"/design/windows", "/design/footprint_shape"})

_ROOM_PATH = re.compile(
    r"^/rooms/(?P<i>\d+)/(?:(?P<field>target_area_m2|faces)"
    r"|(?P<list>adjacent_to|open_to|separate_from)/(?P<j>\d+))$"
)
_LIST_KIND: dict[str, RequirementKind] = {
    "adjacent_to": "adjacent",
    "open_to": "open",
    "separate_from": "separate",
}
# Default permissible deviation of an explicit room target that has no min/max of its own.
# A design default of the evaluation (not a building rule): the rules profile still bounds
# every room from below.
DEFAULT_AREA_TOLERANCE = 0.10


@dataclass(frozen=True)
class Requirement:
    """One checkable requirement of a spec, with its priority and origin."""

    kind: RequirementKind
    path: str
    priority: Priority
    origin: RequirementOrigin
    quote: str | None
    room: str | None = None  # spec room key
    other: str | None = None  # spec room key (pairs)

    @property
    def mandatory(self) -> bool:
        return self.priority == Priority.MUST


@dataclass(frozen=True)
class AreaRange:
    target: float
    low: float
    high: float


def area_range(room: RoomRequirement, tolerance: float = DEFAULT_AREA_TOLERANCE) -> AreaRange:
    """Permissible area of an explicitly sized room: [min_area_m2, max_area_m2] where given,
    else target ± tolerance."""
    target = room.target_area_m2
    if target is None:
        raise ValueError(f"{room.key} has no target area")
    low = room.min_area_m2 if room.min_area_m2 is not None else target * (1 - tolerance)
    high = room.max_area_m2 if room.max_area_m2 is not None else target * (1 + tolerance)
    return AreaRange(target, low, high)


def _requirement(
    spec: BuildingSpecification,
    kind: RequirementKind,
    path: str,
    room: str | None,
    other: str | None = None,
) -> Requirement:
    trace = spec.trace(path)
    return Requirement(
        kind=kind,
        path=path,
        priority=trace.priority if trace else Priority.SHOULD,
        origin=trace.origin if trace else RequirementOrigin.USER_TEXT,
        quote=trace.quote if trace else None,
        room=room,
        other=other,
    )


def requirements(spec: BuildingSpecification) -> list[Requirement]:
    """Every checkable requirement of `spec` (traced or not), in spec order."""
    out: list[Requirement] = []
    for i, room in enumerate(spec.rooms):
        if room.target_area_m2 is not None:
            out.append(
                _requirement(spec, "room_area", pointer("rooms", i, "target_area_m2"), room.key)
            )
        for field, kind in _LIST_KIND.items():
            for j, other in enumerate(getattr(room, field)):
                out.append(_requirement(spec, kind, pointer("rooms", i, field, j), room.key, other))
        if room.faces is not None:
            out.append(_requirement(spec, "faces", pointer("rooms", i, "faces"), room.key))
    if spec.design.windows is not None:
        out.append(_requirement(spec, "windows", "/design/windows", None))
    if spec.design.footprint_shape is not None:
        out.append(_requirement(spec, "footprint", "/design/footprint_shape", None))
    return out


def _resolves(spec: BuildingSpecification, path: str) -> bool:
    data = spec.model_dump(mode="json")
    node: object = data
    for part in path.strip("/").split("/"):
        if isinstance(node, list) and part.isdigit() and int(part) < len(node):
            node = node[int(part)]
        elif isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return False
    return node is not None


def _enforceable(path: str) -> bool:
    return path in ENFORCEABLE_DESIGN_PATHS or _ROOM_PATH.match(path) is not None


def check_requirements(spec: BuildingSpecification) -> list[Issue]:
    """Tier-2 checks of requirement traces and separation requests."""
    issues: list[Issue] = []
    keys = {r.key for r in spec.rooms}
    for n, trace in enumerate(spec.requirements):
        path = pointer("requirements", n, "path")
        if not _resolves(spec, trace.path):
            issues.append(
                Issue(
                    severity="error",
                    code="SPEC_REQUIREMENT_PATH",
                    path=path,
                    message=f"{trace.path} does not name a value of this specification",
                )
            )
        elif trace.priority == Priority.MUST and not _enforceable(trace.path):
            issues.append(
                Issue(
                    severity="error",
                    code="SPEC_REQUIREMENT_UNSUPPORTED",
                    path=path,
                    message=f"{trace.path} cannot be enforced as mandatory by the layout engine",
                    suggestion="Mark it as a preference (should) instead.",
                )
            )
    shape = spec.design.footprint_shape
    reason = unsupported_reason(shape, spec.targets.storeys) if shape is not None else None
    if shape is not None and reason is not None:
        # A shape the engine cannot generate (no generator, or not for this many storeys):
        # a MUST stops generation with this reason (never a silent rectangle); a SHOULD is
        # reported and a rectangle is generated instead. (Not repairable by an AI call:
        # ai/interpreter.py USER_LIMITS.)
        must = spec.priority_of("/design/footprint_shape") == Priority.MUST
        cap = capability(shape)
        storey_limit = cap.generated and spec.targets.storeys > cap.max_storeys
        issues.append(
            Issue(
                severity="error" if must else "warning",
                code="SPEC_FOOTPRINT_UNSUPPORTED",
                path="/design/footprint_shape",
                message=f"{cap.an_label} footprint was requested, but {reason}"
                + (" (it was required, so nothing was generated)" if must else "")
                + ("" if must else "; a rectangular footprint will be used"),
                suggestion=(
                    "Ask for one storey, or for a rectangular footprint."
                    if storey_limit
                    else "Ask for one of: "
                    + ", ".join(c.label for c in supported_shapes())
                    + (", or make the shape a preference." if must else ".")
                ),
            )
        )
    for i, room in enumerate(spec.rooms):
        for j, other in enumerate(room.separate_from):
            if other == room.key or other not in keys:
                issues.append(
                    Issue(
                        severity="error",
                        code="SPEC_UNKNOWN_ROOM_KEY",
                        path=pointer("rooms", i, "separate_from", j),
                        message=f"{room.key}: separate_from refers to unknown room {other!r}",
                    )
                )
            elif (
                other in room.adjacent_to
                or other in room.open_to
                or any(
                    r.key == other and (room.key in r.adjacent_to or room.key in r.open_to)
                    for r in spec.rooms
                )
            ):
                issues.append(
                    Issue(
                        severity="error",
                        code="SPEC_REQUIREMENT_CONFLICT",
                        path=pointer("rooms", i, "separate_from", j),
                        message=f"{room.key} cannot be both next to and separate from {other}",
                        suggestion="Keep one of the two requests.",
                    )
                )
        if room.max_area_m2 is not None and room.target_area_m2 is None:
            issues.append(
                Issue(
                    severity="warning",
                    code="SPEC_RANGE_WITHOUT_TARGET",
                    path=pointer("rooms", i, "max_area_m2"),
                    message=f"{room.key}: a maximum area without a target area is not used",
                    suggestion="Give a target area as well.",
                )
            )
    return issues
