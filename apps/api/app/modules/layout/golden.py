"""Golden files for the reference specifications (data/fixtures/specs).

A golden file is a compact, reviewable summary of what the engine generates for a spec + seed:
footprint, rooms with areas, element counts, the sha256 of the full model JSON and the geometry
fingerprint (building/fingerprint.py: levels + elements without type metadata). Tests fail on
any change; update deliberately (and say why in the commit) with:  pnpm golden

It also writes data/fixtures/generated-house.model.json (reference spec 01, seed 0) and
generated-l-house.model.json (reference spec 11, the L-shaped footprint) and
generated-t-house.model.json (reference spec 12, the T-shaped footprint), the shared fixtures
the web tests use to check that generated models render through the 3D engine.
"""

import hashlib
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from app.modules.building.elements import Room
from app.modules.building.fingerprint import geometry_sha256
from app.modules.building.specification import BuildingSpecification
from app.modules.building.summary import summarize
from app.modules.layout.config import DEFAULT_CONFIG, LayoutConfig
from app.modules.layout.engine import LayoutResult, generate_layout
from app.modules.rules.loader import load_rules_profile

GOLDEN_NAMESPACE = uuid.UUID("0b0e4f7c-6d0a-4a55-9a4c-2d6c1a0f5e11")
GOLDEN_SEED = 0
RULES_REF = "generic-residential@1"
GENERATED_FIXTURE = "generated-house.model.json"
GENERATED_FIXTURE_SPEC = "01-family-house-280.spec.json"
# The L-shaped reference (V1.1); the web tests render it through the 3D engine too.
GENERATED_L_FIXTURE = "generated-l-house.model.json"
GENERATED_L_FIXTURE_SPEC = "11-l-shaped-bungalow-160.spec.json"
GENERATED_T_FIXTURE = "generated-t-house.model.json"
GENERATED_T_FIXTURE_SPEC = "12-t-shaped-bungalow-170.spec.json"


def generate_reference(
    data_dir: Path,
    spec_path: Path,
    seed: int = GOLDEN_SEED,
    config: LayoutConfig = DEFAULT_CONFIG,
) -> LayoutResult:
    spec = BuildingSpecification.model_validate_json(spec_path.read_text(encoding="utf-8"))
    library = json.loads((data_dir / "materials" / "library.json").read_text(encoding="utf-8"))
    return generate_layout(
        spec,
        load_rules_profile(data_dir, RULES_REF),
        id_namespace=GOLDEN_NAMESPACE,
        seed=seed,
        config=config,
        material_ids={m["id"] for m in library["materials"]},
    )


def golden_summary(result: LayoutResult) -> dict[str, Any]:
    model = result.model
    levels = {lvl.id: lvl.index for lvl in model.levels}
    counts: dict[str, int] = {}
    for el in model.elements:
        counts[el.type] = counts.get(el.type, 0) + 1
    rooms = sorted(
        (
            levels[el.level_id] if el.level_id else -1,
            el.semantic_key,
            el.properties.room_type.value,
            el.dimensions.area,
        )
        for el in model.elements
        if isinstance(el, Room)
    )
    metrics = result.metrics
    return {
        "engine_version": model.engine_version,
        "seed": model.seed,
        "footprint_m": [metrics.footprint_width_m, metrics.footprint_depth_m] if metrics else None,
        "summary": summarize(model).model_dump(mode="json"),
        "element_counts": dict(sorted(counts.items())),
        "rooms": [
            {"level": lv, "key": key, "type": t, "area_m2": area} for lv, key, t, area in rooms
        ],
        "warnings": sorted(w.code for w in result.warnings),
        "model_sha256": hashlib.sha256(model.model_dump_json().encode("utf-8")).hexdigest(),
        "geometry_sha256": geometry_sha256(model),
    }


def golden_path(golden_dir: Path, spec_path: Path) -> Path:
    return golden_dir / spec_path.name.replace(".spec.json", ".golden.json")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m app.modules.layout.golden <data-dir>")
    data_dir = Path(sys.argv[1]).resolve()
    specs = sorted((data_dir / "fixtures" / "specs").glob("*.spec.json"))
    golden_dir = data_dir / "fixtures" / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    for spec_path in specs:
        result = generate_reference(data_dir, spec_path)
        text = json.dumps(golden_summary(result), indent=2, ensure_ascii=False) + "\n"
        golden_path(golden_dir, spec_path).write_text(text, encoding="utf-8", newline="\n")
        fixture = {
            GENERATED_FIXTURE_SPEC: GENERATED_FIXTURE,
            GENERATED_L_FIXTURE_SPEC: GENERATED_L_FIXTURE,
            GENERATED_T_FIXTURE_SPEC: GENERATED_T_FIXTURE,
        }.get(spec_path.name)
        if fixture is not None:
            (data_dir / "fixtures" / fixture).write_text(
                result.model.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
            )
        print(f"{spec_path.name}: {result.model.engine_version} ok")


if __name__ == "__main__":
    main()
