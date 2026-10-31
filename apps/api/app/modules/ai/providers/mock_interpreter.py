"""Deterministic, rule-based interpreter behind MockAIProvider (development, tests, CI, offline).

It reads the usual ways people describe a house (area, storeys, bedroom/bathroom counts, garage,
balcony, terrace, style, windows, roof, facade, budget, city — and since K3 facade colors,
large/panoramic windows on named facades, and living spaces facing the garden, through the
same facade synonym table and color palette as the prompt; since spec 1.2.0 per-room areas,
rooms next to / apart from each other, design priorities, plot width and whether each request
is a MUST, with the words it came from) with regular expressions and builds the same
`SpecificationDraft` a language model would return. Every value it does not
read from the request is recorded as an assumption; requests it cannot express are reported,
never silently dropped. It is not a language model and never pretends to be one in production
(the settings refuse AI_PROVIDER=mock when ENVIRONMENT=production).
"""

import math
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.ai.schemas.generation import GenerationOptions
from app.modules.building.appearance import COLOR_SYNONYMS, PALETTE, color_name
from app.modules.building.facades import FACADE_SYNONYMS
from app.modules.building.footprint import capability, find_shape, shape_priority
from app.modules.building.specification import FacadeSide, FootprintShape

NUMBER_WORDS = {
    "one": 1,
    "single": 1,
    "two": 2,
    "double": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
NUM = r"(\d{1,2}|one|single|two|double|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
STYLES = (
    "minimalist",
    "scandinavian",
    "industrial",
    "mediterranean",
    "contemporary",
    "traditional",
    "classic",
    "luxury",
    "modern",
)
INTERIOR_STYLES = (
    "minimalist",
    "modern",
    "classic",
    "scandinavian",
    "industrial",
    "luxury",
    "cozy",
)
FLAT_ROOF_STYLES = ("modern", "minimalist", "contemporary", "industrial")
# Below this floor area per storey the mock plans one open kitchen-living space (a program
# choice of the offline interpreter, like a model's judgement — not a building rule).
COMPACT_STOREY_AREA_M2 = 75.0
REGIONS = {
    "almaty": "KZ-ALA",
    "astana": "KZ-AST",
    "nur-sultan": "KZ-AST",
    "shymkent": "KZ-SHY",
    "kazakhstan": "KZ",
}
CURRENCIES = {
    "kzt": "KZT",
    "tenge": "KZT",
    "₸": "KZT",
    "usd": "USD",
    "dollars": "USD",
    "$": "USD",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "€": "EUR",
}
UNSUPPORTED = {
    r"swimming pool|\bpool\b": "Swimming pool",
    r"sauna": "Sauna",
    r"basement|cellar": "Basement",
    r"\blift\b|elevator": "Lift / elevator",
    r"home (?:cinema|theat(?:er|re))": "Home cinema",
    r"\bgym\b": "Home gym",
    r"fireplace": "Fireplace",
    r"solar panels?": "Solar panels",
    r"roof(?:top)? garden|green roof": "Roof garden",
}
INJECTION = re.compile(
    r"ignore (?:all |any |your |the |previous |prior )*(?:instructions|rules)|system prompt|"
    r"\bpython\b|\bsql\b|javascript|executable|source code|\bscript\b|api key",
    re.IGNORECASE,
)


# Room nouns -> spec room keys (longest first). Plural "bedrooms" is a count, not a size.
ROOM_NOUNS: tuple[tuple[str, str], ...] = (
    (r"(?:master|main|primary) bedroom", "master_bedroom"),
    (r"living room|living area|living space|sitting room|lounge", "living"),
    (r"dining room|dining area|dining", "dining"),
    (r"kitchen", "kitchen"),
    (r"home office|study|office", "study"),
    (r"bathroom", "bathroom"),
    (r"bedroom", "bedroom"),
)
_ROOM_RE = "|".join(f"(?:{p})" for p, _ in ROOM_NOUNS)
UNIT = r"(?:m2|sq\.? ?m\b|sqm|square met(?:er|re)s?|met(?:er|re)s? squared)"
AREA_NUMBER = r"(\d{1,3}(?:[ ,]\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)"
MUST_WORDS = re.compile(
    r"\b(?:must|has to|have to|needs? to|required|requirement|essential|mandatory|exactly|"
    r"at least|no less than|minimum)\b"
)
HEDGE_WORDS = re.compile(
    r"\b(?:about|around|approx\w*|roughly|circa|ideally|preferably|if possible)\b|~"
)
AT_LEAST = re.compile(r"\b(?:at least|no less than|minimum(?: of)?|min\.?)\s*$")
NEXT_TO = r"next to|adjacent to|beside|alongside|right by|close to|near"
PRIORITY_WORDS: tuple[tuple[str, str], ...] = (
    (r"daylight|natural light|sunlight|light[- ]filled|\bbright\b", "daylight"),
    (r"privacy|\bprivate\b", "privacy"),
    (
        r"garden[- ]facing|facing the (?:garden|backyard)|towards? the garden|garden views?|"
        r"onto the garden|to the garden",
        "garden_connection",
    ),
    (
        r"\bcompact\b|space[- ]efficient|efficient (?:layout|plan|circulation)|economical",
        "compactness",
    ),
    (r"open[- ]plan", "open_plan"),
)


def _number(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token]


def _room_key(noun: str) -> str:
    return next(key for pattern, key in ROOM_NOUNS if re.fullmatch(pattern, noun))


def _priority(sentence: str) -> str:
    return "must" if MUST_WORDS.search(sentence) and not HEDGE_WORDS.search(sentence) else "should"


@dataclass(frozen=True)
class _RoomArea:
    value: float
    priority: str  # must | should
    at_least: bool
    quote: str


@dataclass
class _Draft:
    text: str
    options: GenerationOptions | None
    signals: int = 0
    assumptions: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def assume(self, path: str, value: Any, reason: str) -> None:
        self.assumptions.append({"path": path, "value": value, "reason": reason})

    def find(self, pattern: str) -> re.Match[str] | None:
        return re.search(pattern, self.text)

    def sentence_at(self, pos: int) -> str:
        start = max(self.text.rfind(c, 0, pos) for c in ".;\n") + 1
        ends = [i for i in (self.text.find(c, pos) for c in ".;\n") if i != -1]
        return self.text[start : min(ends) if ends else len(self.text)].strip()[:200]


def _normalize(prompt: str) -> str:
    text = prompt.lower().replace("²", "2").replace("\u2013", "-").replace("\u2014", "-")
    return re.sub(r"\s+", " ", text).strip()


def _room_areas(d: _Draft) -> tuple[dict[str, _RoomArea], list[tuple[int, int]]]:
    """Sizes given for individual rooms ("a 40 m² living room", "kitchen of about 15 m2") and
    the text spans they use (those numbers are not the house's floor area)."""
    found: dict[str, _RoomArea] = {}
    spans: list[tuple[int, int]] = []
    before = re.compile(rf"{AREA_NUMBER}\s*{UNIT}\s+(?:[a-z-]+\s+)?({_ROOM_RE})\b(?!s)")
    after = re.compile(
        rf"({_ROOM_RE})\b(?!s)\s*(?:of|at|:|=|\(|-|measuring|sized)?\s*"
        rf"((?:about|around|approximately|roughly|at least|no less than|minimum(?: of)?|"
        rf"exactly|~)\s*)?{AREA_NUMBER}\s*{UNIT}"
    )
    for m in before.finditer(d.text):
        value, noun = float(m.group(1).replace(",", "").replace(" ", "")), m.group(2)
        prefix = d.text[max(0, m.start() - 20) : m.start()]
        found.setdefault(_room_key(noun), _area_of(d, value, prefix, m.start()))
        spans.append(m.span(1))
    for m in after.finditer(d.text):
        noun, qualifier = m.group(1), m.group(2) or ""
        value = float(m.group(3).replace(",", "").replace(" ", ""))
        if value >= 100:  # "... a living room 150 m2" is more likely the house
            continue
        found.setdefault(_room_key(noun), _area_of(d, value, qualifier, m.start()))
        spans.append(m.span(3))
    return found, spans


def _area_of(d: _Draft, value: float, qualifier: str, pos: int) -> _RoomArea:
    sentence = d.sentence_at(pos)
    hedged = bool(HEDGE_WORDS.search(qualifier))
    at_least = bool(AT_LEAST.search(qualifier.strip() + " ")) or "at least" in qualifier
    # An exact number for a room is a requirement unless it is hedged ("about 40 m²"); only
    # the words right before the number count (another room in the sentence may be hedged).
    return _RoomArea(value, "should" if hedged else "must", at_least, sentence)


def _area(d: _Draft, room_spans: list[tuple[int, int]]) -> float | None:
    """The house's floor area: the first area in the text that is not a room's size."""
    for m in re.finditer(rf"{AREA_NUMBER}\s*{UNIT}", d.text):
        if any(a <= m.start(1) < b for a, b in room_spans):
            continue
        d.signals += 1
        return float(m.group(1).replace(",", "").replace(" ", ""))
    return None


def _plot(d: _Draft) -> dict[str, float]:
    """Plot width/depth: "plot 8 x 30 m", "a narrow plot 9 m wide", "30 m deep"."""
    site: dict[str, float] = {}
    m = d.find(
        r"(?:plot|lot|site)[^.;]*?(\d+(?:\.\d+)?)\s*(?:m\s*)?(?:x|by|\u00d7)\s*(\d+(?:\.\d+)?)\s*m\b"
    )
    if m:
        site["plot_width_m"], site["plot_depth_m"] = float(m.group(1)), float(m.group(2))
    else:
        w = d.find(r"(\d+(?:\.\d+)?)\s*(?:m|metres|meters)\s+wide\b")
        if w:
            site["plot_width_m"] = float(w.group(1))
        dp = d.find(r"(\d+(?:\.\d+)?)\s*(?:m|metres|meters)\s+deep\b")
        if dp:
            site["plot_depth_m"] = float(dp.group(1))
    if site:
        d.signals += 1
    return site


def _relations(d: _Draft) -> list[tuple[str, str, str, str, str]]:
    """(kind, room key, other key, priority, quote) for "the kitchen next to the dining room"
    (adjacent) and "bedrooms separated from the living spaces" (separate)."""
    out: list[tuple[str, str, str, str, str]] = []
    for sentence in _sentences(d):
        # The room named closest before "next to" (no other room noun in between).
        for m in re.finditer(
            rf"({_ROOM_RE})s?\b(?:(?!{_ROOM_RE})[^.;])*?\b(?:{NEXT_TO})\s+(?:the\s+|a\s+)?"
            rf"({_ROOM_RE})",
            sentence,
        ):
            a, b = _room_key(m.group(1)), _room_key(m.group(2))
            if a != b:
                out.append(("adjacent", a, b, _priority(sentence), sentence[:200]))
        sep = re.search(
            r"(bedrooms?|sleeping|night|private (?:rooms|zone|areas?|spaces?))[^.;]*?"
            r"\b(?:separate[d]?|apart|away|isolated|distance[d]?)\b[^.;]*?"
            r"\b(living|public|day|social|kitchen|dining|entertaining)",
            sentence,
        )
        if sep:
            targets = ["living"]
            if sep.group(2) in ("public", "day", "social", "entertaining") or re.search(
                r"living (?:spaces|areas)|public", sentence
            ):
                targets = ["living", "dining", "kitchen"]
            for target in targets:
                for bedroom in ("master_bedroom", "bedroom"):
                    out.append(("separate", bedroom, target, _priority(sentence), sentence[:200]))
    return out


def _footprint_shape(d: _Draft) -> tuple[str, str] | None:
    """(footprint shape, the words) for a request for a footprint shape, read with the shared
    vocabulary (building/footprint.py SHAPE_WORDS), so any shape the user names is recorded -
    supported or not. The quote is the sentence that states it as mandatory ("...; the L
    shape is required") if there is one, else the first that names it; its priority is
    shape_priority(quote) (explicit = must, softened = should), as for an AI model's answer."""
    found = [(shape, s) for s in _sentences(d) if (shape := find_shape(s)) is not None]
    if not found:
        return None
    shape, quote = next((f for f in found if MUST_WORDS.search(f[1])), found[0])
    return shape.value, quote


def _priorities(d: _Draft) -> list[str]:
    hits = [(m.start(), key) for pattern, key in PRIORITY_WORDS if (m := d.find(pattern))]
    return [key for _, key in sorted(hits)]


def _storeys(d: _Draft) -> int | None:
    m = d.find(rf"\b{NUM}[ -]?(?:stor(?:e)?y|stories|storeys|floors?|levels?)\b") or d.find(
        rf"how many (?:floors|storeys|stories)[^?]*\?\s*{NUM}\b"  # answer to a clarification
    )
    if m:
        d.signals += 1
        return _number(m.group(1))
    if d.find(r"\bbungalow\b|single[ -]level|one[ -]level"):
        d.signals += 1
        return 1
    return None


def _count(d: _Draft, noun: str) -> int | None:
    m = d.find(rf"\b{NUM}[ -]?{noun}")
    if not m:
        return None
    d.signals += 1
    return _number(m.group(1))


def _budget(d: _Draft) -> dict[str, str] | None:
    symbols = "|".join(re.escape(k) for k in CURRENCIES)
    for m in re.finditer(
        rf"(?P<pre>[$€₸])\s?(?P<num>\d[\d ,.]*\d|\d)\s*(?P<mult>million|mln|thousand|k\b)?|"
        rf"(?P<num2>\d[\d ,.]*\d|\d)\s*(?P<mult2>million|mln|thousand|k\b)?\s*(?P<cur>{symbols})",
        d.text,
    ):
        symbol = m.group("pre") or m.group("cur")
        raw = m.group("num") or m.group("num2")
        mult = m.group("mult") or m.group("mult2")
        if not symbol or not raw:
            continue
        try:
            amount = Decimal(raw.replace(" ", "").replace(",", ""))
        except InvalidOperation:
            continue
        if mult in ("million", "mln"):
            amount *= 1_000_000
        elif mult in ("thousand", "k"):
            amount *= 1_000
        if amount <= 0:
            continue
        return {"amount": f"{amount:.2f}", "currency": CURRENCIES[symbol]}
    return None


def _style(d: _Draft) -> tuple[str | None, str | None]:
    interior = None
    m = d.find(rf"\b({'|'.join(INTERIOR_STYLES)})(?:ist)? interior")
    if m:
        interior = m.group(1)
    else:
        m = d.find(rf"interior[^.]*?\b({'|'.join(INTERIOR_STYLES)})\b")
        if m:
            interior = m.group(1)
    architectural = None
    for word in re.findall(r"[a-z]+", d.text):
        candidate = "luxury" if word == "luxurious" else word
        if candidate in STYLES:
            if candidate == interior and d.find(rf"\b{candidate}\w* interior"):
                continue
            architectural = candidate
            break
    if architectural or interior:
        d.signals += 1
    return architectural, interior


_FACADE_WORDS = sorted(FACADE_SYNONYMS, key=lambda w: (-len(w), w))  # longest first
_FACADE_RE = re.compile(rf"\b({'|'.join(re.escape(w) for w in _FACADE_WORDS)})\b")
_COLOR_WORDS = sorted(
    {n.replace("_", " ") for n in PALETTE} | set(COLOR_SYNONYMS), key=lambda w: (-len(w), w)
)
_COLOR_RE = "|".join(re.escape(w) for w in _COLOR_WORDS)
_NEGATION = re.compile(r"\b(?:not|no|never|avoid|without|except)\b")


def _sentences(d: _Draft) -> list[str]:
    return [s.strip() for s in re.split(r"[.;\n]", d.text) if s.strip()]


def _facade_color(d: _Draft) -> str | None:
    """ "Make the exterior walls yellow", "a yellow facade" -> palette name."""
    m = d.find(
        rf"(?:exterior|external|outside|outer|facade)[^.]*?\b(?:walls?|facade|render)?[^.]*?"
        rf"\b({_COLOR_RE})\b"
    ) or d.find(
        rf"\b({_COLOR_RE})\s+(?:exterior |external |outside )?"
        r"(?:render |rendered |brick |timber |wooden |concrete |stucco |plaster |painted )?"
        r"(?:walls|facade|house|exterior)"
    )
    if not m:
        return None
    return color_name(m.group(1))


def _window_intent(d: _Draft) -> dict[str, Any] | None:
    """Large/panoramic windows on named facades (preferred) and excluded facades."""
    emphasis: str | None = None
    preferred: list[str] = []
    excluded: list[str] = []
    for sentence in _sentences(d):
        if "window" not in sentence:
            continue
        size = (
            "panoramic"
            if re.search(r"panoramic|floor[ -]to[ -]ceiling", sentence)
            else "large"
            if re.search(r"\b(?:large|big)\b", sentence)
            else None
        )
        if size is None:
            continue
        for m in _FACADE_RE.finditer(sentence):
            side = FACADE_SYNONYMS[m.group(1)].value
            negated = bool(_NEGATION.search(sentence[: m.start()]))
            target = excluded if negated else preferred
            if side not in preferred + excluded:
                target.append(side)
                emphasis = emphasis or size
    if not preferred or emphasis is None:
        return None
    return {"emphasis": emphasis, "preferred_facades": preferred, "excluded_facades": excluded}


def _rooms_facing_rear(d: _Draft) -> list[tuple[str, str]]:
    """(room key, sentence) for rooms that should face the garden/backyard ("the living room
    should face the backyard")."""
    keys: list[tuple[str, str]] = []
    for sentence in _sentences(d):
        if not re.search(r"\b(?:face|faces|facing|overlook\w*|toward\w*|onto)\b", sentence):
            continue
        sides = {FACADE_SYNONYMS[m.group(1)] for m in _FACADE_RE.finditer(sentence)}
        if FacadeSide.REAR not in sides or "window" in sentence:
            continue
        for key, pattern in (("living", r"\bliving|lounge"), ("dining", r"\bdining")):
            if re.search(pattern, sentence) and key not in [k for k, _ in keys]:
                keys.append((key, sentence))
    return keys


def interpret_offline(prompt: str, options: GenerationOptions | None = None) -> dict[str, Any]:
    """Return a SpecificationDraft as plain JSON data (the shape a model would return)."""
    d = _Draft(text=_normalize(prompt), options=options)
    injection = bool(INJECTION.search(d.text))

    room_areas, room_spans = _room_areas(d)
    if room_areas:
        d.signals += 1
    area = _area(d, room_spans)
    storeys = _storeys(d)
    bedrooms = _count(d, r"bed(?:room)?s?\b")
    bathrooms = _count(d, r"bath(?:room)?s?\b")
    if d.find(r"\b(?:family|villa|bungalow|townhouse|cottage)\b"):
        d.signals += 1
    if _footprint_shape(d) is not None:  # "an L-shaped house": enough to start from defaults
        d.signals += 1
    architectural, interior = _style(d)
    budget = _budget(d)
    if budget:
        d.signals += 1

    for pattern, label in UNSUPPORTED.items():
        if d.find(pattern):
            d.unsupported.append(f"{label} — not supported by the layout engine yet")
    if injection:
        d.unsupported.append("Non-building instructions were ignored")

    # Form fields are explicit requirements and win over the text (conflicts are reported).
    if options is not None:
        if options.storeys is not None:
            if storeys is not None and storeys != options.storeys:
                d.conflicts.append(
                    f"The description says {storeys} storeys but the form says "
                    f"{options.storeys}; the form value was used."
                )
            storeys = options.storeys
            d.signals += 1
        if options.gross_floor_area_m2 is not None:
            if area is not None and area != options.gross_floor_area_m2:
                d.conflicts.append(
                    f"The description says {area:g} m² but the form says "
                    f"{options.gross_floor_area_m2:g} m²; the form value was used."
                )
            area = options.gross_floor_area_m2
            d.signals += 1
        if options.architectural_style is not None:
            architectural = options.architectural_style.value
            d.signals += 1
        if options.budget is not None:
            budget = {
                "amount": f"{options.budget.amount:.2f}",
                "currency": options.budget.currency,
            }

    if d.signals == 0:
        return {
            "outcome": "clarification",
            "understanding": "The request does not describe the house yet"
            + (" (non-building instructions were ignored)." if injection else "."),
            "clarification_questions": [
                "How many floors should the house have (1 to 3)?",
                "About how many bedrooms and bathrooms do you need?",
                "Do you have an approximate total floor area (m²) or budget?",
            ],
            "unsupported_requests": d.unsupported,
        }
    if storeys is not None and storeys > 3:
        return {
            "outcome": "clarification",
            "understanding": f"A {storeys}-storey house was requested.",
            "clarification_questions": [
                f"BuildAI 3D currently designs houses of 1 to 3 storeys. Would a 3-storey "
                f"design work instead of {storeys}?"
            ],
            "conflicts": [f"{storeys} storeys exceeds the supported maximum of 3."],
            "unsupported_requests": d.unsupported,
        }
    if area is not None and not 20 <= area <= 2000:
        return {
            "outcome": "clarification",
            "understanding": f"A house of {area:g} m² was requested.",
            "clarification_questions": [
                "BuildAI 3D designs houses between 20 and 2000 m². What floor area do you need?"
            ],
            "conflicts": [f"{area:g} m² is outside the supported range of 20 to 2000 m²."],
            "unsupported_requests": d.unsupported,
        }
    return _specification(
        d, area, storeys, bedrooms, bathrooms, architectural, interior, budget, room_areas
    )


def _specification(
    d: _Draft,
    area: float | None,
    storeys: int | None,
    bedrooms: int | None,
    bathrooms: int | None,
    architectural: str | None,
    interior: str | None,
    budget: dict[str, str] | None,
    room_areas: dict[str, _RoomArea],
) -> dict[str, Any]:
    villa = bool(d.find(r"\bvilla\b"))
    small = bool(d.find(r"\b(?:small|compact|tiny)\b"))
    family = d.find(rf"family of {NUM}")
    kind = (
        "villa"
        if villa
        else "bungalow"
        if d.find(r"\bbungalow\b")
        else "family house"
        if d.find(r"\bfamily\b")
        else "house"
    )

    shape = _footprint_shape(d)
    cap = capability(FootprintShape(shape[0])) if shape is not None else None
    if storeys is None and cap is not None and cap.generated and cap.max_storeys == 1:
        storeys = 1
        d.assume(
            "/targets/storeys",
            1,
            f"{cap.label} footprints are generated for single-storey houses.",
        )
    if storeys is None:
        storeys = 1 if small or (area is not None and area < 2 * COMPACT_STOREY_AREA_M2) else 2
        d.assume("/targets/storeys", storeys, "Not specified; chosen from the size of the house.")
    if bedrooms is None:
        if family:
            bedrooms = max(2, _number(family.group(1)) - 1)
            d.assume("/rooms", bedrooms, f"{bedrooms} bedrooms for a family of {family.group(1)}.")
        else:
            bedrooms = (
                4 if villa else 2 if small else max(1, min(6, round(area / 70))) if area else 3
            )
            d.assume("/rooms", bedrooms, f"Number of bedrooms not specified; {bedrooms} assumed.")
    if bathrooms is None:
        bathrooms = max(1, math.ceil(bedrooms / 2))
        d.assume("/rooms", bathrooms, f"Number of bathrooms not specified; {bathrooms} assumed.")
    architectural = architectural or "modern"
    if not d.find(rf"\b{architectural}"):
        d.assume("/style/architectural_style", architectural, "No style given; modern assumed.")

    upper = 1 if storeys >= 2 else None
    # Small storeys (as in reference spec 09) cannot fit separate living, kitchen and dining
    # rooms next to a stair core: combine them into one open-plan space.
    separate_rooms = bool(
        {"kitchen", "dining"} & set(room_areas) or d.find(r"dining room|separate kitchen")
    )
    compact = (small or (area is not None and area / storeys < COMPACT_STOREY_AREA_M2)) and (
        not separate_rooms
    )
    living: dict[str, Any] = {"key": "living", "type": "living", "name": "Living room"}
    if compact:
        living = {"key": "living", "type": "open_kitchen_living", "name": "Kitchen & living"}
        d.assume(
            "/rooms/0/type",
            "open_kitchen_living",
            "Compact plan: kitchen, dining and living share one open space.",
        )
    if storeys >= 2:
        living["level"] = 0
    if "living" not in room_areas and d.find(
        r"\b(?:large|big|spacious|generous) (?:living|lounge)"
    ):
        living["target_area_m2"] = 40.0
        d.assume("/rooms/0/target_area_m2", 40.0, "“Large living room” read as about 40 m².")
    rooms: list[dict[str, Any]] = [living]
    if not compact:
        kitchen: dict[str, Any] = {"key": "kitchen", "type": "kitchen", "name": "Kitchen"}
        if storeys >= 2:
            kitchen["level"] = 0
        if d.find(
            r"open[ -](?:plan|kitchen)|kitchen[^.,]*(?:connected|open) to|"
            r"(?:living|lounge)[^.,]*(?:connected|open) to[^.,]*kitchen"
        ):
            living["open_to"] = ["kitchen"]
        rooms.append(kitchen)
    if not compact and not d.find(r"\bno dining"):
        dining: dict[str, Any] = {"key": "dining", "type": "dining", "name": "Dining area"}
        if storeys >= 2:
            dining["level"] = 0
        if not d.find(r"\bdining"):
            d.assume("/rooms", "dining", "A dining area is part of a standard family program.")
        rooms.append(dining)
        # "open-plan living, dining and kitchen": one sequence living - dining - kitchen.
        if any(
            re.search(r"open[ -]plan", s) and "dining" in s and "kitchen" in s
            for s in _sentences(d)
        ):
            living["open_to"] = ["dining"]
            dining["open_to"] = ["kitchen"]
    if d.find(r"\b(?:study|office|workspace|work from home)\b"):
        rooms.append({"key": "study", "type": "study", "name": "Study"})
    if d.find(r"guest (?:wc|toilet)|powder room"):
        rooms.append({"key": "wc", "type": "wc", "name": "Guest WC", "level": 0})
    if d.find(r"\blaundry|utility room"):
        rooms.append({"key": "laundry", "type": "laundry", "name": "Laundry"})
    if d.find(r"\bstorage|pantry"):
        rooms.append({"key": "storage", "type": "storage", "name": "Storage"})

    en_suite = bathrooms >= 2 and bedrooms >= 2
    master: dict[str, Any] = {"key": "master_bedroom", "type": "bedroom", "name": "Master bedroom"}
    if upper is not None:
        master["level"] = upper
    if en_suite:
        master["features"] = ["en_suite"]
        d.assume(
            "/rooms",
            "en_suite",
            f"One of the {bathrooms} bathrooms is an en-suite to the master bedroom.",
        )
    rooms.append(master)
    if bedrooms > 1:
        bedroom: dict[str, Any] = {"key": "bedroom", "type": "bedroom", "count": bedrooms - 1}
        if upper is not None:
            bedroom["level"] = upper
        rooms.append(bedroom)
    remaining = bathrooms - (1 if en_suite else 0)
    if remaining > 0:
        rooms.append({"key": "bathroom", "type": "bathroom", "count": remaining})
    if upper is not None:
        d.assume("/rooms", upper, "Living spaces on the ground floor, bedrooms upstairs.")

    features: dict[str, Any] = {}
    garage = d.find(rf"{NUM}[ -]car garage|garage for {NUM} cars?|double garage|garage")
    if garage:
        cars_token = garage.group(1) or garage.group(2)
        cars = 2 if "double" in garage.group(0) else _number(cars_token) if cars_token else 1
        if not cars_token and "double" not in garage.group(0):
            d.assume("/features/garage/cars", 1, "Garage size not specified; one car assumed.")
        if cars > 3:
            d.conflicts.append(f"A {cars}-car garage was requested; the maximum is 3 cars.")
            cars = 3
        features["garage"] = {"cars": cars}
    if d.find(r"balcon"):
        if storeys < 2:
            d.conflicts.append("A balcony needs an upper floor; a single-storey house has none.")
        else:
            level = storeys - 1
            m = d.find(r"balcon\w* on the (second|third|upper|top|first) floor")
            if m:
                level = {"first": 1, "second": 1, "third": 2}.get(m.group(1), storeys - 1)
            level = min(level, storeys - 1)
            count_m = d.find(rf"{NUM} balconies")
            count = min(_number(count_m.group(1)), 4) if count_m else 1
            features["balconies"] = [
                {"level": level, "attached_to": "master_bedroom"} if i == 0 else {"level": level}
                for i in range(count)
            ]
            if upper is None or level != upper:
                features["balconies"][0].pop("attached_to")
    if d.find(r"terrace|patio|\bdeck\b"):
        terrace: dict[str, Any] = {"attached_to": "living"}
        if d.find(r"(?:large|big|spacious|generous) (?:terrace|patio|deck)"):
            terrace["depth_m"] = 4.0
        features["terrace"] = terrace

    style: dict[str, Any] = {"architectural_style": architectural}
    if interior:
        style["interior_style"] = interior
    if d.find(r"flat roof"):
        style["roof"] = {"type": "flat"}
    elif d.find(r"gable|pitched roof"):
        style["roof"] = {"type": "gable"}
    elif d.find(r"hip(?:ped)? roof"):
        style["roof"] = {"type": "hip"}
    else:
        roof = (
            "flat"
            if architectural in FLAT_ROOF_STYLES
            else "gable"
            if architectural == "scandinavian"
            else "hip"
        )
        style["roof"] = {"type": roof}
        d.assume("/style/roof/type", roof, f"Roof not specified; typical for {architectural}.")
    traces: list[dict[str, Any]] = []
    index = {room["key"]: i for i, room in enumerate(rooms)}
    for key, size in room_areas.items():
        if key not in index:
            if key in ("kitchen", "dining") and compact:
                d.conflicts.append(
                    f"A {key} size was given, but the compact plan combines kitchen, dining and "
                    "living into one space; the size was not used."
                )
            else:
                d.unsupported.append(
                    f"A size was given for a {key.replace('_', ' ')} that is "
                    "not part of the programme; it was not used."
                )
            continue
        room = rooms[index[key]]
        room["target_area_m2"] = size.value
        if size.at_least:
            room["min_area_m2"] = size.value
            room["max_area_m2"] = min(200.0, round(size.value * 1.25, 1))
            d.assume(
                f"/rooms/{index[key]}/max_area_m2",
                room["max_area_m2"],
                f"“At least {size.value:g} m²”: up to 25% more is accepted.",
            )
        traces.append(
            {
                "path": f"/rooms/{index[key]}/target_area_m2",
                "priority": size.priority,
                "origin": "user_text",
                "quote": size.quote,
            }
        )
    for kind, key, other, priority, quote in _relations(d):
        if key not in index or other not in index:
            continue
        field_name = "adjacent_to" if kind == "adjacent" else "separate_from"
        room = rooms[index[key]]
        values = room.setdefault(field_name, [])
        if other in values or (kind == "adjacent" and other in room.get("open_to", [])):
            continue
        values.append(other)
        traces.append(
            {
                "path": f"/rooms/{index[key]}/{field_name}/{len(values) - 1}",
                "priority": priority,
                "origin": "user_text",
                "quote": quote,
            }
        )
    windows = _window_intent(d)
    if windows is not None:
        # Emphasis goes to the named facades only; the rest of the house keeps standard windows.
        style["window_style"] = "standard"
    elif d.find(r"panoramic|floor[ -]to[ -]ceiling|glass walls?"):
        style["window_style"] = "panoramic"
    elif d.find(r"(?:large|big) windows"):
        style["window_style"] = "large"
    design: dict[str, Any] = {}
    if shape is not None:
        design["footprint_shape"] = shape[0]
        traces.append(
            {
                "path": "/design/footprint_shape",
                "priority": shape_priority(shape[1]).value,
                "origin": "user_text",
                "quote": shape[1][:200],
            }
        )
    priorities = _priorities(d)
    if priorities:
        design["priorities"] = priorities
    color = _facade_color(d)
    if color is not None:
        design["facade_color"] = color
    if windows is not None:
        design["windows"] = windows
        window_quote = next((s for s in _sentences(d) if "window" in s), None)
        traces.append(
            {
                "path": "/design/windows",
                "priority": _priority(window_quote or ""),
                "origin": "user_text",
                "quote": window_quote[:200] if window_quote else None,
            }
        )
    for key, quote in _rooms_facing_rear(d):
        for i, room in enumerate(rooms):
            if room["key"] == key:
                room["faces"] = "rear"
                traces.append(
                    {
                        "path": f"/rooms/{i}/faces",
                        "priority": _priority(quote),
                        "origin": "user_text",
                        "quote": quote[:200],
                    }
                )
    if d.find(r"\bbrick"):
        style["facade_material"] = "brick"
    elif d.find(r"concrete"):
        style["facade_material"] = "concrete"
    elif d.find(r"timber|wooden|\bwood\b"):
        style["facade_material"] = "timber"
    else:
        style["facade_material"] = "render"
        d.assume("/style/facade_material", "render", "Facade material not specified.")
    if architectural == "luxury" or d.find(r"luxur|premium|high[ -]end"):
        style["interior_finish_level"] = "premium"

    targets: dict[str, Any] = {"storeys": storeys}
    if area is not None:
        targets["gross_floor_area_m2"] = area
    else:
        d.assume(
            "/targets/gross_floor_area_m2",
            None,
            "No floor area given; the layout engine derives it from the rooms.",
        )
    d.assume(
        "/targets/floor_to_floor_height_m", 3.0, "Not specified; residential default of 3.0 m."
    )

    spec: dict[str, Any] = {
        "name": f"{architectural.capitalize()} {kind}",
        "description": _summary(storeys, area, architectural, kind, bedrooms, bathrooms, features),
        "targets": targets,
        "style": style,
        "rooms": rooms,
        "features": features,
        "assumptions": d.assumptions[:50],
    }
    if design:
        spec["design"] = design
    if budget:
        spec["budget"] = budget
    region = next((code for city, code in REGIONS.items() if city in d.text), None)
    if d.options is not None and d.options.region_code:
        region = d.options.region_code
    site: dict[str, Any] = _plot(d)
    if region:
        site["region_code"] = region
    if site:
        spec["site"] = site
    if traces:
        spec["requirements"] = traces[:60]
    if d.find(r"narrow (?:urban )?(?:plot|lot|site)") and "plot_width_m" not in site:
        spec.setdefault("open_questions", []).append("How wide is the plot (in metres)?")
    if not d.find(r"garage") and storeys >= 1:
        spec.setdefault("open_questions", []).append("Do you need a garage or a carport?")
    return {
        "outcome": "specification",
        "understanding": spec["description"],
        "specification": spec,
        "conflicts": d.conflicts,
        "unsupported_requests": d.unsupported,
    }


def _summary(
    storeys: int,
    area: float | None,
    style: str,
    kind: str,
    bedrooms: int,
    bathrooms: int,
    features: dict[str, Any],
) -> str:
    parts = [f"A {storeys}-storey {style} {kind}"]
    if area is not None:
        parts.append(f"of about {area:g} m²")
    extras = [f"{bedrooms} bedrooms", f"{bathrooms} bathrooms"]
    if "garage" in features:
        extras.append(f"a {features['garage']['cars']}-car garage")
    if features.get("balconies"):
        extras.append("a balcony")
    if "terrace" in features:
        extras.append("a terrace")
    return " ".join(parts) + " with " + ", ".join(extras[:-1]) + " and " + extras[-1] + "."
