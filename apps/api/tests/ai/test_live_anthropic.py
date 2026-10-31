"""Live AnthropicProvider test — skipped unless explicitly enabled (never in CI by default).

    RUN_LIVE_AI_TESTS=true ANTHROPIC_API_KEY=... AI_LIVE_MODEL=claude-opus-5 \
        pytest tests/ai/test_live_anthropic.py

Costs money: one generation call (+ at most one repair). The key is read from the environment
and never printed.
"""

import os

import pytest

from app.modules.ai.interpreter import interpret
from app.modules.ai.providers.anthropic import AnthropicProvider
from app.modules.building.issues import errors
from app.modules.building.requirements import spec_facts
from tests.ai.helpers import DEMO_PROMPT, context, validate_spec

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS", "").lower() != "true"
    or not os.environ.get("ANTHROPIC_API_KEY"),
    reason="live AI tests need RUN_LIVE_AI_TESTS=true and ANTHROPIC_API_KEY",
)


async def test_live_demo_prompt() -> None:
    provider = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("AI_LIVE_MODEL", "claude-opus-5"),
        timeout_s=180,
    )
    result = await interpret(
        DEMO_PROMPT,
        provider=provider,
        options=None,
        context=context(),
        validate_spec=validate_spec,
    )
    assert result.spec is not None
    assert errors(validate_spec(result.spec)) == []
    facts = spec_facts(result.spec)
    assert facts.storeys == 2 and facts.bedrooms == 4 and facts.bathrooms == 3
    assert facts.garage_cars == 2 and facts.balconies >= 1
    assert facts.gross_floor_area_m2 is not None and 260 <= facts.gross_floor_area_m2 <= 300
