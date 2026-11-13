"""MockAIProvider: deterministic offline provider for development, tests, CI and offline work.

It answers every request (generation and repair alike) with the rule-based interpretation of
the user's original text (modification requests: `mock_modification.py`, over the model
digest), serialized exactly as a model's structured output would be, so the parse -> validate
-> repair -> layout pipeline runs unchanged without an API key or network.
"""

import asyncio
import json

from app.modules.ai.providers.base import AIProvider
from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.providers.mock_modification import interpret_modification_offline
from app.modules.ai.structured import AITask, StructuredRequest, StructuredResult, TextCallback

MOCK_MODEL = "mock-interpreter@1"
# Streaming: the serialized answer in pieces of this many characters (deterministic).
MOCK_STREAM_CHUNK_CHARS = 48


class MockAIProvider(AIProvider):
    name = "mock"

    def __init__(self, model: str = MOCK_MODEL, *, stream_delay_s: float = 0.0) -> None:
        self.model = model
        # Pause between two streamed pieces (development only: lets the UI show the answer
        # arriving, as it does with a language model). 0 in tests and CI.
        self.stream_delay_s = stream_delay_s

    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        if request.task == AITask.PLAN_MODIFICATION:
            data = interpret_modification_offline(request.user_prompt, request.modification_context)
        else:
            data = interpret_offline(request.user_prompt, request.options)
        return StructuredResult(
            data=data,
            raw_output=json.dumps(data, ensure_ascii=False, sort_keys=True),
            model=self.model,
            stop_reason="end_turn",
        )

    async def stream_structured(
        self, request: StructuredRequest, on_text: TextCallback
    ) -> StructuredResult:
        """The same answer as `complete_structured`, delivered in fixed-size pieces."""
        result = await self.complete_structured(request)
        raw = result.raw_output
        for start in range(0, len(raw), MOCK_STREAM_CHUNK_CHARS):
            if self.stream_delay_s > 0:
                await asyncio.sleep(self.stream_delay_s)
            await on_text(raw[start : start + MOCK_STREAM_CHUNK_CHARS])
        return result
