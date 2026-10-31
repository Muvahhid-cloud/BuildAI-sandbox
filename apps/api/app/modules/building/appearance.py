"""Display colors (K3): a fixed, deterministic palette for appearance intent.

A color here is render appearance only — the face of an element is drawn in this color. It is
never a construction material and carries no thermal, structural, fire or cost meaning; the
element keeps its material id (e.g. an exterior render wall stays `exterior_wall` and is drawn
yellow). The palette is editorial and region-neutral.
"""

import re

from pydantic import Field

from app.modules.building.primitives import Frozen, HexColor

# name -> sRGB hex. Names are the vocabulary offered to people and the AI.
PALETTE: dict[str, str] = {
    "white": "#f4f2ec",
    "off_white": "#ece6d8",
    "warm_beige": "#d9c4a0",
    "sand": "#d6bf8a",
    "yellow": "#e8c547",
    "ochre": "#c99a2e",
    "terracotta": "#b8613f",
    "brick_red": "#8f3b2b",
    "light_grey": "#c9cbcc",
    "grey": "#8d9194",
    "anthracite": "#3b3f44",
    "black": "#1f2124",
    "sage_green": "#9aab8a",
    "light_blue": "#a9c3d6",
    "timber_brown": "#7a5334",
}
# Everyday words for palette names (mock interpreter / UI); the AI is given the names only.
COLOR_SYNONYMS: dict[str, str] = {
    "beige": "warm_beige",
    "cream": "off_white",
    "gray": "grey",
    "light gray": "light_grey",
    "light grey": "light_grey",
    "dark grey": "anthracite",
    "dark gray": "anthracite",
    "charcoal": "anthracite",
    "red": "brick_red",
    "green": "sage_green",
    "blue": "light_blue",
    "brown": "timber_brown",
    "warm beige": "warm_beige",
    "off white": "off_white",
    "off-white": "off_white",
}
_HEX = re.compile(r"^#[0-9a-f]{6}$")


class ResolvedColor(Frozen):
    hex: HexColor
    name: str | None = Field(default=None, max_length=40)  # palette name, if any


def color_name(word: str) -> str | None:
    """Palette name for a word ("gray" -> "grey", "yellow" -> "yellow"), or None."""
    key = " ".join(word.lower().replace("_", " ").split())
    if key.replace(" ", "_") in PALETTE:
        return key.replace(" ", "_")
    return COLOR_SYNONYMS.get(key)


def resolve_color(value: str) -> ResolvedColor | None:
    """A spec color value (palette name or "#rrggbb") as hex; None if it is not valid."""
    if _HEX.match(value):
        name = next((n for n, h in PALETTE.items() if h == value), None)
        return ResolvedColor(hex=value, name=name)
    if value in PALETTE:
        return ResolvedColor(hex=PALETTE[value], name=value)
    return None
