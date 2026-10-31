"""Provider-neutral request/response types shared by prompts, providers and the interpreter."""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from app.modules.ai.schemas.generation import GenerationOptions


class AITask(StrEnum):
    GENERATE_SPECIFICATION = "generate_specification"
    REPAIR_SPECIFICATION = "repair_specification"


@dataclass(frozen=True)
class AIMessage:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class StructuredRequest:
    task: AITask
    prompt_version: str
    system: str
    messages: tuple[AIMessage, ...]
    output_name: str
    output_description: str
    output_schema: dict[str, Any]
    max_tokens: int
    # The user's original request, for providers that do not run a language model (mock).
    user_prompt: str = ""
    options: GenerationOptions | None = None


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any] | None  # the structured output; None if the model returned none
    raw_output: str  # what the model returned, serialized (stored in ai_runs for debugging)
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str | None = None
    # Provider-reported request cost in USD (OpenRouter credits); None when not reported.
    cost_usd: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepairInput:
    previous_output: str  # raw output of the rejected attempt
    issues: tuple[str, ...]  # "path: message" lines
