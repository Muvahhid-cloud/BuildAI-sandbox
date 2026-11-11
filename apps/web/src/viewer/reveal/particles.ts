// GPU objects of the build reveal: one Points object (one draw call) for the cloud, the flight
// and the sparkle; a dark veil; the glowing sweep sheet. Created and disposed by the React
// components in this folder. Nothing here is pickable and nothing carries an elementId.
import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Color,
  DoubleSide,
  Mesh,
  NormalBlending,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  Vector3,
} from "three";

import { REVEAL } from "../render-settings";

const NO_RAYCAST = () => undefined;

const VERTEX = /* glsl */ `
  attribute vec4 aSeed;
  uniform float uTime;
  uniform vec3 uCenter;
  uniform float uRadius;
  uniform float uFlatten;
  uniform float uAssemble;   // seconds since the assembly started; < 0 while waiting
  uniform float uFly;
  uniform float uStagger;
  uniform float uJitter;
  uniform float uMinZ;
  uniform float uMaxZ;
  uniform float uSweepZ;
  uniform float uFadeBand;
  uniform float uBurst;
  uniform float uDensity;
  uniform float uSize;
  uniform float uScale;      // pixels per meter at distance 1 (perspective) or per meter (ortho)
  uniform float uOrtho;
  uniform float uSparkle;    // 1: twinkle in place (changed elements)
  uniform float uSparkleLen;
  varying float vAlpha;
  varying float vMix;
  varying float vCore;

  void main() {
    // Cloud: a flattened, slowly swirling ball; inner particles turn faster.
    float r = uRadius * (0.3 + 0.7 * pow(aSeed.x, 0.6)) * (1.0 + 0.35 * uBurst * (0.4 + aSeed.w));
    float theta = aSeed.y * 6.2831853 + uTime * (0.18 + 0.5 * (1.0 - aSeed.x));
    float cosPhi = 2.0 * aSeed.z - 1.0;
    float sinPhi = sqrt(max(0.0, 1.0 - cosPhi * cosPhi));
    vec3 cloud = uCenter + vec3(
      r * sinPhi * cos(theta),
      r * sinPhi * sin(theta),
      r * cosPhi * uFlatten + sin(uTime * 0.7 + aSeed.w * 6.2831853) * 0.06 * uRadius
    );

    float height = clamp((position.z - uMinZ) / max(uMaxZ - uMinZ, 0.001), 0.0, 1.0);
    float delay = height * uStagger + aSeed.w * uJitter;
    float k = uAssemble < 0.0 ? 0.0 : clamp((uAssemble - delay) / uFly, 0.0, 1.0);
    float ease = 1.0 - pow(1.0 - k, 3.0);
    vec3 pos = mix(cloud, position, ease);
    // A slight spiral on the way in.
    float swing = sin(3.1415927 * k) * 0.18 * uRadius * (aSeed.x - 0.5);
    pos.xy += vec2(-sin(theta), cos(theta)) * swing;

    float twinkle = 0.62 + 0.38 * sin(uTime * (2.5 + aSeed.z * 5.0) + aSeed.y * 40.0);
    float star = step(0.965, fract(aSeed.x * 91.7 + aSeed.w * 13.3)); // a few larger sparkles
    float alpha = twinkle * (0.55 + 0.45 * star);
    float size = uSize * (0.55 + 0.9 * aSeed.w) * (1.0 + 1.6 * star) * mix(1.0, 0.6, ease);

    if (uSparkle > 0.5) {
      float t = clamp(uAssemble / uSparkleLen, 0.0, 1.0);
      float life = clamp((t - aSeed.x * 0.45) / 0.55, 0.0, 1.0);
      pos = position + vec3(aSeed.x - 0.5, aSeed.y - 0.5, 0.4 + aSeed.z) * 0.22 * life;
      alpha = sin(3.1415927 * life) * (0.5 + 0.5 * twinkle);
      size = uSize * (0.8 + 1.4 * aSeed.w) * (1.0 + 1.2 * star);
      vCore = 1.0;
    } else {
      // Waiting: stages add density. Assembly: every particle takes part.
      float shown = uAssemble < 0.0 ? step(fract(aSeed.x * 7.13 + aSeed.y * 3.7), uDensity) : 1.0;
      alpha *= shown * (1.0 + 0.9 * uBurst);
      // Once landed: glow at the sweep edge, fade below it (the real mesh is there now).
      float d = position.z - uSweepZ;
      float landed = step(0.999, k);
      float below = 1.0 - smoothstep(-uFadeBand, 0.0, d);
      float edge = exp(-abs(d) * 5.0);
      alpha *= mix(1.0, (1.0 - below), landed);
      alpha += landed * edge * 0.9;
      size *= 1.0 + landed * edge * 0.8;
      vCore = 0.35 + 0.65 * max(star, landed * edge);
    }

    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = max(1.0, size * uScale * mix(1.0 / max(-mv.z, 0.001), 1.0, uOrtho));
    vAlpha = alpha;
    vMix = aSeed.y;
  }
`;

const FRAGMENT = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform vec3 uColorC;
  uniform float uOpacity;
  varying float vAlpha;
  varying float vMix;
  varying float vCore;

  void main() {
    vec2 p = gl_PointCoord - 0.5;
    float d2 = dot(p, p);
    if (d2 > 0.25) discard;
    float glow = exp(-d2 * 14.0);          // soft halo
    float core = exp(-d2 * 90.0);          // bright centre
    vec3 color = mix(uColorA, uColorB, vMix);
    color = mix(color, uColorC, core * vCore);
    float a = (glow * 0.55 + core * 0.9) * vAlpha * uOpacity;
    gl_FragColor = vec4(color * a, a);
  }
`;

/** Per-frame values of the particle shader (see the uniforms of the same names). */
export interface ParticleFrame {
  time?: number;
  assemble?: number;
  sweepZ?: number;
  opacity?: number;
  burst?: number;
  density?: number;
  /** Pixels per meter at distance 1 (perspective) or per meter (orthographic). */
  scale?: number;
  ortho?: boolean;
}

/** Fixed values for one run of the effect. */
export interface ParticleSetup {
  center?: [number, number, number];
  radius?: number;
  minZ?: number;
  maxZ?: number;
  size?: number;
  sparkle?: boolean;
}

export interface RevealParticles {
  points: Points<BufferGeometry, ShaderMaterial>;
  setup: (values: ParticleSetup) => void;
  update: (frame: ParticleFrame) => void;
  dispose: () => void;
}

/**
 * `targets`: xyz per particle in model space (the surface points; zeros for the waiting cloud).
 * `seeds`: four numbers per particle. The particle count is capped at REVEAL.maxParticles.
 */
export function createRevealParticles(targets: Float32Array, seeds: Float32Array): RevealParticles {
  const count = Math.min(Math.floor(targets.length / 3), REVEAL.maxParticles);
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(targets.subarray(0, count * 3), 3));
  geometry.setAttribute("aSeed", new BufferAttribute(seeds.subarray(0, count * 4), 4));
  const material = new ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    depthWrite: false,
    depthTest: true,
    blending: AdditiveBlending,
    premultipliedAlpha: true,
    toneMapped: false,
    uniforms: {
      uTime: { value: 0 },
      uCenter: { value: new Vector3() },
      uRadius: { value: 5 },
      uFlatten: { value: REVEAL.cloudFlatten },
      uAssemble: { value: -1 },
      uFly: { value: REVEAL.fly },
      uStagger: { value: REVEAL.stagger },
      uJitter: { value: REVEAL.jitter },
      uMinZ: { value: 0 },
      uMaxZ: { value: 1 },
      uSweepZ: { value: -1e6 },
      uFadeBand: { value: REVEAL.fadeBand },
      uBurst: { value: 0 },
      uDensity: { value: 1 },
      uSize: { value: REVEAL.pointSize },
      uScale: { value: 800 },
      uOrtho: { value: 0 },
      uSparkle: { value: 0 },
      uSparkleLen: { value: REVEAL.sparkle.duration },
      uOpacity: { value: 1 },
      uColorA: { value: new Color(REVEAL.colors.a) },
      uColorB: { value: new Color(REVEAL.colors.b) },
      uColorC: { value: new Color(REVEAL.colors.c) },
    },
  });
  const points = new Points(geometry, material);
  points.name = "reveal-particles";
  points.frustumCulled = false; // positions move in the shader
  points.renderOrder = 1000;
  points.raycast = NO_RAYCAST;
  const u = material.uniforms;
  const set = (name: string, value: number | undefined) => {
    if (value !== undefined) u[name]!.value = value;
  };
  return {
    points,
    setup: (v) => {
      if (v.center) (u.uCenter!.value as Vector3).set(...v.center);
      set("uRadius", v.radius);
      set("uMinZ", v.minZ);
      set("uMaxZ", v.maxZ);
      set("uSize", v.size);
      if (v.sparkle !== undefined) u.uSparkle!.value = v.sparkle ? 1 : 0;
    },
    update: (f) => {
      set("uTime", f.time);
      set("uAssemble", f.assemble);
      set("uSweepZ", f.sweepZ);
      set("uOpacity", f.opacity);
      set("uBurst", f.burst);
      set("uDensity", f.density);
      set("uScale", f.scale);
      if (f.ortho !== undefined) u.uOrtho!.value = f.ortho ? 1 : 0;
    },
    dispose: () => {
      geometry.dispose();
      material.dispose();
    },
  };
}

export interface RevealBackdrop {
  veil: Mesh<BufferGeometry, ShaderMaterial>;
  sheet: Mesh<PlaneGeometry, ShaderMaterial>;
  /** Size and plan centre of the sweep sheet (meters; a 1 m grid is drawn on it). */
  place: (width: number, depth: number, x: number, y: number) => void;
  update: (frame: { veil: number; sheet: number; sweepZ: number }) => void;
  dispose: () => void;
}

/**
 * The veil darkens the whole frame behind the particles (a screen-space triangle, no depth);
 * the sheet is a horizontal glowing plate at the sweep height (model space, depth-tested, so it
 * meets the walls in a bright line).
 */
export function createRevealBackdrop(): RevealBackdrop {
  const veilGeometry = new BufferGeometry();
  veilGeometry.setAttribute(
    "position",
    new BufferAttribute(new Float32Array([-1, -1, 0, 3, -1, 0, -1, 3, 0]), 3),
  );
  const veil = new Mesh(
    veilGeometry,
    new ShaderMaterial({
      vertexShader: "void main() { gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader:
        "uniform vec3 uColor; uniform float uOpacity; void main() { gl_FragColor = vec4(uColor, uOpacity); }",
      uniforms: { uColor: { value: new Color(REVEAL.veilColor) }, uOpacity: { value: 0 } },
      transparent: true,
      depthTest: false,
      depthWrite: false,
      blending: NormalBlending,
      toneMapped: false,
    }),
  );
  veil.name = "reveal-veil";
  veil.frustumCulled = false;
  veil.renderOrder = 998;
  veil.raycast = NO_RAYCAST;

  const sheet = new Mesh(
    new PlaneGeometry(1, 1),
    new ShaderMaterial({
      vertexShader:
        "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: /* glsl */ `
        uniform vec3 uColor;
        uniform float uOpacity;
        uniform vec2 uSize;
        varying vec2 vUv;
        void main() {
          vec2 c = abs(vUv - 0.5) * 2.0;
          float fade = (1.0 - smoothstep(0.55, 1.0, c.x)) * (1.0 - smoothstep(0.55, 1.0, c.y));
          vec2 g = abs(fract(vUv * uSize) - 0.5);
          float grid = 1.0 - smoothstep(0.0, 0.04, min(g.x, g.y));
          float a = (0.10 + 0.22 * grid) * fade * uOpacity;
          gl_FragColor = vec4(uColor * a, a);
        }
      `,
      uniforms: {
        uColor: { value: new Color(REVEAL.colors.edge) },
        uOpacity: { value: 0 },
        uSize: { value: [10, 10] },
      },
      transparent: true,
      depthTest: true,
      depthWrite: false,
      side: DoubleSide,
      blending: AdditiveBlending,
      premultipliedAlpha: true,
      toneMapped: false,
    }),
  );
  sheet.name = "reveal-sheet";
  sheet.renderOrder = 999;
  sheet.raycast = NO_RAYCAST;
  return {
    veil,
    sheet,
    place: (width, depth, x, y) => {
      sheet.scale.set(width, depth, 1);
      sheet.position.set(x, y, 0);
      sheet.material.uniforms.uSize!.value = [width, depth];
    },
    update: (f) => {
      veil.material.uniforms.uOpacity!.value = f.veil;
      sheet.material.uniforms.uOpacity!.value = f.sheet;
      sheet.position.z = f.sweepZ;
    },
    dispose: () => {
      veilGeometry.dispose();
      veil.material.dispose();
      sheet.geometry.dispose();
      sheet.material.dispose();
    },
  };
}
