"""Judge an edited model: apply operations, then hold the result to the same standard as a
generated model (docs/building-model.md §5.1). Pure and synchronous (no I/O); the service runs it
in a worker thread.

An edit is accepted only if it introduces no new model error, no new rules-profile finding and
no new loss of access or daylight (`EDIT_BLOCKING_WARNINGS`) compared with the base version.
Findings the base already had (same code on the same element) do not block an edit, so an older
design that is not perfect can still be improved. New model warnings that are not rules findings
are allowed and returned for display.
"""

import uuid
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from threading import Lock

from shapely.geometry import Polygon as ShapelyPolygon

from app.modules.building.elements import Door, Room, Window
from app.modules.building.evaluation import evaluate_design
from app.modules.building.geometry import to_absolute
from app.modules.building.issues import Issue, Measure
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    BatchRejected,
    MoveOpening,
    Operation,
    ResizeOpening,
    apply_operations,
)
from app.modules.building.operations.openings import host_of, hosted, wall_zones
from app.modules.building.specification import BuildingSpecification
from app.modules.building.validation import validate_model
from app.modules.rules.model_checks import CIRCULATION, check_model
from app.modules.rules.profile import BuildingRulesProfile

IssueKey = tuple[str, uuid.UUID | None, str | None, str | None]


def issue_key(issue: Issue) -> IssueKey:
    return (issue.code, issue.element_id, issue.constraint, issue.rule_ref)


#: Model warnings an edit must not introduce: they are tolerated in a stored design (it may be
#: imported or older) but a plan edit may not cut a room off, remove the last way in, or leave a
#: habitable room without a window (generated models never have them).
EDIT_BLOCKING_WARNINGS = frozenset(
    {"ROOM_UNREACHABLE", "NO_ENTRANCE", "HABITABLE_ROOM_WITHOUT_WINDOW"}
)


def blocking(issue: Issue) -> bool:
    """Model errors and rules-profile findings (dimensional minimums) block an edit; so do
    broken MUST requirements (`requirement_changes`, severity error) and the warnings in
    `EDIT_BLOCKING_WARNINGS`."""
    return (
        issue.severity == "error"
        or issue.rule_ref is not None
        or issue.code in EDIT_BLOCKING_WARNINGS
    )


def model_issues(
    model: BuildingModel, profile: BuildingRulesProfile, material_ids: Iterable[str]
) -> list[Issue]:
    return [*validate_model(model, material_ids=material_ids), *check_model(model, profile)]


#: A circulation room part that the corridor minimum removes (m²) counts as a pinch.
PINCH_AREA_TOLERANCE = 0.01
#: Clearances are compared on the 1 mm grid of stored coordinates.
EPS_GAP = 0.0005


def _narrow_area(room: Room, min_width: float) -> float:
    """Area of the parts of a room narrower than `min_width` (morphological opening; mitred
    joins keep rectilinear corners exact)."""
    poly = ShapelyPolygon(to_absolute(room.properties.boundary, room.position, room.rotation))
    # 1 cm under half the minimum, so a part exactly at the minimum keeps a sliver that
    # survives the erosion (Shapely drops millimetre slivers).
    r = min_width / 2 - 0.01
    opened = poly.buffer(-r, join_style="mitre").buffer(r, join_style="mitre")
    return max(0.0, poly.area - opened.intersection(poly).area)


def circulation_pinches(
    base: BuildingModel, edited: BuildingModel, profile: BuildingRulesProfile
) -> list[Issue]:
    """Corridors and halls must stay passable along their whole length. The rules measure a
    room's main part (an alcove is fine in a bedroom); an edit must not squeeze part of a
    circulation room below the corridor minimum. Narrow parts the base already had are not
    counted against the edit."""
    min_width = profile.corridors.min_width_m
    before = {e.id: e for e in base.elements if isinstance(e, Room)}
    issues: list[Issue] = []
    for i, el in enumerate(edited.elements):
        if not isinstance(el, Room) or el.properties.room_type not in CIRCULATION:
            continue
        old = before.get(el.id)
        if old is not None and old.properties.boundary == el.properties.boundary:
            continue
        narrow = _narrow_area(el, min_width)
        if old is not None:
            narrow -= _narrow_area(old, min_width)
        if narrow > PINCH_AREA_TOLERANCE:
            issues.append(
                Issue(
                    severity="error",
                    code="EDIT_CIRCULATION_PINCH",
                    path=f"/elements/{i}/properties/boundary",
                    message=(
                        f"{el.name} would get a passage narrower than the {min_width} m "
                        "corridor minimum"
                    ),
                    rule_ref=profile.rule_ref("corridors.min_width_m"),
                    element_id=el.id,
                    measure=Measure(
                        quantity="narrow_area", actual=round(narrow, 3), limit=0.0, unit="m2"
                    ),
                )
            )
    return issues


def placed_openings(
    base: BuildingModel, edited: BuildingModel, operations: Sequence[Operation]
) -> list[Door | Window]:
    """Openings the edit placed: moved by `move_opening`, resized by `resize_opening`, or new."""
    moved = {op.opening_id for op in operations if isinstance(op, MoveOpening | ResizeOpening)}
    before = {e.id for e in base.elements}
    return [
        e
        for e in edited.elements
        if isinstance(e, Door | Window) and (e.id in moved or e.id not in before)
    ]


def opening_clearances(
    base: BuildingModel,
    edited: BuildingModel,
    operations: Sequence[Operation],
    profile: BuildingRulesProfile,
) -> list[Issue]:
    """A placed opening keeps the profile's clearance of solid wall to the walls that join its
    wall, to the wall's ends and to the other openings of the wall. Overlaps and cuts into a
    junction are model errors already; this is the margin beyond them."""
    if profile.openings is None:
        return []
    need = profile.openings.min_clearance_m
    placed = {o.id for o in placed_openings(base, edited, operations)}
    issues: list[Issue] = []
    for i, el in enumerate(edited.elements):
        if el.id not in placed or not isinstance(el, Door | Window):
            continue
        wall = host_of(edited, el)
        if wall is None:
            continue  # reported by the validator
        u0, u1 = el.position.x, el.position.x + el.dimensions.width
        gaps: list[tuple[float, str]] = [
            (u0, f"the start of {wall.name}"),
            (wall.dimensions.length - u1, f"the end of {wall.name}"),
        ]
        for lo, hi in wall_zones(edited, wall):
            if hi <= u0 + EPS_GAP:
                gaps.append((u0 - hi, f"the wall joining {wall.name}"))
            elif lo >= u1 - EPS_GAP:
                gaps.append((lo - u1, f"the wall joining {wall.name}"))
        for other in hosted(edited, wall):
            if other.id == el.id:
                continue
            o0, o1 = other.position.x, other.position.x + other.dimensions.width
            if o1 <= u0 + EPS_GAP:
                gaps.append((u0 - o1, other.name))
            elif o0 >= u1 - EPS_GAP:
                gaps.append((o0 - u1, other.name))
        gap, what = min(gaps, key=lambda g: g[0])
        if gap + EPS_GAP < need:
            issues.append(
                Issue(
                    severity="error",
                    code="EDIT_OPENING_CLEARANCE",
                    path=f"/elements/{i}/position/x",
                    message=(
                        f"{el.name} would be {max(gap, 0.0):.2f} m from {what}; keep at least "
                        f"{need} m of wall"
                    ),
                    rule_ref=profile.rule_ref("openings.min_clearance_m"),
                    element_id=el.id,
                    related_ids=[wall.id],
                    measure=Measure(
                        quantity="clearance", actual=round(max(gap, 0.0), 3), limit=need, unit="m"
                    ),
                )
            )
    return issues


def entrance_kept(base: BuildingModel, edited: BuildingModel) -> list[Issue]:
    """A design with an entrance door keeps one: other exterior doors (garden, garage) make the
    rooms reachable, but the house would have no front door."""

    def entrances(m: BuildingModel) -> list[Door]:
        return [
            e for e in m.elements if isinstance(e, Door) and e.properties.door_kind == "entrance"
        ]

    if not entrances(base) or entrances(edited):
        return []
    return [
        Issue(
            severity="error",
            code="EDIT_ENTRANCE_REMOVED",
            path="/elements",
            message="the design would have no entrance door; add another one first",
            element_id=entrances(base)[0].id,
        )
    ]


def requirement_changes(
    spec: BuildingSpecification, base: BuildingModel, edited: BuildingModel
) -> tuple[list[Issue], list[Issue]]:
    """Requirements of the spec that the base model meets and the edited one no longer does:
    MUST ones block the edit (a MUST requirement is never relaxed), SHOULD ones are warnings.
    Requirements the base already missed are not counted against the edit."""
    before = {r.path: r.met for r in evaluate_design(spec, base).requirements}
    must: list[Issue] = []
    should: list[Issue] = []
    for r in evaluate_design(spec, edited).requirements:
        if r.met or not before.get(r.path, False):
            continue
        issue = Issue(
            severity="error" if r.priority == "must" else "warning",
            code="EDIT_REQUIREMENT_UNMET" if r.priority == "must" else "EDIT_PREFERENCE_UNMET",
            path=r.path,
            message=(
                f"{r.label} is {'required' if r.priority == 'must' else 'preferred'}: expected "
                f"{r.expected}, the edited plan gives {r.delivered}"
            ),
        )
        (must if r.priority == "must" else should).append(issue)
    return must, should


def _instance_of(spec_key: str, semantic_key: str) -> bool:
    """Whether a room's semantic key is an instance of a spec room (`room:<key>[_<n>]`), as the
    design evaluation matches them."""
    name = semantic_key.removeprefix("room:")
    suffix = name.removeprefix(spec_key)
    return (
        semantic_key.startswith("room:")
        and name.startswith(spec_key)
        and (suffix == "" or (suffix.startswith("_") and suffix[1:].isdigit()))
    )


def program_changes(
    spec: BuildingSpecification, base: BuildingModel, edited: BuildingModel
) -> tuple[list[Issue], list[Issue]]:
    """Rooms the spec asked for that the edit retypes or merges away. The design evaluation
    finds spec rooms by key, so it would still credit a bedroom turned into a study; this keeps
    the room program honest. A spec room with a MUST requirement blocks (a MUST is never
    relaxed); otherwise the change is a warning."""
    after = {e.id: e for e in edited.elements if isinstance(e, Room)}
    must: list[Issue] = []
    should: list[Issue] = []
    for i, req in enumerate(spec.rooms):
        prefix = f"/rooms/{i}/"
        strict = any(
            r.priority == "must" and (r.path + "/").startswith(prefix) for r in spec.requirements
        )
        for room in base.elements:
            if (
                not isinstance(room, Room)
                or room.properties.room_type.value != req.type.value
                or not _instance_of(req.key, room.semantic_key)
            ):
                continue
            now = after.get(room.id)
            if now is not None and now.properties.room_type == room.properties.room_type:
                continue
            wanted = req.type.value.replace("_", " ")
            change = (
                "would be merged into another room"
                if now is None
                else f"would become a {now.properties.room_type.value.replace('_', ' ')}"
            )
            issue = Issue(
                severity="error" if strict else "warning",
                code="EDIT_REQUIREMENT_UNMET" if strict else "EDIT_PROGRAM_CHANGED",
                path=f"/rooms/{i}",
                message=(
                    f"{room.name} is the {wanted} the specification "
                    f"{'requires' if strict else 'asks for'}; it {change}"
                ),
                element_id=room.id,
            )
            (must if strict else should).append(issue)
    return must, should


@dataclass
class EditRejection:
    code: str
    message: str
    index: int | None = None
    element_id: uuid.UUID | None = None
    related_ids: list[uuid.UUID] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)


@dataclass
class EditOutcome:
    model: BuildingModel | None
    warnings: list[Issue] = field(default_factory=list)
    rejection: EditRejection | None = None
    # Elements whose stored data differs from the base model (for highlighting).
    changed_ids: list[uuid.UUID] = field(default_factory=list)


class _BaseIssueCache:
    """Issue keys of base versions. Versions are immutable, so a version id identifies its
    findings for good; bounded so a long-running process does not grow without limit."""

    def __init__(self, size: int = 32) -> None:
        self.size = size
        self.entries: OrderedDict[tuple[str, str], frozenset[IssueKey]] = OrderedDict()
        self.lock = Lock()

    def get(self, key: tuple[str, str]) -> frozenset[IssueKey] | None:
        with self.lock:
            hit = self.entries.get(key)
            if hit is not None:
                self.entries.move_to_end(key)
            return hit

    def put(self, key: tuple[str, str], value: frozenset[IssueKey]) -> None:
        with self.lock:
            self.entries[key] = value
            self.entries.move_to_end(key)
            while len(self.entries) > self.size:
                self.entries.popitem(last=False)


BASE_ISSUES = _BaseIssueCache()


def changed_elements(before: BuildingModel, after: BuildingModel) -> list[uuid.UUID]:
    old = {e.id: e for e in before.elements}
    new = {e.id: e for e in after.elements}
    ids = {i for i in new if old.get(i) != new[i]} | (old.keys() - new.keys())
    return sorted(ids, key=str)


def evaluate_edits(
    base: BuildingModel,
    operations: Sequence[Operation],
    profile: BuildingRulesProfile,
    material_ids: Iterable[str],
    *,
    spec: BuildingSpecification | None = None,
    cache_key: tuple[str, str] | None = None,
) -> EditOutcome:
    """`spec`: the specification the base version was generated from (None for hand-authored
    models). Its MUST requirements that the base meets must still be met after the edit."""
    materials = frozenset(material_ids)
    try:
        edited = apply_operations(base, operations)
    except BatchRejected as err:
        return EditOutcome(
            model=None,
            rejection=EditRejection(
                code=err.code,
                message=err.message,
                index=err.index,
                element_id=err.element_id,
                related_ids=err.related_ids,
            ),
        )
    base_keys = BASE_ISSUES.get(cache_key) if cache_key else None
    if base_keys is None:
        base_keys = frozenset(issue_key(i) for i in model_issues(base, profile, materials))
        if cache_key:
            BASE_ISSUES.put(cache_key, base_keys)
    introduced = [
        i for i in model_issues(edited, profile, materials) if issue_key(i) not in base_keys
    ]
    must, should = requirement_changes(spec, base, edited) if spec else ([], [])
    if spec:
        program_must, program_should = program_changes(spec, base, edited)
        must, should = must + program_must, should + program_should
    blockers = (
        must
        + circulation_pinches(base, edited, profile)
        + opening_clearances(base, edited, operations, profile)
        + entrance_kept(base, edited)
        + [i for i in introduced if blocking(i)]
    )
    if blockers:
        first = blockers[0]
        more = (
            f" ({len(blockers) - 1} more problem{'s' if len(blockers) > 2 else ''})"
            if len(blockers) > 1
            else ""
        )
        return EditOutcome(
            model=None,
            rejection=EditRejection(
                code="EDIT_INVALID",
                message=f"This change would make the design invalid: {first.message}{more}",
                index=len(operations) - 1 if operations else None,
                element_id=first.element_id,
                related_ids=list(first.related_ids),
                issues=blockers,
            ),
        )
    return EditOutcome(
        model=edited,
        warnings=should + [i for i in introduced if not blocking(i)],
        changed_ids=changed_elements(base, edited),
    )
