"""Pattern library resolution (Design Intelligence V1, docs/knowledge.md §3.6).

Turns pattern records into `building.patterns.LayoutPattern` snapshots for the generation
pipeline. Unlike types and design systems (approved only), layout patterns are SOFT
heuristics: draft records are included, carry their status into every snapshot and report,
and can never create or relax a hard requirement (the layout engine only scores them).
Deprecated and reference-only records are left out.
"""

from app.modules.building.patterns import LayoutPattern, PatternLibrary
from app.modules.catalog.provenance import Status, Usage
from app.modules.catalog.registry import KnowledgeRegistry
from app.modules.catalog.resolver import record_sha256


def pattern_library(registry: KnowledgeRegistry) -> PatternLibrary:
    patterns: list[LayoutPattern] = []
    for pattern_id, record in sorted(registry.layout_patterns().items()):
        if record.status == Status.DEPRECATED or record.usage != Usage.RUNTIME_CANDIDATE:
            continue
        patterns.append(
            LayoutPattern(
                id=pattern_id,
                name=record.name,
                source=registry.pack_of(pattern_id) or "unknown@1",
                status=record.status.value,
                content_sha256=record_sha256(record),
                intent=record.intent,
                context=record.context,
                relationships=record.relationships,
                circulation=record.circulation,
                privacy=record.privacy,
                daylight=record.daylight,
                facade=record.facade,
                tradeoffs=list(record.tradeoffs),
                limitations=list(record.limitations),
                statements=list(record.statements),
                engine_support=record.engine_support,
                applicability=record.applicability,
                recipe=record.recipe,
            )
        )
    return PatternLibrary(patterns=patterns)
