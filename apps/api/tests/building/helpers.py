import json
from pathlib import Path
from typing import Any

from app.modules.building.elements import Element
from app.modules.building.model import BuildingModel

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
FIXTURE_PATH = DATA_DIR / "fixtures" / "demo-house.model.json"
SCHEMA_PATH = REPO_ROOT / "packages" / "schema" / "generated" / "building-model.schema.json"
SPEC_SCHEMA_PATH = (
    REPO_ROOT / "packages" / "schema" / "generated" / "building-specification.schema.json"
)
SPECS_DIR = DATA_DIR / "fixtures" / "specs"


def material_ids() -> set[str]:
    lib = json.loads((DATA_DIR / "materials" / "library.json").read_text(encoding="utf-8"))
    return {m["id"] for m in lib["materials"]}


def find(model: BuildingModel, semantic_key: str) -> tuple[int, Element]:
    for i, el in enumerate(model.elements):
        if el.semantic_key == semantic_key:
            return i, el
    raise KeyError(semantic_key)


def with_element(model: BuildingModel, semantic_key: str, **update: Any) -> BuildingModel:
    """Copy of `model` with one element's fields replaced (no re-validation, on purpose)."""
    i, el = find(model, semantic_key)
    elements = list(model.elements)
    elements[i] = el.model_copy(update=update)
    return model.model_copy(update={"elements": elements})
