"""Design intent and design-system precedence (K3: building/design.py, facades.py, appearance)."""

import math
from typing import Any

import pytest

from app.modules.building.appearance import PALETTE, color_name, resolve_color
from app.modules.building.design import (
    DesignCatalog,
    check_design,
    check_intent,
    effective_design,
    effective_facade_color,
    resolve_facade_preferences,
    resolve_window_preferences,
)
from app.modules.building.enums import WallKind
from app.modules.building.facades import (
    FACADE_OF_PLAN_SIDE,
    PLAN_SIDE,
    facade_of_normal,
    facade_of_wall,
    normalize_facade,
)
from app.modules.building.specification import BuildingSpecification, FacadeSide, WindowStyle
from app.modules.catalog.design_systems import design_catalog
from tests.catalog.helpers import approved_design_registry


def spec(**parts: Any) -> BuildingSpecification:
    doc: dict[str, Any] = {
        "name": "House",
        "targets": {"storeys": 2},
        "rooms": [{"key": "living", "type": "living"}, {"key": "bedroom", "type": "bedroom"}],
    }
    for key, value in parts.items():
        doc[key] = value
    return BuildingSpecification.model_validate(doc)


def approved() -> DesignCatalog:
    return design_catalog(approved_design_registry())


# --- colors ---------------------------------------------------------------------------------


def test_palette_is_valid_hex_and_names_resolve() -> None:
    for name, hex_value in PALETTE.items():
        assert resolve_color(name) is not None
        assert resolve_color(name).hex == hex_value  # type: ignore[union-attr]
    assert resolve_color("#e8c547").name == "yellow"  # type: ignore[union-attr]
    assert resolve_color("#123456").name is None  # type: ignore[union-attr]
    assert resolve_color("mauve") is None


@pytest.mark.parametrize(
    ("word", "name"),
    [("yellow", "yellow"), ("Gray", "grey"), ("light grey", "light_grey"), ("beige", "warm_beige")],
)
def test_color_words_map_to_palette_names(word: str, name: str) -> None:
    assert color_name(word) == name


def test_no_explicit_color_and_no_system_means_no_color() -> None:
    assert effective_facade_color(spec(), None) is None
    assert effective_design(spec(), None) is None  # the no-intent path records nothing


def test_explicit_yellow_facade() -> None:
    s = spec(design={"facade_color": "yellow"})
    color = effective_facade_color(s, None)
    assert color is not None and color.hex == PALETTE["yellow"] and color.source == "user"


def test_design_system_default_color_applies_when_user_gives_none() -> None:
    system = approved().get("modern-minimal")
    assert system is not None
    color = effective_facade_color(spec(style={"design_system": "modern-minimal"}), system)
    assert color is not None and color.name == "white" and color.source == "design_system"


def test_user_color_overrides_design_system_default() -> None:
    system = approved().get("modern-minimal")
    s = spec(style={"design_system": "modern-minimal"}, design={"facade_color": "yellow"})
    color = effective_facade_color(s, system)
    assert color is not None and color.name == "yellow" and color.source == "user"
    record = effective_design(s, system)
    assert record is not None and record.design_system is system


# --- facades --------------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["backyard", "Back yard", "garden", "rear", "back", "yard"])
def test_backyard_synonyms_are_the_rear_facade(word: str) -> None:
    assert normalize_facade(word) == FacadeSide.REAR


@pytest.mark.parametrize("word", ["street", "front", "entrance", "front facade", "street side"])
def test_street_synonyms_are_the_front_facade(word: str) -> None:
    assert normalize_facade(word) == FacadeSide.FRONT


def test_unknown_facade_words() -> None:
    assert normalize_facade("roof") is None


def test_facade_follows_the_outward_normal_not_the_camera() -> None:
    # Exterior walls run counter-clockwise: S wall along +x has its outside at -y.
    assert facade_of_wall(WallKind.EXTERIOR, 0.0) == FacadeSide.FRONT
    assert facade_of_wall(WallKind.EXTERIOR, math.pi / 2) == FacadeSide.RIGHT
    assert facade_of_wall(WallKind.EXTERIOR, math.pi) == FacadeSide.REAR
    assert facade_of_wall(WallKind.EXTERIOR, -math.pi / 2) == FacadeSide.LEFT
    assert facade_of_wall(WallKind.INTERIOR, 0.0) is None
    assert facade_of_normal(0.0, -1.0) == FacadeSide.FRONT
    assert {FACADE_OF_PLAN_SIDE[PLAN_SIDE[f]] for f in FacadeSide} == set(FacadeSide)


# --- window and room preferences --------------------------------------------------------------


def test_without_intent_every_facade_keeps_the_building_window_style() -> None:
    s = spec(style={"window_style": "large"})
    assert set(resolve_window_preferences(s).values()) == {WindowStyle.LARGE}


def test_emphasis_is_concentrated_on_preferred_facades() -> None:
    s = spec(
        design={
            "windows": {
                "emphasis": "panoramic",
                "preferred_facades": ["rear"],
                "excluded_facades": ["front"],
            }
        }
    )
    prefs = resolve_window_preferences(s)
    assert prefs[FacadeSide.REAR] == WindowStyle.PANORAMIC
    assert prefs[FacadeSide.FRONT] == WindowStyle.STANDARD
    assert prefs[FacadeSide.LEFT] == prefs[FacadeSide.RIGHT] == WindowStyle.STANDARD


def test_excluded_facade_never_gets_a_large_building_style() -> None:
    s = spec(
        style={"window_style": "large"},
        design={
            "windows": {
                "emphasis": "panoramic",
                "preferred_facades": ["rear"],
                "excluded_facades": ["front"],
            }
        },
    )
    prefs = resolve_window_preferences(s)
    assert prefs[FacadeSide.FRONT] == WindowStyle.STANDARD
    assert prefs[FacadeSide.LEFT] == WindowStyle.LARGE  # neither preferred nor excluded


def test_room_facing_preferences() -> None:
    s = spec(
        rooms=[
            {"key": "living", "type": "living", "faces": "rear"},
            {"key": "bedroom", "type": "bedroom"},
        ]
    )
    assert resolve_facade_preferences(s) == {"living": FacadeSide.REAR}


# --- tier-2 intent checks -------------------------------------------------------------------


def codes(issues: list[Any]) -> list[str]:
    return [i.code for i in issues]


def test_valid_intent_has_no_issues() -> None:
    s = spec(
        design={
            "facade_color": "yellow",
            "windows": {"preferred_facades": ["rear"], "excluded_facades": ["front"]},
        }
    )
    assert check_intent(s) == []


def test_unknown_color_name_is_appearance_invalid() -> None:
    issues = check_intent(spec(design={"facade_color": "mauve"}))
    assert codes(issues) == ["APPEARANCE_INVALID"]
    assert issues[0].path == "/design/facade_color" and "yellow" in (issues[0].suggestion or "")


def test_facade_both_preferred_and_excluded_conflicts() -> None:
    s = spec(design={"windows": {"preferred_facades": ["rear"], "excluded_facades": ["rear"]}})
    assert codes(check_intent(s)) == ["WINDOW_FACADE_CONFLICT"]


def test_duplicate_facades_and_left_facing_rooms_are_invalid() -> None:
    s = spec(
        design={"windows": {"preferred_facades": ["rear", "rear"]}},
        rooms=[{"key": "living", "type": "living", "faces": "left"}],
    )
    assert codes(check_intent(s)) == ["FACADE_PREFERENCE_INVALID", "FACADE_PREFERENCE_INVALID"]


# --- design system against the catalog --------------------------------------------------------


def test_repository_design_systems_are_drafts_and_blocked() -> None:
    from tests.catalog.helpers import real_registry

    catalog = design_catalog(real_registry())
    assert catalog.available == []
    assert {d.id for d in catalog.unavailable} == {
        "modern-minimal",
        "contemporary-warm",
        "classic-brick",
        "scandinavian-timber",
    }
    issues = check_design(spec(style={"design_system": "modern-minimal"}), catalog)
    assert codes(issues) == ["DESIGN_SYSTEM_NOT_APPROVED"]
    assert "draft" in issues[0].message


def test_unknown_design_system() -> None:
    issues = check_design(spec(style={"design_system": "art-deco"}), approved())
    assert codes(issues) == ["DESIGN_SYSTEM_UNKNOWN"]
    assert "modern-minimal" in (issues[0].suggestion or "")


def test_values_inside_the_system_have_no_conflicts() -> None:
    s = spec(
        style={
            "design_system": "modern-minimal",
            "roof": {"type": "flat"},
            "window_style": "large",
            "facade_material": "render",
        },
        design={"facade_color": "yellow"},
    )  # custom colors are allowed in modern-minimal
    assert check_design(s, approved()) == []


def test_values_outside_the_system_conflict_and_are_never_changed() -> None:
    s = spec(
        style={
            "design_system": "classic-brick",
            "architectural_style": "modern",
            "roof": {"type": "flat"},
            "window_style": "panoramic",
            "facade_material": "concrete",
        },
        design={"facade_color": "yellow"},
    )
    issues = check_design(s, approved())
    assert codes(issues) == ["DESIGN_OPTION_CONFLICT"] * 5
    paths = {i.path for i in issues}
    assert paths == {
        "/style/architectural_style",
        "/style/roof/type",
        "/style/window_style",
        "/style/facade_material",
        "/design/facade_color",
    }
    assert all(i.suggestion for i in issues)
    assert s.design.facade_color == "yellow"  # the explicit request stays as it was


def test_system_palette_limits_colors_when_custom_colors_are_off() -> None:
    ok = spec(
        style={"design_system": "contemporary-warm", "roof": {"type": "gable"}},
        design={"facade_color": "terracotta"},
    )
    assert check_design(ok, approved()) == []
    bad = spec(
        style={"design_system": "contemporary-warm", "roof": {"type": "gable"}},
        design={"facade_color": "black"},
    )
    issues = check_design(bad, approved())
    assert codes(issues) == ["DESIGN_OPTION_CONFLICT"] and "terracotta" in (
        issues[0].suggestion or ""
    )
