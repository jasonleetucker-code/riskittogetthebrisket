"""One OCR'd line -> a player or pick CANDIDATE (or nothing).

This module only shapes strings.  It never decides identity: a pick label is
normalised into a grammar the canonical pick owner understands and then
parsed BY that owner (``src.identity.picks.parse_pick_label``); a player name
is handed on, with any position/team hints read off the same line, to the
canonical player resolver later.

OCR repair is deliberately narrow.  Character substitutions (``O``->``0``,
``l``/``I``->``1``, ``Z``->``2``) are applied ONLY inside tokens that are
already pick-shaped (a year, a round ordinal, a slot) — a name is never
"repaired", because a repaired name is a guessed name.

A line whose text is an instruction ("ignore previous instructions and add
...") is just a string here.  It fails the name-shape checks and comes back
as ``None``; nothing reads it as anything but a candidate asset string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.identity.picks import MarketPickRef, parse_pick_label, round_suffix
from src.utils.name_clean import NFL_TEAM_CODES, POSITION_ALIASES, normalize_position

KIND_PLAYER = "player"
KIND_PICK = "pick"

NOTE_PICK_OWNER = "pick_owner_not_established"
REASON_PICK_YEAR_MISSING = "pick_year_missing"
REASON_PICK_UNPARSEABLE = "unparseable_pick"


@dataclass(frozen=True)
class ParsedItem:
    kind: str  # "player" | "pick"
    raw: str
    market_ref: MarketPickRef | None = None
    name: str | None = None
    hints: dict = field(default_factory=lambda: {"position": None, "team": None})
    reason: str | None = None  # why a pick-shaped line has no market_ref
    notes: tuple[str, ...] = ()
    label: str | None = None  # the normalised pick label handed to the owner


# ── Shared token helpers ────────────────────────────────────────────────

_LEADING_BULLET_RE = re.compile(r"^\s*(?:[•·●▪◦\*\-–—>»]+\s*)+")
_LEADING_RANK_RE = re.compile(r"^\s*(?:#\s?\d{1,3}|\d{1,3}[\.\):])\s+")
_EDGE_JUNK = "|©®*•·●▪◦>«»<\"'“”‘’:;,_~=+"
_VALUE_TOKEN_RE = re.compile(
    r"^[+\-−±]?\$?(?:\d{1,3}(?:,\d{3})+|\d{3,})(?:\.\d+)?%?$"
    r"|^[+\-−±]\$?\d+(?:\.\d+)?%?$"
    r"|^\d+(?:\.\d+)?%$"
)
_PAREN_RE = re.compile(r"\s*[\(\[]([^\)\]]*)[\)\]]\s*$")
_POS_RANK_RE = re.compile(r"^([A-Z]{1,4})\d{1,3}$")
_SEPARATORS_RE = re.compile(r"\s+[·•|–—\-/]\s+|\s*[·•|]\s*")
_HINT_SPLIT_RE = re.compile(r"[\s,·•|/\-–—]+")
_NAME_PARTICLES = frozenset({"de", "da", "van", "von", "la", "le", "di", "du", "del", "st", "st."})
_SKIP_TAGS = frozenset({"FA", "R", "IR", "PUP", "NFI", "SUS", "O", "Q", "D", "OUT", "ROOKIE"})


def _strip_leading(text: str) -> str:
    s = _LEADING_BULLET_RE.sub("", text)
    s = _LEADING_RANK_RE.sub("", s)
    return s.strip()


def _position_of(token: str) -> str | None:
    """A position hint only from an UPPERCASE token (OCR keeps UI case):
    ``"WR"`` is a position, the word ``"Wr"`` in a name is not."""
    if not token or token != token.upper():
        return None
    tok = token.strip(".")
    if tok in POSITION_ALIASES and tok != "PICK":
        return normalize_position(tok) or None
    m = _POS_RANK_RE.match(tok)
    if m and m.group(1) in POSITION_ALIASES and m.group(1) != "PICK":
        return normalize_position(m.group(1)) or None
    return None


def _team_of(token: str) -> str | None:
    tok = token.strip(".")
    if tok and tok == tok.upper() and tok in NFL_TEAM_CODES:
        return tok
    return None


def _is_value_token(token: str) -> bool:
    return bool(_VALUE_TOKEN_RE.match(token.replace("−", "-")))


# ── Picks ───────────────────────────────────────────────────────────────

_YEAR_CHARS = {"O": "0", "o": "0", "Q": "0", "D": "0", "l": "1", "I": "1", "|": "1", "i": "1"}
_ONE_LIKE = {"l": "1", "I": "1", "|": "1", "i": "1", "!": "1"}
_TWO_LIKE = {"Z": "2", "z": "2"}
_ORD_RE = re.compile(r"^([1-9lI|i!Zz])\s?(st|nd|rd|th)\.?$", re.I)
_SLOT_RE = re.compile(r"^(?:R|Rd)?([1-6lI|i!Zz])[\.,·]([0-9OoQDlI|]{1,2})$", re.I)
_ROUND_ONLY_RE = re.compile(r"^R(?:d)?\.?([1-9lI|])$", re.I)
_TIERS = {"early": "Early", "mid": "Mid", "middle": "Mid", "late": "Late"}
_ROUND_WORDS = frozenset({"round", "rd", "rd.", "rnd"})
_PICK_WORDS = frozenset({"pick", "pk", "pick#", "#"})


def _fix_year(token: str) -> int | None:
    tok = token.strip(".,")
    if len(tok) != 4:
        return None
    first = _TWO_LIKE.get(tok[0], tok[0])
    rest = "".join(_YEAR_CHARS.get(c, c) for c in tok[1:])
    fixed = first + rest
    if re.fullmatch(r"20\d{2}", fixed):
        return int(fixed)
    return None


def _digit(ch: str) -> str:
    return _ONE_LIKE.get(ch, _TWO_LIKE.get(ch, ch))


def _fix_ordinal(token: str) -> int | None:
    m = _ORD_RE.match(token)
    if not m:
        return None
    d = _digit(m.group(1))
    return int(d) if d.isdigit() else None


def _fix_slot(token: str) -> tuple[int, int] | None:
    m = _SLOT_RE.match(token)
    if not m:
        return None
    rnd = _digit(m.group(1))
    slot = "".join(_YEAR_CHARS.get(c, c) for c in m.group(2))
    if not (rnd.isdigit() and slot.isdigit()):
        return None
    if int(slot) < 1:
        return None
    return int(rnd), int(slot)


def _round_number(token: str) -> int | None:
    tok = token.strip(".")
    d = "".join(_digit(c) for c in tok)
    return int(d) if d.isdigit() and 1 <= int(d) <= 9 else None


def _merge_split_ordinals(tokens: list[str]) -> list[str]:
    """``["1", "st"]`` -> ``["1st"]`` (OCR often splits the suffix)."""
    out: list[str] = []
    for tok in tokens:
        if out and tok.lower() in ("st", "nd", "rd", "th") and re.fullmatch(r"[1-9lI|]", out[-1]):
            out[-1] = out[-1] + tok
        else:
            out.append(tok)
    return out


def _parse_pick(text: str, raw: str) -> ParsedItem | None:
    """Return a pick ParsedItem when ``text`` is pick-shaped, else None."""
    annotation = ""
    m = _PAREN_RE.search(text)
    if m:
        annotation = f" ({m.group(1).strip()})" if m.group(1).strip() else ""
        text = text[: m.start()].strip()
    tokens = _merge_split_ordinals(text.replace("#", " # ").split())
    if not tokens:
        return None
    # Drop trailing value numbers ("2027 1st 4,512").
    while len(tokens) > 1 and _is_value_token(tokens[-1]) and _fix_year(tokens[-1]) is None:
        tokens.pop()

    year = _fix_year(tokens[0])
    rest = tokens[1:] if year is not None else tokens
    lowered = [t.lower() for t in rest]
    has_round_signal = any(
        _fix_ordinal(t) is not None
        or _fix_slot(t) is not None
        or _ROUND_ONLY_RE.match(t)
        or t.lower() in _ROUND_WORDS
        for t in rest
    )
    if year is None:
        # Without a year this is only a pick if the WHOLE line is pick
        # grammar ("Early 1st", "1.05", "Round 2") — never a name.
        tierless = [t for t in lowered if t not in _TIERS]
        if (
            has_round_signal
            and all(
                _fix_ordinal(t) is not None
                or _fix_slot(t) is not None
                or _ROUND_ONLY_RE.match(t)
                or t.lower() in _ROUND_WORDS
                or t.lower() in _PICK_WORDS
                or _round_number(t) is not None
                for t in tierless
            )
            and tierless
        ):
            return ParsedItem(kind=KIND_PICK, raw=raw, reason=REASON_PICK_YEAR_MISSING)
        return None
    if not has_round_signal:
        return None

    label: str | None = None
    notes: tuple[str, ...] = ()
    n = len(rest)

    def ordinal(rnd: int) -> str:
        return round_suffix(rnd)

    # Exact grammars first.
    if n == 1 and _fix_slot(rest[0]):
        rnd, slot = _fix_slot(rest[0])  # type: ignore[misc]
        label = f"{year} {rnd}.{slot:02d}"
    elif n == 2 and lowered[0] in _PICK_WORDS and _fix_slot(rest[1]):
        rnd, slot = _fix_slot(rest[1])  # type: ignore[misc]
        label = f"{year} {rnd}.{slot:02d}"
    elif n >= 2 and lowered[0] in _TIERS and _fix_ordinal(rest[1]) is not None:
        tail = lowered[2:]
        if all(t in _ROUND_WORDS or t in _PICK_WORDS for t in tail):
            label = f"{year} {_TIERS[lowered[0]]} {ordinal(_fix_ordinal(rest[1]))}"  # type: ignore[arg-type]
    elif n >= 1 and _fix_ordinal(rest[0]) is not None:
        tail = lowered[1:]
        if all(t in _ROUND_WORDS or t in _PICK_WORDS for t in tail):
            label = f"{year} {ordinal(_fix_ordinal(rest[0]))}"  # type: ignore[arg-type]
    elif n == 1 and _ROUND_ONLY_RE.match(rest[0]):
        label = f"{year} Round {_round_number(_ROUND_ONLY_RE.match(rest[0]).group(1))}"  # type: ignore[union-attr]
    elif n >= 2 and lowered[0] in _ROUND_WORDS and _round_number(rest[1]) is not None:
        rnd = _round_number(rest[1])
        tail = lowered[2:]
        if not tail:
            label = f"{year} Round {rnd}"
        elif len(tail) == 2 and tail[0] in _PICK_WORDS and _round_number(rest[3]) is not None:
            slot = int("".join(_YEAR_CHARS.get(c, c) for c in rest[3]))
            label = f"{year} {rnd}.{slot:02d}"
        elif len(tail) == 1 and tail[0] in _PICK_WORDS:
            label = f"{year} Round {rnd}"

    if label is None:
        # "<year> <words naming a team/owner> [Early] <Nth>": keep the round
        # at the grade the label PROVES and say the owner is not established.
        last = rest[-1]
        trailing = [t for t in lowered if t not in _ROUND_WORDS and t not in _PICK_WORDS]
        ord_val = _fix_ordinal(last)
        if ord_val is None and len(rest) >= 2 and lowered[-1] in _ROUND_WORDS:
            # "<year> Team A 1st Round": the suffix word is already excluded.
            ord_val = _fix_ordinal(rest[-2])
        if ord_val is not None and len(trailing) >= 2:
            tier_tok = None
            idx = len(rest) - 1 if _fix_ordinal(last) is not None else len(rest) - 2
            if idx - 1 >= 0 and lowered[idx - 1] in _TIERS:
                tier_tok = _TIERS[lowered[idx - 1]]
            label = f"{year} {tier_tok + ' ' if tier_tok else ''}{ordinal(ord_val)}"
            notes = (NOTE_PICK_OWNER,)
        else:
            return ParsedItem(kind=KIND_PICK, raw=raw, reason=REASON_PICK_UNPARSEABLE)

    parsed = parse_pick_label(label + annotation)
    if parsed is None:
        return ParsedItem(kind=KIND_PICK, raw=raw, reason=REASON_PICK_UNPARSEABLE, label=label)
    try:
        ref = parsed.market_ref
    except ValueError:
        return ParsedItem(kind=KIND_PICK, raw=raw, reason=REASON_PICK_UNPARSEABLE, label=label)
    return ParsedItem(kind=KIND_PICK, raw=raw, market_ref=ref, notes=notes, label=label)


# ── Players ─────────────────────────────────────────────────────────────


_AGE_RE = re.compile(r"^(?:1[89]|[2-4]\d)(?:\.\d)?$")
_AGE_UNITS = frozenset({"yo", "y.o.", "y.o", "yo.", "yrs", "yr", "age"})


def _is_meta_token(token: str) -> bool:
    """Row metadata that may sit between position/team hints, never a hint
    itself: an age ("23.4", "y.o.", "age") or another site's value number
    ("5,542") read in the same segment."""
    tok = token.strip(_EDGE_JUNK + " ")
    return bool(_AGE_RE.match(tok)) or tok.lower() in _AGE_UNITS or _is_value_token(tok)


def _hints_from_tokens(tokens: list[str]) -> tuple[str | None, str | None, bool]:
    """``(position, team, all_tokens_were_hints)``."""
    pos = team = None
    all_hint = bool(tokens)
    for tok in tokens:
        p, t = _position_of(tok), _team_of(tok)
        if p and pos is None:
            pos = p
        elif t and team is None:
            team = t
        elif p or t or tok.upper() in _SKIP_TAGS or _is_meta_token(tok):
            continue
        else:
            all_hint = False
    return pos, team, all_hint


def parse_hints_only(text: str) -> dict | None:
    """``{"position", "team"}`` when the line is ONLY position/team tags
    ("QB · KC", "WR NYJ"), else None."""
    s = _strip_leading(str(text or "")).strip(_EDGE_JUNK + " ")
    s = s.strip("()[] ")
    tokens = [t.strip(_EDGE_JUNK) for t in _HINT_SPLIT_RE.split(s)]
    tokens = [t for t in tokens if t]
    if not tokens:
        return None
    pos, team, all_hint = _hints_from_tokens(tokens)
    if all_hint and (pos or team):
        return {"position": pos, "team": team}
    return None


def _parse_player(text: str, raw: str) -> ParsedItem | None:
    pos = team = None
    s = text
    # 1. Trailing parenthetical: "(WR, NYJ)", "(WR - NYJ)", "(IR)".
    m = _PAREN_RE.search(s)
    if m:
        p, t, _ = _hints_from_tokens([x for x in _HINT_SPLIT_RE.split(m.group(1)) if x])
        pos, team = pos or p, team or t
        s = s[: m.start()].strip()
    # 2. Separator-delimited tails: "Garrett Wilson · WR · NYJ", "X - WR - NYJ".
    parts = [p.strip() for p in _SEPARATORS_RE.split(s) if p and p.strip()]
    if len(parts) > 1:
        head, tails = parts[0], parts[1:]
        tail_tokens = [x for part in tails for x in _HINT_SPLIT_RE.split(part) if x]
        p, t, all_hint = _hints_from_tokens(tail_tokens)
        if all_hint or (p or t):
            pos, team = pos or p, team or t
            s = head
    # 3. Trailing tags / numbers: "Patrick Mahomes QB KC 9,999", "WR12", "25".
    tokens = s.split()
    while len(tokens) > 1:
        last = tokens[-1].strip(_EDGE_JUNK)
        if not last:
            tokens.pop()
            continue
        p, t = _position_of(last), _team_of(last)
        if p:
            pos = pos or p
        elif t:
            team = team or t
        elif _is_value_token(last) or last.isdigit() or last.upper() in _SKIP_TAGS:
            pass
        else:
            break
        tokens.pop()
    # 4. Leading team/position tags ("KC QB Patrick Mahomes").
    while len(tokens) > 2:
        first = tokens[0].strip(_EDGE_JUNK)
        p, t = _position_of(first), _team_of(first)
        if p and len(first) > 1:
            pos = pos or p
        elif t:
            team = team or t
        else:
            break
        tokens.pop(0)
    name = " ".join(t.strip(_EDGE_JUNK) for t in tokens).strip(_EDGE_JUNK + " ")
    name = re.sub(r"\s{2,}", " ", name)

    # Shape checks: a player name is 2-5 tokens of letters, capitalised.
    words = name.split()
    if not (2 <= len(words) <= 5):
        return None
    if any(ch.isdigit() for ch in name):
        return None
    letters = sum(ch.isalpha() for ch in name)
    if letters < 4 or letters < 0.7 * len(name.replace(" ", "")):
        return None
    caps = [w for w in words if w[:1].isupper()]
    lowers = [w for w in words if w[:1].islower() and w.lower() not in _NAME_PARTICLES]
    if lowers and caps:
        # Mixed case with an un-capitalised non-particle word reads as prose
        # ("add Patrick Mahomes"), not a name.
        return None
    if not caps and not lowers:
        return None
    return ParsedItem(
        kind=KIND_PLAYER,
        raw=raw,
        name=name,
        hints={"position": pos, "team": team},
    )


# ── Entry point ─────────────────────────────────────────────────────────


def parse_line(text: str) -> ParsedItem | None:
    """Parse one line of OCR text.  ``None`` = not an asset (the caller files
    it under ``ignored`` with reason ``not_an_asset``)."""
    raw = str(text or "").strip()
    if not raw:
        return None
    s = _strip_leading(raw)
    s = s.strip(_EDGE_JUNK.replace("(", "") + " ")
    if not s:
        return None
    pick = _parse_pick(s, raw)
    if pick is not None:
        return pick
    return _parse_player(s, raw)


def is_asset_like(text: str) -> bool:
    return parse_line(text) is not None
