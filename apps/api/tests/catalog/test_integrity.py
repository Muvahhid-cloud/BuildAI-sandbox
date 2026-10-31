"""Every integrity rule fires on a minimal violation of the real data (and only that rule)."""

from pathlib import Path
from typing import Any

import pytest

from tests.catalog.helpers import BOOK_DIR, CORE_DIR, codes, copy_data, edit_yaml, item, load_issues

ItemEdit = tuple[str, str, Any]


def _set_item(file: str, item_id: str, **fields: Any) -> ItemEdit:
    return (f"{BOOK_DIR}/{file}", item_id, fields)


@pytest.mark.parametrize(
    ("edit", "code"),
    [
        # provenance
        (
            _set_item(
                "model.yaml",
                "model.zero_level",
                provenance=[{"source": "nobody-1999", "pages": [1]}],
            ),
            "CITATION_SOURCE_UNKNOWN",
        ),
        (
            _set_item(
                "model.yaml", "model.zero_level", provenance=[{"source": "georgievsky-2004"}]
            ),
            "CITATION_PAGES_REQUIRED",
        ),
        (
            _set_item(
                "model.yaml",
                "model.zero_level",
                provenance=[{"source": "georgievsky-2004", "pages": [145]}],
            ),
            "CITATION_PAGE_OUT_OF_RANGE",
        ),
        (
            _set_item(
                "model.yaml",
                "model.zero_level",
                provenance=[
                    {"source": "georgievsky-2004", "pages": [45]},
                    {"source": "buildai-editorial", "pages": [3]},
                ],
            ),
            "CITATION_PAGES_UNEXPECTED",
        ),
        # lifecycle vs. source kind
        (_set_item("model.yaml", "model.zero_level", status="draft"), "STATUS_SOURCE_MISMATCH"),
        (
            _set_item(
                "model.yaml", "model.zero_level", provenance=[{"source": "buildai-editorial"}]
            ),
            "STATUS_SOURCE_MISMATCH",
        ),
        # units, scales, references
        (_set_item("model.yaml", "model.zero_level", params={"height": 2.5}), "PARAM_UNIT_MISSING"),
        (
            _set_item("model.yaml", "model.zero_level", params={"plan_scales": ["1/100"]}),
            "PARAM_SCALE_FORMAT",
        ),
        (_set_item("model.yaml", "model.zero_level", related=["class.teleporter"]), "REF_UNKNOWN"),
        (
            _set_item(
                "model.yaml",
                "model.zero_level",
                status="approved",
                confidence="low",
                review={"reviewed_by": "x", "reviewed_on": "2026-09-28"},
            ),
            "APPROVED_LOW_CONFIDENCE",
        ),
        # drawing profile grouping
        (
            _set_item("drawing-views.yaml", "drawing.titles", category="layout"),
            "PROFILE_ITEM_UNKNOWN",
        ),
    ],
)
def test_item_rules(tmp_path: Path, edit: ItemEdit, code: str) -> None:
    data = copy_data(tmp_path)
    rel, item_id, fields = edit
    edit_yaml(data, rel, lambda d: item(d, item_id).update(fields))
    assert codes(load_issues(data)) == {code}


def test_unreviewed_items_cannot_carry_approval_fields(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/model.yaml",
        lambda d: item(d, "model.zero_level").update(status="approved"),
    )
    assert codes(load_issues(data)) == {"KNOWLEDGE_SCHEMA"}  # approval needs a review record


def test_global_pack_may_not_borrow_statements_from_a_source(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def borrow(doc: dict[str, Any]) -> None:
        wall = next(c for c in doc["classes"] if c["id"] == "class.wall")
        wall["provenance"][0]["supports"] = ["statement"]

    edit_yaml(data, f"{CORE_DIR}/ontology.yaml", borrow)
    assert codes(load_issues(data)) == {"GLOBAL_SCOPE_BORROWS_SOURCE"}


def test_ontology_must_cover_every_model_vocabulary_value(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def drop(doc: dict[str, Any]) -> None:
        doc["classes"] = [c for c in doc["classes"] if c["id"] != "class.space.garage"]

    edit_yaml(data, f"{CORE_DIR}/ontology.yaml", drop)
    issues = load_issues(data)
    assert codes(issues) == {"ONTOLOGY_COVERAGE"}
    assert "room_type:garage" in issues[0].message


def test_double_binding_is_an_error(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def double(doc: dict[str, Any]) -> None:
        roof = next(c for c in doc["classes"] if c["id"] == "class.roof")
        roof["model_binding"] = {"element_type": "wall"}

    edit_yaml(data, f"{CORE_DIR}/ontology.yaml", double)
    messages = [i.message for i in load_issues(data)]
    assert any("element_type:wall is bound by 2" in m for m in messages)
    assert any("element_type:roof is bound by 0" in m for m in messages)


def test_class_hierarchy_and_relationship_references(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def break_refs(doc: dict[str, Any]) -> None:
        wall = next(c for c in doc["classes"] if c["id"] == "class.wall")
        wall["parent"] = "class.wall.partition"  # partition's parent is class.wall -> cycle
        rel = next(r for r in doc["relationships"] if r["id"] == "rel.bounds")
        rel["target_classes"] = ["class.nowhere"]

    edit_yaml(data, f"{CORE_DIR}/ontology.yaml", break_refs)
    assert codes(load_issues(data)) == {"CLASS_CYCLE", "REL_CLASS_UNKNOWN"}


def test_localized_terms_need_a_canonical_term(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/glossary.ru.yaml",
        lambda d: d["localized"][0].update(term_id="term.unknown_concept"),
    )
    assert codes(load_issues(data)) == {"LOCALIZED_TERM_UNKNOWN"}


def test_drawing_items_must_belong_to_the_profile(tmp_path: Path) -> None:
    data = copy_data(tmp_path)

    def ungroup(doc: dict[str, Any]) -> None:
        doc["profiles"][0]["topics"]["titles"] = []

    edit_yaml(data, f"{BOOK_DIR}/drawing-profile.yaml", ungroup)
    assert codes(load_issues(data)) == {"DRAWING_ITEM_UNGROUPED"}


def test_drawing_profile_cannot_live_in_a_global_pack(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/pack.yaml",
        lambda d: d["scope"].update(kind="global", drawing_profile=None),
    )
    found = codes(load_issues(data))
    assert "PROFILE_SCOPE_MISMATCH" in found
    assert "GLOBAL_SCOPE_BORROWS_SOURCE" in found  # and book statements cannot become global


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"rules_profile": "generic-residential@9"}, "REGION_RULES_PROFILE_UNKNOWN"),
        ({"knowledge_packs": ["core@1", "missing@1"]}, "REGION_PACK_UNKNOWN"),
        ({"drawing_profile": "iso@1"}, "REGION_DRAWING_PROFILE_UNKNOWN"),
        ({"drawing_profile": "spds@1"}, "REGION_PACK_MISSING"),
    ],
)
def test_region_profile_references(tmp_path: Path, fields: dict[str, Any], code: str) -> None:
    data = copy_data(tmp_path)
    edit_yaml(data, "regions/generic.v1.yaml", lambda d: d.update(fields))
    assert codes(load_issues(data)) == {code}


def test_region_can_opt_into_the_spds_profile(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        "regions/generic.v1.yaml",
        lambda d: d.update(
            drawing_profile="spds@1", knowledge_packs=["core@1", "spds-georgievsky-2004@1"]
        ),
    )
    assert load_issues(data) == []


def test_pack_manifest_rules(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/pack.yaml",
        lambda d: d.update(version=2, depends_on=["core@1", "base@3"]),
    )
    assert codes(load_issues(data)) == {"PACK_DIRECTORY_MISMATCH", "PACK_DEPENDENCY_UNKNOWN"}
