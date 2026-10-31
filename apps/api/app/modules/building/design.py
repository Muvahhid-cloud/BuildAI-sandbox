"""Design systems and explicit design intent (Phase 3.5 K3, docs/building-model.md §2.2, §3.6).

Plain building-level data: the catalog (`catalog.design_systems`) turns APPROVED design-system
records into `DesignSystemSnapshot`s, and the generation pipeline passes them here and to the
layout engine. Nothing in this module reads the catalog or decides geometry.

Precedence (deterministic, never decided by an LLM):

    1. explicit user requirement   (a value in the specification)
    2. explicit selected design system -> its allow-lists (conflicts are errors, never
       silently changed)
    3. design-system defaults      (only for what the spec leaves null: facade color,
       finishes, furniture palette, component types)
    4. generic defaults            (the layout engine's existing behaviour)

`effective_design` returns the `DesignRecord` a generated model carries (None when there is no
system and no intent, so the no-intent path is unchanged).
"""

from typing import Annotated, Literal

from pydantic import Field

from app.modules.building.appearance import PALETTE, ResolvedColor, resolve_color
from app.modules.building.enums import RoofType
from app.modules.building.issues import Issue, pointer
from app.modules.building.primitives import Frozen, HexColor, MaterialId
from app.modules.building.specification import (
    ArchitecturalStyle,
    BuildingSpecification,
    DesignSystemRef,
    FacadeMaterial,
    FacadeSide,
    InteriorStyle,
    WindowStyle,
)
from app.modules.building.types import ContentHash, SourceRef, TypeId

# --- design-system content (shared by catalog records and model snapshots) ---------------


class DesignRoof(Frozen):
    types: list[RoofType] = Field(min_length=1)
    default: RoofType
    default_pitch_deg: float | None = Field(default=None, ge=5, le=45)


class DesignWindows(Frozen):
    styles: list[WindowStyle] = Field(min_length=1)
    default: WindowStyle


class DesignFacade(Frozen):
    materials: list[FacadeMaterial] = Field(min_length=1)
    default_material: FacadeMaterial
    colors: list[str] = Field(default_factory=list)  # palette names (appearance.PALETTE)
    default_color: str | None = None  # palette name; None = the material's own color
    custom_colors: bool = False  # may a user choose a color outside `colors`?


class DesignFinishes(Frozen):
    """Interior finish materials (material-library ids; render appearance + future costing)."""

    dry_floor: MaterialId  # living rooms, bedrooms, corridors
    wet_floor: MaterialId  # kitchens, bathrooms, WCs, laundry, entrance
    interior_wall: MaterialId
    wet_wall: MaterialId  # wall faces of wet rooms


class FurniturePalette(Frozen):
    """Furniture materials by slot (placeholders use these material ids)."""

    upholstery: MaterialId
    upholstery_light: MaterialId
    wood: MaterialId
    wood_dark: MaterialId
    cabinet: MaterialId
    countertop: MaterialId


# What the engine did before K3 (and still does without a design system).
GENERIC_FINISHES = DesignFinishes(
    dry_floor="parquet", wet_floor="tile", interior_wall="interior_wall", wet_wall="tile"
)
GENERIC_FURNITURE = FurniturePalette(
    upholstery="fabric",
    upholstery_light="fabric_light",
    wood="wood",
    wood_dark="wood_dark",
    cabinet="cabinet",
    countertop="countertop",
)


class DesignSystemSnapshot(Frozen):
    """An approved design system as copied into a model (self-contained, like type snapshots)."""

    id: DesignSystemRef
    name: str = Field(min_length=1, max_length=120)
    source: SourceRef  # catalog pack ref
    content_sha256: ContentHash  # of the catalog record
    style_tags: list[ArchitecturalStyle] = Field(min_length=1)
    interior_styles: list[InteriorStyle] = Field(min_length=1)
    role_mapping: Annotated[str, Field(max_length=96)]
    type_ids: list[TypeId]  # the types its role mapping resolved to (sorted)
    roof: DesignRoof
    windows: DesignWindows
    facade: DesignFacade
    finishes: DesignFinishes
    furniture: FurniturePalette


class UnavailableDesignSystem(Frozen):
    id: DesignSystemRef
    name: str
    reason: str


class DesignCatalog(Frozen):
    """What generation may use: approved, complete systems — and why others are not usable."""

    available: list[DesignSystemSnapshot] = Field(default_factory=list)
    unavailable: list[UnavailableDesignSystem] = Field(default_factory=list)

    def get(self, design_id: str) -> DesignSystemSnapshot | None:
        return next((d for d in self.available if d.id == design_id), None)

    def reason(self, design_id: str) -> UnavailableDesignSystem | None:
        return next((d for d in self.unavailable if d.id == design_id), None)


# --- effective design (stored in the model, schema 1.2.0) --------------------------------

ChoiceSource = Literal["user", "design_system"]


class EffectiveColor(Frozen):
    hex: HexColor
    name: str | None = None
    source: ChoiceSource


class WindowIntentRecord(Frozen):
    emphasis: WindowStyle
    preferred_facades: list[FacadeSide]
    excluded_facades: list[FacadeSide]
    source: ChoiceSource = "user"


class DesignRecord(Frozen):
    """The design decisions a model was generated with (self-contained; K3)."""

    design_system: DesignSystemSnapshot | None
    facade_color: EffectiveColor | None  # exterior wall faces (render appearance)
    windows: WindowIntentRecord | None


def effective_facade_color(
    spec: BuildingSpecification, system: DesignSystemSnapshot | None
) -> EffectiveColor | None:
    """User color > design-system default color > none (the facade material's own color)."""
    if spec.design.facade_color is not None:
        resolved = resolve_color(spec.design.facade_color)
        if resolved is None:  # tier-2 checks report APPEARANCE_INVALID first
            return None
        return EffectiveColor(hex=resolved.hex, name=resolved.name, source="user")
    if system is not None and system.facade.default_color is not None:
        resolved = resolve_color(system.facade.default_color)
        if resolved is not None:
            return EffectiveColor(hex=resolved.hex, name=resolved.name, source="design_system")
    return None


def resolve_window_preferences(spec: BuildingSpecification) -> dict[FacadeSide, WindowStyle]:
    """The window size class for each facade.

    Without window intent every facade uses `style.window_style` (the pre-K3 behaviour). With
    intent: preferred facades get the emphasis; excluded facades never get an emphasised size
    (standard); the others keep `style.window_style`, capped to standard when that is the
    emphasis itself (so emphasis stays concentrated where it was asked for)."""
    base = spec.style.window_style
    intent = spec.design.windows
    out: dict[FacadeSide, WindowStyle] = {}
    for side in FacadeSide:
        if intent is None:
            out[side] = base
        elif side in intent.preferred_facades:
            out[side] = intent.emphasis
        elif side in intent.excluded_facades or base == intent.emphasis:
            out[side] = WindowStyle.STANDARD
        else:
            out[side] = base
    return out


def resolve_facade_preferences(spec: BuildingSpecification) -> dict[str, FacadeSide]:
    """Room key -> the facade it should face (rooms[].faces)."""
    return {r.key: r.faces for r in spec.rooms if r.faces is not None}


def finishes_of(system: DesignSystemSnapshot | None) -> DesignFinishes:
    return system.finishes if system is not None else GENERIC_FINISHES


def furniture_substitution(system: DesignSystemSnapshot | None) -> dict[str, str]:
    """Generic furniture material -> the system's material for the same slot."""
    if system is None:
        return {}
    generic = GENERIC_FURNITURE.model_dump()
    chosen = system.furniture.model_dump()
    return {generic[slot]: chosen[slot] for slot in generic if generic[slot] != chosen[slot]}


def effective_design(
    spec: BuildingSpecification, system: DesignSystemSnapshot | None
) -> DesignRecord | None:
    color = effective_facade_color(spec, system)
    intent = spec.design.windows
    windows = (
        WindowIntentRecord(
            emphasis=intent.emphasis,
            preferred_facades=list(intent.preferred_facades),
            excluded_facades=list(intent.excluded_facades),
        )
        if intent is not None
        else None
    )
    if system is None and color is None and windows is None:
        return None
    return DesignRecord(design_system=system, facade_color=color, windows=windows)


# --- tier-2 checks -------------------------------------------------------------------------


def _error(code: str, path: str, message: str, suggestion: str | None = None) -> Issue:
    return Issue(severity="error", code=code, path=path, message=message, suggestion=suggestion)


def check_intent(spec: BuildingSpecification) -> list[Issue]:
    """Design intent that is invalid on its own (no catalog needed)."""
    issues: list[Issue] = []
    color = spec.design.facade_color
    if color is not None and resolve_color(color) is None:
        issues.append(
            _error(
                "APPEARANCE_INVALID",
                "/design/facade_color",
                f"{color!r} is not a supported color",
                suggestion=f"Use one of {', '.join(PALETTE)} or a #rrggbb value.",
            )
        )
    intent = spec.design.windows
    if intent is not None:
        for field in ("preferred_facades", "excluded_facades"):
            values = getattr(intent, field)
            if len(set(values)) != len(values):
                issues.append(
                    _error(
                        "FACADE_PREFERENCE_INVALID",
                        f"/design/windows/{field}",
                        f"{field} lists a facade twice",
                    )
                )
        both = sorted(set(intent.preferred_facades) & set(intent.excluded_facades))
        if both:
            issues.append(
                _error(
                    "WINDOW_FACADE_CONFLICT",
                    "/design/windows",
                    f"{', '.join(both)} is both preferred and excluded for "
                    f"{intent.emphasis.value} windows",
                    suggestion="Remove the facade from one of the two lists.",
                )
            )
    for i, room in enumerate(spec.rooms):
        if room.faces in (FacadeSide.LEFT, FacadeSide.RIGHT):
            issues.append(
                _error(
                    "FACADE_PREFERENCE_INVALID",
                    pointer("rooms", i, "faces"),
                    f"{room.key}: rooms can face the front (street) or the rear (garden) "
                    "facade; left and right are not supported",
                    suggestion="Use faces: rear (garden/backyard) or front (street).",
                )
            )
    return issues


def check_design(spec: BuildingSpecification, catalog: DesignCatalog) -> list[Issue]:
    """The selected design system against the catalog and its allow-lists (tier 2)."""
    design_id = spec.style.design_system
    if design_id is None:
        return []
    path = "/style/design_system"
    system = catalog.get(design_id)
    if system is None:
        unavailable = catalog.reason(design_id)
        usable = ", ".join(d.id for d in catalog.available) or "none"
        if unavailable is not None:
            return [
                _error(
                    "DESIGN_SYSTEM_NOT_APPROVED",
                    path,
                    f"Design system {design_id} cannot be used yet: {unavailable.reason}",
                    suggestion=f"Leave design_system empty. Usable design systems: {usable}.",
                )
            ]
        return [
            _error(
                "DESIGN_SYSTEM_UNKNOWN",
                path,
                f"Unknown design system {design_id!r}",
                suggestion=f"Usable design systems: {usable}.",
            )
        ]
    issues: list[Issue] = []

    def conflict(where: str, what: str, value: str, allowed: list[str]) -> None:
        issues.append(
            _error(
                "DESIGN_OPTION_CONFLICT",
                where,
                f"{what} {value} is not part of the {system.name} design system",
                suggestion=f"Compatible choices: {', '.join(allowed)}; or choose another "
                "design system (or none).",
            )
        )

    style = spec.style
    if style.architectural_style not in system.style_tags:
        conflict(
            "/style/architectural_style",
            "Architectural style",
            style.architectural_style.value,
            [s.value for s in system.style_tags],
        )
    if style.interior_style is not None and style.interior_style not in system.interior_styles:
        conflict(
            "/style/interior_style",
            "Interior style",
            style.interior_style.value,
            [s.value for s in system.interior_styles],
        )
    if style.roof.type not in system.roof.types:
        conflict(
            "/style/roof/type", "Roof", style.roof.type.value, [r.value for r in system.roof.types]
        )
    if style.window_style not in system.windows.styles:
        conflict(
            "/style/window_style",
            "Window style",
            style.window_style.value,
            [w.value for w in system.windows.styles],
        )
    intent = spec.design.windows
    if intent is not None and intent.emphasis not in system.windows.styles:
        conflict(
            "/design/windows/emphasis",
            "Window size",
            intent.emphasis.value,
            [w.value for w in system.windows.styles],
        )
    if style.facade_material not in system.facade.materials:
        conflict(
            "/style/facade_material",
            "Facade material",
            style.facade_material.value,
            [m.value for m in system.facade.materials],
        )
    color = spec.design.facade_color
    resolved: ResolvedColor | None = resolve_color(color) if color is not None else None
    if (
        resolved is not None
        and not system.facade.custom_colors
        and resolved.name not in system.facade.colors
    ):
        issues.append(
            _error(
                "DESIGN_OPTION_CONFLICT",
                "/design/facade_color",
                f"Facade color {color} is not in the {system.name} palette"
                + ("" if system.facade.colors else " (its facades keep their material color)"),
                suggestion=(
                    f"Compatible colors: {', '.join(system.facade.colors)}; or choose another "
                    "design system (or none)."
                    if system.facade.colors
                    else "Choose another design system (or none) to color the facade."
                ),
            )
        )
    return issues
