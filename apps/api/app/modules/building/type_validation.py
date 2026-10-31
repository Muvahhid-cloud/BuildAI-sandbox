"""Type and assembly invariants of BuildingModel 1.1.0 (docs/building-model.md §4, items 10-13).

Errors: duplicate snapshots, unknown or mismatched type references, a type without the
assembly its element type needs, assembly layers not adding up, elements differing from the
FIXED parameters of their type, unknown ceiling assemblies, unknown materials. Warning: a
snapshot no element (or type) uses.
"""

from typing import Literal

from app.modules.building.elements import (
    Door,
    Element,
    Railing,
    Roof,
    Room,
    Slab,
    Stair,
    Wall,
    Window,
)
from app.modules.building.issues import Issue
from app.modules.building.model import BuildingModel
from app.modules.building.primitives import EPS
from app.modules.building.types import (
    ASSEMBLY_KIND_FOR,
    AssemblyKind,
    AssemblySnapshot,
    DoorTypeParams,
    RailingTypeParams,
    SlabTypeParams,
    StairTypeParams,
    TypeSnapshot,
    WallTypeParams,
    WindowTypeParams,
)


class _TypeChecker:
    def __init__(self, model: BuildingModel, material_ids: frozenset[str] | None) -> None:
        self.model = model
        self.material_ids = material_ids
        self.issues: list[Issue] = []
        self.index = {el.id: i for i, el in enumerate(model.elements)}
        self.types: dict[str, TypeSnapshot] = {}
        self.assemblies: dict[str, AssemblySnapshot] = {}
        for i, t in enumerate(model.types):
            if t.id in self.types:
                self.add("error", "TYPE_SNAPSHOT_DUPLICATE", f"/types/{i}", f"{t.id} twice")
            self.types[t.id] = t
        for i, a in enumerate(model.assemblies):
            if a.id in self.assemblies:
                self.add("error", "TYPE_SNAPSHOT_DUPLICATE", f"/assemblies/{i}", f"{a.id} twice")
            self.assemblies[a.id] = a

    def add(
        self,
        severity: Literal["error", "warning"],
        code: str,
        path: str,
        message: str,
        element: Element | None = None,
    ) -> None:
        self.issues.append(
            Issue(
                severity=severity,
                code=code,
                path=path,
                message=message,
                element_id=element.id if element is not None else None,
            )
        )

    def run(self) -> list[Issue]:
        model = self.model
        for i, a in enumerate(model.assemblies):
            total = sum(layer.thickness for layer in a.layers)
            if abs(total - a.total_thickness) > EPS:
                self.add(
                    "error",
                    "ASSEMBLY_THICKNESS_SUM",
                    f"/assemblies/{i}/total_thickness",
                    f"{a.id}: layers add up to {total:.3f} m, total is {a.total_thickness} m",
                )
            self._materials(f"/assemblies/{i}/layers", [layer.material_id for layer in a.layers])
        for i, t in enumerate(model.types):
            self._type(i, t)
        used_types: set[str] = set()
        used_assemblies = {t.assembly_id for t in model.types if t.assembly_id is not None}
        for el in model.elements:
            path = f"/elements/{self.index[el.id]}"
            if el.type_ref is not None:
                used_types.add(el.type_ref)
                self._element(el, path)
            if isinstance(el, Room) and el.properties.ceiling_assembly_ref is not None:
                ref = el.properties.ceiling_assembly_ref
                used_assemblies.add(ref)
                ceiling = self.assemblies.get(ref)
                if ceiling is None or ceiling.kind != AssemblyKind.CEILING:
                    self.add(
                        "error",
                        "CEILING_ASSEMBLY_UNKNOWN",
                        f"{path}/properties/ceiling_assembly_ref",
                        f"{el.name}: {ref} is not a ceiling assembly of this model",
                        el,
                    )
        for i, t in enumerate(model.types):
            if t.id not in used_types:
                self.add("warning", "SNAPSHOT_UNUSED", f"/types/{i}", f"{t.id} is not used")
        for i, a in enumerate(model.assemblies):
            if a.id not in used_assemblies:
                self.add("warning", "SNAPSHOT_UNUSED", f"/assemblies/{i}", f"{a.id} is not used")
        return self.issues

    def _materials(self, path: str, ids: list[str | None]) -> None:
        if self.material_ids is None:
            return
        for mid in ids:
            if mid is not None and mid not in self.material_ids:
                self.add("error", "UNKNOWN_MATERIAL", path, f"Unknown material {mid!r}")

    def _type(self, i: int, t: TypeSnapshot) -> None:
        path = f"/types/{i}"
        expected = ASSEMBLY_KIND_FOR.get(t.element_type)
        assembly = self.assemblies.get(t.assembly_id) if t.assembly_id else None
        if expected is None and t.assembly_id is not None:
            self.add(
                "error",
                "TYPE_ASSEMBLY_UNEXPECTED",
                f"{path}/assembly_id",
                f"{t.id}: {t.element_type} types have no assembly",
            )
        elif expected is not None and (assembly is None or assembly.kind != expected):
            self.add(
                "error",
                "TYPE_ASSEMBLY_UNKNOWN",
                f"{path}/assembly_id",
                f"{t.id} needs a {expected} assembly carried by the model, got {t.assembly_id!r}",
            )
        p = t.params
        materials: list[str | None] = []
        if isinstance(p, DoorTypeParams | WindowTypeParams):
            materials = [p.material_id, p.frame_material_id]
        elif isinstance(p, StairTypeParams | RailingTypeParams):
            materials = [p.material_id]
        self._materials(f"{path}/params", materials)

    def _element(self, el: Element, path: str) -> None:
        t = self.types.get(el.type_ref or "")
        if t is None:
            self.add(
                "error",
                "TYPE_REF_UNKNOWN",
                f"{path}/type_ref",
                f"{el.name}: type {el.type_ref} is not carried by the model",
                el,
            )
            return
        if t.element_type != el.type:
            self.add(
                "error",
                "TYPE_ELEMENT_MISMATCH",
                f"{path}/type_ref",
                f"{el.name}: {t.id} is a {t.element_type} type, not a {el.type} type",
                el,
            )
            return
        diffs = fixed_param_differences(el, t, self.assemblies.get(t.assembly_id or ""))
        if diffs:
            self.add(
                "error",
                "TYPE_PARAM_MISMATCH",
                path,
                f"{el.name} differs from its type {t.id}: {'; '.join(diffs)}",
                el,
            )


def fixed_param_differences(
    el: Element, t: TypeSnapshot, assembly: AssemblySnapshot | None
) -> list[str]:
    """Differences between an element and the FIXED parameters of its type (defaults excluded)."""
    diffs: list[str] = []

    def same(field: str, actual: object, fixed: object) -> None:
        if isinstance(actual, float) and isinstance(fixed, float) and abs(actual - fixed) <= EPS:
            return
        if actual != fixed:
            diffs.append(f"{field} {actual} != {fixed}")

    p = t.params
    if isinstance(el, Wall | Slab | Roof) and assembly is not None:
        same("thickness", el.dimensions.thickness, assembly.total_thickness)
    if isinstance(el, Wall) and isinstance(p, WallTypeParams):
        same("wall_kind", el.properties.wall_kind, p.wall_kind)
        same("load_bearing", el.properties.load_bearing, p.load_bearing)
    elif isinstance(el, Slab) and isinstance(p, SlabTypeParams):
        same("slab_kind", el.properties.slab_kind, p.slab_kind)
    elif isinstance(el, Door) and isinstance(p, DoorTypeParams):
        same("door_kind", el.properties.door_kind, p.door_kind)
        same("height", el.dimensions.height, p.height)
        same("thickness", el.dimensions.thickness, p.thickness)
        same("material_id", el.material_id, p.material_id)
        same("frame_material_id", el.properties.frame_material_id, p.frame_material_id)
    elif isinstance(el, Window) and isinstance(p, WindowTypeParams):
        same("material_id", el.material_id, p.material_id)
        same("frame_material_id", el.properties.frame_material_id, p.frame_material_id)
    elif isinstance(el, Stair) and isinstance(p, StairTypeParams):
        same("stair_type", el.properties.stair_type, p.stair_type)
        same("width", el.dimensions.width, p.width)
        same("material_id", el.material_id, p.material_id)
    elif isinstance(el, Railing) and isinstance(p, RailingTypeParams):
        same("railing_kind", el.properties.railing_kind, p.railing_kind)
        same("height", el.dimensions.height, p.height)
        same("post_spacing", el.properties.post_spacing, p.post_spacing)
        same("material_id", el.material_id, p.material_id)
    return diffs


def check_types(model: BuildingModel, material_ids: frozenset[str] | None) -> list[Issue]:
    return _TypeChecker(model, material_ids).run()
