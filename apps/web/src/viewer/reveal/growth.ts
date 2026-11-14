// A growing element: a stand-in for its real meshes that is revealed from the bottom up by a
// horizontal clipping plane (the growing front). The real mesh, its materials, userData and
// React props are untouched — it only waits on the hidden camera layer (gate.ts) and takes
// over, pixel for pixel, when the front has reached the top.
//
// - The stand-in uses copies of the element's real materials (same textures, roughness, glass)
//   with one local clipping plane, also applied to its shadow, so the shadow grows with it.
// - The cut is closed: where the element's back faces can be seen (only through the cut — a
//   stencil mask records exactly those pixels), the cut surface itself is drawn: shaded as a
//   horizontal face in the material's colour, with the depth of the cut plane (gl_FragDepth).
//   So a wall is never hollow or see-through while it grows, and ambient occlusion sees a
//   solid top.
// - A faint line of the material's own tone, brightened, runs along the growing edge.
//
// Nothing here is pickable and nothing carries an elementId.
import {
  AlwaysStencilFunc,
  BackSide,
  Color,
  DoubleSide,
  EqualStencilFunc,
  Group,
  type Material,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  type Object3D,
  Plane,
  ReplaceStencilOp,
  Vector3,
  ZeroStencilOp,
} from "three";

import type { RenderDescriptor } from "@/engine/builders/types";
import { materialPreset } from "@/engine/materials/library";
import { materialCache, parseMaterialKey } from "@/engine/materials/material-cache";

import { REVEAL } from "../render-settings";

const NO_RAYCAST = () => undefined;
/** Material groups that get no cut surface (glass and other see-through materials). */
const NO_CAP = new MeshBasicMaterial({ visible: false });

/** sRGB hex a material key is drawn in without textures (its library or display colour). */
export function materialHex(key: string): string {
  const { id, color } = parseMaterialKey(key);
  return color ?? materialPreset(id).color;
}

export interface Growth {
  /** Add under the model root rotation (`space: "model"`) or directly to the scene. */
  object: Group;
  space: "model" | "world";
  /** Height of the growing front (model z = world y) and the strength of the edge line. */
  setFront: (z: number, edge: number) => void;
  dispose: () => void;
}

interface Cut {
  /** World-space plane: keeps what lies below the front. */
  plane: Plane;
  height: { value: number };
  edge: { value: number };
  /** Stencil value of this element's cut (1..255): its section is drawn only on its mask. */
  ref: number;
}

let nextRef = 0;

function createCut(): Cut {
  nextRef = (nextRef % 255) + 1;
  return {
    plane: new Plane(new Vector3(0, -1, 0), 0),
    height: { value: 0 },
    edge: { value: 0 },
    ref: nextRef,
  };
}

/** Drawn after every opaque mesh: first the masks of the cuts, then the cut surfaces. */
const MASK_ORDER = 10;
const CAP_ORDER = 11;

/**
 * The mask of a cut: the pixels where a back face of the element is visible. A back face of a
 * closed solid can only be seen through its open cut, so these are exactly the pixels of the
 * section. Writes neither colour nor depth.
 */
function maskMaterial(cut: Cut): MeshBasicMaterial {
  const mask = new MeshBasicMaterial({ side: BackSide, colorWrite: false, depthWrite: false });
  mask.clippingPlanes = [cut.plane];
  mask.stencilWrite = true;
  mask.stencilRef = cut.ref;
  mask.stencilFunc = AlwaysStencilFunc;
  mask.stencilZPass = ReplaceStencilOp;
  return mask;
}

// Height of a fragment below the cut, in view space (the model root only rotates Z-up to Y-up).
const BELOW_CUT = /* glsl */ `
  vec3 cutNormal = normalize(mat3(viewMatrix) * vec3(0.0, 1.0, 0.0));
  vec3 cutPoint = (viewMatrix * vec4(0.0, uCutY, 0.0, 1.0)).xyz;
`;

/**
 * A copy of `source` that is clipped at the cut (shadow included) and shows the edge line.
 * Shares the source's textures; the copy is owned by the growth and disposed with it.
 */
function growMaterial(source: Material, cut: Cut, doubleSided: boolean): Material {
  const copy = source.clone();
  copy.clippingPlanes = [cut.plane];
  copy.clipShadows = true;
  if (doubleSided) copy.side = DoubleSide;
  if (!(copy instanceof MeshStandardMaterial)) return copy;
  copy.onBeforeCompile = (shader) => {
    shader.uniforms.uCutY = cut.height;
    shader.uniforms.uEdgeGain = cut.edge;
    shader.uniforms.uEdgeWidth = { value: REVEAL.growth.edgeWidth };
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        "#include <common>\nuniform float uCutY;\nuniform float uEdgeGain;\nuniform float uEdgeWidth;",
      )
      .replace(
        "#include <color_fragment>",
        // The growing edge: the material's own tone, a little brighter just below the cut.
        `#include <color_fragment>
        {
          ${BELOW_CUT}
          float below = dot(cutNormal, cutPoint + vViewPosition);
          diffuseColor.rgb *= 1.0 + uEdgeGain * (1.0 - smoothstep(0.0, uEdgeWidth, below));
        }`,
      );
  };
  copy.customProgramCacheKey = () => "reveal-grow";
  return copy;
}

/**
 * The cut surface of a solid: drawn on the element's back faces, inside the element's mask,
 * but placed (depth) and lit (normal) as the horizontal section where the view ray crosses the
 * cut plane. The mask is cleared where the section is drawn.
 */
function capMaterial(color: string, cut: Cut): MeshStandardMaterial {
  const cap = new MeshStandardMaterial({
    color: new Color(color),
    roughness: REVEAL.growth.capRoughness,
    metalness: 0,
    side: BackSide,
  });
  cap.clippingPlanes = [cut.plane];
  cap.stencilWrite = true;
  cap.stencilRef = cut.ref;
  cap.stencilFunc = EqualStencilFunc;
  cap.stencilZPass = ZeroStencilOp;
  cap.onBeforeCompile = (shader) => {
    shader.uniforms.uCutY = cut.height;
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        "#include <common>\nuniform float uCutY;\nuniform mat4 projectionMatrix;\nvec3 capNormal;",
      )
      .replace(
        "#include <clipping_planes_fragment>",
        `#include <clipping_planes_fragment>
        {
          ${BELOW_CUT}
          vec3 seen = -vViewPosition;
          vec3 origin = isOrthographic ? vec3(seen.xy, 0.0) : vec3(0.0);
          vec3 ray = seen - origin;
          float slope = dot(cutNormal, ray);
          float hit = dot(cutNormal, cutPoint - origin) / slope;
          if (abs(slope) < 1e-6 || hit <= 0.0 || hit > 1.0) discard;
          vec4 clip = projectionMatrix * vec4(origin + ray * hit, 1.0);
          gl_FragDepth = clamp(clip.z / clip.w * 0.5 + 0.5, 0.0, 1.0);
          capNormal = slope < 0.0 ? cutNormal : -cutNormal;
        }`,
      )
      .replace(
        "#include <normal_fragment_maps>",
        "#include <normal_fragment_maps>\nnormal = capNormal;",
      );
  };
  cap.customProgramCacheKey = () => "reveal-cap";
  return cap;
}

function finish(object: Group, space: Growth["space"], cut: Cut, owned: Material[]): Growth {
  return {
    object,
    space,
    setFront: (z, edge) => {
      cut.plane.constant = z;
      cut.height.value = z;
      cut.edge.value = edge;
    },
    dispose: () => {
      object.removeFromParent();
      owned.forEach((m) => m.dispose());
    },
  };
}

/** The growing stand-in of an element drawn from render descriptors (model space). */
export function createGrowth(parts: readonly RenderDescriptor[]): Growth {
  const cut = createCut();
  const owned: Material[] = [];
  const group = new Group();
  for (const d of parts) {
    const body = d.materials.map((key) => {
      const copy = growMaterial(materialCache.get(key), cut, false);
      owned.push(copy);
      return copy;
    });
    const mesh = new Mesh(d.geometry, body.length === 1 ? body[0] : body);
    mesh.matrixAutoUpdate = false;
    mesh.matrix.copy(d.matrix);
    mesh.castShadow = d.castShadow;
    mesh.receiveShadow = true;
    mesh.renderOrder = d.part === "glass" ? 1 : 0;
    mesh.raycast = NO_RAYCAST;
    group.add(mesh);

    const caps = d.materials.map((key, i) => {
      if (body[i]!.transparent) return NO_CAP;
      const cap = capMaterial(materialHex(key), cut);
      owned.push(cap);
      return cap;
    });
    if (caps.every((c) => c === NO_CAP)) continue;
    const mask = maskMaterial(cut);
    owned.push(mask);
    const masked = new Mesh(d.geometry, mask);
    masked.matrixAutoUpdate = false;
    masked.matrix.copy(d.matrix);
    masked.renderOrder = MASK_ORDER;
    masked.castShadow = false;
    masked.raycast = NO_RAYCAST;
    group.add(masked);
    const section = new Mesh(d.geometry, caps.length === 1 ? caps[0] : caps);
    section.renderOrder = CAP_ORDER;
    section.matrixAutoUpdate = false;
    section.matrix.copy(d.matrix);
    section.castShadow = false;
    section.receiveShadow = false;
    section.raycast = NO_RAYCAST;
    group.add(section);
  }
  return finish(group, "model", cut, owned);
}

/**
 * The growing stand-in of something the viewer draws as an object of its own (a glTF furniture
 * model, the site mesh, a plant): a copy placed by the source's world matrix, with copies of
 * its materials. Such meshes need not be closed, so both sides are drawn instead of a cut
 * surface.
 */
export function createObjectGrowth(source: Object3D): Growth {
  const cut = createCut();
  const owned: Material[] = [];
  source.updateWorldMatrix(true, true);
  const copy = source.clone(true);
  copy.traverse((o) => {
    o.layers.set(0); // the source waits on the hidden layer
    o.userData = {};
    if (!(o instanceof Mesh)) return;
    const list = (Array.isArray(o.material) ? o.material : [o.material]) as Material[];
    const grown = list.map((m) => {
      const g = growMaterial(m, cut, true);
      owned.push(g);
      return g;
    });
    o.material = Array.isArray(o.material) ? grown : grown[0]!;
    o.raycast = NO_RAYCAST;
  });
  copy.matrixAutoUpdate = false;
  copy.matrix.copy(source.matrixWorld);
  const group = new Group();
  group.add(copy);
  return finish(group, "world", cut, owned);
}
