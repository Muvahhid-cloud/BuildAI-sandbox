// Camera presets, computed in MODEL space from the scene bounds and the model itself.
// The viewer converts poses to world space with modelToWorld (math/coords.ts).
import type { Box3 } from "three";

import type { XYZ } from "../math/coords";
import { bbox, type P2 } from "../math/polygon";
import type { ModelIndex } from "../model/model-index";
import type { Room } from "../model/types";

export type CameraPresetId = "exterior" | "front" | "rear" | "top" | "interior" | `level:${string}`;

export interface CameraPose {
  position: XYZ;
  target: XYZ;
  /** Level filter the preset implies (null = leave the current filter unchanged). */
  levelFilter: string | null;
}

export const EYE_HEIGHT = 1.6;

export function cameraPose(preset: CameraPresetId, bounds: Box3, index: ModelIndex): CameraPose {
  const { min, max } = bounds;
  const cx = (min.x + max.x) / 2;
  const cy = (min.y + max.y) / 2;
  const size = Math.max(max.x - min.x, max.y - min.y, max.z - min.z, 1);
  const midZ = (min.z + max.z) / 2;

  switch (preset) {
    case "exterior":
      return pose([cx + 0.95 * size, cy - 1.25 * size, midZ + 0.75 * size], [cx, cy, midZ * 0.7]);
    case "front": // street side = south (-y)
      return pose([cx, min.y - 1.6 * size, midZ + 0.2 * size], [cx, cy, midZ]);
    case "rear":
      return pose([cx, max.y + 1.6 * size, midZ + 0.2 * size], [cx, cy, midZ]);
    case "top": // tiny y offset keeps orbit controls away from the pole singularity
      return pose([cx, cy - 0.01, max.z + 2.2 * size], [cx, cy, min.z]);
    case "interior":
      return interiorPose(index, [cx, cy]);
    default: {
      const level = index.levelsById.get(preset.slice("level:".length));
      if (!level) return pose([cx + size, cy - size, midZ + size], [cx, cy, midZ]);
      const z = level.elevation + 1;
      return {
        ...pose([cx + 0.55 * size, cy - 0.95 * size, z + 1.15 * size], [cx, cy, z]),
        levelFilter: level.id,
      };
    }
  }
}

function pose(position: [number, number, number], target: [number, number, number]): CameraPose {
  const [x, y, z] = position;
  const [tx, ty, tz] = target;
  return { position: { x, y, z }, target: { x: tx, y: ty, z: tz }, levelFilter: null };
}

/**
 * Stand in a corner of the main living space (the lowest-level living room) at eye height,
 * looking diagonally across it. Isolates that level so daylight reaches the interior.
 */
function interiorPose(index: ModelIndex, fallback: P2): CameraPose {
  const rooms = index.levels.flatMap((l) =>
    (index.elementsByLevel.get(l.id) ?? []).filter((e): e is Room => e.type === "room"),
  );
  const living = rooms.find((r) => r.properties.room_type === "living") ?? rooms[0];
  if (!living)
    return pose([fallback[0], fallback[1], EYE_HEIGHT], [fallback[0] + 1, fallback[1], EYE_HEIGHT]);
  const level = index.levelsById.get(living.level_id ?? "");
  const z = (level?.elevation ?? 0) + EYE_HEIGHT;
  const b = bbox(
    living.properties.boundary.map((p) => [p.x + living.position.x, p.y + living.position.y] as P2),
  );
  return {
    position: { x: b.minX + 0.7, y: b.minY + 0.6, z },
    target: { x: b.maxX + 1.5, y: b.maxY - 0.6, z: z - 0.35 },
    levelFilter: level?.id ?? null,
  };
}
