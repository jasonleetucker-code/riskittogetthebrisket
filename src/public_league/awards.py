"""Section: Awards + Award Races.

Catalog is split into two classes:
    * historical — finalized awards per completed season + across-the-window
      aggregates
    * live races — top-3 current-season leaderboards for awards where the
      race is interesting in flight

Every award exposes a machine-readable ``key``, a human label, a short
``description`` (the explanation shown on the public page) and a
``value`` payload that is either a number, a simple string, or an
object of derived display fields.  No raw private valuation or edge
signal ever appears in the public output — live-race tiebreakers can
*consult* private outputs internally but only ever emit derived,
public-safe values.

Award catalog:
    champion                 — winner of the finals
    runner_up                — loser of the finals
    top_seed                 — best regular-season seed
    regular_season_crown     — best regular-season record
    points_king              — most regular-season points
    points_black_hole        — most points ALLOWED
    toilet_bowl              — worst final playoff placement
    highest_single_week      — largest single-week score
    lowest_single_week       — smallest single-week score
    trader_of_the_year       — realized points gained via trades
    best_trade_of_the_year   — single-trade bake-off (historical only)
    waiver_king              — realized points gained via waivers/FA
    chaos_agent              — transaction chaos score
    most_active              — raw transaction volume
    pick_hoarder             — weighted draft stockpile
    silent_assassin          — win% in close games
    weekly_hammer            — weekly high-score finishes
    playoff_mvp              — playoff team points (+ top individual scorer)
    bad_beat                 — biggest "points in a loss" performance
    best_rebuild             — year-over-year improvement (finalized only)
    rivalry_of_the_year      — season-scoped rivalry_index peak
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import metrics
from .draft import _pick_ownership_map, pick_weight
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# Explanation strings exposed on every award card so the page never
# needs to hard-code copy.  Keep these short and human — the UI prints
# them verbatim beneath the winner.
AWARD_DESCRIPTIONS: dict[str, str] = {
    "champion": "Winner of the final playoff matchup.",
    "runner_up": "Lost in the final playoff matchup.",
    "top_seed": "Best regular-season seed after tiebreaks.",
    "regular_season_crown": "Best regular-season record.",
    "points_king": "Most regular-season points scored.",
    "points_black_hole": "Most regular-season points allowed.",
    "toilet_bowl": "Worst final finish in the consolation bracket.",
    "highest_single_week": "Largest single-week scoring explosion.",
    "lowest_single_week": "Smallest single-week score.",
    "trader_of_the_year": (
        "Realized post-trade fantasy points gained. Sums points acquired "
        "minus points sent away across every trade, weighted by the weeks "
        "played after the deal. Tiebreaks: playoff points gained, then a "
        "server-side asset-value delta."
    ),
    "best_trade_of_the_year": (
        "Best single trade by post-deal realized points for one side. "
        "Historical only — finalized after the season."
    ),
    "waiver_king": (
        "Realized points scored by your own waiver / FA pickups after they "
        "were added. Tiebreaks: FAAB efficiency, then count of useful adds."
    ),
    "chaos_agent": (
        "Chaos score. 3 points per trade, 1 per unique partner, 1 per asset "
        "moved, 1 per pick moved, 0.5 per waiver add."
    ),
    "most_active": "Total trades + waivers + drops + free-agent adds.",
    "pick_hoarder": (
        "Weighted draft stockpile. 1st round = 4, 2nd = 3, 3rd = 2, 4th+ = 1."
    ),
    "silent_assassin": (
        "Win% in games decided by 10 points or fewer (4+ eligible games)."
    ),
    "weekly_hammer": "Count of weekly high-score finishes.",
    "playoff_mvp": (
        "Highest playoff VORP (Value Over Replacement Player) — the player "
        "who outscored his position's playoff replacement by the most while "
        "in a starting lineup."
    ),
    "bad_beat": "Biggest single 'points in a loss' performance.",
    "best_rebuild": (
        "Year-over-year improvement. 40% points-rank jump + 30% record-rank "
        "jump + 20% extra weighted stockpile + 10% more rostered rookies."
    ),
    "rivalry_of_the_year": (
        "Season's nastiest head-to-head ranked by rivalry index, boosted by "
        "playoff meetings."
    ),
    # ── Manager awards ──
    "top_offense": (
        "Most regular-season points produced by offensive starters "
        "(QB / RB / WR / TE / K) — bench points excluded."
    ),
    "top_defense": (
        "Most regular-season points produced by defensive starters "
        "(DL / LB / DB / DEF) — bench points excluded."
    ),
    "manager_of_the_year": (
        "Composite manager rating: 60% regular-season win%, 40% "
        "regular-season points scored (normalized to league high)."
    ),
    # ── Player awards ──
    "top_qb": "Top QB by total starter-only points scored in the regular season.",
    "top_rb": "Top RB by total starter-only points scored in the regular season.",
    "top_wr": "Top WR by total starter-only points scored in the regular season.",
    "top_te": "Top TE by total starter-only points scored in the regular season.",
    "top_k":  "Top K by total starter-only points scored in the regular season.",
    "top_dl": "Top DL by total starter-only points scored in the regular season.",
    "top_lb": "Top LB by total starter-only points scored in the regular season.",
    "top_db": "Top DB by total starter-only points scored in the regular season.",
    "league_mvp": (
        "Regular-season MVP: highest VORP (Value Over Replacement Player) "
        "across all positions, computed from starter-only scoring."
    ),
}


# Player-award positions in display order.
_PLAYER_AWARD_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
_PLAYER_AWARD_KEY_BY_POS = {
    "QB": "top_qb",
    "RB": "top_rb",
    "WR": "top_wr",
    "TE": "top_te",
    "K":  "top_k",
    "DL": "top_dl",
    "LB": "top_lb",
    "DB": "top_db",
}
_PLAYER_AWARD_LABEL_BY_POS = {
    "QB": "Top QB",
    "RB": "Top RB",
    "WR": "Top WR",
    "TE": "Top TE",
    "K":  "Top Kicker",
    "DL": "Top DL",
    "LB": "Top LB",
    "DB": "Top DB",
}

# Offensive vs defensive position families for manager awards.
_OFFENSIVE_POSITIONS = frozenset({"QB", "RB", "WR", "TE", "K"})
_DEFENSIVE_POSITIONS = frozenset({"DL", "LB", "DB", "DEF"})


# ── helpers ────────────────────────────────────────────────────────────────
def _roster_player_points(matchup_entry: dict[str, Any]) -> dict[str, float]:
    """Return ``{player_id: points}`` for a matchup entry.

    Falls back to an empty dict if the Sleeper payload is missing the
    per-player scoring map (older seasons sometimes are).
    """
    pp = matchup_entry.get("players_points")
    if isinstance(pp, dict):
        out: dict[str, float] = {}
        for pid, val in pp.items():
            try:
                out[str(pid)] = float(val or 0.0)
            except (TypeError, ValueError):
                continue
        return out
    return {}


def _starter_set(matchup_entry: dict[str, Any]) -> set[str]:
    starters = matchup_entry.get("starters") or []
    return {str(s) for s in starters if s}


def _post_weeks(season: SeasonSnapshot, after_leg: int) -> list[int]:
    """Weeks strictly after ``after_leg`` in the season's schedule."""
    return [w for w in sorted(season.matchups_by_week.keys()) if w > after_leg]


def _player_points_in_week_for_roster(
    season: SeasonSnapshot,
    week: int,
    roster_id: int,
    player_id: str,
    require_started: bool = False,
) -> float | None:
    """Return the player's scored points for a specific roster-week.

    ``require_started`` restricts the lookup to when the roster actually
    started the player that week.  Returns ``None`` if the data isn't
    available (older seasons or missing players_points map).
    """
    entries = season.matchups_by_week.get(week) or []
    for entry in entries:
        try:
            rid = int(entry.get("roster_id"))
        except (TypeError, ValueError):
            continue
        if rid != roster_id:
            continue
        if require_started and str(player_id) not in _starter_set(entry):
            return None
        pp = _roster_player_points(entry)
        return pp.get(str(player_id))
    return None


def _season_has_player_scoring(season: SeasonSnapshot) -> bool:
    """True when at least one matchup entry carries players_points."""
    for entries in season.matchups_by_week.values():
        for m in entries:
            if isinstance(m.get("players_points"), dict) and m["players_points"]:
                return True
    return False


# ── per-season canonical awards (already in v1) ────────────────────────────
def _canonical_award(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot, rid: int | None, key: str, label: str, value: Any = None) -> dict[str, Any] | None:
    if rid is None:
        return None
    owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
    if not owner_id:
        return None
    return {
        "key": key,
        "label": label,
        "description": AWARD_DESCRIPTIONS.get(key, ""),
        "ownerId": owner_id,
        "displayName": metrics.display_name_for(snapshot, owner_id),
        "teamName": metrics.team_name(snapshot, season.league_id, rid),
        "value": value,
    }


def _season_canonical_awards(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    standings = metrics.season_standings(season, snapshot.managers)
    placement = metrics.playoff_placement(season.winners_bracket)
    if not standings:
        return []

    champion_rid = metrics.season_champion(season)
    runner_up_rid = metrics.season_runner_up(season)
    top_seed = metrics.top_seed(standings)
    best_record_rid = standings[0]["rosterId"] if standings else None
    pf_leader = max(standings, key=lambda r: r["pointsFor"], default=None)
    pa_leader = max(standings, key=lambda r: r["pointsAgainst"], default=None)

    worst_place = max((p for p in placement.values()), default=None)
    toilet_rid: int | None = None
    if worst_place is not None:
        toilet_rid = next((rid for rid, p in placement.items() if p == worst_place), None)

    high_week: tuple[float, int, int] | None = None
    low_week: tuple[float, int, int] | None = None
    for week, entries in season.matchups_by_week.items():
        for m in entries:
            rid = metrics.roster_id_of(m)
            if rid is None:
                continue
            pts = metrics.matchup_points(m)
            if pts <= 0:
                continue
            if high_week is None or pts > high_week[0]:
                high_week = (pts, rid, week)
            if low_week is None or pts < low_week[0]:
                low_week = (pts, rid, week)

    awards = [
        _canonical_award(snapshot, season, champion_rid, "champion", "Champion"),
        _canonical_award(snapshot, season, runner_up_rid, "runner_up", "Runner-Up"),
        _canonical_award(
            snapshot, season,
            top_seed["rosterId"] if top_seed else None,
            "top_seed", "Top Seed",
            value={"winPct": top_seed["winPct"]} if top_seed else None,
        ),
        _canonical_award(
            snapshot, season, best_record_rid,
            "regular_season_crown", "Regular-Season Crown",
            value={"record": f'{standings[0]["wins"]}-{standings[0]["losses"]}'} if standings else None,
        ),
        _canonical_award(
            snapshot, season,
            pf_leader["rosterId"] if pf_leader else None,
            "points_king", "Points King",
            value={"pointsFor": pf_leader["pointsFor"]} if pf_leader else None,
        ),
        _canonical_award(
            snapshot, season,
            pa_leader["rosterId"] if pa_leader else None,
            "points_black_hole", "Points Black Hole",
            value={"pointsAgainst": pa_leader["pointsAgainst"]} if pa_leader else None,
        ),
        _canonical_award(snapshot, season, toilet_rid, "toilet_bowl", "Toilet Bowl"),
        _canonical_award(
            snapshot, season,
            high_week[1] if high_week else None,
            "highest_single_week", "Highest Single-Week Score",
            value={"points": round(high_week[0], 2), "week": high_week[2]} if high_week else None,
        ),
        _canonical_award(
            snapshot, season,
            low_week[1] if low_week else None,
            "lowest_single_week", "Lowest Single-Week Score",
            value={"points": round(low_week[0], 2), "week": low_week[2]} if low_week else None,
        ),
    ]
    return [a for a in awards if a is not None]


# ── activity-based per-season awards ───────────────────────────────────────
def _trader_of_the_year_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> tuple[list[dict[str, Any]], tuple[float, str, dict[str, Any]] | None]:
    """Return sortable trader-of-the-year score rows per owner."""
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "tradeCount": 0,
                "pointsGained": 0.0,
                "playoffPointsGained": 0.0,
                "assetSwingValue": 0.0,
                "biggestTradeGain": 0.0,
                "biggestTradeId": "",
            }
        return per_owner[owner_id]

    best_trade: tuple[float, str, dict[str, Any]] | None = None

    for tx in season.trades():
        leg = tx.get("leg") or tx.get("_leg") or 0
        try:
            leg_int = int(leg)
        except (TypeError, ValueError):
            leg_int = 0
        post_weeks = _post_weeks(season, leg_int)
        if not post_weeks:
            continue

        adds = tx.get("adds") or {}
        drops = tx.get("drops") or {}
        roster_ids: list[int] = []
        for rid in tx.get("roster_ids") or []:
            try:
                roster_ids.append(int(rid))
            except (TypeError, ValueError):
                continue
        if len(roster_ids) < 2:
            continue

        for rid in roster_ids:
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            received = [pid for pid, r in adds.items() if int(r) == rid]
            sent = [pid for pid, r in drops.items() if int(r) == rid]

            gain = 0.0
            playoff_gain = 0.0
            for week in post_weeks:
                is_playoff = week >= season.playoff_week_start
                for pid in received:
                    pts = _player_points_in_week_for_roster(season, week, rid, pid)
                    if pts is None:
                        continue
                    gain += pts
                    if is_playoff:
                        playoff_gain += pts
                for pid in sent:
                    other_rid = next(
                        (int(r) for p, r in adds.items() if p == pid and int(r) != rid),
                        None,
                    )
                    if other_rid is None:
                        continue
                    pts = _player_points_in_week_for_roster(season, week, other_rid, pid)
                    if pts is None:
                        continue
                    gain -= pts
                    if is_playoff:
                        playoff_gain -= pts

            swing = 0.0
            for pk in tx.get("draft_picks") or []:
                try:
                    pk_round = int(pk.get("round") or 4)
                except (TypeError, ValueError):
                    pk_round = 4
                if int(pk.get("owner_id") or 0) == rid:
                    swing += max(1, 5 - pk_round)
                elif int(pk.get("previous_owner_id") or 0) == rid:
                    swing -= max(1, 5 - pk_round)

            rec = _ensure(owner_id)
            rec["tradeCount"] += 1
            rec["pointsGained"] += gain
            rec["playoffPointsGained"] += playoff_gain
            rec["assetSwingValue"] += swing
            if gain > rec["biggestTradeGain"]:
                rec["biggestTradeGain"] = gain
                rec["biggestTradeId"] = str(tx.get("transaction_id") or "")

            if best_trade is None or gain > best_trade[0]:
                best_trade = (gain, owner_id, {
                    "transactionId": str(tx.get("transaction_id") or ""),
                    "season": season.season,
                    "leagueId": season.league_id,
                    "week": leg_int,
                    "ownerId": owner_id,
                    "pointsGained": round(gain, 2),
                    "playoffPointsGained": round(playoff_gain, 2),
                    "receivedPlayerIds": list(received),
                    "sentPlayerIds": list(sent),
                })

    rows = list(per_owner.values())
    for r in rows:
        r["pointsGained"] = round(r["pointsGained"], 2)
        r["playoffPointsGained"] = round(r["playoffPointsGained"], 2)
        r["assetSwingValue"] = round(r["assetSwingValue"], 4)
        r["displayName"] = metrics.display_name_for(snapshot, r["ownerId"])
    rows.sort(
        key=lambda r: (
            -r["pointsGained"],
            -r["playoffPointsGained"],
            -r["assetSwingValue"],
        )
    )
    for r in rows:
        r.pop("assetSwingValue", None)
    return rows, best_trade


def _waiver_king_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "pointsGained": 0.0,
                "faabSpent": 0,
                "addCount": 0,
                "usefulAdds": 0,
            }
        return per_owner[owner_id]

    for tx in season.waivers():
        leg = tx.get("leg") or tx.get("_leg") or 0
        try:
            leg_int = int(leg)
        except (TypeError, ValueError):
            leg_int = 0
        post_weeks = _post_weeks(season, leg_int)
        if not post_weeks:
            continue
        adds = tx.get("adds") or {}
        settings = tx.get("settings") or {}
        bid_raw = settings.get("waiver_bid")
        try:
            bid = int(bid_raw) if bid_raw is not None else 0
        except (TypeError, ValueError):
            bid = 0

        for pid, rid in adds.items():
            try:
                rid_int = int(rid)
            except (TypeError, ValueError):
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid_int)
            if not owner_id:
                continue
            rec = _ensure(owner_id)
            rec["addCount"] += 1
            rec["faabSpent"] += max(0, bid)
            gain = 0.0
            started_at_least_once = False
            for week in post_weeks:
                starter_pts = _player_points_in_week_for_roster(
                    season, week, rid_int, pid, require_started=True
                )
                if starter_pts is not None:
                    gain += starter_pts
                    started_at_least_once = True
                    continue
                total_pts = _player_points_in_week_for_roster(
                    season, week, rid_int, pid, require_started=False
                )
                if total_pts is not None and not _starter_set(
                    _matchup_for(season, week, rid_int) or {}
                ):
                    gain += total_pts
            rec["pointsGained"] += gain
            if started_at_least_once and gain > 0:
                rec["usefulAdds"] += 1

    rows = list(per_owner.values())
    for r in rows:
        r["pointsGained"] = round(r["pointsGained"], 2)
        r["faabEfficiency"] = (
            round(r["pointsGained"] / r["faabSpent"], 3) if r["faabSpent"] > 0 else None
        )
        r["displayName"] = metrics.display_name_for(snapshot, r["ownerId"])
    rows.sort(
        key=lambda r: (
            -r["pointsGained"],
            -(r["faabEfficiency"] or 0),
            -r["usefulAdds"],
        )
    )
    return rows


def _matchup_for(season: SeasonSnapshot, week: int, roster_id: int) -> dict[str, Any] | None:
    for m in season.matchups_by_week.get(week) or []:
        try:
            if int(m.get("roster_id")) == roster_id:
                return m
        except (TypeError, ValueError):
            continue
    return None


def _chaos_agent_scores(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "trades": 0,
                "waiverAdds": 0,
                "distinctPartners": 0,
                "playersMoved": 0,
                "picksMoved": 0,
                "score": 0.0,
                "_partners": set(),
            }
        return per_owner[owner_id]

    for tx in season.trades():
        roster_ids = []
        for rid in tx.get("roster_ids") or []:
            try:
                roster_ids.append(int(rid))
            except (TypeError, ValueError):
                continue
        if len(roster_ids) < 2:
            continue
        owners = [
            metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            for rid in roster_ids
        ]
        owners = [o for o in owners if o]
        if len(owners) < 2:
            continue
        adds = tx.get("adds") or {}
        picks = tx.get("draft_picks") or []
        for owner in owners:
            rec = _ensure(owner)
            rec["trades"] += 1
            rec["_partners"].update(o for o in owners if o != owner)
            rid = next(
                (
                    r for r in roster_ids
                    if metrics.resolve_owner(snapshot.managers, season.league_id, r) == owner
                ),
                None,
            )
            if rid is None:
                continue
            rec["playersMoved"] += sum(1 for _, r in adds.items() if int(r) == rid)
            rec["picksMoved"] += sum(
                1 for pk in picks if int(pk.get("owner_id") or 0) == rid
            )

    for tx in season.waivers():
        for rid in tx.get("roster_ids") or []:
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            rec = _ensure(owner_id)
            rec["waiverAdds"] += 1

    rows = []
    for owner_id, rec in per_owner.items():
        rec["distinctPartners"] = len(rec["_partners"])
        rec.pop("_partners", None)
        score = (
            3 * rec["trades"]
            + 1 * rec["distinctPartners"]
            + 1 * rec["playersMoved"]
            + 1 * rec["picksMoved"]
            + 0.5 * rec["waiverAdds"]
        )
        rec["score"] = round(score, 2)
        rec["displayName"] = metrics.display_name_for(snapshot, owner_id)
        rows.append(rec)
    rows.sort(key=lambda r: (-r["score"], -r["trades"], -r["waiverAdds"]))
    return rows


def _most_active_scores(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, int]] = defaultdict(lambda: {
        "trades": 0, "waivers": 0, "freeAgents": 0, "drops": 0,
    })
    for tx in season.trades():
        for rid in tx.get("roster_ids") or []:
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if owner_id:
                per_owner[owner_id]["trades"] += 1
    for week in sorted(season.transactions_by_week.keys()):
        for tx in season.transactions_by_week[week]:
            ttype = str(tx.get("type") or "").lower()
            status = str(tx.get("status") or "").lower()
            if status != "complete":
                continue
            for rid in tx.get("roster_ids") or []:
                owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
                if not owner_id:
                    continue
                if ttype == "waiver":
                    per_owner[owner_id]["waivers"] += 1
                elif ttype == "free_agent":
                    per_owner[owner_id]["freeAgents"] += 1
                drops = tx.get("drops") or {}
                per_owner[owner_id]["drops"] += sum(
                    1 for _, r in drops.items() if int(r) == int(rid)
                )
    rows = []
    for owner_id, rec in per_owner.items():
        total = sum(rec.values())
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "trades": rec["trades"],
            "waivers": rec["waivers"],
            "freeAgents": rec["freeAgents"],
            "drops": rec["drops"],
            "total": total,
        })
    rows.sort(key=lambda r: (-r["total"], -r["trades"], -r["waivers"]))
    return rows


def _silent_assassin_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    min_eligible: int = 4,
) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "wins": 0,
                "games": 0,
                "marginSum": 0.0,
                "seasonWins": 0,
            }
        return per_owner[owner_id]

    for week in sorted(season.matchups_by_week.keys()):
        if week >= season.playoff_week_start:
            continue
        for a, b in metrics.matchup_pairs(season.matchups_by_week[week]):
            pa = metrics.matchup_points(a)
            pb = metrics.matchup_points(b)
            if pa <= 0 and pb <= 0:
                continue
            margin = abs(pa - pb)
            owner_a = metrics.resolve_owner(snapshot.managers, season.league_id, a.get("roster_id"))
            owner_b = metrics.resolve_owner(snapshot.managers, season.league_id, b.get("roster_id"))
            if not owner_a or not owner_b:
                continue
            for owner in (owner_a, owner_b):
                _ensure(owner)["seasonWins"] += 0
            if margin > 10.0 + 1e-9:
                continue
            for owner in (owner_a, owner_b):
                _ensure(owner)["games"] += 1
            if pa > pb:
                _ensure(owner_a)["wins"] += 1
                _ensure(owner_a)["marginSum"] += margin
            elif pb > pa:
                _ensure(owner_b)["wins"] += 1
                _ensure(owner_b)["marginSum"] += margin

    standings = metrics.season_standings(season, snapshot.managers)
    season_wins = {r["ownerId"]: r["wins"] for r in standings}

    rows = []
    for owner_id, rec in per_owner.items():
        games = rec["games"]
        if games == 0:
            continue
        win_pct = rec["wins"] / games
        avg_margin = rec["marginSum"] / rec["wins"] if rec["wins"] else 0.0
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "closeGames": games,
            "closeWins": rec["wins"],
            "winPct": round(win_pct, 4),
            "avgCloseMargin": round(avg_margin, 2),
            "seasonWins": season_wins.get(owner_id, 0),
            "eligible": games >= min_eligible,
        })
    rows.sort(
        key=lambda r: (
            -r["winPct"] if r["eligible"] else 1,
            r["avgCloseMargin"],
            -r["seasonWins"],
        )
    )
    return rows


def _weekly_hammer_scores(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "highScoreFinishes": 0,
                "totalPoints": 0.0,
                "highestWeekPoints": 0.0,
            }
        return per_owner[owner_id]

    for week in sorted(season.matchups_by_week.keys()):
        if week >= season.playoff_week_start:
            continue
        entries = season.matchups_by_week[week]
        scored = [
            (metrics.roster_id_of(m), metrics.matchup_points(m))
            for m in entries
        ]
        scored = [s for s in scored if s[0] is not None and s[1] > 0]
        if not scored:
            continue
        top_pts = max(pts for _, pts in scored)
        for rid, pts in scored:
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            rec = _ensure(owner_id)
            rec["totalPoints"] += pts
            if pts > rec["highestWeekPoints"]:
                rec["highestWeekPoints"] = pts
            if abs(pts - top_pts) < 1e-6:
                rec["highScoreFinishes"] += 1

    rows = []
    for owner_id, rec in per_owner.items():
        rec["displayName"] = metrics.display_name_for(snapshot, owner_id)
        rec["totalPoints"] = round(rec["totalPoints"], 2)
        rec["highestWeekPoints"] = round(rec["highestWeekPoints"], 2)
        rows.append(rec)
    rows.sort(
        key=lambda r: (
            -r["highScoreFinishes"],
            -r["totalPoints"],
            -r["highestWeekPoints"],
        )
    )
    return rows


def _playoff_mvp_scores(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "playoffPoints": 0.0,
                "playoffWeeksPlayed": 0,
                "topPlayerName": "",
                "topPlayerPosition": "",
                "topPlayerPoints": 0.0,
            }
        return per_owner[owner_id]

    for week in sorted(season.matchups_by_week.keys()):
        if week < season.playoff_week_start:
            continue
        for entry in season.matchups_by_week[week]:
            rid = metrics.roster_id_of(entry)
            if rid is None:
                continue
            pts = metrics.matchup_points(entry)
            if pts <= 0:
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            rec = _ensure(owner_id)
            rec["playoffPoints"] += pts
            rec["playoffWeeksPlayed"] += 1
            for pid, pp in _roster_player_points(entry).items():
                if pp is None:
                    continue
                if pp > rec["topPlayerPoints"]:
                    rec["topPlayerPoints"] = pp
                    rec["topPlayerName"] = snapshot.player_display(pid) or pid
                    rec["topPlayerPosition"] = snapshot.player_position(pid)

    rows = []
    for owner_id, rec in per_owner.items():
        rec["displayName"] = metrics.display_name_for(snapshot, owner_id)
        rec["playoffPoints"] = round(rec["playoffPoints"], 2)
        rec["topPlayerPoints"] = round(rec["topPlayerPoints"], 2)
        rows.append(rec)
    rows.sort(key=lambda r: (-r["playoffPoints"], -r["playoffWeeksPlayed"]))
    return rows


def _bad_beat_scores(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> list[dict[str, Any]]:
    per_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in per_owner:
            per_owner[owner_id] = {
                "ownerId": owner_id,
                "biggestLoss": 0.0,
                "biggestLossWeek": None,
                "biggestLossSeason": season.season,
                "biggestLossOpponentPoints": 0.0,
                "pointsInLosses": 0.0,
                "lossCount": 0,
            }
        return per_owner[owner_id]

    for week in sorted(season.matchups_by_week.keys()):
        for a, b in metrics.matchup_pairs(season.matchups_by_week[week]):
            pa = metrics.matchup_points(a)
            pb = metrics.matchup_points(b)
            if pa <= 0 and pb <= 0:
                continue
            owner_a = metrics.resolve_owner(snapshot.managers, season.league_id, a.get("roster_id"))
            owner_b = metrics.resolve_owner(snapshot.managers, season.league_id, b.get("roster_id"))
            if not owner_a or not owner_b:
                continue
            if pa < pb:
                loser, loser_pts, opp_pts = owner_a, pa, pb
            elif pb < pa:
                loser, loser_pts, opp_pts = owner_b, pb, pa
            else:
                continue
            rec = _ensure(loser)
            rec["pointsInLosses"] += loser_pts
            rec["lossCount"] += 1
            if loser_pts > rec["biggestLoss"]:
                rec["biggestLoss"] = loser_pts
                rec["biggestLossWeek"] = week
                rec["biggestLossOpponentPoints"] = opp_pts

    rows = []
    for owner_id, rec in per_owner.items():
        rec["displayName"] = metrics.display_name_for(snapshot, owner_id)
        rec["biggestLoss"] = round(rec["biggestLoss"], 2)
        rec["pointsInLosses"] = round(rec["pointsInLosses"], 2)
        rec["biggestLossOpponentPoints"] = round(rec["biggestLossOpponentPoints"], 2)
        rows.append(rec)
    rows.sort(key=lambda r: (-r["biggestLoss"], -r["pointsInLosses"]))
    return rows


def _pick_hoarder_scores(snapshot: PublicLeagueSnapshot) -> list[dict[str, Any]]:
    ownership = _pick_ownership_map(snapshot)
    rows = []
    for owner_id, picks in ownership.items():
        weight = sum(pick_weight(p["round"]) for p in picks)
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "weightedScore": weight,
            "totalPicks": len(picks),
        })
    rows.sort(key=lambda r: (-r["weightedScore"], -r["totalPicks"]))
    return rows


def _best_rebuild_scores(
    snapshot: PublicLeagueSnapshot,
    current: SeasonSnapshot,
    previous: SeasonSnapshot,
) -> list[dict[str, Any]]:
    """Historical only: YoY improvement across standings + stockpile."""
    def _rank_lookup(season: SeasonSnapshot) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
        standings = metrics.season_standings(season, snapshot.managers)
        by_points = sorted(standings, key=lambda r: -r["pointsFor"])
        record_rank = {r["ownerId"]: r["standing"] for r in standings}
        points_rank = {r["ownerId"]: i + 1 for i, r in enumerate(by_points)}
        rookies: dict[str, int] = {}
        for r in season.rosters:
            try:
                rid = int(r.get("roster_id"))
            except (TypeError, ValueError):
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            count = 0
            for pid in r.get("players") or []:
                p = snapshot.nfl_players.get(str(pid)) or {}
                try:
                    if int(p.get("years_exp")) == 0:
                        count += 1
                except (TypeError, ValueError):
                    continue
            rookies[owner_id] = count
        return record_rank, points_rank, rookies

    cur_record, cur_points, cur_rookies = _rank_lookup(current)
    prev_record, prev_points, prev_rookies = _rank_lookup(previous)

    current_weighted = {
        row["ownerId"]: row["weightedScore"]
        for row in _pick_hoarder_scores(snapshot)
    }

    rows = []
    for owner_id in snapshot.managers.by_owner_id:
        if owner_id not in cur_record or owner_id not in prev_record:
            continue
        record_delta = prev_record[owner_id] - cur_record[owner_id]
        points_delta = prev_points[owner_id] - cur_points[owner_id]
        stockpile = current_weighted.get(owner_id, 0)
        rookies_delta = cur_rookies.get(owner_id, 0) - prev_rookies.get(owner_id, 0)

        composite = (
            0.40 * points_delta
            + 0.30 * record_delta
            + 0.20 * (stockpile / 4.0)
            + 0.10 * rookies_delta
        )
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "pointsRankDelta": points_delta,
            "recordRankDelta": record_delta,
            "stockpileScore": stockpile,
            "rookiesDelta": rookies_delta,
            "compositeScore": round(composite, 3),
        })
    rows.sort(key=lambda r: (-r["compositeScore"], -r["recordRankDelta"], -r["pointsRankDelta"]))
    return rows


# ── Starter-only scoring helpers (manager + player + MVP awards) ──────────
def _starter_scoring_walk(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    regular_season_only: bool,
):
    """Yield ``(week, roster_id, owner_id, player_id, position, points, is_playoff)``
    for every starter in every scored matchup of the season.

    Skips any matchup-entry that lacks ``players_points`` or ``starters``
    (older Sleeper seasons sometimes omit them).  Position is resolved
    via ``snapshot.player_position`` so IDP-eligible players collapse
    into DL/LB/DB.
    """
    for week in sorted(season.matchups_by_week.keys()):
        is_playoff = week >= season.playoff_week_start
        if regular_season_only and is_playoff:
            continue
        for entry in season.matchups_by_week[week]:
            rid = metrics.roster_id_of(entry)
            if rid is None:
                continue
            owner_id = metrics.resolve_owner(snapshot.managers, season.league_id, rid)
            if not owner_id:
                continue
            pp = entry.get("players_points")
            if not isinstance(pp, dict):
                continue
            starters = _starter_set(entry)
            if not starters:
                continue
            for pid in starters:
                raw = pp.get(pid)
                try:
                    pts = float(raw or 0.0)
                except (TypeError, ValueError):
                    continue
                pos = snapshot.player_position(pid)
                yield week, rid, owner_id, pid, pos, pts, is_playoff


def _manager_unit_points(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    regular_season_only: bool = True,
) -> dict[str, dict[str, float]]:
    """Aggregate starter-only points per owner, partitioned by offense /
    defense unit.  Returns ``{owner_id: {"offense": pts, "defense": pts}}``.
    """
    out: dict[str, dict[str, float]] = {}
    for _wk, _rid, owner_id, _pid, pos, pts, _is_p in _starter_scoring_walk(
        snapshot, season, regular_season_only=regular_season_only
    ):
        rec = out.setdefault(owner_id, {"offense": 0.0, "defense": 0.0})
        if pos in _OFFENSIVE_POSITIONS or pos == "":
            # Default unmapped positions into offense (covers DEF/ST team
            # defenses too if they appear in an offense-style starter slot).
            if pos in _DEFENSIVE_POSITIONS:
                rec["defense"] += pts
            else:
                rec["offense"] += pts
        elif pos in _DEFENSIVE_POSITIONS:
            rec["defense"] += pts
        else:
            rec["offense"] += pts
    return out


def _top_offense_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    units = _manager_unit_points(snapshot, season, regular_season_only=True)
    rows = []
    for owner_id, totals in units.items():
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "offensePoints": round(totals["offense"], 2),
        })
    rows.sort(key=lambda r: -r["offensePoints"])
    return rows


def _top_defense_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    units = _manager_unit_points(snapshot, season, regular_season_only=True)
    rows = []
    for owner_id, totals in units.items():
        rows.append({
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "defensePoints": round(totals["defense"], 2),
        })
    # Filter out leagues with no IDP scoring on file so we don't surface
    # an "everyone tied at 0.0" race.
    rows = [r for r in rows if r["defensePoints"] > 0]
    rows.sort(key=lambda r: -r["defensePoints"])
    return rows


def _manager_of_the_year_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    """60% regular-season win% + 40% PF-normalized.  Both rescaled to
    [0, 1] within the league so a perfect manager would score 1.0.
    """
    standings = metrics.season_standings(season, snapshot.managers)
    if not standings:
        return []
    pf_max = max((r["pointsFor"] for r in standings), default=0.0) or 1.0
    rows = []
    for r in standings:
        win_component = r["winPct"]
        pf_component = r["pointsFor"] / pf_max
        composite = 0.6 * win_component + 0.4 * pf_component
        rows.append({
            "ownerId": r["ownerId"],
            "displayName": metrics.display_name_for(snapshot, r["ownerId"]),
            "wins": r["wins"],
            "losses": r["losses"],
            "ties": r["ties"],
            "winPct": round(r["winPct"], 4),
            "pointsFor": r["pointsFor"],
            "compositeScore": round(composite, 4),
        })
    rows.sort(key=lambda r: (-r["compositeScore"], -r["wins"], -r["pointsFor"]))
    return rows


def _player_starter_totals(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    regular_season_only: bool = True,
) -> dict[str, dict[str, Any]]:
    """Aggregate starter-only points per player across the season.

    Returns ``{player_id: {points, gamesStarted, position, ownerIds}}``.
    """
    out: dict[str, dict[str, Any]] = {}
    for week, _rid, owner_id, pid, pos, pts, _is_p in _starter_scoring_walk(
        snapshot, season, regular_season_only=regular_season_only
    ):
        rec = out.setdefault(pid, {
            "playerId": pid,
            "playerName": snapshot.player_display(pid),
            "position": pos,
            "starterPoints": 0.0,
            "gamesStarted": 0,
            "ownerIds": set(),
            "lastOwnerId": "",
            "lastWeek": 0,
        })
        # Track the most-recent fantasy owner so we can attribute the
        # award to a manager card on the page (ownership can change
        # mid-season after a trade).
        rec["starterPoints"] += pts
        rec["gamesStarted"] += 1
        rec["ownerIds"].add(owner_id)
        if week >= rec["lastWeek"]:
            rec["lastWeek"] = week
            rec["lastOwnerId"] = owner_id
        # Position can drift if a player is dual-eligible — keep the
        # IDP-resolved one when present, otherwise overwrite.
        if pos and not rec["position"]:
            rec["position"] = pos
    for rec in out.values():
        rec["starterPoints"] = round(rec["starterPoints"], 2)
        rec["ownerIds"] = sorted(rec["ownerIds"])
    return out


def _nfl_team_for(snapshot: PublicLeagueSnapshot, pid: str) -> str:
    """Return the NFL team abbreviation for a Sleeper player id, or ""."""
    nfl_player = snapshot.nfl_players.get(str(pid)) or {}
    return str(nfl_player.get("team") or "").upper()


def _top_player_per_position_scores(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    regular_season_only: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    """Top scorers grouped by position from starter-only points.

    Returns ``{pos: [row, row, row]}`` where rows are sorted descending
    by ``starterPoints``.  Up to top 3 per position.
    """
    totals = _player_starter_totals(
        snapshot, season, regular_season_only=regular_season_only
    )
    grouped: dict[str, list[dict[str, Any]]] = {pos: [] for pos in _PLAYER_AWARD_POSITIONS}
    for pid, rec in totals.items():
        pos = rec["position"]
        if pos not in grouped:
            continue
        owner_id = rec["lastOwnerId"]
        grouped[pos].append({
            "playerId": pid,
            "playerName": rec["playerName"],
            "team": _nfl_team_for(snapshot, pid),
            "position": pos,
            "starterPoints": rec["starterPoints"],
            "gamesStarted": rec["gamesStarted"],
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
        })
    for pos in grouped:
        grouped[pos].sort(key=lambda r: -r["starterPoints"])
    return grouped


def _replacement_per_game_for_position(
    rows: list[dict[str, Any]],
    starter_slots: int,
) -> float:
    """Replacement-level points-per-game at a position.

    Thin shim around :func:`src.scoring.replacement_level.replacement_per_game`
    that lets the awards path keep using its dict shape (``starterPoints``,
    ``gamesStarted``) without restructuring callers.  See the shared
    module for the algorithm.
    """
    from src.scoring.replacement_level import replacement_per_game
    return replacement_per_game(rows or [], starter_slots, band_size=5)


def _starter_slot_counts(
    season: SeasonSnapshot,
) -> dict[str, int]:
    """Total starting slots per position across the entire league per week.

    Thin shim around
    :func:`src.scoring.replacement_level.starter_slot_counts`.  Pulls
    ``roster_positions`` + team count off the snapshot and delegates
    the FLEX / SUPER_FLEX / IDP_FLEX splitting to the shared module.
    """
    from src.scoring.replacement_level import starter_slot_counts
    return starter_slot_counts(
        season.league.get("roster_positions") or [],
        season.num_teams,
    )


def _vorp_rows(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    regular_season_only: bool,
) -> list[dict[str, Any]]:
    """Compute a VORP row per player.

    Replacement-level baseline is per-position (per-game), so injured
    starters who scored a lot per game still rate fairly against
    healthier-but-thinner peers.
    """
    totals = _player_starter_totals(
        snapshot, season, regular_season_only=regular_season_only
    )
    if not totals:
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in totals.values():
        pos = rec["position"]
        if not pos:
            continue
        grouped[pos].append({
            "playerId": rec["playerId"],
            "playerName": rec["playerName"],
            "position": pos,
            "starterPoints": rec["starterPoints"],
            "gamesStarted": rec["gamesStarted"],
            "ownerIds": rec["ownerIds"],
            "lastOwnerId": rec["lastOwnerId"],
        })

    starter_slots = _starter_slot_counts(season)
    out: list[dict[str, Any]] = []
    for pos, rows in grouped.items():
        slots = starter_slots.get(pos, 0)
        if slots <= 0:
            # No dedicated slot for this position; treat as a thin
            # baseline so a single-game cameo doesn't outshine real
            # full-season starters.
            slots = max(1, len(rows) // 2)
        replacement_per_game = _replacement_per_game_for_position(rows, slots)
        for r in rows:
            games = r["gamesStarted"] or 1
            replacement_total = replacement_per_game * games
            vorp = r["starterPoints"] - replacement_total
            owner_id = r["lastOwnerId"]
            out.append({
                "playerId": r["playerId"],
                "playerName": r["playerName"],
                "team": _nfl_team_for(snapshot, r["playerId"]),
                "position": pos,
                "starterPoints": r["starterPoints"],
                "gamesStarted": r["gamesStarted"],
                "vorp": round(vorp, 2),
                "replacementPerGame": round(replacement_per_game, 2),
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
            })
    out.sort(key=lambda r: -r["vorp"])
    return out


def _league_mvp_rows(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    """Regular-season MVP candidates ranked by VORP."""
    return _vorp_rows(snapshot, season, regular_season_only=True)


def _playoff_mvp_player_rows(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    """Playoff MVP candidates ranked by VORP across playoff weeks only."""
    totals = _player_starter_totals(
        snapshot, season, regular_season_only=False
    )
    if not totals:
        return []
    # Strip regular-season data: we want playoff-only.  Re-run the walk
    # but only over playoff weeks.
    playoff_totals: dict[str, dict[str, Any]] = {}
    for week, _rid, owner_id, pid, pos, pts, is_playoff in _starter_scoring_walk(
        snapshot, season, regular_season_only=False
    ):
        if not is_playoff:
            continue
        rec = playoff_totals.setdefault(pid, {
            "playerId": pid,
            "playerName": snapshot.player_display(pid),
            "position": pos,
            "starterPoints": 0.0,
            "gamesStarted": 0,
            "lastOwnerId": "",
            "lastWeek": 0,
        })
        rec["starterPoints"] += pts
        rec["gamesStarted"] += 1
        if week >= rec["lastWeek"]:
            rec["lastWeek"] = week
            rec["lastOwnerId"] = owner_id
        if pos and not rec["position"]:
            rec["position"] = pos
    if not playoff_totals:
        return []

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in playoff_totals.values():
        pos = rec["position"]
        if not pos:
            continue
        grouped[pos].append(rec)

    starter_slots = _starter_slot_counts(season)
    out: list[dict[str, Any]] = []
    for pos, rows in grouped.items():
        slots = starter_slots.get(pos, 0)
        if slots <= 0:
            slots = max(1, len(rows) // 2)
        replacement_per_game = _replacement_per_game_for_position(rows, slots)
        for r in rows:
            games = r["gamesStarted"] or 1
            vorp = r["starterPoints"] - replacement_per_game * games
            owner_id = r["lastOwnerId"]
            out.append({
                "playerId": r["playerId"],
                "playerName": r["playerName"],
                "team": _nfl_team_for(snapshot, r["playerId"]),
                "position": pos,
                "starterPoints": round(r["starterPoints"], 2),
                "gamesStarted": r["gamesStarted"],
                "vorp": round(vorp, 2),
                "ownerId": owner_id,
                "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else "",
            })
    out.sort(key=lambda r: -r["vorp"])
    return out


def _rivalry_of_the_year(snapshot: PublicLeagueSnapshot, season: SeasonSnapshot) -> dict[str, Any] | None:
    """Season-scoped rivalry of the year."""
    pair_scores: dict[tuple[str, str], dict[str, Any]] = {}

    def _ensure(a: str, b: str) -> dict[str, Any]:
        key = (a, b) if a <= b else (b, a)
        if key not in pair_scores:
            pair_scores[key] = {
                "ownerIds": list(key),
                "totalMeetings": 0,
                "playoffMeetings": 0,
                "decidedByFive": 0,
                "decidedByTen": 0,
                "seriesWinsA": 0,
                "seriesWinsB": 0,
            }
        return pair_scores[key]

    for week in sorted(season.matchups_by_week.keys()):
        is_playoff = week >= season.playoff_week_start
        for a, b in metrics.matchup_pairs(season.matchups_by_week[week]):
            pa = metrics.matchup_points(a)
            pb = metrics.matchup_points(b)
            if pa <= 0 and pb <= 0:
                continue
            oa = metrics.resolve_owner(snapshot.managers, season.league_id, a.get("roster_id"))
            ob = metrics.resolve_owner(snapshot.managers, season.league_id, b.get("roster_id"))
            if not oa or not ob or oa == ob:
                continue
            rec = _ensure(oa, ob)
            rec["totalMeetings"] += 1
            if is_playoff:
                rec["playoffMeetings"] += 1
            margin = abs(pa - pb)
            if margin <= 5.0 + 1e-9:
                rec["decidedByFive"] += 1
            if margin <= 10.0 + 1e-9:
                rec["decidedByTen"] += 1
            key_a = rec["ownerIds"][0]
            if pa > pb:
                if oa == key_a:
                    rec["seriesWinsA"] += 1
                else:
                    rec["seriesWinsB"] += 1
            elif pb > pa:
                if ob == key_a:
                    rec["seriesWinsA"] += 1
                else:
                    rec["seriesWinsB"] += 1

    if not pair_scores:
        return None

    best_key: tuple[str, str] | None = None
    best_score = -1.0
    best_row: dict[str, Any] | None = None
    for key, rec in pair_scores.items():
        split = 1 if rec["seriesWinsA"] > 0 and rec["seriesWinsB"] > 0 else 0
        score = (
            5 * rec["playoffMeetings"]
            + 3 * rec["decidedByFive"]
            + 2 * rec["decidedByTen"]
            + 2 * split
            + 1 * rec["totalMeetings"]
        )
        rec["rivalryIndex"] = score
        if score > best_score:
            best_score = score
            best_key = key
            best_row = rec

    if best_row is None:
        return None
    best_row["displayNames"] = [
        metrics.display_name_for(snapshot, best_row["ownerIds"][0]),
        metrics.display_name_for(snapshot, best_row["ownerIds"][1]),
    ]
    return best_row


# ── assembly helpers ────────────────────────────────────────────────────────
def _award_from_row(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    rows: list[dict[str, Any]],
    key: str,
    label: str,
    value_builder,
    eligible_only: bool = False,
) -> dict[str, Any] | None:
    if not rows:
        return None
    pool = rows
    if eligible_only:
        pool = [r for r in rows if r.get("eligible") is True]
    if not pool:
        return None
    winner = pool[0]
    owner_id = winner["ownerId"]
    rid = _roster_id_for_owner(season, owner_id)
    return {
        "key": key,
        "label": label,
        "description": AWARD_DESCRIPTIONS.get(key, ""),
        "ownerId": owner_id,
        "displayName": winner.get("displayName") or metrics.display_name_for(snapshot, owner_id),
        "teamName": (
            metrics.team_name(snapshot, season.league_id, rid) if rid is not None else ""
        ),
        "value": value_builder(winner),
    }


def _roster_id_for_owner(season: SeasonSnapshot, owner_id: str) -> int | None:
    for r in season.rosters:
        if str(r.get("owner_id") or "") == owner_id:
            try:
                return int(r.get("roster_id"))
            except (TypeError, ValueError):
                return None
    return None


# ── public entry point ────────────────────────────────────────────────────
def _activity_awards_for_season(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    previous_season: SeasonSnapshot | None,
) -> list[dict[str, Any]]:
    trader_rows, best_trade = _trader_of_the_year_scores(snapshot, season)
    waiver_rows = _waiver_king_scores(snapshot, season)
    chaos_rows = _chaos_agent_scores(snapshot, season)
    active_rows = _most_active_scores(snapshot, season)
    silent_rows = _silent_assassin_scores(snapshot, season)
    hammer_rows = _weekly_hammer_scores(snapshot, season)
    playoff_rows = _playoff_mvp_scores(snapshot, season)
    bad_beat_rows = _bad_beat_scores(snapshot, season)

    awards: list[dict[str, Any]] = []

    def _add(award):
        if award:
            awards.append(award)

    _add(_award_from_row(
        snapshot, season, trader_rows, "trader_of_the_year", "Trader of the Year",
        lambda r: {"pointsGained": r["pointsGained"], "trades": r["tradeCount"]},
    ))
    if best_trade is not None:
        gain, owner_id, payload = best_trade
        rid = _roster_id_for_owner(season, owner_id)
        _add({
            "key": "best_trade_of_the_year",
            "label": "Best Trade of the Year",
            "description": AWARD_DESCRIPTIONS["best_trade_of_the_year"],
            "ownerId": owner_id,
            "displayName": metrics.display_name_for(snapshot, owner_id),
            "teamName": metrics.team_name(snapshot, season.league_id, rid) if rid is not None else "",
            "value": {
                "pointsGained": payload["pointsGained"],
                "week": payload["week"],
                "transactionId": payload["transactionId"],
            },
        })
    _add(_award_from_row(
        snapshot, season, waiver_rows, "waiver_king", "Waiver King",
        lambda r: {
            "pointsGained": r["pointsGained"],
            "adds": r.get("usefulAdds", 0),
            "faabEfficiency": r.get("faabEfficiency"),
        },
    ))
    _add(_award_from_row(
        snapshot, season, chaos_rows, "chaos_agent", "Chaos Agent",
        lambda r: {"score": r["score"], "trades": r["trades"], "partners": r["distinctPartners"]},
    ))
    _add(_award_from_row(
        snapshot, season, active_rows, "most_active", "Most Active",
        lambda r: {"total": r["total"], "trades": r["trades"], "waivers": r["waivers"]},
    ))
    _add(_award_from_row(
        snapshot, season, silent_rows, "silent_assassin", "Silent Assassin",
        lambda r: {"winPct": r["winPct"], "closeGames": r["closeGames"], "closeWins": r["closeWins"]},
        eligible_only=True,
    ))
    _add(_award_from_row(
        snapshot, season, hammer_rows, "weekly_hammer", "Weekly Hammer",
        lambda r: {"highScoreFinishes": r["highScoreFinishes"], "highestWeek": r["highestWeekPoints"]},
    ))
    # Playoff MVP — VORP-based player award (replaces the prior team-points version).
    playoff_mvp_rows = _playoff_mvp_player_rows(snapshot, season)
    if playoff_mvp_rows:
        winner = playoff_mvp_rows[0]
        rid = _roster_id_for_owner(season, winner["ownerId"])
        awards.append({
            "key": "playoff_mvp",
            "label": "Playoff MVP",
            "description": AWARD_DESCRIPTIONS["playoff_mvp"],
            "ownerId": winner["ownerId"],
            "displayName": winner["displayName"],
            "teamName": metrics.team_name(snapshot, season.league_id, rid) if rid is not None else "",
            "value": {
                "playerId": winner["playerId"],
                "playerName": winner["playerName"],
                "team": winner.get("team", ""),
                "position": winner["position"],
                "vorp": winner["vorp"],
                "starterPoints": winner["starterPoints"],
                "gamesStarted": winner["gamesStarted"],
            },
        })
    _add(_award_from_row(
        snapshot, season, bad_beat_rows, "bad_beat", "Bad Beat",
        lambda r: {
            "points": r["biggestLoss"],
            "week": r["biggestLossWeek"],
            "opponentPoints": r["biggestLossOpponentPoints"],
        },
    ))

    # ── Manager awards ─────────────────────────────────────────────
    offense_rows = _top_offense_scores(snapshot, season)
    _add(_award_from_row(
        snapshot, season, offense_rows, "top_offense", "Top Offense",
        lambda r: {"offensePoints": r["offensePoints"]},
    ))
    defense_rows = _top_defense_scores(snapshot, season)
    if defense_rows:
        _add(_award_from_row(
            snapshot, season, defense_rows, "top_defense", "Top Defense",
            lambda r: {"defensePoints": r["defensePoints"]},
        ))
    moty_rows = _manager_of_the_year_scores(snapshot, season)
    _add(_award_from_row(
        snapshot, season, moty_rows, "manager_of_the_year", "Manager of the Year",
        lambda r: {
            "compositeScore": r["compositeScore"],
            "wins": r["wins"],
            "losses": r["losses"],
            "winPct": r["winPct"],
            "pointsFor": r["pointsFor"],
        },
    ))

    # ── Player awards (top scorer per position, regular-season starter-only) ──
    player_rows_by_pos = _top_player_per_position_scores(
        snapshot, season, regular_season_only=True
    )
    for pos in _PLAYER_AWARD_POSITIONS:
        rows = player_rows_by_pos.get(pos) or []
        if not rows:
            continue
        winner = rows[0]
        if winner["starterPoints"] <= 0:
            continue
        rid = _roster_id_for_owner(season, winner["ownerId"]) if winner["ownerId"] else None
        awards.append({
            "key": _PLAYER_AWARD_KEY_BY_POS[pos],
            "label": _PLAYER_AWARD_LABEL_BY_POS[pos],
            "description": AWARD_DESCRIPTIONS[_PLAYER_AWARD_KEY_BY_POS[pos]],
            "ownerId": winner["ownerId"],
            "displayName": winner["displayName"],
            "teamName": metrics.team_name(snapshot, season.league_id, rid) if rid is not None else "",
            "value": {
                "playerId": winner["playerId"],
                "playerName": winner["playerName"],
                "team": winner.get("team", ""),
                "position": winner["position"],
                "starterPoints": winner["starterPoints"],
                "gamesStarted": winner["gamesStarted"],
            },
        })

    # ── League MVP (regular-season VORP) ───────────────────────────
    mvp_rows = _league_mvp_rows(snapshot, season)
    if mvp_rows:
        winner = mvp_rows[0]
        rid = _roster_id_for_owner(season, winner["ownerId"]) if winner["ownerId"] else None
        awards.append({
            "key": "league_mvp",
            "label": "League MVP",
            "description": AWARD_DESCRIPTIONS["league_mvp"],
            "ownerId": winner["ownerId"],
            "displayName": winner["displayName"],
            "teamName": metrics.team_name(snapshot, season.league_id, rid) if rid is not None else "",
            "value": {
                "playerId": winner["playerId"],
                "playerName": winner["playerName"],
                "team": winner.get("team", ""),
                "position": winner["position"],
                "vorp": winner["vorp"],
                "starterPoints": winner["starterPoints"],
                "gamesStarted": winner["gamesStarted"],
            },
        })

    pick_rows = _pick_hoarder_scores(snapshot)
    if pick_rows:
        _add(_award_from_row(
            snapshot, season, pick_rows, "pick_hoarder", "Pick Hoarder",
            lambda r: {"weightedScore": r["weightedScore"], "totalPicks": r["totalPicks"]},
        ))

    if previous_season is not None and season.is_complete and previous_season.is_complete:
        rebuild_rows = _best_rebuild_scores(snapshot, season, previous_season)
        if rebuild_rows and rebuild_rows[0]["compositeScore"] > 0:
            _add(_award_from_row(
                snapshot, season, rebuild_rows, "best_rebuild", "Best Rebuild",
                lambda r: {
                    "compositeScore": r["compositeScore"],
                    "recordRankDelta": r["recordRankDelta"],
                    "pointsRankDelta": r["pointsRankDelta"],
                },
            ))

    rivalry = _rivalry_of_the_year(snapshot, season)
    if rivalry is not None and rivalry["rivalryIndex"] > 0:
        awards.append({
            "key": "rivalry_of_the_year",
            "label": "Rivalry of the Year",
            "description": AWARD_DESCRIPTIONS["rivalry_of_the_year"],
            "ownerId": "",
            "displayName": f"{rivalry['displayNames'][0]} vs {rivalry['displayNames'][1]}",
            "teamName": "",
            "value": {
                "ownerIds": rivalry["ownerIds"],
                "displayNames": rivalry["displayNames"],
                "rivalryIndex": rivalry["rivalryIndex"],
                "totalMeetings": rivalry["totalMeetings"],
                "playoffMeetings": rivalry["playoffMeetings"],
            },
        })

    return awards


def _build_race(
    snapshot: PublicLeagueSnapshot,
    key: str,
    label: str,
    rows: list[dict[str, Any]],
    value_builder,
    *,
    eligible_only: bool = False,
    top_n: int = 3,
) -> dict[str, Any] | None:
    pool = rows
    if eligible_only:
        pool = [r for r in rows if r.get("eligible") is True]
    if not pool:
        return None
    leaders = []
    for i, row in enumerate(pool[:top_n]):
        leaders.append({
            "rank": i + 1,
            "ownerId": row["ownerId"],
            "displayName": row.get("displayName") or metrics.display_name_for(snapshot, row["ownerId"]),
            "value": value_builder(row),
        })
    return {
        "key": key,
        "label": label,
        "description": AWARD_DESCRIPTIONS.get(key, ""),
        "leaders": leaders,
    }


def _current_season_races(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
) -> list[dict[str, Any]]:
    races: list[dict[str, Any]] = []

    trader_rows, _ = _trader_of_the_year_scores(snapshot, season)
    waiver_rows = _waiver_king_scores(snapshot, season)
    chaos_rows = _chaos_agent_scores(snapshot, season)
    active_rows = _most_active_scores(snapshot, season)
    silent_rows = _silent_assassin_scores(snapshot, season)
    hammer_rows = _weekly_hammer_scores(snapshot, season)
    playoff_rows = _playoff_mvp_scores(snapshot, season)
    bad_beat_rows = _bad_beat_scores(snapshot, season)
    pick_rows = _pick_hoarder_scores(snapshot)

    def _add(race):
        if race:
            races.append(race)

    _add(_build_race(
        snapshot, "trader_of_the_year", "Trader of the Year", trader_rows,
        lambda r: {"pointsGained": r["pointsGained"], "trades": r["tradeCount"]},
    ))
    _add(_build_race(
        snapshot, "waiver_king", "Waiver King", waiver_rows,
        lambda r: {
            "pointsGained": r["pointsGained"],
            "adds": r.get("usefulAdds", 0),
            "faabEfficiency": r.get("faabEfficiency"),
        },
    ))
    _add(_build_race(
        snapshot, "chaos_agent", "Chaos Agent", chaos_rows,
        lambda r: {"score": r["score"], "trades": r["trades"], "partners": r["distinctPartners"]},
    ))
    _add(_build_race(
        snapshot, "most_active", "Most Active", active_rows,
        lambda r: {"total": r["total"], "trades": r["trades"], "waivers": r["waivers"]},
    ))
    _add(_build_race(
        snapshot, "silent_assassin", "Silent Assassin", silent_rows,
        lambda r: {"winPct": r["winPct"], "closeGames": r["closeGames"], "closeWins": r["closeWins"]},
        eligible_only=True,
    ))
    _add(_build_race(
        snapshot, "weekly_hammer", "Weekly Hammer", hammer_rows,
        lambda r: {"highScoreFinishes": r["highScoreFinishes"], "highestWeek": r["highestWeekPoints"]},
    ))
    playoff_mvp_rows = _playoff_mvp_player_rows(snapshot, season)
    if playoff_mvp_rows:
        race = {
            "key": "playoff_mvp",
            "label": "Playoff MVP",
            "description": AWARD_DESCRIPTIONS["playoff_mvp"],
            "leaders": [
                {
                    "rank": i + 1,
                    "ownerId": r["ownerId"],
                    "displayName": r["displayName"],
                    "value": {
                        "playerId": r["playerId"],
                        "playerName": r["playerName"],
                        "team": r.get("team", ""),
                        "position": r["position"],
                        "vorp": r["vorp"],
                        "starterPoints": r["starterPoints"],
                    },
                }
                for i, r in enumerate(playoff_mvp_rows[:3])
            ],
        }
        _add(race)
    _add(_build_race(
        snapshot, "bad_beat", "Bad Beat", bad_beat_rows,
        lambda r: {
            "points": r["biggestLoss"],
            "week": r["biggestLossWeek"],
        },
    ))
    _add(_build_race(
        snapshot, "pick_hoarder", "Pick Hoarder", pick_rows,
        lambda r: {"weightedScore": r["weightedScore"], "totalPicks": r["totalPicks"]},
    ))

    # ── Manager-award races ──
    offense_rows = _top_offense_scores(snapshot, season)
    _add(_build_race(
        snapshot, "top_offense", "Top Offense Race", offense_rows,
        lambda r: {"offensePoints": r["offensePoints"]},
    ))
    defense_rows = _top_defense_scores(snapshot, season)
    if defense_rows:
        _add(_build_race(
            snapshot, "top_defense", "Top Defense Race", defense_rows,
            lambda r: {"defensePoints": r["defensePoints"]},
        ))
    moty_rows = _manager_of_the_year_scores(snapshot, season)
    _add(_build_race(
        snapshot, "manager_of_the_year", "Manager of the Year Race", moty_rows,
        lambda r: {
            "compositeScore": r["compositeScore"],
            "wins": r["wins"],
            "losses": r["losses"],
            "winPct": r["winPct"],
            "pointsFor": r["pointsFor"],
        },
    ))

    # ── Player-award races (top 3 per position) ──
    player_rows_by_pos = _top_player_per_position_scores(
        snapshot, season, regular_season_only=True
    )
    for pos in _PLAYER_AWARD_POSITIONS:
        rows = player_rows_by_pos.get(pos) or []
        rows = [r for r in rows if r["starterPoints"] > 0]
        if not rows:
            continue
        race = {
            "key": _PLAYER_AWARD_KEY_BY_POS[pos],
            "label": f"{_PLAYER_AWARD_LABEL_BY_POS[pos]} Race",
            "description": AWARD_DESCRIPTIONS[_PLAYER_AWARD_KEY_BY_POS[pos]],
            "leaders": [
                {
                    "rank": i + 1,
                    "ownerId": r["ownerId"],
                    "displayName": r["displayName"],
                    "value": {
                        "playerId": r["playerId"],
                        "playerName": r["playerName"],
                        "team": r.get("team", ""),
                        "position": r["position"],
                        "starterPoints": r["starterPoints"],
                        "gamesStarted": r["gamesStarted"],
                    },
                }
                for i, r in enumerate(rows[:3])
            ],
        }
        _add(race)

    # ── League MVP race ──
    mvp_rows = _league_mvp_rows(snapshot, season)
    if mvp_rows:
        race = {
            "key": "league_mvp",
            "label": "League MVP Race",
            "description": AWARD_DESCRIPTIONS["league_mvp"],
            "leaders": [
                {
                    "rank": i + 1,
                    "ownerId": r["ownerId"],
                    "displayName": r["displayName"],
                    "value": {
                        "playerId": r["playerId"],
                        "playerName": r["playerName"],
                        "team": r.get("team", ""),
                        "position": r["position"],
                        "vorp": r["vorp"],
                        "starterPoints": r["starterPoints"],
                        "gamesStarted": r["gamesStarted"],
                    },
                }
                for i, r in enumerate(mvp_rows[:3])
            ],
        }
        _add(race)

    return races


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    by_season: list[dict[str, Any]] = []
    for idx, season in enumerate(snapshot.seasons):
        prev = snapshot.seasons[idx + 1] if idx + 1 < len(snapshot.seasons) else None
        canonical = _season_canonical_awards(snapshot, season)
        activity_based = _activity_awards_for_season(snapshot, season, prev)
        by_season.append({
            "season": season.season,
            "leagueId": season.league_id,
            "seasonStatus": str(season.league.get("status") or ""),
            "isComplete": season.is_complete,
            "hasPlayerScoring": _season_has_player_scoring(season),
            "awards": canonical + activity_based,
        })

    races: list[dict[str, Any]] = []
    current = snapshot.current_season
    if current is not None and not current.is_complete:
        races = _current_season_races(snapshot, current)

    hottest = None
    for race in races:
        if race.get("leaders"):
            hottest = {
                "key": race["key"],
                "label": race["label"],
                "description": race["description"],
                "topLeader": race["leaders"][0],
            }
            break

    return {
        "bySeason": by_season,
        "awardRaces": races,
        "currentSeason": current.season if current else None,
        "currentSeasonStatus": "in_progress" if (current and not current.is_complete) else "complete",
        "hottestRace": hottest,
        "descriptions": AWARD_DESCRIPTIONS,
    }
