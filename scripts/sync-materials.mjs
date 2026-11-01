// Copies the material assets (data/materials/{textures,hdri}) to apps/web/public/materials so
// Next.js serves them at /materials/... (MATERIAL_ASSET_BASE). The copy is git-ignored;
// data/materials is the only source. Runs before `dev` and `build` of the web app. It also
// writes manifest.json (the files present), so the viewer never requests a missing texture.
import { cpSync, existsSync, mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const source = join(root, "data", "materials");
const target = join(root, "apps", "web", "public", "materials");

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
for (const dir of ["textures", "hdri"]) {
  const from = join(source, dir);
  if (!existsSync(from)) continue;
  cpSync(from, join(target, dir), { recursive: true });
}
const files = [];
const walk = (dir) => {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) walk(path);
    else files.push(relative(target, path).split(sep).join("/"));
  }
};
walk(target);
files.sort();
writeFileSync(join(target, "manifest.json"), `${JSON.stringify({ files }, null, 2)}\n`);
console.log(`[sync-materials] ${files.length} material asset file(s) -> apps/web/public/materials`);
