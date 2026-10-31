"""Read-only shared data files (data/): material library, rules profiles. Cached per process."""

import json
from functools import lru_cache
from pathlib import Path

from app.modules.rules.loader import load_rules_profile
from app.modules.rules.profile import BuildingRulesProfile

MATERIAL_LIBRARY_PATH = Path("materials") / "library.json"


@lru_cache
def material_ids(data_dir: Path) -> frozenset[str]:
    library = json.loads((data_dir / MATERIAL_LIBRARY_PATH).read_text(encoding="utf-8"))
    return frozenset(m["id"] for m in library["materials"])


def rules_profile(data_dir: Path, ref: str) -> BuildingRulesProfile:
    return load_rules_profile(data_dir, ref)
