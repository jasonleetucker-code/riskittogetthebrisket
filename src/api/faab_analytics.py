"""League-level FAAB analytics — historical bid summarizer.

Powers two consumer surfaces:

  1. ``GET /api/public/league/faabAnalytics`` (lazy section) — used
     by the /waivers page's "league FAAB context" panel to show the
     average winning bid, top historical bids by position, and
     comparable bids for any specific player.

  2. ``src/trade/faab_recommender.py::recommend_faab`` (B6) —
     calibrates the per-player FAAB recommendation against the
     league's actual historical winning bids for similar
     position+tier so the recommendation reflects how THIS league
     bids, not just a generic formula.

Inputs
──────
A ``PublicLeagueSnapshot`` (from ``src.public_league.snapshot``).
We walk every season's completed ``waiver`` and ``free_agent``
transactions, pull ``settings.waiver_bid`` for the FAAB amount,
and resolve player IDs through ``snapshot.nfl_players``.

The resulting summary is intentionally JSON-serializable (no
dataclass return types) so the contract layer can pass it
through verbatim.

Out of scope
────────────
*  Failed waiver bids — Sleeper's API doesn't expose them, so the
   "winning bid" history is the only signal we have.  Documented
   as a known limitation in the FAAB recommender's UI copy.
*  Sleeper trending data — orthogonal to historical bid analytics
   and gathered separately by the recommender.
"""

from __future__ import annotations

import statistics
from typing import Any

from src.public_league.snapshot import PublicLeagueSnapshot


# ── Tier thresholds (winning-bid amount, not value) ──────────────
# Calibrated for a 100-budget league; thresholds scale linearly with
# league_budget so a 200-budget league reads the same tier labels.
# Tier 1 is starter-tier waiver wars, tier 4 is dart throws.
_TIER_BREAKPOINTS_PCT = (
    ("tier1", 0.20),  # ≥20% of budget  ($20+ on $100)
    ("tier2", 0.10),  # 10-20%
    ("tier3", 0.03),  # 3-10%
    ("tier4", 0.0),  # ≤3% (incl. zero-bid free-agent pickups)
)


def _player_position(snapshot: PublicLeagueSnapshot, pid: str) -> str | None:
    """Resolve the NFL position for a player ID.  Returns ``None``
    for IDs we can't find in the players dump (Sleeper occasionally
    references ghost IDs for retired players)."""
    rec = snapshot.nfl_players.get(str(pid)) if isinstance(snapshot.nfl_players, dict) else None
    if not isinstance(rec, dict):
        return None
    pos = rec.get("position") or rec.get("fantasy_positions", [None])[0]
    if not pos:
        return None
    pos_str = str(pos).upper()
    # Normalize IDP positions to base buckets so all D-line variants
    # roll up under "DL" for the position-bid summary.
    if pos_str in ("DT", "DE", "EDGE", "NT"):
        return "DL"
    if pos_str in ("ILB", "OLB", "MLB"):
        return "LB"
    if pos_str in ("CB", "FS", "SS", "S"):
        return "DB"
    return pos_str


def _player_name(snapshot: PublicLeagueSnapshot, pid: str) -> str:
    rec = snapshot.nfl_players.get(str(pid)) if isinstance(snapshot.nfl_players, dict) else None
    if not isinstance(rec, dict):
        return str(pid)
    return (
        rec.get("full_name")
        or f"{rec.get('first_name') or ''} {rec.get('last_name') or ''}".strip()
        or str(pid)
    )


def _tier_for_bid(bid: int, league_budget: int) -> str:
    """Bucket a winning bid into one of four tiers based on % of
    league budget.  Floors at tier4 so zero-bid FA pickups still
    appear in the bid history."""
    if league_budget <= 0:
        return "tier4"
    pct = float(bid) / float(league_budget)
    for label, breakpoint in _TIER_BREAKPOINTS_PCT:
        if pct >= breakpoint:
            return label
    return "tier4"


def _season_budget(season: Any) -> int:
    """Waiver budget for ONE season.  Falls back to 100 (Sleeper's default).

    Per-season, because this league's budget has changed across seasons and
    a bid is only interpretable against the budget it was placed under.
    """
    if season is None:
        return 100
    league = getattr(season, "league", None)
    if not isinstance(league, dict):
        return 100
    settings = league.get("settings") or {}
    if not isinstance(settings, dict):
        return 100
    try:
        v = int(settings.get("waiver_budget"))
        if v > 0:
            return v
    except (TypeError, ValueError):
        pass
    return 100


def _league_budget(snapshot: PublicLeagueSnapshot) -> int:
    """The CURRENT season's waiver budget — the unit every output is in."""
    return _season_budget(snapshot.current_season)


def _normalize_bid(bid: float, season_budget: int, current_budget: int) -> float:
    """Express a historical bid in CURRENT-season dollars.

    A bid only means something as a share of the budget it was placed
    under. This league's budget has been $1000, $200 and $100 across
    seasons, and every aggregate here pooled the raw dollar figures: a $200
    bid from a $1000-budget season (20% of it) was averaged against $100
    budgets as though it were 200% of one.

    Measured effect: positionBids reported an RB average of 43.0 with a max
    of 340 in a $100 league, against a budget-normalized 8.58 — a 5.0x
    inflation. `faab_recommender` blends that average 50/50 into every
    recommendation for any position with 3+ historical bids, which is all
    eight, so replacement-level running backs drew $22-$32 bids on a $100
    budget. Audit finding W11-F001 (P0, upheld under adversarial review).

    Output stays in DOLLARS so no consumer's units change — the recommender
    blends these against its own dollar figures.
    """
    if season_budget <= 0:
        return float(bid)
    return float(bid) / float(season_budget) * float(current_budget)


def _stats_block(values: list[float]) -> dict[str, Any]:
    """Compute {avg, min, max, count} on a list of bids.  Returns a
    zero-shape block when the list is empty so the contract is
    always destructure-safe.

    ``values`` may carry fractional entries — a multi-add transaction
    splits one bid across its added players.  Rounding happens HERE,
    for display, never on the way in.  ``min``/``max`` round rather
    than truncate so a $3.60 share reads as $4."""
    if not values:
        return {"avg": 0.0, "min": 0, "max": 0, "count": 0}
    return {
        "avg": round(statistics.fmean(values), 2),
        "min": int(round(min(values))),
        "max": int(round(max(values))),
        "count": len(values),
    }


def _walk_waivers(
    snapshot: PublicLeagueSnapshot,
) -> list[dict[str, Any]]:
    """Flatten every season's completed waiver/FA transactions into
    one list, annotated with the season string + the resolved
    winning-bid amount."""
    out: list[dict[str, Any]] = []
    for season in snapshot.seasons:
        for tx in season.waivers():
            settings = tx.get("settings") or {}
            try:
                bid = int(settings.get("waiver_bid") or 0)
            except (TypeError, ValueError):
                bid = 0
            adds = tx.get("adds") or {}
            roster_ids = tx.get("roster_ids") or []
            roster_id = roster_ids[0] if roster_ids else None
            out.append(
                {
                    "season": season.season,
                    "leagueId": season.league_id,
                    "type": str(tx.get("type") or ""),
                    "bid": bid,
                    # The budget this bid was actually placed under. Without
                    # it the raw dollar figure is uninterpretable across
                    # seasons — see ``_normalize_bid``.
                    "seasonBudget": _season_budget(season),
                    "adds": adds if isinstance(adds, dict) else {},
                    "rosterId": roster_id,
                    "ownerId": _owner_for_roster(season, roster_id),
                    "createdAt": int(tx.get("status_updated") or tx.get("created") or 0),
                }
            )
    return out


def _owner_for_roster(season: Any, roster_id: Any) -> str | None:
    """Lookup owner_id for a roster_id within a SeasonSnapshot.
    Defensive — returns None when the roster isn't found (mid-
    season ownership swaps shouldn't crash the analytics)."""
    if roster_id is None:
        return None
    rosters = getattr(season, "rosters", None) or []
    for r in rosters:
        if r.get("roster_id") == roster_id or r.get("roster_id") == int(roster_id or 0):
            return r.get("owner_id")
    return None


def summarize_league_faab(
    snapshot: PublicLeagueSnapshot,
    *,
    recent_limit: int = 25,
) -> dict[str, Any]:
    """Build the league FAAB analytics block.

    Returns a dict with the following shape::

        {
            "leagueBudget":          int,       # current-season setting
            "leagueAvgWinningBid":   float,
            "leagueMedianWinningBid": float,
            "totalBidsAnalyzed":     int,
            "positionBids":          {"QB": {avg, min, max, count}, ...},
            "tierBids":              {"tier1": {avg, min, max, count}, ...},
            "teamAggression":        {"<ownerId>": {totalSpent, avgBid, count, maxBid}, ...},
            "recentWins":            [{season, bid, position, addedNames, ownerId}, ...],
            "playerHistory":         {"<playerId>": [{season, bid, ownerId}, ...], ...},
        }
    """
    league_budget = _league_budget(snapshot)
    waivers = _walk_waivers(snapshot)

    all_bids: list[int] = []
    # Per-position shares are fractional whenever a transaction added
    # more than one player — see the split comment below.
    position_bids: dict[str, list[float]] = {}
    tier_bids: dict[str, list[int]] = {label: [] for label, _ in _TIER_BREAKPOINTS_PCT}
    team_totals: dict[str, dict[str, Any]] = {}
    player_history: dict[str, list[dict[str, Any]]] = {}
    recent: list[dict[str, Any]] = []

    # Sort newest-first for the recentWins slice.
    waivers_recent_first = sorted(waivers, key=lambda tx: -int(tx.get("createdAt") or 0))

    for tx in waivers:
        raw_bid = int(tx.get("bid") or 0)
        season_budget = int(tx.get("seasonBudget") or league_budget)
        # Every AGGREGATE below is budget-normalized, because pooling raw
        # dollars across seasons with different budgets compares fractions
        # of different wholes (W11-F001). The RAW figure is preserved for
        # ``recentWins`` and ``playerHistory``, which are records of what
        # actually happened in a given season and would be falsified by
        # rescaling.
        bid = _normalize_bid(raw_bid, season_budget, league_budget)
        owner_id = tx.get("ownerId")
        if raw_bid > 0:
            all_bids.append(bid)
            tier_bids[_tier_for_bid(bid, league_budget)].append(bid)

        # Per-position bid attribution.  Multi-add transactions split
        # the bid evenly across each added player's position so a
        # multi-add doesn't double-count.  Most adds are 1-player.
        #
        # The split is stored at FULL precision and rounded only for
        # display in ``_stats_block``.  Rounding each share on the way
        # in made a 3-add $10 bid contribute 3 + 3 + 3 = $9, so every
        # multi-add quietly leaked money out of the position averages
        # the FAAB recommender calibrates against.
        adds = tx.get("adds") or {}
        n_added = max(1, len(adds))
        per_player_bid = bid / n_added if bid > 0 else 0.0
        for pid in adds.keys():
            pos = _player_position(snapshot, str(pid))
            if pos and bid > 0:
                position_bids.setdefault(pos, []).append(per_player_bid)
            # Player history: every add (including FA pickups @ 0)
            # gets a row so the UI can show "this player has been
            # added X times historically".
            player_history.setdefault(str(pid), []).append(
                {
                    "season": tx.get("season"),
                    # RAW, with the budget it was placed under. "$223 in
                    # 2023" is a true statement about that season; rescaling
                    # it would falsify a record the UI presents as history.
                    # The aggregates above are the normalized ones.
                    "bid": raw_bid,
                    "seasonBudget": season_budget,
                    "normalizedBid": round(bid, 2),
                    "ownerId": owner_id,
                    "type": tx.get("type"),
                }
            )

        # Team aggression aggregates ALL spending (zero-bid FA
        # pickups don't bump avgBid but DO bump count, telling the
        # recommender "this owner pickup-shops a lot").
        if owner_id:
            entry = team_totals.setdefault(
                str(owner_id),
                {"totalSpent": 0, "winningCount": 0, "totalCount": 0, "maxBid": 0},
            )
            entry["totalCount"] += 1
            if bid > 0:
                entry["totalSpent"] += bid
                entry["winningCount"] += 1
                entry["maxBid"] = max(entry["maxBid"], bid)

    # Finalize team aggression: derive avgBid from totalSpent /
    # winningCount (only winning bids count towards the average).
    team_aggression: dict[str, dict[str, Any]] = {}
    for oid, e in team_totals.items():
        win_count = e["winningCount"]
        team_aggression[oid] = {
            "totalSpent": round(e["totalSpent"], 2),
            "avgBid": (round(e["totalSpent"] / win_count, 2) if win_count > 0 else 0.0),
            "winningCount": win_count,
            "totalCount": e["totalCount"],
            "maxBid": e["maxBid"],
        }

    # Recent wins: first N winning bids (skip zero-bid FA pickups
    # because they're noisy on the timeline).
    for tx in waivers_recent_first:
        if tx.get("bid", 0) <= 0:
            continue
        adds = tx.get("adds") or {}
        added_names: list[str] = []
        first_pos: str | None = None
        for pid in adds.keys():
            added_names.append(_player_name(snapshot, str(pid)))
            if first_pos is None:
                first_pos = _player_position(snapshot, str(pid))
        recent.append(
            {
                "season": tx.get("season"),
                "bid": tx.get("bid"),
                "position": first_pos,
                "addedNames": added_names,
                "ownerId": tx.get("ownerId"),
                "createdAt": tx.get("createdAt"),
            }
        )
        if len(recent) >= recent_limit:
            break

    return {
        "leagueBudget": league_budget,
        # Every aggregate below (leagueAvg/Median, positionBids, tierBids,
        # teamAggression) is expressed in CURRENT-season dollars after
        # normalizing each historical bid by the budget it was placed
        # under. ``recentWins`` and ``playerHistory`` keep the raw figures,
        # each carrying its own ``seasonBudget``. Stamped so a consumer can
        # tell which it is holding rather than having to know.
        "budgetNormalized": True,
        "seasonBudgets": {
            str(s.season): _season_budget(s) for s in getattr(snapshot, "seasons", []) or []
        },
        "leagueAvgWinningBid": (round(statistics.fmean(all_bids), 2) if all_bids else 0.0),
        "leagueMedianWinningBid": (
            round(float(statistics.median(all_bids)), 2) if all_bids else 0.0
        ),
        "totalBidsAnalyzed": len(all_bids),
        "positionBids": {pos: _stats_block(vals) for pos, vals in position_bids.items()},
        "tierBids": {label: _stats_block(vals) for label, vals in tier_bids.items()},
        "teamAggression": team_aggression,
        "recentWins": recent,
        "playerHistory": player_history,
    }


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Public-contract section builder.  Returns the same payload
    ``summarize_league_faab`` returns; kept as a thin wrapper so
    the section registry can call ``build_section`` uniformly with
    every other section."""
    return summarize_league_faab(snapshot)
