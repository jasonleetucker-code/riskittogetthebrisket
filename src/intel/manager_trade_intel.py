"""Manager Intelligence Batch B3 — draft capital and trade intelligence.

Part of the activity payload (``src/intel/manager_activity.py``), built over
the SAME request's reads — the league's rosters, drafts and completed draft
picks, plus one ``/league/{id}/traded_picks`` call per league — and the
SAME windowed trade stream B1 publishes.  Nothing here fetches.

Draft capital
    Which picks the searched manager holds in each league NOW.  The default
    ownership + traded-diff fold is the canonical one,
    ``src/identity/picks.py::build_pick_ownership`` (the same fold the Sleeper
    overlay publishes from); a ``/traded_picks`` answer is read through
    ``picks.traded_picks_observation`` and a failed or non-list fetch leaves
    that league's picks ``None`` with ``pickOwnershipState: "unavailable"``
    (``picks.pick_ownership_fields``) — never ``[]``, which would claim the
    manager owns no picks.

    Seasons are the league's OWN draft years from the canonical league-scope
    resolver (``draft_class_evidence.league_draft_years_for`` →
    ``pick_lifecycle.league_draft_years``): anchor ``max(calendar year,
    league.season)``, ``OWNED_PICK_HORIZON_CLASSES`` classes, minus classes
    this league has PROVEN retired (rookie draft complete AND its picks
    rostered).  For any league the evidence is assembled
    (``pick_lifecycle.evidence_from_sleeper``) from the ``/drafts`` list and
    completed-draft picks this request already read; when the drafts list
    could not be read the resolver falls back to the persisted snapshot
    (registry leagues only) and otherwise has no evidence, which retires
    nothing.  Unlike the warm-pass collector this does not hop to the
    previous season's league (no new fetch path); that hop only ever affects
    classes before the anchor.  Rounds are the league's own
    ``settings.draft_rounds`` (``pick_lifecycle.league_draft_rounds``).

    Values: ``manager_activity._Pricer.pick`` →
    ``pick_value_resolution.resolve_pick_value`` at the GENERIC grade
    (season + round) — never a fabricated tier or slot.  Unpriced →
    ``value: None`` + ``valueReason``; league totals are sums over PRICED
    picks with the unpriced counted beside them (the draft-capital posture).

Pick movement
    Picks the manager acquired and sent by trade, from the windowed trade
    stream, with dates and counterparties.

Tendencies
    Counts with samples over the windowed trades — evidence, never labels.
    Every block carries ``n``, the window and ``sufficientSample``; below
    :data:`TENDENCY_MIN_SAMPLE` the block says "insufficient sample" rather
    than implying a pattern.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any

#: PRIOR (not fitted, not validated): the smallest number of observations a
#: tendency block needs before the UI presents its counts as a sample rather
#: than "insufficient sample".  Declared here so no surface invents its own.
TENDENCY_MIN_SAMPLE = 3

#: PRIOR age buckets, by the player's CURRENT age (Sleeper directory / board).
#: ``(label, lowest age inclusive, highest age inclusive)``; ``None`` = open.
AGE_BUCKETS: tuple[tuple[str, float | None, float | None], ...] = (
    ("≤23", None, 23),
    ("24-26", 24, 26),
    ("27-29", 27, 29),
    ("30+", 30, None),
)
AGE_UNKNOWN = "unknown"

COV_COMPLETE = "complete"

DC_REASON_EARLIER_SEASON = "earlier_season"
DC_REASON_ROSTERS_UNAVAILABLE = "rosters_unavailable"


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── draft capital ───────────────────────────────────────────────────────


def _draft_evidence(league: Any, observed_at: str) -> Any:
    from src.identity.pick_lifecycle import evidence_from_sleeper  # noqa: PLC0415

    rostered: list[str] = []
    for roster in league.rosters:
        rostered.extend(str(p) for p in (roster.get("players") or []) if p)
    return evidence_from_sleeper(
        league_key=league.key,
        sleeper_league_id=league.league_id,
        drafts=league.drafts or [],
        picks_by_draft_id=league.draft_picks,
        rostered_player_ids=rostered if league.rosters else None,
        observed_at=observed_at,
        draft_lists_observed=[league.league_id],
    )


def _league_years(league: Any, *, calendar_year: int, observed_at: str) -> tuple[Any, str]:
    from src.api.draft_class_evidence import league_draft_years_for  # noqa: PLC0415

    if league.drafts is not None:
        ev = _draft_evidence(league, observed_at)
        years = league_draft_years_for(
            league.league_id,
            league_season=league.season,
            evidence=ev,
            calendar_year=calendar_year,
        )
        return years, "league_drafts_read"
    years = league_draft_years_for(
        league.league_id, league_season=league.season, calendar_year=calendar_year
    )
    return years, "persisted_snapshot_or_none"


def _owner_name(league: Any, rid: int | None) -> str | None:
    return league.display_name(league.current_owner(rid)) if rid is not None else None


def league_draft_capital(
    league: Any,
    pricer: Any,
    *,
    traded_picks: list[Any] | None,
    coverage: str,
    calendar_year: int,
    observed_at: str,
) -> dict[str, Any]:
    """One league's picks for the searched manager (see the module docstring).

    ``traded_picks`` is the ``/traded_picks`` OBSERVATION (a list, or
    ``None`` when not observed); ``coverage`` is that fetch's coverage state.
    """
    from src.identity import picks as pick_identity  # noqa: PLC0415
    from src.identity.pick_lifecycle import league_draft_rounds  # noqa: PLC0415

    settings = league.raw.get("settings") if isinstance(league.raw.get("settings"), dict) else {}
    rounds = league_draft_rounds(settings)
    raw_rounds = _int(settings.get("draft_rounds"))
    years, evidence_source = _league_years(
        league, calendar_year=calendar_year, observed_at=observed_at
    )
    mine = sorted(league.manager_roster_ids())
    entry: dict[str, Any] = {
        **league.entry(),
        "coverage": coverage,
        "managerRosterIds": mine,
        "rounds": rounds,
        "roundsSource": "league_settings" if raw_rounds == rounds else "default",
        "draftYears": {**years.to_dict(), "evidence": evidence_source},
        "picks": None,
        "ownPicksTradedAway": None,
        "counts": None,
        "pricedValue": None,
        "pricedPickCount": None,
        "unpricedPickCount": None,
        "unpricedReasons": None,
        "bySeason": None,
    }
    if traded_picks is None:
        entry.update(pick_identity.pick_ownership_fields(False))
        return entry
    entry.update(pick_identity.pick_ownership_fields(True))
    roster_ids = sorted(
        r for r in (_int(x.get("roster_id")) for x in league.rosters) if r is not None and r > 0
    )
    try:
        owned = pick_identity.build_pick_ownership(
            league.key,
            roster_ids,
            traded_picks,
            seasons=years.owned_pick_seasons,
            rounds=rounds,
        )
    except ValueError:
        # No valid pick identity can be minted for this league: ownership is
        # unknown, never "owns nothing".
        entry[pick_identity.PICK_OWNERSHIP_STATE_FIELD] = pick_identity.PICK_OWNERSHIP_UNAVAILABLE
        entry[pick_identity.PICK_OWNERSHIP_REASON_FIELD] = "pick_identity_unavailable"
        return entry
    mine_set = set(mine)
    held: list[dict[str, Any]] = []
    away: list[dict[str, Any]] = []
    for o in sorted(
        owned,
        key=lambda p: (p.identity.season, p.identity.round_num, p.identity.origin_roster_id),
    ):
        ident = o.identity
        owner = o.state.owner_roster_id
        origin = ident.origin_roster_id
        if owner not in mine_set and origin not in mine_set:
            continue
        asset = pricer.pick(
            {"season": ident.season, "round": ident.round_num, "roster_id": origin},
            league,
            ident.canonical_id,
        )
        asset.update(
            {
                "originOwnerName": _owner_name(league, origin),
                "currentOwnerRosterId": owner,
                "currentOwnerName": _owner_name(league, owner),
                "own": origin in mine_set,
            }
        )
        if owner in mine_set:
            held.append(asset)
        else:
            away.append(asset)

    priced = [p for p in held if p.get("value") is not None]
    unpriced = [p for p in held if p.get("value") is None]
    if not held:
        priced_value: int | None = 0  # observed: the manager holds no pick
    elif priced:
        priced_value = sum(int(p["value"]) for p in priced)
    else:
        priced_value = None  # holds picks, none priced: no total to state
    by_season: dict[str, dict[str, int]] = {}
    for p in held:
        bucket = by_season.setdefault(str(p["season"]), {"held": 0, "own": 0, "acquired": 0})
        bucket["held"] += 1
        bucket["own" if p["own"] else "acquired"] += 1
    entry.update(
        {
            "picks": held,
            "ownPicksTradedAway": away,
            "counts": {
                "held": len(held),
                "own": sum(1 for p in held if p["own"]),
                "acquired": sum(1 for p in held if not p["own"]),
                "ownTradedAway": len(away),
            },
            "pricedValue": priced_value,
            "pricedPickCount": len(priced),
            "unpricedPickCount": len(unpriced),
            "unpricedReasons": dict(sorted(Counter(p["valueReason"] for p in unpriced).items())),
            "bySeason": dict(sorted(by_season.items())),
        }
    )
    return entry


def unread_league_entry(league: Any, reason: str, coverage: str) -> dict[str, Any]:
    """A league whose rosters could not be read: ownership unknown."""
    from src.identity import picks as pick_identity  # noqa: PLC0415

    return {
        **league.entry(),
        "coverage": coverage,
        "managerRosterIds": None,
        "rounds": None,
        "roundsSource": None,
        "draftYears": None,
        pick_identity.PICK_OWNERSHIP_STATE_FIELD: pick_identity.PICK_OWNERSHIP_UNAVAILABLE,
        pick_identity.PICK_OWNERSHIP_REASON_FIELD: reason,
        "picks": None,
        "ownPicksTradedAway": None,
        "counts": None,
        "pricedValue": None,
        "pricedPickCount": None,
        "unpricedPickCount": None,
        "unpricedReasons": None,
        "bySeason": None,
    }


def draft_capital_totals(entries: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [e for e in entries if e.get("picks") is not None]
    held = [p for e in observed for p in e["picks"]]
    priced = [p for p in held if p.get("value") is not None]
    return {
        "leaguesObserved": len(observed),
        "leaguesUnavailable": len(entries) - len(observed),
        "picksHeld": len(held),
        "acquiredHeld": sum(1 for p in held if not p.get("own")),
        "ownTradedAway": sum(len(e.get("ownPicksTradedAway") or []) for e in observed),
        "pricedPickCount": len(priced),
        "unpricedPickCount": len(held) - len(priced),
        # A sum over PRICED picks of OBSERVED leagues only; ``None`` when picks
        # are held but none is priced.
        "pricedValue": (
            sum(int(p["value"]) for p in priced) if priced else (0 if not held else None)
        ),
    }


# ── pick movement ───────────────────────────────────────────────────────


def _counterparty(trade: dict[str, Any], pick_id: str | None, key: str) -> dict[str, Any]:
    """The side whose ``key`` list carries ``pick_id`` (picksOut for a pick the
    manager received, picksIn for one they sent)."""
    for side in trade.get("sides") or []:
        if side.get("isManager"):
            continue
        if pick_id and any(p.get("pickId") == pick_id for p in side.get(key) or []):
            return {"rosterId": side["rosterId"], "displayName": side.get("displayName")}
    return {"rosterId": None, "displayName": None}


def pick_movements(
    trades: list[dict[str, Any]], capital_by_league: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Picks acquired and sent by trade (windowed), newest first, each with
    whether the manager still holds it (``None`` when that cannot be said)."""
    rows: list[dict[str, Any]] = []
    for trade in trades:
        me = next((s for s in trade.get("sides") or [] if s.get("isManager")), None)
        if me is None:
            continue
        for direction, key, other_key in (
            ("acquired", "picksIn", "picksOut"),
            ("sent", "picksOut", "picksIn"),
        ):
            for pick in me.get(key) or []:
                cap = capital_by_league.get(trade["leagueId"]) or {}
                held_ids = (
                    {p.get("pickId") for p in cap["picks"]}
                    if cap.get("picks") is not None
                    else None
                )
                owned_seasons = set((cap.get("draftYears") or {}).get("ownedPickSeasons") or [])
                if held_ids is None:
                    still, still_reason = None, "pick_ownership_unavailable"
                elif pick.get("season") not in owned_seasons:
                    still, still_reason = None, "class_not_in_owned_horizon"
                else:
                    still, still_reason = pick.get("pickId") in held_ids, None
                rows.append(
                    {
                        "id": f"{trade['id']}:{direction}:{pick.get('pickId') or pick.get('label')}",
                        "tradeId": trade["id"],
                        "direction": direction,
                        "leagueId": trade["leagueId"],
                        "leagueName": trade.get("leagueName"),
                        "season": trade.get("season"),
                        "week": trade.get("week"),
                        "occurredAt": trade.get("occurredAt"),
                        "pick": pick,
                        "counterparty": _counterparty(trade, pick.get("pickId"), other_key),
                        "stillHeld": still,
                        "stillHeldReason": still_reason,
                    }
                )
    by_league: dict[str, dict[str, Any]] = {}
    for r in rows:
        b = by_league.setdefault(
            r["leagueId"], {"leagueName": r["leagueName"], "acquired": 0, "sent": 0}
        )
        b[r["direction"]] += 1
    return {
        "rows": rows,
        "acquired": sum(1 for r in rows if r["direction"] == "acquired"),
        "sent": sum(1 for r in rows if r["direction"] == "sent"),
        "byLeague": by_league,
    }


# ── tendencies ──────────────────────────────────────────────────────────


def age_bucket(age: Any) -> str:
    if not isinstance(age, (int, float)) or isinstance(age, bool):
        return AGE_UNKNOWN
    for label, lo, hi in AGE_BUCKETS:
        if (lo is None or age >= lo) and (hi is None or age <= hi):
            return label
    # Between buckets (fractional ages, e.g. 23.5): the next bucket up.
    for label, lo, _hi in AGE_BUCKETS:
        if lo is not None and age < lo:
            return label
    return AGE_UNKNOWN


def _sample(n: int) -> dict[str, Any]:
    return {"n": n, "minSample": TENDENCY_MIN_SAMPLE, "sufficientSample": n >= TENDENCY_MIN_SAMPLE}


def _flow() -> dict[str, Any]:
    return {"count": 0, "pricedValue": 0, "pricedCount": 0, "unpricedCount": 0}


def _add_flow(flow: dict[str, Any], asset: dict[str, Any]) -> None:
    flow["count"] += 1
    if asset.get("value") is None:
        flow["unpricedCount"] += 1
    else:
        flow["pricedCount"] += 1
        flow["pricedValue"] += int(asset["value"])


def _finish_flow(flow: dict[str, Any]) -> dict[str, Any]:
    # A value sum exists only when something was priced.
    if not flow["pricedCount"]:
        flow["pricedValue"] = None
    return flow


def _breakdown(
    me_sides: list[dict[str, Any]], key_of: Any, order: list[str] | None = None
) -> dict[str, Any]:
    groups: dict[str, dict[str, dict[str, Any]]] = {}
    n = 0
    for side in me_sides:
        for direction, assets in (
            ("acquired", side.get("playersIn") or []),
            ("sent", side.get("playersOut") or []),
        ):
            for asset in assets:
                key = key_of(asset)
                g = groups.setdefault(key, {"acquired": _flow(), "sent": _flow()})
                _add_flow(g[direction], asset)
                n += 1
    keys = order or sorted(groups)
    rows = [
        {
            "key": k,
            "acquired": _finish_flow(groups[k]["acquired"]),
            "sent": _finish_flow(groups[k]["sent"]),
        }
        for k in keys
        if k in groups
    ]
    return {**_sample(n), "unit": "players", "rows": rows}


def _trade_shape(side: dict[str, Any]) -> tuple[str, int, int]:
    p_in, p_out = len(side.get("playersIn") or []), len(side.get("playersOut") or [])
    k_in, k_out = len(side.get("picksIn") or []), len(side.get("picksOut") or [])
    if not (k_in or k_out):
        kind = "players_for_players" if p_in and p_out else "other"
    elif not (p_in or p_out):
        kind = "picks_for_picks"
    elif k_out and not p_out and p_in and not k_in:
        kind = "picks_for_players"
    elif p_out and not k_out and k_in and not p_in:
        kind = "players_for_picks"
    else:
        kind = "mixed"
    return kind, p_in + k_in, p_out + k_out


SHAPE_KINDS = (
    "picks_for_players",
    "players_for_picks",
    "players_for_players",
    "picks_for_picks",
    "mixed",
    "other",
)


def trade_tendencies(trades: list[dict[str, Any]], *, window: str, season: Any) -> dict[str, Any]:
    """Counts with samples over the windowed trades (manager side only).

    A trade whose attribution is uncertain (no party's current owner made it)
    may not be this manager's decision, so it is left out and counted.
    """
    counted = [t for t in trades if not (t.get("attribution") or {}).get("uncertain")]
    me_sides = [
        s for t in counted for s in (t.get("sides") or []) if s.get("isManager")
    ]  # one manager side per trade
    shapes = Counter()
    pieces = Counter()
    piece_shapes = Counter()
    for side in me_sides:
        kind, pin, pout = _trade_shape(side)
        shapes[kind] += 1
        if pin > pout:
            pieces["depth"] += 1
        elif pin < pout:
            pieces["consolidation"] += 1
        else:
            pieces["even"] += 1
        piece_shapes[f"{pin}-for-{pout}"] += 1
    n_trades = len(me_sides)
    return {
        "window": window,
        "season": season,
        "tradeCount": n_trades,
        "excludedUncertain": len(trades) - len(counted),
        "minSample": TENDENCY_MIN_SAMPLE,
        "minSampleBasis": "PRIOR",
        "basis": (
            "Counts over this manager's completed trades in the window — evidence, not "
            "labels. A block below the minimum sample is shown as insufficient."
        ),
        "positions": _breakdown(me_sides, lambda a: a.get("position") or "UNKNOWN"),
        "ages": {
            **_breakdown(
                me_sides,
                lambda a: age_bucket(a.get("age")),
                order=[b[0] for b in AGE_BUCKETS] + [AGE_UNKNOWN],
            ),
            "basis": "current age (Sleeper directory), not age at the time of the trade",
            "buckets": [b[0] for b in AGE_BUCKETS],
        },
        "pickPlayer": {
            **_sample(n_trades),
            "unit": "trades",
            "counts": {k: shapes[k] for k in SHAPE_KINDS},
        },
        "pieces": {
            **_sample(n_trades),
            "unit": "trades",
            "counts": {k: pieces[k] for k in ("consolidation", "depth", "even")},
            "definition": (
                "consolidation = fewer pieces received than sent; depth = more pieces "
                "received than sent (players + picks)"
            ),
            "shapes": dict(sorted(piece_shapes.items())),
        },
    }


def observed_at_iso(now_s: float) -> str:
    return datetime.fromtimestamp(now_s, tz=timezone.utc).isoformat()


__all__ = [
    "AGE_BUCKETS",
    "TENDENCY_MIN_SAMPLE",
    "age_bucket",
    "draft_capital_totals",
    "league_draft_capital",
    "pick_movements",
    "trade_tendencies",
    "unread_league_entry",
]
