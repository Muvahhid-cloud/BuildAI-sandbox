"""Cross-document integrity checks for loaded knowledge (docs/knowledge.md §5).

Schema validation (Pydantic) covers single documents; these checks cover everything that
spans documents: provenance against sources, lifecycle against source kinds, scope limits,
units, references, ontology coverage of the canonical building model, drawing profiles and
region profiles. All issues use the shared `Issue` shape; any error blocks loading.
"""

import re
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import get_args

from pydantic import JsonValue

from app.modules.building.elements import ElementType
from app.modules.building.enums import RelationshipKind, RoomType
from app.modules.building.issues import Issue, pointer
from app.modules.building.model import BuildingInfo
from app.modules.catalog.component_integrity import check_components, check_design_systems
from app.modules.catalog.patterns_schema import check_patterns
from app.modules.catalog.provenance import (
    Provenanced,
    SourceKind,
    Status,
    SupportKind,
)
from app.modules.catalog.registry import KnowledgeRegistry, LoadedPack
from app.modules.catalog.schemas import (
    KnowledgeCategory,
    OntologyClass,
    PackScopeKind,
)

# Numeric parameters must declare their unit through a key suffix (own key or enclosing key).
UNIT_SUFFIXES = (
    "_m",  # meters (building space)
    "_m2",
    "_paper_mm",  # millimetres on the drawing sheet
    "_deg",
    "_ratio",  # dimensionless ratio (slopes, fractions)
    "_s",  # multiple of the main line thickness S (drawing line weights)
    "_count",
    "_index",
)
SCALE_PATTERN = re.compile(r"^\d+(\.\d+)?:\d+(\.\d+)?$")
ELEMENT_TYPES = frozenset(get_args(ElementType))
BUILDING_TYPES = frozenset(get_args(BuildingInfo.model_fields["building_type"].annotation))


def _issue(code: str, path: str, message: str, suggestion: str | None = None) -> Issue:
    return Issue(severity="error", code=code, path=path, message=message, suggestion=suggestion)


def check_registry(
    registry: KnowledgeRegistry,
    *,
    known_rules_profiles: frozenset[str],
    known_materials: frozenset[str] | None = None,
) -> list[Issue]:
    issues: list[Issue] = []
    issues += _check_packs(registry)
    issues += check_components(registry, known_materials=known_materials)
    issues += check_design_systems(registry, known_materials=known_materials)
    issues += check_patterns(registry)
    for pack in registry.packs.values():
        issues += _check_provenance(registry, pack)
        issues += _check_items(registry, pack)
        issues += _check_drawing_profiles(pack)
    issues += _check_ontology(registry)
    issues += _check_glossary(registry)
    issues += _check_regions(registry, known_rules_profiles)
    return issues


# --- packs ---


def _dependency_closure(registry: KnowledgeRegistry, ref: str) -> set[str]:
    seen: set[str] = set()
    stack = [ref]
    while stack:
        current = stack.pop()
        pack = registry.packs.get(current)
        for dep in pack.manifest.depends_on if pack else []:
            if dep not in seen:
                seen.add(dep)
                stack.append(dep)
    return seen


def _check_packs(registry: KnowledgeRegistry) -> list[Issue]:
    issues: list[Issue] = []
    for ref, pack in registry.packs.items():
        m = pack.manifest
        path = pointer("packs", ref)
        expected_dir = f"packs/{m.id}.v{m.version}"
        if pack.directory != expected_dir:
            issues.append(
                _issue("PACK_DIRECTORY_MISMATCH", path, f"{ref} must live in {expected_dir}/")
            )
        for extra in pack.extra_files:
            issues.append(
                _issue(
                    "PACK_UNLISTED_FILE",
                    pointer("packs", ref, extra),
                    f"{extra} is not listed in {ref}'s manifest contents",
                )
            )
        for src in m.sources:
            if src not in registry.sources:
                issues.append(_issue("PACK_SOURCE_UNKNOWN", path, f"unknown source {src}"))
        for dep in m.depends_on:
            if dep not in registry.packs:
                issues.append(_issue("PACK_DEPENDENCY_UNKNOWN", path, f"unknown pack {dep}"))
        if ref in _dependency_closure(registry, ref):
            issues.append(_issue("PACK_DEPENDENCY_CYCLE", path, f"{ref} depends on itself"))
        for dup, n in Counter(i.id for _, i in pack.items).items():
            if n > 1:
                issues.append(_issue("DUPLICATE_ID", path, f"item {dup} defined {n} times"))
    for kind, ids in (
        ("class", [c.id for p in registry.packs.values() for c in p.classes]),
        ("relationship", [r.id for p in registry.packs.values() for r in p.relationships]),
        ("term", [t.id for p in registry.packs.values() for t in p.terms]),
        (
            "localized term",
            [f"{t.term_id}/{t.locale}" for p in registry.packs.values() for t in p.localized],
        ),
    ):
        for dup, n in Counter(ids).items():
            if n > 1:
                issues.append(
                    _issue("DUPLICATE_ID", pointer("packs"), f"{kind} {dup} defined {n} times")
                )
    return issues


# --- provenance, lifecycle and scope ---


def _provenanced(pack: LoadedPack) -> Iterator[tuple[str, Provenanced]]:
    for _, item in pack.items:
        yield pointer("packs", pack.ref, "items", item.id), item
    for c in pack.classes:
        yield pointer("packs", pack.ref, "classes", c.id), c
    for r in pack.relationships:
        yield pointer("packs", pack.ref, "relationships", r.id), r
    for t in pack.terms:
        yield pointer("packs", pack.ref, "terms", t.id), t
    for lt in pack.localized:
        yield pointer("packs", pack.ref, "localized", f"{lt.term_id}/{lt.locale}"), lt
    for d in pack.drawing_profiles:
        yield pointer("packs", pack.ref, "drawing_profiles", d.ref), d
    for family in pack.families:
        yield pointer("packs", pack.ref, "families", family.id), family
    for type_record in pack.types:
        yield pointer("packs", pack.ref, "types", type_record.id), type_record
    for assembly in pack.assemblies:
        yield pointer("packs", pack.ref, "assemblies", assembly.id), assembly
    for mapping in pack.role_mappings:
        yield pointer("packs", pack.ref, "role_mappings", mapping.id), mapping
    for design in pack.design_systems:
        yield pointer("packs", pack.ref, "design_systems", design.id), design
    for pattern in pack.patterns:
        yield pointer("packs", pack.ref, "patterns", pattern.id), pattern


def _check_provenance(registry: KnowledgeRegistry, pack: LoadedPack) -> list[Issue]:
    issues: list[Issue] = []
    declared = set(pack.manifest.sources)
    is_global = pack.manifest.scope.kind == PackScopeKind.GLOBAL
    for path, obj in _provenanced(pack):
        kinds: list[SourceKind] = []
        for n, cit in enumerate(obj.provenance):
            cpath = f"{path}/provenance/{n}"
            source = registry.sources.get(cit.source)
            if source is None:
                issues.append(_issue("CITATION_SOURCE_UNKNOWN", cpath, f"unknown {cit.source}"))
                continue
            kinds.append(source.kind)
            if cit.source not in declared:
                issues.append(
                    _issue(
                        "CITATION_SOURCE_UNDECLARED",
                        cpath,
                        f"{cit.source} is not listed in the sources of {pack.ref}",
                    )
                )
            if source.page_count is not None:
                if not cit.pages:
                    issues.append(
                        _issue(
                            "CITATION_PAGES_REQUIRED",
                            cpath,
                            f"citations of {cit.source} must give printed page numbers",
                        )
                    )
                bad = [p for p in cit.pages if p > source.page_count]
                if bad:
                    issues.append(
                        _issue(
                            "CITATION_PAGE_OUT_OF_RANGE",
                            cpath,
                            f"pages {bad} exceed the {source.page_count} pages of {cit.source}",
                        )
                    )
            elif cit.pages:
                issues.append(
                    _issue("CITATION_PAGES_UNEXPECTED", cpath, f"{cit.source} has no pages")
                )
            if (
                is_global
                and source.kind != SourceKind.EDITORIAL
                and set(cit.supports) - {SupportKind.EXISTENCE}
            ):
                issues.append(
                    _issue(
                        "GLOBAL_SCOPE_BORROWS_SOURCE",
                        cpath,
                        f"global pack {pack.ref} may cite {cit.source} only for the existence of "
                        "a concept, not for statements, terms or parameters",
                        "Move source-specific knowledge into a scoped pack.",
                    )
                )
        editorial_only = bool(kinds) and all(k == SourceKind.EDITORIAL for k in kinds)
        if obj.status == Status.DRAFT and not editorial_only:
            issues.append(
                _issue(
                    "STATUS_SOURCE_MISMATCH",
                    path,
                    "draft is for team-authored knowledge; source-derived knowledge starts as "
                    "extracted or needs_verification",
                )
            )
        if obj.status in (Status.EXTRACTED, Status.NEEDS_VERIFICATION) and editorial_only:
            issues.append(
                _issue(
                    "STATUS_SOURCE_MISMATCH",
                    path,
                    f"{obj.status} requires a citation of a published source",
                )
            )
    return issues


# --- items ---


def _unitless_numbers(value: JsonValue, key: str, has_unit: bool) -> Iterator[str]:
    has_unit = has_unit or key.endswith(UNIT_SUFFIXES)
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, int | float):
        if not has_unit:
            yield key
    elif isinstance(value, list):
        for v in value:
            yield from _unitless_numbers(v, key, has_unit)
    else:
        for k, v in value.items():
            yield from _unitless_numbers(v, k, has_unit)


def _bad_scales(value: JsonValue, key: str) -> Iterator[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _bad_scales(v, k)
    elif isinstance(value, list):
        for v in value:
            yield from _bad_scales(v, key)
    elif "scale" in key and not (isinstance(value, str) and SCALE_PATTERN.match(value)):
        yield key


def _check_items(registry: KnowledgeRegistry, pack: LoadedPack) -> list[Issue]:
    issues: list[Issue] = []
    ids = {i.id for _, i in pack.items}
    classes = registry.classes()
    terms = registry.terms()
    for _, item in pack.items:
        path = pointer("packs", pack.ref, "items", item.id)
        for key in sorted(set(_unitless_numbers(item.params, "", False))):
            issues.append(
                _issue(
                    "PARAM_UNIT_MISSING",
                    f"{path}/params",
                    f"numeric parameter {key!r} has no unit suffix",
                    f"Use one of {', '.join(UNIT_SUFFIXES)} in the key or an enclosing key.",
                )
            )
        for key in sorted(set(_bad_scales(item.params, ""))):
            issues.append(
                _issue(
                    "PARAM_SCALE_FORMAT",
                    f"{path}/params",
                    f"scale parameter {key!r} must be a quoted ratio such as '1:100'",
                    "Unquoted YAML ratios can be parsed as numbers.",
                )
            )
        if item.status == Status.APPROVED and item.confidence == "low":
            issues.append(
                _issue("APPROVED_LOW_CONFIDENCE", path, "low-confidence items cannot be approved")
            )
        for ref in item.related:
            known = ref in classes if ref.startswith("class.") else ref in terms
            if not (ref.startswith(("class.", "term.")) and known) and ref not in ids:
                issues.append(_issue("REF_UNKNOWN", f"{path}/related", f"unknown {ref}"))
        if item.superseded_by is not None and item.superseded_by not in ids:
            issues.append(
                _issue("REF_UNKNOWN", f"{path}/superseded_by", f"unknown {item.superseded_by}")
            )
    return issues


# --- ontology ---


def _check_ontology(registry: KnowledgeRegistry) -> list[Issue]:
    issues: list[Issue] = []
    classes = registry.classes()
    for cid, cls in classes.items():
        path = pointer("classes", cid)
        if cls.parent is not None and cls.parent not in classes:
            issues.append(_issue("CLASS_PARENT_UNKNOWN", path, f"unknown parent {cls.parent}"))
        seen = {cid}
        parent = cls.parent
        while parent is not None and parent in classes:
            if parent in seen:
                issues.append(_issue("CLASS_CYCLE", path, f"{cid} is its own ancestor"))
                break
            seen.add(parent)
            parent = classes[parent].parent
        b = cls.model_binding
        if b is not None:
            if b.element_type is not None and b.element_type not in ELEMENT_TYPES:
                issues.append(
                    _issue("BINDING_UNKNOWN", path, f"no element type {b.element_type!r}")
                )
            if b.building_type is not None and b.building_type not in BUILDING_TYPES:
                issues.append(
                    _issue("BINDING_UNKNOWN", path, f"no building type {b.building_type!r}")
                )
    for rid, rel in registry.relationships().items():
        for ref in [*rel.source_classes, *rel.target_classes]:
            if ref not in classes:
                issues.append(
                    _issue("REL_CLASS_UNKNOWN", pointer("relationships", rid), f"unknown {ref}")
                )
    issues += _check_coverage(classes.values(), registry)
    return issues


def _check_coverage(classes: Iterable[OntologyClass], registry: KnowledgeRegistry) -> list[Issue]:
    """Every canonical model vocabulary value is bound by exactly one primary class."""
    bound: Counter[str] = Counter()
    for cls in classes:
        b = cls.model_binding
        if b is None or not b.is_primary:
            continue
        if b.element_type is not None:
            bound[f"element_type:{b.element_type}"] += 1
        elif b.room_type is not None:
            bound[f"room_type:{b.room_type}"] += 1
        elif b.building_type is not None:
            bound[f"building_type:{b.building_type}"] += 1
        elif b.level:
            bound["level"] += 1
    rel_bound = Counter(str(r.model_binding) for r in registry.relationships().values())
    expected = [
        *(f"element_type:{t}" for t in sorted(ELEMENT_TYPES)),
        *(f"room_type:{t}" for t in RoomType),
        *(f"building_type:{t}" for t in sorted(BUILDING_TYPES)),
        "level",
    ]
    issues: list[Issue] = []
    if not registry.packs:
        return issues
    for key in expected:
        if bound[key] != 1:
            issues.append(
                _issue(
                    "ONTOLOGY_COVERAGE",
                    pointer("classes"),
                    f"{key} is bound by {bound[key]} primary classes (expected exactly 1)",
                    "Add or fix the class in the core ontology when the building model changes.",
                )
            )
    for kind in RelationshipKind:
        if rel_bound[str(kind)] != 1:
            issues.append(
                _issue(
                    "ONTOLOGY_COVERAGE",
                    pointer("relationships"),
                    f"relationship {kind} is defined {rel_bound[str(kind)]} times (expected 1)",
                )
            )
    return issues


# --- glossary ---


def _check_glossary(registry: KnowledgeRegistry) -> list[Issue]:
    issues: list[Issue] = []
    classes = registry.classes()
    for pack in registry.packs.values():
        visible = {t.id for t in pack.terms}
        for dep in _dependency_closure(registry, pack.ref):
            if dep in registry.packs:
                visible |= {t.id for t in registry.packs[dep].terms}
        for term in pack.terms:
            if term.class_ref is not None and term.class_ref not in classes:
                issues.append(
                    _issue(
                        "TERM_CLASS_UNKNOWN",
                        pointer("packs", pack.ref, "terms", term.id),
                        f"unknown {term.class_ref}",
                    )
                )
        for lt in pack.localized:
            if lt.term_id not in visible:
                issues.append(
                    _issue(
                        "LOCALIZED_TERM_UNKNOWN",
                        pointer("packs", pack.ref, "localized", f"{lt.term_id}/{lt.locale}"),
                        f"{lt.term_id} is not defined in {pack.ref} or its dependencies",
                    )
                )
    return issues


# --- drawing profiles ---


def _check_drawing_profiles(pack: LoadedPack) -> list[Issue]:
    issues: list[Issue] = []
    by_id = {i.id: i for _, i in pack.items}
    grouped: set[str] = set()
    scope = pack.manifest.scope
    for profile in pack.drawing_profiles:
        path = pointer("packs", pack.ref, "drawing_profiles", profile.ref)
        if scope.kind != PackScopeKind.DRAWING_CONVENTION_PROFILE or (
            scope.drawing_profile != profile.id
        ):
            issues.append(
                _issue(
                    "PROFILE_SCOPE_MISMATCH",
                    path,
                    f"{profile.ref} must live in a drawing-convention pack scoped to {profile.id}",
                )
            )
        for topic, refs in profile.topics.items():
            for ref in refs:
                item = by_id.get(ref)
                if item is None or item.category != KnowledgeCategory.DRAWING:
                    issues.append(
                        _issue(
                            "PROFILE_ITEM_UNKNOWN",
                            f"{path}/topics/{topic}",
                            f"{ref} is not a drawing item of {pack.ref}",
                        )
                    )
                grouped.add(ref)
    if pack.drawing_profiles:
        for _, item in pack.items:
            if item.category == KnowledgeCategory.DRAWING and item.id not in grouped:
                issues.append(
                    _issue(
                        "DRAWING_ITEM_UNGROUPED",
                        pointer("packs", pack.ref, "items", item.id),
                        f"{item.id} is not assigned to a topic of the pack's drawing profile",
                    )
                )
    return issues


# --- region profiles ---


def _check_regions(
    registry: KnowledgeRegistry, known_rules_profiles: frozenset[str]
) -> list[Issue]:
    issues: list[Issue] = []
    drawing_profiles = {
        d.ref: pack.ref for pack in registry.packs.values() for d in pack.drawing_profiles
    }
    for ref, region in registry.regions.items():
        path = pointer("regions", ref)
        if region.rules_profile not in known_rules_profiles:
            issues.append(
                _issue(
                    "REGION_RULES_PROFILE_UNKNOWN",
                    path,
                    f"rules profile {region.rules_profile} not found in data/rules-profiles",
                )
            )
        for pack_ref in region.knowledge_packs:
            if pack_ref not in registry.packs:
                issues.append(_issue("REGION_PACK_UNKNOWN", path, f"unknown pack {pack_ref}"))
        if region.drawing_profile is not None:
            owner = drawing_profiles.get(region.drawing_profile)
            if owner is None:
                issues.append(
                    _issue(
                        "REGION_DRAWING_PROFILE_UNKNOWN",
                        path,
                        f"unknown drawing profile {region.drawing_profile}",
                    )
                )
            elif owner not in region.knowledge_packs:
                issues.append(
                    _issue(
                        "REGION_PACK_MISSING",
                        path,
                        f"drawing profile {region.drawing_profile} needs pack {owner}",
                    )
                )
    return issues
