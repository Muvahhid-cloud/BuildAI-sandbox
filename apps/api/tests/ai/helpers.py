"""Test doubles and fixtures for the AI module (no network, no paid API)."""

import copy
import json
from collections.abc import Callable
from typing import Any

from app.modules.ai.context import GenerationContext, generation_context
from app.modules.ai.providers.base import AIProvider
from app.modules.ai.providers.mock_interpreter import interpret_offline
from app.modules.ai.structured import StructuredRequest, StructuredResult
from app.modules.building.issues import Issue
from app.modules.building.specification import BuildingSpecification
from app.modules.layout.config import DEFAULT_CONFIG
from app.modules.rules.profile import BuildingRulesProfile
from app.modules.rules.spec_checks import check_spec
from app.shared.data_files import rules_profile
from tests.building.helpers import DATA_DIR

DEMO_PROMPT = (
    "Create a modern two-story family house of approximately 280 square meters with four "
    "bedrooms, three bathrooms, a large living room connected to the kitchen, a two-car garage, "
    "a balcony on the second floor, large windows and minimalist interior design."
)


def profile() -> BuildingRulesProfile:
    return rules_profile(DATA_DIR, "generic-residential@1")


def context() -> GenerationContext:
    return generation_context(region_code="KZ-ALA", currency="KZT", profile=profile())


def validate_spec(spec: BuildingSpecification) -> list[Issue]:
    return check_spec(spec, profile(), floor_structure_m=DEFAULT_CONFIG.floor_slab_thickness)


def valid_draft(prompt: str = DEMO_PROMPT) -> dict[str, Any]:
    return copy.deepcopy(interpret_offline(prompt))


Response = dict[str, Any] | None | Exception | Callable[[StructuredRequest], dict[str, Any]]


class ScriptedAIProvider(AIProvider):
    """Answers with a fixed sequence of outputs (dicts, None = no JSON, or exceptions)."""

    name = "scripted"

    def __init__(self, *responses: Response, model: str = "scripted-model") -> None:
        self.model = model
        self.responses = list(responses)
        self.requests: list[StructuredRequest] = []

    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("ScriptedAIProvider ran out of responses")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if callable(response):
            response = response(request)
        raw = json.dumps(response) if response is not None else "I cannot do that."
        return StructuredResult(
            data=response,
            raw_output=raw,
            model=self.model,
            input_tokens=100,
            output_tokens=50,
            latency_ms=5,
        )
