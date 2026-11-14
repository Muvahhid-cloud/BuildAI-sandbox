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
 * Live creation and construction of the model (docs/3d-engine.md §25). Every constant of the
 * effect lives here; the effect itself only in viewer/reveal.
 */
export const REVEAL = {
  /** Thin slices that settle on an element's surfaces at its growing front (reveal/pieces.ts). */
  pieces: {
    /** Hard ceiling of the piece count (instanced; one draw call per library material). */
    maxPieces: 16000,
    /** Fewest pieces an element gets, so small elements are visibly built too. */
    minPerItem: 4,
    /** Largest share of a surface that pieces cover (courses being laid, not a closed skin). */
    fill: 0.6,
    /** A slice at full size: long (horizontal) × short × thick, meters. */
    length: 0.36,
    height: 0.22,
    thickness: 0.035,
    /** Scaled to the element: `perRootArea × √(surface)`, within [minScale, 1]. */
    perRootArea: 0.14,
    minScale: 0.42,
    /** Share of its cell a slice fills (the rest is the joint). */
    joint: 0.94,
    /** A slice comes from this far above and outside its place (meters)… */
    approach: 0.5,
    /** …in this time (ease-out), pressing the last centimeters into place. */
    settle: 0.3,
    settleDrop: 0.025,
    /** Once the front has passed, the slice sinks into the surface over this time. */
    absorb: 0.09,
    /** A slice is in place up to this long before the front reaches it (irregular rhythm). */
    early: 0.06,
  },
  /** Timing of the construction (reveal/order.ts scheduleConstruction). */
  schedule: {
    /** The plan draws itself on the ground before the first element starts. */
    lead: 1.1,
    /** Whole build: minDuration + secondsPerElement × elements, at most maxDuration. */
    minDuration: 6,
    maxDuration: 10,
    secondsPerElement: 0.02,
    /** An element grows bottom to top in height × growPerMeter seconds, within [min, max]. */
    growPerMeter: 0.42,
    minGrow: 0.8,
    maxGrow: 1.7,
    /** Relative time between the start of an element of each stage and the next element. */
    stageWeight: {
      slab: 3,
      floor: 0.5,
      exterior_wall: 3,
      interior_wall: 1.5,
      opening: 0.6,
      stair: 2,
      roof: 4,
      canopy: 2,
      balcony: 1.2,
      furniture: 0.45,
      site: 1.5,
    },
    /** Extra pause between two groups (same units as the weights). */
    groupGap: 1.5,
  },
  /**
   * Share of the piece budget per stage: walls and roofs read as the building, so they are
   * laid densely; small details and layers that end up covered get fewer pieces.
   */
  stageDensity: {
    slab: 0.5,
    floor: 0.25,
    exterior_wall: 1,
    interior_wall: 0.8,
    opening: 0.5,
    stair: 0.8,
    roof: 0.85,
    canopy: 0.8,
    balcony: 0.7,
    furniture: 0.5,
    site: 0.3,
  },
  /** The growing front of an element (reveal/growth.ts). */
  growth: {
    /** The cut rises this far past the element's top, so the edge line leaves it cleanly. */
    overshoot: 0.02,
    /** Highlight along the growing edge: the material's own tone, brightened by this share… */
    edgeGain: 0.16,
    /** …within this distance below the cut (meters), fading out near the end of the growth. */
    edgeWidth: 0.045,
    edgeFadeOut: 0.18,
    /** Roughness of the cut surface (a fresh, matte section in the material's colour). */
    capRoughness: 0.92,
  },
  /** The plan that draws itself on the ground, and the paper sheet under it. */
  blueprint: {
    draw: 1.1,
    settle: 0.9,
    trace: 0.3,
    out: 1.4,
    line: "#4f4ee0",
    lineWidth: 0.05,
    /** Height of the lines above the storey's floor level. */
    lift: 0.03,
    sheet: "#f3f5fb",
    sheetOpacity: 0.42,
    /** Sheet margin around the building and its grid spacing. */
    margin: 2.5,
    grid: 1,
  },
  /** Camera: a slow dolly and orbit that ends exactly on the default exterior view. */
  camera: {
    /** Angle travelled around the building (radians). */
    sweep: 1.05,
    /** Distance and extra height at the start, relative to the final view. */
    distance: 1.14,
    lift: 0.1,
    /** Blend from the camera's pose when the build starts (seconds, ease-in-out). */
    blend: 1.6,
  },
  /** While the backend works: the drafting sheet on the ground (reveal/WaitingGround). */
  waiting: {
    line: "#4f4ee0",
    paper: "#f6f7fc",
    paperOpacity: 0.86,
    /** Grid spacing, opacity of its lines and how far the sheet reaches (meters). */
    grid: 1,
    gridOpacity: 0.34,
    reach: 28,
    /** One pass of the scanning line over the sheet. */
    scanPeriod: 6.5,
    scanOpacity: 0.55,
    /** A real stage change: one brighter pass that decays at this rate (per second). */
    pulse: 0.5,
    pulseDecay: 0.9,
    /** Fade of the sheet when waiting starts and when the model arrives (per second). */
    fade: 3.2,
    /** The plot outline once the floor area is known: footprint proportion and margin. */
    plotAspect: 1.3,
    plotMargin: 3,
    plotOpacity: 0.7,
    /** The view while there is no model yet (model space, meters). */
    bounds: { width: 14, depth: 11, height: 6.5 },
  },
  /** A stage failed after the house was shown: the canvas fades out, then shows the ground. */
  fail: { fade: 0.7 },
  /** After "Apply" in Modify with AI: only the changed elements grow again. */
  changes: { duration: 2.4 },
} as const;
