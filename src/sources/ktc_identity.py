"""KeepTradeCut playerID -> asset identity.  ONE owner.

KTC's public crowd pages (``/dynasty/trade-database``,
``/dynasty/waiver-database``) reference every asset by a bare numeric
``playerID``.  Resolving those ids is a single concept, and it had three
implementations: an inline regex in ``scripts/fetch_crowd_faab.py``, a
second inline regex in ``Dynasty Scraper.py``, and a third derivation
feeding a never-shipped ``ktcIdMap`` export.  They disagreed about which
array to read, which is why one of them resolved 145 of 192 references
and the other resolved none at all.

WHICH ARRAY IS RIGHT — measured 2026-08-18 on both live pages
─────────────────────────────────────────────────────────────
Both pages carry ``playersArray`` (500 rows, the value board) and
``allPlayerSearchValues`` (~1,997 rows, the site-wide search index).
The crowd feeds reference the SEARCH index, not the board:

    identity source          entries   waiver refs unresolved
    playersArray                 500                       47
    allPlayerSearchValues      1,997                        0

So ``playersArray`` is not a smaller-but-correct map — it is the wrong
population, and every reference it misses is a real claim silently
dropped.  ``allPlayerSearchValues`` is preferred and ``playersArray``
is a recorded fallback, never a silent one.

MISSING IS NEVER ZERO, AND UNRESOLVED IS NEVER A NAME
─────────────────────────────────────────────────────
The retired scraper helper returned ``f"Player#{pid}"`` for an
unresolvable id.  That string is TRUTHY, so it passed every downstream
emptiness check and then joined nothing — a missing identity wearing the
costume of a present one.  An unresolved reference is reported as
``kind="unresolved"`` with a reason and no ``name``.  It may be counted,
logged and diagnosed; it may not be presented as a player.

PICKS ARE CLASSIFIED, NOT PLAYER-RESOLVED
─────────────────────────────────────────
Draft picks reach these feeds two different ways, and both were being
treated as players:

  * as a numeric id whose search-index row is a pick — vendor-declared
    by ``position == "RDP"`` (36 rows), e.g. ``1709 -> "2027 Mid 3rd"``;
  * as a literal label in the reference position itself, e.g.
    ``"2026 Pick 1.02"`` (52 of the trade feed's 259 references).

A FAAB amount (``"$3.00"``) also appears in the reference position.
``classify`` names all four kinds so no caller has to guess from shape.

This module REPORTS what an id is.  It does not blend, value, or rank —
valuation stays in the pipeline, and pick VALUE identity belongs to
``src/identity/picks.py``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal, Mapping

__all__ = [
    "KtcIdentityCollision",
    "KtcIdentityMap",
    "KtcAsset",
    "parse_ktc_identity",
    "SEARCH_INDEX_VAR",
    "VALUE_BOARD_VAR",
]

SEARCH_INDEX_VAR = "allPlayerSearchValues"
VALUE_BOARD_VAR = "playersArray"

#: KTC's own position code for a rookie draft pick row.
_PICK_POSITION = "RDP"

#: Picks written out in the reference position rather than by id.  All
#: three shapes are OBSERVED on the live trade feed (2026-08-18) — they
#: are not speculative formats:
#:     ``2026 Pick 1.02``    (season + slot)     x52
#:     ``2028 Round 5``      (season + round)    x7, rounds past 4
#:     ``Startup Pick 26.01`` (startup draft)    x1
#: Anything else stays ``unresolved``; a label we do not recognise must
#: not be quietly filed as a pick.
_LITERAL_PICKS = (
    re.compile(r"^\s*\d{4}\s+Pick\s+\d+\.\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*\d{4}\s+Round\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*Startup\s+Pick\s+\d+\.\d+\s*$", re.IGNORECASE),
)

#: A FAAB dollar amount in the reference position, e.g. ``$3.00``.
_FAAB_AMOUNT = re.compile(r"^\s*\$\s*(\d+(?:\.\d+)?)\s*$")

AssetKind = Literal["player", "pick", "faab_amount", "unresolved"]


class KtcIdentityCollision(RuntimeError):
    """Two different names claimed the same KTC playerID.

    Fails closed rather than picking one.  A collision means the feed's
    identity is genuinely ambiguous, and silently choosing a winner is
    how a wrong join becomes invisible.
    """


@dataclass(frozen=True)
class KtcAsset:
    """What one reference in a crowd feed actually is."""

    raw: str
    kind: AssetKind
    name: str | None = None
    player_id: int | None = None
    reason: str | None = None

    @property
    def is_player(self) -> bool:
        return self.kind == "player"


@dataclass(frozen=True)
class KtcIdentityMap:
    """Resolved KTC identity for one page load."""

    players: Mapping[int, str] = field(default_factory=dict)
    picks: Mapping[int, str] = field(default_factory=dict)
    source: str | None = None
    rejected_ids: int = 0
    missing_names: int = 0

    def __len__(self) -> int:  # convenience for "did we get anything"
        return len(self.players) + len(self.picks)

    def name_for(self, player_id: int) -> str | None:
        """Player name for an id, or ``None``.  Never a fabricated label."""
        return self.players.get(player_id)

    def classify(self, ref: Any) -> KtcAsset:
        """Name what a single feed reference is.

        Accepts the raw value exactly as the feed carries it (KTC uses
        strings for ids in ``teamOne.playerIds`` and ints elsewhere).
        """
        raw = "" if ref is None else str(ref)
        text = raw.strip()

        if not text:
            return KtcAsset(raw=raw, kind="unresolved", reason="empty_reference")

        money = _FAAB_AMOUNT.match(text)
        if money:
            return KtcAsset(raw=raw, kind="faab_amount", name=text)

        if any(pattern.match(text) for pattern in _LITERAL_PICKS):
            return KtcAsset(raw=raw, kind="pick", name=text)

        try:
            pid = int(text)
        except ValueError:
            return KtcAsset(raw=raw, kind="unresolved", reason="not_an_id")

        # KTC uses -1 (and occasionally 0) as "no asset on this side".
        if pid <= 0:
            return KtcAsset(raw=raw, kind="unresolved", reason="sentinel_no_asset")

        if pid in self.picks:
            return KtcAsset(raw=raw, kind="pick", name=self.picks[pid], player_id=pid)
        if pid in self.players:
            return KtcAsset(raw=raw, kind="player", name=self.players[pid], player_id=pid)
        return KtcAsset(raw=raw, kind="unresolved", player_id=pid, reason="id_not_in_index")


def _extract_array(html: str, var_name: str) -> list[Any] | None:
    """Pull one inline ``var <name> = [...]`` array out of the page.

    Returns ``None`` when the array is absent or unparseable — both are
    "we did not observe it", and neither is an empty market.
    """
    match = re.search(
        r"var\s+%s\s*=\s*(\[.*?\]);" % re.escape(var_name),
        html,
        re.DOTALL,
    )
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, list) else None


def _ingest(rows: Iterable[Any]) -> tuple[dict[int, str], dict[int, str], int, int]:
    players: dict[int, str] = {}
    picks: dict[int, str] = {}
    rejected = 0
    missing = 0

    for row in rows:
        if not isinstance(row, dict):
            rejected += 1
            continue

        raw_id = row.get("playerID")
        try:
            pid = int(raw_id)
        except (TypeError, ValueError):
            rejected += 1
            continue
        if pid <= 0:
            rejected += 1
            continue

        name = row.get("playerName")
        name = name.strip() if isinstance(name, str) else ""
        if not name:
            # A row with an id and no name is not a resolution.
            missing += 1
            continue

        bucket = picks if str(row.get("position") or "").upper() == _PICK_POSITION else players
        other = players if bucket is picks else picks

        prior = bucket.get(pid)
        if prior is not None and prior != name:
            raise KtcIdentityCollision(
                f"KTC playerID {pid} claimed by two names: {prior!r} and {name!r}"
            )
        cross = other.get(pid)
        if cross is not None:
            raise KtcIdentityCollision(
                f"KTC playerID {pid} appears as both a player and a pick: "
                f"{cross!r} and {name!r}"
            )
        bucket[pid] = name  # identical duplicates dedupe harmlessly

    return players, picks, rejected, missing


def parse_ktc_identity(html: str) -> KtcIdentityMap:
    """Build the id -> identity map for one KTC page.

    Prefers the search index; falls back to the value board and RECORDS
    which it used, because a fallback that looks like a success is how
    the 47 dropped claims stayed invisible.

    Raises :class:`KtcIdentityCollision` if one id carries two names.
    """
    for var_name in (SEARCH_INDEX_VAR, VALUE_BOARD_VAR):
        rows = _extract_array(html, var_name)
        if not rows:
            continue
        players, picks, rejected, missing = _ingest(rows)
        if not players and not picks:
            continue
        return KtcIdentityMap(
            players=players,
            picks=picks,
            source=var_name,
            rejected_ids=rejected,
            missing_names=missing,
        )

    # Neither array present or usable.  An empty map with source=None is
    # distinguishable from a populated one, and callers must treat it as
    # "unobserved", never as "this page has no players".
    return KtcIdentityMap()
