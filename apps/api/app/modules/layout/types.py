"""Use a TypeSet for the layout engine's design values (Phase 3.5 K2, docs/3d-engine.md §16.6).

`config_with_types` returns the LayoutConfig the engine runs with: each value a type of the set
defines replaces the matching LayoutConfig default; roles without a type keep the default. The
engine's geometry code is unchanged — it reads the (effective) config as before — so a type set
that mirrors the defaults produces byte-identical geometry.

Values the config holds once but the set could define per role (door thickness, railing post
spacing, roof thickness for main and garage roofs) must agree; otherwise the set cannot be
expressed and `TypeSetError` is raised (never averaged or picked silently).
"""

from app.modules.building.specification import WindowStyle
from app.modules.building.types import (
    DoorTypeParams,
    RailingTypeParams,
    StairTypeParams,
    TypeSet,
    TypeSnapshot,
    WindowTypeParams,
)
from app.modules.layout.config import LayoutConfig, WindowPreset

WINDOW_STYLE_ROLES = {
    WindowStyle.STANDARD: "window.standard",
    WindowStyle.LARGE: "window.large",
    WindowStyle.PANORAMIC: "window.panoramic",
}
SLAB_ROLES = {
    "slab.ground": "ground_slab_thickness",
    "slab.floor": "floor_slab_thickness",
    "slab.balcony": "balcony_slab_thickness",
    "slab.terrace": "terrace_slab_thickness",
}
WALL_ROLES = {
    "wall.exterior": "exterior_wall_thickness",
    "wall.interior": "interior_wall_thickness",
}
DOOR_ROLES = {
    "door.entrance": "entrance_door",
    "door.interior": "interior_door",
    "door.wet_room": "wet_room_door",
    "door.sliding": "sliding_door",
}


class TypeSetError(ValueError):
    pass


def _thickness(type_set: TypeSet, t: TypeSnapshot) -> float:
    assembly = type_set.assembly(t.assembly_id)
    if assembly is None:
        raise TypeSetError(f"{t.id}: assembly {t.assembly_id} is not in the type set")
    return assembly.total_thickness


def _agree(name: str, values: list[float]) -> float | None:
    distinct = sorted(set(values))
    if len(distinct) > 1:
        raise TypeSetError(f"types disagree on {name}: {distinct}")
    return distinct[0] if distinct else None


def config_with_types(config: LayoutConfig, type_set: TypeSet | None) -> LayoutConfig:
    if type_set is None:
        return config
    update: dict[str, object] = {}

    def typed(role: str) -> TypeSnapshot | None:
        return type_set.type_for(role)

    for role, field in {**WALL_ROLES, **SLAB_ROLES}.items():
        if (t := typed(role)) is not None:
            update[field] = _thickness(type_set, t)
    roof = _agree(
        "roof thickness",
        [_thickness(type_set, t) for r in ("roof.main", "roof.garage") if (t := typed(r))],
    )
    if roof is not None:
        update["roof_thickness"] = roof

    door_thickness: list[float] = []
    for role, field in DOOR_ROLES.items():
        t = typed(role)
        if t is None:
            continue
        p = t.params
        if not isinstance(p, DoorTypeParams) or p.default_width is None:
            raise TypeSetError(f"{role}: {t.id} needs door params with a default_width")
        update[field] = (p.default_width, p.height)
        door_thickness.append(p.thickness)
    if (t := typed("door.garage")) is not None:
        p = t.params
        if not isinstance(p, DoorTypeParams) or p.width_per_car is None:
            raise TypeSetError(f"door.garage: {t.id} needs door params with width_per_car")
        update["garage_door_height"] = p.height
        update["garage_door_width_per_car"] = p.width_per_car
        door_thickness.append(p.thickness)
    thickness = _agree("door thickness", door_thickness)
    if thickness is not None:
        update["door_thickness"] = thickness

    presets = dict(config.window_presets)
    for style, role in WINDOW_STYLE_ROLES.items():
        t = typed(role)
        if t is None:
            continue
        wp = t.params
        if (
            not isinstance(wp, WindowTypeParams)
            or wp.glazing_ratio is None
            or wp.mullion_spacing is None
        ):
            raise TypeSetError(f"{role}: {t.id} needs glazing_ratio and mullion_spacing")
        presets[style] = WindowPreset(
            sill=wp.default_sill,
            height=wp.default_height,
            glazing_ratio=wp.glazing_ratio,
            mullion_spacing=wp.mullion_spacing,
        )
    update["window_presets"] = presets
    if (t := typed("window.service")) is not None:
        wp = t.params
        if not isinstance(wp, WindowTypeParams) or wp.default_width is None:
            raise TypeSetError(f"window.service: {t.id} needs a default_width")
        update["service_window"] = (wp.default_width, wp.default_height, wp.default_sill)
    if (t := typed("window.stair")) is not None:
        wp = t.params
        if not isinstance(wp, WindowTypeParams):
            raise TypeSetError(f"window.stair: {t.id} is not a window type")
        update["stair_window"] = (wp.default_height, wp.default_sill)

    if (t := typed("stair.main")) is not None:
        sp = t.params
        if not isinstance(sp, StairTypeParams):
            raise TypeSetError(f"stair.main: {t.id} is not a stair type")
        update["stair_width"] = sp.width
    spacing: list[float] = []
    for role, field in (
        ("railing.stair", "stair_railing_height"),
        ("railing.balcony", "balcony_railing_height"),
    ):
        t = typed(role)
        if t is None:
            continue
        rp = t.params
        if not isinstance(rp, RailingTypeParams):
            raise TypeSetError(f"{role}: {t.id} is not a railing type")
        update[field] = rp.height
        spacing.append(rp.post_spacing)
    post_spacing = _agree("railing post spacing", spacing)
    if post_spacing is not None:
        update["railing_post_spacing"] = post_spacing
    return config.model_copy(update=update)
