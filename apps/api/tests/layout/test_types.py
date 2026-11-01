"""TypeSet integration of the layout engine (K2): same design values, same geometry."""

import json
import os
import subprocess
import sys

import pytest

from app.modules.building.elements import Furniture, Room, Slab
from app.modules.building.enums import SlabKind
from app.modules.building.fingerprint import geometry_sha256
from app.modules.building.types import TypeSet
from app.modules.building.validation import validate_model
from app.modules.layout.config import DEFAULT_CONFIG, ENGINE_VERSION
from app.modules.layout.engine import LayoutError, generate_layout
from app.modules.layout.golden import GOLDEN_NAMESPACE, golden_path
from app.modules.layout.types import TypeSetError, config_with_types
from tests.building.helpers import DATA_DIR, material_ids
from tests.catalog.helpers import approved_generic_type_set
from tests.layout.helpers import PROFILE, SPEC_PATHS, load_spec, reference

API_ROOT = DATA_DIR.parent / "apps" / "api"
NAMES = [p.name for p in SPEC_PATHS]


def _typed(name: str, type_set: TypeSet | None = None, seed: int = 0):  # type: ignore[no-untyped-def]
    return generate_layout(
        load_spec(name),
        PROFILE,
        id_namespace=GOLDEN_NAMESPACE,
        seed=seed,
        material_ids=material_ids(),
        type_set=type_set or approved_generic_type_set(),
    )


def _replace_type(type_set: TypeSet, type_id: str, **params: object) -> TypeSet:
    types = [
        t.model_copy(update={"params": t.params.model_copy(update=params)})
        if t.id == type_id
        else t
        for t in type_set.types
    ]
    return type_set.model_copy(update={"types": types})


def test_engine_version() -> None:
    assert ENGINE_VERSION == "layout@1.14.0"


def test_generic_types_reproduce_layout_config_exactly() -> None:
    """The generic type pack is a lossless migration of LayoutConfig's design defaults."""
    assert config_with_types(DEFAULT_CONFIG, approved_generic_type_set()) == DEFAULT_CONFIG
    assert config_with_types(DEFAULT_CONFIG, None) is DEFAULT_CONFIG


def test_type_values_replace_config_values() -> None:
    ts = approved_generic_type_set()
    assemblies = [
        a.model_copy(
            update={
                "total_thickness": 0.35,
                "layers": [a.layers[0].model_copy(update={"thickness": 0.35})],
            }
        )
        if a.id == "assembly.wall.generic_exterior_300"
        else a
        for a in ts.assemblies
    ]
    changed = _replace_type(
        ts.model_copy(update={"assemblies": assemblies}),
        "type.door.generic_entrance",
        default_width=1.1,
    )
    cfg = config_with_types(DEFAULT_CONFIG, changed)
    assert cfg.exterior_wall_thickness == 0.35
    assert cfg.entrance_door == (1.1, 2.2)
    assert cfg.interior_wall_thickness == DEFAULT_CONFIG.interior_wall_thickness


def test_values_held_once_must_agree() -> None:
    ts = _replace_type(approved_generic_type_set(), "type.door.generic_garage", thickness=0.08)
    with pytest.raises(TypeSetError, match="door thickness"):
        config_with_types(DEFAULT_CONFIG, ts)
    with pytest.raises(LayoutError) as exc:
        _typed(NAMES[1], ts)
    assert exc.value.code == "LAYOUT_INVALID"


@pytest.mark.parametrize("name", NAMES)
def test_typed_generation_keeps_geometry_identical(name: str) -> None:
    golden = json.loads(
        golden_path(DATA_DIR / "fixtures" / "golden", SPEC_PATHS[NAMES.index(name)]).read_text()
    )
    model = _typed(name).model
    assert geometry_sha256(model) == golden["geometry_sha256"]
    assert geometry_sha256(model) == geometry_sha256(reference(name).model)
    issues = validate_model(model, material_ids=material_ids())
    assert [i for i in issues if i.severity == "error"] == []
    assert not [i for i in issues if i.code == "SNAPSHOT_UNUSED"]
    typed = [el for el in model.elements if el.type_ref is not None]
    untyped = [el for el in model.elements if el.type_ref is None]
    # Rooms, furniture and (V3, BuildingModel 1.3.0) entrance canopies have no type role.
    assert typed and all(
        isinstance(el, Room | Furniture)
        or (isinstance(el, Slab) and el.properties.slab_kind == SlabKind.CANOPY)
        for el in untyped
    )
    assert {t.id for t in model.types} == {el.type_ref for el in typed}
    assert model.metadata.generator.endswith("types buildai-generic-types@1 mapping.generic")


def test_untyped_generation_carries_no_types() -> None:
    model = reference(NAMES[0]).model
    assert model.schema_version == "1.3.0" and model.engine_version == "layout@1.14.0"
    assert model.design is None  # no design system, no intent: nothing recorded
    assert model.types == [] and model.assemblies == []
    assert all(el.type_ref is None for el in model.elements)


def test_typed_generation_is_deterministic() -> None:
    a, b = _typed(NAMES[2], seed=7).model, _typed(NAMES[2], seed=7).model
    assert a.model_dump_json() == b.model_dump_json()


def test_typed_determinism_does_not_depend_on_hash_seed() -> None:
    code = (
        "from tests.layout.test_types import _typed;"
        "import hashlib;"
        "m = _typed('02-compact-bungalow-90.spec.json').model;"
        "print(hashlib.sha256(m.model_dump_json().encode()).hexdigest())"
    )
    hashes = set()
    for hash_seed in ("1", "2"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(API_ROOT)}
        out = subprocess.run(  # noqa: S603 - fixed argv, our own interpreter
            [sys.executable, "-c", code],
            cwd=API_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        hashes.add(out.stdout.strip().splitlines()[-1])
    assert len(hashes) == 1
