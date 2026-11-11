// GPU objects of the build reveal, created and disposed by RevealLayer: the pieces (one
// instanced mesh = one draw call), the blueprint lines and the paper sheet under them. Nothing
// here is pickable and nothing carries an elementId.
import {
  BoxGeometry,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  IcosahedronGeometry,
  InstancedBufferAttribute,
  InstancedBufferGeometry,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
  ShaderMaterial,
} from "three";

import { REVEAL } from "../render-settings";
import type { BlueprintPlan } from "./blueprint";
import type { PieceMotion, PieceTargets } from "./pieces";

const NO_RAYCAST = () => undefined;

const PIECE_VERTEX_PARS = /* glsl */ `
  attribute vec3 aTarget;
  attribute vec3 aStart;
  attribute vec4 aQuat;
  attribute vec3 aScale;
  attribute vec3 aColor;
  attribute vec3 aTime;      // departure, arrival, start of the shrink
  uniform float uTime;
  uniform float uGrow;
  uniform float uShrink;
  varying vec3 vPieceColor;
  varying float vPieceMoving;
  vec3 pieceRotate(vec3 v) {
    return v + 2.0 * cross(aQuat.xyz, cross(aQuat.xyz, v) + aQuat.w * v);
  }
`;

const PIECE_BEGIN_VERTEX = /* glsl */ `
  float pieceK = clamp((uTime - aTime.x) / max(aTime.y - aTime.x, 0.0001), 0.0, 1.0);
  float pieceEase = 1.0 - pow(1.0 - pieceK, 3.0);            // ease-out: settles into place
  float pieceSize = smoothstep(0.0, uGrow, uTime - aTime.x)    // grows as it leaves the base
    * (1.0 - smoothstep(aTime.z, aTime.z + uShrink, uTime));   // shrinks once the mesh is there
  vec3 transformed = mix(aStart, aTarget, pieceEase) + pieceRotate(position * aScale * pieceSize);
  vPieceMoving = 1.0 - smoothstep(0.72, 1.0, pieceK);
  vPieceColor = aColor;
`;

export interface RevealPieces {
  mesh: Mesh<InstancedBufferGeometry, MeshStandardMaterial>;
  /** Seconds since the assembly started. */
  update: (elapsed: number) => void;
  dispose: () => void;
}

/**
 * All pieces as one instanced mesh. Position, size and color are computed in the vertex shader
 * from per-piece attributes and the time, so a frame costs one uniform. Lit like the building
 * (standard material: sun, HDRI, fog, tone mapping, section cut); casts no shadow.
 */
export function createRevealPieces(pieces: PieceTargets, motion: PieceMotion): RevealPieces {
  const box = new BoxGeometry(1, 1, 1);
  const geometry = new InstancedBufferGeometry();
  geometry.setIndex(box.getIndex());
  geometry.setAttribute("position", box.getAttribute("position"));
  geometry.setAttribute("normal", box.getAttribute("normal"));
  geometry.setAttribute("uv", box.getAttribute("uv"));
  geometry.setAttribute("aTarget", new InstancedBufferAttribute(pieces.target, 3));
  geometry.setAttribute("aStart", new InstancedBufferAttribute(motion.start, 3));
  geometry.setAttribute("aQuat", new InstancedBufferAttribute(pieces.quat, 4));
  geometry.setAttribute("aScale", new InstancedBufferAttribute(pieces.scale, 3));
  geometry.setAttribute("aColor", new InstancedBufferAttribute(pieces.color, 3));
  geometry.setAttribute("aTime", new InstancedBufferAttribute(motion.time, 3));
  geometry.instanceCount = pieces.count;

  const uniforms = {
    uTime: { value: 0 },
    uGrow: { value: REVEAL.grow },
    uShrink: { value: REVEAL.schedule.shrink },
    uAccent: { value: new Color(REVEAL.accent) },
    uGlow: { value: REVEAL.glow },
  };
  const material = new MeshStandardMaterial({ roughness: REVEAL.roughness, metalness: 0 });
  material.onBeforeCompile = (shader) => {
    Object.assign(shader.uniforms, uniforms);
    shader.vertexShader = shader.vertexShader
      .replace("#include <common>", `#include <common>\n${PIECE_VERTEX_PARS}`)
      .replace("#include <beginnormal_vertex>", "vec3 objectNormal = pieceRotate(normal);")
      .replace("#include <begin_vertex>", PIECE_BEGIN_VERTEX);
    shader.fragmentShader = shader.fragmentShader
      .replace(
        "#include <common>",
        "#include <common>\nuniform vec3 uAccent;\nuniform float uGlow;\nvarying vec3 vPieceColor;\nvarying float vPieceMoving;",
      )
      .replace(
        "#include <color_fragment>",
        // Accent while it moves, the element's own color as it lands.
        "#include <color_fragment>\ndiffuseColor.rgb = mix(vPieceColor, uAccent, vPieceMoving);",
      )
      .replace(
        "#include <emissivemap_fragment>",
        "#include <emissivemap_fragment>\ntotalEmissiveRadiance += uAccent * (vPieceMoving * uGlow);",
      );
  };
  material.customProgramCacheKey = () => "reveal-pieces";

  const mesh = new Mesh(geometry, material);
  mesh.name = "reveal-pieces";
  mesh.frustumCulled = false; // positions are computed in the shader
  mesh.raycast = NO_RAYCAST;
  mesh.castShadow = false;
  mesh.receiveShadow = false;
  return {
    mesh,
    update: (elapsed) => {
      uniforms.uTime.value = elapsed;
    },
    dispose: () => {
      geometry.dispose();
      box.dispose();
      material.dispose();
    },
  };
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

/**
 * A plant's stand-in for sampling pieces (plants are drawn by glTF models that are not part of
 * the scene's descriptors): a low crown of the plant's height. Unit size; scaled by a matrix.
 */
export function plantProxyGeometry(): BufferGeometry {
  // Model space is Z-up: the crown sits on z = 0 and is 1 high.
  return new IcosahedronGeometry(0.5, 1).translate(0, 0, 0.5);
}
