"""MockAIProvider: deterministic offline provider for development, tests, CI and offline work.

It answers every request (generation and repair alike) with the rule-based interpretation of
the user's original text, serialized exactly as a model's structured output would be, so the
parse -> validate -> repair -> layout pipeline runs unchanged without an API key or network.
"""

import json

from app.modules.ai.providers.base import AIProvider
from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.structured import StructuredRequest, StructuredResult

MOCK_MODEL = "mock-interpreter@1"


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self, model: str = MOCK_MODEL) -> None:
        self.model = model

    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        data = interpret_offline(request.user_prompt, request.options)
        return StructuredResult(
            data=data,
            raw_output=json.dumps(data, ensure_ascii=False, sort_keys=True),
            model=self.model,
            stop_reason="end_turn",
        )
