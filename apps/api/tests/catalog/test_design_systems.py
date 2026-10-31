"""Design-system records, integrity and gated resolution (K3, catalog/design_systems.py)."""

from dataclasses import replace
from pathlib import Path
from typing import Any

from app.modules.building.types import TYPE_ROLES
from app.modules.catalog.design_systems import design_catalog, resolve_design
from app.modules.catalog.loader import read_knowledge
from app.modules.catalog.provenance import Status
from app.modules.catalog.resolver import record_sha256
from tests.catalog.helpers import (
    DESIGN_COMPONENTS,
    DESIGN_PACK,
    approve_components,
    approve_design_systems,
    approved_design_registry,
    codes,
    copy_data,
    edit_yaml,
    load_issues,
    real_registry,
)

SYSTEMS = ["classic-brick", "contemporary-warm", "modern-minimal", "scandinavian-timber"]


def _system(doc: dict[str, Any], design_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(d for d in doc["design_systems"] if d["id"] == design_id)
    return found


def _edit_system(data: Path, design_id: str, **changes: Any) -> None:
    def change(doc: dict[str, Any]) -> None:
        rec = _system(doc, design_id)
        for key, value in changes.items():
            if isinstance(value, dict) and isinstance(rec.get(key), dict):
                rec[key] = {**rec[key], **value}
            else:
                rec[key] = value

    edit_yaml(data, DESIGN_COMPONENTS, change)


def issue_messages(data: Path, code: str) -> list[str]:
    return [i.message for i in load_issues(data) if i.code == code]


# --- repository state -------------------------------------------------------------------------


def test_four_design_systems_exist_as_editorial_drafts() -> None:
    registry = real_registry()
    designs = registry.design_systems()
    assert sorted(designs) == SYSTEMS
    assert all(d.status == Status.DRAFT for d in designs.values())
    assert all(registry.pack_of(d) == DESIGN_PACK for d in designs)
    assert all(p.source == "buildai-editorial" for d in designs.values() for p in d.provenance)
    pack = registry.packs[DESIGN_PACK].manifest
    assert pack.status == Status.DRAFT and pack.scope.kind.value == "global"
    assert pack.scope.jurisdiction_context == []  # region-neutral


def test_draft_design_systems_are_blocked() -> None:
    registry = real_registry()
    for design_id in SYSTEMS:
        resolution = resolve_design(registry, design_id)
        assert resolution.snapshot is None
        assert "draft" in (resolution.reason or "")
    assert design_catalog(registry).available == []


def test_approved_system_with_draft_components_stays_blocked(tmp_path: Path) -> None:
    """Approving only the design-system record is not enough: its types must be approved."""
    data = copy_data(tmp_path)

    def approve_only_systems(doc: dict[str, Any]) -> None:
        for rec in doc["design_systems"]:
            rec["status"] = "approved"
            rec["review"] = {"reviewed_by": "test", "reviewed_on": "2026-09-29"}

    edit_yaml(data, DESIGN_COMPONENTS, approve_only_systems)
    # Integrity refuses an approved system with unapproved dependencies ...
    assert "DESIGN_SYSTEM_INCOMPLETE" in codes(load_issues(data))
    assert any(
        "unapproved components" in m for m in issue_messages(data, "DESIGN_SYSTEM_INCOMPLETE")
    )


# --- resolution when approved (temporary copy only) ------------------------------------------


def test_approved_systems_resolve_to_complete_snapshots() -> None:
    registry = approved_design_registry()
    catalog = design_catalog(registry)
    assert [d.id for d in catalog.available] == SYSTEMS and catalog.unavailable == []
    for snapshot in catalog.available:
        resolution = resolve_design(registry, snapshot.id)
        assert resolution.types is not None and resolution.types.type_set is not None
        assert set(resolution.types.type_set.roles) == set(TYPE_ROLES)
        assert snapshot.type_ids == sorted(t.id for t in resolution.types.type_set.types)
        assert snapshot.content_sha256 == record_sha256(registry.design_systems()[snapshot.id])
        assert snapshot.source == DESIGN_PACK
        assert snapshot.roof.default in snapshot.roof.types
        assert snapshot.windows.default in snapshot.windows.styles
        assert snapshot.facade.default_material in snapshot.facade.materials


def test_resolution_is_deterministic() -> None:
    registry = approved_design_registry()
    a = design_catalog(registry).model_dump_json()
    b = design_catalog(registry).model_dump_json()
    assert a == b


def test_systems_differ_in_visible_choices() -> None:
    catalog = design_catalog(approved_design_registry())
    by_id = {d.id: d for d in catalog.available}
    assert by_id["modern-minimal"].finishes.dry_floor == "oak_light"
    assert by_id["classic-brick"].facade.default_material.value == "brick"
    assert by_id["classic-brick"].facade.colors == []
    assert "type.window.white_frame_standard" in by_id["classic-brick"].type_ids
    assert "type.door.minimal_entrance" in by_id["modern-minimal"].type_ids


def test_partially_approved_components_block_the_system(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_design_systems(data)

    def unapprove(doc: dict[str, Any]) -> None:
        for rec in doc["types"]:
            if rec["id"] == "type.door.minimal_entrance":
                rec["status"] = "draft"
                rec.pop("review", None)

    edit_yaml(data, DESIGN_COMPONENTS, unapprove)
    # Integrity refuses the inconsistent catalog (it would not load at all) ...
    assert any("minimal_entrance" in m for m in issue_messages(data, "DESIGN_SYSTEM_INCOMPLETE"))

    # ... and even with integrity bypassed, resolution refuses the system (defence in depth).
    registry = approved_design_registry()
    pack = registry.packs[DESIGN_PACK]
    types = tuple(
        t.model_copy(update={"status": Status.DRAFT, "review": None})
        if t.id == "type.door.minimal_entrance"
        else t
        for t in pack.types
    )
    bypassed = replace(registry, packs={**registry.packs, DESIGN_PACK: replace(pack, types=types)})
    resolution = resolve_design(bypassed, "modern-minimal")
    assert resolution.snapshot is None and "not all approved" in (resolution.reason or "")
    assert resolve_design(bypassed, "classic-brick").snapshot is not None  # unaffected


# --- integrity ------------------------------------------------------------------------------


def test_unknown_role_mapping_is_an_invalid_dependency(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit_system(data, "modern-minimal", role_mapping="mapping.does_not_exist")
    assert any("does not exist" in m for m in issue_messages(data, "DESIGN_SYSTEM_INCOMPLETE"))


def test_mapping_with_a_missing_role_is_incomplete(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def drop_role(doc: dict[str, Any]) -> None:
        mapping = next(m for m in doc["role_mappings"] if m["id"] == "mapping.modern_minimal")
        del mapping["roles"]["window.panoramic"]

    edit_yaml(data, DESIGN_COMPONENTS, drop_role)
    assert "MAPPING_ROLE_MISSING" in codes(load_issues(data))


def test_mapping_with_an_unknown_type_is_invalid(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def bad_type(doc: dict[str, Any]) -> None:
        mapping = next(m for m in doc["role_mappings"] if m["id"] == "mapping.classic_brick")
        mapping["roles"]["window.standard"] = "type.window.nonexistent"

    edit_yaml(data, DESIGN_COMPONENTS, bad_type)
    assert "MAPPING_TYPE_UNKNOWN" in codes(load_issues(data))


def test_unknown_material_is_refused(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit_system(data, "scandinavian-timber", finishes={"dry_floor": "unobtainium"})
    assert "UNKNOWN_MATERIAL" in codes(load_issues(data))


def test_invalid_defaults_are_refused(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit_system(
        data,
        "classic-brick",
        roof={"default": "flat"},  # not in [hip, gable] (and a pitch for a flat roof)
        windows={"default": "panoramic"},
        facade={"default_color": "yellow"},  # no palette and no custom colors
    )
    messages = issue_messages(data, "DESIGN_SYSTEM_INCOMPLETE")
    assert any("default roof" in m for m in messages)
    assert any("flat default roof" in m for m in messages)
    assert any("default window style" in m for m in messages)
    assert any("default facade color" in m for m in messages)


def test_unknown_palette_color_is_refused(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit_system(data, "contemporary-warm", facade={"colors": ["warm_beige", "neon_pink"]})
    assert any("neon_pink" in m for m in issue_messages(data, "DESIGN_SYSTEM_INCOMPLETE"))


def test_invalid_style_tag_is_a_schema_error(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    _edit_system(data, "modern-minimal", style_tags=["googie"])
    assert "KNOWLEDGE_SCHEMA" in codes(load_issues(data))


def test_duplicate_design_system_ids(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def duplicate(doc: dict[str, Any]) -> None:
        doc["design_systems"].append(dict(_system(doc, "modern-minimal")))

    edit_yaml(data, DESIGN_COMPONENTS, duplicate)
    assert "DUPLICATE_ID" in codes(load_issues(data))


def test_generic_types_alone_do_not_make_a_system_usable(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    approve_components(data)  # generic pack approved, design pack still draft
    registry = read_knowledge(data, verify=False)
    assert design_catalog(registry).available == []
