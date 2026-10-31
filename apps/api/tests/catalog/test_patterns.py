"""Layout pattern pack (buildai-layout-patterns@1) and its resolution to snapshots."""

from pathlib import Path
from typing import Any

from app.modules.building.patterns import EngineSupport, StatementKind
from app.modules.catalog.loader import read_knowledge
from app.modules.catalog.patterns import pattern_library
from app.modules.catalog.provenance import Status, Usage
from tests.catalog.helpers import (
    PATTERN_PACK,
    codes,
    copy_data,
    edit_yaml,
    load_issues,
    real_registry,
)

PATTERNS = "packs/buildai-layout-patterns.v1/patterns.yaml"


def _pattern(doc: dict[str, Any], pattern_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(p for p in doc["patterns"] if p["id"] == pattern_id)
    return found


def test_pattern_pack_is_an_editorial_draft() -> None:
    registry = real_registry()
    records = registry.layout_patterns()
    assert len(records) == 7
    assert registry.packs[PATTERN_PACK].manifest.status == Status.DRAFT
    for record in records.values():
        assert record.status == Status.DRAFT and record.review is None
        assert all(c.source == "buildai-editorial" for c in record.provenance)
        kinds = {s.kind for s in record.statements}
        # Never claimed as a source-backed rule: no reviewed published source exists.
        assert StatementKind.SOURCE_RULE not in kinds
        assert record.intent and record.context and record.circulation and record.privacy


def test_unsupported_patterns_are_reference_only_and_not_in_the_library() -> None:
    registry = real_registry()
    courtyard = registry.layout_patterns()["pattern.courtyard_house"]
    assert courtyard.engine_support == EngineSupport.NONE
    assert courtyard.usage == Usage.REFERENCE_ONLY
    library = pattern_library(registry)
    ids = [p.id for p in library.patterns]
    assert "pattern.courtyard_house" not in ids
    assert ids == sorted(ids) and len(ids) == 6
    assert all(p.status == "draft" and p.source == PATTERN_PACK for p in library.patterns)
    assert all(len(p.content_sha256) == 64 for p in library.patterns)


def test_every_recipe_is_explained_by_a_heuristic_statement() -> None:
    for p in pattern_library(real_registry()).patterns:
        assert any(s.kind == StatementKind.HEURISTIC for s in p.statements), p.id
        if p.engine_support == EngineSupport.PARTIAL:
            assert p.limitations, p.id


def test_a_source_rule_needs_a_reviewed_published_source(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def claim(doc: dict[str, Any]) -> None:
        _pattern(doc, "pattern.compact_family_home")["statements"].append(
            {"kind": "source_rule", "text": "A claimed standard."}
        )

    edit_yaml(data, PATTERNS, claim)
    assert "PATTERN_RULE_UNSOURCED" in codes(load_issues(data))


def test_an_unsupported_pattern_cannot_carry_a_recipe(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def recipe(doc: dict[str, Any]) -> None:
        _pattern(doc, "pattern.courtyard_house")["recipe"] = {"footprint_aspect": [1.0, 1.2]}

    edit_yaml(data, PATTERNS, recipe)
    assert "PATTERN_UNSUPPORTED_RUNTIME" in codes(load_issues(data))


def test_partial_support_must_list_limitations(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data, PATTERNS, lambda doc: _pattern(doc, "pattern.open_plan_living").update(limitations=[])
    )
    assert "PATTERN_LIMITATIONS_MISSING" in codes(load_issues(data))


def test_deprecated_patterns_are_left_out(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        PATTERNS,
        lambda doc: _pattern(doc, "pattern.open_plan_living").update(
            status="deprecated", superseded_by="pattern.garden_oriented_living"
        ),
    )
    ids = [p.id for p in pattern_library(read_knowledge(data, verify=False)).patterns]
    assert "pattern.open_plan_living" not in ids


def test_l_pattern_only_adds_a_topology_on_one_storey() -> None:
    pattern = pattern_library(real_registry()).get("pattern.l_shaped_garden_wing")
    assert pattern is not None and pattern.status == "draft"
    assert pattern.recipe.topology == "l_shape"
    assert pattern.applicability.storeys == [1]
    assert pattern.applicability.required_triggers == ["privacy_zoning"]


def test_a_topology_pattern_must_be_single_storey(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        PATTERNS,
        lambda doc: _pattern(doc, "pattern.l_shaped_garden_wing")["applicability"].update(
            storeys=[1, 2]
        ),
    )
    assert "PATTERN_TOPOLOGY_STOREYS" in codes(load_issues(data))
