"""Repair prompt: the previous structured output was rejected; send the issues back once.

A single self-contained user turn (original request + rejected output + issues), so it works
the same for every provider. The system prompt is the generation one (shared cache prefix).
"""

from app.modules.ai.context import GenerationContext
from app.modules.ai.prompts.generation import system_prompt
from app.modules.ai.prompts.shared import (
    OUTPUT_DESCRIPTION,
    OUTPUT_NAME,
    PROMPT_VERSION,
    context_block,
    output_schema_json,
    quote_user_text,
)
from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.ai.structured import AIMessage, AITask, RepairInput, StructuredRequest

MAX_PREVIOUS_OUTPUT_CHARS = 20_000
MAX_ISSUES = 30

REPAIR_INSTRUCTIONS = f"""Your previous {OUTPUT_NAME} answer was rejected by validation. \
Answer again with a corrected {OUTPUT_NAME} JSON object.
- Fix exactly what the issues require; keep everything else unchanged.
- Keep every explicit requirement of the request. If an issue exists only because explicit \
requirements conflict or exceed the supported scope, do not remove or shrink the requirement: \
answer with outcome "clarification" and explain the conflict in plain language.
- Paths are JSON pointers into your previous answer."""


def build_repair_request(
    prompt: str,
    *,
    options: GenerationOptions | None,
    context: GenerationContext,
    repair: RepairInput,
    max_tokens: int,
) -> StructuredRequest:
    issues = "\n".join(f"- {line}" for line in repair.issues[:MAX_ISSUES])
    user = "\n\n".join(
        [
            context_block(context, options),
            quote_user_text(prompt),
            "<previous_output>\n"
            + repair.previous_output[:MAX_PREVIOUS_OUTPUT_CHARS]
            + "\n</previous_output>",
            f"<validation_issues>\n{issues}\n</validation_issues>",
            REPAIR_INSTRUCTIONS,
        ]
    )
    return StructuredRequest(
        task=AITask.REPAIR_SPECIFICATION,
        prompt_version=PROMPT_VERSION,
        system=system_prompt(),
        messages=(AIMessage(role="user", content=user),),
        output_name=OUTPUT_NAME,
        output_description=OUTPUT_DESCRIPTION,
        output_schema=output_schema_json(),
        max_tokens=max_tokens,
        user_prompt=prompt,
        options=options,
    )
