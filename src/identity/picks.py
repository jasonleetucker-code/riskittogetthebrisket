"""Canonical draft-pick identity — THE owner (C1-ID-02 / unit C1-U3).

This module is the single place that decides what a draft-pick asset IS,
how it is keyed, how legacy representations parse into it, and how it
serializes back out.  Design record:
``docs/identity/C1_ID_02_PICK_IDENTITY.md``.  Consumers may keep their
own *presentation* formats; they may not keep their own identity rules.

Two distinct canonical concepts, deliberately separate:

* :class:`LeaguePickIdentity` — an OWNED asset: a claim on a selection
  in one league's season-N rookie draft, identified by the franchise
  whose draft position it represents (Sleeper's own model: a
  ``traded_picks`` row is ``(season, round, roster_id)`` with
  ``owner_id`` as mere state).  Identity fields: ``league_key``,
  ``season``, ``round_num``, ``origin_roster_id`` — nothing else.
  Current owner and realized slot are MUTABLE STATE
  (:class:`LeaguePickState`); a trade or the draft order becoming known
  never mints a new asset.

* :class:`MarketPickRef` — a REFERENCE CLASS ranking sources price
  ("2026 Pick 1.06", "2027 Early 1st", "a 2028 2nd") at exactly one of
  three refinement grades: exact slot, tier, or generic round.  Nobody
  owns these; a league pick *resolves to* one for valuation
  (:func:`market_resolution`), and the resolution is a function of its
  state — never part of its identity.

Hard rules, each pinned by ``tests/identity/test_pick_identity.py``:

* identity construction reads no clock and no display name — every
  component is a birth fact, so an id minted at trade time resolves
  forever;
* an unknown slot is ``None`` and resolves to the GENERIC market grade —
  never a fabricated tier or slot (the legacy "unknown → Mid" display
  convention survives only inside the explicitly-named legacy label
  formatters, for output parity, and is labelled there);
* parse functions return exactly what a representation proves, or
  ``None`` — they never guess and never fuzzy-match;
* valuation is a different concept: nothing in this module reads,
  computes or stores a value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

__all__ = [
    "LeaguePickIdentity",
    "LeaguePickState",
    "OwnedLeaguePick",
    "MarketPickRef",
    "PickMarketResolution",
    "ParsedPickLabel",
    "PICK_TIERS",
    "build_pick_ownership",
    "format_intel_pick_asset_id",
    "format_pick_label_baked",
    "format_pick_label_overlay",
    "format_trade_pick_label",
    "is_pick_name",
    "legacy_slot_tier_label",
    "market_resolution",
    "parse_any_pick_asset_id",
    "parse_board_pick_name",
    "parse_board_slot_name",
    "parse_board_tier_name",
    "parse_intel_pick_asset_id",
    "parse_league_pick_id",
    "parse_market_pick_id",
    "parse_pick_label",
    "pick_year_from_name",
    "round_suffix",
    "slot_tier",
]

# ── Grammar constants ─────────────────────────────────────────────────
#
# The board grammars are moved here VERBATIM from
# ``src/api/data_contract.py`` (which now imports them back) — the
# acceptance bounds are part of the published board's behavior and must
# not drift: rounds 1-6, slots 1-12, years 20xx.  The tier regex
# deliberately does not validate the ordinal suffix against the digit
# ("2027 Early 1th" matches), exactly as the pipeline always accepted.
BOARD_SLOT_RE = re.compile(r"^(20\d{2})\s+Pick\s+([1-6])\.(0?[1-9]|1[0-2])$", re.I)
BOARD_TIER_RE = re.compile(r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(st|nd|rd|th)$", re.I)

PICK_TIERS = ("early", "mid", "late")

# Canonical-id component grammar.  A league key must be a slug that can
# never be mistaken for a season year, which keeps ``pick:``-prefixed
# ids formally unambiguous against the intel ledger's legacy
# ``pick:<season>:<round>`` grade (see ``parse_any_pick_asset_id``).
_LEAGUE_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

_LEAGUE_PICK_ID_RE = re.compile(
    r"^pick:(?P<league>[a-z][a-z0-9_-]*):(?P<season>20\d{2}):r(?P<round>\d{1,2}):o(?P<origin>\d{1,3})$"
)
_MARKET_PICK_ID_RE = re.compile(
    r"^mpick:(?P<year>20\d{2}):r(?P<round>\d{1,2})(?::(?:s(?P<slot>\d{1,2})|t(?P<tier>early|mid|late)))?$"
)
_INTEL_PICK_ID_RE = re.compile(r"^pick:(?P<season>20\d{2}):(?P<round>\d{1,2})$")

# Legacy label grammars (census L1-L5 + public-league "R1" + trade
# fallback "Round 1").  Each parses to exactly what it proves.
_LABEL_ANNOTATION_RE = re.compile(r"\s*\((?P<ann>[^)]*)\)\s*$")
_LABEL_SLOT_RE = re.compile(r"^(20\d{2})\s+(?:Pick\s+)?([1-6])\.(0?[1-9]|1[0-2])$", re.I)
_LABEL_TIER_RE = re.compile(
    r"^(20\d{2})\s+(Early|Mid|Late)\s+([1-6])(?:st|nd|rd|th)$", re.I
)
_LABEL_ROUND_SUFFIX_RE = re.compile(r"^(20\d{2})\s+([1-6])(?:st|nd|rd|th)$", re.I)
_LABEL_ROUND_WORD_RE = re.compile(r"^(20\d{2})\s+(?:Round\s+|R)([1-9]\d?)$", re.I)

# ``_is_pick_name`` moved verbatim from data_contract (same three
# searches, same looseness — it is a DETECTOR, not a parser).
_IS_PICK_TIER_SEARCH = re.compile(r"\b(20\d{2})\s+(EARLY|MID|LATE)\s+[1-6](ST|ND|RD|TH)\b", re.I)
_IS_PICK_SLOT_SEARCH = re.compile(r"\b(20\d{2})\s+[1-6]\.(0?[1-9]|1[0-2])\b", re.I)
_IS_PICK_WORD_SEARCH = re.compile(r"\b(20\d{2})\s+(PICK|ROUND)\b", re.I)

_YEAR_SEARCH = re.compile(r"\b(20\d{2})\b")


def _coerce_int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def round_suffix(round_num: int) -> str:
    """``1 -> "1st"`` … matching the scraper/overlay convention."""
    n = int(round_num)
    if n == 1:
        return "1st"
    if n == 2:
        return "2nd"
    if n == 3:
        return "3rd"
    return f"{n}th"


# ── League pick: identity ─────────────────────────────────────────────


@dataclass(frozen=True)
class LeaguePickIdentity:
    """The four birth facts that ARE a league draft pick.

    Nothing here can change after the asset exists: not by trade (owner
    is state), not by the draft order landing (slot is state), not by a
    team renaming (display names are presentation).  Equality and hash
    are field equality on exactly these four.
    """

    league_key: str
    season: int
    round_num: int
    origin_roster_id: int

    def __post_init__(self) -> None:
        if not _LEAGUE_KEY_RE.match(self.league_key or ""):
            raise ValueError(
                f"league_key must be a registry slug (got {self.league_key!r}); "
                "raw Sleeper league ids are not league identity"
            )
        if not (2000 <= int(self.season) <= 2099):
            raise ValueError(f"season out of range: {self.season!r}")
        if not (1 <= int(self.round_num) <= 20):
            raise ValueError(f"round out of range: {self.round_num!r}")
        if int(self.origin_roster_id) < 1:
            raise ValueError(f"origin_roster_id out of range: {self.origin_roster_id!r}")

    @property
    def canonical_id(self) -> str:
        return (
            f"pick:{self.league_key}:{self.season}"
            f":r{self.round_num}:o{self.origin_roster_id}"
        )


def parse_league_pick_id(s: str) -> LeaguePickIdentity | None:
    """Exact inverse of :attr:`LeaguePickIdentity.canonical_id`.

    Returns ``None`` for anything that is not a canonical league-pick
    id — including the intel ledger's legacy ``pick:<season>:<round>``
    grade, which is structurally unambiguous against this form because a
    league key cannot start with a digit.
    """
    m = _LEAGUE_PICK_ID_RE.match(str(s or "").strip())
    if not m:
        return None
    try:
        return LeaguePickIdentity(
            league_key=m.group("league"),
            season=int(m.group("season")),
            round_num=int(m.group("round")),
            origin_roster_id=int(m.group("origin")),
        )
    except ValueError:
        return None


# ── League pick: state (never identity) ───────────────────────────────


@dataclass
class LeaguePickState:
    """What is true about a league pick TODAY.

    ``slot`` is the realized draft slot when the league's draft order is
    actually known, else ``None``.  ``None`` means UNKNOWN — it is never
    0, never a tier, and never defaulted.  ``owner_roster_id`` is who
    holds the asset now; it changes by trade without touching identity.
    """

    owner_roster_id: int | None = None
    slot: int | None = None
    source: str = ""
    observed_at: str | None = None


@dataclass
class OwnedLeaguePick:
    identity: LeaguePickIdentity
    state: LeaguePickState = field(default_factory=LeaguePickState)


def build_pick_ownership(
    league_key: str,
    roster_ids: Iterable[int],
    traded_picks: Iterable[Mapping[str, Any]] | None,
    *,
    seasons: Iterable[int],
    rounds: int,
    slot_by_origin: Mapping[tuple[int, int], int] | None = None,
    source: str = "sleeper_traded_picks",
) -> list[OwnedLeaguePick]:
    """THE default-ownership + traded-diff fold, written once.

    Seed: every franchise owns its own pick in every round of every
    requested season.  Then apply Sleeper ``/traded_picks`` rows —
    ``roster_id`` is the ORIGIN (identity), ``owner_id`` the current
    holder (state).  Rows that don't join a seeded identity (unknown
    origin, out-of-range season/round) are skipped, as every legacy
    copy of this fold skipped them.  One deliberate hardening over the
    overlay's copy: a row whose ``owner_id`` is not a league roster is
    also skipped (the pick stays with its origin), where the legacy
    pivot filed the asset under the foreign id and it silently vanished
    from every team's list.  Valid Sleeper data never hits this branch
    — ``owner_id`` is always a roster in the league.

    Sleeper serializes ``season`` as a string; normalization to ``int``
    happens here, at the boundary, so no consumer ever joins int-vs-str
    again (RED: ``test_red_natural_key_join_fails_on_season_type``).

    ``slot_by_origin`` — ``{(season, origin_roster_id): slot}`` from the
    league's draft-order endpoints — populates realized slots as STATE.
    """
    rids = [int(r) for r in roster_ids]
    rid_set = set(rids)
    out: dict[tuple[int, int, int], OwnedLeaguePick] = {}
    for season in seasons:
        season_i = int(season)
        for rnd in range(1, int(rounds) + 1):
            for rid in rids:
                ident = LeaguePickIdentity(
                    league_key=league_key,
                    season=season_i,
                    round_num=rnd,
                    origin_roster_id=rid,
                )
                slot = None
                if slot_by_origin:
                    slot = slot_by_origin.get((season_i, rid))
                out[(season_i, rnd, rid)] = OwnedLeaguePick(
                    identity=ident,
                    state=LeaguePickState(
                        owner_roster_id=rid, slot=slot, source=source
                    ),
                )
    for tp in traded_picks or []:
        if not isinstance(tp, Mapping):
            continue
        season_i = _coerce_int(tp.get("season"))
        rnd = _coerce_int(tp.get("round"))
        origin = _coerce_int(tp.get("roster_id"))
        owner = _coerce_int(tp.get("owner_id"))
        if season_i is None or rnd is None or origin is None or owner is None:
            continue
        if origin not in rid_set or owner not in rid_set:
            continue
        entry = out.get((season_i, rnd, origin))
        if entry is not None:
            entry.state.owner_roster_id = owner
    return list(out.values())


# ── Market pick reference ─────────────────────────────────────────────


@dataclass(frozen=True)
class MarketPickRef:
    """A pick reference class at exactly one refinement grade.

    ``slot`` and ``tier`` are mutually exclusive; both absent means the
    GENERIC grade ("a 2028 2nd").  ``tier`` is lowercase
    ``early|mid|late``.
    """

    year: int
    round_num: int
    slot: int | None = None
    tier: str | None = None

    def __post_init__(self) -> None:
        if not (2000 <= int(self.year) <= 2099):
            raise ValueError(f"year out of range: {self.year!r}")
        if not (1 <= int(self.round_num) <= 20):
            raise ValueError(f"round out of range: {self.round_num!r}")
        if self.slot is not None and self.tier is not None:
            raise ValueError("slot and tier are mutually exclusive refinements")
        if self.slot is not None and int(self.slot) < 1:
            raise ValueError(f"slot out of range: {self.slot!r}")
        if self.tier is not None and self.tier not in PICK_TIERS:
            raise ValueError(f"tier must be one of {PICK_TIERS}: {self.tier!r}")

    @property
    def grade(self) -> str:
        if self.slot is not None:
            return "slot"
        if self.tier is not None:
            return "tier"
        return "generic"

    @property
    def canonical_id(self) -> str:
        base = f"mpick:{self.year}:r{self.round_num}"
        if self.slot is not None:
            return f"{base}:s{self.slot}"
        if self.tier is not None:
            return f"{base}:t{self.tier}"
        return base

    def board_row_name(self) -> str | None:
        """The canonical board display name, or ``None`` when the board
        has no row form for this grade (the generic grade has no board
        row today — that completeness question is C1-U6's, and inventing
        a name here would fabricate a row the pipeline never made)."""
        if self.slot is not None:
            return f"{self.year} Pick {self.round_num}.{self.slot:02d}"
        if self.tier is not None:
            return f"{self.year} {self.tier.capitalize()} {round_suffix(self.round_num)}"
        return None


def parse_market_pick_id(s: str) -> MarketPickRef | None:
    """Exact inverse of :attr:`MarketPickRef.canonical_id`."""
    m = _MARKET_PICK_ID_RE.match(str(s or "").strip())
    if not m:
        return None
    slot = _coerce_int(m.group("slot")) if m.group("slot") else None
    tier = m.group("tier") or None
    try:
        return MarketPickRef(
            year=int(m.group("year")),
            round_num=int(m.group("round")),
            slot=slot,
            tier=tier,
        )
    except ValueError:
        return None


# ── Board-name grammar (owned here; data_contract delegates) ──────────


def parse_board_slot_name(name: str) -> tuple[int, int, int] | None:
    """``"2026 Pick 1.06" -> (2026, 1, 6)`` — verbatim semantics of the
    contract's ``_parse_pick_slot`` (None for tier rows)."""
    if not name:
        return None
    m = BOARD_SLOT_RE.match(str(name).strip())
    if not m:
        return None
    try:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    except (TypeError, ValueError):
        return None


def parse_board_tier_name(name: str) -> tuple[int, str, int] | None:
    """``"2027 Early 1st" -> (2027, "Early", 1)`` — verbatim semantics of
    the contract's ``_parse_pick_tier`` (capitalized tier, None for slot
    rows)."""
    if not name:
        return None
    m = BOARD_TIER_RE.match(str(name).strip())
    if not m:
        return None
    try:
        return int(m.group(1)), m.group(2).capitalize(), int(m.group(3))
    except (TypeError, ValueError):
        return None


def parse_board_pick_name(name: str) -> MarketPickRef | None:
    """Either board grammar → :class:`MarketPickRef`, else ``None``."""
    slot_parsed = parse_board_slot_name(name)
    if slot_parsed is not None:
        year, rnd, slot = slot_parsed
        return MarketPickRef(year=year, round_num=rnd, slot=slot)
    tier_parsed = parse_board_tier_name(name)
    if tier_parsed is not None:
        year, tier, rnd = tier_parsed
        return MarketPickRef(year=year, round_num=rnd, tier=tier.lower())
    return None


def is_pick_name(name: str) -> bool:
    """Verbatim port of the contract's ``_is_pick_name`` detector.

    NOTE — this package hosts TWO pick detectors answering DIFFERENT
    questions, and they deliberately do not agree (measured divergence
    on 5 of 9 label forms, census `docs/identity/C1_ID_02_CENSUS.md`):

    * this one — "should the CONTRACT treat this row name as a pick
      row" (board-detector semantics; accepts bare slot forms like
      ``2026 1.05`` and ``Round`` phrasing);
    * ``resolution.looks_like_pick_name`` — "should PLAYER matching
      refuse this string" (C1-U2's frozen V1 refusal rung; accepts
      bare round-suffix ``2028 2nd`` but not annotated roster labels).

    Do not "unify" them casually: each is pinned to its consumer's
    behavior, and widening the refusal rung is a player-identity
    behavior change (a C1-U2 follow-up, not a drive-by).  For parsing
    (rather than detecting), use :func:`parse_pick_label`, which covers
    every measured production grammar including the annotated forms
    both detectors miss."""
    n = str(name or "").strip()
    if not n:
        return False
    if _IS_PICK_TIER_SEARCH.search(n):
        return True
    if _IS_PICK_SLOT_SEARCH.search(n):
        return True
    if _IS_PICK_WORD_SEARCH.search(n):
        return True
    return False


def pick_year_from_name(name: str) -> int | None:
    """Verbatim port of the contract's ``_pick_year_from_name``."""
    if not name:
        return None
    m = _YEAR_SEARCH.search(str(name))
    if not m:
        return None
    try:
        return int(m.group(1))
    except (TypeError, ValueError):
        return None


# ── Legacy label parsing (every measured grammar) ─────────────────────


@dataclass(frozen=True)
class ParsedPickLabel:
    """What a legacy pick label PROVES — nothing more.

    ``origin_team_name`` is a display string when the label carried a
    "(from X)" annotation; resolving it to a roster id requires the
    caller's roster map for the league AND DATE the label was minted —
    this module never fuzzy-matches names.  ``is_own`` is True for
    "(own)", None when the label carried no annotation.  ``tier`` is
    lowercase; ``slot`` is only set when the label literally stated it.
    ``grammar`` names which measured form matched (board_slot,
    bare_slot, tier, round_suffix, round_word).
    """

    year: int
    round_num: int
    slot: int | None = None
    tier: str | None = None
    origin_team_name: str | None = None
    is_own: bool | None = None
    grammar: str = ""

    @property
    def market_ref(self) -> MarketPickRef:
        return MarketPickRef(
            year=self.year, round_num=self.round_num, slot=self.slot, tier=self.tier
        )


def parse_pick_label(raw: str) -> ParsedPickLabel | None:
    """Parse any measured legacy pick-label grammar (census L1-L5, the
    public-league ``"2027 R1"`` form, the trade fallback
    ``"2027 Round 2"``, with or without a trailing "(own)" / "(from X)"
    annotation).  Returns ``None`` for anything else — never a guess."""
    s = str(raw or "").strip()
    if not s:
        return None
    origin_team_name: str | None = None
    is_own: bool | None = None
    ann = _LABEL_ANNOTATION_RE.search(s)
    if ann:
        text = ann.group("ann").strip()
        if text.lower() == "own":
            is_own = True
        elif text.lower().startswith("from "):
            is_own = False
            origin_team_name = text[5:].strip() or None
        # An unrecognized annotation is presentation noise; the base
        # label still parses, but we claim nothing about origin.
        s = s[: ann.start()].strip()
    m = _LABEL_SLOT_RE.match(s)
    if m:
        return ParsedPickLabel(
            year=int(m.group(1)),
            round_num=int(m.group(2)),
            slot=int(m.group(3)),
            origin_team_name=origin_team_name,
            is_own=is_own,
            grammar="board_slot" if "pick" in s.lower() else "bare_slot",
        )
    m = _LABEL_TIER_RE.match(s)
    if m:
        return ParsedPickLabel(
            year=int(m.group(1)),
            round_num=int(m.group(3)),
            tier=m.group(2).lower(),
            origin_team_name=origin_team_name,
            is_own=is_own,
            grammar="tier",
        )
    m = _LABEL_ROUND_SUFFIX_RE.match(s)
    if m:
        return ParsedPickLabel(
            year=int(m.group(1)),
            round_num=int(m.group(2)),
            origin_team_name=origin_team_name,
            is_own=is_own,
            grammar="round_suffix",
        )
    m = _LABEL_ROUND_WORD_RE.match(s)
    if m:
        return ParsedPickLabel(
            year=int(m.group(1)),
            round_num=int(m.group(2)),
            origin_team_name=origin_team_name,
            is_own=is_own,
            grammar="round_word",
        )
    return None


# ── Tier rule and market resolution ───────────────────────────────────


def slot_tier(slot: int | None, league_size: int = 12) -> str | None:
    """League-size-aware Early/Mid/Late thirds — the backend rule
    (``per_tier = size // 3``), which wins over the frontend's 12-team
    hardcode.  Returns ``None`` for an unknown slot: unknown is NOT
    "mid" (that fabrication survives only in the legacy formatters
    below, labelled)."""
    n = _coerce_int(slot)
    if not isinstance(n, int) or n <= 0:
        return None
    size = max(3, int(league_size or 12))
    per_tier = max(1, size // 3)
    if n <= per_tier:
        return "early"
    if n <= min(size, per_tier * 2):
        return "mid"
    return "late"


@dataclass(frozen=True)
class PickMarketResolution:
    """Which market reference prices a league pick, and on what basis.

    ``basis`` is one of:

    * ``exact_slot`` — slot known and the year is the active draft, so
      the board's slot rows apply;
    * ``tier_from_slot`` — slot known but the board only carries tier
      rows for that year;
    * ``unknown_slot`` — no slot exists yet; the honest resolution is
      the GENERIC grade.  Nothing here invents a tier or a slot — the
      legacy "assume Mid" convention is a display/lookup approximation
      that belongs to its consumers, labelled, never to identity.
    """

    ref: MarketPickRef
    basis: str


def market_resolution(
    *,
    year: int,
    round_num: int,
    slot: int | None,
    current_draft_year: int,
    league_size: int = 12,
) -> PickMarketResolution:
    """Deterministic (identity, state) → market-reference resolution.

    Pure function: the clock is an INPUT (``current_draft_year`` — the
    contract's ``current_rookie_draft_year()`` at the caller), never
    read here.  The generic→exact transition is this function changing
    its answer as ``slot`` becomes known and the draft year advances —
    the league pick's identity never changes across it.
    """
    if slot is not None and int(slot) > 0:
        if int(year) <= int(current_draft_year):
            return PickMarketResolution(
                ref=MarketPickRef(year=int(year), round_num=int(round_num), slot=int(slot)),
                basis="exact_slot",
            )
        tier = slot_tier(int(slot), league_size=league_size)
        return PickMarketResolution(
            ref=MarketPickRef(year=int(year), round_num=int(round_num), tier=tier),
            basis="tier_from_slot",
        )
    return PickMarketResolution(
        ref=MarketPickRef(year=int(year), round_num=int(round_num)),
        basis="unknown_slot",
    )


# ── Legacy display formatting (presentation, produced by the owner) ───
#
# Both producers' grammars are reproduced BYTE-FOR-BYTE (parity-pinned
# against the live implementations) so routing them through the owner
# changes no served payload.  The "unknown slot → Mid" fabrication the
# legacy grammars require lives HERE and only here, named as such.


def legacy_slot_tier_label(slot: Any, league_size: int = 12) -> str:
    """The legacy DISPLAY fabrication: unknown slot renders as "Mid".

    Kept ONLY for output parity of the two legacy label grammars (the
    overlay's and scraper's ``_slot_to_tier_label`` both delegate
    here); the canonical answer for an unknown slot is
    :func:`market_resolution`'s ``unknown_slot`` basis, which fabricates
    nothing."""
    tier = slot_tier(slot, league_size=league_size)
    return (tier or "mid").capitalize()


def format_pick_label_baked(
    *,
    season: int,
    round_num: int,
    slot: int | None,
    current_year: int,
    league_size: int = 12,
) -> str:
    """The scraper's baked roster-label grammar (census L3, S2 shape):
    future years tiered ("2027 Mid 1st"), the current year slot-specific
    when known ("2026 1.03"), round-suffix otherwise ("2026 1st")."""
    season_i = int(season)
    rnd = int(round_num)
    if season_i >= int(current_year) + 1:
        return f"{season_i} {legacy_slot_tier_label(slot, league_size)} {round_suffix(rnd)}"
    if isinstance(slot, int) and slot > 0:
        return f"{season_i} {rnd}.{str(slot).zfill(2)}"
    return f"{season_i} {round_suffix(rnd)}"


def format_pick_label_overlay(season: Any, round_num: int, slot: int | None = None) -> str:
    """The overlay's roster-label grammar (census S4): slot-specific when
    known ("2027 1.05"), round-suffix otherwise ("2027 1st").  ``season``
    passes through verbatim (the overlay historically formatted the
    string Sleeper sent)."""
    if slot is not None and slot > 0:
        return f"{season} {round_num}.{str(slot).zfill(2)}"
    return f"{season} {round_suffix(int(round_num))}"


def format_trade_pick_label(
    pick: Mapping[str, Any],
    rid_to_name: Mapping[Any, str],
    draft_slot_by_origin: Mapping[tuple[int, int], int],
    *,
    current_year: int,
    league_size: int = 12,
) -> str:
    """The trade-history label grammar (census L4), one implementation.

    Byte-identical to the two legacy copies (overlay
    ``_format_trade_pick_label`` and the scraper's inline version),
    parity-pinned.  ``current_year`` is REQUIRED here — the legacy
    copies defaulted it from the wall clock, which is exactly the
    serialization drift pinned by
    ``test_red_year_rollover_changes_the_label_with_no_state_change``;
    callers that want today's behavior pass their own clock.
    """
    season = _coerce_int(pick.get("season"))
    round_num = _coerce_int(pick.get("round"))
    origin_rid = _coerce_int(pick.get("roster_id") or pick.get("origin_roster_id"))

    from_team: str | None = None
    if origin_rid is not None:
        from_team = (
            rid_to_name.get(origin_rid)
            or rid_to_name.get(str(origin_rid))
            or f"Team {origin_rid}"
        )

    base_label: str | None = None
    if season is not None and round_num is not None and round_num > 0:
        slot = (
            draft_slot_by_origin.get((season, origin_rid))
            if origin_rid is not None
            else None
        )
        if season >= int(current_year) + 1:
            tier_label = legacy_slot_tier_label(slot, league_size)
            base_label = f"{season} {tier_label} {round_suffix(round_num)}"
        elif isinstance(slot, int) and slot > 0:
            base_label = f"{season} {round_num}.{str(slot).zfill(2)}"
        else:
            base_label = f"{season} {round_suffix(round_num)}"

    if not base_label:
        season_txt = str(pick.get("season", "")).strip()
        round_txt = str(pick.get("round", "?")).strip()
        base_label = f"{season_txt} Round {round_txt}".strip()

    return f"{base_label} (from {from_team})" if from_team else base_label


# ── Intel-ledger legacy grade ─────────────────────────────────────────


def format_intel_pick_asset_id(season: Any, round_num: Any) -> str:
    """The intel ledger's PERSISTED asset-id grade:
    ``pick:<season>:<round>``.

    This is a GENERIC-grade market key applied to league assets — two
    real picks of the same season+round collapse into it (RED:
    ``test_red_two_distinct_2027_seconds_share_one_asset_id``).  It is
    kept because it is persisted in the production SQLite ledger and
    holdings/events must keep joining; the re-key onto
    :attr:`LeaguePickIdentity.canonical_id` is C1-U8's migration
    (C1-ACQ-01/-03), where the transaction ledger is built.
    """
    return f"pick:{season}:{round_num}"


def parse_intel_pick_asset_id(s: str) -> tuple[int, int] | None:
    """``"pick:2027:2" -> (2027, 2)`` — the legacy generic grade only."""
    m = _INTEL_PICK_ID_RE.match(str(s or "").strip())
    if not m:
        return None
    return int(m.group("season")), int(m.group("round"))


def parse_any_pick_asset_id(
    s: str,
) -> tuple[str, LeaguePickIdentity | MarketPickRef | tuple[int, int]] | None:
    """Tagged parse across every canonical/persisted id grade:
    ``("league", LeaguePickIdentity)`` / ``("market", MarketPickRef)`` /
    ``("intel_generic", (season, round))`` — or ``None``.  The grades
    are formally unambiguous: a league key cannot start with a digit,
    so ``pick:2027:2`` can only be the intel grade."""
    league = parse_league_pick_id(s)
    if league is not None:
        return ("league", league)
    market = parse_market_pick_id(s)
    if market is not None:
        return ("market", market)
    intel = parse_intel_pick_asset_id(s)
    if intel is not None:
        return ("intel_generic", intel)
    return None
