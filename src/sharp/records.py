"""Multi-season manager records for the Sharp Score.

Discovery (``discovery.py``) finds MANAGERS.  The Sharp Score needs
RECORDS — completed seasons, win/loss, playoff appearances,
championships, finishes — and transactions cannot supply any of that.
This is the second crawl pass that closes the gap, and until it runs no
manager can be scored at all.

──────────────────────────────────────────────────────────────────────
Reuses ``src/public_league/`` rather than reimplementing it
──────────────────────────────────────────────────────────────────────
That package already walks ``previous_league_id`` chains and derives
records, playoff fields and champions, and its logic was verified live
against three seasons of the home league.  Writing a second parser would
be exactly the "competing implementation" this codebase keeps getting
bitten by, so:

    sleeper_client.walk_league_chain        chain walk, with loop guard
    metrics.regular_season_settings_record  W/L/PF/PA, correct /100 math
    metrics.playoff_teams                   from the winners bracket
    metrics.season_champion / _runner_up    p==1 semantics + fallback

What is NOT reused is ``snapshot.build_public_snapshot``: it budgets
~85 GETs per season because it also pulls 18 weeks of matchups and
transactions.  A records pass needs four calls per league-season
(league, users, rosters, winners_bracket), so this module assembles a
minimal ``SeasonSnapshot`` itself — the dataclass is plain, and the
metric functions only read the fields we populate.

──────────────────────────────────────────────────────────────────────
Facts verified live, worth not rediscovering
──────────────────────────────────────────────────────────────────────
* ``previous_league_id`` terminates at the STRING ``"0"``, not null and
  not absent.  A falsy-only check walks off the end.
* ``roster["settings"]`` key sets VARY BY SEASON — 2024 lacks
  ``locked``, and an IN-SEASON roster omits ``fpts_against`` / ``ppts``
  entirely (keys absent, not zero).  Always ``.get`` with a default.
* ``rank`` is never present.  Finish order must be derived.
* Playoff participants come from the winners bracket only; the losers
  bracket is not needed and its ``p==1`` winner is the CONSOLATION
  winner, which is not a playoff result worth crediting.

──────────────────────────────────────────────────────────────────────
Only completed seasons count
──────────────────────────────────────────────────────────────────────
An in-progress season has no final standing, no champion, and a partial
record.  Counting it would let a manager sitting at 3-0 in week 3 look
like a 100% win-rate season.  Rows are stored for in-season leagues (so
coverage is inspectable) but ``is_complete`` is 0 and the scorer ignores
them.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.intel import ledger, league_filter
from src.sharp import score as sharp_score

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

# Sleeper's chain terminator. Not None, not "" — the literal string "0".
_CHAIN_TERMINATOR = "0"

# 4 calls per league-season (league, users, rosters, winners_bracket).
CALLS_PER_SEASON = 4
DEFAULT_BUDGET = 1200
DEFAULT_SLEEP_S = 0.12
MAX_SEASONS_PER_LEAGUE = 6

HttpGet = Callable[[str], Any]


def _default_http_get(url: str) -> Any:
    from src.api import sleeper_overlay

    return sleeper_overlay._http_get_json(url)


@dataclass
class RecordsResult:
    leagues_examined: int = 0
    seasons_recorded: int = 0
    completed_seasons: int = 0
    managers_touched: int = 0
    calls_used: int = 0
    budget_exhausted: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguesExamined": self.leagues_examined,
            "seasonsRecorded": self.seasons_recorded,
            "completedSeasons": self.completed_seasons,
            "managersTouched": self.managers_touched,
            "callsUsed": self.calls_used,
            "budgetExhausted": self.budget_exhausted,
            "errors": self.errors[:20],
        }


class _Budget:
    def __init__(self, budget: int, sleep_s: float, http_get: HttpGet, sleep_fn=time.sleep):
        self.remaining = max(0, int(budget))
        self.used = 0
        self._sleep_s = max(0.0, float(sleep_s))
        self._get = http_get
        self._sleep = sleep_fn

    def can_call(self, n: int = 1) -> bool:
        return self.remaining >= n

    def get(self, url: str) -> Any:
        if self.remaining <= 0:
            return None
        if self.used > 0 and self._sleep_s > 0:
            self._sleep(self._sleep_s)
        self.remaining -= 1
        self.used += 1
        return self._get(url)


def _finish_ranks(rosters: list[dict[str, Any]]) -> dict[str, int]:
    """Regular-season finish order, 1 = best.

    Sleeper publishes no ``rank``, so it is derived the way a league
    standings page does: wins, then points-for as the tiebreak.
    """
    scored = []
    for r in rosters:
        if not isinstance(r, dict):
            continue
        rid = r.get("roster_id")
        if rid is None:
            continue
        settings = r.get("settings") or {}
        wins = int(settings.get("wins") or 0)
        ties = int(settings.get("ties") or 0)
        pf = float(settings.get("fpts") or 0) + float(settings.get("fpts_decimal") or 0) / 100.0
        scored.append((wins + 0.5 * ties, pf, str(rid)))
    scored.sort(key=lambda t: (-t[0], -t[1]))
    return {rid: i + 1 for i, (_w, _pf, rid) in enumerate(scored)}


def _season_rows(
    league: dict[str, Any],
    rosters: list[dict[str, Any]],
    winners_bracket: list[dict[str, Any]],
    *,
    sharp_eligible: bool,
) -> list[dict[str, Any]]:
    """One row per manager for one league-season."""
    from src.public_league import metrics
    from src.public_league.snapshot import SeasonSnapshot

    league_id = str(league.get("league_id") or "")
    season = str(league.get("season") or "")
    status = str(league.get("status") or "").lower()
    is_complete = status in ("complete", "post_season", "postseason")

    # Minimal snapshot — the metric helpers read only these fields.
    snap = SeasonSnapshot(
        season=season,
        league_id=league_id,
        league=league,
        users=[],
        rosters=rosters,
        matchups_by_week={},
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=winners_bracket or [],
        losers_bracket=[],
    )

    playoff_rids = {str(r) for r in metrics.playoff_teams(winners_bracket or [])}
    champion = metrics.season_champion(snap) if is_complete else None
    runner_up = metrics.season_runner_up(snap) if is_complete else None
    ranks = _finish_ranks(rosters)
    now = int(time.time() * 1000)

    rows = []
    for roster in rosters:
        if not isinstance(roster, dict):
            continue
        owner = str(roster.get("owner_id") or "").strip()
        rid = roster.get("roster_id")
        if not owner or rid is None:
            continue  # orphaned roster — no manager to credit
        rid_s = str(rid)
        rec = metrics.regular_season_settings_record(roster)
        rows.append(
            {
                "league_id": league_id,
                "season": season,
                "user_id": owner,
                "roster_id": rid_s,
                "wins": int(rec.get("wins") or 0),
                "losses": int(rec.get("losses") or 0),
                "ties": int(rec.get("ties") or 0),
                "points_for": float(rec.get("points_for") or 0.0),
                "points_against": float(rec.get("points_against") or 0.0),
                "made_playoffs": 1 if rid_s in playoff_rids else 0,
                "is_champion": 1 if (champion is not None and str(champion) == rid_s) else 0,
                "is_runner_up": 1 if (runner_up is not None and str(runner_up) == rid_s) else 0,
                "finish_rank": ranks.get(rid_s),
                "team_count": len(rosters),
                "is_complete": 1 if is_complete else 0,
                "sharp_eligible": 1 if sharp_eligible else 0,
                "crawled_ms": now,
            }
        )
    return rows


def _store_rows(rows: list[dict[str, Any]], *, conn) -> int:
    written = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO manager_seasons
              (league_id, season, user_id, roster_id, wins, losses, ties,
               points_for, points_against, made_playoffs, is_champion,
               is_runner_up, finish_rank, team_count, is_complete,
               sharp_eligible, crawled_ms)
            VALUES (:league_id, :season, :user_id, :roster_id, :wins, :losses, :ties,
                    :points_for, :points_against, :made_playoffs, :is_champion,
                    :is_runner_up, :finish_rank, :team_count, :is_complete,
                    :sharp_eligible, :crawled_ms)
            ON CONFLICT(league_id, season, user_id) DO UPDATE SET
              roster_id=excluded.roster_id, wins=excluded.wins,
              losses=excluded.losses, ties=excluded.ties,
              points_for=excluded.points_for,
              points_against=excluded.points_against,
              made_playoffs=excluded.made_playoffs,
              is_champion=excluded.is_champion,
              is_runner_up=excluded.is_runner_up,
              finish_rank=excluded.finish_rank,
              team_count=excluded.team_count,
              is_complete=excluded.is_complete,
              sharp_eligible=excluded.sharp_eligible,
              crawled_ms=excluded.crawled_ms
            """,
            row,
        )
        written += 1
    return written


def crawl_records(
    *,
    league_ids: list[str] | None = None,
    http_get: HttpGet | None = None,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = DEFAULT_SLEEP_S,
    max_seasons: int = MAX_SEASONS_PER_LEAGUE,
    ledger_path=None,
    sleep_fn=time.sleep,
) -> RecordsResult:
    """Walk each league's season chain and record every manager's result.

    Defaults to the SHARP-eligible leagues in the ledger (dynasty only,
    >= 2 seasons old): those are the only leagues whose results may
    certify a manager, so spending budget elsewhere buys nothing for the
    cohort.

    Idempotent — rows upsert on (league_id, season, user_id).
    """
    http = http_get or _default_http_get
    b = _Budget(budget, sleep_s, http, sleep_fn=sleep_fn)
    result = RecordsResult()

    if league_ids is None:
        from src.sharp import discovery

        league_ids = discovery.sharp_eligible_league_ids(ledger_path=ledger_path)

    seen_leagues: set[str] = set()
    touched_managers: set[str] = set()
    conn = ledger.connect(ledger_path)
    try:
        for start_id in league_ids:
            if not b.can_call(CALLS_PER_SEASON):
                break
            current = str(start_id)
            hops = 0
            while current and current != _CHAIN_TERMINATOR and hops < max_seasons:
                if current in seen_leagues:
                    break  # loop guard — a chain must never revisit
                if not b.can_call(CALLS_PER_SEASON):
                    break
                seen_leagues.add(current)
                hops += 1

                league = b.get(f"{SLEEPER_BASE}/league/{current}")
                if not isinstance(league, dict):
                    result.errors.append(f"league_fetch_failed:{current}")
                    break
                result.leagues_examined += 1

                rosters = b.get(f"{SLEEPER_BASE}/league/{current}/rosters")
                if not isinstance(rosters, list):
                    result.errors.append(f"rosters_fetch_failed:{current}")
                    current = str(league.get("previous_league_id") or "")
                    continue

                status = str(league.get("status") or "").lower()
                is_complete = status in ("complete", "post_season", "postseason")
                bracket: list[dict[str, Any]] = []
                if is_complete and b.can_call():
                    raw = b.get(f"{SLEEPER_BASE}/league/{current}/winners_bracket")
                    if isinstance(raw, list):
                        bracket = raw

                rows = _season_rows(
                    league,
                    rosters,
                    bracket,
                    sharp_eligible=league_filter.is_sharp_eligible(league),
                )
                result.seasons_recorded += 1
                if is_complete:
                    result.completed_seasons += 1
                for row in rows:
                    touched_managers.add(row["user_id"])
                _store_rows(rows, conn=conn)

                current = str(league.get("previous_league_id") or "")
        conn.commit()
    finally:
        conn.close()

    result.calls_used = b.used
    result.budget_exhausted = not b.can_call(CALLS_PER_SEASON)
    result.managers_touched = len(touched_managers)
    log.info("sharp.records: %s", result.to_dict())
    return result


# ── records -> ManagerRecord ─────────────────────────────────────────


def build_manager_records(
    *,
    ledger_path=None,
    min_season_rows: int = 1,
) -> list[sharp_score.ManagerRecord]:
    """Assemble scoreable ``ManagerRecord``s from the stored seasons.

    ONLY completed, sharp-eligible seasons contribute.  An in-progress
    season has no final standing and a partial record; counting it would
    let a 3-0 start read as a perfect season.
    """
    conn = ledger.connect(ledger_path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM manager_seasons
             WHERE is_complete = 1 AND sharp_eligible = 1
            """
        ).fetchall()
        activity = {
            r["user_id"]: r["n"]
            for r in conn.execute(
                """
                SELECT user_id, COUNT(DISTINCT tx_id) AS n
                  FROM asset_movements
                 WHERE tx_type = 'trade'
                 GROUP BY user_id
                """
            ).fetchall()
        }
        last_seen = {
            r["user_id"]: r["ts"]
            for r in conn.execute(
                "SELECT user_id, MAX(ts) AS ts FROM asset_movements GROUP BY user_id"
            ).fetchall()
        }
    finally:
        conn.close()

    by_user: dict[str, list[Any]] = {}
    for row in rows:
        by_user.setdefault(str(row["user_id"]), []).append(row)

    now_ms = int(time.time() * 1000)
    out: list[sharp_score.ManagerRecord] = []
    for user_id, seasons in by_user.items():
        if len(seasons) < min_season_rows:
            continue
        leagues = {str(s["league_id"]) for s in seasons}
        wins = sum(int(s["wins"] or 0) for s in seasons)
        losses = sum(int(s["losses"] or 0) for s in seasons)
        ties = sum(int(s["ties"] or 0) for s in seasons)

        finishes = []
        for s in seasons:
            rank = s["finish_rank"]
            teams = s["team_count"]
            if rank and teams and teams > 1:
                # 1.0 = first, 0.0 = last.
                finishes.append((teams - int(rank)) / float(teams - 1))

        last_ts = last_seen.get(user_id)
        days_idle = int((now_ms - int(last_ts)) / 86_400_000) if last_ts else None

        out.append(
            sharp_score.ManagerRecord(
                user_id=user_id,
                completed_seasons=len(seasons),
                observed_leagues=len(leagues),
                # Every row here is already sharp-eligible (dynasty,
                # >= 2 seasons old), so the league count IS the
                # qualifying-dynasty-league count the gate reads.
                dynasty_leagues=len(leagues),
                completed_games=wins + losses + ties,
                wins=wins,
                losses=losses,
                ties=ties,
                playoff_appearances=sum(1 for s in seasons if s["made_playoffs"]),
                championships=sum(1 for s in seasons if s["is_champion"]),
                finish_percentiles=finishes,
                trades_completed=int(activity.get(user_id, 0)),
                days_since_last_activity=days_idle,
            )
        )
    return out


def records_coverage(*, ledger_path=None) -> dict[str, Any]:
    conn = ledger.connect(ledger_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS rows_total,
                   COUNT(DISTINCT user_id) AS managers,
                   COUNT(DISTINCT league_id) AS leagues,
                   SUM(is_complete) AS complete_rows,
                   MIN(season) AS earliest_season,
                   MAX(season) AS latest_season
              FROM manager_seasons
            """
        ).fetchone()
    finally:
        conn.close()
    return {
        "seasonRows": int(row["rows_total"] or 0),
        "completedSeasonRows": int(row["complete_rows"] or 0),
        "managersWithRecords": int(row["managers"] or 0),
        "leaguesWithRecords": int(row["leagues"] or 0),
        "earliestSeason": row["earliest_season"],
        "latestSeason": row["latest_season"],
    }
