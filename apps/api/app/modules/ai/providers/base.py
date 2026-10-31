"""AIProvider: the only interface the rest of the code uses to talk to a language model.

Providers implement one primitive, `complete_structured`: send a system prompt + messages and
get back one JSON object constrained to a Pydantic JSON Schema (structured output). The
building-specific operations (`generate_building_specification`, `repair_building_specification`)
are built on top of it from the versioned prompt modules, so every provider receives exactly the
same prompts. Providers never validate or trust their output — the interpreter does.
"""

from abc import ABC, abstractmethod

from app.modules.ai.context import GenerationContext
from app.modules.ai.prompts.generation import build_generation_request
from app.modules.ai.prompts.repair import build_repair_request
from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.ai.structured import RepairInput, StructuredRequest, StructuredResult


class AIProvider(ABC):
    """Vendor-neutral provider. Implementations live in `providers/<vendor>.py`."""

    name: str
    model: str

    @abstractmethod
    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        """One model call whose answer is a JSON object for `request.output_schema`.

        Raises `AIProviderError` subclasses (never vendor exceptions)."""

    async def generate_building_specification(
        self,
        prompt: str,
        *,
        options: GenerationOptions | None,
        context: GenerationContext,
        max_tokens: int,
    ) -> StructuredResult:
        return await self.complete_structured(
            build_generation_request(
                prompt, options=options, context=context, max_tokens=max_tokens
            )
        )

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
