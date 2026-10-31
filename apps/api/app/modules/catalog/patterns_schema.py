"""Layout pattern records (Design Intelligence V1, docs/knowledge.md §3.6) and their checks.

A pattern record has the provenance and review lifecycle of every knowledge object. Its
recipe reuses the building-level shapes (`building.patterns`), so a record and the snapshot
copied into generation reports cannot disagree on structure. Resolution: catalog/patterns.py.
"""

from collections import Counter
from typing import TYPE_CHECKING

from pydantic import Field

from app.modules.building.issues import Issue, pointer
from app.modules.building.patterns import (
    EngineSupport,
    PatternApplicability,
    PatternId,
    PatternRecipe,
    PatternStatement,
    PatternTrigger,
    StatementKind,
)
from app.modules.catalog.provenance import (
    KnowledgeModel,
    Paraphrase,
    Provenanced,
    ShortText,
    SourceKind,
    Status,
    Usage,
)

if TYPE_CHECKING:
    from app.modules.catalog.registry import KnowledgeRegistry


class PatternRecord(Provenanced):
    id: PatternId
    name: ShortText
    intent: Paraphrase
    context: Paraphrase
    relationships: Paraphrase
    circulation: Paraphrase
    privacy: Paraphrase
    daylight: Paraphrase
    facade: Paraphrase
    tradeoffs: list[Paraphrase] = Field(default_factory=list)
    limitations: list[Paraphrase] = Field(default_factory=list)
    statements: list[PatternStatement] = Field(min_length=1)
    engine_support: EngineSupport
    applicability: PatternApplicability
    recipe: PatternRecipe = Field(default_factory=PatternRecipe)
    usage: Usage = Usage.RUNTIME_CANDIDATE


class PatternsDocument(KnowledgeModel):
    patterns: list[PatternRecord] = Field(min_length=1)


def _issue(code: str, path: str, message: str) -> Issue:
    return Issue(severity="error", code=code, path=path, message=message)


def check_patterns(registry: "KnowledgeRegistry") -> list[Issue]:
    """Unique ids; source rules need a reviewed published source; unsupported patterns are
    reference-only and carry no recipe; supported ones name their limitations when partial."""
    issues: list[Issue] = []
    records = [(p.ref, r) for p in registry.packs.values() for r in p.patterns]
    for dup, n in Counter(r.id for _, r in records).items():
        if n > 1:
            issues.append(_issue("DUPLICATE_ID", pointer("patterns"), f"{dup} defined {n}x"))
    for pack_ref, r in records:
        path = pointer("packs", pack_ref, "patterns", r.id)
        published = [
            c
            for c in r.provenance
            if (s := registry.sources.get(c.source)) is not None and s.kind != SourceKind.EDITORIAL
        ]
        has_rule = any(s.kind == StatementKind.SOURCE_RULE for s in r.statements)
        if has_rule and (not published or r.status not in (Status.REVIEWED, Status.APPROVED)):
            issues.append(
                _issue(
                    "PATTERN_RULE_UNSOURCED",
                    path,
                    "source_rule statements need a cited published source and a review; "
                    "state it as a principle or heuristic instead",
                )
            )
        if not any(s.kind == StatementKind.HEURISTIC for s in r.statements) and (
            r.recipe != PatternRecipe()
        ):
            issues.append(
                _issue(
                    "PATTERN_RECIPE_UNEXPLAINED",
                    path,
                    "a recipe is BuildAI's heuristic: add a heuristic statement explaining it",
                )
            )
        if r.engine_support == EngineSupport.NONE:
            if r.usage != Usage.REFERENCE_ONLY or r.recipe != PatternRecipe():
                issues.append(
                    _issue(
                        "PATTERN_UNSUPPORTED_RUNTIME",
                        path,
                        "a pattern the engine cannot realise is reference_only and has no recipe",
                    )
                )
        elif r.engine_support == EngineSupport.PARTIAL and not r.limitations:
            issues.append(
                _issue("PATTERN_LIMITATIONS_MISSING", path, "partial support must list limitations")
            )
        if r.recipe.topology is not None and r.applicability.storeys != [1]:
            issues.append(
                _issue(
                    "PATTERN_TOPOLOGY_STOREYS",
                    path,
                    "the engine generates other footprint topologies for single-storey houses "
                    "only: set applicability.storeys to [1]",
                )
            )
        if PatternTrigger.COURTYARD in r.applicability.triggers and (
            r.engine_support != EngineSupport.NONE
        ):
            issues.append(
                _issue(
                    "PATTERN_TRIGGER_UNSUPPORTED",
                    path,
                    "the engine cannot detect or build courtyards yet",
                )
            )
    return issues
