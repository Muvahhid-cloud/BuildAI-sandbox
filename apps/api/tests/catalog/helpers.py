import shutil
import tempfile
from collections.abc import Callable
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.modules.building.issues import Issue
from app.modules.building.types import TypeSet
from app.modules.catalog.loader import KnowledgeLoadError, read_knowledge
from app.modules.catalog.registry import KnowledgeRegistry
from app.modules.catalog.resolver import resolve_type_set
from tests.building.helpers import DATA_DIR

BOOK_PACK = "spds-georgievsky-2004@1"
BOOK_DIR = "packs/spds-georgievsky-2004.v1"
CORE_PACK = "core@1"
CORE_DIR = "packs/core.v1"
GENERIC_PACK = "buildai-generic-types@1"
GENERIC_DIR = "packs/buildai-generic-types.v1"
GENERIC_COMPONENTS = f"{GENERIC_DIR}/components.yaml"
DESIGN_PACK = "buildai-design-systems@1"
PATTERN_PACK = "buildai-layout-patterns@1"
DESIGN_DIR = "packs/buildai-design-systems.v1"
DESIGN_COMPONENTS = f"{DESIGN_DIR}/design-systems.yaml"
COMPONENT_KINDS = ("families", "types", "assemblies", "role_mappings", "design_systems")
TEST_REVIEW = {"reviewed_by": "test-suite (temporary copy only)", "reviewed_on": "2026-09-28"}


def copy_data(tmp_path: Path) -> Path:
    """A private copy of the knowledge and rules-profile data to mutate in a test."""
    data = tmp_path / "data"
    shutil.copytree(DATA_DIR / "knowledge", data / "knowledge")
    shutil.copytree(DATA_DIR / "rules-profiles", data / "rules-profiles")
    shutil.copytree(DATA_DIR / "materials", data / "materials")
    return data


def edit_yaml(data: Path, rel: str, change: Callable[[Any], None]) -> None:
    path = data / "knowledge" / rel
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_issues(data: Path, *, verify: bool = False) -> list[Issue]:
    try:
        read_knowledge(data, verify=verify)
    except KnowledgeLoadError as exc:
        return exc.issues
    return []


def codes(issues: list[Issue]) -> set[str]:
    return {i.code for i in issues}


def item(doc: dict[str, Any], item_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(i for i in doc["items"] if i["id"] == item_id)
    return found


def real_registry() -> KnowledgeRegistry:
    return read_knowledge(DATA_DIR)


def approve_components(data: Path, only: set[str] | None = None) -> None:
    """Approve generic component records IN A TEMPORARY COPY (the repository copy stays draft)."""

    edit_yaml(data, GENERIC_COMPONENTS, _approver(only))


def _approver(only: set[str] | None) -> Callable[[Any], None]:
    def approve(doc: dict[str, Any]) -> None:
        for kind in COMPONENT_KINDS:
            for rec in doc.get(kind, []):
                if only is None or rec["id"] in only:
                    rec["status"] = "approved"
                    rec["review"] = dict(TEST_REVIEW)

    return approve


def approve_design_systems(data: Path, only: set[str] | None = None) -> None:
    """Approve the generic components AND the design-system pack records IN A TEMPORARY COPY
    (the repository copies stay draft). `only` limits the design-pack records approved."""
    approve_components(data)
    edit_yaml(data, DESIGN_COMPONENTS, _approver(only))


@cache
def approved_design_registry() -> KnowledgeRegistry:
    """The catalog as it would be once every design system is reviewed (temporary copy)."""
    data = copy_data(Path(tempfile.mkdtemp(prefix="buildai-designs-")))
    approve_design_systems(data)
    return read_knowledge(data, verify=False)


@cache
def approved_generic_type_set() -> TypeSet:
    """The generic type set as it would resolve after approval (temporary copy, cached)."""
    data = copy_data(Path(tempfile.mkdtemp(prefix="buildai-types-")))
    approve_components(data)
    resolution = resolve_type_set(read_knowledge(data, verify=False))
    assert resolution.type_set is not None, resolution.skipped
    return resolution.type_set
