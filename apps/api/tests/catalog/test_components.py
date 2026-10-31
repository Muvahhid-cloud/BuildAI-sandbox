"""Component records (K2): the generic pack, its status, and the component integrity rules."""

from pathlib import Path
from typing import Any

import pytest

from app.modules.building.types import TYPE_ROLES
from app.modules.catalog.components import AssemblyRecord, FamilyRecord, RoleMapping, TypeRecord
from app.modules.catalog.provenance import SourceKind, Status
from tests.catalog.helpers import (
    GENERIC_COMPONENTS,
    GENERIC_PACK,
    codes,
    copy_data,
    edit_yaml,
    load_issues,
    real_registry,
)


def test_generic_pack_is_an_unreviewed_editorial_draft() -> None:
    registry = real_registry()
    pack = registry.packs[GENERIC_PACK]
    assert pack.manifest.status == Status.DRAFT
    assert pack.manifest.sources == ["buildai-editorial"]
    records: list[FamilyRecord | TypeRecord | AssemblyRecord | RoleMapping] = [
        *pack.families,
        *pack.types,
        *pack.assemblies,
        *pack.role_mappings,
    ]
    assert len(records) == 7 + 20 + 7 + 1
    kinds = {s: src.kind for s, src in registry.sources.items()}
    for rec in records:
        assert rec.status == Status.DRAFT and rec.review is None, rec.id
        assert all(kinds[c.source] == SourceKind.EDITORIAL for c in rec.provenance), rec.id


def test_generic_types_invent_no_construction_data() -> None:
    """Single structural layers with unspecified material; no knowledge-derived values."""
    pack = real_registry().packs[GENERIC_PACK]
    for a in pack.assemblies:
        assert [(layer.function, layer.material_id) for layer in a.layers] == [("structure", None)]
        assert a.derived_from.layout_config and not a.derived_from.knowledge
    for t in pack.types:
        assert t.derived_from.layout_config and not t.derived_from.knowledge


def test_generic_mapping_covers_every_role_with_a_matching_type() -> None:
    registry = real_registry()
    mapping = registry.role_mappings()["mapping.generic"]
    types = registry.component_types()
    assert set(mapping.roles) == set(TYPE_ROLES)
    for role, type_id in mapping.roles.items():
        assert types[type_id].params.element_type == TYPE_ROLES[role]


def _edit(data: Path, kind: str, record_id: str, **fields: Any) -> None:
    def change(doc: dict[str, Any]) -> None:
        next(r for r in doc[kind] if r["id"] == record_id).update(fields)

    edit_yaml(data, GENERIC_COMPONENTS, change)


@pytest.mark.parametrize(
    ("kind", "record_id", "fields", "code"),
    [
        (
            "families",
            "family.wall.basic",
            {"element_type": "chimney"},
            "FAMILY_ELEMENT_TYPE_UNKNOWN",
        ),
        ("families", "family.wall.basic", {"class_ref": "class.nowhere"}, "FAMILY_CLASS_UNKNOWN"),
        (
            "types",
            "type.wall.generic_interior_120",
            {"family": "family.door.hinged"},
            "TYPE_FAMILY_MISMATCH",
        ),
        (
            "types",
            "type.wall.generic_interior_120",
            {"family": "family.nowhere"},
            "TYPE_FAMILY_UNKNOWN",
        ),
        (
            "types",
            "type.wall.generic_interior_120",
            {"assembly": "assembly.roof.generic_200"},
            "TYPE_ASSEMBLY_UNKNOWN",
        ),
        (
            "types",
            "type.door.generic_interior",
            {"assembly": "assembly.roof.generic_200"},
            "TYPE_ASSEMBLY_UNEXPECTED",
        ),
        (
            "assemblies",
            "assembly.roof.generic_200",
            {"total_thickness": 0.25},
            "ASSEMBLY_THICKNESS_SUM",
        ),
        (
            "assemblies",
            "assembly.roof.generic_200",
            {"layers": [{"function": "structure", "material_id": "unobtainium", "thickness": 0.2}]},
            "UNKNOWN_MATERIAL",
        ),
        (
            "types",
            "type.door.generic_interior",
            {"derived_from": {"knowledge": ["spds-georgievsky-2004@1:no.such.item"]}},
            "DERIVED_KNOWLEDGE_UNKNOWN",
        ),
    ],
)
def test_component_integrity_rules(
    tmp_path: Path, kind: str, record_id: str, fields: dict[str, Any], code: str
) -> None:
    data = copy_data(tmp_path)
    _edit(data, kind, record_id, **fields)
    assert code in codes(load_issues(data))


def test_mapping_rules(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def change(doc: dict[str, Any]) -> None:
        roles = doc["role_mappings"][0]["roles"]
        del roles["stair.main"]
        roles["wall.curtain"] = "type.wall.generic_exterior_300"
        roles["wall.interior"] = "type.door.generic_interior"
        roles["roof.main"] = "type.roof.nowhere"

    edit_yaml(data, GENERIC_COMPONENTS, change)
    assert {
        "MAPPING_ROLE_MISSING",
        "MAPPING_ROLE_UNKNOWN",
        "MAPPING_ROLE_TYPE_MISMATCH",
        "MAPPING_TYPE_UNKNOWN",
    } <= codes(load_issues(data))


def test_editorial_components_cannot_claim_extraction(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit(data, "types", "type.door.generic_interior", status="extracted")
    assert codes(load_issues(data)) == {"STATUS_SOURCE_MISMATCH"}


def test_approved_record_needs_approved_derived_knowledge(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit(
        data,
        "types",
        "type.window.generic_standard",
        status="approved",
        review={"reviewed_by": "test", "reviewed_on": "2026-09-28"},
        derived_from={"knowledge": ["spds-georgievsky-2004@1:layout.window_sizes_gost_11214_86"]},
    )
    assert codes(load_issues(data)) == {"APPROVED_DERIVED_UNAPPROVED"}
