"""Vendor-neutral JSON Schema handling for structured outputs, shared by the real providers.

Claude's structured outputs (direct or through a gateway such as OpenRouter) do not accept
numeric/length constraints, so they are moved into field descriptions here and enforced by
Pydantic afterwards — the interpreter never trusts the output either way.

They also compile the schema into a grammar with size limits, and the full `SpecificationDraft`
schema exceeds them ("compiled grammar is too large", a 400 before any generation). Providers
then fall back — once, and for every later call — to the `prompt_schema` mode: the JSON Schema
goes into the system prompt (`prompt_schema_system`) and no grammar is requested. Both modes
parse the answer with `json.loads` only and are validated identically by the interpreter.
"""

from typing import Any

from app.modules.ai.prompts.shared import schema_in_prompt_block

JSON_SCHEMA = "json_schema"  # strict structured outputs (grammar-constrained)
PROMPT_SCHEMA = "prompt_schema"  # fallback: schema in the system prompt, JSON-only answer

# Upstream messages meaning "this schema is too complex for structured outputs". Matched
# case-insensitively; anything else is a normal error and never triggers the fallback.
SCHEMA_TOO_COMPLEX_MARKERS = (
    "grammar is too large",
    "schema is too complex",
    "too many optional",
    "simplify your tool schemas",
    "schema too large",
)


def is_schema_too_complex(text: str) -> bool:
    """True if a provider error message says the output schema cannot be compiled."""
    lowered = text.lower()
    return any(marker in lowered for marker in SCHEMA_TOO_COMPLEX_MARKERS)


def prompt_schema_system(system: str, schema: dict[str, Any]) -> str:
    """The system prompt for `prompt_schema` mode (static per prompt version: cacheable)."""
    return f"{system}\n\n{schema_in_prompt_block(schema)}"


# JSON Schema keywords structured outputs reject; they are kept as text for the model.
_UNSUPPORTED_KEYWORDS = {
    "minimum": "minimum",
    "maximum": "maximum",
    "exclusiveMinimum": "greater than",
    "exclusiveMaximum": "less than",
    "multipleOf": "multiple of",
    "minLength": "min length",
    "maxLength": "max length",
    "pattern": "pattern",
    "minItems": "min items",
    "maxItems": "max items",
    "uniqueItems": "unique items",
}


def structured_output_schema(schema: Any) -> Any:
    """Copy of `schema` without unsupported constraints (described in `description` instead)."""
    if isinstance(schema, list):
        return [structured_output_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    notes: list[str] = []
    for key, value in schema.items():
        if key in _UNSUPPORTED_KEYWORDS and not isinstance(value, dict):
            notes.append(f"{_UNSUPPORTED_KEYWORDS[key]} {value}")
        elif key == "properties" and isinstance(value, dict):
            out[key] = {name: structured_output_schema(prop) for name, prop in value.items()}
        else:
            out[key] = structured_output_schema(value)
    if notes:
        prefix = f"{out['description']} " if "description" in out else ""
        out["description"] = f"{prefix}({'; '.join(notes)})"
    return out
