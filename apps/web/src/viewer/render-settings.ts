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
  /** Fallback fill when the HDRI is unavailable. */
  fallbackHemisphere: { sky: "#f4f7fb", ground: "#a89c8a", intensity: 1.1 },
  /** Neutral sky gradient (sRGB, not tone mapped). */
  sky: { zenith: "#9dbbd6", horizon: "#e4ebf0" },
  contactShadow: { opacity: 0.5, blur: 2.4, far: 3.5, resolution: 1024 },
  /** N8AO: world-space radius (m), falloff and strength. */
  ao: { radius: 0.9, distanceFalloff: 1.0, intensity: 4 },
} as const;
