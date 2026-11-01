// One THREE material per (material key, variant), created lazily and shared by every mesh.
//
// Materials come only from the library (data/materials/library.json). A preset with `textures`
// gets PBR maps (albedo, normal, roughness) from a TextureSource; the flat library color stays
// in place until a map has actually loaded, and remains the fallback if it never does. Texture
// repeat = 1 / tile_size_m because the mesh builders generate UVs in meters.
import {
  type ColorSpace,
  Color,
  FrontSide,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  NoColorSpace,
  RepeatWrapping,
  SRGBColorSpace,
  type Texture,
} from "three";

import { MATERIAL_PRESETS, type MaterialPreset, materialPreset } from "./library";

export type MaterialVariant = "default" | "selected" | "ghost";
export type TextureSlot = "albedo" | "normal" | "roughness";

/**
 * Loads texture files (paths relative to data/materials). `onLoad` is called once the image is
 * available; a missing or failing file never calls it, so the material keeps its flat color.
 * The engine stays free of I/O: the viewer injects a browser loader, tests inject fakes.
 */
export interface TextureSource {
  load(path: string, onLoad: (texture: Texture) => void): Texture | null;
}

const SELECTION_EMISSIVE = new Color("#2f6fed");
const HEX = /^#[0-9a-f]{6}$/;
const DEFAULT_TINT = "#ffffff";
/** Anisotropic filtering for grazing views of floors and facades (clamped by the GPU). */
const ANISOTROPY = 8;

/**
 * Material key of a face drawn in a display color (K3 appearance intent): the library preset
 * `id` with only its color replaced ("exterior_wall@#e8c547"). Roughness, metalness and the
 * material id itself are unchanged — a color is appearance, never a different material.
 */
export function coloredMaterialKey(id: string, color: string | null | undefined): string {
  return color && HEX.test(color) ? `${id}@${color}` : id;
}

export function parseMaterialKey(key: string): { id: string; color: string | null } {
  const at = key.lastIndexOf("@");
  if (at > 0 && HEX.test(key.slice(at + 1)))
    return { id: key.slice(0, at), color: key.slice(at + 1) };
  return { id: key, color: null };
}

/** Texture repeat for a tile size in meters (UVs are in meters: 1 UV unit = 1 m). */
export function textureRepeat(tileSizeM: readonly [number, number]): [number, number] {
  return [1 / tileSizeM[0], 1 / tileSizeM[1]];
}

/** Color space of a texture slot: albedo is sRGB, data maps are linear. */
export function slotColorSpace(slot: TextureSlot): ColorSpace {
  return slot === "albedo" ? SRGBColorSpace : NoColorSpace;
}

export class MaterialCache {
  private readonly materials = new Map<string, MeshStandardMaterial>();
  private readonly textures = new Map<string, TextureEntry>();
  private readonly missing = new Set<string>();
  private readonly listeners = new Set<() => void>();
  private source: TextureSource | null;

  constructor(source: TextureSource | null = null) {
    this.source = source;
  }

  /** Set (or remove) the texture loader. Existing materials are recreated on next `get`. */
  setTextureSource(source: TextureSource | null): void {
    if (source === this.source) return;
    this.dispose();
    this.source = source;
  }

  get hasTextureSource(): boolean {
    return this.source !== null;
  }

  get(id: string, variant: MaterialVariant = "default"): MeshStandardMaterial {
    const key = `${id}|${variant}`;
    let material = this.materials.get(key);
    if (!material) {
      material = this.create(id, variant);
      this.materials.set(key, material);
    }
    return material;
  }

  /** Called whenever a texture finishes loading (the viewer re-renders on demand). */
  onChange(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Material ids requested by geometry that are not in the library. */
  get missingIds(): string[] {
    return [...this.missing].sort();
  }

  get size(): number {
    return this.materials.size;
  }

  get textureCount(): number {
    return this.textures.size;
  }

  dispose(): void {
    for (const m of this.materials.values()) m.dispose();
    for (const t of this.textures.values()) t.texture.dispose();
    this.materials.clear();
    this.textures.clear();
    this.missing.clear();
  }

  private create(key: string, variant: MaterialVariant): MeshStandardMaterial {
    const { id, color } = parseMaterialKey(key);
    if (!MATERIAL_PRESETS.has(id)) this.missing.add(id);
    const p = materialPreset(id);
    const opacity = p.opacity ?? 1;
    const params = {
      name: `${key}:${variant}`,
      color: new Color(color ?? p.color),
      roughness: p.roughness,
      metalness: p.metalness,
      side: FrontSide,
      transparent: opacity < 1,
      opacity,
      depthWrite: opacity >= 1,
      envMapIntensity: p.env_intensity ?? 1,
    };
    const material =
      p.shading === "glass"
        ? new MeshPhysicalMaterial({
            ...params,
            // Reflective, slightly tinted glazing without a transmission pass (cheap): the
            // environment map supplies reflections, opacity lets the interior show through.
            ior: 1.5,
            specularIntensity: 1,
            clearcoat: 0.6,
            clearcoatRoughness: 0.05,
            envMapIntensity: p.env_intensity ?? 1.6,
          })
        : new MeshStandardMaterial(params);
    if (variant !== "ghost") this.applyTextures(material, p, color);
    if (variant === "selected") {
      material.emissive = SELECTION_EMISSIVE;
      material.emissiveIntensity = 0.45;
    } else if (variant === "ghost") {
      material.transparent = true;
      material.opacity = Math.min(opacity, 0.12);
      material.depthWrite = false;
    }
    return material;
  }

  private applyTextures(
    material: MeshStandardMaterial,
    preset: MaterialPreset,
    displayColor: string | null,
  ): void {
    const t = preset.textures;
    if (!t || !this.source) return;
    const repeat = textureRepeat(t.tile_size_m);
    const slots: [TextureSlot, string | undefined][] = [
      ["albedo", t.albedo],
      ["normal", t.normal],
      ["roughness", t.roughness],
    ];
    for (const [slot, path] of slots) {
      if (!path) continue;
      this.texture(path, slot, repeat, (texture) => {
        if (slot === "albedo") {
          material.map = texture;
          // With a map the flat color would darken it twice: use the tint (or display color).
          material.color.set(displayColor ?? t.tint ?? DEFAULT_TINT);
        } else if (slot === "normal") {
          material.normalMap = texture;
        } else {
          material.roughnessMap = texture;
        }
        material.needsUpdate = true;
        this.emit();
      });
    }
  }

  /** One shared texture per (file, repeat); `apply` runs as soon as the image is available. */
  private texture(
    path: string,
    slot: TextureSlot,
    repeat: [number, number],
    apply: (texture: Texture) => void,
  ): void {
    const key = textureKey(path, repeat);
    const entry = this.textures.get(key);
    if (entry) {
      if (entry.loaded) apply(entry.texture);
      else entry.waiters.push(apply);
      return;
    }
    const pending: TextureEntry = { texture: null!, loaded: false, waiters: [apply] };
    const texture = this.source!.load(path, (loaded) => {
      pending.loaded = true;
      loaded.needsUpdate = true;
      const waiters = pending.waiters;
      pending.waiters = [];
      for (const fn of waiters) fn(loaded);
    });
    if (!texture) return; // flat color stays
    pending.texture = texture;
    texture.wrapS = RepeatWrapping;
    texture.wrapT = RepeatWrapping;
    texture.repeat.set(repeat[0], repeat[1]);
    texture.anisotropy = ANISOTROPY;
    texture.colorSpace = slotColorSpace(slot);
    this.textures.set(key, pending);
  }

  private emit(): void {
    for (const l of this.listeners) l();
  }
}

interface TextureEntry {
  texture: Texture;
  loaded: boolean;
  waiters: ((texture: Texture) => void)[];
}

function textureKey(path: string, repeat: [number, number]): string {
  return `${path}|${repeat[0]}x${repeat[1]}`;
}

/** App-wide cache: materials are reused across meshes and scene rebuilds. */
export const materialCache = new MaterialCache();
