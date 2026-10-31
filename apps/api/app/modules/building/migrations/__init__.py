"""Upgrade-on-read for stored BuildingModel documents (docs/building-model.md §8).

Stored versions are immutable: rows keep the JSON (and hash) they were written with. Every read
of a stored or file-based model goes through `load_model`, which upgrades the document step by
step to the current `SCHEMA_VERSION` and validates it. Upgrades are pure and idempotent.
"""

import json
from collections.abc import Callable
from typing import Any

from app.modules.building.migrations import v1_0_0_to_v1_1_0, v1_1_0_to_v1_2_0
from app.modules.building.model import SCHEMA_VERSION, BuildingModel

Upgrade = Callable[[dict[str, Any]], dict[str, Any]]

# from-version -> (to-version, pure upgrade function)
UPGRADES: dict[str, tuple[str, Upgrade]] = {
    v1_0_0_to_v1_1_0.FROM_VERSION: (v1_0_0_to_v1_1_0.TO_VERSION, v1_0_0_to_v1_1_0.upgrade),
    v1_1_0_to_v1_2_0.FROM_VERSION: (v1_1_0_to_v1_2_0.TO_VERSION, v1_1_0_to_v1_2_0.upgrade),
}


class ModelVersionError(ValueError):
    pass


def upgrade_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Return `doc` upgraded to the current schema version; `doc` itself is never modified."""
    current = doc
    seen: set[str] = set()
    while (version := current.get("schema_version")) != SCHEMA_VERSION:
        if not isinstance(version, str) or version not in UPGRADES or version in seen:
            raise ModelVersionError(f"Unsupported BuildingModel schema_version {version!r}")
        seen.add(version)
        _, step = UPGRADES[version]
        current = step(current)
    return current


def load_model(doc: dict[str, Any]) -> BuildingModel:
    """The one way to turn a stored model document into a BuildingModel."""
    return BuildingModel.model_validate(upgrade_document(doc))


def load_model_json(text: str | bytes) -> BuildingModel:
    doc = json.loads(text)
    if not isinstance(doc, dict):
        raise ModelVersionError("A BuildingModel document must be a JSON object")
    return load_model(doc)
