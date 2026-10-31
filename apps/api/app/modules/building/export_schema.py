"""Export the canonical JSON Schemas (consumed by packages/schema codegen).

Usage:  python -m app.modules.building.export_schema <output-dir>

Writes building-model.schema.json (serialization shape: what the API emits) and
building-specification.schema.json (validation shape: what clients may send; fields with
defaults are optional).
"""

import json
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from app.modules.building.model import SCHEMA_VERSION, BuildingModel
from app.modules.building.specification import SPEC_SCHEMA_VERSION, BuildingSpecification

MODEL_SCHEMA_FILE = "building-model.schema.json"
SPEC_SCHEMA_FILE = "building-specification.schema.json"


def strip_property_titles(node: Any) -> Any:
    """Pydantic titles every property ("Id", "Name", ...); code generators turn each into a
    named alias type. Keep titles only on models/enums ($defs), which name real types."""
    if isinstance(node, dict):
        out = {k: strip_property_titles(v) for k, v in node.items()}
        # A default next to a $ref makes TS generators emit duplicate types (Style1, ...).
        # Defaults are applied by Pydantic on the server; the schema doesn't need to carry them.
        if "$ref" in out:
            out.pop("default", None)
        props = out.get("properties")
        # Only object *schemas* (not a properties map that has a field named "properties").
        if out.get("type") == "object" and isinstance(props, dict):
            out["properties"] = {
                name: {k: v for k, v in prop.items() if k != "title"}
                for name, prop in props.items()
            }
        return out
    if isinstance(node, list):
        return [strip_property_titles(v) for v in node]
    return node


def _export(
    model: type[BaseModel], mode: Literal["validation", "serialization"], version: str
) -> dict[str, Any]:
    schema = strip_property_titles(model.model_json_schema(mode=mode))
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$comment": f"GENERATED from Pydantic (schema_version {version}). Do not edit.",
        **schema,
    }


def building_model_json_schema() -> dict[str, Any]:
    # Serialization mode: exactly the shape the API emits (defaulted fields are required).
    return _export(BuildingModel, "serialization", SCHEMA_VERSION)


def building_specification_json_schema() -> dict[str, Any]:
    # Validation mode: the shape a client (form, AI) may send; defaulted fields are optional.
    return _export(BuildingSpecification, "validation", SPEC_SCHEMA_VERSION)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.modules.building.export_schema <output-dir>")
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for name, schema in (
        (MODEL_SCHEMA_FILE, building_model_json_schema()),
        (SPEC_SCHEMA_FILE, building_specification_json_schema()),
    ):
        text = json.dumps(schema, indent=2, ensure_ascii=False) + "\n"
        (out / name).write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
