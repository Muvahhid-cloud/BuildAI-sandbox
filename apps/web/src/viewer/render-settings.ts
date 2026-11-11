// Look-development constants of the viewer (not part of the BuildingModel). One place, so
// screenshots and tuning stay reproducible. See docs/3d-engine.md §21.
import { MATERIAL_ASSET_BASE } from "@/engine/materials/library";

export const RENDER = {
  /** Local HDRI (data/materials/hdri, see ASSETS.md); never a runtime CDN. .hdr or .exr. */
  hdriUrl: `${MATERIAL_ASSET_BASE}hdri/potsdamer_platz_1k.hdr`,
  /** Image-based light strength (diffuse + reflections). */
  environmentIntensity: 0.75,
  /** Tone mapping exposure (ACES Filmic). */
  exposure: 1.0,
  /** Key light: the sun casts the soft shadows; the HDRI does the fill. */
  sunIntensity: 2.6,
  sunColor: "#fff3e2",
  shadowMapSize: 2048,
  /** PCF filter radius (soft shadow edges; PCFSoftShadowMap no longer exists in three). */
  shadowRadius: 4,
  /**
   * Bounce fill (V2): a soft hemisphere light that stands in for light reflected by floors and
   * the ground, so downward-facing surfaces (slab soffits seen as ceilings, eaves) are not black.
   */
  bounce: { sky: "#e9eef3", ground: "#d9cfc1", intensity: 0.55 },
  /** Fallback fill when the HDRI is unavailable. */
  fallbackHemisphere: { sky: "#f4f7fb", ground: "#a89c8a", intensity: 1.1 },
  /** Neutral sky gradient (sRGB, not tone mapped). */
  sky: { zenith: "#9dbbd6", horizon: "#e4ebf0" },
  contactShadow: { opacity: 0.5, blur: 2.4, far: 3.5, resolution: 1024 },
  /** N8AO: world-space radius (m), falloff and strength. */
  ao: { radius: 0.9, distanceFalloff: 1.0, intensity: 4 },
} as const;

/**
 * Build reveal (docs/3d-engine.md §25): the blueprint state while a design is generated and the
 * construction of the finished model from small pieces. Viewer effect only — never part of the
 * BuildingModel. Times in seconds, sizes in meters, angles in radians.
 */
export const REVEAL = {
  /** The pieces: instanced blocks, one draw call. */
  pieces: {
    /** Hard ceiling (performance budget on integrated GPUs); density adapts below it. */
    maxPieces: 25_000,
    minPerItem: 6,
    /** Largest share of a surface that pieces cover. */
    fill: 0.75,
    /** Piece edge: perRootArea × √(element surface), within [min, max]. */
    min: 0.12,
    max: 0.2,
    perRootArea: 0.06,
    /** Course height on vertical surfaces as a share of the edge (brick proportion). */
    course: 0.8,
    thickness: 0.3,
    /** Share of its cell a piece fills (the rest reads as the joint). */
    joint: 0.9,
    /** Largest horizontal offset of a piece's start from the point under its target. */
    startJitter: 0.12,
  },
  /** Timing of the construction (reveal/order.ts scheduleConstruction). */
  schedule: {
    /** The blueprint draws itself before the first element starts. */
    lead: 1,
    /** Whole build: minDuration + secondsPerElement × elements, at most maxDuration. */
    minDuration: 6,
    maxDuration: 9,
    secondsPerElement: 0.025,
    /** One piece's rise from the element base to its place (ease-out). */
    rise: 0.55,
    /** Largest per-piece random delay. */
    jitter: 0.12,
    /** Bottom-to-top arrival spread of an element: height × this, within [min, max]. */
    spreadPerMeter: 0.22,
    minSpread: 0.12,
    maxSpread: 0.7,
    /** The real mesh fades in once every piece of the element has landed. */
    fade: 0.3,
    /** The pieces shrink away, starting shrinkDelay × fade into the fade. */
    shrink: 0.35,
    shrinkDelay: 0.6,
    /** Relative time an element of each stage takes before the next one starts. */
    stageWeight: {
      slab: 3,
      floor: 0.6,
      exterior_wall: 3,
      interior_wall: 1.6,
      opening: 0.6,
      stair: 2,
      roof: 4,
      canopy: 2,
      balcony: 1.2,
      furniture: 0.5,
      site: 1.5,
    },
    /** Extra pause between two groups (same units as the weights). */
    groupGap: 2,
  },
  /**
   * Share of the piece budget per stage: walls and roofs read as the building, so they are
   * laid densely; small details and layers that end up covered get fewer pieces.
   */
  stageDensity: {
    slab: 0.35,
    floor: 0.4,
    exterior_wall: 1,
    interior_wall: 0.8,
    opening: 0.25,
    stair: 0.8,
    roof: 0.8,
    canopy: 0.8,
    balcony: 0.6,
    furniture: 0.3,
    site: 0.35,
  },
  /** A piece grows from nothing over this time as it leaves the base. */
  grow: 0.14,
  /** Moving pieces: the brand accent (globals.css --accent) and how much of it glows. */
  accent: "#5b5ee8",
  glow: 0.3,
  /** Roughness of a landed piece (matte, like plaster and concrete). */
  roughness: 0.85,
  /** The plan that draws itself on the ground, and the paper sheet under it. */
  blueprint: {
    draw: 1,
    settle: 0.8,
    trace: 0.28,
    out: 1.2,
    line: "#4f4ee0",
    lineWidth: 0.06,
    /** Height of the lines above the storey's floor level. */
    lift: 0.03,
    sheet: "#f3f5fb",
    sheetOpacity: 0.4,
    /** Sheet margin around the building and its grid spacing. */
    margin: 2.5,
    grid: 1,
  },
  /** Camera: a slow orbit that ends on the default exterior view. */
  camera: {
    sweep: 0.95,
    distance: 1.03,
    lift: 0.06,
    /** Blend from the camera's pose when the build starts. */
    blend: 0.9,
  },
  /** While the backend works: a ground grid and a slow scanning line (WaitingBlueprint). */
  waiting: {
    background: RENDER.sky.horizon,
    line: "#4f4ee0",
    /** Grid spacing, opacity of its lines and how far it reaches. */
    grid: 1,
    gridOpacity: 0.3,
    reach: 22,
    /** One pass of the scanning line over the grid. */
    scanPeriod: 6,
    scanOpacity: 0.85,
    /** A real stage change: one brighter pass that decays at this rate (per second). */
    pulse: 0.5,
    pulseDecay: 0.9,
  },
  /** After "Apply" in Modify with AI: only the changed elements re-assemble. */
  changes: { duration: 2.4 },
} as const;
