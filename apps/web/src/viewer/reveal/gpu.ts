// GPU objects of the construction, created and disposed by RevealLayer: the pieces (instanced,
// one draw call per library material, drawn with that material), the blueprint lines with the
// paper sheet under them, and the drafting sheet shown while the backend works. Nothing here
// is pickable and nothing carries an elementId. Growing elements: growth.ts.
import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  Group,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  Mesh,
  MeshDepthMaterial,
  type MeshStandardMaterial,
  PlaneGeometry,
  ShaderChunk,
  ShaderMaterial,
} from "three";

import { materialCache } from "@/engine/materials/material-cache";

import { REVEAL } from "../render-settings";
import type { BlueprintPlan } from "./blueprint";
import type { PieceTargets } from "./pieces";

const NO_RAYCAST = () => undefined;

// The same arithmetic as pieces.ts `pieceState` (tests cover that one).
const PIECE_VERTEX_PARS = /* glsl */ `
  attribute vec3 aTarget;
  attribute vec4 aQuat;
  attribute vec3 aScale;
  attribute vec2 aPieceUv;
  attribute float aFront;    // the moment the growing front reaches the piece
  attribute float aSeed;
  uniform float uTime;
  uniform float uSettle;
  uniform float uApproach;
  uniform float uDrop;
  uniform float uAbsorb;
  uniform float uEarly;
  vec3 pieceRotate(vec3 v) {
    return v + 2.0 * cross(aQuat.xyz, cross(aQuat.xyz, v) + aQuat.w * v);
  }
`;

const PIECE_BEGIN_VERTEX = /* glsl */ `
  float pieceAppear = aFront - aSeed * uEarly - uSettle;
  float pieceK = clamp((uTime - pieceAppear) / uSettle, 0.0, 1.0);
  float pieceEase = 1.0 - pow(1.0 - pieceK, 3.0);               // ease-out: settles into place
  float pieceAlive = step(pieceAppear, uTime)
    * (1.0 - smoothstep(aFront, aFront + uAbsorb, uTime));      // gone once the front has passed
  float pieceIn = smoothstep(0.0, 0.35, pieceK) * pieceAlive;
  vec3 pieceNormal = pieceRotate(vec3(0.0, 0.0, 1.0));
  // From just above and outside (model space is Z-up), then the last centimeters pressed in.
  vec3 pieceFrom = normalize(pieceNormal * 0.55 + vec3(0.0, 0.0, 0.85));
  vec3 pieceOffset = pieceFrom * uApproach * (1.0 - pieceEase)
    + pieceNormal * uDrop * (1.0 - smoothstep(0.7, 1.0, pieceK));
  vec3 pieceSize = aScale * vec3(pieceIn, pieceIn, pieceIn * pieceAlive);
  vec3 transformed = aTarget + pieceOffset + pieceRotate(position * pieceSize);
`;

// The slice continues the surface's texture: its UVs are the surface's own meter coordinates.
const PIECE_UV_VERTEX =
  "vec2 pieceUv = aPieceUv + position.xy * aScale.xy;\n" +
  ShaderChunk.uv_vertex.replace(/\b[A-Z0-9_]*MAP_UV\b/g, "pieceUv");

export interface RevealPieces {
  /** One instanced mesh per library material. */
  group: Group;
  /** Draw calls of the pieces (= materials in use). */
  batches: number;
  /** Seconds since the assembly started. */
  update: (elapsed: number) => void;
  dispose: () => void;
}

/**
 * The pieces: thin slices, instanced. Each run of pieces of one library material is one mesh
 * (one draw call) drawn with a copy of that material — the same colour, textures, roughness
 * and glass as the finished element — whose vertex stage places the slice from per-piece
 * attributes and one time uniform. They receive and cast shadows like the building.
 */
export function createRevealPieces(pieces: PieceTargets, front: Float32Array): RevealPieces {
  const p = REVEAL.pieces;
  const box = new BoxGeometry(1, 1, 1);
  const uniforms = {
    uTime: { value: 0 },
    uSettle: { value: p.settle },
    uApproach: { value: p.approach },
    uDrop: { value: p.settleDrop },
    uAbsorb: { value: p.absorb },
    uEarly: { value: p.early },
  };
  const patchVertex = (shader: { uniforms: object; vertexShader: string }) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\n${PIECE_VERTEX_PARS}`)
      .replace("#include <uv_vertex>", PIECE_UV_VERTEX)
      .replace("#include <beginnormal_vertex>", "vec3 objectNormal = pieceRotate(normal);")
      .replace("#include <begin_vertex>", PIECE_BEGIN_VERTEX);
  };
  // Shadow pass: the same placement, so a slice casts its own small shadow.
  const depth = new MeshDepthMaterial();
  depth.onBeforeCompile = patchVertex;
  depth.customProgramCacheKey = () => "reveal-pieces-depth";

  const group = new Group();
  group.name = "reveal-pieces";
  const geometries: InstancedBufferGeometry[] = [];
  const materials: { source: MeshStandardMaterial; copy: MeshStandardMaterial }[] = [];
  for (const batch of pieces.batches) {
    if (batch.count === 0) continue;
    const geometry = new InstancedBufferGeometry();
    geometry.setIndex(box.getIndex());
    geometry.setAttribute("position", box.getAttribute("position"));
    geometry.setAttribute("normal", box.getAttribute("normal"));
    geometry.setAttribute("uv", box.getAttribute("uv"));
    const slice = (array: Float32Array, size: number) =>
      new InstancedBufferAttribute(
        array.subarray(batch.offset * size, (batch.offset + batch.count) * size),
        size,
      );
    geometry.setAttribute("aTarget", slice(pieces.target, 3));
    geometry.setAttribute("aQuat", slice(pieces.quat, 4));
    geometry.setAttribute("aScale", slice(pieces.scale, 3));
    geometry.setAttribute("aPieceUv", slice(pieces.uv, 2));
    geometry.setAttribute("aSeed", slice(pieces.seed, 1));
    geometry.setAttribute("aFront", slice(front, 1));
    geometry.instanceCount = batch.count;
    geometries.push(geometry);

    const source = materialCache.get(batch.material);
    const copy = source.clone();
    copy.onBeforeCompile = patchVertex;
    copy.customProgramCacheKey = () => "reveal-pieces";
    materials.push({ source, copy });

    const mesh = new Mesh(geometry, copy);
    mesh.frustumCulled = false; // positions are computed in the shader
    mesh.raycast = NO_RAYCAST;
    mesh.castShadow = !copy.transparent;
    mesh.receiveShadow = true;
    mesh.customDepthMaterial = depth;
    group.add(mesh);
  }
  return {
    group,
    batches: geometries.length,
    update: (elapsed) => {
      uniforms.uTime.value = elapsed;
      // A texture that finished loading meanwhile reaches the copy too.
      for (const { source, copy } of materials) syncMaterial(source, copy);
    },
    dispose: () => {
      geometries.forEach((g) => g.dispose());
      materials.forEach((m) => m.copy.dispose());
      depth.dispose();
      box.dispose();
    },
  };
}

/** Keeps a copied library material in step with its source's maps (they load lazily). */
export function syncMaterial(source: MeshStandardMaterial, copy: MeshStandardMaterial): void {
  if (
    copy.map === source.map &&
    copy.normalMap === source.normalMap &&
    copy.roughnessMap === source.roughnessMap
  ) {
    return;
  }
  copy.map = source.map;
  copy.normalMap = source.normalMap;
  copy.roughnessMap = source.roughnessMap;
  copy.color.copy(source.color);
  copy.needsUpdate = true;
}

export interface RevealBlueprint {
  lines: Mesh<BufferGeometry, ShaderMaterial>;
  sheet: Mesh<PlaneGeometry, ShaderMaterial>;
  update: (frame: { progress: number; lines: number; sheet: number }) => void;
  dispose: () => void;
}

/**
 * The plan as thin flat ribbons (model space, at the plan's height) that appear along the
 * drawing progress, with a brighter pen tip; and a pale paper sheet with a faint grid on the
 * ground under the building (`rect`: min x, min y, max x, max y; `groundZ`: its height).
 */
export function createRevealBlueprint(
  plan: BlueprintPlan,
  rect: [number, number, number, number],
  groundZ: number,
): RevealBlueprint {
  const b = REVEAL.blueprint;
  const position = new Float32Array(plan.segments.length * 18);
  const along = new Float32Array(plan.segments.length * 6);
  const half = b.lineWidth / 2;
  const z = plan.z + b.lift;
  plan.segments.forEach((s, i) => {
    const len = Math.hypot(s.bx - s.ax, s.by - s.ay) || 1;
    const ux = (s.bx - s.ax) / len;
    const uy = (s.by - s.ay) / len;
    // Ends extended by half a width so corners close.
    const ax = s.ax - ux * half;
    const ay = s.ay - uy * half;
    const bx = s.bx + ux * half;
    const by = s.by + uy * half;
    const nx = -uy * half;
    const ny = ux * half;
    const corners = [
      [ax + nx, ay + ny, s.from],
      [ax - nx, ay - ny, s.from],
      [bx - nx, by - ny, s.to],
      [bx + nx, by + ny, s.to],
    ] as const;
    [0, 1, 2, 0, 2, 3].forEach((c, k) => {
      position.set([corners[c]![0], corners[c]![1], z], i * 18 + k * 3);
      along[i * 6 + k] = corners[c]![2];
    });
  });
  const lineGeometry = new BufferGeometry();
  lineGeometry.setAttribute("position", new BufferAttribute(position, 3));
  lineGeometry.setAttribute("aAlong", new BufferAttribute(along, 1));
  const lines = new Mesh(
    lineGeometry,
    new ShaderMaterial({
      vertexShader: /* glsl */ `
        attribute float aAlong;
        varying float vAlong;
        void main() {
          vAlong = aAlong;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uColor;
        uniform float uProgress;
        uniform float uOpacity;
        varying float vAlong;
        void main() {
          if (vAlong > uProgress) discard;
          // The pen tip: brighter just behind the drawing front, until the plan is complete.
          float tip = (1.0 - smoothstep(0.0, 0.035, uProgress - vAlong)) * step(uProgress, 0.999);
          gl_FragColor = vec4(mix(uColor, vec3(1.0), tip * 0.6), uOpacity);
          #include <colorspace_fragment>
        }
      `,
      uniforms: {
        uColor: { value: new Color(b.line) },
        uProgress: { value: 0 },
        uOpacity: { value: 0 },
      },
      transparent: true,
      depthWrite: false,
      side: DoubleSide,
      polygonOffset: true,
      polygonOffsetFactor: -2,
      polygonOffsetUnits: -2,
      toneMapped: false,
    }),
  );
  lines.name = "reveal-blueprint";
  lines.frustumCulled = false;
  lines.renderOrder = 3;
  lines.raycast = NO_RAYCAST;

  const [minX, minY, maxX, maxY] = rect;
  const width = maxX - minX;
  const depth = maxY - minY;
  const sheet = new Mesh(
    new PlaneGeometry(1, 1),
    new ShaderMaterial({
      vertexShader: /* glsl */ `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uPaper;
        uniform vec3 uLine;
        uniform float uOpacity;
        uniform vec2 uCells;     // sheet size in grid cells
        varying vec2 vUv;
        void main() {
          // Soft edges: the sheet dissolves into the ground.
          vec2 edge = min(vUv, 1.0 - vUv) * uCells;
          float fade = smoothstep(0.0, 2.5, min(edge.x, edge.y));
          vec2 cell = vUv * uCells;
          vec2 g = abs(fract(cell - 0.5) - 0.5) / max(fwidth(cell), vec2(1e-5));
          float grid = 1.0 - min(min(g.x, g.y), 1.0);
          vec3 color = mix(uPaper, uLine, grid * 0.22);
          gl_FragColor = vec4(color, uOpacity * fade);
          #include <colorspace_fragment>
        }
      `,
      uniforms: {
        uPaper: { value: new Color(b.sheet) },
        uLine: { value: new Color(b.line) },
        uOpacity: { value: 0 },
        uCells: { value: [width / b.grid, depth / b.grid] },
      },
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
      toneMapped: false,
    }),
  );
  sheet.name = "reveal-sheet";
  sheet.scale.set(width, depth, 1);
  sheet.position.set((minX + maxX) / 2, (minY + maxY) / 2, groundZ);
  sheet.renderOrder = 2;
  sheet.raycast = NO_RAYCAST;

  return {
    lines,
    sheet,
    update: (f) => {
      lines.material.uniforms.uProgress!.value = f.progress;
      lines.material.uniforms.uOpacity!.value = f.lines;
      sheet.material.uniforms.uOpacity!.value = f.sheet * b.sheetOpacity;
      lines.visible = f.lines > 0.001;
      sheet.visible = f.sheet > 0.001;
    },
    dispose: () => {
      lineGeometry.dispose();
      lines.material.dispose();
      sheet.geometry.dispose();
      sheet.material.dispose();
    },
  };
}

export interface WaitingSheet {
  mesh: Mesh<PlaneGeometry, ShaderMaterial>;
  update: (frame: {
    opacity: number;
    /** Position of the scanning line across the sheet, -1..1. */
    scan: number;
    pulse: number;
    /** Half size of the plot outline (0 = not known yet) and its opacity. */
    plot: readonly [number, number];
    plotOpacity: number;
  }) => void;
  dispose: () => void;
}

/**
 * The drafting sheet on the ground while the backend works: pale paper that dissolves into the
 * site, a 1 m grid, a slow scanning line and — once the floor area is known — the outline of
 * the plot. One quad with a small shader, centred on `center` (model x, y) at height `z`.
 */
export function createWaitingSheet(center: readonly [number, number], z: number): WaitingSheet {
  const w = REVEAL.waiting;
  const uniforms = {
    uLine: { value: new Color(w.line) },
    uPaper: { value: new Color(w.paper) },
    uPaperOpacity: { value: w.paperOpacity },
    uCell: { value: w.grid },
    uGrid: { value: w.gridOpacity },
    uReach: { value: w.reach },
    uScan: { value: 0.75 },
    uScanOpacity: { value: w.scanOpacity },
    uPulse: { value: 0 },
    uOpacity: { value: 0 },
    uPlot: { value: [0, 0] as [number, number] },
    uPlotOpacity: { value: 0 },
  };
  const mesh = new Mesh(
    new PlaneGeometry(w.reach * 2, w.reach * 2),
    new ShaderMaterial({
      vertexShader: /* glsl */ `
        varying vec2 vPlan;
        void main() {
          vPlan = position.xy;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: /* glsl */ `
        uniform vec3 uLine;
        uniform vec3 uPaper;
        uniform float uPaperOpacity;
        uniform float uCell;
        uniform float uGrid;
        uniform float uReach;
        uniform float uScan;
        uniform float uScanOpacity;
        uniform float uPulse;
        uniform float uOpacity;
        uniform vec2 uPlot;
        uniform float uPlotOpacity;
        varying vec2 vPlan;
        void main() {
          vec2 cell = vPlan / uCell;
          vec2 w = max(fwidth(cell), vec2(1e-5));
          vec2 g = abs(fract(cell - 0.5) - 0.5) / w;
          float minor = 1.0 - min(min(g.x, g.y), 1.0);
          vec2 g5 = abs(fract(cell / 5.0 - 0.5) - 0.5) / (w / 5.0);
          float major = 1.0 - min(min(g5.x, g5.y), 1.0);
          // The sheet dissolves into the ground towards its edge.
          float fade = 1.0 - smoothstep(0.3, 1.0, length(vPlan) / uReach);
          // The scanning line travels across the sheet; the grid glows softly in its wake.
          float d = vPlan.y - uScan * uReach;
          float line = 1.0 - smoothstep(0.0, 0.04 + fwidth(vPlan.y) * 1.5, abs(d));
          float wake = exp(-max(d, 0.0) * 0.3) * step(0.0, d);
          float grid = max(minor * 0.5, major);
          float ink = grid * uGrid * (1.0 + wake * (1.2 + 3.0 * uPulse))
            + line * uScanOpacity * (1.0 + uPulse)
            + wake * 0.05;
          // The plot outline: a thin rectangle with soft corners marks.
          vec2 q = abs(vPlan) - uPlot;
          float box = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
          float aa = max(fwidth(box), 1e-4);
          float outline = (1.0 - smoothstep(0.03, 0.03 + aa * 1.5, abs(box))) * uPlotOpacity;
          float inside = (1.0 - smoothstep(-aa, aa, box)) * uPlotOpacity * 0.06;
          ink = clamp(ink + outline + inside, 0.0, 1.0);
          float paper = uPaperOpacity * fade;
          vec3 color = mix(uPaper, uLine, ink);
          gl_FragColor = vec4(color, clamp(paper + ink * fade, 0.0, 1.0) * uOpacity);
          #include <colorspace_fragment>
        }
      `,
      transparent: true,
      depthWrite: false,
      polygonOffset: true,
      polygonOffsetFactor: -1,
      polygonOffsetUnits: -1,
      toneMapped: false,
      uniforms,
    }),
  );
  mesh.name = "reveal-waiting";
  mesh.position.set(center[0], center[1], z);
  mesh.renderOrder = 2;
  mesh.raycast = NO_RAYCAST;
  mesh.visible = false;
  return {
    mesh,
    update: (f) => {
      uniforms.uOpacity.value = f.opacity;
      uniforms.uScan.value = f.scan;
      uniforms.uPulse.value = f.pulse;
      uniforms.uPlot.value = [f.plot[0], f.plot[1]];
      uniforms.uPlotOpacity.value = f.plotOpacity;
      mesh.visible = f.opacity > 0.002;
    },
    dispose: () => {
      mesh.geometry.dispose();
      mesh.material.dispose();
    },
  };
}
