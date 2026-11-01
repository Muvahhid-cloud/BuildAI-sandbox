// Installs the browser texture loader on the shared MaterialCache before any viewer material is
// created (imported by ElementMesh). Tests and the plan view never load textures.
import { createBrowserTextureSource } from "@/engine/materials/browser-textures";
import { materialCache } from "@/engine/materials/material-cache";

if (typeof window !== "undefined" && !materialCache.hasTextureSource) {
  materialCache.setTextureSource(createBrowserTextureSource());
}
