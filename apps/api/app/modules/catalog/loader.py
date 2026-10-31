"""Load knowledge from `data/knowledge/` (docs/knowledge.md §4).

    data/knowledge/
      knowledge.lock.json             SHA-256 per source, pack and region (lock.py)
      sources/<source-id>.yaml        one Source record each
      packs/<pack-id>.v<n>/pack.yaml  PackManifest + the files it lists
      regions/<region-id>.v<n>.yaml   RegionProfile

Loading validates every document (Pydantic), runs the integrity checks and verifies the hash
lock; any error raises `KnowledgeLoadError` with all issues. Packs are immutable once used:
changes go into a new `.v<n>` directory.
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.modules.building.issues import Issue, errors, pointer
from app.modules.catalog.components import ComponentsDocument
from app.modules.catalog.integrity import check_registry
from app.modules.catalog.lock import PACKS_DIR, REGIONS_DIR, SOURCES_DIR, verify_lock
from app.modules.catalog.patterns_schema import PatternsDocument
from app.modules.catalog.provenance import Source
from app.modules.catalog.registry import KnowledgeRegistry, LoadedPack
from app.modules.catalog.schemas import (
    DrawingProfilesDocument,
    GlossaryDocument,
    ItemsDocument,
    OntologyDocument,
    PackManifest,
    RegionProfile,
)

KNOWLEDGE_DIR = Path("knowledge")
RULES_PROFILES_DIR = Path("rules-profiles")
MANIFEST = "pack.yaml"
MATERIAL_LIBRARY = Path("materials") / "library.json"
_RULES_FILE = re.compile(r"^(?P<id>[a-z][a-z0-9-]*)\.v(?P<version>[1-9][0-9]*)\.yaml$")


class KnowledgeLoadError(ValueError):
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = issues
        lines = [f"{i.code} {i.path}: {i.message}" for i in issues[:20]]
        more = f"\n… and {len(issues) - 20} more" if len(issues) > 20 else ""
        super().__init__("Invalid knowledge data:\n" + "\n".join(lines) + more)


def _yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _parse[M: BaseModel](model: type[M], path: Path, rel: str, issues: list[Issue]) -> M | None:
    try:
        return model.model_validate(_yaml(path))
    except yaml.YAMLError as exc:
        issues.append(
            Issue(severity="error", code="KNOWLEDGE_YAML", path=pointer(rel), message=str(exc))
        )
    except ValidationError as exc:
        for err in exc.errors():
            loc = [str(p) for p in err["loc"]]
            issues.append(
                Issue(
                    severity="error",
                    code="KNOWLEDGE_SCHEMA",
                    path=pointer(rel, *loc),
                    message=err["msg"],
                )
            )
    return None


def _load_pack(knowledge_dir: Path, pack_dir: Path, issues: list[Issue]) -> LoadedPack | None:
    rel_dir = pack_dir.relative_to(knowledge_dir).as_posix()
    manifest = _parse(PackManifest, pack_dir / MANIFEST, f"{rel_dir}/{MANIFEST}", issues)
    if manifest is None:
        return None
    c = manifest.contents
    listed = {MANIFEST, *c.files()}
    missing = sorted(n for n in listed if not (pack_dir / n).is_file())
    for name in missing:
        issues.append(
            Issue(
                severity="error",
                code="PACK_FILE_MISSING",
                path=pointer(rel_dir, name),
                message=f"{name} is listed in {manifest.ref}'s manifest but does not exist",
            )
        )
    if missing:
        return None
    items, classes, rels, terms, localized, profiles = [], [], [], [], [], []
    for name in c.items:
        doc = _parse(ItemsDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        items += [(name, i) for i in doc.items] if doc else []
    for name in c.ontology:
        onto = _parse(OntologyDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        if onto:
            classes += onto.classes
            rels += onto.relationships
    for name in c.glossary:
        gloss = _parse(GlossaryDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        if gloss:
            terms += gloss.terms
            localized += gloss.localized
    for name in c.drawing_profiles:
        dp = _parse(DrawingProfilesDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        profiles += dp.profiles if dp else []
    families, types, assemblies, mappings, designs = [], [], [], [], []
    for name in c.components:
        comp = _parse(ComponentsDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        if comp:
            families += comp.families
            types += comp.types
            assemblies += comp.assemblies
            mappings += comp.role_mappings
            designs += comp.design_systems
    patterns = []
    for name in c.patterns:
        pat = _parse(PatternsDocument, pack_dir / name, f"{rel_dir}/{name}", issues)
        patterns += pat.patterns if pat else []
    present = {f.relative_to(pack_dir).as_posix() for f in pack_dir.rglob("*") if f.is_file()}
    return LoadedPack(
        manifest=manifest,
        directory=rel_dir,
        items=tuple(items),
        classes=tuple(classes),
        relationships=tuple(rels),
        terms=tuple(terms),
        localized=tuple(localized),
        drawing_profiles=tuple(profiles),
        families=tuple(families),
        types=tuple(types),
        assemblies=tuple(assemblies),
        role_mappings=tuple(mappings),
        design_systems=tuple(designs),
        patterns=tuple(patterns),
        extra_files=tuple(sorted(present - listed)),
    )


def known_rules_profiles(data_dir: Path) -> frozenset[str]:
    refs = set()
    for path in (data_dir / RULES_PROFILES_DIR).glob("*.yaml"):
        match = _RULES_FILE.match(path.name)
        if match:
            refs.add(f"{match['id']}@{match['version']}")
    return frozenset(refs)


def known_materials(data_dir: Path) -> frozenset[str] | None:
    """Material ids of the shared library (data/materials/library.json), if present."""
    path = data_dir / MATERIAL_LIBRARY
    if not path.is_file():
        return None
    doc = json.loads(path.read_text(encoding="utf-8"))
    return frozenset(str(m["id"]) for m in doc.get("materials", []))


def read_knowledge(data_dir: Path, *, verify: bool = True) -> KnowledgeRegistry:
    """Load and check all knowledge under `data_dir/knowledge` (uncached)."""
    knowledge_dir = data_dir / KNOWLEDGE_DIR
    issues: list[Issue] = []
    sources: dict[str, Source] = {}
    for path in sorted((knowledge_dir / SOURCES_DIR).glob("*.yaml")):
        rel = path.relative_to(knowledge_dir).as_posix()
        source = _parse(Source, path, rel, issues)
        if source is None:
            continue
        if source.id != path.stem:
            issues.append(
                Issue(
                    severity="error",
                    code="SOURCE_FILE_MISMATCH",
                    path=pointer(rel),
                    message=f"file {path.name} declares source {source.id}",
                )
            )
        sources[source.id] = source
    packs: dict[str, LoadedPack] = {}
    for pack_dir in sorted(p for p in (knowledge_dir / PACKS_DIR).iterdir() if p.is_dir()):
        pack = _load_pack(knowledge_dir, pack_dir, issues)
        if pack is None:
            continue
        if pack.ref in packs:
            issues.append(
                Issue(
                    severity="error",
                    code="DUPLICATE_ID",
                    path=pointer("packs", pack.ref),
                    message=f"pack {pack.ref} defined twice",
                )
            )
        packs[pack.ref] = pack
    regions: dict[str, RegionProfile] = {}
    for path in sorted((knowledge_dir / REGIONS_DIR).glob("*.yaml")):
        rel = path.relative_to(knowledge_dir).as_posix()
        region = _parse(RegionProfile, path, rel, issues)
        if region is None:
            continue
        if path.name != f"{region.id}.v{region.version}.yaml":
            issues.append(
                Issue(
                    severity="error",
                    code="REGION_FILE_MISMATCH",
                    path=pointer(rel),
                    message=f"file {path.name} declares region {region.ref}",
                )
            )
        regions[region.ref] = region
    registry = KnowledgeRegistry(sources=sources, packs=packs, regions=regions)
    if not issues:
        issues += check_registry(
            registry,
            known_rules_profiles=known_rules_profiles(data_dir),
            known_materials=known_materials(data_dir),
        )
    if verify:
        issues += verify_lock(knowledge_dir)
    if errors(issues):
        raise KnowledgeLoadError(errors(issues))
    return registry


@lru_cache
def load_knowledge(data_dir: Path) -> KnowledgeRegistry:
    """Cached, lock-verified knowledge for `data_dir` (one load per process)."""
    return read_knowledge(data_dir, verify=True)
