"""Cheap derived statistics of a BuildingModel (for version lists and generation summaries).

Derived data: always recomputable from the model, never edited directly.
"""

from collections import defaultdict

from pydantic import Field
from shapely import LineString, unary_union
from shapely.ops import polygonize

from app.modules.building.design_checks import window_facades
from app.modules.building.elements import Door, Room, Wall, Window
from app.modules.building.enums import RelationshipKind, RoomType, WallKind, Zone
from app.modules.building.facades import facade_of_wall
from app.modules.building.geometry import wall_axis
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import Frozen

CIRCULATION = frozenset({RoomType.CORRIDOR, RoomType.HALL, RoomType.ENTRANCE, RoomType.STAIRCASE})


class ModelSummary(Frozen):
    storeys: int
    # Area enclosed by the exterior wall centerlines of each level, summed (garage excluded:
    # its walls stop at the house's outer face and do not close a loop).
    gross_floor_area_m2: float
    net_floor_area_m2: float  # rooms, excluding circulation, garage and outdoor rooms
    rooms: int  # rooms excluding circulation, garage and outdoor rooms
    bedrooms: int
    bathrooms: int  # bathrooms + en-suites
    wcs: int
    garage: bool
    balconies: int
    terraces: int
    walls: int
    doors: int
    windows: int
    elements: int
    # Delivered design facts (K3; defaults keep older stored summaries valid). Facades are
    # front/rear/left/right (building/facades.py).
    facade_colors: list[str] = Field(default_factory=list)  # distinct exterior face colors
    windows_by_facade: dict[str, dict[str, int]] = Field(default_factory=dict)  # size -> count
    rooms_on_facade: dict[str, list[str]] = Field(default_factory=dict)  # room semantic keys


def _design_facts(
    model: BuildingModel,
) -> tuple[list[str], dict[str, dict[str, int]], dict[str, list[str]]]:
    colors: set[str] = set()
    rooms_on: dict[str, set[str]] = defaultdict(set)
    semantic = {el.id: el.semantic_key for el in model.elements if isinstance(el, Room)}
    for el in model.elements:
        if not isinstance(el, Wall) or el.properties.wall_kind != WallKind.EXTERIOR:
            continue
        if el.properties.finish_right_color is not None:
            colors.add(el.properties.finish_right_color)
        side = facade_of_wall(el.properties.wall_kind, el.rotation.z)
        for rel in el.relationships:
            if rel.kind == RelationshipKind.BOUNDS and rel.target_id in semantic and side:
                rooms_on[side.value].add(semantic[rel.target_id])
    windows: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    facades = window_facades(model)
    for el in model.elements:
        if isinstance(el, Window) and el.properties.size_class is not None:
            side = facades.get(el.id)
            if side is not None:
                windows[side.value][el.properties.size_class.value] += 1
    return (
        sorted(colors),
        {f: dict(sorted(sizes.items())) for f, sizes in sorted(windows.items())},
        {f: sorted(keys) for f, keys in sorted(rooms_on.items())},
    )


def summarize(model: BuildingModel) -> ModelSummary:
    gross = 0.0
    for level in model.levels:
        axes = [
            tuple((round(x, 3), round(y, 3)) for x, y in wall_axis(el))  # 1 mm: close the loops
            for el in model.elements
            if isinstance(el, Wall)
            and el.level_id == level.id
            and el.properties.wall_kind == WallKind.EXTERIOR
        ]
        if axes:
            noded = unary_union([LineString(axis) for axis in axes])  # split at crossings
            gross += sum(p.area for p in polygonize(getattr(noded, "geoms", [noded])))
    rooms = [el for el in model.elements if isinstance(el, Room)]
    types = [r.properties.room_type for r in rooms]
    main = [
        r
        for r in rooms
        if r.properties.room_type not in CIRCULATION
        and r.properties.room_type != RoomType.GARAGE
        and r.properties.zone != Zone.EXTERIOR
    ]
    colors, windows_by_facade, rooms_on_facade = _design_facts(model)
    return ModelSummary(
        storeys=len(model.levels),
        gross_floor_area_m2=round(gross, 1),
        net_floor_area_m2=round(sum(r.dimensions.area for r in main), 1),
        rooms=len(main),
        bedrooms=types.count(RoomType.BEDROOM),
        bathrooms=types.count(RoomType.BATHROOM) + types.count(RoomType.EN_SUITE),
        wcs=types.count(RoomType.WC),
        garage=RoomType.GARAGE in types,
        balconies=types.count(RoomType.BALCONY),
        terraces=types.count(RoomType.TERRACE),
        walls=sum(isinstance(el, Wall) for el in model.elements),
        doors=sum(isinstance(el, Door) for el in model.elements),
        windows=sum(isinstance(el, Window) for el in model.elements),
        elements=len(model.elements),
        facade_colors=colors,
        windows_by_facade=windows_by_facade,
        rooms_on_facade=rooms_on_facade,
    )
