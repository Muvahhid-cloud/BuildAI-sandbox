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
 * Build reveal (docs/3d-engine.md §25): the particle cloud while a design is generated and the
 * assembly into the finished model. Viewer effect only — never part of the BuildingModel.
 * Times in seconds, sizes in meters.
 */
export const REVEAL = {
  /** GPU points, one draw call (waiting cloud and assembly use the same count). */
  particleCount: 40_000,
  /** Hard ceiling (performance budget on integrated GPUs). */
  maxParticles: 50_000,
  /** Whole assembly: fly-in, sweep, fade. */
  duration: 3.6,
  /** One particle's flight from the cloud to its surface point. */
  fly: 1.15,
  /** Extra delay of the top of the building over the bottom (floor by floor). */
  stagger: 0.85,
  /** Per-particle random delay on top of the stagger. */
  jitter: 0.3,
  /** The meshes are revealed bottom-up between these times. */
  sweepStart: 1.45,
  sweepEnd: 3.2,
  /** Particles above the sweep stay; below it they fade over this height. */
  fadeBand: 0.7,
  /** Point radius at rest; sparkles are larger. */
  pointSize: 0.085,
  /** Cloud radius as a share of the building's size, and its vertical flattening. */
  cloudRadius: 0.62,
  cloudFlatten: 0.6,
  /** Share of the particles shown at the first real stage, growing to 1 at the last. */
  minDensity: 0.3,
  /** A real stage change: burst strength and how fast it decays (per second). */
  burst: 1,
  burstDecay: 1.6,
  /** Dark backdrop behind additive particles (waiting canvas and the veil over the scene). */
  veilColor: "#0b0c14",
  veilOpacity: 0.88,
  /** Particle colors: brand indigo, violet, cyan highlight; the sweep edge. */
  colors: { a: "#6d70ff", b: "#b08cff", c: "#7fe3ff", edge: "#9aa0ff" },
  /** After "Apply" in Modify with AI: only the changed elements sparkle. */
  sparkle: { duration: 1.6, particleCount: 6_000 },
} as const;
