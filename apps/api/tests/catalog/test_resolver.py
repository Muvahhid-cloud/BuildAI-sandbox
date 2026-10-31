"""Type-set resolution: approved records only, deterministic, never substituted (K2)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

import yaml

from app.modules.building.types import TYPE_ROLES
from app.modules.catalog.components import ComponentsDocument
from app.modules.catalog.loader import read_knowledge
from app.modules.catalog.registry import KnowledgeRegistry
from app.modules.catalog.resolver import record_sha256, resolve_type_set
from tests.catalog.helpers import (
    BOOK_DIR,
    GENERIC_COMPONENTS,
    GENERIC_PACK,
    TEST_REVIEW,
    approve_components,
    approved_generic_type_set,
    codes,
    copy_data,
    edit_yaml,
    item,
    load_issues,
    real_registry,
)

WINDOW_KNOWLEDGE = "spds-georgievsky-2004@1:layout.window_sizes_gost_11214_86"


def test_repository_state_resolves_to_no_type_set() -> None:
    """The generic pack is a draft: until a person approves it, generation stays untyped."""
    resolution = resolve_type_set(real_registry())
    assert resolution.type_set is None
    assert "not approved" in resolution.skipped["*"]


def test_approved_generic_pack_resolves_every_role() -> None:
    type_set = approved_generic_type_set()
    assert set(type_set.roles) == set(TYPE_ROLES)
    assert type_set.source == GENERIC_PACK and type_set.mapping == "mapping.generic"
    assert [t.id for t in type_set.types] == sorted(t.id for t in type_set.types)
    assert [a.id for a in type_set.assemblies] == sorted(a.id for a in type_set.assemblies)
    assert len(type_set.types) == 20  # roof.main and roof.garage share one type
    assert all(t.source == GENERIC_PACK for t in type_set.types)


def test_resolution_is_deterministic(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_components(data)
    a = resolve_type_set(read_knowledge(data, verify=False)).type_set
    b = resolve_type_set(read_knowledge(data, verify=False)).type_set
    assert a is not None and a.model_dump_json() == b.model_dump_json()  # type: ignore[union-attr]
    assert a.model_dump_json() == approved_generic_type_set().model_dump_json()


def test_snapshots_carry_the_hash_of_their_catalog_record(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_components(data)
    registry = read_knowledge(data, verify=False)
    type_set = resolve_type_set(registry).type_set
    assert type_set is not None
    records = registry.component_types()
    for snap in type_set.types:
        assert snap.content_sha256 == record_sha256(records[snap.id])


def test_partial_approval_resolves_only_approved_roles(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_components(
        data,
        only={
            "mapping.generic",
            "family.wall.basic",
            "type.wall.generic_exterior_300",
            "assembly.wall.generic_exterior_300",
        },
    )
    resolution = resolve_type_set(read_knowledge(data, verify=False))
    assert resolution.type_set is not None
    assert resolution.type_set.roles == {"wall.exterior": "type.wall.generic_exterior_300"}
    assert "not approved" in resolution.skipped["wall.interior"]


def test_unapproved_assembly_or_family_blocks_the_type(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_components(
        data, only={"mapping.generic", "family.wall.basic", "type.wall.generic_exterior_300"}
    )
    resolution = resolve_type_set(read_knowledge(data, verify=False))
    assert resolution.type_set is None
    assert (
        "assembly.wall.generic_exterior_300 is not approved" in resolution.skipped["wall.exterior"]
    )


def _add_book_window_type(data: Path) -> None:
    def add(doc: dict[str, Any]) -> None:
        doc["types"].append(
            {
                "id": "type.window.gost_11214_86_15_15",
                "family": "family.window.basic",
                "name": "Window 15-15 (GOST 11214-86 series)",
                "params": {
                    "element_type": "window",
                    "material_id": "glass",
                    "frame_material_id": "window_frame",
                    "default_sill": 0.9,
                    "default_height": 1.46,
                    "default_width": 1.47,
                },
                "derived_from": {"knowledge": [WINDOW_KNOWLEDGE]},
                "provenance": [
                    {"source": "buildai-editorial", "supports": ["mapping"]},
                ],
                "status": "approved",
                "review": dict(TEST_REVIEW),
            }
        )
        doc["role_mappings"][0]["roles"]["window.service"] = "type.window.gost_11214_86_15_15"

    edit_yaml(data, GENERIC_COMPONENTS, add)


def test_book_derived_types_stay_blocked_until_their_knowledge_is_approved(tmp_path: Path) -> None:
    """A GOST window type is refused while the K1 window table is needs_verification — even if
    the type record itself were approved (integrity refuses that too)."""
    data = copy_data(tmp_path)
    approve_components(data)
    _add_book_window_type(data)
    # Integrity forbids approving a record derived from unapproved knowledge ...
    assert "APPROVED_DERIVED_UNAPPROVED" in codes(load_issues(data))

    # ... and once the K1 item is reviewed and approved (in this temporary copy), it resolves.
    def approve_item(doc: dict[str, Any]) -> None:
        item(doc, "layout.window_sizes_gost_11214_86").update(
            status="approved", review=dict(TEST_REVIEW), confidence="medium"
        )

    edit_yaml(data, f"{BOOK_DIR}/layout.yaml", approve_item)
    type_set = resolve_type_set(read_knowledge(data, verify=False)).type_set
    assert type_set is not None
    assert type_set.roles["window.service"] == "type.window.gost_11214_86_15_15"


def test_resolver_skips_book_derived_type_whose_knowledge_is_unapproved(tmp_path: Path) -> None:
    """Defence in depth: even if integrity were bypassed, resolution refuses the type."""
    data = copy_data(tmp_path)
    approve_components(data)
    _add_book_window_type(data)
    comp = data / "knowledge" / GENERIC_COMPONENTS
    doc = yaml.safe_load(comp.read_text(encoding="utf-8"))
    registry = read_knowledge(copy_data(tmp_path / "base"), verify=False)
    parsed = ComponentsDocument.model_validate(doc)
    generic = registry.packs[GENERIC_PACK]
    packs = dict(registry.packs)
    packs[GENERIC_PACK] = replace(
        generic,
        families=tuple(parsed.families),
        types=tuple(parsed.types),
        assemblies=tuple(parsed.assemblies),
        role_mappings=tuple(parsed.role_mappings),
    )
    bypassed = KnowledgeRegistry(sources=registry.sources, packs=packs, regions=registry.regions)
    resolution = resolve_type_set(bypassed)
    assert resolution.type_set is not None
    assert "window.service" not in resolution.type_set.roles
    assert WINDOW_KNOWLEDGE in resolution.skipped["window.service"]
