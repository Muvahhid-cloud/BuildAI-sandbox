"""OpenRouterProvider: Claude (or another model) through OpenRouter's OpenAI-compatible API.

One `POST {base_url}/chat/completions` per request over plain `httpx` (no vendor SDK). The
answer is constrained with structured outputs (`response_format = json_schema`, strict) using
the same JSON Schema of `SpecificationDraft` as the Anthropic provider, with unsupported
numeric/length constraints moved into descriptions (`json_schema.structured_output_schema`).
`provider.require_parameters` makes OpenRouter route only to upstream endpoints that support
structured outputs, so the schema is never silently dropped.

Claude's structured outputs compile the schema into a grammar with size limits; the full
`SpecificationDraft` schema exceeds them ("compiled grammar is too large", a 400 before any
generation). On that specific rejection the provider switches, for this and every later call,
to the `prompt_schema` mode: the JSON Schema is appended to the system prompt
(`prompts.shared.schema_in_prompt_block`) and no grammar is requested. In both modes the
answer is parsed with `json.loads` only — prose, fenced code or a refusal yields "no object"
and the interpreter decides (repair once, then fail). Nothing here validates or trusts the
output; the mode is reported in `StructuredResult.metadata["output_mode"]`.

The API key is sent only in the Authorization header; it never appears in errors or logs
(error details are redacted and truncated). Transient failures (429, 5xx, connection errors)
are retried `max_retries` times with a short backoff; timeouts are not retried.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.modules.ai.errors import AIProviderError, AITimeoutError, AIUnavailableError
from app.modules.ai.prompts.shared import SCHEMA_IN_PROMPT_VERSION
from app.modules.ai.providers.base import AIProvider
from app.modules.ai.providers.json_schema import (
    JSON_SCHEMA,
    PROMPT_SCHEMA,
    is_schema_too_complex,
    prompt_schema_system,
    structured_output_schema,
)
from app.modules.ai.structured import StructuredRequest, StructuredResult

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
APP_TITLE = "BuildAI 3D"  # OpenRouter app attribution header (not a secret)

_RETRYABLE_STATUS = frozenset({408, 429, 500, 502, 503, 504, 529})
_MAX_BACKOFF_S = 10.0
_MAX_DETAIL_CHARS = 500
# OpenRouter `reasoning.effort` has no "max"; the closest level is used.
_EFFORT_MAP = {"max": "xhigh"}


class OpenRouterProvider(AIProvider):
    name = "openrouter"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        effort: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._effort = _EFFORT_MAP.get(effort, effort) if effort else None
        # `transport` and `sleep` are injectable for unit tests (httpx.MockTransport, no wait).
        self._transport = transport
        self._sleep = sleep
        # Set once the upstream refused to compile the output schema; later calls go straight
        # to the schema-in-prompt mode (no repeated failing request).
        self._schema_rejected = False

    def __repr__(self) -> str:  # never expose the key through a repr
        return f"OpenRouterProvider(model={self.model!r})"

    @property
    def output_mode(self) -> str:
        return PROMPT_SCHEMA if self._schema_rejected else JSON_SCHEMA

    def _payload(self, request: StructuredRequest, mode: str) -> dict[str, Any]:
        system = request.system
        if mode == PROMPT_SCHEMA:
            # Static per prompt version too, so the cache breakpoint below still applies.
            system = prompt_schema_system(system, request.output_schema)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "messages": [
                {
                    "role": "system",
                    # Static per prompt version: a cache breakpoint for Anthropic upstreams.
                    "content": [
                        {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                    ],
                },
                *({"role": m.role, "content": m.content} for m in request.messages),
            ],
            "usage": {"include": True},
        }
        if mode == JSON_SCHEMA:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.output_name,
                    "description": request.output_description,
                    "strict": True,
                    "schema": structured_output_schema(request.output_schema),
                },
            }
            # Only endpoints that honour every parameter (structured outputs) may serve this.
            payload["provider"] = {"require_parameters": True}
        if self._effort:
            payload["reasoning"] = {"effort": self._effort}
        return payload

    def _safe(self, text: object) -> str:
        """Error detail safe for logs: key redacted, length capped."""
        out = str(text)
        if self._api_key:
            out = out.replace(self._api_key, "***")
        return out[:_MAX_DETAIL_CHARS]

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": APP_TITLE,
        }
        attempt = 0
        async with httpx.AsyncClient(timeout=self._timeout_s, transport=self._transport) as client:
            while True:
                try:
                    response = await client.post(self._url, json=payload, headers=headers)
                except httpx.TimeoutException as exc:
                    raise AITimeoutError(
                        f"openrouter: timeout after {self._timeout_s:g}s ({type(exc).__name__})"
                    ) from exc
                except httpx.TransportError as exc:
                    if attempt >= self._max_retries:
                        raise AIUnavailableError(
                            f"openrouter: connection failed ({type(exc).__name__}: "
                            f"{self._safe(exc)})"
                        ) from exc
                    await self._sleep(self._backoff(attempt, None))
                    attempt += 1
                    continue
                if response.status_code in _RETRYABLE_STATUS and attempt < self._max_retries:
                    await self._sleep(self._backoff(attempt, response))
                    attempt += 1
                    continue
                return response

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response | None) -> float:
        retry_after = response.headers.get("retry-after") if response is not None else None
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), _MAX_BACKOFF_S)
            except ValueError:
                pass
        return min(0.5 * 2.0**attempt, _MAX_BACKOFF_S)

    def _error_message(self, body: Any, response: httpx.Response) -> str:
        error = body.get("error") if isinstance(body, dict) else None
        if isinstance(error, dict) and error.get("message"):
            message = str(error["message"])
            # OpenRouter wraps upstream errors ("Provider returned error"); the reason is in
            # metadata.raw (the upstream body as a string).
            metadata = _dict(error.get("metadata"))
            upstream = _upstream_message(metadata.get("raw"))
            if upstream:
                who = metadata.get("provider_name") or "upstream"
                message = f"{message} [{who}: {upstream}]"
            return self._safe(message)
        return self._safe(response.text or response.reason_phrase)

    def _schema_too_complex(self, response: httpx.Response, body: Any) -> bool:
        if response.status_code != 400:
            return False
        return is_schema_too_complex(
            self._error_message(body, response) + " " + response.text[:4000]
        )

    def _status_error(self, status: int, message: str) -> AIProviderError:
        if status == 401:
            return AIUnavailableError(
                "openrouter: credentials rejected (401); check OPENROUTER_API_KEY"
            )
        if status == 402:
            return AIUnavailableError(f"openrouter: insufficient credits (402): {message}")
        if status == 403:
            return AIUnavailableError(f"openrouter: request forbidden (403): {message}")
        if status == 404:
            return AIUnavailableError(
                "openrouter: model or endpoint not found, or no endpoint supports structured "
                f"outputs for this model (404): {message}"
            )
        if status == 408:
            return AITimeoutError(f"openrouter: upstream timeout (408): {message}")
        if status == 429:
            return AIUnavailableError(f"openrouter: rate limited (429): {message}")
        if status >= 500:
            return AIUnavailableError(f"openrouter: provider unavailable ({status}): {message}")
        return AIUnavailableError(f"openrouter: request rejected ({status}): {message}")

    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        started = time.perf_counter()
        mode = self.output_mode
        response = await self._post(self._payload(request, mode))
        body = _json_body(response)
        if mode == JSON_SCHEMA and self._schema_too_complex(response, body):
            # The upstream cannot compile the schema into a grammar (rejected before generation,
            # nothing billed). Fall back once, and for every later call, to the schema in the
            # system prompt. The answer is still parsed with json.loads only and validated by
            # the interpreter exactly like a structured output.
            logger.warning(
                "openrouter: structured outputs rejected the %s schema (%s); using %s mode",
                request.output_name,
                self._error_message(body, response),
                SCHEMA_IN_PROMPT_VERSION,
            )
            self._schema_rejected = True
            mode = PROMPT_SCHEMA
            response = await self._post(self._payload(request, mode))
            body = _json_body(response)
        latency_ms = round((time.perf_counter() - started) * 1000)

        if response.status_code >= 400:
            raise self._status_error(response.status_code, self._error_message(body, response))
        if not isinstance(body, dict):
            raise AIUnavailableError(
                f"openrouter: unexpected response (HTTP {response.status_code}, not a JSON "
                f"object): {self._safe(response.text)}"
            )
        # OpenRouter may report an upstream failure inside a 200 body.
        if isinstance(body.get("error"), dict):
            error = body["error"]
            code = error.get("code")
            status = code if isinstance(code, int) else 502
            raise self._status_error(status, self._error_message(body, response))
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIUnavailableError(
                f"openrouter: unexpected response (no choices): {self._safe(response.text)}"
            )
        choice: dict[str, Any] = choices[0]
        if isinstance(choice.get("error"), dict):
            err = choice["error"]
            code = err.get("code")
            raise self._status_error(
                code if isinstance(code, int) else 502, self._safe(err.get("message", err))
            )
        message = choice.get("message")
        if not isinstance(message, dict):
            raise AIUnavailableError("openrouter: unexpected response (choice without message)")

        text = _content_text(message.get("content"))
        finish_reason = choice.get("finish_reason")
        refusal = message.get("refusal")
        if refusal:
            stop_reason: str | None = "refusal"
        elif finish_reason == "length":
            stop_reason = "max_tokens"
        elif finish_reason == "content_filter":
            stop_reason = "refusal"
        else:
            stop_reason = choice.get("native_finish_reason") or finish_reason

        data: dict[str, Any] | None = None
        # A refusal or a cut-off answer may not match the schema: the interpreter treats a
        # missing/invalid object as invalid output (and may repair once).
        if stop_reason not in ("refusal", "max_tokens"):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            data = parsed if isinstance(parsed, dict) else None

        usage = _dict(body.get("usage"))
        prompt_details = _dict(usage.get("prompt_tokens_details"))
        completion_details = _dict(usage.get("completion_tokens_details"))
        return StructuredResult(
            data=data,
            raw_output=text if text else (str(refusal) if refusal else ""),
            model=str(body.get("model") or self.model),
            input_tokens=_int(usage.get("prompt_tokens")),
            output_tokens=_int(usage.get("completion_tokens")),
            latency_ms=latency_ms,
            stop_reason=stop_reason,
            cost_usd=_decimal(usage.get("cost")),
            metadata={
                "generation_id": body.get("id"),
                "upstream_provider": body.get("provider"),
                "cached_tokens": _int(prompt_details.get("cached_tokens")),
                "reasoning_tokens": _int(completion_details.get("reasoning_tokens")),
                "finish_reason": finish_reason,
                "output_mode": mode,
            },
        )


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _upstream_message(raw: Any) -> str | None:
    """The upstream error message inside OpenRouter's `metadata.raw` (a JSON string)."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw
    error = _dict(_dict(parsed).get("error"))
    return str(error.get("message") or raw)


def _content_text(content: Any) -> str:
    """`message.content` is a string, or a list of parts on some upstreams."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in (None, "text")
        )
    return ""


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None
