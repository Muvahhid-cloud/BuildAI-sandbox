"""Read-only, typed access to loaded knowledge.

References follow the rules-profile style: items are `<pack>@<version>:<item id>`
(e.g. `spds-georgievsky-2004@1:drawing.axes.labeling`); ontology classes (`class.*`) and
glossary terms (`term.*`) share one namespace across packs.

Consumers that act on knowledge (engines, AI) must go through `approved_items()`: unreviewed
knowledge is visible for review and documentation, never for runtime decisions.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field

from app.modules.catalog.components import (
    AssemblyRecord,
    DesignSystemRecord,
    FamilyRecord,
    RoleMapping,
    TypeRecord,
)
from app.modules.catalog.patterns_schema import PatternRecord
from app.modules.catalog.provenance import Source, Status, Usage
from app.modules.catalog.schemas import (
    DrawingProfile,
    KnowledgeCategory,
    KnowledgeItem,
    LocalizedTerm,
    OntologyClass,
    PackManifest,
    RegionProfile,
    RelationshipDefinition,
    Term,
)


@dataclass(frozen=True)
class LoadedPack:
    manifest: PackManifest
    directory: str  # e.g. "packs/core.v1"
    items: tuple[tuple[str, KnowledgeItem], ...] = ()  # (file, item)
    classes: tuple[OntologyClass, ...] = ()
    relationships: tuple[RelationshipDefinition, ...] = ()
    terms: tuple[Term, ...] = ()
    localized: tuple[LocalizedTerm, ...] = ()
    drawing_profiles: tuple[DrawingProfile, ...] = ()
    families: tuple[FamilyRecord, ...] = ()
    types: tuple[TypeRecord, ...] = ()
    assemblies: tuple[AssemblyRecord, ...] = ()
    role_mappings: tuple[RoleMapping, ...] = ()
    design_systems: tuple[DesignSystemRecord, ...] = ()  # K3
    patterns: tuple[PatternRecord, ...] = ()  # layout patterns (Design Intelligence V1)
    extra_files: tuple[str, ...] = ()  # YAML files present but not listed in the manifest

    @property
    def ref(self) -> str:
        return self.manifest.ref


@dataclass(frozen=True)
class RegistryItem:
    pack: str  # pack ref
    item: KnowledgeItem

    @property
    def ref(self) -> str:
        return f"{self.pack}:{self.item.id}"


@dataclass(frozen=True)
class KnowledgeRegistry:
    sources: Mapping[str, Source]
    packs: Mapping[str, LoadedPack]  # by pack ref, sorted
    regions: Mapping[str, RegionProfile]  # by region ref, sorted
    _items: dict[str, RegistryItem] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for pack in self.packs.values():
            for _, item in pack.items:
                entry = RegistryItem(pack.ref, item)
                self._items.setdefault(entry.ref, entry)

    # --- items ---
    def item(self, ref: str) -> KnowledgeItem:
        return self._items[ref].item

    def items(
        self,
        *,
        pack: str | None = None,
        category: KnowledgeCategory | None = None,
        status: Status | None = None,
    ) -> Iterator[RegistryItem]:
        for entry in self._items.values():
            if pack is not None and entry.pack != pack:
                continue
            if category is not None and entry.item.category != category:
                continue
            if status is not None and entry.item.status != status:
                continue
            yield entry

    def approved_items(self) -> list[RegistryItem]:
        """The only knowledge an engine or AI prompt may consume."""
        return [
            e
            for e in self._items.values()
            if e.item.status == Status.APPROVED and e.item.usage == Usage.RUNTIME_CANDIDATE
        ]

    # --- ontology & glossary (one namespace across packs) ---
    def classes(self) -> dict[str, OntologyClass]:
        return {c.id: c for p in self.packs.values() for c in p.classes}

    def relationships(self) -> dict[str, RelationshipDefinition]:
        return {r.id: r for p in self.packs.values() for r in p.relationships}

    def terms(self) -> dict[str, Term]:
        return {t.id: t for p in self.packs.values() for t in p.terms}

    def localized_terms(self, locale: str) -> list[LocalizedTerm]:
        return [t for p in self.packs.values() for t in p.localized if t.locale == locale]

    # --- profiles ---
    def drawing_profiles(self) -> dict[str, DrawingProfile]:
        return {d.ref: d for p in self.packs.values() for d in p.drawing_profiles}

    def drawing_profile(self, ref: str) -> DrawingProfile:
        return self.drawing_profiles()[ref]

    # --- components (K2), one namespace across packs ---
    def families(self) -> dict[str, FamilyRecord]:
        return {f.id: f for p in self.packs.values() for f in p.families}

    def component_types(self) -> dict[str, TypeRecord]:
        return {t.id: t for p in self.packs.values() for t in p.types}

    def assemblies(self) -> dict[str, AssemblyRecord]:
        return {a.id: a for p in self.packs.values() for a in p.assemblies}

    def role_mappings(self) -> dict[str, RoleMapping]:
        return {m.id: m for p in self.packs.values() for m in p.role_mappings}

    def design_systems(self) -> dict[str, DesignSystemRecord]:
        return {d.id: d for p in self.packs.values() for d in p.design_systems}

    def layout_patterns(self) -> dict[str, PatternRecord]:
        return {r.id: r for p in self.packs.values() for r in p.patterns}

    def pack_of(self, record_id: str) -> str | None:
        """The pack ref that defines a component record (family/type/assembly/mapping/design
        system)."""
        for pack in self.packs.values():
            ids = [
                *(f.id for f in pack.families),
                *(t.id for t in pack.types),
                *(a.id for a in pack.assemblies),
                *(m.id for m in pack.role_mappings),
                *(d.id for d in pack.design_systems),
                *(r.id for r in pack.patterns),
            ]
            if record_id in ids:
                return pack.ref
        return None

    def region(self, ref: str) -> RegionProfile:
        return self.regions[ref]
