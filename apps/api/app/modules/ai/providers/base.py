"""AIProvider: the only interface the rest of the code uses to talk to a language model.

Providers implement one primitive, `complete_structured`: send a system prompt + messages and
get back one JSON object constrained to a Pydantic JSON Schema (structured output), and may
override its streaming variant `stream_structured` (same call, text reported as it arrives). The
building-specific operations (`generate_building_specification`, `repair_building_specification`)
are built on top of it from the versioned prompt modules, so every provider receives exactly the
same prompts. Providers never validate or trust their output — the interpreter does.
"""

from abc import ABC, abstractmethod

from app.modules.ai.context import GenerationContext
from app.modules.ai.prompts.generation import build_generation_request
from app.modules.ai.prompts.repair import build_repair_request
from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.ai.structured import (
    RepairInput,
    StructuredRequest,
    StructuredResult,
    TextCallback,
)


class AIProvider(ABC):
    """Vendor-neutral provider. Implementations live in `providers/<vendor>.py`."""

    name: str
    model: str

    @abstractmethod
    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        """One model call whose answer is a JSON object for `request.output_schema`.

        Raises `AIProviderError` subclasses (never vendor exceptions)."""

    async def stream_structured(
        self, request: StructuredRequest, on_text: TextCallback
    ) -> StructuredResult:
        """The same single call as `complete_structured`, with the answer's text passed to
        `on_text` while it is produced. The pieces, joined, are the raw output.

        The text seen on the way is only ever used for interim display: the returned result is
        what gets validated. Providers that cannot stream keep this default, which delivers the
        whole answer in one piece when the call returns."""
        result = await self.complete_structured(request)
        if result.raw_output:
            await on_text(result.raw_output)
        return result

    async def generate_building_specification(
        self,
        prompt: str,
        *,
        options: GenerationOptions | None,
        context: GenerationContext,
        max_tokens: int,
        on_text: TextCallback | None = None,
    ) -> StructuredResult:
        request = build_generation_request(
            prompt, options=options, context=context, max_tokens=max_tokens
        )
        if on_text is None:
            return await self.complete_structured(request)
        return await self.stream_structured(request, on_text)

    async def repair_building_specification(
        self,
        prompt: str,
        *,
        options: GenerationOptions | None,
        context: GenerationContext,
        repair: RepairInput,
        max_tokens: int,
    ) -> StructuredResult:
        return await self.complete_structured(
            build_repair_request(
                prompt, options=options, context=context, repair=repair, max_tokens=max_tokens
            )
        )
