// Camera path of the build reveal: a slow orbit that ends exactly on a given pose (the default
// exterior view). Pure, model space (Z-up); the viewer converts with modelToWorld.
import type { XYZ } from "@/engine/math/coords";

export interface OrbitPose {
  position: XYZ;
  target: XYZ;
}

export interface OrbitConfig {
  /** Angle travelled around the vertical axis through the target (radians). */
  sweep: number;
  /** Distance at the start as a multiple of the final distance. */
  distance: number;
  /** Extra height at the start as a share of the final height above the target. */
  lift: number;
}

/** Smooth in and out, with zero speed at both ends. */
export function easeInOut(x: number): number {
  const t = Math.min(Math.max(x, 0), 1);
  return t * t * t * (t * (6 * t - 15) + 10);
}

/**
 * The camera at `progress` (0 = start of the build, 1 = its end): `end` turned back around the
 * target's vertical axis, a little further out and higher, easing into `end` itself at 1.
 */
export function orbitPose(end: OrbitPose, progress: number, cfg: OrbitConfig): OrbitPose {
  const left = 1 - easeInOut(progress);
  const angle = -cfg.sweep * left;
  const scale = 1 + (cfg.distance - 1) * left;
  const dx = end.position.x - end.target.x;
  const dy = end.position.y - end.target.y;
  const dz = end.position.z - end.target.z;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);
  return {
    position: {
      x: end.target.x + (dx * cos - dy * sin) * scale,
      y: end.target.y + (dx * sin + dy * cos) * scale,
      z: end.target.z + dz * scale * (1 + cfg.lift * left),
    },
    target: { ...end.target },
  };
}
