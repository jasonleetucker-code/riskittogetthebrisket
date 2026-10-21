"""Manager Intelligence Batch C — league-wide opponent scouting.

For ONE Sleeper league, a scouting row for every team in it: who manages it
(current owners only), what the roster holds and how strong it is by
position on the canonical board, the draft capital it holds, how active it
has been in the window, and its trade tendencies — plus each team's position
in the league by roster value.  Workstream:
``docs/intel/MANAGER_INTELLIGENCE_WORKSTREAM.md`` → "Batch C".

Nothing here is a second pipeline.  It reads ONE league through the SAME
machinery as the per-manager activity lookup and folds it per roster:

* Sleeper HTTP — ``src/public_league/sleeper_client`` classified fetchers,
  through ``manager_activity._budgeted`` (the per-request call budget and the
  per-(league, week) transaction memo, so a week already read for a manager
  lookup is free here and vice versa);
* league base read (rosters, users, drafts, one ``/traded_picks``) —
  ``manager_activity._read_league_base``; weeks + draft picks —
  ``manager_activity._read_league_activity``; coverage —
  ``manager_activity._league_coverage``;
* per-team trades / acquisitions / feed — ``manager_activity._Assembler`` over
  a per-roster view of the one read (attribution rules unchanged);
* draft capital — ``manager_trade_intel.league_draft_capital`` (the canonical
  ``picks.build_pick_ownership`` fold; unknown is ``None``, never "no picks");
* tendencies — ``manager_trade_intel.trade_tendencies`` (counts with samples)
  for external leagues; for OUR registry leagues the existing Manager Scout
  profile (``manager_scout.cached_manager_scout``) is attached instead and
  nothing is re-derived;
* values — ``manager_activity._Pricer`` (``build_player_index`` over the live
  contract; generic-grade picks).  An unpriced player is ``value: None`` +
  ``valueReason`` and is COUNTED beside a priced-only total — never summed
  as 0.

Values are the canonical board's, a Superflex / TE-premium board, so roster
value totals and the league ranks over them are published only for a
Superflex league (the Batch A posture); any other format keeps its per-player
values and counts, with ``value: None`` + ``canonical_board_is_superflex`` on
every total and rank.

Privacy: rows are the league's CURRENT rosters.  A row carries its current
owner's Sleeper user id (the same id the private page already receives for a
looked-up manager) and display name; former members appear nowhere — the
attached Manager Scout block is the current member's own profile (whose
partner rows already null former members' ids behind the opaque
``managerKey``), and only a COUNT of former members with history is
published.  Trade sides and creators (which can name a former owner through
a recorded hand-off) are not served — this view publishes counts.

Bounded: one league per request; ``LEAGUE_CALL_BUDGET`` Sleeper calls; one
league + users + rosters + drafts + traded_picks fetch; ``budgetExhausted``
and per-kind coverage states say when the answer is incomplete.
"""

from __future__ import annotations

import threading
import time
from collections import Counter
from typing import Any, Callable

from src.intel import manager_activity as ma
from src.intel import manager_portfolio as mp
from src.intel import manager_trade_intel as mti
from src.public_league import sleeper_client

Fetch = Callable[..., tuple[str, Any]]
ScoutProvider = Callable[..., Any]

#: Sleeper calls one league scouting request may spend: league, rosters,
#: users, drafts, traded picks, up to 19 transaction legs and each live or
#: complete draft's picks.  A memo hit is free.
LEAGUE_CALL_BUDGET = 80
PAYLOAD_TTL_SECONDS = 10 * 60
_PAYLOAD_MAX_ENTRIES = 64

#: Display order of position groups; anything else follows alphabetically.
POSITION_ORDER = ("QB", "RB", "WR", "TE", "K", "DEF", "DL", "LB", "DB")

TOP_PLAYERS_N = 5

VALUE_REASON_NOT_SUPERFLEX = "canonical_board_is_superflex"
VALUE_REASON_NO_BOARD = "board_unavailable"


class _LeagueWide(ma._League):  # noqa: SLF001 — the activity lookup's league context
    """The league read once for EVERY roster: the base read asks for traded
    picks only when "the manager" holds a roster, so here every roster is."""

    def __init__(self, league: dict[str, Any]) -> None:
        super().__init__(league, "")

    def manager_roster_ids(self) -> set[int]:
        return {r for r in (ma._int(x.get("roster_id")) for x in self.rosters) if r is not None}


def _roster_view(base: ma._League, roster_id: int, owner_id: str | None) -> ma._League:
    """One roster's view of the shared read: same rosters, users, drafts,
    transactions and traded picks; "the manager" is this roster's current
    owner, and the managed roster is exactly this one."""
    view = ma._League.__new__(ma._League)
    view.__dict__.update(base.__dict__)
    view.user_id = owner_id or ""
    view._mine = {roster_id}
    return view


# ── roster summary ──────────────────────────────────────────────────────


def _position_key(position: str | None) -> str:
    return (position or "UNKNOWN").upper()


def _position_sort(position: str) -> tuple[int, str]:
    try:
        return (POSITION_ORDER.index(position), position)
    except ValueError:
        return (len(POSITION_ORDER), position)


def _roster_summary(
    roster: dict[str, Any], pricer: ma._Pricer, league_raw: dict[str, Any]
) -> dict[str, Any]:
    """Slot counts, the roster's players (priced through the one pricer) and
    per-position strength.  Totals add PRICED players; the unpriced are
    counted beside them (an unpriced player is not a 0)."""
    slots = mp._slot_assets(roster)  # noqa: SLF001 — canonical slot rule
    slot_counts = Counter(slot for _pid, slot in slots)
    players: list[dict[str, Any]] = []
    for pid, slot in slots:
        p = pricer.player(pid)
        players.append(
            {
                "playerId": pid,
                "name": p.get("name"),
                "position": p.get("position"),
                "team": p.get("team"),
                "age": p.get("age"),
                "isRookie": p.get("isRookie"),
                "slot": slot,
                # The board row name the Trade Calculator resolves the player
                # by (Batch D seeds); None when the board has no row for him.
                "boardName": p.get("boardName"),
                "value": p.get("value"),
                "rank": p.get("rank"),
                "valueReason": p.get("valueReason"),
            }
        )
    players.sort(
        key=lambda p: (
            # Unpriced players sort after every priced one (an ORDER key,
            # never a published value).
            (1, 0) if p["value"] is None else (0, -p["value"]),
            p["name"] or p["playerId"],
        )
    )
    by_position: dict[str, dict[str, Any]] = {}
    for p in players:
        g = by_position.setdefault(
            _position_key(p["position"]),
            {"count": 0, "pricedCount": 0, "unpricedCount": 0, "pricedValue": 0},
        )
        g["count"] += 1
        if p["value"] is None:
            g["unpricedCount"] += 1
        else:
            g["pricedCount"] += 1
            g["pricedValue"] += int(p["value"])
    for g in by_position.values():
        if not g["pricedCount"]:
            g["pricedValue"] = None  # holds players here, none priced: no total
    priced = [p for p in players if p["value"] is not None]
    unpriced = [p for p in players if p["value"] is None]
    spots = len([s for s in (league_raw.get("roster_positions") or []) if s]) or None
    return {
        "playerCount": len(players),
        "rosterSpots": spots,
        "starters": slot_counts.get("starter", 0),
        "bench": slot_counts.get("bench", 0),
        "taxi": slot_counts.get("taxi", 0),
        "reserve": slot_counts.get("reserve", 0),
        "pricedCount": len(priced),
        "unpricedCount": len(unpriced),
        "unpricedReasons": dict(sorted(Counter(p["valueReason"] for p in unpriced).items())),
        # An empty roster genuinely holds 0; a roster of only unpriced players
        # has no total to state.
        "pricedValue": (
            sum(int(p["value"]) for p in priced) if priced else (0 if not players else None)
        ),
        "byPosition": {k: by_position[k] for k in sorted(by_position, key=_position_sort)},
        "topPlayers": [
            {k: p[k] for k in ("playerId", "name", "position", "value", "rank")}
            for p in priced[:TOP_PLAYERS_N]
        ],
        "players": players,
    }


def _competition_ranks(values: dict[Any, int | None]) -> dict[Any, int | None]:
    """1-based competition ranks (ties share a rank) over the non-``None``
    values, highest first; ``None`` values are unranked (never last)."""
    ranked = sorted((v for v in values.values() if v is not None), reverse=True)
    out: dict[Any, int | None] = {}
    for key, v in values.items():
        out[key] = None if v is None else ranked.index(v) + 1
    return out


def _apply_value_ranks(rows: list[dict[str, Any]], *, comparable_reason: str | None) -> dict:
    """Stamp ``valueRank`` (roster) and per-position ranks on each row, or
    withhold every total and rank with the reason."""
    positions = sorted(
        {pos for r in rows if r["roster"] for pos in r["roster"]["byPosition"]},
        key=_position_sort,
    )
    if comparable_reason is not None:
        for r in rows:
            roster = r["roster"]
            if roster is None:
                continue
            roster["pricedValue"] = None
            roster["valueNote"] = comparable_reason
            for g in roster["byPosition"].values():
                g["pricedValue"] = None
                g["rank"] = None
            r["valueRank"] = None
        return {"rankedRosters": 0, "positions": positions, "withheld": comparable_reason}

    totals = {r["rosterId"]: (r["roster"] or {}).get("pricedValue") for r in rows}
    ranks = _competition_ranks(totals)
    for r in rows:
        r["valueRank"] = ranks.get(r["rosterId"])
        if r["roster"] is not None:
            r["roster"]["valueNote"] = None
    for pos in positions:
        per = {}
        for r in rows:
            if r["roster"] is None:
                per[r["rosterId"]] = None
                continue
            g = r["roster"]["byPosition"].get(pos)
            # Observed: this roster holds no one at the position.
            per[r["rosterId"]] = 0 if g is None else g["pricedValue"]
        pos_ranks = _competition_ranks(per)
        for r in rows:
            g = (r["roster"] or {}).get("byPosition", {}).get(pos)
            if g is not None:
                g["rank"] = pos_ranks.get(r["rosterId"])
    return {
        "rankedRosters": sum(1 for v in totals.values() if v is not None),
        "positions": positions,
        "withheld": None,
    }


# ── activity counts ─────────────────────────────────────────────────────


def _activity_counts(
    feed: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    acquisitions: list[dict[str, Any]],
    all_feed: list[dict[str, Any]],
) -> dict[str, Any]:
    """Counts over the windowed stream.  An event whose attribution is
    uncertain (possibly the roster's previous owner) is counted apart, not
    credited to this team."""
    certain = [f for f in feed if not (f.get("attribution") or {}).get("uncertain")]
    kinds = Counter(f["kind"] for f in certain)
    faab = [
        f["faabBid"] for f in certain if f["kind"] == "waiver" and isinstance(f["faabBid"], int)
    ]
    dated = [f["occurredAt"] for f in all_feed if f.get("occurredAt") is not None]
    return {
        "trades": sum(1 for t in trades if not (t.get("attribution") or {}).get("uncertain")),
        "waiverClaims": kinds.get("waiver", 0),
        "freeAgentAdds": kinds.get("free_agent", 0),
        "dropsOnly": kinds.get("drop", 0),
        "commissionerMoves": kinds.get("commissioner", 0),
        "draftPicks": kinds.get("draft", 0),
        "playersAdded": len(acquisitions),
        "playersAddedByMethod": dict(sorted(Counter(a["method"] for a in acquisitions).items())),
        "playersDropped": sum(
            len(f["dropped"]) for f in certain if f["kind"] in ("waiver", "free_agent", "drop")
        ),
        "faabSpent": sum(faab) if faab else None,
        "faabClaims": len(faab),
        "uncertainAttribution": len(feed) - len(certain),
        "events": len(certain),
        # Over everything read this season (not only the window).
        "lastActivityAt": max(dated) if dated else None,
    }


# ── registry leagues: Manager Scout ─────────────────────────────────────


def _registry_config(league_id: str) -> Any:
    try:
        from src.api import league_registry  # noqa: PLC0415

        key = league_registry.league_key_for_sleeper_id(league_id)
        return league_registry.get_league_by_key(key) if key else None
    except Exception:  # noqa: BLE001 — registry unreadable: treated as external
        return None


def _default_scout_provider(cfg: Any, current_teams: list[dict[str, Any]], contract: Any) -> Any:
    from src.intel import manager_scout, manager_scout_api  # noqa: PLC0415

    # Today's values only from a board loaded for THIS league — the same gate
    # GET /api/manager-scout applies.
    board = contract if manager_scout_api._current_teams(contract, cfg.key) else None  # noqa: SLF001
    return manager_scout.cached_manager_scout(
        cfg.key, league_cfg=cfg, current_teams=current_teams, contract=board
    )


def _scout_block(
    cfg: Any,
    rows: list[dict[str, Any]],
    contract: Any,
    provider: ScoutProvider,
) -> dict[str, Any]:
    """Attach each current member's Manager Scout profile; publish only a
    COUNT of former members (their history stays behind the scout page)."""
    teams = [
        {"ownerId": r["ownerUserId"], "name": r["displayName"], "roster_id": r["rosterId"]}
        for r in rows
        if r["ownerUserId"]
    ]
    try:
        payload = provider(cfg, teams, contract)
    except Exception:  # noqa: BLE001 — a store fault is an unavailable state
        payload = None
    if not isinstance(payload, dict):
        for r in rows:
            r["scout"] = None
        return {"state": "unavailable", "reason": "manager_scout_unreadable", "leagueKey": cfg.key}
    by_owner = {
        str(m.get("ownerId")): m
        for m in payload.get("managers") or []
        if m.get("currentMember") and m.get("ownerId")
    }
    for r in rows:
        m = by_owner.get(str(r["ownerUserId"] or ""))
        r["scout"] = (
            {
                k: m.get(k)
                for k in (
                    "managerKey",
                    "tradeTendencies",
                    "waiverTendencies",
                    "faabTendencies",
                )
            }
            if m
            else None
        )
    former = sum(1 for m in payload.get("managers") or [] if not m.get("currentMember"))
    return {
        "state": "attached",
        "leagueKey": cfg.key,
        "methodVersion": payload.get("methodVersion"),
        "generatedAt": payload.get("generatedAt"),
        "sources": payload.get("sources"),
        "lineupTendencies": (payload.get("sources") or {}).get("lineup"),
        "formerMembersWithHistory": former,
    }


# ── builder ─────────────────────────────────────────────────────────────


#: Why the league-scoped trade tools (Analyze Trade, the Package Builder) are
#: not offered for a league.  The generic calculator seed is always offered.
TRADE_TOOLS_EXTERNAL_LEAGUE = "external_league"
TRADE_TOOLS_ROSTERS_NOT_LOADED = "league_rosters_not_loaded"


def _trade_tools_block(cfg: Any, contract: Any) -> dict[str, Any]:
    """Batch D: may this league seed the LEAGUE-SCOPED trade tools?

    Only a registry league whose rosters the site has loaded — the same
    league-match gate ``GET /api/manager-scout`` applies
    (``manager_scout_api._current_teams``), because Analyze Trade and the
    Package Builder run against the loaded contract's ``sleeper.teams`` and
    refuse any other league.  Every league may still seed the generic Trade
    Calculator (players and generic picks on the canonical board).  The
    ``packageModel`` receipt is the ACTIVE model the calculator values under,
    carried into every seeded link so one receipt spans the surfaces.
    """
    from src.intel import manager_scout_api  # noqa: PLC0415
    from src.valuation_math import package_model  # noqa: PLC0415

    if cfg is None:
        scoped, reason = False, TRADE_TOOLS_EXTERNAL_LEAGUE
    elif manager_scout_api._current_teams(contract, cfg.key):  # noqa: SLF001
        scoped, reason = True, None
    else:
        scoped, reason = False, TRADE_TOOLS_ROSTERS_NOT_LOADED
    return {
        "leagueScoped": scoped,
        "leagueKey": getattr(cfg, "key", None) if scoped else None,
        "reason": reason,
        "packageModel": package_model.receipt(),
    }


def _fail(status: str, league_id: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, "query": {"leagueId": league_id}, **extra}


def build_league_scouting(
    league_id: str,
    *,
    contract: dict[str, Any] | None,
    window: str = ma.DEFAULT_WINDOW,
    call_budget: int = LEAGUE_CALL_BUDGET,
    workers: int = ma.DEFAULT_WORKERS,
    fetch_league: Fetch = sleeper_client.fetch_league_classified,
    fetch_rosters: Fetch = sleeper_client.fetch_rosters_classified,
    fetch_users: Fetch = sleeper_client.fetch_league_users_classified,
    fetch_transactions: Fetch = sleeper_client.fetch_transactions_classified,
    fetch_drafts: Fetch = sleeper_client.fetch_drafts_classified,
    fetch_draft_picks: Fetch = sleeper_client.fetch_draft_picks_classified,
    fetch_traded_picks: Fetch = sleeper_client.fetch_traded_picks_classified,
    fetch_state: Callable[[], Any] = sleeper_client.fetch_nfl_state,
    fetch_directory: Callable[[], Any] = sleeper_client.fetch_nfl_players,
    registry_config: Callable[[str], Any] = _registry_config,
    scout_provider: ScoutProvider = _default_scout_provider,
    now: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """The league scouting payload for one Sleeper league id.

    ``status``: ``ok`` / ``partial`` (some data kind not fully read) /
    ``not_found`` / ``rate_limited`` / ``upstream_unavailable``.  Never raises
    for an upstream failure; never fabricates an unread week or roster.
    """
    league_id = str(league_id).strip()
    if window not in ma.WINDOWS:
        window = ma.DEFAULT_WINDOW
    t_now = now()
    budget = ma._Budget(call_budget)  # noqa: SLF001

    kind, raw = ma._budgeted(  # noqa: SLF001
        fetch_league,
        (league_id,),
        budget=budget,
        memo_key=("league", league_id),
        ttl=ma.WEEK_TTL_CURRENT_SECONDS,
        now=t_now,
    )
    if kind != sleeper_client.FETCH_OK:
        return _fail(
            {
                sleeper_client.FETCH_NOT_FOUND: mp.STATUS_NOT_FOUND,
                sleeper_client.FETCH_RATE_LIMITED: mp.STATUS_RATE_LIMITED,
            }.get(kind, mp.STATUS_UPSTREAM_UNAVAILABLE),
            league_id,
        )

    state = fetch_state() or {}
    current_season = str(
        state.get("league_season") or state.get("season") or time.gmtime(t_now).tm_year
    )
    lg = _LeagueWide(raw)
    season = lg.season or current_season
    want_picks = season == current_season

    ma._read_league_base(  # noqa: SLF001
        lg,
        budget=budget,
        fetch_rosters=fetch_rosters,
        fetch_users=fetch_users,
        fetch_drafts=fetch_drafts,
        now=t_now,
        fetch_traded_picks=fetch_traded_picks if want_picks else None,
    )
    if lg.rosters_state != ma.COV_COMPLETE:
        # Without the rosters there is no team to scout.
        return _fail(
            mp.STATUS_RATE_LIMITED
            if lg.rosters_state == ma.COV_RATE_LIMITED
            else mp.STATUS_UPSTREAM_UNAVAILABLE,
            league_id,
            league={**lg.entry(), "scope": mp.league_scope(raw)},
        )

    legs, current_leg = ma._legs(state, season, current_season)  # noqa: SLF001
    ma._read_league_activity(  # noqa: SLF001
        [lg],
        legs,
        current_leg,
        budget=budget,
        fetch_transactions=fetch_transactions,
        fetch_draft_picks=fetch_draft_picks,
        now=t_now,
        workers=workers,
    )

    directory = fetch_directory() or {}
    pricer = ma._Pricer(contract, directory)  # noqa: SLF001

    days = ma.WINDOWS[window]
    window_applied = window
    if season != current_season:
        days = None
        window_applied = "season"
    start = (t_now - days * 86400) * 1000 if days is not None else None

    def _in_window(item: dict[str, Any]) -> bool:
        if start is None:
            return True
        occurred = item.get("occurredAt")
        if occurred is not None:
            return occurred >= start
        bound = (item.get("occurredBound") or {}).get("notAfter")
        return bound is not None and bound >= start

    cfg = registry_config(league_id)
    calendar_year = time.gmtime(t_now).tm_year
    observed_at = mti.observed_at_iso(t_now)
    picks_state = ma._traded_picks_state(lg, want_picks)  # noqa: SLF001

    rows: list[dict[str, Any]] = []
    rosters = sorted(
        (r for r in lg.rosters if ma._int(r.get("roster_id")) is not None),
        key=lambda r: ma._int(r.get("roster_id")),
    )
    for roster in rosters:
        rid = ma._int(roster.get("roster_id"))
        owner = lg.current_owner(rid)
        view = _roster_view(lg, rid, owner)
        asm = ma._Assembler(owner or "", pricer)  # noqa: SLF001
        asm.league(view)
        trades = [t for t in asm.trades if _in_window(t)]
        acquisitions = [a for a in asm.acquisitions if _in_window(a)]
        all_feed = list(asm.feed.values())
        feed = [f for f in all_feed if _in_window(f)]
        user = lg.users.get(owner or "") or {}
        metadata = user.get("metadata") if isinstance(user.get("metadata"), dict) else {}
        if want_picks:
            capital = mti.league_draft_capital(
                view,
                pricer,
                traded_picks=lg.traded_picks,
                coverage=picks_state,
                calendar_year=calendar_year,
                observed_at=observed_at,
                pick_used=ma._pick_used,  # noqa: SLF001
            )
        else:
            capital = {
                "available": False,
                "reason": mti.DC_REASON_EARLIER_SEASON,
                "picks": None,
                "counts": None,
                "pricedValue": None,
            }
        rows.append(
            {
                "rosterId": rid,
                # A CURRENT owner's id only — the private page already receives
                # it for a looked-up manager.  An orphaned roster has none.
                "ownerUserId": owner,
                "displayName": lg.display_name(owner),
                "teamName": (metadata.get("team_name") or None) if owner else None,
                "orphan": owner is None,
                "coOwnerCount": len(lg.co_owners(rid)),
                "record": mp._record(roster),  # noqa: SLF001
                "roster": _roster_summary(roster, pricer, raw),
                "draftCapital": capital,
                "activity": _activity_counts(feed, trades, acquisitions, all_feed),
                "tendencies": None
                if cfg is not None
                else mti.trade_tendencies(trades, window=window_applied, season=season),
                "tendenciesSource": "manager_scout" if cfg is not None else "trade_stream",
                "excluded": dict(asm.excluded),
            }
        )

    if not pricer.has_board:
        comparable_reason: str | None = VALUE_REASON_NO_BOARD
    elif lg.format.get("superflex") is not True:
        comparable_reason = VALUE_REASON_NOT_SUPERFLEX
    else:
        comparable_reason = None
    ranking = _apply_value_ranks(rows, comparable_reason=comparable_reason)

    scout = None
    if cfg is not None:
        scout = _scout_block(cfg, rows, contract, scout_provider)
    else:
        for r in rows:
            r["scout"] = None

    rows.sort(
        key=lambda r: (
            # Unranked rows sort last (an ORDER key, never a published rank).
            (1, 0) if r["valueRank"] is None else (0, r["valueRank"]),
            (r["displayName"] or "").lower(),
            r["rosterId"],
        )
    )

    cov = ma._league_coverage(lg, legs, want_picks)  # noqa: SLF001
    incomplete = cov.pop("incomplete") or not lg.users_read
    picks_priced = [
        r["draftCapital"].get("pricedValue")
        for r in rows
        if isinstance(r["draftCapital"].get("pricedValue"), int)
    ]
    return {
        "status": mp.STATUS_PARTIAL if incomplete else mp.STATUS_OK,
        "query": {"leagueId": league_id},
        "league": {
            **lg.entry(),
            "scope": mp.league_scope(raw),
            "status": raw.get("status") or None,
            "totalRosters": raw.get("total_rosters"),
            "registryLeague": cfg is not None,
            "registryKey": getattr(cfg, "key", None),
        },
        "season": season,
        "currentSeason": current_season,
        "window": window,
        "windowApplied": window_applied,
        "windowStart": int(start) if start is not None else None,
        "hasBoard": pricer.has_board,
        "managers": rows,
        "managerCount": len(rows),
        "ranking": {
            **ranking,
            "basis": "canonical board value (rankDerivedValue) of priced rostered players",
            "note": (
                "Ranks compare the league's rosters on the canonical board, a Superflex / "
                "TE-premium board. Totals add priced players only; unpriced players are "
                "counted beside them, never as 0."
            ),
        },
        "draftCapital": {
            "available": want_picks,
            "reason": None if want_picks else mti.DC_REASON_EARLIER_SEASON,
            "coverage": picks_state,
            "rostersWithPricedPicks": len(picks_priced),
            "valueNote": (
                "Pick values are the canonical board's at the generic season + round grade "
                "— no tier or slot is assumed."
            ),
        },
        "tendencies": {
            "source": "manager_scout" if cfg is not None else "trade_stream",
            "minSample": mti.TENDENCY_MIN_SAMPLE,
            "minSampleBasis": "PRIOR",
        },
        "scout": scout,
        "tradeTools": _trade_tools_block(cfg, contract),
        "coverage": {
            **cov,
            "legsRequested": legs,
            "budgetExhausted": budget.refused > 0,
            "callsSpent": budget.spent,
            "callBudget": budget.limit,
        },
        "valueBasis": {
            "field": "rankDerivedValue",
            "board": "canonical Superflex / TE-premium board",
            "note": (
                "Values are the canonical board's (a Superflex / TE-premium board). Roster "
                "totals and league ranks are published only for a Superflex league."
            ),
        },
        "fetchedAt": int(t_now * 1000),
    }


# ── per-process payload memo ────────────────────────────────────────────

_payload_cache: dict[tuple[str, ...], tuple[float, dict[str, Any]]] = {}
_payload_lock = threading.Lock()


def cached_league_scouting(
    league_id: str,
    *,
    contract: dict[str, Any] | None,
    window: str = ma.DEFAULT_WINDOW,
    now: Callable[[], float] = time.time,
    **kwargs: Any,
) -> dict[str, Any]:
    """:func:`build_league_scouting` memoised for ``PAYLOAD_TTL_SECONDS``;
    only ``ok`` answers are memoised so a partial or failed one retries."""
    key = (str(league_id).strip(), window)
    t = now()
    with _payload_lock:
        hit = _payload_cache.get(key)
        if hit and t - hit[0] < PAYLOAD_TTL_SECONDS:
            return {**hit[1], "cached": True}
    payload = build_league_scouting(league_id, contract=contract, window=window, now=now, **kwargs)
    if payload.get("status") == mp.STATUS_OK:
        with _payload_lock:
            mp.drop_expired_payloads_locked(_payload_cache, t, PAYLOAD_TTL_SECONDS)
            if len(_payload_cache) >= _PAYLOAD_MAX_ENTRIES:
                oldest = min(_payload_cache, key=lambda k: _payload_cache[k][0])
                _payload_cache.pop(oldest, None)
            _payload_cache[key] = (t, payload)
    return {**payload, "cached": False}


def reset_cache() -> None:
    with _payload_lock:
        _payload_cache.clear()


__all__ = [
    "LEAGUE_CALL_BUDGET",
    "build_league_scouting",
    "cached_league_scouting",
    "reset_cache",
]
