"""BuildingModel 1.1.0 → 1.2.0 (additive, K3): design metadata becomes explicit and empty.

An upgraded model has no design system, no appearance overrides and no window size classes —
nothing is inferred or back-filled; geometry, materials, properties and relationships are
untouched (checked by the geometry fingerprint).
"""

import copy
from typing import Any

FROM_VERSION = "1.1.0"
TO_VERSION = "1.2.0"


def upgrade(doc: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    out["schema_version"] = TO_VERSION
    out.setdefault("design", None)
    for element in out.get("elements", []):
        if not isinstance(element, dict):
            continue
        props = element.get("properties")
        if not isinstance(props, dict):
            continue
        if element.get("type") == "wall":
            props.setdefault("finish_left_color", None)
            props.setdefault("finish_right_color", None)
        elif element.get("type") == "window":
            props.setdefault("size_class", None)
    return out
