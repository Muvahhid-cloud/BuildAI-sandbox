"""Natural-language change request -> validated ModificationDraft (docs/ai-pipeline.md §11).

    provider call -> JSON object? -> ModificationDraft (Pydantic) -> references exist in the digest?
                  -> invalid: at most `max_repairs` repair calls with the issues
                  -> still invalid: ModificationInterpretationError (never accepted silently)

The draft only says what the user asked for; turning it into operations, asking questions and
validating the edited model is the deterministic resolver's job (modules/modification). No
database, no geometry.
"""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from app.modules.ai.modification_context import ModificationContext
from app.modules.ai.prompts.modification import (
    MODIFICATION_PROMPT_VERSION,
    build_modification_repair_request,
    build_modification_request,
)
from app.modules.ai.providers.base import AIProvider
from app.modules.ai.schemas.modification import ModificationDraft
from app.modules.ai.structured import StructuredResult


class ModificationInterpretationError(Exception):
    """The provider's answer could not be validated, even after the repair calls."""

    code = "AI_MODIFICATION_INVALID"

    def __init__(self, message: str, issues: list[str]) -> None:
        super().__init__(message)
        self.message = message
        self.issues = issues


@dataclass(frozen=True)
class ModificationInterpretation:
    draft: ModificationDraft
    provider: str
    model: str
    prompt_version: str
    attempts: int


def draft_issues(
    data: object, context: ModificationContext
) -> tuple[ModificationDraft | None, list[str]]:
    """Validate a structured answer: the schema, then every reference against the digest."""
    if not isinstance(data, dict):
        return None, ["the answer is not a JSON object"]
    try:
        draft = ModificationDraft.model_validate(data)
    except ValidationError as err:
        return None, [
            f"{'/'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in err.errors()
        ]
    rooms = {r.ref for r in context.rooms}
    openings = {o.ref for o in context.openings}
    issues: list[str] = []
    for i, change in enumerate(draft.changes):
        for field_name in ("room", "other_room"):
            ref = getattr(change, field_name)
            if ref is not None and ref not in rooms:
                issues.append(f"changes/{i}/{field_name}: {ref!r} is not a room reference")
        if change.opening is not None and change.opening not in openings:
            issues.append(f"changes/{i}/opening: {change.opening!r} is not an opening reference")
    return (draft if not issues else None), issues


async def interpret_modification(
    provider: AIProvider,
    prompt: str,
    *,
    context: ModificationContext,
    max_tokens: int,
    max_repairs: int,
) -> ModificationInterpretation:
    request = build_modification_request(prompt, context=context, max_tokens=max_tokens)
    attempts = 0
    while True:
        attempts += 1
        result: StructuredResult = await provider.complete_structured(request)
        draft, issues = draft_issues(result.data, context)
        if draft is not None:
            return ModificationInterpretation(
                draft=draft,
                provider=provider.name,
                model=result.model,
                prompt_version=MODIFICATION_PROMPT_VERSION,
                attempts=attempts,
            )
        if attempts > max_repairs:
            raise ModificationInterpretationError(
                "The AI's interpretation of the request could not be validated.", issues
            )
        previous = result.raw_output or json.dumps(result.data, ensure_ascii=False)
        request = build_modification_repair_request(
            prompt,
            context=context,
            previous_output=previous,
            issues=issues,
            max_tokens=max_tokens,
        )
