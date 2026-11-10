"""ModificationDraft -> typed editing operations, deterministically (docs/ai-pipeline.md §11).

For every requested change, in the user's order, on the model the earlier changes produced:

1. Missing or ambiguous facts become questions with options (which room, which side, how far,
   merge or open up, ...). Nothing is guessed: a null field of the draft is a question, and when
   several placements are valid the user chooses. A single valid placement is used and said so.
2. The change becomes D2 editing operations (`resize_room`, `add_opening`, `remove_wall`, ...),
   placed from the model's own geometry (free wall stretches, the profile's opening clearance).
3. Every candidate is judged by the same `evaluate_edits` as a manual edit: model invariants,
   rules profile, circulation, reachability, MUST requirements of the spec. Refused candidates
   are reported with the editor's reason; nothing is silently dropped.

Pure (no I/O). Answers re-run this resolver on the same draft, never the AI, so the question ids
and options are stable.
"""

import math
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.modules.ai.modification_context import (
    Compass,
    compass_of,
    opening_refs,
    opening_rooms,
    room_refs,
    side_is_exterior,
    side_neighbours,
)
from app.modules.ai.schemas.modification import ModificationDraft, RequestedChange
from app.modules.building.diff import ModelDiff, diff_models
from app.modules.building.elements import Door, Room, Wall, Window
from app.modules.building.enums import RoomType, WallKind
from app.modules.building.facades import facade_of_normal
from app.modules.building.geometry import Point, wall_axis
from app.modules.building.model import BuildingModel
from app.modules.building.operations import (
    AddOpening,
    Operation,
    RemoveElement,
    RemoveWall,
    RenameRoom,
    ResizeOpening,
    ResizeRoom,
    SetRoomType,
    room_sides,
)
from app.modules.building.operations.openings import hosted, wall_zones
from app.modules.building.operations.rooms import FIXED_ROOM_TYPES, RoomSide
from app.modules.building.primitives import EPS
from app.modules.building.specification import BuildingSpecification
from app.modules.editing.evaluate import EditOutcome, evaluate_edits
from app.modules.modification.schemas import (
    ClarificationQuestion,
    ModifyAnswer,
    PlannedChange,
    QuestionOption,
)
from app.modules.rules.profile import BuildingRulesProfile

AMOUNT_OPTIONS = ("0.5", "1", "1.5", "2")
MAX_DISTANCE_M = 20.0


@dataclass
class Resolution:
    changes: list[PlannedChange]
    questions: list[ClarificationQuestion]
    operations: list[Operation]  # the new ones only
    outcome: EditOutcome | None  # session operations + new ones
    diff: ModelDiff | None


@dataclass
class _Step:
    """The result of resolving one change."""

    status: str
    summary: str = ""
    operations: list[Operation] = field(default_factory=list)
    reason: str | None = None
    questions: list[ClarificationQuestion] = field(default_factory=list)


class _Ctx:
    def __init__(
        self,
        base: BuildingModel,
        session_ops: Sequence[Operation],
        profile: BuildingRulesProfile,
        materials: Iterable[str],
        spec: BuildingSpecification | None,
        cache_key: tuple[str, str] | None,
    ) -> None:
        self.base = base
        self.profile = profile
        self.materials = frozenset(materials)
        self.spec = spec
        self.cache_key = cache_key
        self.ops: list[Operation] = list(session_ops)
        self._cache: dict[str, EditOutcome] = {}
        start = self.check(self.ops) if self.ops else None
        if start is not None and start.model is None:
            raise ValueError("the editing session's operations are not valid any more")
        self.start: BuildingModel = start.model if start and start.model else base
        self.current: BuildingModel = self.start
        # References are those of the model the AI saw: the session's model.
        self.rooms = {ref: r.id for ref, r in room_refs(self.start).items()}
        self.openings = {ref: o.id for ref, o in opening_refs(self.start).items()}

    def check(self, ops: Sequence[Operation]) -> EditOutcome:
        key = repr([op.model_dump(mode="json") for op in ops])
        if key not in self._cache:
            self._cache[key] = evaluate_edits(
                self.base,
                ops,
                self.profile,
                self.materials,
                spec=self.spec,
                cache_key=self.cache_key,
            )
        return self._cache[key]

    def try_ops(self, new: Sequence[Operation]) -> EditOutcome:
        return self.check([*self.ops, *new])

    def element(self, element_id: uuid.UUID) -> Any:
        return next((e for e in self.current.elements if e.id == element_id), None)

    def room(self, ref: str | None) -> Room | None:
        if ref is None or ref not in self.rooms:
            return None
        el = self.element(self.rooms[ref])
        return el if isinstance(el, Room) else None

    def ref_of(self, room: Room) -> str | None:
        return next((ref for ref, i in self.rooms.items() if i == room.id), None)


def _reason(outcome: EditOutcome) -> str:
    r = outcome.rejection
    return r.message if r else "The change is not possible."


def _q(
    index: int,
    field_name: str,
    text: str,
    input_kind: str,
    options: Sequence[tuple[str, str]] = (),
) -> ClarificationQuestion:
    return ClarificationQuestion(
        id=f"{index}.{field_name}",
        change_index=index,
        field=field_name,
        text=text,
        input=input_kind,
        options=[QuestionOption(value=v, label=label) for v, label in options],
    )


def _type_label(room_type: RoomType | str) -> str:
    value = room_type.value if isinstance(room_type, RoomType) else room_type
    return value.replace("_", " ")


def _room_label(room: Room, model: BuildingModel) -> str:
    level = next((lv for lv in model.levels if lv.id == room.level_id), None)
    floor = f", {level.name}" if level else ""
    kind = _type_label(room.properties.room_type)
    return f"{room.name} ({kind}{floor}, {room.dimensions.area:.1f} m²)"


# --- answers -------------------------------------------------------------------------------


def _apply_answers(
    change: RequestedChange, index: int, answers: dict[str, str]
) -> tuple[RequestedChange, dict[str, str]]:
    """The change with the user's answers filled in; `choices` keeps answers that pick one of
    several computed options (side, wall, opening)."""
    update: dict[str, Any] = {}
    choices: dict[str, str] = {}
    for qid, value in answers.items():
        prefix, _, name = qid.partition(".")
        if prefix != str(index):
            continue
        direction = name == "direction" and value in ("increase", "decrease")
        if name in ("room", "other_room", "opening", "new_name") or direction:
            update[name] = value
        elif name in ("amount_m", "width_m", "height_m"):
            try:
                number = float(value.replace(",", "."))
            except ValueError:
                continue
            if 0 < number <= MAX_DISTANCE_M and math.isfinite(number):
                update[name] = round(number, 3)
        elif name == "merge_rooms" and value in ("true", "false"):
            update[name] = value == "true"
        elif name == "new_room_type":
            try:
                update[name] = RoomType(value)
            except ValueError:
                continue
        else:
            choices[name] = value
    if update:
        change = change.model_copy(update=update)
    return change, choices


# --- shared pieces -------------------------------------------------------------------------


def _ask_room(ctx: _Ctx, i: int, change: RequestedChange, field_name: str, text: str) -> _Step:
    hint = (change.room_hint or "").lower().strip()
    rooms = [r for r in (ctx.room(ref) for ref in ctx.rooms) if r is not None]
    if hint and field_name == "room":
        words = [w for w in hint.replace("-", " ").split() if len(w) > 2]
        matching = [
            r
            for r in rooms
            if any(w in r.name.lower() or w in _type_label(r.properties.room_type) for w in words)
        ]
        rooms = matching or rooms
    options = [(ctx.ref_of(r) or "", _room_label(r, ctx.current)) for r in rooms]
    return _Step("needs_clarification", questions=[_q(i, field_name, text, "choice", options)])


def _side_beyond(ctx: _Ctx, room: Room, side: RoomSide) -> str:
    if side_is_exterior(side):
        return f"exterior wall, {facade_of_normal(*side.outward).value} facade"
    names = [n.name for n in side_neighbours(ctx.current, room, side)]
    return ", ".join(names) if names else "open boundary"


def _movable(side: RoomSide) -> bool:
    return bool(side.walls) and side.covered >= side.length - EPS


def _axis(compass: Compass) -> str:
    return "x" if compass in ("east", "west") else "y"


def _extent_axis_of_house(ctx: _Ctx) -> str:
    """Axis of the house's shorter extent (its width), from the exterior walls."""
    pts = [
        p
        for w in ctx.current.elements
        if isinstance(w, Wall) and w.properties.wall_kind == WallKind.EXTERIOR
        for p in wall_axis(w)
    ]
    if not pts:
        return "x"
    w = max(p[0] for p in pts) - min(p[0] for p in pts)
    d = max(p[1] for p in pts) - min(p[1] for p in pts)
    return "x" if w <= d else "y"


def _extent_axis(room: Room, ctx: _Ctx, dimension: str) -> str:
    """Axis of a room's width (its shorter extent) or length (its longer extent)."""
    sides = room_sides(ctx.current, room)
    xs = [p for s in sides for p in (s.start[0], s.end[0])]
    ys = [p for s in sides for p in (s.start[1], s.end[1])]
    w, d = max(xs) - min(xs), max(ys) - min(ys)
    shorter = "x" if w <= d else "y"
    return shorter if dimension == "width" else ("y" if shorter == "x" else "x")


# --- resize_room / move_wall ---------------------------------------------------------------


def _resize(ctx: _Ctx, i: int, change: RequestedChange, choices: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "Which room should change?")
    questions = []
    if change.direction is None:
        questions.append(
            _q(
                i,
                "direction",
                f"Should {room.name} become larger or smaller?",
                "choice",
                [("increase", "Larger"), ("decrease", "Smaller")],
            )
        )
    if change.amount_m is None:
        questions.append(
            _q(
                i,
                "amount_m",
                f"By how many metres should the wall of {room.name} move?",
                "number",
                [(a, f"{a} m") for a in AMOUNT_OPTIONS],
            )
        )
    if questions:
        return _Step("needs_clarification", questions=questions)
    if change.amount_m is None:  # pragma: no cover - asked above
        return _Step("needs_clarification")
    sign = 1.0 if change.direction == "increase" else -1.0
    amount = change.amount_m

    sides = [s for s in room_sides(ctx.current, room) if s.length > EPS]
    candidates = [s for s in sides if _movable(s)]
    other = ctx.room(change.other_room)
    if change.action == "move_wall" and other is not None:
        candidates = [
            s
            for s in candidates
            if any(n.id == other.id for n in side_neighbours(ctx.current, room, s))
        ]
        if not candidates:
            return _Step(
                "refused",
                reason=f"{room.name} and {other.name} do not share a wall that can move.",
            )
    if change.side is not None:
        candidates = [s for s in candidates if compass_of(s.outward) == change.side]
    elif change.dimension is not None:
        axis = _extent_axis(room, ctx, change.dimension)
        candidates = [s for s in candidates if _axis(compass_of(s.outward)) == axis]
    if not candidates:
        where = f"its {change.side} side" if change.side else "any side"
        return _Step(
            "refused",
            reason=f"{room.name} cannot change at {where}: no side there runs along walls "
            "that can move (open boundaries cannot be moved).",
        )

    valid: list[tuple[RoomSide, ResizeRoom]] = []
    reasons: list[str] = []
    for side in candidates:
        op = ResizeRoom(room_id=room.id, edge=side.index, delta_m=round(sign * amount, 3))
        outcome = ctx.try_ops([op])
        if outcome.model is not None:
            valid.append((side, op))
        else:
            reasons.append(f"{compass_of(side.outward)} side: {_reason(outcome)}")
    if not valid:
        return _Step(
            "refused",
            reason=f"{room.name} cannot {'grow' if sign > 0 else 'shrink'} by {amount:.2f} m. "
            + " · ".join(reasons[:3]),
        )
    if choices.get("target") == "skip":
        return _Step("refused", reason="Skipped: you chose not to make this change.")
    if "target" in choices:
        chosen = [v for v in valid if f"s{v[0].index}" == choices["target"]]
        valid = chosen or valid
    if len(valid) > 1:
        options = [
            (
                f"s{side.index}",
                f"{compass_of(side.outward).capitalize()} side → {_side_beyond(ctx, room, side)}",
            )
            for side, _ in valid
        ]
        verb = "grow" if sign > 0 else "shrink"
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "target",
                    f"Which side of {room.name} should {verb} by {amount:.2f} m?",
                    "choice",
                    options,
                )
            ],
        )
    side, op = valid[0]
    if side_is_exterior(side) and change.side is None and choices.get("target") != f"s{side.index}":
        # Moving a facade changes the footprint, every storey on that line, slabs and roof:
        # never without an explicit yes, even when it is the only possible side.
        compass = compass_of(side.outward)
        what = "wider" if _axis(compass) == _extent_axis_of_house(ctx) else "longer"
        verb_house = (
            f"the house gets {amount:.2f} m {what}"
            if sign > 0
            else f"the house gets {amount:.2f} m smaller"
        )
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "target",
                    f"{room.name} can only change at its {compass} side, which is an exterior "
                    f"wall: the {compass} facade moves on every floor and {verb_house}. "
                    "Do that?",
                    "choice",
                    [(f"s{side.index}", f"Yes, move the {compass} facade"), ("skip", "No, skip")],
                )
            ],
        )
    only = (
        " (the only side where it is possible)"
        if len(candidates) > 1 and "target" not in choices
        else ""
    )
    verb = "grows" if sign > 0 else "shrinks"
    return _Step(
        "planned",
        summary=f"{room.name} {verb} {amount:.2f} m at its {compass_of(side.outward)} side "
        f"({_side_beyond(ctx, room, side)}){only}",
        operations=[op],
    )


# --- openings ------------------------------------------------------------------------------


def _wall_u(wall: Wall, p: Point) -> float:
    (ax, ay), (bx, by) = wall_axis(wall)
    length = math.dist((ax, ay), (bx, by)) or 1.0
    return ((p[0] - ax) * (bx - ax) + (p[1] - ay) * (by - ay)) / length


def _free_stretch(ctx: _Ctx, wall: Wall, lo: float, hi: float, width: float) -> float | None:
    """Start offset for an opening of `width` centred in the longest free stretch of the wall
    between `lo` and `hi`, keeping the profile's clearance to openings, junctions and ends."""
    clearance = ctx.profile.openings.min_clearance_m if ctx.profile.openings else 0.0
    length = wall.dimensions.length
    blocked: list[tuple[float, float]] = [(-1.0, clearance), (length - clearance, length + 1.0)]
    blocked += [
        (o.position.x - clearance, o.position.x + o.dimensions.width + clearance)
        for o in hosted(ctx.current, wall)
    ]
    blocked += [(a - clearance, b + clearance) for a, b in wall_zones(ctx.current, wall)]
    blocked.sort()
    best: tuple[float, float] | None = None
    cursor = max(lo, 0.0)
    for a, b in blocked:
        if a > cursor:
            seg = (cursor, min(a, hi))
            if seg[1] - seg[0] > (best[1] - best[0] if best else 0):
                best = seg
        cursor = max(cursor, b)
        if cursor >= hi:
            break
    if cursor < hi:
        seg = (cursor, hi)
        if seg[1] - seg[0] > (best[1] - best[0] if best else 0):
            best = seg
    if best is None or best[1] - best[0] + EPS < width:
        return None
    return round((best[0] + best[1]) / 2 - width / 2, 3)


def _template_window(ctx: _Ctx, room: Room) -> tuple[float, float, float]:
    own = [o for o in _room_openings(ctx, room) if isinstance(o, Window)]
    if own:
        w = max(own, key=lambda o: (o.dimensions.width, o.semantic_key))
        return w.dimensions.width, w.dimensions.height, w.position.z
    same_level = [
        e for e in ctx.current.elements if isinstance(e, Window) and e.level_id == room.level_id
    ]
    if same_level:
        sizes: dict[tuple[float, float, float], int] = {}
        for w in same_level:
            key = (w.dimensions.width, w.dimensions.height, w.position.z)
            sizes[key] = sizes.get(key, 0) + 1
        return max(sizes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    wr = ctx.profile.windows
    return wr.min_width_m, wr.min_height_m, wr.min_sill_height_m


def _template_door(ctx: _Ctx) -> tuple[float, float]:
    doors = [
        e
        for e in ctx.current.elements
        if isinstance(e, Door) and e.properties.door_kind == "interior"
    ]
    if doors:
        sizes: dict[tuple[float, float], int] = {}
        for d in doors:
            key = (d.dimensions.width, d.dimensions.height)
            sizes[key] = sizes.get(key, 0) + 1
        return max(sizes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    rule = ctx.profile.doors.interior
    return rule.min_width_m, rule.min_height_m


def _room_openings(ctx: _Ctx, room: Room) -> list[Door | Window]:
    return [
        o
        for o in ctx.current.elements
        if isinstance(o, Door | Window)
        and any(r.id == room.id for r in opening_rooms(ctx.current, o))
    ]


def _side_range(wall: Wall, side: RoomSide) -> tuple[float, float]:
    a, b = sorted((_wall_u(wall, side.start), _wall_u(wall, side.end)))
    return max(a, 0.0), min(b, wall.dimensions.length)


def _add_window(ctx: _Ctx, i: int, change: RequestedChange, choices: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "Which room should get the window?")
    sides = [s for s in room_sides(ctx.current, room) if side_is_exterior(s) and s.length > EPS]
    if not sides:
        return _Step(
            "refused",
            reason=f"{room.name} has no exterior wall; windows go in exterior walls.",
        )
    if change.side is not None:
        sides = [s for s in sides if compass_of(s.outward) == change.side]
        if not sides:
            return _Step(
                "refused", reason=f"{room.name} has no exterior wall on its {change.side} side."
            )
    tw, th, ts = _template_window(ctx, room)
    width = change.width_m or tw
    height = change.height_m or th
    sill = change.sill_m if change.sill_m is not None else ts
    widths = (
        [width] if change.width_m else sorted({tw, ctx.profile.windows.min_width_m}, reverse=True)
    )

    valid: list[tuple[RoomSide, Wall, AddOpening]] = []
    reasons: list[str] = []
    for side in sides:
        placed = False
        for wall in sorted(side.walls, key=lambda w: w.semantic_key):
            if wall.properties.wall_kind != WallKind.EXTERIOR:
                continue
            lo, hi = _side_range(wall, side)
            for w in widths:
                offset = _free_stretch(ctx, wall, lo, hi, w)
                if offset is None:
                    continue
                op = AddOpening(
                    kind="window",
                    host_wall_id=wall.id,
                    offset_m=max(offset, 0.0),
                    width_m=w,
                    height_m=height,
                    sill_m=sill,
                )
                outcome = ctx.try_ops([op])
                if outcome.model is not None:
                    valid.append((side, wall, op))
                    placed = True
                    break
                reasons.append(f"{compass_of(side.outward)} side: {_reason(outcome)}")
            if placed:
                break
        if not placed and not any(r.startswith(compass_of(side.outward)) for r in reasons):
            reasons.append(
                f"{compass_of(side.outward)} side: no free stretch of wall for a "
                f"{widths[-1]:.2f} m window"
            )
    if not valid:
        return _Step(
            "refused",
            reason=f"No window fits in {room.name}. " + " · ".join(reasons[:3]),
        )
    if "target" in choices:
        valid = [v for v in valid if f"s{v[0].index}" == choices["target"]] or valid
    if len(valid) > 1:
        options = [
            (
                f"s{side.index}",
                f"{compass_of(side.outward).capitalize()} side "
                f"({facade_of_normal(*side.outward).value} facade, {wall.name})",
            )
            for side, wall, _ in valid
        ]
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "target",
                    f"On which side of {room.name} should the new window go?",
                    "choice",
                    options,
                )
            ],
        )
    side, wall, op = valid[0]
    note = (
        ""
        if change.width_m
        else (
            " (sized like the room's other windows)"
            if op.width_m == tw
            else " (narrower: the wider size does not fit)"
        )
    )
    return _Step(
        "planned",
        summary=f"New window {op.width_m:.2f} x {op.height_m:.2f} m (sill {op.sill_m:.2f} m) in "
        f"{room.name}, {compass_of(side.outward)} side ({wall.name}){note}",
        operations=[op],
    )


def _add_door(ctx: _Ctx, i: int, change: RequestedChange, choices: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "Which room should get the door?")
    shared = [
        s
        for s in room_sides(ctx.current, room)
        if s.walls and not side_is_exterior(s) and s.length > EPS
    ]
    other = ctx.room(change.other_room)
    if other is None:
        neighbours: dict[uuid.UUID, Room] = {}
        for s in shared:
            for n in side_neighbours(ctx.current, room, s):
                neighbours[n.id] = n
        if not neighbours:
            return _Step("refused", reason=f"{room.name} has no interior wall to put a door in.")
        options = [(ctx.ref_of(n) or "", _room_label(n, ctx.current)) for n in neighbours.values()]
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "other_room",
                    f"The door from {room.name} should lead into which room?",
                    "choice",
                    options,
                )
            ],
        )
    width, height = _template_door(ctx)
    width = change.width_m or width
    height = change.height_m or height
    reasons: list[str] = []
    for side in shared:
        if not any(n.id == other.id for n in side_neighbours(ctx.current, room, side)):
            continue
        for wall in sorted(side.walls, key=lambda w: w.semantic_key):
            if wall.properties.wall_kind == WallKind.EXTERIOR:
                continue
            lo, hi = _side_range(wall, side)
            # Only the stretch the two rooms share.
            other_side = [
                s for s in room_sides(ctx.current, other) if any(w.id == wall.id for w in s.walls)
            ]
            for s2 in other_side:
                a2, b2 = _side_range(wall, s2)
                lo2, hi2 = max(lo, a2), min(hi, b2)
                offset = _free_stretch(ctx, wall, lo2, hi2, width)
                if offset is None:
                    continue
                op = AddOpening(
                    kind="door",
                    host_wall_id=wall.id,
                    offset_m=max(offset, 0.0),
                    width_m=width,
                    height_m=height,
                )
                outcome = ctx.try_ops([op])
                if outcome.model is not None:
                    return _Step(
                        "planned",
                        summary=f"New door {width:.2f} x {height:.2f} m between {room.name} and "
                        f"{other.name} ({wall.name})",
                        operations=[op],
                    )
                reasons.append(_reason(outcome))
    if not reasons:
        return _Step(
            "refused",
            reason=f"{room.name} and {other.name} share no interior wall with a free stretch of "
            f"{width:.2f} m for a door.",
        )
    return _Step(
        "refused", reason=f"No door fits between {room.name} and {other.name}. {reasons[0]}"
    )


def _pick_opening(ctx: _Ctx, i: int, change: RequestedChange, verb: str) -> Door | Window | _Step:
    if change.opening is not None:
        if change.opening not in ctx.openings:
            return _Step("refused", reason=f"Opening {change.opening} is not in the design.")
        el = ctx.element(ctx.openings[change.opening])
        if not isinstance(el, Door | Window):
            return _Step("refused", reason=f"Opening {change.opening} no longer exists.")
        return el
    room = ctx.room(change.room)
    if room is None:
        if change.room is None and change.room_hint is None and change.opening_kind is None:
            return _Step("refused", reason="The request does not say which door or window.")
        if change.room is None:
            return _ask_room(ctx, i, change, "room", f"In which room is the opening to {verb}?")
        return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
    found = [
        o
        for o in _room_openings(ctx, room)
        if change.opening_kind is None or (change.opening_kind == "window") == isinstance(o, Window)
    ]
    if not found:
        kind = change.opening_kind or "door or window"
        return _Step("refused", reason=f"{room.name} has no {kind}.")
    if len(found) == 1:
        return found[0]
    ref_by_id = {v: k for k, v in ctx.openings.items()}
    options = [
        (
            ref_by_id.get(o.id, ""),
            f"{o.name} ({'window' if isinstance(o, Window) else 'door'}, "
            f"{o.dimensions.width:.2f} x {o.dimensions.height:.2f} m)",
        )
        for o in found
        if o.id in ref_by_id
    ]
    return _Step(
        "needs_clarification",
        questions=[
            _q(i, "opening", f"Which opening of {room.name} should {verb}?", "choice", options)
        ],
    )


def _remove_opening(ctx: _Ctx, i: int, change: RequestedChange, _: dict[str, str]) -> _Step:
    picked = _pick_opening(ctx, i, change, "be removed")
    if isinstance(picked, _Step):
        return picked
    op = RemoveElement(element_id=picked.id)
    outcome = ctx.try_ops([op])
    if outcome.model is None:
        return _Step("refused", reason=f"{picked.name} cannot be removed: {_reason(outcome)}")
    return _Step("planned", summary=f"{picked.name} removed", operations=[op])


def _resize_opening(ctx: _Ctx, i: int, change: RequestedChange, _: dict[str, str]) -> _Step:
    picked = _pick_opening(ctx, i, change, "change size")
    if isinstance(picked, _Step):
        return picked
    if change.width_m is None and change.height_m is None and change.sill_m is None:
        w = picked.dimensions.width
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "width_m",
                    f"How wide should {picked.name} be (now {w:.2f} m)?",
                    "number",
                    [(f"{w + d:.2f}", f"{w + d:.2f} m") for d in (0.3, 0.6, 0.9)],
                )
            ],
        )
    op = ResizeOpening(
        opening_id=picked.id,
        width_m=change.width_m or picked.dimensions.width,
        height_m=change.height_m or picked.dimensions.height,
        sill_m=change.sill_m if isinstance(picked, Window) else None,
    )
    outcome = ctx.try_ops([op])
    if outcome.model is None:
        return _Step("refused", reason=f"{picked.name} cannot take that size: {_reason(outcome)}")
    return _Step(
        "planned",
        summary=f"{picked.name}: {picked.dimensions.width:.2f} x {picked.dimensions.height:.2f} m "
        f"→ {op.width_m:.2f} x {op.height_m:.2f} m",
        operations=[op],
    )


# --- rooms ---------------------------------------------------------------------------------


def _rename(ctx: _Ctx, i: int, change: RequestedChange, _: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "Which room should be renamed?")
    if not change.new_name:
        return _Step(
            "needs_clarification",
            questions=[_q(i, "new_name", f"What should {room.name} be called?", "text")],
        )
    op = RenameRoom(room_id=room.id, name=change.new_name)
    outcome = ctx.try_ops([op])
    if outcome.model is None:
        return _Step("refused", reason=_reason(outcome))
    return _Step(
        "planned", summary=f"{room.name} renamed to {change.new_name.strip()}", operations=[op]
    )


def _retype(ctx: _Ctx, i: int, change: RequestedChange, _: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "Which room should change its type?")
    if change.new_room_type is None:
        options = [(t.value, _type_label(t)) for t in RoomType if t not in FIXED_ROOM_TYPES]
        return _Step(
            "needs_clarification",
            questions=[
                _q(i, "new_room_type", f"What should {room.name} become?", "choice", options)
            ],
        )
    op = SetRoomType(room_id=room.id, room_type=change.new_room_type)
    outcome = ctx.try_ops([op])
    if outcome.model is None:
        return _Step("refused", reason=_reason(outcome))
    return _Step(
        "planned",
        summary=f"{room.name}: {_type_label(room.properties.room_type)} → "
        f"{_type_label(change.new_room_type)}",
        operations=[op],
    )


def _remove_wall(ctx: _Ctx, i: int, change: RequestedChange, _: dict[str, str]) -> _Step:
    room = ctx.room(change.room)
    if room is None:
        if change.room is not None:
            return _Step("refused", reason=f"Room {change.room} no longer exists in the design.")
        return _ask_room(ctx, i, change, "room", "The wall of which room should be removed?")
    other = ctx.room(change.other_room)
    if other is None:
        neighbours: dict[uuid.UUID, Room] = {}
        for s in room_sides(ctx.current, room):
            if s.walls and not side_is_exterior(s):
                for n in side_neighbours(ctx.current, room, s):
                    neighbours[n.id] = n
        if not neighbours:
            return _Step("refused", reason=f"{room.name} has no interior wall to remove.")
        options = [(ctx.ref_of(n) or "", _room_label(n, ctx.current)) for n in neighbours.values()]
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "other_room",
                    f"Remove the wall between {room.name} and which room?",
                    "choice",
                    options,
                )
            ],
        )
    if change.merge_rooms is None:
        return _Step(
            "needs_clarification",
            questions=[
                _q(
                    i,
                    "merge_rooms",
                    f"Make {room.name} and {other.name} one room, or keep both "
                    "and open them into each other?",
                    "choice",
                    [("true", "Merge into one room"), ("false", "Open up, keep both rooms")],
                )
            ],
        )
    walls: dict[uuid.UUID, Wall] = {}
    for s in room_sides(ctx.current, room):
        if any(n.id == other.id for n in side_neighbours(ctx.current, room, s)):
            for w in s.walls:
                if w.properties.wall_kind != WallKind.EXTERIOR:
                    walls[w.id] = w
    if not walls:
        return _Step("refused", reason=f"{room.name} and {other.name} do not share a wall.")
    ordered = sorted(walls.values(), key=lambda w: w.semantic_key)
    ops: list[Operation] = [
        RemoveWall(wall_id=w.id, merge_rooms=bool(change.merge_rooms) and k == len(ordered) - 1)
        for k, w in enumerate(ordered)
    ]
    outcome = ctx.try_ops(ops)
    if outcome.model is None:
        return _Step(
            "refused",
            reason=f"The wall between {room.name} and {other.name} cannot be removed: "
            f"{_reason(outcome)}",
        )
    what = "merged into one room" if change.merge_rooms else "opened into each other"
    return _Step(
        "planned",
        summary=f"Wall between {room.name} and {other.name} removed ({what})",
        operations=ops,
    )


_RESOLVERS: dict[str, Callable[[_Ctx, int, RequestedChange, dict[str, str]], _Step]] = {
    "resize_room": _resize,
    "move_wall": _resize,
    "add_window": _add_window,
    "add_door": _add_door,
    "remove_opening": _remove_opening,
    "resize_opening": _resize_opening,
    "rename_room": _rename,
    "set_room_type": _retype,
    "remove_wall": _remove_wall,
}


def resolve_draft(
    draft: ModificationDraft,
    *,
    base: BuildingModel,
    session_ops: Sequence[Operation],
    answers: Sequence[ModifyAnswer],
    profile: BuildingRulesProfile,
    materials: Iterable[str],
    spec: BuildingSpecification | None,
    cache_key: tuple[str, str] | None = None,
) -> Resolution:
    ctx = _Ctx(base, session_ops, profile, materials, spec, cache_key)
    given = {a.question_id: a.value for a in answers}
    changes: list[PlannedChange] = []
    questions: list[ClarificationQuestion] = []
    new_ops: list[Operation] = []
    for i, raw in enumerate(draft.changes):
        change, choices = _apply_answers(raw, i, given)
        step = _RESOLVERS[change.action](ctx, i, change, choices)
        if step.status == "planned":
            ctx.ops.extend(step.operations)
            new_ops.extend(step.operations)
            outcome = ctx.check(ctx.ops)
            if outcome.model is not None:
                ctx.current = outcome.model
        questions.extend(step.questions)
        changes.append(
            PlannedChange(
                index=i,
                quote=change.quote,
                action=change.action,
                status=step.status,
                summary=step.summary
                or (step.reason or "")
                or (step.questions[0].text if step.questions else ""),
                operations=step.operations,
                reason=step.reason,
            )
        )
    final: EditOutcome | None = ctx.check(ctx.ops) if ctx.ops else None
    diff = (
        diff_models(ctx.start, final.model)
        if new_ops and final is not None and final.model is not None
        else None
    )
    return Resolution(
        changes=changes, questions=questions, operations=new_ops, outcome=final, diff=diff
    )
