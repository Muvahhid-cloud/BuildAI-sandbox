// Copies the material assets (data/materials/{textures,hdri}) to apps/web/public/materials so
// Next.js serves them at /materials/... (MATERIAL_ASSET_BASE). The copy is git-ignored;
// data/materials is the only source. Runs before `dev` and `build` of the web app.
import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "data", "materials");
const target = join(root, "apps", "web", "public", "materials");

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
let copied = 0;
for (const dir of ["textures", "hdri"]) {
  const from = join(source, dir);
  if (!existsSync(from)) continue;
  cpSync(from, join(target, dir), { recursive: true });
  copied += 1;
}
console.log(
  `[sync-materials] ${copied ? "copied" : "no"} material assets -> apps/web/public/materials`,
);
