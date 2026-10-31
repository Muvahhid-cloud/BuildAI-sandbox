"""Step 1 — Program: expand the spec's room requirements into individual room requests."""

from dataclasses import dataclass, field

from app.modules.building.enums import RoomType, Zone
from app.modules.building.intent import area_range, requirements
from app.modules.building.specification import BuildingSpecification, RoomFeature
from app.modules.layout.config import LayoutConfig
from app.modules.rules.profile import BuildingRulesProfile

PUBLIC = frozenset(
    {RoomType.LIVING, RoomType.DINING, RoomType.KITCHEN, RoomType.OPEN_KITCHEN_LIVING}
)
PRIVATE = frozenset({RoomType.BEDROOM, RoomType.STUDY})
WET = frozenset({RoomType.BATHROOM, RoomType.EN_SUITE, RoomType.WC, RoomType.LAUNDRY})
# Service rooms small enough to be "tucked" against the corridor inside a larger room's column.
TUCKABLE = frozenset(
    {
        RoomType.BATHROOM,
        RoomType.EN_SUITE,
        RoomType.WC,
        RoomType.LAUNDRY,
        RoomType.UTILITY,
        RoomType.STORAGE,
        RoomType.WALK_IN_CLOSET,
        RoomType.PLANT_ROOM,
    }
)
HABITABLE = PUBLIC | PRIVATE

_NAMES = {
    RoomType.BEDROOM: "Bedroom",
    RoomType.BATHROOM: "Bathroom",
    RoomType.EN_SUITE: "En-suite",
    RoomType.WC: "WC",
    RoomType.KITCHEN: "Kitchen",
    RoomType.LIVING: "Living room",
    RoomType.DINING: "Dining room",
    RoomType.OPEN_KITCHEN_LIVING: "Kitchen & living",
    RoomType.STUDY: "Study",
    RoomType.LAUNDRY: "Laundry",
    RoomType.UTILITY: "Utility room",
    RoomType.STORAGE: "Storage",
    RoomType.WALK_IN_CLOSET: "Walk-in closet",
    RoomType.PLANT_ROOM: "Plant room",
}


def zone_of(room_type: RoomType) -> Zone:
    if room_type in PUBLIC:
        return Zone.PUBLIC
    if room_type in PRIVATE:
        return Zone.PRIVATE
    return Zone.SERVICE


@dataclass
class RoomRequest:
    key: str  # instance key, unique; semantic key of the room = f"room:{key}"
    spec_key: str
    spec_index: int
    type: RoomType
    name: str
    target_area: float
    explicit_target: bool
    min_area: float
    min_width: float
    zone: Zone
    level: int | None  # fixed by the spec, else None
    serves: str | None = None  # en-suite / walk-in closet: instance key of its bedroom
    attached: list[str] = field(default_factory=list)  # keys of rooms reached through this one
    # Permissible range of an explicit target (building/intent.py) and whether it is a MUST.
    area_low: float | None = None
    area_high: float | None = None
    area_must: bool = False

    @property
    def tuckable(self) -> bool:
        return self.type in TUCKABLE


@dataclass
class Program:
    rooms: list[RoomRequest]
    adjacency: list[tuple[str, str]]  # spec-key pairs that should share a wall
    open_plan: list[tuple[str, str]]  # spec-key pairs that should be open to each other
    separate: list[tuple[str, str]] = field(default_factory=list)  # must not share a wall
    # (kind, a, b) of pairs marked MUST; kind is "adjacent" / "open" / "separate", a < b.
    must_pairs: frozenset[tuple[str, str, str]] = frozenset()

    def by_key(self) -> dict[str, RoomRequest]:
        return {r.key: r for r in self.rooms}

    def instances(self, spec_key: str) -> list[RoomRequest]:
        return [r for r in self.rooms if r.spec_key == spec_key]


def expand_program(
    spec: BuildingSpecification, profile: BuildingRulesProfile, config: LayoutConfig
) -> Program:
    rooms: list[RoomRequest] = []

    def request(
        key: str,
        spec_key: str,
        spec_index: int,
        room_type: RoomType,
        name: str,
        target: float | None,
        spec_min: float | None,
        level: int | None,
        serves: str | None = None,
    ) -> RoomRequest:
        rule = profile.room(room_type)
        min_area = max(rule.min_area_m2, spec_min or 0.0)
        area = target if target is not None else config.default_areas[room_type]
        return RoomRequest(
            key=key,
            spec_key=spec_key,
            spec_index=spec_index,
            type=room_type,
            name=name,
            target_area=max(area, min_area),
            explicit_target=target is not None,
            min_area=min_area,
            min_width=rule.min_width_m,
            zone=zone_of(room_type),
            level=level,
            serves=serves,
        )

    for i, req in enumerate(spec.rooms):
        room_type = RoomType(req.type.value)
        base_name = req.name or _NAMES[room_type]
        for n in range(req.count):
            key = req.key if req.count == 1 else f"{req.key}_{n + 1}"
            name = base_name if req.count == 1 else f"{base_name} {n + 1}"
            room = request(
                key, req.key, i, room_type, name, req.target_area_m2, req.min_area_m2, req.level
            )
            if req.target_area_m2 is not None:
                bounds = area_range(req)
                room.area_low = max(bounds.low, room.min_area)
                room.area_high = max(bounds.high, room.area_low)
                room.area_must = spec.priority_of(f"/rooms/{i}/target_area_m2") == "must"
            rooms.append(room)
            for feature in req.features:
                attached_type = (
                    RoomType.EN_SUITE
                    if feature == RoomFeature.EN_SUITE
                    else RoomType.WALK_IN_CLOSET
                )
                attached = request(
                    f"{key}_{feature.value}",
                    req.key,
                    i,
                    attached_type,
                    f"{_NAMES[attached_type]} ({name})",
                    None,
                    None,
                    req.level,
                    serves=key,
                )
                room.attached.append(attached.key)
                rooms.append(attached)

    adjacency = sorted({tuple(sorted((r.key, o))) for r in spec.rooms for o in r.adjacent_to})
    open_plan = sorted({tuple(sorted((r.key, o))) for r in spec.rooms for o in r.open_to})
    separate = sorted({tuple(sorted((r.key, o))) for r in spec.rooms for o in r.separate_from})
    must_pairs = frozenset(
        (req.kind, min(req.room, req.other), max(req.room, req.other))
        for req in requirements(spec)
        if req.mandatory and req.room is not None and req.other is not None
    )
    return Program(
        rooms=rooms,
        adjacency=[(a, b) for a, b in adjacency],
        open_plan=[(a, b) for a, b in open_plan],
        separate=[(a, b) for a, b in separate],
        must_pairs=must_pairs,
    )
