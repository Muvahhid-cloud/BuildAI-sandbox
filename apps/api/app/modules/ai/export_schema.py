"""Export the AI generation API contracts (consumed by packages/schema codegen).

Usage:  python -m app.modules.ai.export_schema <output-dir>

Writes ai-generation.schema.json: the generation record, the history list and the request,
all in serialization shape (one definition per model), so the web app validates responses with
generated Zod schemas instead of a hand-written copy.
"""

import json
import sys
from pathlib import Path
from typing import Any

from pydantic.json_schema import models_json_schema

from app.modules.ai.schemas.responses import AIGenerateRequest, AIGenerationList, AIGenerationOut
from app.modules.building.export_schema import strip_property_titles

AI_SCHEMA_FILE = "ai-generation.schema.json"


def ai_generation_json_schema() -> dict[str, Any]:
    _, schema = models_json_schema(
        [
            (AIGenerationOut, "serialization"),
            (AIGenerationList, "serialization"),
            (AIGenerateRequest, "serialization"),
        ],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": "GENERATED from Pydantic (app/modules/ai/schemas/responses.py). Do not edit.",
        "title": "AIGenerationContracts",
        **strip_property_titles(schema),
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.modules.ai.export_schema <output-dir>")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    text = json.dumps(ai_generation_json_schema(), indent=2, ensure_ascii=False) + "\n"
    (out / AI_SCHEMA_FILE).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
