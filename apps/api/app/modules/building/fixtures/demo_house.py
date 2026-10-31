"""Hand-authored two-floor demo house (Phase 1 fixture).

Every wall, opening, room, slab, stair, roof, railing and furniture item is written out
explicitly below — this is NOT the layout engine. The script only derives what is mechanical:
UUIDs (uuid5 of the semantic key, so they are stable), wall lengths/angles, opening offsets,
areas, and relationships (bounds / adjacent_to / hosted_by / connects / located_in / supports).

Plan (meters, wall centerlines; x = east, y = north; street side = south):

    Floor 1 (12 x 10)                         Floor 2
    y=10 +-----------+---------+             +-----------+---------+  balcony y 10..11.6
         |  Living   | Dining  |             |  Master   |  Study  |
    y=6  +-----------+ - - - - +             +-----------+---------+
         | Corridor  |         |             |      Corridor       |
    y=4.8+----+--+---+ Kitchen |             +----+--+---+---------+
         |Ent.|St|Bath|        |             | Bd3|vd|Bath| Bed 2   |
         |    |ai|----+        |             |    |oi|    |         |
    y=0  +----+rs+Stor+--------+             +----+d-+----+---------+
         x=0 3.4 4.8 7.4      12

Regenerate data/fixtures/demo-house.model.json with:  pnpm fixtures
"""

import math
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.building.elements import (
    Door,
    DoorDimensions,
    DoorProperties,
    Element,
    Furniture,
    FurnitureDimensions,
    FurnitureProperties,
    Railing,
    RailingDimensions,
    RailingProperties,
    Relationship,
    Roof,
    RoofDimensions,
    RoofProperties,
    Room,
    RoomDimensions,
    RoomProperties,
    Slab,
    SlabDimensions,
    SlabProperties,
    Stair,
    StairDimensions,
    StairProperties,
    Wall,
    WallDimensions,
    WallProperties,
    Window,
    WindowDimensions,
    WindowProperties,
)
from app.modules.building.enums import (
    DoorKind,
    DoorSwing,
    FurnitureKind,
    Layer,
    Origin,
    RailingKind,
    RelationshipKind,
    RoofType,
    RoomType,
    SlabKind,
    StairType,
    WallKind,
    WindowKind,
    Zone,
)
from app.modules.building.geometry import Point, segment_overlap_length
from app.modules.building.model import (
    SCHEMA_VERSION,
    BuildingInfo,
    BuildingModel,
    Level,
    ModelMetadata,
)
from app.modules.building.primitives import EPS, Rotation, Vec2, Vec3

NAMESPACE = uuid.UUID("6f1c1a3e-2b1d-4c1e-9a55-7d3c0b1e2f40")

LEVEL_HEIGHT = 3.0
WALL_HEIGHT = 2.8  # up to the soffit of the slab above
EXT_T = 0.3
INT_T = 0.12
FLOOR_SLAB_T = 0.2
HALF_PI = math.pi / 2


def uid(key: str) -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, key)


def _no_rotation() -> Rotation:
    return Rotation(x=0, y=0, z=0)


@dataclass
class _WallSpec:
    key: str
    name: str
    level: str
    start: Point
    end: Point
    kind: WallKind
    material: str
    left: str
    right: str

    @property
    def length(self) -> float:
        return math.dist(self.start, self.end)

    @property
    def angle(self) -> float:
        return math.atan2(self.end[1] - self.start[1], self.end[0] - self.start[0])

    @property
    def thickness(self) -> float:
        return EXT_T if self.kind == WallKind.EXTERIOR else INT_T

    def offset_of(self, a: float, b: float) -> float:
        """Axis offset of the opening spanning plan coordinates a..b along the wall."""
        horizontal = abs(self.end[1] - self.start[1]) < EPS
        s = self.start[0] if horizontal else self.start[1]
        return min(abs(a - s), abs(b - s))

    def point_at(self, a: float, b: float) -> Point:
        mid = (a + b) / 2
        horizontal = abs(self.end[1] - self.start[1]) < EPS
        return (mid, self.start[1]) if horizontal else (self.start[0], mid)


@dataclass
class _RoomSpec:
    key: str
    name: str
    level: str
    rect: tuple[float, float, float, float]
    room_type: RoomType
    zone: Zone
    floor: str

    def edges(self) -> list[tuple[Point, Point]]:
        x0, y0, x1, y1 = self.rect
        pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return [(pts[i], pts[(i + 1) % 4]) for i in range(4)]

    def contains(self, p: Point) -> bool:
        x0, y0, x1, y1 = self.rect
        return x0 - EPS <= p[0] <= x1 + EPS and y0 - EPS <= p[1] <= y1 + EPS


@dataclass
class _Builder:
    levels: dict[str, Level] = field(default_factory=dict)
    walls: dict[str, _WallSpec] = field(default_factory=dict)
    rooms: dict[str, _RoomSpec] = field(default_factory=dict)
    elements: list[Element] = field(default_factory=list)
    supports: dict[str, list[str]] = field(default_factory=dict)  # wall key -> supported keys

    # --- authoring helpers --------------------------------------------------------------

    def level(self, key: str, name: str, index: int, elevation: float) -> None:
        self.levels[key] = Level(
            id=uid(f"level:{key}"),
            name=name,
            index=index,
            elevation=elevation,
            height=LEVEL_HEIGHT,
            semantic_key=f"level:{key}",
        )

    def room(
        self,
        key: str,
        name: str,
        level: str,
        rect: tuple[float, float, float, float],
        room_type: RoomType,
        zone: Zone,
        floor: str,
    ) -> None:
        self.rooms[key] = _RoomSpec(key, name, level, rect, room_type, zone, floor)

    def wall(
        self,
        key: str,
        name: str,
        level: str,
        start: Point,
        end: Point,
        kind: WallKind,
        material: str,
        left: str,
        right: str,
    ) -> None:
        self.walls[key] = _WallSpec(key, name, level, start, end, kind, material, left, right)

    def door(
        self,
        key: str,
        name: str,
        wall: str,
        span: tuple[float, float],
        size: tuple[float, float],
        kind: DoorKind,
        swing: DoorSwing,
        material: str = "wood",
    ) -> None:
        w = self.walls[wall]
        mid = w.point_at(*span)
        rooms = self._rooms_on_axis(w, mid)
        self.elements.append(
            Door(
                id=uid(f"door:{key}"),
                name=name,
                layer=Layer.ARCHITECTURE,
                level_id=self.levels[w.level].id,
                position=Vec3(x=w.offset_of(*span), y=0, z=0),
                rotation=_no_rotation(),
                material_id=material,
                relationships=[
                    Relationship(kind=RelationshipKind.HOSTED_BY, target_id=uid(f"wall:{wall}"))
                ]
                + [
                    Relationship(kind=RelationshipKind.CONNECTS, target_id=uid(f"room:{r}"))
                    for r in rooms
                ],
                origin=Origin.USER,
                semantic_key=f"door:{key}",
                dimensions=DoorDimensions(width=size[0], height=size[1], thickness=0.06),
                properties=DoorProperties(
                    door_kind=kind, swing=swing, frame_material_id="window_frame"
                ),
            )
        )

    def window(
        self,
        key: str,
        name: str,
        wall: str,
        span: tuple[float, float],
        sill: float,
        height: float,
        kind: WindowKind = WindowKind.CASEMENT,
        mullions: int = 0,
    ) -> None:
        w = self.walls[wall]
        self.elements.append(
            Window(
                id=uid(f"window:{key}"),
                name=name,
                layer=Layer.ARCHITECTURE,
                level_id=self.levels[w.level].id,
                position=Vec3(x=w.offset_of(*span), y=0, z=sill),
                rotation=_no_rotation(),
                material_id="glass",
                relationships=[
                    Relationship(kind=RelationshipKind.HOSTED_BY, target_id=uid(f"wall:{wall}"))
                ],
                origin=Origin.USER,
                semantic_key=f"window:{key}",
                dimensions=WindowDimensions(width=abs(span[1] - span[0]), height=height),
                properties=WindowProperties(
                    window_kind=kind, frame_material_id="window_frame", mullions=mullions
                ),
            )
        )

    def furniture(
        self,
        key: str,
        name: str,
        level: str,
        kind: FurnitureKind,
        at: Point,
        yaw: float,
        size: tuple[float, float, float],
        material: str,
    ) -> None:
        rooms = [r.key for r in self.rooms.values() if r.level == level and r.contains(at)]
        self.elements.append(
            Furniture(
                id=uid(f"furniture:{key}"),
                name=name,
                layer=Layer.FURNITURE,
                level_id=self.levels[level].id,
                position=Vec3(x=at[0], y=at[1], z=0),
                rotation=Rotation(x=0, y=0, z=yaw),
                material_id=material,
                relationships=[
                    Relationship(kind=RelationshipKind.LOCATED_IN, target_id=uid(f"room:{r}"))
                    for r in rooms[:1]
                ],
                origin=Origin.USER,
                semantic_key=f"furniture:{key}",
                dimensions=FurnitureDimensions(width=size[0], depth=size[1], height=size[2]),
                properties=FurnitureProperties(furniture_kind=kind, asset_id=None),
            )
        )

    def _rooms_on_axis(self, w: _WallSpec, p: Point) -> list[str]:
        """Rooms whose boundary edge lies on the wall axis at point p (for door `connects`)."""
        found = []
        for r in self.rooms.values():
            if r.level != w.level:
                continue
            for a, b in r.edges():
                if _point_on_segment(p, a, b):
                    found.append(r.key)
                    break
        return found

    # --- assembly -----------------------------------------------------------------------

    def build_rooms_and_walls(self) -> list[Element]:
        out: list[Element] = []
        for r in self.rooms.values():
            x0, y0, x1, y1 = r.rect
            width, depth = x1 - x0, y1 - y0
            adjacent = sorted(
                o.key
                for o in self.rooms.values()
                if o.key != r.key and o.level == r.level and _rooms_share_edge(r, o)
            )
            out.append(
                Room(
                    id=uid(f"room:{r.key}"),
                    name=r.name,
                    layer=Layer.ARCHITECTURE,
                    level_id=self.levels[r.level].id,
                    position=Vec3(x=x0, y=y0, z=0),
                    rotation=_no_rotation(),
                    material_id=r.floor,
                    relationships=[
                        Relationship(kind=RelationshipKind.ADJACENT_TO, target_id=uid(f"room:{k}"))
                        for k in adjacent
                    ],
                    origin=Origin.USER,
                    semantic_key=f"room:{r.key}",
                    dimensions=RoomDimensions(
                        area=width * depth,
                        perimeter=2 * (width + depth),
                        height=LEVEL_HEIGHT - FLOOR_SLAB_T,
                    ),
                    properties=RoomProperties(
                        room_type=r.room_type,
                        zone=r.zone,
                        floor_material_id=r.floor,
                        boundary=_rect(width, depth),
                    ),
                )
            )
        for w in self.walls.values():
            bounds = sorted(
                r.key
                for r in self.rooms.values()
                if r.level == w.level
                and any(segment_overlap_length((w.start, w.end), e) > EPS for e in r.edges())
            )
            rels = [
                Relationship(kind=RelationshipKind.BOUNDS, target_id=uid(f"room:{k}"))
                for k in bounds
            ]
            rels += [
                Relationship(kind=RelationshipKind.SUPPORTS, target_id=uid(s))
                for s in self.supports.get(w.key, [])
            ]
            exterior = w.kind == WallKind.EXTERIOR
            out.append(
                Wall(
                    id=uid(f"wall:{w.key}"),
                    name=w.name,
                    layer=Layer.STRUCTURE if exterior else Layer.ARCHITECTURE,
                    level_id=self.levels[w.level].id,
                    position=Vec3(x=w.start[0], y=w.start[1], z=0),
                    rotation=Rotation(x=0, y=0, z=w.angle),
                    material_id=w.material,
                    relationships=rels,
                    origin=Origin.USER,
                    semantic_key=f"wall:{w.key}",
                    dimensions=WallDimensions(
                        length=w.length, thickness=w.thickness, height=WALL_HEIGHT
                    ),
                    properties=WallProperties(
                        wall_kind=w.kind,
                        load_bearing=exterior,
                        finish_left_id=w.left,
                        finish_right_id=w.right,
                    ),
                )
            )
        return out


def _point_on_segment(p: Point, a: Point, b: Point) -> bool:
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    if abs(cross) > EPS:
        return False
    return (
        min(a[0], b[0]) - EPS <= p[0] <= max(a[0], b[0]) + EPS
        and min(a[1], b[1]) - EPS <= p[1] <= max(a[1], b[1]) + EPS
    )


def _rooms_share_edge(a: _RoomSpec, b: _RoomSpec) -> bool:
    return any(segment_overlap_length(ea, eb) > EPS for ea in a.edges() for eb in b.edges())


def _rect(w: float, d: float) -> list[Vec2]:
    return [Vec2(x=0, y=0), Vec2(x=w, y=0), Vec2(x=w, y=d), Vec2(x=0, y=d)]


def build_demo_house() -> BuildingModel:
    b = _Builder()
    b.level("L0", "Floor 1", 0, 0.0)
    b.level("L1", "Floor 2", 1, LEVEL_HEIGHT)

    # --- Rooms -----------------------------------------------------------------------------
    P, S, C, E = Zone.PUBLIC, Zone.SERVICE, Zone.CIRCULATION, Zone.EXTERIOR
    b.room("entrance", "Entrance", "L0", (0, 0, 3.4, 4.8), RoomType.ENTRANCE, C, "floor")
    b.room("staircase", "Staircase", "L0", (3.4, 0, 4.8, 4.8), RoomType.STAIRCASE, C, "floor")
    b.room("storage", "Storage", "L0", (4.8, 0, 7.4, 2.4), RoomType.STORAGE, S, "floor")
    b.room("bath_g", "Bathroom", "L0", (4.8, 2.4, 7.4, 4.8), RoomType.BATHROOM, S, "tile")
    b.room("kitchen", "Kitchen", "L0", (7.4, 0, 12, 6), RoomType.KITCHEN, S, "floor")
    b.room("corridor_g", "Corridor", "L0", (0, 4.8, 7.4, 6), RoomType.CORRIDOR, C, "parquet")
    b.room("living", "Living room", "L0", (0, 6, 7.4, 10), RoomType.LIVING, P, "parquet")
    b.room("dining", "Dining area", "L0", (7.4, 6, 12, 10), RoomType.DINING, P, "parquet")

    Q = Zone.PRIVATE
    b.room("bedroom3", "Bedroom 3", "L1", (0, 0, 3.4, 4.8), RoomType.BEDROOM, Q, "parquet")
    b.room("bath_f", "Bathroom", "L1", (4.8, 0, 7.4, 4.8), RoomType.BATHROOM, S, "tile")
    b.room("bedroom2", "Bedroom 2", "L1", (7.4, 0, 12, 4.8), RoomType.BEDROOM, Q, "parquet")
    b.room("corridor_f", "Corridor", "L1", (0, 4.8, 12, 6), RoomType.CORRIDOR, C, "parquet")
    b.room("master", "Master bedroom", "L1", (0, 6, 7.4, 10), RoomType.BEDROOM, Q, "parquet")
    b.room("study", "Study", "L1", (7.4, 6, 12, 10), RoomType.STUDY, Q, "parquet")
    b.room("balcony", "Balcony", "L1", (0.6, 10, 6.6, 11.6), RoomType.BALCONY, E, "decking")

    # --- Walls (exterior loops are counter-clockwise: left face = interior) -----------------
    for lvl, tag, facade in (("L0", "G", "brick"), ("L1", "F", "exterior_wall")):
        corners = [(0.0, 0.0), (12.0, 0.0), (12.0, 10.0), (0.0, 10.0)]
        for i, side in enumerate("SENW"):
            b.wall(
                f"{tag}-{side}",
                f"W-{tag}{i + 1:02d}",
                lvl,
                corners[i],
                corners[(i + 1) % 4],
                WallKind.EXTERIOR,
                facade,
                "interior_wall",
                facade,
            )

    iw, tile = "interior_wall", "tile"
    INT = WallKind.INTERIOR
    b.wall("G-I1", "W-G05", "L0", (0, 4.8), (3.4, 4.8), INT, iw, iw, iw)
    b.wall("G-I2", "W-G06", "L0", (4.8, 0), (4.8, 4.8), INT, iw, iw, iw)
    b.wall("G-I3", "W-G07", "L0", (4.8, 4.8), (7.4, 4.8), INT, iw, iw, tile)
    b.wall("G-I4", "W-G08", "L0", (4.8, 2.4), (7.4, 2.4), INT, iw, tile, iw)
    b.wall("G-I5", "W-G09", "L0", (7.4, 0), (7.4, 6.0), INT, iw, iw, iw)
    b.wall("G-I6", "W-G10", "L0", (0, 6.0), (7.4, 6.0), INT, iw, iw, iw)

    b.wall("F-I1", "W-F05", "L1", (3.4, 0), (3.4, 4.8), INT, iw, iw, iw)
    b.wall("F-I2", "W-F06", "L1", (4.8, 0), (4.8, 4.8), INT, iw, iw, tile)
    b.wall("F-I3", "W-F07", "L1", (0, 4.8), (3.4, 4.8), INT, iw, iw, iw)
    b.wall("F-I4", "W-F08", "L1", (4.8, 4.8), (12, 4.8), INT, iw, iw, iw)
    b.wall("F-I5", "W-F09", "L1", (7.4, 0), (7.4, 4.8), INT, iw, tile, iw)
    b.wall("F-I6", "W-F10", "L1", (0, 6.0), (12, 6.0), INT, iw, iw, iw)
    b.wall("F-I7", "W-F11", "L1", (7.4, 6.0), (7.4, 10), INT, iw, iw, iw)

    for side in "SENW":  # load path: ground facades carry the floor slab, upper ones the roof
        b.supports[f"G-{side}"] = ["slab:floor_f"]
        b.supports[f"F-{side}"] = ["roof:main"]

    # --- Doors -----------------------------------------------------------------------------
    D, SW = DoorKind, DoorSwing
    b.door("front", "Front door", "G-S", (1.2, 2.2), (1.0, 2.2), D.ENTRANCE, SW.LEFT, "wood_dark")
    b.door("ent_corr", "Door D-G02", "G-I1", (1.2, 2.1), (0.9, 2.1), D.INTERIOR, SW.RIGHT)
    b.door("bath_g", "Door D-G03", "G-I3", (5.3, 6.1), (0.8, 2.1), D.INTERIOR, SW.LEFT)
    b.door("storage", "Door D-G04", "G-I5", (0.8, 1.6), (0.8, 2.1), D.INTERIOR, SW.RIGHT)
    b.door("kitchen", "Door D-G05", "G-I5", (5.0, 5.9), (0.9, 2.1), D.INTERIOR, SW.LEFT)
    b.door("living", "Door D-G06", "G-I6", (2.8, 4.4), (1.6, 2.1), D.INTERIOR, SW.DOUBLE)
    b.door("garden", "Garden door", "G-N", (1.5, 4.0), (2.5, 2.4), D.SLIDING, SW.SLIDING, "glass")

    b.door("bedroom3", "Door D-F01", "F-I3", (1.2, 2.1), (0.9, 2.1), D.INTERIOR, SW.RIGHT)
    b.door("bath_f", "Door D-F02", "F-I4", (5.3, 6.1), (0.8, 2.1), D.INTERIOR, SW.LEFT)
    b.door("bedroom2", "Door D-F03", "F-I4", (8.2, 9.1), (0.9, 2.1), D.INTERIOR, SW.RIGHT)
    b.door("master", "Door D-F04", "F-I6", (5.4, 6.3), (0.9, 2.1), D.INTERIOR, SW.LEFT)
    b.door("study", "Door D-F05", "F-I6", (8.2, 9.1), (0.9, 2.1), D.INTERIOR, SW.RIGHT)
    b.door("balcony", "Balcony door", "F-N", (2.2, 4.6), (2.4, 2.4), D.SLIDING, SW.SLIDING, "glass")

    # --- Windows ---------------------------------------------------------------------------
    PAN, FIX = WindowKind.PANORAMIC, WindowKind.FIXED
    b.window("ent", "Window WN-G01", "G-S", (0.3, 0.9), 0.9, 1.3)
    b.window("stair_g", "Window WN-G02", "G-S", (3.6, 4.6), 1.2, 1.0, FIX)
    b.window("storage", "Window WN-G03", "G-S", (5.7, 6.5), 1.6, 0.6, FIX)
    b.window("kitchen_s", "Window WN-G04", "G-S", (8.2, 11.2), 0.95, 1.3, mullions=2)
    b.window("kitchen_e", "Window WN-G05", "G-E", (1.0, 2.8), 1.1, 1.1, mullions=1)
    b.window("dining_e", "Window WN-G06", "G-E", (6.8, 9.0), 0.6, 1.8, mullions=1)
    b.window("dining_n", "Window WN-G07", "G-N", (8.0, 11.2), 0.1, 2.4, PAN, mullions=2)
    b.window("living_n", "Window WN-G08", "G-N", (4.6, 6.8), 0.1, 2.4, PAN, mullions=1)
    b.window("living_w", "Window WN-G09", "G-W", (6.8, 9.2), 0.6, 1.8, mullions=1)

    b.window("bed3_s", "Window WN-F01", "F-S", (0.9, 2.5), 0.9, 1.4, mullions=1)
    b.window("bed3_w", "Window WN-F02", "F-W", (1.4, 3.0), 0.9, 1.4)
    b.window("stair_f", "Window WN-F03", "F-S", (3.6, 4.6), 1.0, 1.2, FIX)
    b.window("bath_f", "Window WN-F04", "F-S", (5.5, 6.7), 1.3, 0.9)
    b.window("bed2_s", "Window WN-F05", "F-S", (8.4, 11.0), 0.9, 1.4, mullions=1)
    b.window("bed2_e", "Window WN-F06", "F-E", (1.4, 3.4), 0.9, 1.4, mullions=1)
    b.window("corr_e", "Window WN-F07", "F-E", (5.0, 5.8), 1.0, 1.2, FIX)
    b.window("corr_w", "Window WN-F08", "F-W", (5.0, 5.8), 1.0, 1.2, FIX)
    b.window("master_n", "Window WN-F09", "F-N", (5.0, 6.8), 0.9, 1.4, mullions=1)
    b.window("master_w", "Window WN-F10", "F-W", (8.4, 9.6), 0.9, 1.4)
    b.window("study_n", "Window WN-F11", "F-N", (8.4, 11.0), 0.9, 1.4, mullions=1)
    b.window("study_e", "Window WN-F12", "F-E", (6.8, 8.8), 0.9, 1.4, mullions=1)

    # --- Furniture (base center, yaw; the front of each piece faces local -y) ----------------
    F = FurnitureKind
    fur = b.furniture
    fur("sofa", "Sofa", "L0", F.SOFA, (2.4, 6.75), math.pi, (2.4, 0.95, 0.8), "fabric")
    fur("coffee", "Coffee table", "L0", F.COFFEE_TABLE, (2.4, 8.0), 0, (1.2, 0.6, 0.4), "wood")
    fur("armchair", "Armchair", "L0", F.ARMCHAIR, (4.5, 8.0), -HALF_PI, (0.85, 0.85, 0.8), "fabric")
    fur("tv", "TV unit", "L0", F.TV_UNIT, (0.4, 8.0), HALF_PI, (1.8, 0.45, 0.5), "wood_dark")
    fur("dtable", "Dining table", "L0", F.DINING_TABLE, (9.7, 8.0), 0, (2.0, 1.0, 0.75), "wood")
    for i, x in enumerate((9.05, 9.7, 10.35)):
        fur(
            f"chair_s{i}",
            f"Chair {i + 1}",
            "L0",
            F.CHAIR,
            (x, 7.25),
            math.pi,
            (0.45, 0.5, 0.9),
            "wood",
        )
        fur(f"chair_n{i}", f"Chair {i + 4}", "L0", F.CHAIR, (x, 8.75), 0, (0.45, 0.5, 0.9), "wood")
    fur(
        "counter",
        "Kitchen counter",
        "L0",
        F.KITCHEN_COUNTER,
        (11.55, 2.4),
        -HALF_PI,
        (3.6, 0.6, 0.9),
        "countertop",
    )
    fur("fridge", "Fridge", "L0", F.FRIDGE, (11.5, 4.7), -HALF_PI, (0.7, 0.7, 1.9), "metal")
    fur(
        "island",
        "Kitchen island",
        "L0",
        F.KITCHEN_ISLAND,
        (9.4, 2.6),
        HALF_PI,
        (2.0, 0.9, 0.9),
        "countertop",
    )
    fur("toilet_g", "Toilet", "L0", F.TOILET, (5.2, 3.1), HALF_PI, (0.4, 0.65, 0.8), "ceramic")
    fur("basin_g", "Basin", "L0", F.BASIN, (6.4, 2.72), math.pi, (0.8, 0.5, 0.85), "ceramic")
    fur("shower_g", "Shower", "L0", F.SHOWER, (6.85, 3.95), 0, (0.9, 0.9, 2.0), "glass")
    fur("coat", "Coat wardrobe", "L0", F.WARDROBE, (0.45, 2.8), HALF_PI, (1.2, 0.6, 2.0), "wood")

    fur("bed_m", "Double bed", "L1", F.BED, (2.8, 7.11), math.pi, (1.8, 2.1, 0.5), "fabric_light")
    fur("ns_m1", "Nightstand 1", "L1", F.NIGHTSTAND, (1.55, 6.3), math.pi, (0.5, 0.4, 0.5), "wood")
    fur("ns_m2", "Nightstand 2", "L1", F.NIGHTSTAND, (4.05, 6.3), math.pi, (0.5, 0.4, 0.5), "wood")
    fur("wardrobe_m", "Wardrobe", "L1", F.WARDROBE, (7.04, 8.2), -HALF_PI, (2.0, 0.6, 2.2), "wood")
    fur("bed_2", "Bed", "L1", F.BED, (10.85, 2.6), -HALF_PI, (1.6, 2.0, 0.5), "fabric_light")
    fur("desk_2", "Desk", "L1", F.DESK, (7.76, 3.6), HALF_PI, (1.2, 0.6, 0.75), "wood")
    fur("wardrobe_2", "Wardrobe", "L1", F.WARDROBE, (10.8, 4.44), 0, (1.6, 0.6, 2.2), "wood")
    fur("bed_3", "Bed", "L1", F.BED, (2.34, 2.8), -HALF_PI, (1.4, 2.0, 0.5), "fabric_light")
    fur("desk_3", "Desk", "L1", F.DESK, (0.45, 2.2), HALF_PI, (1.2, 0.6, 0.75), "wood")
    fur("tub", "Bathtub", "L1", F.BATHTUB, (6.1, 0.525), math.pi, (1.7, 0.75, 0.55), "ceramic")
    fur("toilet_f", "Toilet", "L1", F.TOILET, (5.2, 2.2), HALF_PI, (0.4, 0.65, 0.8), "ceramic")
    fur("basin_f", "Basin", "L1", F.BASIN, (7.09, 2.6), -HALF_PI, (0.8, 0.5, 0.85), "ceramic")
    fur("shower_f", "Shower", "L1", F.SHOWER, (6.85, 4.2), 0, (0.9, 0.9, 2.0), "glass")
    fur("desk_s", "Desk", "L1", F.DESK, (9.7, 9.5), 0, (1.4, 0.7, 0.75), "wood")
    fur("chair_s", "Desk chair", "L1", F.CHAIR, (9.7, 8.95), math.pi, (0.45, 0.5, 0.9), "fabric")
    fur("shelf_s", "Bookshelf", "L1", F.BOOKSHELF, (7.66, 8.6), HALF_PI, (1.6, 0.4, 2.0), "wood")
    fur("btable", "Balcony table", "L1", F.COFFEE_TABLE, (3.6, 10.9), 0, (0.7, 0.7, 0.45), "wood")
    fur(
        "bchair1",
        "Balcony chair 1",
        "L1",
        F.CHAIR,
        (2.9, 10.9),
        -HALF_PI,
        (0.45, 0.5, 0.9),
        "metal",
    )
    fur(
        "bchair2", "Balcony chair 2", "L1", F.CHAIR, (4.3, 10.9), HALF_PI, (0.45, 0.5, 0.9), "metal"
    )

    L0, L1 = b.levels["L0"].id, b.levels["L1"].id
    elements: list[Element] = [*b.build_rooms_and_walls(), *b.elements]

    # --- Slabs -----------------------------------------------------------------------------
    def slab(
        key: str,
        name: str,
        level: uuid.UUID,
        origin: Point,
        size: Point,
        t: float,
        kind: SlabKind,
        holes: list[list[Vec2]],
    ) -> Slab:
        hole_area = sum(
            (max(p.x for p in h) - min(p.x for p in h))
            * (max(p.y for p in h) - min(p.y for p in h))
            for h in holes
        )
        return Slab(
            id=uid(f"slab:{key}"),
            name=name,
            layer=Layer.STRUCTURE,
            level_id=level,
            position=Vec3(x=origin[0], y=origin[1], z=0),
            rotation=_no_rotation(),
            material_id="concrete",
            relationships=[],
            origin=Origin.USER,
            semantic_key=f"slab:{key}",
            dimensions=SlabDimensions(thickness=t, area=size[0] * size[1] - hole_area),
            properties=SlabProperties(slab_kind=kind, outline=_rect(*size), holes=holes),
        )

    half = EXT_T / 2
    footprint = (12 + EXT_T, 10 + EXT_T)
    # Stair void: between the inner faces of walls F-I1/F-I2, from the south wall's inner face
    # to the corridor edge (relative to the slab origin at -half, -half).
    hx0, hx1 = 3.4 + INT_T / 2 + half, 4.8 - INT_T / 2 + half
    hy0, hy1 = half + half, 4.8 + half
    void = [Vec2(x=hx0, y=hy0), Vec2(x=hx1, y=hy0), Vec2(x=hx1, y=hy1), Vec2(x=hx0, y=hy1)]
    elements += [
        slab("ground", "Ground slab", L0, (-half, -half), footprint, 0.3, SlabKind.GROUND, []),
        slab(
            "floor_f",
            "Floor 2 slab",
            L1,
            (-half, -half),
            footprint,
            FLOOR_SLAB_T,
            SlabKind.FLOOR,
            [void],
        ),
        slab(
            "balcony",
            "Balcony slab",
            L1,
            (0.6, 10 + half),
            (6.0, 1.6 - half),
            FLOOR_SLAB_T,
            SlabKind.BALCONY,
            [],
        ),
    ]

    # --- Stair: 16 risers x 187.5 mm, 15 treads x 260 mm, rising north from y=0.9 -----------
    risers, riser_h, tread = 16, LEVEL_HEIGHT / 16, 0.26
    elements.append(
        Stair(
            id=uid("stair:main"),
            name="Main stair",
            layer=Layer.STRUCTURE,
            level_id=L0,
            position=Vec3(x=4.65, y=0.9, z=0),
            rotation=Rotation(x=0, y=0, z=HALF_PI),
            material_id="wood",
            relationships=[
                Relationship(kind=RelationshipKind.LOCATED_IN, target_id=uid("room:staircase"))
            ],
            origin=Origin.USER,
            semantic_key="stair:main",
            dimensions=StairDimensions(
                width=1.1, run_length=(risers - 1) * tread, rise_total=LEVEL_HEIGHT
            ),
            properties=StairProperties(
                stair_type=StairType.STRAIGHT,
                risers=risers,
                riser_height=riser_h,
                tread_depth=tread,
                from_level_id=L0,
                to_level_id=L1,
            ),
        )
    )

    # --- Railings --------------------------------------------------------------------------
    def railing(
        key: str,
        name: str,
        level: uuid.UUID,
        start: tuple[float, float, float],
        yaw: float,
        length: float,
        height: float,
        rise: float,
        kind: RailingKind,
        room: str,
    ) -> Railing:
        return Railing(
            id=uid(f"railing:{key}"),
            name=name,
            layer=Layer.ARCHITECTURE,
            level_id=level,
            position=Vec3(x=start[0], y=start[1], z=start[2]),
            rotation=Rotation(x=0, y=0, z=yaw),
            material_id="metal",
            relationships=[
                Relationship(kind=RelationshipKind.LOCATED_IN, target_id=uid(f"room:{room}"))
            ],
            origin=Origin.USER,
            semantic_key=f"railing:{key}",
            dimensions=RailingDimensions(length=length, height=height),
            properties=RailingProperties(railing_kind=kind, rise=rise, post_spacing=1.0),
        )

    run = (risers - 1) * tread
    by = 11.55
    elements += [
        railing(
            "stair",
            "Stair railing",
            L0,
            (3.58, 0.9, riser_h),
            HALF_PI,
            run,
            0.9,
            LEVEL_HEIGHT - riser_h,
            RailingKind.BARS,
            "staircase",
        ),
        railing(
            "balcony_w",
            "Balcony railing W",
            L1,
            (0.65, 10 + half, 0),
            HALF_PI,
            by - 10 - half,
            1.1,
            0,
            RailingKind.GLASS,
            "balcony",
        ),
        railing(
            "balcony_n",
            "Balcony railing N",
            L1,
            (0.65, by, 0),
            0,
            5.9,
            1.1,
            0,
            RailingKind.GLASS,
            "balcony",
        ),
        railing(
            "balcony_e",
            "Balcony railing E",
            L1,
            (6.55, by, 0),
            -HALF_PI,
            by - 10 - half,
            1.1,
            0,
            RailingKind.GLASS,
            "balcony",
        ),
    ]

    # --- Roof: hip roof over floor 2; underside meets the wall tops at the outer face --------
    overhang, pitch, roof_t = 0.5, 25.0, 0.2
    eave_z = WALL_HEIGHT - overhang * math.tan(math.radians(pitch)) + roof_t
    size = (12 + EXT_T + 2 * overhang, 10 + EXT_T + 2 * overhang)
    elements.append(
        Roof(
            id=uid("roof:main"),
            name="Roof",
            layer=Layer.ARCHITECTURE,
            level_id=L1,
            position=Vec3(x=-half - overhang, y=-half - overhang, z=eave_z),
            rotation=_no_rotation(),
            material_id="roof",
            relationships=[],
            origin=Origin.USER,
            semantic_key="roof:main",
            dimensions=RoofDimensions(thickness=roof_t, overhang=overhang),
            properties=RoofProperties(
                roof_type=RoofType.HIP,
                outline=_rect(*size),
                pitch_deg=pitch,
                ridge_axis="x",
                parapet_height=0,
            ),
        )
    )

    return BuildingModel(
        schema_version=SCHEMA_VERSION,
        id=uid("model:demo-house"),
        building=BuildingInfo(
            name="Demo family house",
            building_type="single_family_house",
            description=(
                "Hand-authored two-floor family house (12 x 10 m, ~240 m2) used to prove the "
                "BuildingModel -> procedural 3D pipeline. Not produced by the layout engine."
            ),
        ),
        units="m",
        engine_version="fixture@1",
        seed=None,
        levels=list(b.levels.values()),
        elements=elements,
        metadata=ModelMetadata(
            source="fixture", generator="app.modules.building.fixtures.demo_house"
        ),
    )


def demo_house_json() -> str:
    return build_demo_house().model_dump_json(indent=2) + "\n"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.modules.building.fixtures.demo_house <out.json>")
    Path(sys.argv[1]).write_text(demo_house_json(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
