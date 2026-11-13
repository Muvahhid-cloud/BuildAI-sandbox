"""Interim facts: what can already be read from the AI's answer while it is still being written.

The structured answer arrives as JSON text, piece by piece. `parse_partial_json` reads the part
that is complete so far (a value that may still continue — an open string, a number at the end
of the text, an unfinished array element — is left out, so a half-written "28" is never shown
for 280). `interim_facts` then picks a few simple facts from it: floors, floor area, rooms by
type, garage, style, roof, balconies, terrace, footprint shape.

They are for display only ("Understood so far"): interim, unvalidated, never used for geometry.
The validated specification still decides everything; once it exists the facts are replaced by
the same reading of that specification.
"""

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

# Only fact keys and values of this shape leave the module (the text comes from a model).
_WORD = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_WHITESPACE = " \t\n\r"
_LITERALS: tuple[tuple[str, Any], ...] = (("true", True), ("false", False), ("null", None))
_DECODER = json.JSONDecoder()
MAX_FACTS = 24

FactKey = Literal[
    "storeys",
    "floor_area_m2",
    "style",
    "roof",
    "footprint_shape",
    "garage_cars",
    "balconies",
    "terrace",
]


class InterimFact(BaseModel):
    """One fact read from the answer so far. `key` is a `FactKey` or `room:<room type>`."""

    key: str = Field(pattern=r"^([a-z][a-z0-9_]{0,39})(:[a-z][a-z0-9_]{0,39})?$")
    value: int | float | str | bool


class _IncompleteError(Exception):
    """The text ends (or stops making sense) inside the value being read."""


def _skip(text: str, i: int) -> int:
    while i < len(text) and text[i] in _WHITESPACE:
        i += 1
    return i


def _scalar(text: str, i: int) -> tuple[Any, int]:
    if i >= len(text):
        raise _IncompleteError
    ch = text[i]
    if ch == '"':
        try:
            value, end = _DECODER.raw_decode(text, i)
        except ValueError:
            raise _IncompleteError from None
        return value, end
    for word, value in _LITERALS:
        if text.startswith(word, i):
            return value, i + len(word)
    match = _NUMBER.match(text, i)
    # A number at the very end of the text may still grow ("28" of "280").
    if match is None or match.end() >= len(text):
        raise _IncompleteError
    number = match.group()
    return (float(number) if any(c in number for c in ".eE") else int(number)), match.end()


def _value(text: str, i: int) -> tuple[Any, int, bool]:
    """(value, next index, complete). A container may come back incomplete with what it holds
    so far; an incomplete scalar raises `_IncompleteError`."""
    i = _skip(text, i)
    if i < len(text) and text[i] == "{":
        return _object(text, i + 1)
    if i < len(text) and text[i] == "[":
        return _array(text, i + 1)
    value, end = _scalar(text, i)
    return value, end, True


def _after_value(text: str, i: int, close: str) -> tuple[int, bool]:
    """After a member: (next index, container closed). Anything but `,` or the closing
    bracket ends the reading (the text stops here, or is not JSON)."""
    i = _skip(text, i)
    if i < len(text) and text[i] == close:
        return i + 1, True
    if i < len(text) and text[i] == ",":
        return i + 1, False
    raise _IncompleteError


def _object(text: str, i: int) -> tuple[dict[str, Any], int, bool]:
    out: dict[str, Any] = {}
    try:
        i = _skip(text, i)
        if i < len(text) and text[i] == "}":
            return out, i + 1, True
        while True:
            i = _skip(text, i)
            if i >= len(text) or text[i] != '"':
                raise _IncompleteError
            key, i = _scalar(text, i)
            i = _skip(text, i)
            if i >= len(text) or text[i] != ":":
                raise _IncompleteError
            value, i, complete = _value(text, i + 1)
            out[key] = value
            if not complete:
                return out, i, False
            i, closed = _after_value(text, i, "}")
            if closed:
                return out, i, True
    except _IncompleteError:
        return out, len(text), False


def _array(text: str, i: int) -> tuple[list[Any], int, bool]:
    """Only finished elements are kept: a half-written room is not a room yet."""
    out: list[Any] = []
    try:
        i = _skip(text, i)
        if i < len(text) and text[i] == "]":
            return out, i + 1, True
        while True:
            value, i, complete = _value(text, i)
            if not complete:
                return out, i, False
            out.append(value)
            i, closed = _after_value(text, i, "]")
            if closed:
                return out, i, True
    except _IncompleteError:
        return out, len(text), False


def parse_partial_json(text: str) -> dict[str, Any]:
    """The JSON object in `text` as far as it is complete (`{}` when there is none yet).
    Never raises: the text is a model's unfinished, untrusted answer."""
    i = _skip(text, 0)
    if i >= len(text) or text[i] != "{":
        return {}
    return _object(text, i + 1)[0]


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _word(value: Any) -> str | None:
    return value if isinstance(value, str) and _WORD.match(value) else None


def _count(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if low <= value <= high else None


def spec_facts_for_display(spec: dict[str, Any]) -> list[InterimFact]:
    """Facts of a (possibly partial, untrusted) specification object, in the order its keys
    appear. Values outside the specification's own ranges are ignored."""
    facts: list[InterimFact] = []

    def add(key: str, value: int | float | str | bool | None) -> None:
        if value is not None and len(facts) < MAX_FACTS:
            facts.append(InterimFact(key=key, value=value))

    for section, content in spec.items():
        if section == "targets":
            targets = _dict(content)
            for field in targets:
                if field == "storeys":
                    add("storeys", _count(targets[field], 1, 3))
                elif field == "gross_floor_area_m2":
                    area = targets[field]
                    if (
                        isinstance(area, int | float)
                        and not isinstance(area, bool)
                        and 20 <= area <= 2000
                    ):
                        add("floor_area_m2", round(float(area), 1))
        elif section == "style":
            style = _dict(content)
            for field in style:
                if field == "architectural_style":
                    add("style", _word(style[field]))
                elif field == "roof":
                    add("roof", _word(_dict(style[field]).get("type")))
        elif section == "rooms" and isinstance(content, list):
            counts: dict[str, int] = {}
            for room in content:
                kind = _word(_dict(room).get("type"))
                if kind is None:
                    continue
                count = _count(_dict(room).get("count", 1), 1, 12) or 1
                counts[kind] = counts.get(kind, 0) + count
            for kind, count in counts.items():
                add(f"room:{kind}", count)
        elif section == "features":
            features = _dict(content)
            for field in features:
                if field == "garage":
                    add("garage_cars", _count(_dict(features[field]).get("cars"), 1, 3))
                elif field == "balconies" and isinstance(features[field], list):
                    add("balconies", len(features[field]) or None)
                elif field == "terrace" and isinstance(features[field], dict):
                    add("terrace", True)
        elif section == "design":
            add("footprint_shape", _word(_dict(content).get("footprint_shape")))
    return facts


def interim_facts(partial_output: str) -> list[InterimFact]:
    """Facts readable from the answer text received so far (a `SpecificationDraft` in the
    making). Empty until the specification starts."""
    draft = parse_partial_json(partial_output)
    return spec_facts_for_display(_dict(draft.get("specification")))


def merge_facts(known: list[InterimFact], current: list[InterimFact]) -> list[InterimFact]:
    """`current` in a stable order: facts keep the position in which they first appeared (the
    list on screen only grows or updates in place while the answer is written); facts that are
    no longer stated are dropped."""
    by_key = {f.key: f for f in current}
    merged = [by_key.pop(f.key) for f in known if f.key in by_key]
    return merged + list(by_key.values())
