"""Adapter between the FAAB endpoint and the FAAB engine.

All the model lives in ``src/trade/faab_engine.py``.  This module's
only job is to translate the endpoint's loosely-typed inputs (Sleeper
team dicts, the league analytics block, trending counts, the KTC crowd
map) into the engine's dataclasses, and to translate the engine's
answer back into the response shape ``/waivers`` already consumes.

What changed, and why
─────────────────────
The previous implementation WAS the model: it started from
``_compute_faab_bid`` (a pool-relative share of the budget with no
absolute value scale) and then multiplied that number by up to five
independent factors — a value-gain modifier (x0.5-1.8), a Sleeper
trending kicker (x1.0-1.2), a league-historical position blend, a
budget-environment scale (x0.6-1.6) and a rival-contention raise.
Three problems, all fixed by moving the model into the engine:

1.  **The stacked multipliers compounded.**  Nothing bounded their
    product, so a trending player at a position the league bids hot
    could be marked up ~3.5x off a baseline that was already 21% of
    budget for any top-of-wire player.

2.  **They double-counted.**  "This player is in demand" entered
    through the trending kicker, again through the league-historical
    position blend, again through the budget-environment scale, and
    again through rival contention — four readings of one signal, each
    applied multiplicatively.  In the engine, demand enters exactly
    once, in the market layer, where it belongs.

3.  **They moved the wrong number.**  Every one of those factors
    adjusted the BID.  Positional scarcity, dynasty outlook and age are
    already inside the canonical 1-9999 value, and market demand
    belongs to the clearing price, not to what the player is worth.
    The engine keeps the objective ceiling and the recommended bid as
    separate quantities so a factor can only touch the one it actually
    describes.

Signals that survive, and where they now go
───────────────────────────────────────────
*  Sleeper trending / KTC crowd bid % — now **demand evidence** that
   nudges rival engagement in the market layer.  They can raise the
   price you must pay; they can no longer raise what the player is
   worth.
*  League historical bids — now fitted priors in
   ``src/trade/faab_history.py``, applied per-manager as an aggression
   factor on rival bids.
*  Drop side — now surplus-over-replacement inside the team ceiling.

``recommend_faab`` keeps its keyword-only signature and its response
keys so existing callers and tests keep working.
"""

from __future__ import annotations

from typing import Any, Sequence

from src.trade import faab_engine as engine

__all__ = ["recommend_faab", "compute_confidence", "build_rivals"]


# Retained for the endpoint's post-hoc factor append (it adds a
# "Rival contention: missing" row AFTER the engine has run and needs to
# recompute the bucket honestly).
def compute_confidence(factors: Sequence[Any]) -> str:
    """Weighted realized-share confidence bucket over factor rows.

    Accepts engine factor dicts or anything exposing ``weight`` /
    ``missing``, so callers that append rows after the fact can keep
    the reported confidence honest about the full factor set.
    """
    cfg = engine.FaabConfig()
    total = 0.0
    realized = 0.0
    for f in factors:
        if isinstance(f, dict):
            try:
                weight = float(f.get("weight") or 0.0)
            except (TypeError, ValueError):
                continue
            missing = bool(f.get("missing"))
        else:
            weight = float(getattr(f, "weight", 0.0) or 0.0)
            missing = bool(getattr(f, "missing", False))
        total += weight
        if not missing:
            realized += weight
    share = (realized / total) if total > 0 else 0.0
    if share >= cfg.num("confidence", "highThreshold", 0.85):
        return "high"
    if share >= cfg.num("confidence", "mediumThreshold", 0.55):
        return "medium"
    return "low"


def _need_level(
    position: str | None,
    roster_players: Sequence[str],
    asset_pool: Any,
    *,
    anchors: engine.Anchors | None = None,
    starters: dict[str, Any] | None = None,
    roster_index: dict[str, tuple[float, str]] | None = None,
) -> str:
    """Classify one roster's need at ``position``.

    Prefers the engine's startable-depth classifier, which needs the
    roster's player VALUES and the league's lineup slots.  Falls back
    to ``src.trade.suggestions.analyze_roster`` only when those are
    unavailable.

    The fallback is second choice for a measured reason: on this
    platform's real 58-man best-ball rosters ``analyze_roster``
    returns ``surplus`` for 68 of 84 team/position pairs and ``need``
    exactly once, so the resulting factor is very nearly a constant
    and cannot discriminate between a team with a lineup hole and one
    with four spare starters.  It answers a trade-surplus question,
    not a start-this-week question.
    """
    if not position or not roster_players:
        return "neutral"

    if anchors is not None and starters and roster_index:
        target_family = engine.position_family(position)
        at_position = [
            value
            for value, pos in (
                roster_index.get(str(name).strip().lower(), (None, "")) for name in roster_players
            )
            if value is not None and engine.position_family(pos) == target_family
        ]
        if at_position:
            return engine.classify_need(at_position, position, starters, anchors)

    if asset_pool is None:
        return "neutral"
    try:
        from src.trade.suggestions import analyze_roster  # noqa: PLC0415

        analysis = analyze_roster([str(n) for n in roster_players], asset_pool)
    except Exception:  # noqa: BLE001 — one bad roster must not kill the estimate
        return "neutral"
    pos = str(position).upper()
    if pos in getattr(analysis, "need_positions", ()) or ():
        return "need"
    if pos in getattr(analysis, "surplus_positions", ()) or ():
        return "surplus"
    return "neutral"


def _aggression_from_league_summary(
    league_summary: dict[str, Any] | None,
    owner_id: str,
) -> tuple[float, bool]:
    """``(factor, low_sample)`` from the live league-analytics block.

    Fallback for when no persisted bid-history snapshot exists yet
    (``scripts/fetch_faab_history.py`` has not run for this league).
    Same shape as the historical fit: an owner's average winning bid
    relative to the league median, clamped, and requiring a minimum
    sample before it is trusted at all.
    """
    if not isinstance(league_summary, dict):
        return 1.0, True
    entry = (league_summary.get("teamAggression") or {}).get(str(owner_id))
    if not isinstance(entry, dict):
        return 1.0, True
    cfg = engine.FaabConfig()
    min_sample = int(cfg.num("market", "minWinningBidsForAggression", 3))
    try:
        count = int(entry.get("winningCount") or 0)
    except (TypeError, ValueError):
        count = 0
    avg_bid = entry.get("avgBid")
    median = league_summary.get("leagueMedianWinningBid")
    if (
        count < min_sample
        or not isinstance(avg_bid, (int, float))
        or avg_bid <= 0
        or not isinstance(median, (int, float))
        or median <= 0
    ):
        return 1.0, True
    lo, hi = (cfg.section("market").get("aggressionClamp") or [0.5, 2.0])[:2]
    return max(float(lo), min(float(hi), float(avg_bid) / float(median))), False


def build_rivals(
    opponent_teams: Sequence[dict[str, Any]],
    *,
    position: str | None = None,
    asset_pool: Any = None,
    market_priors: Any = None,
    league_summary: dict[str, Any] | None = None,
    roster_size: int = 0,
    anchors: engine.Anchors | None = None,
    starters: dict[str, Any] | None = None,
    roster_index: dict[str, tuple[float, str]] | None = None,
) -> list[engine.RivalTeam]:
    """Translate Sleeper opponent dicts into engine rivals.

    A rival with no visible ``faabRemaining`` is passed through with
    ``faab_remaining=None``; the engine excludes those from the
    clearing math by policy, because an unverifiable rival who might
    be broke must never raise the user's bid.

    Aggression prefers the persisted bid-history fit (which keeps $0
    bids and so measures the real market), and falls back to the live
    league-analytics block when no snapshot exists.
    """
    from src.trade.faab_history import owner_aggression_factor  # noqa: PLC0415

    rivals: list[engine.RivalTeam] = []
    for team in opponent_teams or []:
        if not isinstance(team, dict):
            continue
        owner_id = str(team.get("ownerId") or "").strip()
        if not owner_id:
            continue
        remaining = team.get("faabRemaining")
        if not isinstance(remaining, int):
            remaining = None

        aggression, low_sample = (1.0, True)
        if market_priors is not None:
            aggression, low_sample = owner_aggression_factor(market_priors, owner_id)
        if low_sample:
            aggression, low_sample = _aggression_from_league_summary(league_summary, owner_id)

        players = team.get("players") or []
        open_spots = max(0, int(roster_size) - len(players)) if roster_size else 0

        rivals.append(
            engine.RivalTeam(
                owner_id=owner_id,
                name=str(team.get("name") or ""),
                faab_remaining=remaining,
                need_level=_need_level(
                    position,
                    players,
                    asset_pool,
                    anchors=anchors,
                    starters=starters,
                    roster_index=roster_index,
                ),
                aggression=aggression,
                low_sample=low_sample,
                open_roster_spots=open_spots,
            )
        )
    return rivals


def _demand_evidence_factors(
    sleeper_trending: dict[str, Any] | None,
    player_name: str | None,
) -> list[dict[str, Any]]:
    """Trending + crowd signals as REPORTED EVIDENCE, not multipliers.

    These describe how much the market wants a player.  They are shown
    so a user can see why competition is expected to be heavy, and they
    are already reflected in the market layer's demand term.  They no
    longer scale the bid directly — doing that on top of the market
    model would count the same demand twice.
    """
    rows: list[dict[str, Any]] = []

    count: int | None = None
    if isinstance(sleeper_trending, dict):
        try:
            count = int(sleeper_trending.get("count"))
        except (TypeError, ValueError):
            count = None
    if count is None:
        rows.append(
            {"label": "Trending adds", "contribution": "missing", "weight": 0.08, "missing": True}
        )
    else:
        rows.append(
            {
                "label": "Trending adds",
                "contribution": f"{count:,} adds in the last 24h",
                "weight": 0.08,
            }
        )

    return rows


def recommend_faab(
    *,
    add_player_value: float,
    drop_player_value: float = 0.0,
    add_player_position: str | None = None,
    add_player_name: str | None = None,
    drop_player_name: str | None = None,
    team_faab_remaining: int | None = None,
    league_faab_summary: dict[str, Any] | None = None,
    sleeper_trending: dict[str, Any] | None = None,
    league_budget: int = 100,
    top_value_in_pool: float | None = None,
    contention: dict[str, Any] | None = None,
    next_best_fa_value: float | None = None,
    # Engine inputs.  Every one is optional; missing inputs lower the
    # reported confidence rather than silently changing the answer.
    anchors: engine.Anchors | None = None,
    board_values: Sequence[float] | None = None,
    available_values: Sequence[float] | None = None,
    rivals: Sequence[engine.RivalTeam] = (),
    team_count: int = 12,
    starters_per_team: int = 20,
    current_week: int | None = None,
    playoff_week_start: int = 15,
    in_season: bool = True,
    open_roster_spots: int = 0,
    need_level: str = "neutral",
    competitive_status: str = "bubble",
    risk_posture: str = "balanced",
    faab_carries_over: bool = False,
    league_key: str = "",
    crowd: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend a FAAB bid for a single add/drop pair.

    Returns the engine payload plus the legacy keys ``conservative`` /
    ``standard`` / ``aggressive`` / ``max`` so existing consumers keep
    working.  ``standard`` is the recommended bid; ``max`` is now the
    MAX RATIONAL bid (bounded by both the player's worth and the
    team's balance) rather than simply the team's balance, which is
    the whole point of the redesign.
    """
    cfg = engine.FaabConfig()
    budget = max(1, int(league_budget or cfg.num("leagueRules", "defaultBudget", 100)))

    league = engine.LeagueContext(
        original_budget=budget,
        team_count=int(team_count or 12),
        starters_per_team=int(starters_per_team or 20),
        current_week=current_week,
        playoff_week_start=int(playoff_week_start or 15),
        in_season=bool(in_season),
        faab_carries_over=bool(faab_carries_over),
        league_key=str(league_key or ""),
        min_bid=int(cfg.num("leagueRules", "minBid", 0)),
        bid_increment=int(cfg.num("leagueRules", "bidIncrement", 1)),
        zero_bid_allowed=bool(cfg.get("leagueRules", "zeroBidAllowed", True)),
    )

    if anchors is None:
        anchors = engine.resolve_anchors(
            board_values or [],
            league,
            available_values=available_values,
            config=cfg,
        )

    team = engine.TeamContext(
        faab_remaining=team_faab_remaining,
        open_roster_spots=int(open_roster_spots or 0),
        need_level=str(need_level or "neutral"),
        competitive_status=str(competitive_status or "bubble"),
        risk_posture=str(risk_posture or cfg.get("bidPolicy", "defaultRiskPosture", "balanced")),
    )

    drop_value = float(drop_player_value or 0.0)
    # A drop VALUE without a drop NAME still means a drop is required —
    # the endpoint resolves the row but may not always pass the label,
    # and treating that as "no drop" would hand back a free-add bid for
    # a swap that costs the user a real player.
    drop_label = drop_player_name or ("your drop" if drop_value > 0 else None)

    player = engine.PlayerInput(
        name=str(add_player_name or ""),
        value=float(add_player_value or 0.0),
        position=add_player_position,
        drop_name=drop_label,
        drop_value=drop_value,
    )

    extra = _demand_evidence_factors(sleeper_trending, add_player_name)
    if league_faab_summary is None:
        extra.append(
            {
                "label": "League bid history",
                "contribution": "missing",
                "weight": 0.10,
                "missing": True,
            }
        )

    result = engine.recommend(
        player,
        league,
        team,
        anchors=anchors,
        rivals=rivals,
        config=cfg,
        extra_factors=extra,
        crowd=crowd,
    )

    bids = result["bids"]
    # Legacy keys — same names, better numbers.
    result["standard"] = bids["recommended"]
    result["conservative"] = bids["conservative"]
    result["aggressive"] = bids["aggressive"]
    result["max"] = bids["maxRational"]
    return result
