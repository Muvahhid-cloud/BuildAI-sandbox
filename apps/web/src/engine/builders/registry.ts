import type { BuildingElement, ElementOfType, ElementType } from "../model/types";
import { buildFloor } from "./floor";
import { buildFurniture } from "./furniture";
import { buildDoor, buildWindow } from "./openings";
import { buildRailing } from "./railing";
import { buildRoof } from "./roof";
import { buildSlab } from "./slab";
import { buildStair } from "./stair";
import type { BuildContext, RenderDescriptor } from "./types";
import { buildWall } from "./wall";

type Builder<T extends ElementType> = (
  el: ElementOfType<T>,
  ctx: BuildContext,
) => RenderDescriptor[];

/** One geometry builder per element type. Adding a type requires adding its builder here. */
export const BUILDERS: { [T in ElementType]: Builder<T> } = {
  wall: buildWall,
  door: buildDoor,
  window: buildWindow,
  room: buildFloor,
  slab: buildSlab,
  stair: buildStair,
  roof: buildRoof,
  railing: buildRailing,
  furniture: buildFurniture,
};

export function buildElement(el: BuildingElement, ctx: BuildContext): RenderDescriptor[] {
  return (BUILDERS[el.type] as Builder<typeof el.type>)(el as never, ctx);
}
