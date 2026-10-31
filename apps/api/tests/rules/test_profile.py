from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.modules.building.enums import RoomType
from app.modules.rules.loader import RulesProfileNotFoundError, load_rules_profile, parse_ref
from tests.building.helpers import DATA_DIR

REF = "generic-residential@1"


def test_generic_profile_loads() -> None:
    profile = load_rules_profile(DATA_DIR, REF)
    assert profile.ref == REF
    assert profile.room(RoomType.BEDROOM).min_width_m == 2.7
    assert profile.room(RoomType.BEDROOM).requires_window
    # Unlisted types fall back to "default".
    assert profile.room(RoomType.HALL).min_area_m2 == profile.rooms["hall"].min_area_m2
    assert profile.stairs.max_risers_per_flight == 16
    assert "not a building-code compliance" in profile.disclaimer.lower() or (
        "conceptual" in profile.disclaimer.lower()
    )


def test_rule_refs_are_traceable() -> None:
    profile = load_rules_profile(DATA_DIR, REF)
    assert profile.rule_ref("stairs.riser_m") == "generic-residential@1:stairs.riser_m"
    assert profile.room_rule_ref(RoomType.BEDROOM) == "generic-residential@1:rooms.bedroom"
    assert profile.room_rule_ref(RoomType.HALL) == "generic-residential@1:rooms.hall"


def test_extends_deep_merges_parent(tmp_path: Path) -> None:
    base = yaml.safe_load(
        (DATA_DIR / "rules-profiles" / "generic-residential.v1.yaml").read_text(encoding="utf-8")
    )
    (tmp_path / "rules-profiles").mkdir()
    (tmp_path / "rules-profiles" / "generic-residential.v1.yaml").write_text(
        yaml.safe_dump(base), encoding="utf-8"
    )
    regional = {
        "id": "kz-residential",
        "version": 1,
        "name": "Regional",
        "extends": REF,
        "rooms": {"bedroom": {"min_area_m2": 10.0, "min_width_m": 2.8}},
        "stairs": {"riser_m": {"min": 0.15, "max": 0.18}},
    }
    (tmp_path / "rules-profiles" / "kz-residential.v1.yaml").write_text(
        yaml.safe_dump(regional), encoding="utf-8"
    )
    profile = load_rules_profile(tmp_path, "kz-residential@1")
    assert profile.ref == "kz-residential@1"
    assert profile.room(RoomType.BEDROOM).min_area_m2 == 10.0
    assert profile.room(RoomType.LIVING).min_area_m2 == 16.0  # inherited
    assert profile.stairs.riser_m.max == 0.18
    assert profile.stairs.tread_m.min == 0.25  # sibling keys of an override are kept


@pytest.mark.parametrize("ref", ["generic-residential", "Generic@1", "generic-residential@0"])
def test_invalid_refs(ref: str) -> None:
    with pytest.raises(RulesProfileNotFoundError):
        parse_ref(ref)


def test_missing_profile() -> None:
    with pytest.raises(RulesProfileNotFoundError):
        load_rules_profile(DATA_DIR, "generic-residential@99")


def test_unknown_room_types_are_rejected(tmp_path: Path) -> None:
    base = yaml.safe_load(
        (DATA_DIR / "rules-profiles" / "generic-residential.v1.yaml").read_text(encoding="utf-8")
    )
    base["rooms"]["ballroom"] = {"min_area_m2": 1, "min_width_m": 1}
    (tmp_path / "rules-profiles").mkdir()
    (tmp_path / "rules-profiles" / "generic-residential.v1.yaml").write_text(
        yaml.safe_dump(base), encoding="utf-8"
    )
    with pytest.raises(ValidationError, match="ballroom"):
        load_rules_profile(tmp_path, REF)
