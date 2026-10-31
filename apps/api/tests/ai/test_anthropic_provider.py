"""AnthropicProvider against a fake SDK client (no network, no API key)."""

import json
import logging
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest

from app.modules.ai.errors import AITimeoutError, AIUnavailableError
from app.modules.ai.interpreter import InterpretationError, interpret
from app.modules.ai.prompts.generation import build_generation_request
from app.modules.ai.prompts.shared import output_schema_json
from app.modules.ai.providers.anthropic import AnthropicProvider, structured_output_schema
from tests.ai.helpers import DEMO_PROMPT, context, valid_draft, validate_spec


class FakeMessages:
    def __init__(self, outcome: Any) -> None:
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def response(text: str, stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model="claude-opus-5",
        usage=SimpleNamespace(
            input_tokens=1200,
            output_tokens=800,
            cache_read_input_tokens=3000,
            cache_creation_input_tokens=0,
        ),
    )


def provider(outcome: Any, effort: str | None = None) -> tuple[AnthropicProvider, FakeMessages]:
    messages = FakeMessages(outcome)
    client = SimpleNamespace(messages=messages)
    return (
        AnthropicProvider(api_key="unused", model="claude-opus-5", effort=effort, client=client),
        messages,
    )


def request() -> Any:
    return build_generation_request(DEMO_PROMPT, options=None, context=context(), max_tokens=16000)


async def test_structured_output_request_shape() -> None:
    p, messages = provider(response(json.dumps(valid_draft())), effort="medium")
    await p.complete_structured(request())
    call = messages.calls[0]
    assert call["model"] == "claude-opus-5" and call["max_tokens"] == 16000
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["messages"][0]["role"] == "user"
    assert DEMO_PROMPT in call["messages"][0]["content"]
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert call["output_config"]["effort"] == "medium"
    assert "tools" not in call and "tool_choice" not in call and "temperature" not in call


async def test_parses_the_json_answer_and_usage() -> None:
    draft = valid_draft()
    p, _ = provider(response(json.dumps(draft)))
    result = await p.complete_structured(request())
    assert result.data == draft
    assert result.model == "claude-opus-5"
    assert result.input_tokens == 4200 and result.output_tokens == 800
    assert result.metadata["cache_read_input_tokens"] == 3000


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
async def test_refusal_or_truncation_yields_no_data(stop_reason: str) -> None:
    p, _ = provider(response('{"outcome": "specifi', stop_reason))
    result = await p.complete_structured(request())
    assert result.data is None and result.stop_reason == stop_reason


async def test_non_object_json_yields_no_data() -> None:
    p, _ = provider(response("[1, 2]"))
    assert (await p.complete_structured(request())).data is None


def _http_error(cls: type[anthropic.APIStatusError], status: int) -> anthropic.APIStatusError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx2.Response(status, request=req), body=None)


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (anthropic.APITimeoutError(request=httpx2.Request("POST", "https://x")), AITimeoutError),
        (
            anthropic.APIConnectionError(request=httpx2.Request("POST", "https://x")),
            AIUnavailableError,
        ),
    ],
)
async def test_transport_errors_are_mapped(exc: Exception, expected: type[Exception]) -> None:
    p, _ = provider(exc)
    with pytest.raises(expected):
        await p.complete_structured(request())


@pytest.mark.parametrize(
    ("cls", "status"),
    [
        (anthropic.AuthenticationError, 401),
        (anthropic.RateLimitError, 429),
        (anthropic.InternalServerError, 500),
        (anthropic.BadRequestError, 400),
    ],
)
async def test_http_errors_are_mapped(cls: type[anthropic.APIStatusError], status: int) -> None:
    p, _ = provider(_http_error(cls, status))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "unused" not in info.value.detail  # the key never appears in errors


# --- schema too complex for structured outputs -> shared schema-in-prompt fallback ------------

GRAMMAR_MESSAGE = (
    "The compiled grammar is too large, which would cause performance issues. "
    "Simplify your tool schemas or reduce the number of strict tools."
)


class SequencedMessages:
    """Fake `messages` returning/raising one outcome per call, in order."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def bad_request(message: str) -> anthropic.BadRequestError:
    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    return anthropic.BadRequestError(message, response=httpx2.Response(400, request=req), body=body)


def sequenced(
    *outcomes: Any, effort: str | None = None
) -> tuple[AnthropicProvider, SequencedMessages]:
    messages = SequencedMessages(*outcomes)
    client = SimpleNamespace(messages=messages)
    return (
        AnthropicProvider(api_key="unused", model="claude-opus-5", effort=effort, client=client),
        messages,
    )


async def test_grammar_rejection_falls_back_to_schema_in_prompt() -> None:
    draft = valid_draft()
    p, messages = sequenced(
        bad_request(GRAMMAR_MESSAGE), response(json.dumps(draft)), effort="high"
    )
    result = await p.complete_structured(request())
    assert len(messages.calls) == 2
    first, second = messages.calls
    assert first["output_config"]["format"]["type"] == "json_schema"
    # Fallback: no grammar, the full schema (constraints included) in the cached system prompt.
    assert "format" not in second["output_config"]
    assert second["output_config"]["effort"] == "high"
    system = second["system"][0]
    assert system["cache_control"] == {"type": "ephemeral"}
    assert system["text"].startswith(first["system"][0]["text"])
    assert "<response_schema>" in system["text"] and '"maximum":3' in system["text"]
    assert second["messages"] == first["messages"]
    assert result.data == draft
    assert result.metadata["output_mode"] == "prompt_schema"
    assert p.output_mode == "prompt_schema"


async def test_fallback_without_effort_sends_no_output_config() -> None:
    p, messages = sequenced(bad_request(GRAMMAR_MESSAGE), response(json.dumps(valid_draft())))
    await p.complete_structured(request())
    assert "output_config" not in messages.calls[1]


async def test_fallback_is_remembered_for_later_calls() -> None:
    p, messages = sequenced(bad_request(GRAMMAR_MESSAGE), response(json.dumps(valid_draft())))
    await p.complete_structured(request())
    await p.complete_structured(request())
    assert len(messages.calls) == 3  # rejected once, then prompt_schema twice
    assert "output_config" not in messages.calls[2]


async def test_strict_mode_is_used_while_the_schema_is_accepted() -> None:
    p, messages = sequenced(response(json.dumps(valid_draft())))
    result = await p.complete_structured(request())
    assert len(messages.calls) == 1 and result.metadata["output_mode"] == "json_schema"


async def test_fallback_output_is_still_parsed_strictly() -> None:
    fenced = "```json\n" + json.dumps(valid_draft()) + "\n```"
    p, _ = sequenced(bad_request(GRAMMAR_MESSAGE), response(fenced))
    assert (await p.complete_structured(request())).data is None


async def test_other_bad_requests_do_not_trigger_the_fallback() -> None:
    p, messages = sequenced(bad_request("prompt is too long: 250000 tokens > 200000 maximum"))
    with pytest.raises(AIUnavailableError):
        await p.complete_structured(request())
    assert len(messages.calls) == 1 and p.output_mode == "json_schema"


async def test_non_400_errors_do_not_trigger_the_fallback() -> None:
    # Even with a matching message, only a 400 (BadRequestError) is a schema rejection.
    p, messages = sequenced(_http_error(anthropic.InternalServerError, 500))
    with pytest.raises(AIUnavailableError):
        await p.complete_structured(request())
    assert len(messages.calls) == 1 and p.output_mode == "json_schema"


async def test_fallback_errors_are_mapped_normally() -> None:
    p, _ = sequenced(bad_request(GRAMMAR_MESSAGE), _http_error(anthropic.RateLimitError, 429))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "rate limited" in info.value.detail and "unused" not in info.value.detail


async def test_fallback_goes_through_the_existing_interpreter() -> None:
    p, _ = sequenced(bad_request(GRAMMAR_MESSAGE), response(json.dumps(valid_draft())))
    result = await interpret(
        DEMO_PROMPT, provider=p, options=None, context=context(), validate_spec=validate_spec
    )
    assert result.spec is not None and result.repair_count == 0
    assert [a.provider for a in result.attempts] == ["anthropic"]


async def test_persistent_prose_in_fallback_fails_after_one_repair() -> None:
    p, messages = sequenced(bad_request(GRAMMAR_MESSAGE), response("Sure! Here's a house."))
    with pytest.raises(InterpretationError) as info:
        await interpret(
            DEMO_PROMPT, provider=p, options=None, context=context(), validate_spec=validate_spec
        )
    assert info.value.code == "AI_INVALID_OUTPUT"
    # strict attempt (rejected) + generation + exactly one repair, both in prompt_schema mode
    assert len(messages.calls) == 3
    assert all("output_config" not in call for call in messages.calls[1:])


async def test_fallback_warning_does_not_leak_the_key(caplog: pytest.LogCaptureFixture) -> None:
    key = "sk-ant-api03-" + "s" * 40
    messages = SequencedMessages(bad_request(GRAMMAR_MESSAGE), response(json.dumps(valid_draft())))
    p = AnthropicProvider(
        api_key=key, model="claude-opus-5", client=SimpleNamespace(messages=messages)
    )
    with caplog.at_level(logging.WARNING, logger="app.modules.ai.providers.anthropic"):
        await p.complete_structured(request())
    assert "grammar is too large" in caplog.text and key not in caplog.text
    assert key not in repr(p)


def test_structured_output_schema_drops_unsupported_constraints() -> None:
    original = output_schema_json()
    schema = structured_output_schema(original)
    text = json.dumps(schema)
    for keyword in ('"minimum"', '"maximum"', '"minLength"', '"maxLength"', '"maxItems"'):
        assert keyword not in text
    # Constraints survive as text for the model; Pydantic still enforces them.
    targets = schema["$defs"]["Targets"]["properties"]["storeys"]
    assert "minimum 1" in targets["description"] and "maximum 3" in targets["description"]
    assert schema["$defs"]["BuildingSpecification"]["additionalProperties"] is False
    assert original["$defs"]["Targets"]["properties"]["storeys"]["maximum"] == 3  # not mutated


def test_property_named_like_a_keyword_is_kept() -> None:
    schema = {
        "type": "object",
        "properties": {"pattern": {"type": "string", "maxLength": 3}},
        "additionalProperties": False,
    }
    out = structured_output_schema(schema)
    assert out["properties"]["pattern"] == {"type": "string", "description": "(max length 3)"}
