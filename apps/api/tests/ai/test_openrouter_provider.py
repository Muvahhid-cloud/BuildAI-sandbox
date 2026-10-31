"""OpenRouterProvider against a mocked HTTP transport (no network, no real key, no credits)."""

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest

from app.modules.ai.errors import AIProviderError, AITimeoutError, AIUnavailableError
from app.modules.ai.interpreter import InterpretationError, interpret
from app.modules.ai.prompts.generation import build_generation_request
from app.modules.ai.providers.openrouter import OpenRouterProvider
from app.modules.ai.structured import StructuredRequest
from tests.ai.helpers import DEMO_PROMPT, context, valid_draft, validate_spec

FAKE_KEY = "sk-or-v1-test-" + "k" * 40
MODEL = "anthropic/claude-opus-5.5"
Handler = Any  # callable(httpx.Request) -> httpx.Response


def completion(
    content: Any,
    *,
    finish_reason: str = "stop",
    refusal: str | None = None,
    usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": "gen-123",
        "provider": "Anthropic",
        "model": MODEL,
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "native_finish_reason": "end_turn" if finish_reason == "stop" else finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
        "usage": usage
        if usage is not None
        else {
            "prompt_tokens": 5200,
            "completion_tokens": 1800,
            "total_tokens": 7000,
            "cost": 0.0712,
            "prompt_tokens_details": {"cached_tokens": 3000},
            "completion_tokens_details": {"reasoning_tokens": 0},
        },
    }


class Recorder:
    def __init__(self, *responses: httpx.Response | Exception) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        outcome = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def provider(
    handler: Handler, *, max_retries: int = 0, effort: str | None = None
) -> tuple[OpenRouterProvider, list[float]]:
    sleeps: list[float] = []

    async def no_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return (
        OpenRouterProvider(
            api_key=FAKE_KEY,
            model=MODEL,
            max_retries=max_retries,
            effort=effort,
            transport=httpx.MockTransport(handler),
            sleep=no_sleep,
        ),
        sleeps,
    )


def request() -> StructuredRequest:
    return build_generation_request(DEMO_PROMPT, options=None, context=context(), max_tokens=16000)


def ok(body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=body)


def err(status: int, message: str = "boom", **headers: str) -> httpx.Response:
    return httpx.Response(
        status, json={"error": {"code": status, "message": message}}, headers=headers
    )


# --- success -------------------------------------------------------------------------------


async def test_structured_output_request_shape() -> None:
    rec = Recorder(ok(completion(json.dumps(valid_draft()))))
    p, _ = provider(rec, effort="high")
    await p.complete_structured(request())
    sent = rec.requests[0]
    assert sent.method == "POST"
    assert str(sent.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {FAKE_KEY}"
    body = json.loads(sent.content)
    assert body["model"] == MODEL and body["max_tokens"] == 16000
    system = body["messages"][0]
    assert system["role"] == "system"
    assert system["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][1]["role"] == "user" and DEMO_PROMPT in body["messages"][1]["content"]
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "building_specification_draft"
    assert fmt["json_schema"]["strict"] is True
    schema_text = json.dumps(fmt["json_schema"]["schema"])
    assert '"maximum"' not in schema_text and '"minLength"' not in schema_text
    assert body["provider"] == {"require_parameters": True}
    assert body["reasoning"] == {"effort": "high"}
    assert "tools" not in body and "temperature" not in body


async def test_parses_answer_usage_cost_and_returned_model() -> None:
    draft = valid_draft()
    p, _ = provider(Recorder(ok(completion(json.dumps(draft)))))
    result = await p.complete_structured(request())
    assert result.data == draft
    assert result.model == MODEL
    assert result.input_tokens == 5200 and result.output_tokens == 1800
    assert result.cost_usd == Decimal("0.0712")
    assert result.stop_reason == "end_turn"
    assert result.metadata["cached_tokens"] == 3000
    assert result.metadata["upstream_provider"] == "Anthropic"
    assert result.metadata["generation_id"] == "gen-123"
    assert result.metadata["output_mode"] == "json_schema"


async def test_content_as_list_of_parts_is_joined() -> None:
    draft = valid_draft()
    text = json.dumps(draft)
    parts = [{"type": "text", "text": text[:50]}, {"type": "text", "text": text[50:]}]
    p, _ = provider(Recorder(ok(completion(parts))))
    assert (await p.complete_structured(request())).data == draft


async def test_missing_usage_yields_zero_tokens_and_no_cost() -> None:
    body = completion(json.dumps(valid_draft()))
    del body["usage"]
    p, _ = provider(Recorder(ok(body)))
    result = await p.complete_structured(request())
    assert result.input_tokens == 0 and result.output_tokens == 0 and result.cost_usd is None


async def test_max_effort_maps_to_xhigh() -> None:
    rec = Recorder(ok(completion(json.dumps(valid_draft()))))
    p, _ = provider(rec, effort="max")
    await p.complete_structured(request())
    assert json.loads(rec.requests[0].content)["reasoning"] == {"effort": "xhigh"}


async def test_full_interpretation_through_the_existing_pipeline() -> None:
    p, _ = provider(Recorder(ok(completion(json.dumps(valid_draft())))))
    result = await interpret(
        DEMO_PROMPT, provider=p, options=None, context=context(), validate_spec=validate_spec
    )
    assert result.spec is not None and result.repair_count == 0
    attempt = result.attempts[0]
    assert attempt.provider == "openrouter" and attempt.model == MODEL
    assert attempt.cost_usd == Decimal("0.0712")


# --- structured output failures (no object -> interpreter repairs once, then fails) ---------


@pytest.mark.parametrize(
    ("kwargs", "stop_reason"),
    [
        ({"finish_reason": "length"}, "max_tokens"),
        ({"refusal": "I can't help with that."}, "refusal"),
        ({"finish_reason": "content_filter"}, "refusal"),
    ],
)
async def test_refusal_or_truncation_yields_no_data(
    kwargs: dict[str, Any], stop_reason: str
) -> None:
    p, _ = provider(Recorder(ok(completion('{"outcome": "specifi', **kwargs))))
    result = await p.complete_structured(request())
    assert result.data is None and result.stop_reason == stop_reason


@pytest.mark.parametrize(
    "content",
    [
        "Here is your house: a lovely two-storey building.",
        '```json\n{"outcome": "specification"}\n```',
        "[1, 2]",
        None,
    ],
)
async def test_prose_fenced_or_non_object_output_is_not_parsed(content: Any) -> None:
    p, _ = provider(Recorder(ok(completion(content))))
    assert (await p.complete_structured(request())).data is None


async def test_persistent_prose_output_fails_after_one_repair() -> None:
    rec = Recorder(ok(completion("Sure! Here's a nice house.")))
    p, _ = provider(rec)
    with pytest.raises(InterpretationError) as info:
        await interpret(
            DEMO_PROMPT, provider=p, options=None, context=context(), validate_spec=validate_spec
        )
    assert info.value.code == "AI_INVALID_OUTPUT"
    assert len(rec.requests) == 2  # generation + exactly one repair


async def test_no_structured_output_endpoint_is_reported() -> None:
    p, _ = provider(Recorder(err(404, "No endpoints found that can handle the requested params")))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "structured outputs" in info.value.detail


# --- schema too complex for structured outputs -> schema-in-prompt fallback -------------------

GRAMMAR_MESSAGE = (
    "The compiled grammar is too large, which would cause performance issues. "
    "Simplify your tool schemas or reduce the number of strict tools."
)


def grammar_rejection() -> httpx.Response:
    """What OpenRouter returned live (2026-09-29) for the full SpecificationDraft schema."""
    raw = json.dumps(
        {"type": "error", "error": {"type": "invalid_request_error", "message": GRAMMAR_MESSAGE}}
    )
    return httpx.Response(
        400,
        json={
            "error": {
                "code": 400,
                "message": "Provider returned error",
                "metadata": {"raw": raw, "provider_name": "Anthropic"},
            }
        },
    )


async def test_grammar_rejection_falls_back_to_schema_in_prompt() -> None:
    draft = valid_draft()
    rec = Recorder(grammar_rejection(), ok(completion(json.dumps(draft))))
    p, _ = provider(rec)
    result = await p.complete_structured(request())
    assert len(rec.requests) == 2
    first, second = (json.loads(r.content) for r in rec.requests)
    assert first["response_format"]["type"] == "json_schema"
    assert "response_format" not in second and "provider" not in second
    system = second["messages"][0]["content"][0]
    assert "<response_schema>" in system["text"]
    assert system["cache_control"] == {"type": "ephemeral"}
    # The full schema (constraints included) is in the prompt; the user turn is unchanged.
    assert '"maximum":3' in system["text"]
    assert second["messages"][1] == first["messages"][1]
    assert result.data == draft and result.metadata["output_mode"] == "prompt_schema"
    assert p.output_mode == "prompt_schema"


async def test_fallback_is_remembered_for_later_calls() -> None:
    rec = Recorder(grammar_rejection(), ok(completion(json.dumps(valid_draft()))))
    p, _ = provider(rec)
    await p.complete_structured(request())
    await p.complete_structured(request())
    assert len(rec.requests) == 3  # rejected once, then prompt_schema twice
    assert "response_format" not in json.loads(rec.requests[2].content)


async def test_fallback_output_is_still_parsed_strictly() -> None:
    fenced = "```json\n" + json.dumps(valid_draft()) + "\n```"
    p, _ = provider(Recorder(grammar_rejection(), ok(completion(fenced))))
    assert (await p.complete_structured(request())).data is None


async def test_other_bad_requests_do_not_trigger_the_fallback() -> None:
    rec = Recorder(err(400, "anthropic/claude-nope is not a valid model ID"))
    p, _ = provider(rec)
    with pytest.raises(AIUnavailableError):
        await p.complete_structured(request())
    assert len(rec.requests) == 1 and p.output_mode == "json_schema"


async def test_fallback_errors_are_mapped_normally() -> None:
    p, _ = provider(Recorder(grammar_rejection(), err(503, "overloaded")))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "provider unavailable" in info.value.detail


async def test_upstream_reason_is_included_in_error_detail() -> None:
    raw = json.dumps({"error": {"message": "prompt is too long"}})
    body = {
        "error": {
            "code": 400,
            "message": "Provider returned error",
            "metadata": {"raw": raw, "provider_name": "Anthropic"},
        }
    }
    p, _ = provider(Recorder(httpx.Response(400, json=body)))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "[Anthropic: prompt is too long]" in info.value.detail


# --- HTTP / transport errors -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected", "fragment"),
    [
        (400, AIUnavailableError, "request rejected"),
        (401, AIUnavailableError, "OPENROUTER_API_KEY"),
        (402, AIUnavailableError, "insufficient credits"),
        (403, AIUnavailableError, "forbidden"),
        (404, AIUnavailableError, "not found"),
        (408, AITimeoutError, "timeout"),
        (429, AIUnavailableError, "rate limited"),
        (500, AIUnavailableError, "provider unavailable"),
        (502, AIUnavailableError, "provider unavailable"),
        (503, AIUnavailableError, "provider unavailable"),
    ],
)
async def test_http_errors_are_mapped(
    status: int, expected: type[AIProviderError], fragment: str
) -> None:
    p, _ = provider(Recorder(err(status)))
    with pytest.raises(expected) as info:
        await p.complete_structured(request())
    assert fragment in info.value.detail


async def test_invalid_model_is_reported() -> None:
    p, _ = provider(Recorder(err(400, "anthropic/claude-nope is not a valid model ID")))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "not a valid model ID" in info.value.detail


async def test_timeout_is_mapped_and_not_retried() -> None:
    rec = Recorder(httpx.ReadTimeout("read timed out"))
    p, sleeps = provider(rec, max_retries=2)
    with pytest.raises(AITimeoutError):
        await p.complete_structured(request())
    assert len(rec.requests) == 1 and sleeps == []


async def test_network_error_is_retried_then_mapped() -> None:
    rec = Recorder(httpx.ConnectError("connection refused"))
    p, sleeps = provider(rec, max_retries=1)
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "connection failed" in info.value.detail
    assert len(rec.requests) == 2 and len(sleeps) == 1


async def test_rate_limit_is_retried_with_retry_after() -> None:
    rec = Recorder(err(429, **{"retry-after": "3"}), ok(completion(json.dumps(valid_draft()))))
    p, sleeps = provider(rec, max_retries=1)
    result = await p.complete_structured(request())
    assert result.data is not None and sleeps == [3.0] and len(rec.requests) == 2


async def test_rate_limit_after_retries_fails() -> None:
    rec = Recorder(err(429))
    p, sleeps = provider(rec, max_retries=1)
    with pytest.raises(AIUnavailableError):
        await p.complete_structured(request())
    assert len(rec.requests) == 2 and sleeps == [0.5]


async def test_client_errors_are_not_retried() -> None:
    rec = Recorder(err(401))
    p, sleeps = provider(rec, max_retries=3)
    with pytest.raises(AIUnavailableError):
        await p.complete_structured(request())
    assert len(rec.requests) == 1 and sleeps == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>gateway</html>"),
        httpx.Response(200, json=[1, 2]),
        httpx.Response(200, json={"id": "x", "choices": []}),
        httpx.Response(200, json={"choices": [{"index": 0}]}),
    ],
)
async def test_unexpected_response_format(response: httpx.Response) -> None:
    p, _ = provider(Recorder(response))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "unexpected response" in info.value.detail


async def test_error_inside_a_200_body_is_mapped() -> None:
    body = {"error": {"code": 502, "message": "upstream overloaded"}}
    p, _ = provider(Recorder(httpx.Response(200, json=body)))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "upstream overloaded" in info.value.detail


async def test_error_inside_a_choice_is_mapped() -> None:
    body = completion("")
    body["choices"][0]["error"] = {"code": 503, "message": "model unavailable"}
    p, _ = provider(Recorder(ok(body)))
    with pytest.raises(AIUnavailableError) as info:
        await p.complete_structured(request())
    assert "model unavailable" in info.value.detail


async def test_provider_errors_fail_the_interpretation_with_the_provider_code() -> None:
    p, _ = provider(Recorder(err(503)))
    with pytest.raises(InterpretationError) as info:
        await interpret(
            DEMO_PROMPT, provider=p, options=None, context=context(), validate_spec=validate_spec
        )
    assert info.value.code == "AI_UNAVAILABLE"
    assert info.value.attempts[0].provider == "openrouter"


# --- secrets ----------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_key_echoed_by_the_server_is_redacted(status: int) -> None:
    p, _ = provider(Recorder(err(status, f"bad key {FAKE_KEY} for request")))
    with pytest.raises(AIProviderError) as info:
        await p.complete_structured(request())
    assert FAKE_KEY not in info.value.detail and FAKE_KEY not in str(info.value)
    assert FAKE_KEY not in info.value.user_message


async def test_key_not_in_repr_or_result() -> None:
    p, _ = provider(Recorder(ok(completion(json.dumps(valid_draft())))))
    assert FAKE_KEY not in repr(p)
    result = await p.complete_structured(request())
    assert FAKE_KEY not in repr(result)
