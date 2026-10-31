import uuid
from functools import cache
from typing import Any

from app.modules.building.elements import Room
from app.modules.building.enums import RoomType
from app.modules.building.model import BuildingModel
from app.modules.building.specification import BuildingSpecification
from app.modules.layout.engine import LayoutResult, generate_layout
from app.modules.layout.golden import generate_reference
from app.modules.rules.loader import load_rules_profile
from tests.building.helpers import DATA_DIR, SPECS_DIR, material_ids

PROFILE = load_rules_profile(DATA_DIR, "generic-residential@1")
NAMESPACE = uuid.UUID("11111111-2222-4333-8444-555555555555")
SPEC_PATHS = sorted(SPECS_DIR.glob("*.spec.json"))


@cache
def reference(name: str) -> LayoutResult:
    """Generated once per test session (the engine is deterministic)."""
    return generate_reference(DATA_DIR, SPECS_DIR / name)


def load_spec(name: str) -> BuildingSpecification:
    return BuildingSpecification.model_validate_json((SPECS_DIR / name).read_text("utf-8"))


def generate(spec: BuildingSpecification | dict[str, Any], seed: int = 0) -> LayoutResult:
    s = (
        spec
        if isinstance(spec, BuildingSpecification)
        else BuildingSpecification.model_validate(spec)
    )
    return generate_layout(
        s, PROFILE, id_namespace=NAMESPACE, seed=seed, material_ids=material_ids()
    )


def rooms_of(model: BuildingModel, room_type: RoomType) -> list[Room]:
    return [
        el for el in model.elements if isinstance(el, Room) and el.properties.room_type == room_type
    ]
