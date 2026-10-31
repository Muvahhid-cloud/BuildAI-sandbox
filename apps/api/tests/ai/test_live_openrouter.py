"""Live OpenRouterProvider test — skipped unless explicitly enabled (never in CI by default).

    RUN_LIVE_AI_TESTS=true OPENROUTER_API_KEY=... OPENROUTER_MODEL=anthropic/claude-opus-5.5 \
        pytest tests/ai/test_live_openrouter.py

Costs money: one generation call (+ at most one repair). The key is read from the environment
and never printed.
"""

import os

import pytest

from app.modules.ai.interpreter import interpret
from app.modules.ai.providers.openrouter import OpenRouterProvider
from app.modules.building.issues import errors
from tests.ai.helpers import DEMO_PROMPT, context, validate_spec

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AI_TESTS", "").lower() != "true"
    or not os.environ.get("OPENROUTER_API_KEY")
    or not os.environ.get("OPENROUTER_MODEL"),
    reason="live AI tests need RUN_LIVE_AI_TESTS=true, OPENROUTER_API_KEY and OPENROUTER_MODEL",
)


async def test_live_demo_prompt() -> None:
    provider = OpenRouterProvider(
        api_key=os.environ["OPENROUTER_API_KEY"],
        model=os.environ["OPENROUTER_MODEL"],
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
