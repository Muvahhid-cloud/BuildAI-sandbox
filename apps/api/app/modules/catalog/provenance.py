"""Provenance: where a piece of knowledge comes from and how far it can be trusted.

Every knowledge object carries at least one `Citation` to a `Source`. Sources are records
about a document (bibliography, fingerprint, usage policy) — the document itself is never
stored in the repository, and knowledge is always paraphrased, never quoted.
"""

import re
from datetime import date
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

SOURCE_ID = r"^[a-z][a-z0-9-]*$"
SourceId = Annotated[str, StringConstraints(pattern=SOURCE_ID, max_length=64)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=200)]
Paraphrase = Annotated[str, StringConstraints(min_length=1, max_length=500)]
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SourceKind(StrEnum):
    REFERENCE_HANDBOOK = "reference_handbook"  # a published book summarising standards
    STANDARD = "standard"  # a standard document itself (not used yet)
    EDITORIAL = "editorial"  # content authored by the BuildAI team (mappings, definitions)


class Status(StrEnum):
    """Review lifecycle. Only `approved` knowledge may ever be consumed by engines or AI."""

    DRAFT = "draft"  # authored by the team (editorial sources only), not reviewed
    EXTRACTED = "extracted"  # taken from a source by a person or AI, not reviewed
    NEEDS_VERIFICATION = "needs_verification"  # extracted, but legibility/interpretation doubtful
    REVIEWED = "reviewed"  # checked against the cited pages by a person
    APPROVED = "approved"  # reviewed and released for runtime use
    DEPRECATED = "deprecated"  # kept for provenance; see superseded_by


UNREVIEWED = frozenset({Status.DRAFT, Status.EXTRACTED, Status.NEEDS_VERIFICATION})


class Usage(StrEnum):
    RUNTIME_CANDIDATE = "runtime_candidate"  # may be used by engines/AI once approved
    REFERENCE_ONLY = "reference_only"  # documented for context; never consumed at runtime


class Confidence(StrEnum):
    HIGH = "high"  # explicit, legible statement in the source
    MEDIUM = "medium"  # read from a figure/table, or requires interpretation
    LOW = "low"  # partly illegible in the source artifact


class SupportKind(StrEnum):
    """Which aspect of a knowledge object a citation backs."""

    EXISTENCE = "existence"  # the concept exists / is named in the source
    TERM = "term"  # the wording of a term
    STATEMENT = "statement"  # the paraphrased rule or convention
    PARAMS = "params"  # the numeric/tabular parameters
    DEFINITION = "definition"  # a definition written for BuildAI
    MAPPING = "mapping"  # a mapping to the model, IFC or another vocabulary


class Title(KnowledgeModel):
    original: ShortText
    en: ShortText | None = None


class SourceArtifact(KnowledgeModel):
    """Fingerprint of the document the knowledge was read from (never stored in the repo)."""

    stored_in_repo: bool = False
    format: ShortText
    sha256: str
    artifact_page_count: int = Field(ge=1)
    page_map: ShortText  # how artifact pages map to printed page numbers

    @model_validator(mode="after")
    def _checks(self) -> "SourceArtifact":
        if self.stored_in_repo:
            raise ValueError("source documents are never stored in the repository")
        if not SHA256.match(self.sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return self


class UsagePolicy(KnowledgeModel):
    paraphrase_only: bool = True
    reproduce_figures: bool = False
    note: Paraphrase | None = None


class Source(KnowledgeModel):
    id: SourceId
    kind: SourceKind
    title: Title
    authors: list[ShortText] = Field(default_factory=list)
    publisher: ShortText | None = None
    publication_year: int | None = Field(default=None, ge=1800, le=2100)
    isbn: ShortText | None = None
    language: Annotated[str, StringConstraints(pattern=r"^[a-z]{2}$")]
    page_count: int | None = Field(default=None, ge=1)  # printed pages; None = not paginated
    basis: list[ShortText] = Field(default_factory=list)  # standards systems it follows
    jurisdiction_context: list[Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]] = Field(
        default_factory=list
    )
    temporal_note: Paraphrase | None = None
    scope_note: Paraphrase | None = None
    artifact: SourceArtifact | None = None
    usage_policy: UsagePolicy = Field(default_factory=UsagePolicy)

    @model_validator(mode="after")
    def _checks(self) -> "Source":
        if self.kind == SourceKind.EDITORIAL:
            return self
        if not self.authors or self.publication_year is None or self.page_count is None:
            raise ValueError("published sources need authors, publication_year and page_count")
        if not self.usage_policy.paraphrase_only or self.usage_policy.reproduce_figures:
            raise ValueError("published sources are paraphrased only; figures are not reproduced")
        return self

    @property
    def paginated(self) -> bool:
        return self.page_count is not None


class Citation(KnowledgeModel):
    source: SourceId
    pages: list[int] = Field(default_factory=list)  # printed page numbers, not artifact pages
    section: ShortText | None = None
    figures: list[ShortText] = Field(default_factory=list)
    tables: list[ShortText] = Field(default_factory=list)
    cites: list[ShortText] = Field(default_factory=list)  # standards the source itself invokes
    supports: list[SupportKind] = Field(default_factory=lambda: [SupportKind.STATEMENT])
    note: Paraphrase | None = None

    @model_validator(mode="after")
    def _checks(self) -> "Citation":
        if any(p < 1 for p in self.pages):
            raise ValueError("page numbers start at 1")
        if len(set(self.supports)) != len(self.supports) or not self.supports:
            raise ValueError("supports must be a non-empty list without duplicates")
        return self


class Review(KnowledgeModel):
    reviewed_by: ShortText
    reviewed_on: date
    note: Paraphrase | None = None


class Provenanced(KnowledgeModel):
    """Fields shared by every knowledge object."""

    provenance: list[Citation] = Field(min_length=1)
    status: Status
    review: Review | None = None
    superseded_by: str | None = None

    @model_validator(mode="after")
    def _lifecycle(self) -> "Provenanced":
        if self.status in (Status.REVIEWED, Status.APPROVED) and self.review is None:
            raise ValueError(f"status {self.status} requires a review record")
        if self.status in UNREVIEWED and self.review is not None:
            raise ValueError(f"status {self.status} cannot carry a review record")
        if self.superseded_by is not None and self.status != Status.DEPRECATED:
            raise ValueError("superseded_by is only valid on deprecated knowledge")
        return self
