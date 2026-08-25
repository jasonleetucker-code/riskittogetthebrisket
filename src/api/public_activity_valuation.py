"""Bridge between the private canonical contract and the public
``/api/public/league`` activity trade-grading pipeline.

The public ``src/public_league`` package is strictly isolated from
private rankings — it never reads ``latest_contract_data`` directly.
Instead, ``server.py`` builds a valuation callable out of the cached
private contract and passes it into
``src.public_league.activity.build_section``, which uses the callable
server-side to compute ``{grade, color, label}`` badges for each
trade side.  The raw values that drive the grade never leave the
backend — only the derived grade block appears on the public payload.

This module hosts the parser that walks a canonical contract dict
and returns that callable.  Keeping it outside ``server.py`` lets
the tests import it without pulling in FastAPI, and pins the
contract-shape dependency (``values.displayValue`` /
``values.overall`` / ``values.finalAdjusted``) so a future rename to
the private bundle keys can not silently disable public grading.

``values.rawComposite`` is deliberately NOT part of that dependency —
it is the legacy scraper composite on a different scale.  See
:func:`_value_from_bundle`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from src.history import asof, keys
from src.identity.picks import MarketPickRef


# Rounds the public activity feed can emit labels for.  Matches
# ``_PUBLIC_ACTIVITY_ROUND_LABELS`` in ``server.py`` and the round
# labels used by ``src/api/data_contract.py`` / the frontend pick
# candidate builder.
_ROUND_LABELS: dict[int, str] = {
    1: "1st",
    2: "2nd",
    3: "3rd",
    4: "4th",
    5: "5th",
    6: "6th",
}


# Tier-center slot mapping — matches the canonical pipeline's
# generic-tier suppression centers and the frontend's
# ``TIER_CENTRE_SLOT`` in ``frontend/lib/trade-logic.js``: Early=2,
# Mid=6, Late=10.  The public activity feed only carries
# ``(season, round)`` so we probe the Mid center first.
_TIER_CENTER_SLOTS: tuple[tuple[str, int], ...] = (
    ("Mid", 6),
    ("Early", 2),
    ("Late", 10),
)


def _value_from_bundle(bundle: dict[str, Any]) -> float:
    """Read the canonical board value out of a contract row's ``values``.

    SCALE (math audit 2026-07-30, finding H1).  This chain used to end in
    ``rawComposite`` — the legacy scraper composite, which runs ~1.131x the
    canonical board.  Every row the blend declined to price therefore
    entered public trade grading on a *different scale* from its
    board-priced counterparties, and the two were summed into one side
    total.  On a real payload that was 270 rows, including every
    suppressed generic pick tier.

    ``values.overall`` / ``finalAdjusted`` / ``displayValue`` all mirror
    ``rankDerivedValue`` and are ``None`` when the board declined to price
    the row (``data_contract._player_value_bundle``).  The three keys are
    kept in the chain because they are the contract's published names and
    a renamed key must not silently disable grading — but ``rawComposite``
    is deliberately NOT here.

    Returns 0.0 when no board value is available, which
    ``activity.build_section`` treats as "cannot grade this asset".
    """
    if not isinstance(bundle, dict):
        return 0.0
    for key in ("displayValue", "overall", "finalAdjusted"):
        raw = bundle.get(key)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return 0.0


def build_valuation_from_contract(
    contract: dict[str, Any] | None,
) -> Callable[[dict[str, Any]], float] | None:
    """Build a ``(asset_dict) -> float`` valuation callable from the
    cached canonical contract.

    Returns ``None`` when the contract is empty or the players array
    has no rows carrying a positive value — ``activity.build_section``
    treats ``None`` as the "grading disabled" signal and ships the
    public feed without grade badges (graceful degradation path).

    The callable is safe to hand to
    ``public_league.activity.build_section(... valuation=...)``: it
    accepts the public trade-side received-asset shape
    (``{kind: "player"|"pick", playerId, playerName, position,
    season, round, ...}``) and returns a numeric value.  Neither the
    callable nor its source values is ever serialized into the
    public payload.
    """
    if not contract:
        return None
    players_array = contract.get("playersArray") or []
    if not players_array:
        return None

    raw_aliases = contract.get("pickAliases") or {}
    pick_aliases: dict[str, str] = {}
    if isinstance(raw_aliases, dict):
        for k, v in raw_aliases.items():
            if isinstance(k, str) and isinstance(v, str):
                pick_aliases[k.lower()] = v.lower()

    by_id: dict[str, float] = {}
    by_name: dict[str, float] = {}
    for row in players_array:
        if not isinstance(row, dict):
            continue
        val = _value_from_bundle(row.get("values") or {})
        if val <= 0:
            continue
        # Suppressed generic-tier pick rows keep a stale legacy value
        # for name-search purposes but are NOT authoritative — the
        # canonical pipeline aliases them to slot-specific siblings.
        # Exclude them so our tier probes either hit the alias
        # redirect or fall through to the real slot row.
        suppressed = bool(row.get("pickGenericSuppressed"))
        if suppressed:
            continue
        pid = str(row.get("playerId") or "").strip()
        if pid:
            by_id[pid] = val
        name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
        if name:
            by_name[name.lower()] = val

    if not by_id and not by_name:
        return None

    def _resolve(name: str) -> float | None:
        key = name.lower()
        aliased = pick_aliases.get(key)
        if aliased is not None:
            hit = by_name.get(aliased)
            if hit is not None:
                return hit
        return by_name.get(key)

    def _pick_value(season: Any, round_: Any) -> float:
        try:
            round_int = int(round_)
        except (TypeError, ValueError):
            return 0.0
        label = _ROUND_LABELS.get(round_int)
        season_str = str(season or "").strip()
        if not label or not season_str:
            return 0.0
        for tier, _slot in _TIER_CENTER_SLOTS:
            hit = _resolve(f"{season_str} {tier} {label}")
            if hit is not None:
                return hit
        for _tier, slot in _TIER_CENTER_SLOTS:
            hit = _resolve(f"{season_str} Pick {round_int}.{slot:02d}")
            if hit is not None:
                return hit
        return 0.0

    def _valuation(asset: Any) -> float:
        if not isinstance(asset, dict):
            return 0.0
        kind = asset.get("kind")
        if kind == "player":
            pid = str(asset.get("playerId") or "").strip()
            if pid:
                hit = by_id.get(pid)
                if hit is not None:
                    return hit
            name = str(asset.get("playerName") or "").strip()
            if name:
                return by_name.get(name.lower(), 0.0)
            return 0.0
        if kind == "pick":
            return _pick_value(asset.get("season"), asset.get("round"))
        return 0.0

    return _valuation


# ── As-of valuation (V1-97 / C3-REPLAY-01) ──────────────────────────────
#
# ``build_valuation_from_contract`` above answers "what is this asset
# worth on TODAY's board" — correct for a live board, wrong for grading a
# historical trade, because a trade graded against today's board silently
# uses evidence that did not exist on the day it happened (hindsight).
#
# The functions below answer the different, date-scoped question: "what
# did the canonical temporal ledger (``src.history.asof`` — C1-U4, the
# ONE owner of as-of reads) know about this asset strictly before the
# trade's own instant?"  They never read ``latest_contract_data`` and
# never fall back to a current value when history is missing — an
# unresolved (asset, instant) pair returns ``None``, and the caller
# (``src.public_league.activity``) is responsible for turning that into
# an explicit "insufficient historical evidence" state rather than a
# partial or substituted total.


def asset_history_key(asset: dict[str, Any]) -> str | None:
    """The canonical ``src.history.keys`` asset key for a public-activity
    trade-side asset dict (``{kind: "player"|"pick", ...}``).

    Player rows resolve platform-id-first via ``keys.player_asset_key`` —
    the same key every other history consumer uses for a player, so a
    trade-side asset and a canonical board row for the same player always
    address the same ledger series.

    Pick rows on this surface carry only ``(season, round)`` — no
    slot/tier — so they resolve to the GENERIC market-pick grade via
    ``MarketPickRef``, the same grade a rank-less "2027 Round 1" board row
    occupies.  A season/round that cannot be parsed as an int, or a round
    outside ``MarketPickRef``'s valid range, is not a pick this ledger
    could ever have recorded a value for, so this returns ``None`` rather
    than raising — the caller treats it exactly like any other
    unresolved key.
    """
    if not isinstance(asset, dict):
        return None
    kind = asset.get("kind")
    if kind == "player":
        return keys.player_asset_key(
            asset.get("playerId"), asset.get("playerName"), asset.get("position")
        )
    if kind == "pick":
        try:
            year = int(asset.get("season"))
            round_num = int(asset.get("round"))
        except (TypeError, ValueError):
            return None
        try:
            ref = MarketPickRef(year=year, round_num=round_num)
        except ValueError:
            return None
        return ref.canonical_id
    return None


def trade_instant_from_created_at(created_at: Any) -> datetime | None:
    """Sleeper's trade ``created`` / ``status_updated`` field, parsed as
    the UTC instant the trade actually happened.

    The field is epoch MILLISECONDS.  Missing, zero, negative, or
    non-numeric input returns ``None`` — never "now": a trade whose
    timestamp cannot be trusted must degrade to an unresolvable instant,
    never silently price it under today's date (which would reintroduce
    the exact hindsight leak this module exists to close).
    """
    try:
        ms = float(created_at)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _normalize_instant(instant: datetime | None) -> datetime | None:
    """UTC-aware, or ``None``.  A naive instant is never guessed at —
    the ledger's contract requires proof of timezone, and there is no
    safe assumption to make about a caller that skipped it."""
    if instant is None or instant.tzinfo is None:
        return None
    return instant.astimezone(timezone.utc)


def build_asof_valuation(
    requests: Iterable[tuple[dict[str, Any], datetime | None]],
    *,
    path: Path | None = None,
    max_age_days: int | None = None,
) -> Callable[[dict[str, Any], datetime | None], float | None]:
    """Build a pure ``(asset, instant) -> float | None`` resolver from the
    canonical temporal ledger, batched exactly once over every
    ``(asset, instant)`` pair the caller passes in.

    ``requests`` should be the FULL set of asset/instant pairs a feed
    build will ever need to resolve — the whole point of batching
    through ``asof.batch_known_before`` is paying the ledger's I/O cost
    once per feed build, not once per trade side.  The returned callable
    does no I/O; it is a plain in-memory lookup, safe to call from a
    tight loop.

    ``None`` — never ``0.0`` — means the ledger has no admissible
    observation for that asset strictly before that instant.  There is
    no legitimate zero canonical value, so coercing a miss to zero would
    make "priced at nothing" indistinguishable from "unpriced".  The
    caller decides what an unresolved asset means for the surface it
    renders.
    """
    keyed: list[tuple[str, datetime]] = []
    seen: set[tuple[str, str]] = set()
    for asset, instant in requests:
        utc = _normalize_instant(instant)
        if utc is None:
            continue
        key = asset_history_key(asset)
        if key is None:
            continue
        pair = (key, utc.isoformat())
        if pair in seen:
            continue
        seen.add(pair)
        keyed.append((key, utc))

    value_by_pair: dict[tuple[str, str], float | None] = {}
    if keyed:
        batch = asof.batch_known_before(keyed, path=path, max_age_days=max_age_days)
        for (key, utc), result in zip(keyed, batch["results"]):
            val = result.get("value")
            value_by_pair[(key, utc.isoformat())] = float(val) if val is not None else None

    def _resolve(asset: dict[str, Any], instant: datetime | None) -> float | None:
        utc = _normalize_instant(instant)
        if utc is None:
            return None
        key = asset_history_key(asset)
        if key is None:
            return None
        return value_by_pair.get((key, utc.isoformat()))

    return _resolve
