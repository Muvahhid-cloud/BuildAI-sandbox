"""BuildingModel 1.2.0 → 1.3.0 (additive, V3): `slab_kind` gains `canopy`.

No 1.2.0 document can contain a canopy, so an upgrade changes only the version; geometry,
materials, properties and relationships are untouched (checked by the geometry fingerprint).
"""

import copy
from typing import Any

FROM_VERSION = "1.2.0"
TO_VERSION = "1.3.0"


def upgrade(doc: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(doc)
    out["schema_version"] = TO_VERSION
    return out
