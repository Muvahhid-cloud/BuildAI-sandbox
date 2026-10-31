"""AnthropicProvider: Claude through the official `anthropic` SDK (the only file importing it).

One Messages API call per request. The answer is constrained with structured outputs
(`output_config.format` = JSON Schema of `SpecificationDraft`), which works on every current
Claude model (unlike forced `tool_choice`). Unsupported numeric/length constraints are moved
into field descriptions (`json_schema.structured_output_schema`) and enforced by Pydantic
afterwards — the interpreter never trusts the output either way.

If the API rejects the schema because its compiled grammar is too large (a 400 before any
generation), the provider switches — for this and every later call — to the shared
`prompt_schema` fallback (`json_schema.prompt_schema_system`): the schema goes into the system
prompt and no `output_config.format` is sent. The answer is parsed with `json.loads` only in
both modes; the mode is reported in `StructuredResult.metadata["output_mode"]`.

The system prompt carries a cache breakpoint: it is static per prompt version, so repeated
generations and the repair call reuse the cached prefix.
"""

import json
import logging
import time
from typing import Any

import anthropic

from app.modules.ai.errors import AITimeoutError, AIUnavailableError
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

__all__ = ["AnthropicProvider", "structured_output_schema"]

logger = logging.getLogger(__name__)


def _error_text(exc: anthropic.APIStatusError) -> str:
    """Message + body of an API error, for matching (the SDK never includes the key)."""
    return f"{exc.message} {exc.body if exc.body is not None else ''}"


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str | None = None,
        timeout_s: float = 120.0,
        max_retries: int = 1,
        effort: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model
        self._effort = effort
        # `client` is injectable for unit tests (a fake with `messages.create`).
        self._client: Any = client or anthropic.AsyncAnthropic(
            api_key=api_key, base_url=base_url, timeout=timeout_s, max_retries=max_retries
        )
        # Set once the API refused to compile the output schema; later calls go straight to
        # the schema-in-prompt mode (no repeated failing request).
        self._schema_rejected = False

    @property
    def output_mode(self) -> str:
        return PROMPT_SCHEMA if self._schema_rejected else JSON_SCHEMA

    def _params(self, request: StructuredRequest, mode: str) -> dict[str, Any]:
        system = request.system
        output_config: dict[str, Any] = {}
        if mode == JSON_SCHEMA:
            output_config["format"] = {
                "type": "json_schema",
                "schema": structured_output_schema(request.output_schema),
            }
        else:
            system = prompt_schema_system(system, request.output_schema)
        if self._effort:
            output_config["effort"] = self._effort
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        }
        if output_config:
            params["output_config"] = output_config
        return params

    async def _create(self, params: dict[str, Any]) -> Any:
        try:
            return await self._client.messages.create(**params)
        except anthropic.APITimeoutError as exc:
            raise AITimeoutError(f"anthropic: timeout ({exc})") from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise AIUnavailableError(
                f"anthropic: credentials rejected ({exc.status_code}); check ANTHROPIC_API_KEY"
            ) from exc
        except anthropic.NotFoundError as exc:
            raise AIUnavailableError(f"anthropic: model or endpoint not found ({exc})") from exc
        except anthropic.RateLimitError as exc:
            raise AIUnavailableError(f"anthropic: rate limited ({exc.status_code})") from exc
        except anthropic.APIStatusError as exc:
            raise AIUnavailableError(f"anthropic: HTTP {exc.status_code} ({exc.message})") from exc
        except anthropic.APIConnectionError as exc:
            raise AIUnavailableError(f"anthropic: connection failed ({exc})") from exc

    async def complete_structured(self, request: StructuredRequest) -> StructuredResult:
        started = time.perf_counter()
        mode = self.output_mode
        try:
            response = await self._create(self._params(request, mode))
        except AIUnavailableError as err:
            cause = err.__cause__
            if not (
                mode == JSON_SCHEMA
                and isinstance(cause, anthropic.BadRequestError)
                and is_schema_too_complex(_error_text(cause))
            ):
                raise
            # The API cannot compile the schema into a grammar (rejected before generation).
            # Fall back once, and for every later call, to the schema in the system prompt;
            # the interpreter validates the answer exactly like a structured output.
            logger.warning(
                "anthropic: structured outputs rejected the %s schema (%s); using %s mode",
                request.output_name,
                cause.message,
                SCHEMA_IN_PROMPT_VERSION,
            )
            self._schema_rejected = True
            mode = PROMPT_SCHEMA
            response = await self._create(self._params(request, mode))
        latency_ms = round((time.perf_counter() - started) * 1000)

        text = "".join(
            block.text for block in response.content if getattr(block, "type", None) == "text"
        )
        data: dict[str, Any] | None = None
        # A refusal or a max_tokens cut-off may not match the schema: the interpreter treats a
        # missing/invalid object as invalid output (and may repair once).
        if response.stop_reason not in ("refusal", "max_tokens"):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            data = parsed if isinstance(parsed, dict) else None
        usage = response.usage
        return StructuredResult(
            data=data,
            raw_output=text,
            model=str(getattr(response, "model", self.model)),
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0)
            + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            latency_ms=latency_ms,
            stop_reason=response.stop_reason,
            metadata={
                "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
                "request_id": getattr(response, "_request_id", None),
                "output_mode": mode,
            },
        )
