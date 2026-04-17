"""Public league snapshot — pipeline that fetches the last N dynasty
seasons from Sleeper and hands a normalized shape to every section
module.

This module MUST NOT read the private canonical pipeline, the private
``latest_data`` / ``latest_contract_data`` state, or any file
containing private rankings / edge signals.  The only inputs are the
league id + the Sleeper public API (via ``sleeper_client``).

The snapshot is intentionally "dumb": it pulls the raw Sleeper
payloads and normalizes them minimally (identity, season ordering,
regular-season-vs-playoff week partitioning).  Section modules do the
actual compute on top of this snapshot so every section sees the same
consistent input.

Cold-fetch performance: a full snapshot is ~85 HTTP GETs against
Sleeper (2 seasons × {users, rosters, 18 matchups, 18 transactions,
drafts, picks, bracket, losers bracket, traded picks}).  We parallelize
everything inside a single snapshot build via a ``ThreadPoolExecutor``
so the wall-clock drops from ~8 s sequential to ~400 ms.  The
executor is scoped to each ``build_public_snapshot`` call so there's
no global shared state.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import sleeper_client
from .identity import ManagerRegistry, build_manager_registry
from .sleeper_client import PUBLIC_MAX_SEASONS


# Concurrency cap for the fetch pool.  Sleeper tolerates a reasonable
# burst (a dozen-or-so parallel GETs); we stay well below that.
_FETCH_CONCURRENCY = 12


# Weeks we will pull matchup + transaction payloads for.  Regular
# season + full playoffs covers every dynasty scoring format Sleeper
# supports today.  Weeks with no games return [] from Sleeper so the
# over-fetch is cheap.
MAX_WEEKS = 18
_WEEK_RANGE = range(1, MAX_WEEKS + 1)

# Default playoff start week used when Sleeper does not surface one.
# 15 matches the most common dynasty / standard league format.
DEFAULT_PLAYOFF_WEEK_START = 15


@dataclass
class SeasonSnapshot:
    """All Sleeper data the public pipeline needs for one season."""
    season: str
    league_id: str
    league: dict[str, Any]
    users: list[dict[str, Any]]
    rosters: list[dict[str, Any]]
    matchups_by_week: dict[int, list[dict[str, Any]]]
    transactions_by_week: dict[int, list[dict[str, Any]]]
    drafts: list[dict[str, Any]]
    draft_picks_by_draft: dict[str, list[dict[str, Any]]]
    traded_picks: list[dict[str, Any]]
    winners_bracket: list[dict[str, Any]]
    losers_bracket: list[dict[str, Any]]

    @property
    def is_complete(self) -> bool:
        """True if the season looks finished / post-playoffs."""
        status = str(self.league.get("status") or "").lower()
        return status in {"complete", "post_season", "postseason"}

    @property
    def season_type(self) -> str:
        return str(self.league.get("season_type") or "regular")

    @property
    def num_teams(self) -> int:
        total_rosters = int(self.league.get("total_rosters") or 0)
        if total_rosters:
            return total_rosters
        return len(self.rosters)

    @property
    def playoff_week_start(self) -> int:
        """First playoff week.  Falls back to ``DEFAULT_PLAYOFF_WEEK_START``.

        Sleeper stores this on the league ``settings`` block under
        ``playoff_week_start``.  We accept an integer-ish string as well.
        """
        settings = self.league.get("settings") or {}
        raw = settings.get("playoff_week_start")
        try:
            val = int(raw)
            if val > 0:
                return val
        except (TypeError, ValueError):
            pass
        return DEFAULT_PLAYOFF_WEEK_START

    @property
    def regular_season_weeks(self) -> list[int]:
        """Weeks that count toward regular-season standings."""
        start_playoffs = self.playoff_week_start
        return sorted(w for w in self.matchups_by_week if w < start_playoffs)

    @property
    def playoff_weeks(self) -> list[int]:
        start_playoffs = self.playoff_week_start
        return sorted(w for w in self.matchups_by_week if w >= start_playoffs)

    @property
    def all_weeks(self) -> list[int]:
        return sorted(self.matchups_by_week.keys())

    def trades(self) -> list[dict[str, Any]]:
        """Flatten all completed trades across weeks (chronological)."""
        out: list[dict[str, Any]] = []
        for week in sorted(self.transactions_by_week.keys()):
            for tx in self.transactions_by_week[week]:
                if str(tx.get("type") or "").lower() != "trade":
                    continue
                if str(tx.get("status") or "").lower() != "complete":
                    continue
                out.append({**tx, "_leg": week})
        out.sort(key=lambda tx: int(tx.get("created") or tx.get("status_updated") or 0))
        return out

    def waivers(self) -> list[dict[str, Any]]:
        """Flatten all completed waiver / FA transactions across weeks."""
        out: list[dict[str, Any]] = []
        for week in sorted(self.transactions_by_week.keys()):
            for tx in self.transactions_by_week[week]:
                ttype = str(tx.get("type") or "").lower()
                if ttype not in {"waiver", "free_agent"}:
                    continue
                if str(tx.get("status") or "").lower() != "complete":
                    continue
                out.append({**tx, "_leg": week})
        out.sort(key=lambda tx: int(tx.get("created") or tx.get("status_updated") or 0))
        return out


@dataclass
class PublicLeagueSnapshot:
    """Top-level public snapshot — one per request (cheap to rebuild)."""
    root_league_id: str
    generated_at: str
    seasons: list[SeasonSnapshot] = field(default_factory=list)
    managers: ManagerRegistry = field(default_factory=ManagerRegistry)
    # Keyed by str(player_id) — Sleeper player dump.  May be empty if
    # the NFL players endpoint was unreachable.
    nfl_players: dict[str, Any] = field(default_factory=dict)

    @property
    def current_season(self) -> SeasonSnapshot | None:
        return self.seasons[0] if self.seasons else None

    @property
    def previous_seasons(self) -> list[SeasonSnapshot]:
        return self.seasons[1:]

    @property
    def season_ids(self) -> list[str]:
        return [s.season for s in self.seasons]

    @property
    def league_ids(self) -> list[str]:
        return [s.league_id for s in self.seasons]

    def season_by_league_id(self, league_id: str) -> SeasonSnapshot | None:
        want = str(league_id or "")
        for s in self.seasons:
            if s.league_id == want:
                return s
        return None

    def season_by_year(self, season: str | int) -> SeasonSnapshot | None:
        want = str(season)
        for s in self.seasons:
            if s.season == want:
                return s
        return None

    def player_display(self, player_id: str | None) -> str:
        """Return a human-readable name for a Sleeper player_id, or ``""``."""
        if not player_id:
            return ""
        p = self.nfl_players.get(str(player_id))
        if not isinstance(p, dict):
            return ""
        full = p.get("full_name")
        if full:
            return str(full)
        first = str(p.get("first_name") or "").strip()
        last = str(p.get("last_name") or "").strip()
        return f"{first} {last}".strip() or str(player_id)

    def player_position(self, player_id: str | None) -> str:
        if not player_id:
            return ""
        p = self.nfl_players.get(str(player_id))
        if not isinstance(p, dict):
            return ""
        return str(p.get("position") or "").upper()


def _fetch_season(
    league_obj: dict[str, Any],
    executor: ThreadPoolExecutor,
) -> SeasonSnapshot:
    """Materialize a single SeasonSnapshot from a league object.

    Every Sleeper GET for the season is submitted to ``executor`` up
    front; we only block on the final ``.result()`` calls.  That lets
    two seasons of ~40 GETs each run concurrently against Sleeper
    without any thread-per-call overhead.
    """
    league_id = str(league_obj.get("league_id") or "")

    users_fut = executor.submit(sleeper_client.fetch_users, league_id)
    rosters_fut = executor.submit(sleeper_client.fetch_rosters, league_id)
    drafts_fut = executor.submit(sleeper_client.fetch_drafts, league_id)
    traded_picks_fut = executor.submit(sleeper_client.fetch_traded_picks, league_id)
    winners_fut = executor.submit(sleeper_client.fetch_winners_bracket, league_id)
    losers_fut = executor.submit(sleeper_client.fetch_losers_bracket, league_id)

    matchup_futs = {
        week: executor.submit(sleeper_client.fetch_matchups, league_id, week)
        for week in _WEEK_RANGE
    }
    tx_futs = {
        week: executor.submit(sleeper_client.fetch_transactions, league_id, week)
        for week in _WEEK_RANGE
    }

    matchups: dict[int, list[dict[str, Any]]] = {}
    for week, fut in matchup_futs.items():
        result = fut.result()
        if result:
            matchups[week] = result
    transactions: dict[int, list[dict[str, Any]]] = {}
    for week, fut in tx_futs.items():
        result = fut.result()
        if result:
            transactions[week] = result

    drafts = drafts_fut.result()
    draft_picks_by_draft: dict[str, list[dict[str, Any]]] = {}
    if drafts:
        pick_futs = {
            str(d.get("draft_id") or ""): executor.submit(
                sleeper_client.fetch_draft_picks, str(d.get("draft_id") or "")
            )
            for d in drafts
            if d.get("draft_id")
        }
        for draft_id, fut in pick_futs.items():
            draft_picks_by_draft[draft_id] = fut.result() or []

    season_key = str(league_obj.get("season") or "")
    return SeasonSnapshot(
        season=season_key,
        league_id=league_id,
        league=league_obj,
        users=users_fut.result(),
        rosters=rosters_fut.result(),
        matchups_by_week=matchups,
        transactions_by_week=transactions,
        drafts=drafts,
        draft_picks_by_draft=draft_picks_by_draft,
        traded_picks=traded_picks_fut.result(),
        winners_bracket=winners_fut.result(),
        losers_bracket=losers_fut.result(),
    )


def build_public_snapshot(
    root_league_id: str,
    max_seasons: int = PUBLIC_MAX_SEASONS,
    include_nfl_players: bool = True,
) -> PublicLeagueSnapshot:
    """Build a PublicLeagueSnapshot for the last ``max_seasons`` dynasty
    seasons starting from ``root_league_id``.

    The chain walk follows Sleeper ``previous_league_id`` links.  If
    the chain is shorter than ``max_seasons`` (e.g. league is in its
    first season), the snapshot simply has fewer entries — every
    section module handles the short case.

    ``include_nfl_players`` controls whether we fetch the ~5 MB
    players/nfl dump.  Tests pass ``False``; production fetches it.
    """
    snapshot = PublicLeagueSnapshot(
        root_league_id=str(root_league_id or "").strip(),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if not snapshot.root_league_id:
        return snapshot

    chain = sleeper_client.walk_league_chain(snapshot.root_league_id, max_seasons=max_seasons)
    if not chain:
        return snapshot

    # One executor spans the entire snapshot build so both seasons AND
    # their ~40-each matchup/transaction GETs all race in parallel.
    with ThreadPoolExecutor(
        max_workers=_FETCH_CONCURRENCY,
        thread_name_prefix="public-league-fetch",
    ) as pool:
        nfl_fut = None
        if include_nfl_players:
            nfl_fut = pool.submit(sleeper_client.fetch_nfl_players)
        season_futs = [pool.submit(_fetch_season, league, pool) for league in chain]
        snapshot.seasons = [f.result() for f in season_futs]
        if nfl_fut is not None:
            try:
                snapshot.nfl_players = nfl_fut.result() or {}
            except Exception:  # noqa: BLE001
                snapshot.nfl_players = {}

    snapshot.managers = build_manager_registry(
        [
            {
                "league": s.league,
                "users": s.users,
                "rosters": s.rosters,
            }
            for s in snapshot.seasons
        ]
    )
    return snapshot
