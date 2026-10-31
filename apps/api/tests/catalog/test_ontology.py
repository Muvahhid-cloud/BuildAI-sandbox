"""The core ontology follows the canonical building model (CLAUDE.md rule 7)."""

from typing import get_args

from app.modules.building.elements import ElementType
from app.modules.building.enums import RelationshipKind, RoomType
from app.modules.catalog.provenance import SourceKind, Status
from app.modules.catalog.schemas import OntologyClass, RelationshipDefinition, Term
from tests.catalog.helpers import real_registry


def test_every_element_type_has_one_primary_class_with_an_ifc_mapping() -> None:
    classes = real_registry().classes().values()
    for element_type in get_args(ElementType):
        bound = [
            c
            for c in classes
            if c.model_binding is not None
            and c.model_binding.element_type == element_type
            and c.model_binding.is_primary
        ]
        assert len(bound) == 1, element_type
        assert bound[0].ifc is not None, element_type


def test_every_room_type_is_a_space_class() -> None:
    classes = real_registry().classes()
    by_room = {
        c.model_binding.room_type: c
        for c in classes.values()
        if c.model_binding is not None and c.model_binding.room_type is not None
    }
    assert set(by_room) == set(RoomType)
    assert all(c.parent == "class.space" for c in by_room.values())


def test_every_relationship_kind_is_defined_once() -> None:
    rels = real_registry().relationships().values()
    assert sorted(r.model_binding for r in rels) == sorted(RelationshipKind)
    reserved = {r.model_binding for r in rels if r.reserved}
    assert reserved == {
        RelationshipKind.SERVES,
        RelationshipKind.CONNECTED_TO,
        RelationshipKind.PART_OF_SYSTEM,
    }


def test_hosted_by_matches_the_model_invariant() -> None:
    rel = real_registry().relationships()["rel.hosted_by"]
    assert rel.source_classes == ["class.door", "class.window"]
    assert rel.target_classes == ["class.wall"]
    assert (rel.per_source.min, rel.per_source.max) == (1, 1)


def test_unbound_classes_introduce_no_model_types() -> None:
    """K1 adds vocabulary only: concepts like foundations stay unbound until a phase models them."""
    classes = real_registry().classes()
    for class_id in ("class.foundation", "class.lintel", "class.column", "class.pipeline"):
        assert classes[class_id].model_binding is None


def test_editorial_only_objects_are_drafts() -> None:
    registry = real_registry()
    kinds = {s: src.kind for s, src in registry.sources.items()}
    core = registry.packs["core@1"]
    objects: list[OntologyClass | RelationshipDefinition | Term] = [
        *core.classes,
        *core.relationships,
        *core.terms,
    ]
    for obj in objects:
        editorial = all(kinds[c.source] == SourceKind.EDITORIAL for c in obj.provenance)
        assert (obj.status == Status.DRAFT) == editorial, obj.id


def test_every_term_class_ref_resolves_and_every_ru_term_has_english() -> None:
    registry = real_registry()
    classes, terms = registry.classes(), registry.terms()
    assert all(t.class_ref in classes for t in terms.values() if t.class_ref)
    assert all(t.term_id in terms for t in registry.localized_terms("ru"))
