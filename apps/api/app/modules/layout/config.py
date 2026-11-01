"""LayoutConfig: construction defaults and search parameters of the layout engine.

These are *design defaults* (typical wall build-ups, preferred door and window sizes, default
room sizes), not rules: every minimum/maximum the engine must respect comes from the active
BuildingRulesProfile, and where both exist the engine uses max(default, rule minimum).
Changing a default changes generated models, so bump ENGINE_VERSION with it.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.modules.building.enums import RoofType, RoomType
from app.modules.building.specification import ArchitecturalStyle, FacadeMaterial, WindowStyle

ENGINE_VERSION = "layout@1.10.0"  # 1.10.0: facade bay grid (V5): bays per facade line,
# windows on bay axes with one width per facade and storey, rooms snap to whole bays where
# their minimums and area ranges allow.
# 1.9.0: facade grid (V4): partitions of the storeys snap to
# each other's facade grid, windows are placed top storey first and stack on shared axes,
# garden/terrace doors stand on an upper window axis, rhythm windows below upper axes.
# 1.8.0: architectural design quality (V3): BuildingModel
# 1.3.0 with an entrance canopy (slab_kind "canopy") over the front door; roof covering per
# roof type (flat roofs: gravel membrane), facade finish per facade material (timber: cladding
# boards), facade zoning per architectural style (plinth storey, accent cladding on the garage;
# never with a requested facade color). Wall cores (material_id) are unchanged.
# 1.7.0: footprint shapes (V1.3): T-shaped single-storey
# footprints, depth bars for L/T main bars (small or long houses), shapes without a generator
# refused with the reason. Rectangular geometry unchanged (fingerprints of specs 01-10 as 1.6.0).
# 1.6.0: L layout quality (V1.2): the wing's last room takes
# the gallery's end, the main corridor's dead ends go to rooms (joining e.g. kitchen and dining),
# garden-sized L band splits, the wing on either side of a garage, more L footprints evaluated
# when an L is requested. Rectangular geometry unchanged (fingerprints of specs 01-10 as 1.5.0).
# 1.5.0: L-shaped single-storey footprints (V1.1); rectangular
# geometry unchanged (fingerprints of reference specs 01-10 equal to 1.4.0).
# 1.4.0: Design Intelligence V1 — requirement priorities
# (MUST/SHOULD), permissible area ranges, separations, layout patterns (soft), every valid built
# candidate evaluated against the spec, bounded repair. Generated models change (golden files).
# 1.3.0: BuildingModel 1.2.0; design systems and design intent
# (facade color, facade-specific window sizes, room orientation; K3). Specs without them build
# the same geometry as 1.2.0 (geometry fingerprints unchanged).
# 1.2.0: stair cores on the facade fit their flights (K2.5)
# 1.1.0: BuildingModel 1.1.0, optional TypeSet (K2)


class _Config(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WindowPreset(_Config):
    sill: float
    height: float
    glazing_ratio: float  # target glazing / floor area for habitable rooms
    mullion_spacing: float


class CanopyConfig(_Config):
    """Entrance canopy over the front door (V3, slab_kind "canopy"). Construction defaults,
    not rules: it projects `depth` from the facade, reaches `side` beyond each door jamb (less
    where a window head would be cut) and hangs `clearance` above the door head."""

    depth: float = Field(default=1.2, gt=0)
    side: float = Field(default=0.45, ge=0)
    thickness: float = Field(default=0.12, gt=0)
    clearance: float = Field(default=0.25, ge=0)


class FacadeZoning(_Config):
    """Facade finishes beside the main one (V3); library material ids, None = main finish."""

    plinth: str | None = None
    accent: str | None = None


class LayoutConfig(_Config):
    engine_version: str = ENGINE_VERSION
    grid: float = 0.05  # all plan coordinates snap to this grid

    # Construction build-up
    exterior_wall_thickness: float = 0.3
    interior_wall_thickness: float = 0.12
    floor_slab_thickness: float = 0.2
    ground_slab_thickness: float = 0.3
    balcony_slab_thickness: float = 0.2
    terrace_slab_thickness: float = 0.15

    # Plan
    corridor_width: float = 1.2
    entrance_hall_width: float = 2.2  # hall part next to the stair core (ground floor)
    compact_hall_width: float = 1.6  # alternative for small footprints (>= rules minimum)
    min_band_depth: float = 3.3
    remainder_min_depth: float = 1.2  # facade-side part left to the room wrapping a tucked room
    # Footprint width/depth ratios (x along the street). < 1 = deep plans for narrow plots.
    footprint_aspects: tuple[float, ...] = (
        0.5,
        0.58,
        0.65,
        0.8,
        0.9,
        1.0,
        1.15,
        1.3,
        1.45,
        1.6,
        1.8,
    )
    # Footprint area relative to the requested floor area. The requested area is a primary
    # target: rooms deviate (with warnings) rather than the house shrinking.
    footprint_area_scales: tuple[float, ...] = (1.0,)
    # South band depth candidates around an even split of the two room bands.
    band_split_offsets: tuple[float, ...] = (-0.6, -0.3, 0.0, 0.3, 0.6)
    core_positions: tuple[float, ...] = (0.0, 0.25, 0.5, 0.75, 1.0)
    variants_per_skeleton: int = 3
    # L topology (single storey, docs/3d-engine.md §16.10): main bar width/depth ratios, share
    # of the floor area in the wing, band splits, and the shape limits of a real L.
    l_main_aspects: tuple[float, ...] = (1.45, 1.8, 2.2)
    l_wing_area_shares: tuple[float, ...] = (0.2, 0.3, 0.4)
    l_band_split_offsets: tuple[float, ...] = (-0.3, 0.0, 0.3)
    l_wing_min_length: float = 3.0  # how far the wing reaches beyond the main bar, at least
    l_min_garden_frontage: float = 4.0  # garden facade of the main bar beside the wing
    # Deepest garden band a garden-sized L split may ask for (V1.2, planner.garden_demands).
    l_garden_band_max_depth: float = 6.0
    # Depth bars (V1.3): main-bar depths above the shallowest double-loaded bar, and wing shares,
    # for houses whose ratio bars are too shallow (small or long L/T footprints).
    l_depth_steps: tuple[float, ...] = (0.0, 0.6, 1.2)
    l_depth_bar_shares: tuple[float, ...] = (0.2, 0.3, 0.4, 0.5)
    t_min_side_frontage: float = 4.0  # T: garden facade on each side of the wing
    t_min_wing_facade: float = 1.2  # T: a habitable wing room's reach beyond the garden facade
    # T main bars are longer than L ones: the wing takes the middle of the garden facade.
    t_main_aspects: tuple[float, ...] = (2.2, 2.6, 3.0)
    # Preferred wing length (beyond the main bar) / main bar width: a balanced L (scored).
    l_wing_ratio: tuple[float, float] = (0.4, 0.9)
    candidates_to_build: int = 6  # built, validated and evaluated; the best one wins
    # L footprints built when the user asked for an L (V1.2): distinct L shapes compared on
    # the evaluation; rectangular alternatives keep their share of candidates_to_build.
    l_requested_builds: int = 5
    repair_candidates_to_build: int = 18  # extra builds when none meets every MUST requirement
    circulation_share: float = 0.22  # GFA overhead estimate when no GFA is specified

    # Stairs
    stair_width: float = 1.0
    stair_clearance: float = 0.04  # each side, between the flight and the lane walls
    stair_comfort_target: float = 0.63  # 2R + T

    # Doors (width, height)
    door_thickness: float = 0.06
    entrance_door: tuple[float, float] = (1.0, 2.2)
    interior_door: tuple[float, float] = (0.9, 2.1)
    wet_room_door: tuple[float, float] = (0.8, 2.1)
    sliding_door: tuple[float, float] = (2.4, 2.4)
    garage_door_height: float = 2.2
    garage_door_width_per_car: float = 2.5
    door_margin: float = 0.2  # from the ends of the wall segment a door sits on

    # Windows
    window_presets: dict[WindowStyle, WindowPreset] = Field(
        default_factory=lambda: {
            WindowStyle.STANDARD: WindowPreset(
                sill=0.9, height=1.4, glazing_ratio=0.16, mullion_spacing=1.0
            ),
            WindowStyle.LARGE: WindowPreset(
                sill=0.6, height=1.8, glazing_ratio=0.22, mullion_spacing=1.2
            ),
            WindowStyle.PANORAMIC: WindowPreset(
                sill=0.1, height=2.4, glazing_ratio=0.3, mullion_spacing=1.4
            ),
        }
    )
    service_window: tuple[float, float, float] = (0.8, 0.6, 1.5)  # width, height, sill
    stair_window: tuple[float, float] = (1.2, 1.0)  # height, sill
    window_margin: float = 0.3
    # Facade grid (V4, docs/3d-engine.md §16.14): an upper storey's room partitions on a facade
    # snap to the partitions of the storey below when they are at most this far off, so the
    # rooms (and the windows centred in them) stack. 0 switches it off.
    facade_grid_snap: float = 1.2
    # Facade bay grid (V5, docs/3d-engine.md §16.15): each facade line is divided into equal
    # bays of bay_min_m..bay_max_m; windows stand on the bay centres with one width per facade
    # and storey (at most bay_window_share of a bay). False reproduces layout@1.9.0 exactly
    facade_bays: bool = True
    bay_min_m: float = 3.0
    bay_max_m: float = 4.2
    bay_window_share: float = 0.6
    bay_windows_per_room: int = 4
    # Stair, hall and corridor windows on bay axes too; off = they follow the windows of the
    # other storeys (V4 axis rule), which stacks them better where the hall below is short.
    bay_circulation_windows: bool = False
    lintel_min: float = 0.2  # wall above the highest opening

    # Garage, balconies, terraces
    garage_width_per_car: float = 3.0
    garage_extra_width: float = 0.5  # door jambs: a one-car garage is 3.5 m wide
    garage_min_depth: float = 6.0
    balcony_width: float = 4.0
    balcony_railing_height: float = 1.1
    stair_railing_height: float = 0.9
    railing_post_spacing: float = 1.0

    # Roof
    roof_pitch_deg: float = 25.0
    roof_overhang: float = 0.5
    roof_thickness: float = 0.2
    parapet_height: float = 0.3

    # Default target areas (m²) when the spec does not give one.
    default_areas: dict[RoomType, float] = Field(
        default_factory=lambda: {
            RoomType.BEDROOM: 13.0,
            RoomType.BATHROOM: 6.0,
            RoomType.EN_SUITE: 4.5,
            RoomType.WC: 2.5,
            RoomType.KITCHEN: 14.0,
            RoomType.LIVING: 28.0,
            RoomType.DINING: 14.0,
            RoomType.OPEN_KITCHEN_LIVING: 42.0,
            RoomType.STUDY: 10.0,
            RoomType.LAUNDRY: 5.0,
            RoomType.UTILITY: 5.0,
            RoomType.STORAGE: 3.5,
            RoomType.WALK_IN_CLOSET: 4.0,
            RoomType.PLANT_ROOM: 4.0,
        }
    )
    # Preferred widths of small service rooms tucked against the corridor.
    tuck_widths: dict[RoomType, float] = Field(
        default_factory=lambda: {
            RoomType.BATHROOM: 2.4,
            RoomType.EN_SUITE: 2.1,
            RoomType.WC: 1.3,
            RoomType.LAUNDRY: 2.1,
            RoomType.UTILITY: 2.1,
            RoomType.STORAGE: 1.4,
            RoomType.WALK_IN_CLOSET: 1.6,
            RoomType.PLANT_ROOM: 1.6,
        }
    )

    facade_materials: dict[FacadeMaterial, str] = Field(
        default_factory=lambda: {
            FacadeMaterial.RENDER: "exterior_wall",
            FacadeMaterial.BRICK: "brick",
            FacadeMaterial.CONCRETE: "concrete",
            FacadeMaterial.TIMBER: "wood",
        }
    )
    # Visible facade finish (wall right face) per facade material (V3). The wall core keeps
    # `facade_materials`; only timber differs: its facade reads as cladding boards.
    facade_finishes: dict[FacadeMaterial, str] = Field(
        default_factory=lambda: {
            FacadeMaterial.RENDER: "exterior_wall",
            FacadeMaterial.BRICK: "brick",
            FacadeMaterial.CONCRETE: "concrete",
            FacadeMaterial.TIMBER: "cladding_timber",
        }
    )
    # Entrance canopy (V3); None = no canopy. Material per architectural style (else trim).
    entrance_canopy: CanopyConfig | None = Field(default_factory=CanopyConfig)
    canopy_materials: dict[ArchitecturalStyle, str] = Field(
        default_factory=lambda: {
            ArchitecturalStyle.CLASSIC: "wood_dark",
            ArchitecturalStyle.TRADITIONAL: "wood_dark",
            ArchitecturalStyle.SCANDINAVIAN: "wood",
            ArchitecturalStyle.MEDITERRANEAN: "wood",
        }
    )
    # Roof covering per roof type (V3): a flat roof is not tiled.
    roof_materials: dict[RoofType, str] = Field(
        default_factory=lambda: {
            RoofType.FLAT: "roof_membrane",
            RoofType.GABLE: "roof",
            RoofType.HIP: "roof",
        }
    )
    # Facade zoning per architectural style (V3, building/design.py precedence: an approved
    # design system's first style tag, else the spec's style). `plinth` = finish of the ground
    # storey of multi-storey houses, `accent` = finish of a distinct volume (the garage). Never
    # applied when a facade color is requested (that colour covers the whole facade), and only
    # where it differs from the main finish. Appearance only: wall cores are unchanged.
    facade_zoning: dict[ArchitecturalStyle, FacadeZoning] = Field(
        default_factory=lambda: {
            ArchitecturalStyle.MODERN: FacadeZoning(accent="cladding_timber"),
            ArchitecturalStyle.MINIMALIST: FacadeZoning(),
            ArchitecturalStyle.CONTEMPORARY: FacadeZoning(plinth="brick", accent="cladding_timber"),
            ArchitecturalStyle.CLASSIC: FacadeZoning(plinth="brick"),
            ArchitecturalStyle.TRADITIONAL: FacadeZoning(plinth="brick"),
            ArchitecturalStyle.SCANDINAVIAN: FacadeZoning(accent="cladding_timber"),
            ArchitecturalStyle.INDUSTRIAL: FacadeZoning(plinth="brick"),
            ArchitecturalStyle.MEDITERRANEAN: FacadeZoning(),
            ArchitecturalStyle.LUXURY: FacadeZoning(plinth="concrete", accent="cladding_timber"),
        }
    )


DEFAULT_CONFIG = LayoutConfig()
