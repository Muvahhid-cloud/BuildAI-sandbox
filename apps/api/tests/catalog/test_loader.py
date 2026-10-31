from pathlib import Path

import pytest

from app.modules.catalog.loader import KnowledgeLoadError, load_knowledge, read_knowledge
from app.modules.catalog.lock import LOCK_FILE, compute_lock, read_lock, render_lock, verify_lock
from app.modules.catalog.provenance import Status
from app.modules.catalog.schemas import KnowledgeCategory
from tests.building.helpers import DATA_DIR
from tests.catalog.helpers import (
    BOOK_DIR,
    BOOK_PACK,
    CORE_PACK,
    DESIGN_PACK,
    GENERIC_PACK,
    PATTERN_PACK,
    codes,
    copy_data,
    edit_yaml,
    item,
    load_issues,
    real_registry,
)


def test_repository_knowledge_loads_and_is_locked() -> None:
    registry = real_registry()
    assert sorted(registry.packs) == [
        DESIGN_PACK,
        GENERIC_PACK,
        PATTERN_PACK,
        CORE_PACK,
        BOOK_PACK,
    ]
    assert sorted(registry.sources) == ["buildai-editorial", "georgievsky-2004"]
    assert sorted(registry.regions) == ["generic@1"]
    assert verify_lock(DATA_DIR / "knowledge") == []


def test_lock_file_is_the_rendered_current_lock() -> None:
    """`pnpm knowledge:lock` output is committed; the file is byte-stable (LF, key order)."""
    knowledge = DATA_DIR / "knowledge"
    on_disk = (knowledge / LOCK_FILE).read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert on_disk == render_lock(compute_lock(knowledge))


def test_loading_is_deterministic_and_cached() -> None:
    a, b = read_knowledge(DATA_DIR), read_knowledge(DATA_DIR)
    assert [e.ref for e in a.items()] == [e.ref for e in b.items()]
    assert a.packs == b.packs
    assert load_knowledge(DATA_DIR) is load_knowledge(DATA_DIR)


def test_registry_lookups() -> None:
    registry = real_registry()
    ref = f"{BOOK_PACK}:drawing.axes.labeling"
    assert registry.item(ref).category == "drawing"
    assert registry.classes()["class.wall"].model_binding is not None
    assert registry.terms()["term.lintel"].class_ref == "class.lintel"
    ru = {t.term_id: t for t in registry.localized_terms("ru")}
    assert ru["term.lintel"].preferred == "перемычка"
    assert ru["term.lintel"].codes == {"spds_letter": "ПР"}
    assert registry.drawing_profile("spds@1").topics
    assert registry.region("generic@1").rules_profile == "generic-residential@1"
    drawing = list(registry.items(pack=BOOK_PACK, category=KnowledgeCategory.DRAWING))
    assert drawing and all(e.item.category == "drawing" for e in drawing)


def test_no_knowledge_is_approved_so_nothing_is_consumable() -> None:
    registry = real_registry()
    assert registry.approved_items() == []
    assert list(registry.items(status=Status.APPROVED)) == []


def test_edit_without_relock_is_refused(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/model.yaml",
        lambda d: item(d, "model.modular.basic_module").update(concept="edited"),
    )
    with pytest.raises(KnowledgeLoadError) as exc:
        read_knowledge(data)
    assert codes(exc.value.issues) == {"KNOWLEDGE_LOCK_STALE"}
    assert exc.value.issues[0].path.endswith(BOOK_PACK)


def test_lock_detects_new_removed_and_missing_entries(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    knowledge = data / "knowledge"
    (knowledge / "regions" / "generic.v1.yaml").rename(knowledge / "regions" / "other.v1.yaml")
    assert codes(verify_lock(knowledge)) == {"KNOWLEDGE_LOCK_UNLISTED", "KNOWLEDGE_LOCK_ORPHAN"}
    (knowledge / LOCK_FILE).unlink()
    assert codes(verify_lock(knowledge)) == {"KNOWLEDGE_LOCK_MISSING"}
    assert read_lock(knowledge) is None


def test_lock_ignores_line_endings(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    knowledge = data / "knowledge"
    path = knowledge / "regions" / "generic.v1.yaml"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert verify_lock(knowledge) == []


def test_schema_errors_carry_file_pointers(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(
        data,
        f"{BOOK_DIR}/model.yaml",
        lambda d: item(d, "model.zero_level").update(quote="copied text"),
    )
    issues = load_issues(data)
    assert codes(issues) == {"KNOWLEDGE_SCHEMA"}
    assert issues[0].path.startswith("/packs~1spds-georgievsky-2004.v1~1model.yaml/items/")


def test_unlisted_pack_file_is_an_error(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    (data / "knowledge" / BOOK_DIR / "notes.yaml").write_text("items: []\n", encoding="utf-8")
    assert codes(load_issues(data)) == {"PACK_UNLISTED_FILE"}


def test_missing_pack_file_is_an_error(tmp_path: Path) -> None:
    data = copy_data(tmp_path)
    edit_yaml(data, f"{BOOK_DIR}/pack.yaml", lambda d: d["contents"]["items"].append("absent.yaml"))
    assert codes(load_issues(data)) == {"PACK_FILE_MISSING"}
