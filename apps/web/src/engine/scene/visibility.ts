// Pure visibility rules: floor isolation, layers and inspection (cutaway) toggles.
import type { ModelIndex } from "../model/model-index";
import type { BuildingElement, Layer } from "../model/types";

export type LevelFilter = "all" | string; // "all" or a level id

export interface VisibilityState {
  levelFilter: LevelFilter;
  layers: Readonly<Record<Layer, boolean>>;
  showRoof: boolean;
  showExteriorWalls: boolean;
}

/** visible = normal; ghost = faint context, not pickable; hidden = not drawn. */
export type VisibilityMode = "visible" | "ghost" | "hidden";

function isOnExteriorWall(el: BuildingElement, index: ModelIndex): boolean {
  if (el.type === "wall") return el.properties.wall_kind === "exterior";
  if (el.type === "door" || el.type === "window") {
    return index.hostOf.get(el.id)?.properties.wall_kind === "exterior";
  }
  return false;
}

export function elementVisibility(
  el: BuildingElement,
  index: ModelIndex,
  state: VisibilityState,
): VisibilityMode {
  if (!state.layers[el.layer]) return "hidden";
  if (el.type === "roof" && (!state.showRoof || state.levelFilter !== "all")) return "hidden";
  if (!state.showExteriorWalls && isOnExteriorWall(el, index)) return "hidden";
  if (el.type === "door" || el.type === "window") {
    // Openings follow their host wall (no floating windows when a wall's layer is off).
    const host = index.hostOf.get(el.id);
    if (host && elementVisibility(host, index, state) === "hidden") return "hidden";
  }
  if (state.levelFilter === "all" || el.level_id === null) return "visible";

  const active = index.levelsById.get(state.levelFilter);
  const own = index.levelsById.get(el.level_id);
  if (!active || !own) return "visible";
  if (own.index === active.index) return "visible";
  return own.index < active.index ? "ghost" : "hidden";
}

export function visibilityMap(
  index: ModelIndex,
  state: VisibilityState,
): Map<string, VisibilityMode> {
  return new Map(index.model.elements.map((el) => [el.id, elementVisibility(el, index, state)]));
}
