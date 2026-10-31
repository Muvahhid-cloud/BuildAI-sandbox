"""The Georgievsky 2004 pack stays a scoped, attributed, unreviewed knowledge source."""

from app.modules.catalog.provenance import SourceKind, Status, SupportKind, Usage
from app.modules.catalog.schemas import KnowledgeCategory, PackScopeKind
from tests.catalog.helpers import BOOK_PACK, CORE_PACK, real_registry

BOOK = "georgievsky-2004"


def test_source_record() -> None:
    source = real_registry().sources[BOOK]
    assert source.kind == SourceKind.REFERENCE_HANDBOOK
    assert source.publication_year == 2004
    assert source.page_count == 144
    assert source.basis == ["ESKD", "SPDS"]
    assert source.artifact is not None
    assert source.artifact.stored_in_repo is False
    assert source.usage_policy.paraphrase_only and not source.usage_policy.reproduce_figures


def test_pack_is_scoped_as_a_drawing_convention_profile_not_global() -> None:
    manifest = real_registry().packs[BOOK_PACK].manifest
    assert manifest.scope.kind == PackScopeKind.DRAWING_CONVENTION_PROFILE
    assert manifest.scope.drawing_profile == "spds"
    assert manifest.depends_on == [CORE_PACK]


def test_every_book_object_is_attributed_and_unreviewed() -> None:
    pack = real_registry().packs[BOOK_PACK]
    objects = [
        *(i for _, i in pack.items),
        *pack.localized,
        *pack.drawing_profiles,
    ]
    assert len(objects) > 140
    for obj in objects:
        assert obj.status in (Status.EXTRACTED, Status.NEEDS_VERIFICATION), obj
        assert obj.review is None
        book = [c for c in obj.provenance if c.source == BOOK]
        assert book, obj
        assert all(1 <= p <= 144 for c in book for p in c.pages)


def test_low_confidence_and_inferred_tables_need_verification() -> None:
    registry = real_registry()
    for entry in registry.items(pack=BOOK_PACK):
        if entry.item.confidence == "low":
            assert entry.item.status == Status.NEEDS_VERIFICATION, entry.ref
    windows = registry.item(f"{BOOK_PACK}:layout.window_sizes_gost_11214_86")
    assert windows.status == Status.NEEDS_VERIFICATION
    assert any("inferred" in note for note in windows.inferences)


def test_statements_are_short_paraphrases() -> None:
    for entry in real_registry().items(pack=BOOK_PACK):
        assert len(entry.item.statement) <= 500
        assert "«" not in entry.item.statement  # no quoted Russian passages


def test_structural_and_reference_knowledge_is_reference_only() -> None:
    registry = real_registry()
    for category in (KnowledgeCategory.STRUCTURAL_DRAWING, KnowledgeCategory.REFERENCE):
        entries = list(registry.items(pack=BOOK_PACK, category=category))
        assert entries
        assert all(e.item.usage == Usage.REFERENCE_ONLY for e in entries)
    example = registry.item(f"{BOOK_PACK}:mep.sewer_scheme_example_values")
    assert example.kind == "example" and example.usage == Usage.REFERENCE_ONLY


def test_core_pack_cites_the_book_only_for_existence() -> None:
    core = real_registry().packs[CORE_PACK]
    citations = [c for obj in (*core.classes, *core.terms) for c in obj.provenance]
    book = [c for c in citations if c.source == BOOK]
    assert book
    assert all(c.supports == [SupportKind.EXISTENCE] for c in book)


def test_sample_extracted_knowledge() -> None:
    registry = real_registry()
    module = registry.item(f"{BOOK_PACK}:model.modular.basic_module")
    assert module.params == {"module_m": 0.1}
    axes = registry.item(f"{BOOK_PACK}:drawing.axes.labeling")
    assert "З" in axes.params["excluded_letters"]  # type: ignore[operator]  # noqa: RUF001
    cut = registry.item(f"{BOOK_PACK}:drawing.plan.cut_plane")
    assert cut.provenance[0].pages == [69]
    codes = registry.item(f"{BOOK_PACK}:mep.pipeline_codes").params["codes"]
    assert isinstance(codes, list)
    assert {
        "code": "К1",  # noqa: RUF001
        "en": "domestic sewer",
        "maps_to_system": "sanitary_drain",
        "confidence": "high",
    } in codes


def test_spds_profile_groups_every_drawing_item() -> None:
    registry = real_registry()
    profile = registry.drawing_profile("spds@1")
    grouped = {ref for refs in profile.topics.values() for ref in refs}
    drawing = {
        e.item.id for e in registry.items(pack=BOOK_PACK, category=KnowledgeCategory.DRAWING)
    }
    assert grouped == drawing


def test_default_region_does_not_apply_the_book() -> None:
    region = real_registry().region("generic@1")
    assert region.drawing_profile is None
    assert region.knowledge_packs == [CORE_PACK]
    assert region.region_codes == []
