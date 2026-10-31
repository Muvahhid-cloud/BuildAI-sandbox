"""Loads and validates the demo BuildingModel fixture."""

from functools import lru_cache
from pathlib import Path

from fastapi import status

from app.core.errors import AppError
from app.modules.building.migrations import load_model_json
from app.modules.building.model import BuildingModel
from app.modules.building.validation import errors, validate_model
from app.shared.data_files import material_ids

DEMO_MODEL_PATH = Path("fixtures") / "demo-house.model.json"


class ModelInvalidError(AppError):
    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "MODEL_INVALID"


@lru_cache
def demo_building_model(data_dir: Path) -> BuildingModel:
    """The demo house, validated against the schema and all model invariants.

    An invalid fixture is a server bug: it is reported loudly instead of being served.
    """
    raw = (data_dir / DEMO_MODEL_PATH).read_text(encoding="utf-8")
    model = load_model_json(raw)
    problems = errors(validate_model(model, material_ids=material_ids(data_dir)))
    if problems:
        raise ModelInvalidError(
            "The demo building model violates model invariants",
            details=[{"path": p.path, "message": p.message, "code": p.code} for p in problems],
        )
    return model
