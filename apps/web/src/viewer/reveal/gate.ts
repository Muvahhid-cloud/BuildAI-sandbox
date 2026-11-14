// Which meshes the camera sees during the construction. An element that is not complete yet
// is moved to a camera layer nothing renders or picks (three.js layers): its mesh, materials,
// userData and React props are untouched, and it is not pickable while hidden.
import type { Object3D } from "three";

/** Layer of not-yet-built objects: no camera, shadow pass or raycaster looks at it. */
export const HIDDEN_LAYER = 31;
const HIDDEN_MASK = (1 << HIDDEN_LAYER) | 0;

/** Site paving and fence (one mesh, not a model element). */
export const SITE_KEY = "site";
/** A plant of the site plan. */
export const plantKey = (kind: string, slot: number) => `site:${kind}:${slot}`;

/** userData of an object that is drawn for a reveal key without being an element mesh. */
export function revealTag(key: string): { revealKey: string } {
  return { revealKey: key };
}

function keyOf(object: Object3D, inherited: string | null): string | null {
  const data = object.userData as { elementId?: unknown; revealKey?: unknown };
  if (typeof data.elementId === "string") return data.elementId;
  if (typeof data.revealKey === "string") return data.revealKey;
  return inherited;
}

/**
 * Hides every object whose key (its element id, or the reveal key of an ancestor) `hidden`
 * says is not built yet, and shows the rest of the keyed objects. Objects without a key are
 * left alone. Objects the viewer draws for a reveal key of their own (tagged: a loaded glTF
 * model, the site mesh, a plant) are collected in `tagged` by key.
 */
export function gateScene(
  root: Object3D,
  hidden: (key: string) => boolean,
  tagged?: Map<string, Object3D>,
  inherited: string | null = null,
): void {
  const key = keyOf(root, inherited);
  if (key !== null) {
    if (tagged && typeof (root.userData as { revealKey?: unknown }).revealKey === "string") {
      tagged.set(key, root);
    }
    if (hidden(key)) root.layers.mask = HIDDEN_MASK;
    else if (root.layers.mask === HIDDEN_MASK) root.layers.set(0);
  }
  for (const child of root.children) gateScene(child, hidden, tagged, key);
}

/** Shows everything the gate has hidden. */
export function ungateScene(root: Object3D): void {
  root.traverse((o) => {
    if (o.layers.mask === HIDDEN_MASK) o.layers.set(0);
  });
}
