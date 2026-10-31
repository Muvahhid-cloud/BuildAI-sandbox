#!/usr/bin/env node
// Runs `uv` with the given arguments. Falls back to `python -m uv` / `py -3.12 -m uv`
// when the uv executable is not on PATH (common on Windows with a --user pip install).
import { spawnSync } from "node:child_process";

const args = process.argv.slice(2);
const candidates = [
  ["uv", []],
  ["python3", ["-m", "uv"]],
  ["python", ["-m", "uv"]],
  ...(process.platform === "win32" ? [["py", ["-3.12", "-m", "uv"]]] : []),
];

for (const [cmd, prefix] of candidates) {
  const probe = spawnSync(cmd, [...prefix, "--version"], { stdio: "ignore" });
  if (probe.status !== 0) continue;
  const result = spawnSync(cmd, [...prefix, ...args], { stdio: "inherit" });
  process.exit(result.status ?? 1);
}

console.error("uv not found. Install it: https://docs.astral.sh/uv/ (or `pip install --user uv`).");
process.exit(127);
