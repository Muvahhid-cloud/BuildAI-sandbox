"""Basic furniture per room type (placeholders the viewer draws procedurally).

Each room gets a small template laid out in a room-local frame: u runs along the room's width
(plan x), v runs from the corridor side (v = 0, where the door usually is) to the far side
(the facade for band rooms). Items that would leave the room, overlap another item or block a
door's clearance zone are skipped, so furniture never makes a model invalid.
"""

import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.modules.building.elements import (
    Element,
    Furniture,
    FurnitureDimensions,
    FurnitureProperties,
    Relationship,
    Room,
)
from app.modules.building.enums import FurnitureKind, Layer, Origin, RelationshipKind, RoomType
from app.modules.building.geometry import Point
from app.modules.building.model import Level
from app.modules.building.primitives import Rotation, Vec3
from app.modules.layout.plan import Rect, Region, rnd
from app.modules.layout.regions import PlanLayout

INSET = 0.15  # from the wall centerline
DOOR_CLEARANCE = 1.0
Facing = Literal["+u", "-u", "+v", "-v"]
F = FurnitureKind


@dataclass
class _Room:
    region: Region
    room: Room
    rect: Rect
    corridor_high: bool  # corridor (v = 0) is at the rect's high y
    doors: list[Rect]
    placed: list[Rect] = field(default_factory=list)
    items: list[Furniture] = field(default_factory=list)

    @property
    def W(self) -> float:  # noqa: N802
        return self.rect.w

    @property
    def D(self) -> float:  # noqa: N802
        return self.rect.h

    def world(self, u: float, v: float) -> Point:
        y = self.rect.y1 - v if self.corridor_high else self.rect.y0 + v
        return (self.rect.x0 + u, y)

    def direction(self, facing: Facing) -> Point:
        sign_v = -1.0 if self.corridor_high else 1.0
        return {
            "+u": (1.0, 0.0),
            "-u": (-1.0, 0.0),
            "+v": (0.0, sign_v),
            "-v": (0.0, -sign_v),
        }[facing]


def _footprint(center: Point, size: tuple[float, float], facing_world: Point) -> Rect:
    w, d = size
    along_x = abs(facing_world[1]) > 0.5  # front faces +-y: width runs along x
    hx, hy = (w / 2, d / 2) if along_x else (d / 2, w / 2)
    return Rect(center[0] - hx, center[1] - hy, center[0] + hx, center[1] + hy)


def _overlap(a: Rect, b: Rect, tol: float = 0.01) -> bool:
    return a.x0 < b.x1 - tol and b.x0 < a.x1 - tol and a.y0 < b.y1 - tol and b.y0 < a.y1 - tol


class _Placer:
    def __init__(
        self, level: Level, ids: Callable[[str], uuid.UUID], counters: dict[str, int]
    ) -> None:
        self.level = level
        self.ids = ids
        self.counters = counters

    def put(
        self,
        room: _Room,
        name: str,
        kind: FurnitureKind,
        u: float,
        v: float,
        facing: Facing,
        size: tuple[float, float, float],
        material: str,
        *,
        near_ok: bool = False,
    ) -> bool:
        center = room.world(u, v)
        direction = room.direction(facing)
        fp = _footprint(center, (size[0], size[1]), direction)
        inner = Rect(
            room.rect.x0 + INSET, room.rect.y0 + INSET, room.rect.x1 - INSET, room.rect.y1 - INSET
        )
        if fp.x0 < inner.x0 - 1e-6 or fp.x1 > inner.x1 + 1e-6:
            return False
        if fp.y0 < inner.y0 - 1e-6 or fp.y1 > inner.y1 + 1e-6:
            return False
        if any(_overlap(fp, d) for d in room.doors):
            return False
        if not near_ok and any(_overlap(fp, p) for p in room.placed):
            return False
        room.placed.append(fp)
        slug = f"furniture:{room.region.key}:{kind.value}"
        self.counters[slug] = self.counters.get(slug, 0) + 1
        key = f"{slug}:{self.counters[slug]}"
        yaw = math.atan2(direction[0], -direction[1])
        room.items.append(
            Furniture(
                id=self.ids(key),
                name=name,
                layer=Layer.FURNITURE,
                level_id=self.level.id,
                position=Vec3(x=rnd(center[0]), y=rnd(center[1]), z=0),
                rotation=Rotation(z=yaw),
                material_id=material,
                relationships=[
                    Relationship(kind=RelationshipKind.LOCATED_IN, target_id=room.room.id)
                ],
                origin=Origin.GENERATED,
                semantic_key=key,
                dimensions=FurnitureDimensions(width=size[0], depth=size[1], height=size[2]),
                properties=FurnitureProperties(furniture_kind=kind, asset_id=None),
            )
        )
        return True


def _door_side(room: _Room) -> float:
    """u of the nearest door on the corridor side (for "keep tall things away")."""
    us = []
    for d in room.doors:
        cx = (d.x0 + d.x1) / 2
        us.append(cx - room.rect.x0)
    return us[0] if us else 0.0


def _bedroom(p: _Placer, r: _Room) -> None:
    bed_w = 1.8 if min(r.W, r.D) >= 3.4 else 1.6 if min(r.W, r.D) >= 3.0 else 1.4
    m = INSET
    # Headboard against the far wall (centred, then shifted), else against a side wall; the
    # first position clear of every door zone (e.g. a balcony door on the facade) wins.
    options: list[tuple[float, float, Facing, list[tuple[float, float]]]] = []
    far = r.D - m - 0.2
    for u in (r.W / 2, m + bed_w / 2 + 0.6, r.W - m - bed_w / 2 - 0.6):
        stands = [(u - bed_w / 2 - 0.3, far), (u + bed_w / 2 + 0.3, far)]
        options.append((u, r.D - m - 1.0, "-v", stands))
    v = r.D / 2 + 0.3
    for facing, u, su in (("+u", m + 1.0, m + 0.2), ("-u", r.W - m - 1.0, r.W - m - 0.2)):
        stands = [(su, v - bed_w / 2 - 0.3), (su, v + bed_w / 2 + 0.3)]
        options.append((u, v, facing, stands))  # type: ignore[arg-type]
    for u, bv, facing, stands in options:
        if p.put(r, "Bed", F.BED, u, bv, facing, (bed_w, 2.0, 0.5), "fabric_light"):
            for i, (su, sv) in enumerate(stands):
                p.put(
                    r, f"Nightstand {i + 1}", F.NIGHTSTAND, su, sv, facing, (0.5, 0.4, 0.5), "wood"
                )
            break
    else:
        return
    door_u = _door_side(r)
    width = min(2.0, r.W - 2 * m - 1.2)
    if width >= 1.0:
        u = (r.W - m - width / 2) if door_u < r.W / 2 else (m + width / 2)
        p.put(r, "Wardrobe", F.WARDROBE, u, m + 0.3, "+v", (round(width, 2), 0.6, 2.2), "wood")


def _living(p: _Placer, r: _Room, u0: float = 0.0, width: float | None = None) -> None:
    m = INSET
    w = r.W - u0 if width is None else width
    if w >= 3.4:
        p.put(r, "TV unit", F.TV_UNIT, u0 + m + 0.25, r.D / 2, "+u", (1.8, 0.45, 0.5), "wood_dark")
        su = u0 + min(w - m - 0.5, m + 3.3)
        p.put(r, "Sofa", F.SOFA, su, r.D / 2, "-u", (2.4, 0.95, 0.8), "fabric")
        p.put(
            r,
            "Coffee table",
            F.COFFEE_TABLE,
            (u0 + m + 0.5 + su - 0.5) / 2,
            r.D / 2,
            "+u",
            (1.2, 0.6, 0.4),
            "wood",
        )
        p.put(
            r,
            "Armchair",
            F.ARMCHAIR,
            (u0 + m + 0.5 + su) / 2,
            r.D - m - 0.6,
            "-v",
            (0.85, 0.85, 0.8),
            "fabric",
        )
    else:
        p.put(r, "TV unit", F.TV_UNIT, u0 + w / 2, m + 1.2, "+v", (1.6, 0.45, 0.5), "wood_dark")
        p.put(r, "Sofa", F.SOFA, u0 + w / 2, r.D - m - 0.6, "-v", (2.2, 0.95, 0.8), "fabric")


def _dining(p: _Placer, r: _Room, u0: float = 0.0, width: float | None = None) -> None:
    w = r.W - u0 if width is None else width
    long_u = w >= r.D
    big = min(w, r.D) >= 3.0 and max(w, r.D) >= 3.4
    tl, tw = (2.0, 1.0) if big else (1.4, 0.9)
    cu, cv = u0 + w / 2, r.D / 2
    facing: Facing = "+v" if long_u else "+u"
    if not p.put(r, "Dining table", F.DINING_TABLE, cu, cv, facing, (tl, tw, 0.75), "wood"):
        return
    offsets = (-0.65, 0.0, 0.65) if big else (-0.35, 0.35)
    n = 0
    for side in (-1, 1):
        for off in offsets:
            n += 1
            if long_u:
                u, v = cu + off, cv + side * (tw / 2 + 0.2)
                face: Facing = "-v" if side > 0 else "+v"
            else:
                u, v = cu + side * (tw / 2 + 0.2), cv + off
                face = "-u" if side > 0 else "+u"
            p.put(r, f"Chair {n}", F.CHAIR, u, v, face, (0.45, 0.45, 0.9), "wood", near_ok=True)


def _kitchen(p: _Placer, r: _Room, u0: float = 0.0, width: float | None = None) -> None:
    m = INSET
    w = r.W - u0 if width is None else width
    door_u = _door_side(r)
    west = door_u - u0 > w / 2  # counter on the side away from the door
    u_wall = u0 + m + 0.3 if west else u0 + w - m - 0.3
    face: Facing = "+u" if west else "-u"
    p.put(
        r,
        "Fridge",
        F.FRIDGE,
        u_wall + (0.05 if west else -0.05),
        r.D - m - 0.35,
        face,
        (0.7, 0.7, 1.9),
        "metal",
    )
    length = min(3.6, r.D - 2 * m - 0.8 - 1.0)
    if length >= 1.2:
        p.put(
            r,
            "Kitchen counter",
            F.KITCHEN_COUNTER,
            u_wall,
            r.D - m - 0.75 - length / 2,
            face,
            (round(length, 2), 0.6, 0.9),
            "countertop",
        )
    if w >= 3.8 and r.D >= 4.0:
        iu = u0 + (m + 0.6 + 1.1 if west else w - m - 0.6 - 1.1)
        p.put(
            r,
            "Kitchen island",
            F.KITCHEN_ISLAND,
            iu,
            r.D / 2 + 0.3,
            face,
            (1.8, 0.9, 0.9),
            "countertop",
        )


def _open_kitchen_living(p: _Placer, r: _Room) -> None:
    kw = min(3.8, r.W * 0.45)
    _kitchen(p, r, 0.0, kw)
    _living(p, r, kw, r.W - kw)


def _bathroom(p: _Placer, r: _Room, wc_only: bool = False) -> None:
    m = INSET
    back = r.D - m
    along_u = r.W >= r.D or r.W >= 1.9
    items: list[tuple[str, FurnitureKind, tuple[float, float, float], str]] = []
    if not wc_only:
        tub = r.W * r.D >= 5.5 and max(r.W, r.D) >= 2.4
        items.append(
            ("Bathtub", F.BATHTUB, (1.7, 0.75, 0.55), "ceramic")
            if tub
            else ("Shower", F.SHOWER, (0.9, 0.9, 2.0), "glass")
        )
    items.append(("Basin", F.BASIN, (0.7, 0.45, 0.85), "ceramic"))
    items.append(("Toilet", F.TOILET, (0.4, 0.65, 0.8), "ceramic"))
    if along_u:
        cursor = m
        for name, kind, size, mat in items:
            if p.put(
                r, name, kind, cursor + size[0] / 2 + 0.02, back - size[1] / 2, "-v", size, mat
            ):
                cursor += size[0] + 0.1
    else:
        cursor = back
        for name, kind, size, mat in items:
            if p.put(r, name, kind, m + size[1] / 2, cursor - size[0] / 2 - 0.02, "+u", size, mat):
                cursor -= size[0] + 0.1


def _study(p: _Placer, r: _Room) -> None:
    m = INSET
    if p.put(r, "Desk", F.DESK, r.W / 2, r.D - m - 0.35, "-v", (1.4, 0.7, 0.75), "wood"):
        p.put(r, "Desk chair", F.CHAIR, r.W / 2, r.D - m - 1.0, "+v", (0.45, 0.5, 0.9), "fabric")
    door_u = _door_side(r)
    u = r.W - m - 0.8 if door_u < r.W / 2 else m + 0.8
    p.put(r, "Bookshelf", F.BOOKSHELF, u, m + 0.2, "+v", (1.4, 0.4, 2.0), "wood")


def _outdoor(p: _Placer, r: _Room) -> None:
    if r.W * r.D < 3.5:
        return
    cv = max(r.D / 2, r.D - INSET - 0.5)  # away from the house wall and its door
    for cu in (r.W / 2, INSET + 1.0, r.W - INSET - 1.0):
        if p.put(r, "Outdoor table", F.COFFEE_TABLE, cu, cv, "+v", (0.7, 0.7, 0.45), "wood"):
            p.put(r, "Outdoor chair 1", F.CHAIR, cu - 0.7, cv, "+u", (0.45, 0.5, 0.9), "metal")
            p.put(r, "Outdoor chair 2", F.CHAIR, cu + 0.7, cv, "-u", (0.45, 0.5, 0.9), "metal")
            return


TEMPLATES: dict[RoomType, Callable[[_Placer, _Room], None]] = {
    RoomType.BEDROOM: _bedroom,
    RoomType.LIVING: _living,
    RoomType.DINING: _dining,
    RoomType.KITCHEN: _kitchen,
    RoomType.OPEN_KITCHEN_LIVING: _open_kitchen_living,
    RoomType.BATHROOM: _bathroom,
    RoomType.EN_SUITE: _bathroom,
    RoomType.WC: lambda p, r: _bathroom(p, r, wc_only=True),
    RoomType.STUDY: _study,
    RoomType.BALCONY: _outdoor,
    RoomType.TERRACE: _outdoor,
}


def furnish(
    plan: PlanLayout,
    rooms: dict[tuple[int, str], Room],
    doors: list[tuple[int, Point, Point]],
    levels: list[Level],
    ids: Callable[[str], uuid.UUID],
) -> list[Element]:
    corridor_y = plan.skeleton.Ds
    out: list[Element] = []
    counters: dict[str, int] = {}
    for level in plan.levels:
        placer = _Placer(levels[level.index], ids, counters)
        zones = []
        for lv, a, b in doors:
            if lv != level.index:
                continue
            if abs(a[1] - b[1]) < 1e-6:  # horizontal wall
                zones.append(
                    Rect(
                        min(a[0], b[0]) - 0.1,
                        a[1] - DOOR_CLEARANCE,
                        max(a[0], b[0]) + 0.1,
                        a[1] + DOOR_CLEARANCE,
                    )
                )
            else:
                zones.append(
                    Rect(
                        a[0] - DOOR_CLEARANCE,
                        min(a[1], b[1]) - 0.1,
                        a[0] + DOOR_CLEARANCE,
                        max(a[1], b[1]) + 0.1,
                    )
                )
        for region in level.regions:
            template = TEMPLATES.get(region.room_type) if region.room_type else None
            room = rooms.get((level.index, region.key))
            if template is None or room is None:
                continue
            rect = max(region.rects, key=lambda r: (r.area, -r.x0, -r.y0))
            doors_here = [
                z
                for z in zones
                if z.x0 < rect.x1 and rect.x0 < z.x1 and z.y0 < rect.y1 and rect.y0 < z.y1
            ]
            local = _Room(
                region, room, rect, corridor_high=rect.y1 <= corridor_y + 1e-6, doors=doors_here
            )
            template(placer, local)
            out += local.items
    return out
