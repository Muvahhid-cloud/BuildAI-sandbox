"""Offline interpretation of modification requests for MockAIProvider (development, tests, CI).

A deterministic, rule-based reader of plain English change requests that answers exactly like a
model's structured output (a ModificationDraft as JSON), using the same model digest. It covers
the phrasings of docs/ai-pipeline.md §11 ("make the kitchen 2 m wider", "move the bathroom wall",
"add another window to the master bedroom", "rename ...", "turn ... into a study", "remove the
wall between ... and ...", ...). Anything it does not understand becomes an `unsupported` entry —
never silently dropped. Room words that fit several rooms stay unresolved (room_hint), exactly
as the prompt asks a model to do.
"""

import re
from typing import Any

# Room-type words -> room types (singular, lowercase).
TYPE_WORDS: dict[str, tuple[str, ...]] = {
    "living room": ("living", "open_kitchen_living"),
    "lounge": ("living", "open_kitchen_living"),
    "living": ("living", "open_kitchen_living"),
    "kitchen": ("kitchen", "open_kitchen_living"),
    "dining room": ("dining",),
    "dining area": ("dining",),
    "dining": ("dining",),
    "master bedroom": ("bedroom",),
    "bedroom": ("bedroom",),
    "guest room": ("bedroom",),
    "bathroom": ("bathroom", "en_suite"),
    "en-suite": ("en_suite",),
    "ensuite": ("en_suite",),
    "toilet": ("wc",),
    "wc": ("wc",),
    "study": ("study",),
    "home office": ("study",),
    "office": ("study",),
    "laundry": ("laundry",),
    "utility room": ("utility",),
    "utility": ("utility",),
    "storage": ("storage",),
    "storeroom": ("storage",),
    "pantry": ("storage",),
    "walk-in closet": ("walk_in_closet",),
    "closet": ("walk_in_closet",),
    "hallway": ("hall", "corridor", "entrance"),
    "hall": ("hall", "entrance"),
    "corridor": ("corridor",),
    "landing": ("corridor",),
    "entrance": ("entrance",),
    "garage": ("garage",),
    "staircase": ("staircase",),
}
# Words for a new room type -> RoomType value.
NEW_TYPE: dict[str, str] = {
    "home office": "study",
    "office": "study",
    "study": "study",
    "bedroom": "bedroom",
    "guest room": "bedroom",
    "guest bedroom": "bedroom",
    "kitchen": "kitchen",
    "living room": "living",
    "dining room": "dining",
    "bathroom": "bathroom",
    "wc": "wc",
    "toilet": "wc",
    "laundry": "laundry",
    "utility room": "utility",
    "storage": "storage",
    "storage room": "storage",
    "pantry": "storage",
    "walk-in closet": "walk_in_closet",
    "closet": "walk_in_closet",
    "hall": "hall",
    "corridor": "corridor",
    "en-suite": "en_suite",
    "plant room": "plant_room",
}
VERBS = (
    "make|move|add|put|insert|remove|delete|rename|call|change|turn|convert|increase|enlarge|"
    "expand|extend|grow|reduce|shrink|widen|narrow|merge|combine|open|knock|take|resize|set"
)
_NUM = r"(\d+(?:[.,]\d+)?)\s*(m|meters?|metres?|cm|centimeters?|centimetres?)\b"
_SIDES = ("north", "east", "south", "west")
_GROW = ("wider", "bigger", "larger", "longer", "increase", "enlarge", "expand", "extend", "grow")
_SHRINK = ("narrower", "smaller", "shorter", "reduce", "shrink", "decrease")


def _meters(text: str) -> list[float]:
    out = []
    for value, unit in re.findall(_NUM, text, flags=re.IGNORECASE):
        v = float(value.replace(",", "."))
        out.append(v / 100 if unit.lower().startswith("c") else v)
    return out


def _clauses(prompt: str) -> list[str]:
    """Split into one clause per requested change (keeps 'between A and B' together)."""
    text = re.sub(r"\s+", " ", prompt).strip()
    protected = re.sub(
        r"\b(between [^,.;]+?) and ", lambda m: m.group(1) + " \x00 ", text, flags=re.IGNORECASE
    )
    protected = re.sub(
        r"\b((?:merge|combine) [^,.;]+?) (and|with) ",
        lambda m: m.group(1) + " \x01 ",
        protected,
        flags=re.IGNORECASE,
    )
    parts = re.split(
        # A full stop ends a clause; a decimal point ("1.2 m") does not.
        rf"\.(?=\s|$)|[;\n]|,\s*(?:and\s+|then\s+)?|\s+(?:and|then|also)\s+(?=(?:{VERBS})\b)",
        protected,
        flags=re.IGNORECASE,
    )
    return [
        p.replace("\x00", "and").replace("\x01", "and").strip(" ,")
        for p in parts
        if p and p.strip(" ,")
    ]


class _Rooms:
    def __init__(self, digest: dict[str, Any]) -> None:
        self.rooms: list[dict[str, Any]] = list(digest.get("rooms", []))
        self.openings: list[dict[str, Any]] = list(digest.get("openings", []))

    def mentions(self, clause: str) -> list[tuple[int, list[str], str]]:
        """Room mentions in order of appearance: (position, matching refs, words)."""
        low = clause.lower()
        found: list[tuple[int, int, list[str], str]] = []
        # Rooms with the same name (two "Bathroom"s) are one ambiguous mention.
        by_name: dict[str, list[str]] = {}
        for r in self.rooms:
            by_name.setdefault(r["name"].lower(), []).append(r["ref"])
        for phrase, refs in sorted(by_name.items(), key=lambda x: -len(x[0])):
            for m in re.finditer(rf"\b{re.escape(phrase)}\b", low):
                found.append((m.start(), m.end(), refs, phrase))
        for phrase, types in sorted(TYPE_WORDS.items(), key=lambda x: -len(x[0])):
            refs = [r["ref"] for r in self.rooms if r["room_type"] in types]
            if not refs:
                continue
            for m in re.finditer(rf"\b{re.escape(phrase)}\b", low):
                found.append((m.start(), m.end(), refs, phrase))
        # Longest match wins; names before type words at the same span.
        found.sort(key=lambda f: (f[0], -(f[1] - f[0])))
        out: list[tuple[int, list[str], str]] = []
        end = -1
        for start, stop, refs, phrase in found:
            if start < end:
                continue
            out.append((start, refs, phrase))
            end = stop
        return out


def _room_fields(mention: tuple[int, list[str], str] | None, key: str) -> dict[str, Any]:
    if mention is None:
        return {}
    _, refs, phrase = mention
    if len(refs) == 1:
        return {key: refs[0]}
    return {"room_hint": phrase} if key == "room" else {}


def _side(clause: str) -> str | None:
    low = clause.lower()
    for s in _SIDES:
        if re.search(rf"\b{s}(ern)?\b", low):
            return s
    return None


def _direction(low: str) -> str | None:
    if any(re.search(rf"\b{w}\b", low) for w in _SHRINK) or "inward" in low:
        return "decrease"
    if any(re.search(rf"\b{w}\b", low) for w in _GROW) or "outward" in low:
        return "increase"
    return None


def _dimension(low: str) -> str | None:
    if re.search(r"\b(wider|narrower|widen|width)\b", low):
        return "width"
    if re.search(r"\b(longer|shorter|lengthen|length)\b", low):
        return "length"
    return None


def _change(clause: str, rooms: _Rooms) -> dict[str, Any] | None:
    low = clause.lower()
    mentions = rooms.mentions(clause)
    first = mentions[0] if mentions else None
    second = mentions[1] if len(mentions) > 1 else None
    base: dict[str, Any] = {"quote": clause[:300]}

    m = re.search(r"\b(?:rename|call)\b(.+?)\b(?:to|as)\b\s*[\"'«]?(.+?)[\"'»]?\s*$", clause, re.I)
    if m and first is not None:
        return {
            **base,
            "action": "rename_room",
            **_room_fields(first, "room"),
            "new_name": m.group(2).strip(),
        }

    m = re.search(
        r"\b(?:change|turn|convert|make)\b(.+?)\b(?:into|to|a|an)\s+(?:an?\s+)?([a-z -]+)$", low
    )
    if m and first is not None:
        target = m.group(2).strip()
        new_type = NEW_TYPE.get(target)
        if new_type and not any(w in low for w in _GROW + _SHRINK):
            return {
                **base,
                "action": "set_room_type",
                **_room_fields(first, "room"),
                "new_room_type": new_type,
            }

    if re.search(r"\b(remove|delete|knock down|knock out|take out|demolish)\b.*\bwall\b", low) or (
        re.search(r"\b(merge|combine)\b", low) and second is not None
    ):
        merge = bool(re.search(r"\b(merge|combine|one room|single room)\b", low))
        opened = bool(re.search(r"\b(open( it)? up|open plan|keep both)\b", low))
        return {
            **base,
            "action": "remove_wall",
            **_room_fields(first, "room"),
            **_room_fields(second, "other_room"),
            "merge_rooms": True if merge else (False if opened else None),
        }

    kind = (
        "window"
        if re.search(r"\bwindows?\b", low)
        else ("door" if re.search(r"\bdoors?\b", low) else None)
    )
    nums = _meters(clause)
    if kind and re.search(r"\b(add|put|insert|install|new|another|one more)\b", low):
        change: dict[str, Any] = {
            **base,
            "action": "add_window" if kind == "window" else "add_door",
        }
        change.update(_room_fields(first, "room"))
        if kind == "door":
            change.update(_room_fields(second, "other_room"))
        else:
            if side := _side(clause):
                change["side"] = side
            w = re.search(_NUM + r"\s*(?:wide|width)", clause, re.I)
            if w:
                change["width_m"] = _meters(w.group(0))[0]
        return change

    if kind and re.search(r"\b(remove|delete|take out|close)\b", low):
        return {
            **base,
            "action": "remove_opening",
            "opening_kind": kind,
            **_room_fields(first, "room"),
        }

    sized = bool(nums) and re.search(r"\b(wide|tall|high)\b", low) is not None
    if kind and (
        sized or re.search(r"\b(bigger|larger|wider|taller|smaller|resize|enlarge|widen)\b", low)
    ):
        change = {**base, "action": "resize_opening", "opening_kind": kind}
        change.update(_room_fields(first, "room"))
        w = re.search(_NUM + r"\s*(?:wide|width)", clause, re.I)
        h = re.search(_NUM + r"\s*(?:high|tall|height)", clause, re.I)
        if w:
            change["width_m"] = _meters(w.group(0))[0]
        if h:
            change["height_m"] = _meters(h.group(0))[0]
        if not w and not h and len(nums) == 1:
            change["width_m"] = nums[0]
        return change

    if re.search(r"\bmove\b.*\bwall\b", low):
        change = {**base, "action": "move_wall", **_room_fields(first, "room")}
        change.update(_room_fields(second, "other_room"))
        if nums:
            change["amount_m"] = nums[0]
        if d := _direction(low):
            change["direction"] = d
        return change

    if first is not None and (_direction(low) or re.search(r"\b(size|resize)\b", low)):
        change = {**base, "action": "resize_room", **_room_fields(first, "room")}
        if d := _direction(low):
            change["direction"] = d
        if dim := _dimension(low):
            change["dimension"] = dim
        if side := _side(clause):
            change["side"] = side
        if nums:
            change["amount_m"] = nums[0]
        return change
    return None


def _understanding(changes: list[dict[str, Any]], unsupported: list[dict[str, Any]]) -> str:
    if not changes:
        return "No supported change was recognised in the request."
    n = len(changes)
    text = f"{n} change{'s' if n != 1 else ''} requested: " + "; ".join(c["quote"] for c in changes)
    return text[:600]


def interpret_modification_offline(prompt: str, digest: dict[str, Any] | None) -> dict[str, Any]:
    rooms = _Rooms(digest or {})
    changes: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    for clause in _clauses(prompt):
        change = _change(clause, rooms)
        if change is None:
            unsupported.append(
                {
                    "quote": clause[:300],
                    "reason": "Not understood by the offline interpreter. Rephrase it like "
                    "'make the kitchen 2 m wider' or 'add a window to the master bedroom'.",
                }
            )
        else:
            changes.append(change)
    return {
        "understanding": _understanding(changes, unsupported),
        "changes": changes[:12],
        "unsupported": unsupported[:12],
    }
