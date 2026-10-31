"""BuildingModel 1.0.0 → 1.1.0 (additive): type metadata becomes explicit and empty.

An upgraded model is untyped — nothing is inferred or back-filled; geometry, materials,
properties and relationships are untouched (checked by the geometry fingerprint).
"""

import copy
from typing import Any

FROM_VERSION = "1.0.0"
TO_VERSION = "1.1.0"


def upgrade(doc: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    out["schema_version"] = TO_VERSION
    out.setdefault("types", [])
    out.setdefault("assemblies", [])
    for element in out.get("elements", []):
        if not isinstance(element, dict):
            continue
        element.setdefault("type_ref", None)
        props = element.get("properties")
        if element.get("type") == "room" and isinstance(props, dict):
            props.setdefault("ceiling_assembly_ref", None)
    return out
