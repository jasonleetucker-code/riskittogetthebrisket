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

from typing import Any, Callable


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


def _value_from_bundle(bundle: dict[str, Any]) -> float | None:
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

    Returns ``None`` when no board value is available — NOT 0.0
    (W19-F003).  ``sanitize_side_values`` drops non-positive numbers,
    so a 0.0 here made an asset the board declined to price
    indistinguishable from one that was never in the trade: dropped
    from both the linear sum and the KTC value adjustment, with the
    letter grade still emitted over what was left.  ``None`` is the
    signal ``activity._side_values`` counts.
    """
    if not isinstance(bundle, dict):
        return None
    for key in ("displayValue", "overall", "finalAdjusted"):
        raw = bundle.get(key)
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return None


def build_valuation_from_contract(
    contract: dict[str, Any] | None,
) -> Callable[[dict[str, Any]], float | None] | None:
    """Build a ``(asset_dict) -> float | None`` valuation callable from
    the cached canonical contract.

    The callable returns ``None`` for any asset the board does not
    price.  That is a different answer from ``0.0``, which means
    "priced, and worth nothing" — see :func:`_value_from_bundle`.
    Note the two ``None``s in this signature are unrelated: the outer
    one disables grading entirely, the inner one abstains on one asset.

    Returns ``None`` when the contract is empty or the players array
    has no rows carrying a positive value — ``activity.build_section``
    treats ``None`` as the "grading disabled" signal and ships the
    public feed without grade badges (graceful degradation path).

    The callable is safe to hand to
    ``public_league.activity.build_section(... valuation=...)``: it
    accepts the public trade-side received-asset shape
    (``{kind: "player"|"pick", playerId, playerName, position,
    season, round, ...}``) and returns a numeric value or ``None``.
    Neither the callable nor its source values is ever serialized into
    the public payload.
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
        if val is None:
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

    # Every miss below returns ``None``, never 0.0 (W19-F003).  The
    # 2026 board carries pick rows for 2026-2028 rounds 1-6 only, so
    # every 2024/2025 pick and every round >= 5 future pick misses
    # PERMANENTLY — 156 of the 224 unpriced slots on the live 191-trade
    # feed are picks, including six ``2024 R1`` and fourteen
    # ``2025 R1``.  "Off the board" is a lasting property of this
    # historical feed, not a transient gap, and a zero would report
    # every one of those as a worthless asset.
    def _pick_value(season: Any, round_: Any) -> float | None:
        try:
            round_int = int(round_)
        except (TypeError, ValueError):
            return None
        label = _ROUND_LABELS.get(round_int)
        season_str = str(season or "").strip()
        if not label or not season_str:
            return None
        for tier, _slot in _TIER_CENTER_SLOTS:
            hit = _resolve(f"{season_str} {tier} {label}")
            if hit is not None:
                return hit
        for _tier, slot in _TIER_CENTER_SLOTS:
            hit = _resolve(f"{season_str} Pick {round_int}.{slot:02d}")
            if hit is not None:
                return hit
        return None

    def _valuation(asset: Any) -> float | None:
        if not isinstance(asset, dict):
            return None
        kind = asset.get("kind")
        if kind == "player":
            pid = str(asset.get("playerId") or "").strip()
            if pid:
                hit = by_id.get(pid)
                if hit is not None:
                    return hit
            name = str(asset.get("playerName") or "").strip()
            if name:
                return by_name.get(name.lower())
            return None
        if kind == "pick":
            return _pick_value(asset.get("season"), asset.get("round"))
        return None

    return _valuation
