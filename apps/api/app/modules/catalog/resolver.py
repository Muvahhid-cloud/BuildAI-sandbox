"""Resolve a role mapping into a TypeSet for the layout engine (Phase 3.5 K2).

Gating (docs/knowledge.md §3.4): a role gets a type only if the mapping, the type, its family and
its assembly are all APPROVED, the type is a runtime candidate, and every knowledge item any of
them is derived from is approved. Anything else is skipped with a recorded reason — never
substituted. With nothing approved the result has no type set and generation stays untyped.

Pure and deterministic: roles are visited in sorted order, snapshots are sorted by id, and each
snapshot carries the sha256 of the canonical JSON of the catalog record it was copied from.
Rules are not checked here (catalog does not depend on rules); the generation pipeline runs
`rules.type_checks.check_type_set` on the result and refuses invalid types instead of resizing.
"""

import hashlib
import json
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.modules.building.types import AssemblySnapshot, TypeSet, TypeSnapshot
from app.modules.catalog.components import AssemblyRecord, DerivedFrom, TypeRecord
from app.modules.catalog.provenance import Status, Usage
from app.modules.catalog.registry import KnowledgeRegistry

DEFAULT_MAPPING = "mapping.generic"


@dataclass(frozen=True)
class TypeResolution:
    type_set: TypeSet | None
    skipped: dict[str, str] = field(default_factory=dict)  # role -> reason


def record_sha256(record: BaseModel) -> str:
    text = json.dumps(
        record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _unapproved_knowledge(source: DerivedFrom, approved: frozenset[str]) -> list[str]:
    return [ref for ref in source.knowledge if ref not in approved]


def _assembly_snapshot(a: AssemblyRecord, pack: str) -> AssemblySnapshot:
    return AssemblySnapshot(
        id=a.id,
        kind=a.kind,
        name=a.name,
        layers=list(a.layers),
        total_thickness=a.total_thickness,
        source=pack,
        content_sha256=record_sha256(a),
    )


def _type_snapshot(t: TypeRecord, pack: str) -> TypeSnapshot:
    return TypeSnapshot(
        id=t.id,
        family=t.family,
        name=t.name,
        params=t.params,
        assembly_id=t.assembly,
        source=pack,
        content_sha256=record_sha256(t),
    )


def resolve_type_set(
    registry: KnowledgeRegistry, *, mapping_id: str = DEFAULT_MAPPING
) -> TypeResolution:
    mapping = registry.role_mappings().get(mapping_id)
    if mapping is None:
        return TypeResolution(None, {"*": f"no role mapping {mapping_id}"})
    if mapping.status != Status.APPROVED:
        return TypeResolution(None, {"*": f"{mapping_id} is {mapping.status}, not approved"})
    approved = frozenset(e.ref for e in registry.approved_items())
    families = registry.families()
    types = registry.component_types()
    assemblies = registry.assemblies()

    roles: dict[str, str] = {}
    type_snaps: dict[str, TypeSnapshot] = {}
    assembly_snaps: dict[str, AssemblySnapshot] = {}
    skipped: dict[str, str] = {}
    for role in sorted(mapping.roles):
        type_id = mapping.roles[role]
        t = types.get(type_id)
        reason: str | None = None
        assembly: AssemblyRecord | None = None
        if t is None:
            reason = f"unknown type {type_id}"
        elif t.status != Status.APPROVED:
            reason = f"{type_id} is {t.status}, not approved"
        elif t.usage != Usage.RUNTIME_CANDIDATE:
            reason = f"{type_id} is reference only"
        elif (family := families.get(t.family)) is None or family.status != Status.APPROVED:
            reason = f"family {t.family} is not approved"
        elif missing := _unapproved_knowledge(t.derived_from, approved):
            reason = f"{type_id} is derived from unapproved knowledge {', '.join(missing)}"
        elif t.assembly is not None:
            assembly = assemblies.get(t.assembly)
            if assembly is None or assembly.status != Status.APPROVED:
                reason = f"assembly {t.assembly} is not approved"
            elif missing := _unapproved_knowledge(assembly.derived_from, approved):
                reason = f"{t.assembly} is derived from unapproved knowledge {', '.join(missing)}"
        if reason is not None or t is None:
            skipped[role] = reason or "unresolved"
            continue
        roles[role] = t.id
        type_snaps[t.id] = _type_snapshot(t, registry.pack_of(t.id) or mapping_id)
        if assembly is not None:
            assembly_snaps[assembly.id] = _assembly_snapshot(
                assembly, registry.pack_of(assembly.id) or mapping_id
            )
    if not roles:
        return TypeResolution(None, skipped)
    pack = registry.pack_of(mapping.id)
    type_set = TypeSet(
        source=pack or "unknown@1",
        mapping=mapping.id,
        roles=roles,
        types=[type_snaps[k] for k in sorted(type_snaps)],
        assemblies=[assembly_snaps[k] for k in sorted(assembly_snaps)],
    )
    return TypeResolution(type_set, skipped)
