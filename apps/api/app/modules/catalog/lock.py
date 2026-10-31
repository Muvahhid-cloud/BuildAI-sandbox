"""Hash lock for knowledge data (`data/knowledge/knowledge.lock.json`).

Every source record, pack directory and region profile has a SHA-256 over its files. The
loader refuses data that does not match the lock, so a knowledge change is always a
deliberate, reviewable act: edit → `pnpm knowledge:lock` → commit data and lock together.
Line endings are normalised to LF, so the digest is identical on Windows and Linux checkouts.

Usage: python -m app.modules.catalog.lock <data_dir>
"""

import hashlib
import json
import sys
from pathlib import Path

from app.modules.building.issues import Issue, pointer

LOCK_FILE = "knowledge.lock.json"
LOCK_VERSION = 1
SOURCES_DIR = "sources"
PACKS_DIR = "packs"
REGIONS_DIR = "regions"


def _normalised(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def digest(root: Path, files: list[Path]) -> str:
    """SHA-256 over (relative path, content) of `files`, in sorted path order."""
    h = hashlib.sha256()
    for rel in sorted(f.relative_to(root).as_posix() for f in files):
        h.update(rel.encode("utf-8") + b"\0")
        h.update(_normalised(root / rel) + b"\0")
    return h.hexdigest()


def _dir_ref(name: str) -> str:
    """`core.v1` / `generic.v1.yaml` → `core@1` / `generic@1` (malformed names kept as-is)."""
    stem = name.removesuffix(".yaml")
    base, _, version = stem.rpartition(".v")
    return f"{base}@{version}" if base and version.isdigit() else stem


def compute_lock(knowledge_dir: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted((knowledge_dir / SOURCES_DIR).glob("*.yaml")):
        entries[f"source:{path.stem}"] = digest(knowledge_dir, [path])
    for pack_dir in sorted(p for p in (knowledge_dir / PACKS_DIR).iterdir() if p.is_dir()):
        files = [f for f in pack_dir.rglob("*") if f.is_file()]
        entries[f"pack:{_dir_ref(pack_dir.name)}"] = digest(knowledge_dir, files)
    for path in sorted((knowledge_dir / REGIONS_DIR).glob("*.yaml")):
        entries[f"region:{_dir_ref(path.name)}"] = digest(knowledge_dir, [path])
    return entries


def render_lock(entries: dict[str, str]) -> str:
    doc = {"lock_version": LOCK_VERSION, "algorithm": "sha256", "entries": entries}
    return json.dumps(doc, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def read_lock(knowledge_dir: Path) -> dict[str, str] | None:
    path = knowledge_dir / LOCK_FILE
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("lock_version") != LOCK_VERSION or doc.get("algorithm") != "sha256":
        return None
    entries = doc.get("entries")
    if not isinstance(entries, dict):
        return None
    return {str(k): str(v) for k, v in entries.items()}


def verify_lock(knowledge_dir: Path) -> list[Issue]:
    locked = read_lock(knowledge_dir)
    if locked is None:
        return [
            Issue(
                severity="error",
                code="KNOWLEDGE_LOCK_MISSING",
                path=pointer(LOCK_FILE),
                message=f"{LOCK_FILE} is missing or unreadable",
                suggestion="Run `pnpm knowledge:lock` after reviewing the knowledge changes.",
            )
        ]
    actual = compute_lock(knowledge_dir)
    issues: list[Issue] = []
    for key in sorted(set(actual) | set(locked)):
        if key not in locked:
            code, message = "KNOWLEDGE_LOCK_UNLISTED", f"{key} is not in the lock"
        elif key not in actual:
            code, message = "KNOWLEDGE_LOCK_ORPHAN", f"{key} is locked but no longer exists"
        elif actual[key] != locked[key]:
            code, message = "KNOWLEDGE_LOCK_STALE", f"{key} changed since it was locked"
        else:
            continue
        issues.append(
            Issue(
                severity="error",
                code=code,
                path=pointer(LOCK_FILE, "entries", key),
                message=message,
                suggestion="Review the change, then run `pnpm knowledge:lock`.",
            )
        )
    return issues


def main() -> None:
    knowledge_dir = Path(sys.argv[1]).resolve() / "knowledge"
    entries = compute_lock(knowledge_dir)
    (knowledge_dir / LOCK_FILE).write_text(render_lock(entries), encoding="utf-8", newline="\n")
    for key, value in entries.items():
        print(f"{value[:12]}  {key}")


if __name__ == "__main__":
    main()
