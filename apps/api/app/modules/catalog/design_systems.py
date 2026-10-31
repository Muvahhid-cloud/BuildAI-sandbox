"""Design systems (Phase 3.5 K3, docs/knowledge.md §3.5).

A design system is an editorial, region-neutral aesthetic grouping of compatible choices:
component types (through a role mapping), roofs, window sizes, facade materials and colors,
interior finishes and a furniture palette — all as allow-lists plus defaults. It is NOT a
building code, an engineering rule or a claim of architectural correctness, and it contains no
construction data of its own (types and assemblies come from its role mapping).

Records follow the component lifecycle (draft -> reviewed -> approved). Resolution
(`resolve_design`) makes a system usable only when the system, its role mapping and every type
the mapping resolves to are APPROVED; otherwise it is reported unavailable with the reason —
never substituted. The result is a `building.design.DesignSystemSnapshot` (sorted, hashed), the
only form in which the layout engine and the AI see a design system.
"""

from app.modules.building.design import (
    DesignCatalog,
    DesignSystemSnapshot,
    UnavailableDesignSystem,
)
from app.modules.catalog.components import DesignSystemRecord
from app.modules.catalog.provenance import Status
from app.modules.catalog.registry import KnowledgeRegistry
from app.modules.catalog.resolver import TypeResolution, record_sha256, resolve_type_set


def _snapshot(record: DesignSystemRecord, pack: str, types: TypeResolution) -> DesignSystemSnapshot:
    if types.type_set is None:
        raise ValueError(f"{record.id}: no type set")
    return DesignSystemSnapshot(
        id=record.id,
        name=record.name,
        source=pack,
        content_sha256=record_sha256(record),
        style_tags=list(record.style_tags),
        interior_styles=list(record.interior_styles),
        role_mapping=record.role_mapping,
        type_ids=sorted(t.id for t in types.type_set.types),
        roof=record.roof,
        windows=record.windows,
        facade=record.facade,
        finishes=record.finishes,
        furniture=record.furniture,
    )


class DesignResolution:
    def __init__(
        self,
        snapshot: DesignSystemSnapshot | None,
        types: TypeResolution | None,
        reason: str | None,
    ) -> None:
        self.snapshot = snapshot
        self.types = types
        self.reason = reason


def resolve_design(registry: KnowledgeRegistry, design_id: str) -> DesignResolution:
    """The usable snapshot + type set of a design system, or the reason it is unavailable."""
    record = registry.design_systems().get(design_id)
    if record is None:
        return DesignResolution(None, None, f"unknown design system {design_id}")
    if record.status != Status.APPROVED:
        return DesignResolution(
            None, None, f"it is {record.status.value}; a person must review and approve it"
        )
    types = resolve_type_set(registry, mapping_id=record.role_mapping)
    if types.type_set is None or types.skipped:
        first = next(iter(sorted(types.skipped.items())), ("*", "no types resolved"))
        return DesignResolution(
            None,
            types,
            f"its components are not all approved ({first[0]}: {first[1]})",
        )
    pack = registry.pack_of(record.id) or "unknown@1"
    return DesignResolution(_snapshot(record, pack, types), types, None)


def design_catalog(registry: KnowledgeRegistry) -> DesignCatalog:
    """Every design system, split into usable snapshots and unavailable ones (sorted by id)."""
    available: list[DesignSystemSnapshot] = []
    unavailable: list[UnavailableDesignSystem] = []
    for design_id, record in sorted(registry.design_systems().items()):
        resolution = resolve_design(registry, design_id)
        if resolution.snapshot is not None:
            available.append(resolution.snapshot)
        else:
            unavailable.append(
                UnavailableDesignSystem(
                    id=design_id, name=record.name, reason=resolution.reason or "unavailable"
                )
            )
    return DesignCatalog(available=available, unavailable=unavailable)
