"""The single issue shape used by spec validation, rules evaluation and model validation.

`path` is a JSON pointer into the validated document (spec or model) so the UI can point at the
offending field; `rule_ref` (e.g. `generic-residential@1:stairs.riser_m`) makes every rules
finding traceable to the exact rule that produced it. Geometric findings (K2.5) name the
violated geometric constraint instead (`constraint`, e.g. `opening.within_length`; catalog in
building/constraints.py), the other elements involved (`related_ids`) and, where a number was
compared, what was measured against which limit (`measure`) — so a report can say what is wrong,
where, why, and which constraint failed without parsing `message`.
"""

import uuid
from typing import Literal

from pydantic import Field

from app.modules.building.primitives import Frozen

Severity = Literal["error", "warning"]


class Measure(Frozen):
    """A measured quantity and the limit it violates (SI units)."""

    quantity: str = Field(min_length=1, max_length=80)
    actual: float
    limit: float
    unit: Literal["m", "m2"]


class Issue(Frozen):
    severity: Severity
    code: str
    path: str
    message: str
    suggestion: str | None = None
    rule_ref: str | None = None
    element_id: uuid.UUID | None = None
    constraint: str | None = None
    related_ids: list[uuid.UUID] = Field(default_factory=list)
    measure: Measure | None = None


def errors[T: Issue](issues: list[T]) -> list[T]:
    return [i for i in issues if i.severity == "error"]


def pointer(*parts: str | int) -> str:
    """Build a JSON pointer, escaping `~` and `/` in segments."""
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts) or ""
