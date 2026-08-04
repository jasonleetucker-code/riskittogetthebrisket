"""Collect the CURRENT rosters of the sharp cohort, on both platforms.

The third crawl pass.  ``discovery.py`` finds MANAGERS, ``records.py``
finds their RESULTS, and this finds what they currently OWN — the fact a
roster percentage is made of, which nothing in the tree persisted.

The cohort is not re-derived here
─────────────────────────────────
The manager pool comes from ``src/sharp/cohort.py::cohort_members`` —
the same call the Sharp Buy/Sell Tracker makes.  This module decides
only which of that pool's ROSTERS are observable and eligible.  It has
no notion of who qualifies as a sharp and must never grow one.

Budget
──────
Two Sleeper calls per league (``/league/{id}`` for format + status,
``/league/{id}/rosters`` for the holdings), paced by the same ``_Budget``
shape ``records.py`` uses.  Leagues are visited once regardless of how
many cohort members play in them, so a league shared by five sharps
costs two calls, not ten.

FFPC costs ZERO calls: its roster contents already arrive through the
public-page crawl and sit in ``platform_memberships.metadata_json``
under ``rosterAssets``.  This pass only lifts them into the queryable
store.

Nothing is silently dropped
───────────────────────────
Every roster reached is written, eligible or not, with its exclusion
reasons attached.  A roster that fails a gate becomes an auditable row
rather than an absence, which is what makes "why is the denominator
smaller than the cohort" answerable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from src.intel import league_filter, platform_ledger
from src.sharp import cohort as sharp_cohort
from src.sharp import roster_store

log = logging.getLogger(__name__)

SLEEPER_BASE = "https://api.sleeper.app/v1"

CALLS_PER_LEAGUE = 2
DEFAULT_BUDGET = 600
DEFAULT_SLEEP_S = 0.15

# Sleeper league statuses that mean the league is not a live dynasty
# team any more.  ``complete`` is normal at season end and is NOT an
# exclusion — a completed 2026 league still describes real ownership
# until the rollover.
_ABANDONED_STATUSES = {"abandoned", "deleted", "archived"}

# Identity confidence below which we will not attribute a roster.  FFPC
# league-scoped team identities sit at 0.70 and are accepted; name-only
# identities sit at 0.25 and are not — attributing a roster to a manager
# matched on a display-name hash is exactly the "uncertain identity
# matching" case the audit requires us to exclude.
MIN_IDENTITY_CONFIDENCE = 0.5

HttpGet = Callable[[str], Any]

# ── exclusion reasons (the audit vocabulary) ─────────────────────────
REASON_LEAGUE_NOT_SHARP_ELIGIBLE = "league_not_sharp_eligible"
REASON_INCOMPATIBLE_FORMAT = "incompatible_league_format"
REASON_ABANDONED_LEAGUE = "abandoned_or_inactive_league"
REASON_ORPHANED_ROSTER = "orphaned_roster_no_owner"
REASON_INCOMPLETE_ROSTER = "incomplete_roster_data"
REASON_UNCERTAIN_IDENTITY = "uncertain_identity_match"
REASON_NO_CANONICAL_ASSETS = "no_mappable_players"
# A prior season of a league whose current season we also collected.
# See ``_collapse_season_chains`` — one dynasty league is one roster,
# however many seasons of it we have observed.
REASON_SUPERSEDED_SEASON = "superseded_by_later_season"


def _default_http_get(url: str) -> Any:
    # Same reasoning as ``records.py``: a paced batch job must not ride
    # the user-request circuit breaker, whose open state would burn
    # budget on instant ``None``s without touching Sleeper.
    from src.public_league import sleeper_client

    return sleeper_client._request_json(url)


@dataclass
class CollectResult:
    leagues_examined: int = 0
    rosters_recorded: int = 0
    eligible_rosters: int = 0
    excluded_rosters: int = 0
    assets_recorded: int = 0
    unmapped_assets: int = 0
    calls_used: int = 0
    budget_exhausted: bool = False
    # Leagues the budget did not reach this run. Published so an operator
    # can size ``--budget`` from the journal instead of guessing: a run
    # that ends with this at 0 is keeping up, and a run that ends with a
    # stable non-zero number needs a bigger budget rather than patience.
    leagues_remaining: int = 0
    exclusion_reasons: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def note_exclusions(self, reasons: Sequence[str]) -> None:
        for reason in reasons:
            self.exclusion_reasons[reason] = self.exclusion_reasons.get(reason, 0) + 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "leaguesExamined": self.leagues_examined,
            "rostersRecorded": self.rosters_recorded,
            "eligibleRosters": self.eligible_rosters,
            "excludedRosters": self.excluded_rosters,
            "assetsRecorded": self.assets_recorded,
            "unmappedAssets": self.unmapped_assets,
            "callsUsed": self.calls_used,
            "budgetExhausted": self.budget_exhausted,
            "leaguesRemaining": self.leagues_remaining,
            "exclusionReasons": dict(sorted(self.exclusion_reasons.items())),
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


# ── league format ────────────────────────────────────────────────────


def league_format(league: dict[str, Any] | None) -> dict[str, Any]:
    """The format facts the roster-percentage filters need.

    Derived from the ``/league/{id}`` payload the collector already
    fetches, so no extra call.  Every field is nullable and the readers
    treat ``None`` as "unknown", never as "false" — a filter must not
    quietly include a league whose format we could not determine.
    """
    if not isinstance(league, dict):
        return {}
    settings = league.get("settings") if isinstance(league.get("settings"), dict) else {}
    scoring = (
        league.get("scoring_settings") if isinstance(league.get("scoring_settings"), dict) else {}
    )
    positions = [str(p).upper() for p in (league.get("roster_positions") or []) if p]

    starting_qb = positions.count("QB")
    superflex = "SUPER_FLEX" in positions or "SFLEX" in positions or starting_qb >= 2
    idp_slots = [p for p in positions if p in ("DL", "LB", "DB", "IDP_FLEX", "DE", "DT", "CB", "S")]
    try:
        te_bonus = float(scoring.get("bonus_rec_te") or 0.0)
    except (TypeError, ValueError):
        te_bonus = 0.0

    return {
        "teams": league.get("total_rosters"),
        "season": league.get("season"),
        "status": str(league.get("status") or "") or None,
        "leagueType": league_filter.type_label(league),
        "superflex": bool(superflex) if positions else None,
        "startingQb": starting_qb if positions else None,
        "tePremium": (te_bonus > 0) if scoring else None,
        "teBonus": te_bonus if scoring else None,
        "idp": bool(idp_slots) if positions else None,
        # Whether the league even HAS a slot for these matters to the
        # denominator, not just to display: a kicker cannot be rostered
        # in a league with no K slot, so counting that league against
        # him would understate every kicker on the board.
        "kicker": ("K" in positions) if positions else None,
        "teamDefense": ("DEF" in positions or "DST" in positions) if positions else None,
        "taxiSlots": settings.get("taxi_slots"),
        "bestBall": bool(settings.get("best_ball")),
    }


def _contention(roster: dict[str, Any]) -> str:
    """``"contending" | "rebuilding" | "unknown"`` from the roster's own record.

    Deliberately the cheapest defensible signal: the current season's
    W/L already rides inside the ``/rosters`` payload, so this costs
    nothing.  Before any game is played there is no evidence either way,
    and that answers ``"unknown"`` rather than defaulting a whole
    preseason board into one bucket.

    This is NOT the BDVM contend/retool/rebuild classifier
    (``src/bdvm/roster.py``).  That one needs projections and a league
    config we do not have for arbitrary discovered leagues.
    """
    settings = roster.get("settings") if isinstance(roster.get("settings"), dict) else {}
    try:
        wins = int(settings.get("wins") or 0)
        losses = int(settings.get("losses") or 0)
        ties = int(settings.get("ties") or 0)
    except (TypeError, ValueError):
        return "unknown"
    played = wins + losses + ties
    if played < 4:
        return "unknown"
    win_pct = (wins + 0.5 * ties) / played
    if win_pct >= 0.55:
        return "contending"
    if win_pct <= 0.45:
        return "rebuilding"
    return "unknown"


# ── Sleeper ──────────────────────────────────────────────────────────


def _sleeper_assets(roster: dict[str, Any]) -> list[roster_store.RosterAsset]:
    """Every player the roster holds, slot-labelled.

    Sleeper's ``players`` array is the WHOLE roster — taxi and reserve
    players are members of it as well as of their own arrays.  So
    ``players`` is the membership truth and ``taxi``/``reserve`` are
    read only to LABEL those same ids.  Reading the three arrays as
    separate populations would double-count every taxi player; the
    store's primary key would collapse it anyway, but the label would
    then depend on insertion order.

    A taxi or IR player still counts as rostered, which is what the
    slot label exists to make visible rather than to filter on.
    """
    players = [str(p).strip() for p in (roster.get("players") or []) if str(p or "").strip()]
    taxi = {str(p).strip() for p in (roster.get("taxi") or []) if str(p or "").strip()}
    reserve = {str(p).strip() for p in (roster.get("reserve") or []) if str(p or "").strip()}
    out = []
    for player_id in players:
        if player_id in taxi:
            slot = roster_store.SLOT_TAXI
        elif player_id in reserve:
            slot = roster_store.SLOT_RESERVE
        else:
            slot = roster_store.SLOT_ACTIVE
        # Sleeper player ids ARE the canonical asset ids — see
        # ``src/platforms/assets.py``, which anchors the catalog on them.
        out.append(
            roster_store.RosterAsset(
                canonical_asset_id=player_id,
                asset_type="player",
                slot=slot,
                source_asset_id=player_id,
            )
        )
    return out


def _cohort_sleeper_leagues(
    manager_keys: Sequence[str],
    *,
    conn,
) -> dict[str, set[str]]:
    """``{source_league_id: {manager_key}}`` for the cohort's Sleeper leagues."""
    sleeper_keys = [k for k in manager_keys if str(k).startswith("sleeper:")]
    if not sleeper_keys:
        return {}
    out: dict[str, set[str]] = {}
    for start in range(0, len(sleeper_keys), 400):
        chunk = sleeper_keys[start : start + 400]
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            SELECT league_key, manager_key
              FROM platform_memberships
             WHERE platform='sleeper' AND manager_key IN ({placeholders})
            """,
            chunk,
        ).fetchall():
            league_key = str(row["league_key"] or "")
            if not league_key.startswith("sleeper:"):
                continue
            out.setdefault(league_key.split(":", 1)[1], set()).add(str(row["manager_key"]))
    return out


def _last_observed_by_league(conn) -> dict[str, int]:
    """``{source_league_id: newest observed_ms}`` from the roster store."""
    out: dict[str, int] = {}
    for row in conn.execute(
        """
        SELECT league_key, MAX(observed_ms) AS last_ms
          FROM sharp_rosters
         WHERE platform='sleeper'
         GROUP BY league_key
        """
    ).fetchall():
        league_key = str(row["league_key"] or "")
        if league_key.startswith("sleeper:") and row["last_ms"] is not None:
            out[league_key.split(":", 1)[1]] = int(row["last_ms"])
    return out


def _collection_order(league_ids: Sequence[str], *, conn) -> list[str]:
    """Fair, persistent crawl order for a BUDGETED pass.

    Reuses ``record_queue.prioritize_league_ids`` — the same ordering the
    records crawl uses — rather than adding a second notion of fairness:
    never-collected leagues first, then previously collected ones oldest
    first, ties stable by id.

    Without this the pass sorted by league id, so a run that hit its call
    budget re-collected the same alphabetical prefix on every subsequent
    run and the leagues after the cutoff were NEVER collected. That is
    not a slow rollout — it is a permanently invisible tail, and it would
    have been silent: the board would look healthy while systematically
    omitting part of the cohort.
    """
    from src.sharp import record_queue

    return record_queue.prioritize_league_ids(league_ids, _last_observed_by_league(conn))


def _collapse_season_chains(
    observations: list[roster_store.RosterObservation],
    leagues: dict[str, dict[str, Any]],
    result: CollectResult,
) -> list[roster_store.RosterObservation]:
    """Keep only the CURRENT season of each dynasty league chain.

    Sleeper mints a NEW ``league_id`` every season and links the old one
    through ``previous_league_id``.  A dynasty league we have observed
    for three years is therefore three ids for ONE league, and the sharp
    playing in it holds ONE team, not three.  Counting each id would
    inflate both the numerator and the denominator — and unevenly, since
    long-running leagues (the ones most likely to be sharp-eligible)
    would be weighted by their age.

    The chain data costs nothing: ``previous_league_id`` rides inside
    the ``/league/{id}`` payload already fetched for the format.  A
    league that is another collected league's predecessor is superseded;
    its rosters are still STORED, marked ineligible with
    ``superseded_by_later_season``, so the collapse is auditable rather
    than a silent disappearance.

    Chains reaching outside this run are unaffected — a predecessor we
    did not collect cannot be superseded by something we never saw, and
    guessing would drop a live league.
    """
    superseded = {
        str(league.get("previous_league_id") or "").strip()
        for league in leagues.values()
        if str(league.get("previous_league_id") or "").strip()
    } & set(leagues)
    if not superseded:
        return observations
    for observation in observations:
        league_id = observation.league_key.split(":", 1)[-1]
        if league_id in superseded:
            observation.exclusion_reasons = list(
                dict.fromkeys([*observation.exclusion_reasons, REASON_SUPERSEDED_SEASON])
            )
            result.note_exclusions([REASON_SUPERSEDED_SEASON])
    return observations


def collect_sleeper_rosters(
    *,
    manager_keys: Sequence[str],
    http_get: HttpGet | None = None,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = DEFAULT_SLEEP_S,
    ledger_path: Path | None = None,
    sleep_fn=time.sleep,
    now_ms: int | None = None,
    run_id: str | None = None,
) -> CollectResult:
    """Fetch and store the cohort's Sleeper rosters."""
    result = CollectResult()
    if not manager_keys:
        return result
    b = _Budget(budget, sleep_s, http_get or _default_http_get, sleep_fn=sleep_fn)
    now = int(now_ms if now_ms is not None else time.time() * 1000)

    conn = roster_store.ensure_roster_schema(ledger_path)
    try:
        by_league = _cohort_sleeper_leagues(manager_keys, conn=conn)
        pool = set(manager_keys)
        observations: list[roster_store.RosterObservation] = []
        fetched: dict[str, dict[str, Any]] = {}

        for league_id in _collection_order(list(by_league), conn=conn):
            member_keys = by_league[league_id]
            if not b.can_call(CALLS_PER_LEAGUE):
                result.budget_exhausted = True
                result.leagues_remaining = len(by_league) - result.leagues_examined
                break
            league = b.get(f"{SLEEPER_BASE}/league/{league_id}")
            if not isinstance(league, dict):
                result.errors.append(f"league_fetch_failed:{league_id}")
                continue
            result.leagues_examined += 1

            rosters = b.get(f"{SLEEPER_BASE}/league/{league_id}/rosters")
            if not isinstance(rosters, list):
                result.errors.append(f"rosters_fetch_failed:{league_id}")
                continue
            fetched[str(league_id)] = league

            league_key = f"sleeper:{league_id}"
            fmt = league_format(league)
            league_reasons: list[str] = []
            sharp_reason = league_filter.sharp_exclusion_reason(league)
            if sharp_reason:
                league_reasons.append(
                    REASON_INCOMPATIBLE_FORMAT
                    if sharp_reason in ("best_ball", "redraft", "keeper")
                    else REASON_LEAGUE_NOT_SHARP_ELIGIBLE
                )
            if str(league.get("status") or "").lower() in _ABANDONED_STATUSES:
                league_reasons.append(REASON_ABANDONED_LEAGUE)

            for roster in rosters:
                if not isinstance(roster, dict):
                    continue
                source_roster_id = roster.get("roster_id")
                if source_roster_id is None:
                    continue
                owner = str(roster.get("owner_id") or "").strip()
                co_owners = [
                    str(c).strip() for c in (roster.get("co_owners") or []) if str(c or "").strip()
                ]

                # Attribute to the cohort member who actually holds this
                # roster.  A cohort co-owner is credited when the primary
                # owner is not in the pool, matching how the Insider
                # Trading crawl attributes co-owned teams.
                attributed = None
                if f"sleeper:{owner}" in pool:
                    attributed = f"sleeper:{owner}"
                else:
                    for candidate in co_owners:
                        if f"sleeper:{candidate}" in pool:
                            attributed = f"sleeper:{candidate}"
                            break
                if attributed is None:
                    continue  # not a sharp's roster — not our business

                reasons = list(league_reasons)
                if not owner and not co_owners:
                    reasons.append(REASON_ORPHANED_ROSTER)
                assets = _sleeper_assets(roster)
                if not assets:
                    reasons.append(REASON_INCOMPLETE_ROSTER)

                observations.append(
                    roster_store.RosterObservation(
                        platform="sleeper",
                        league_key=league_key,
                        manager_key=attributed,
                        source_roster_id=str(source_roster_id),
                        assets=assets,
                        season=str(league.get("season") or "") or None,
                        team_name=None,
                        exclusion_reasons=reasons,
                        league_format=fmt,
                        contention=_contention(roster),
                        observed_ms=now,
                        source_run_id=run_id,
                    )
                )
                result.note_exclusions(reasons)

            # ``member_keys`` is unused beyond league selection, but is
            # kept in the map so a future per-member gate has it.
            del member_keys

        observations = _collapse_season_chains(observations, fetched, result)
        totals = roster_store.record_rosters(observations, conn=conn)
        result.rosters_recorded = totals["rosters"]
        result.eligible_rosters = totals["eligibleRosters"]
        result.excluded_rosters = totals["rosters"] - totals["eligibleRosters"]
        result.assets_recorded = totals["assetsRecorded"]
    finally:
        conn.close()

    result.calls_used = b.used
    if not b.can_call(CALLS_PER_LEAGUE):
        result.budget_exhausted = True
    log.info("sharp.roster_collect.sleeper: %s", result.to_dict())
    return result


# ── FFPC ─────────────────────────────────────────────────────────────


def collect_ffpc_rosters(
    *,
    manager_keys: Sequence[str],
    ledger_path: Path | None = None,
    now_ms: int | None = None,
    run_id: str | None = None,
) -> CollectResult:
    """Lift already-crawled FFPC roster contents into the roster store.

    Zero network calls: ``src/platforms/ffpc/parser.py::_parse_rosters``
    already resolved these players against the Sleeper-keyed catalog
    during the public-page crawl and stashed them on the membership row.

    Two honest limitations are recorded rather than papered over:

    * FFPC publishes no taxi/IR marking on its roster pages, so every
      asset is stored as ``active``.  It is not a claim that none are on
      taxi — it is the absence of the distinction.
    * An FFPC player the resolver could not map has no canonical asset
      id.  Those are counted into ``unmappedAssets`` and left out of the
      roster rather than guessed onto a similar name, which is the same
      no-fuzzy-fallback policy ``AssetResolver`` enforces.
    """
    result = CollectResult()
    ffpc_keys = [k for k in manager_keys if str(k).startswith("ffpc:")]
    if not ffpc_keys:
        return result
    now = int(now_ms if now_ms is not None else time.time() * 1000)

    conn = roster_store.ensure_roster_schema(ledger_path)
    try:
        rows = []
        for start in range(0, len(ffpc_keys), 400):
            chunk = ffpc_keys[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                conn.execute(
                    f"""
                    SELECT pmem.league_key, pmem.manager_key, pmem.roster_id,
                           pmem.source_team_id, pmem.team_name, pmem.metadata_json,
                           pl.season AS season, pl.sharp_eligible AS sharp_eligible,
                           pl.metadata_json AS league_metadata_json,
                           pm.identity_confidence AS identity_confidence
                      FROM platform_memberships pmem
                      LEFT JOIN platform_leagues pl ON pl.league_key=pmem.league_key
                      LEFT JOIN platform_managers pm ON pm.manager_key=pmem.manager_key
                     WHERE pmem.platform='ffpc' AND pmem.manager_key IN ({placeholders})
                    """,
                    chunk,
                ).fetchall()
            )

        observations: list[roster_store.RosterObservation] = []
        leagues_seen: set[str] = set()
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except (TypeError, ValueError):
                metadata = {}
            roster_assets = metadata.get("rosterAssets")
            if not isinstance(roster_assets, list):
                continue  # this membership came from a page with no roster table
            leagues_seen.add(str(row["league_key"]))

            assets = []
            unmapped = 0
            for item in roster_assets:
                if not isinstance(item, dict):
                    continue
                canonical = str(item.get("canonicalAssetId") or "").strip()
                if not canonical:
                    unmapped += 1
                    continue
                assets.append(
                    roster_store.RosterAsset(
                        canonical_asset_id=canonical,
                        asset_type="player",
                        # FFPC pages carry no taxi/IR column.
                        slot=roster_store.SLOT_ACTIVE,
                        source_asset_id=str(item.get("sourceAssetId") or "") or None,
                    )
                )
            result.unmapped_assets += unmapped

            reasons: list[str] = []
            try:
                confidence = float(row["identity_confidence"] or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < MIN_IDENTITY_CONFIDENCE:
                reasons.append(REASON_UNCERTAIN_IDENTITY)
            if not assets:
                reasons.append(REASON_NO_CANONICAL_ASSETS if unmapped else REASON_INCOMPLETE_ROSTER)

            try:
                league_metadata = json.loads(row["league_metadata_json"] or "{}")
            except (TypeError, ValueError):
                league_metadata = {}
            fmt = {
                "leagueType": "dynasty",
                "season": row["season"],
                "status": None,
                # FFPC public pages expose no roster-position list, so
                # every format axis stays unknown rather than assumed.
                "superflex": league_metadata.get("superflex"),
                "tePremium": league_metadata.get("tePremium"),
                "idp": league_metadata.get("idp"),
                "teams": league_metadata.get("teams"),
            }

            source_roster_id = str(row["roster_id"] or row["source_team_id"] or "").strip()
            if not source_roster_id:
                # Without a team id there is no stable roster identity;
                # counting it would risk merging two teams into one slot.
                result.note_exclusions([REASON_UNCERTAIN_IDENTITY])
                result.excluded_rosters += 1
                continue

            observations.append(
                roster_store.RosterObservation(
                    platform="ffpc",
                    league_key=str(row["league_key"]),
                    manager_key=str(row["manager_key"]),
                    source_roster_id=source_roster_id,
                    assets=assets,
                    season=row["season"],
                    team_name=row["team_name"],
                    exclusion_reasons=reasons,
                    league_format=fmt,
                    contention="unknown",
                    observed_ms=now,
                    source_run_id=run_id,
                )
            )
            result.note_exclusions(reasons)

        totals = roster_store.record_rosters(observations, conn=conn)
        result.leagues_examined = len(leagues_seen)
        result.rosters_recorded = totals["rosters"]
        result.eligible_rosters = totals["eligibleRosters"]
        result.excluded_rosters += totals["rosters"] - totals["eligibleRosters"]
        result.assets_recorded = totals["assetsRecorded"]
    finally:
        conn.close()

    log.info("sharp.roster_collect.ffpc: %s", result.to_dict())
    return result


def collect_all(
    *,
    qualification: str = "all",
    ledger_path: Path | None = None,
    http_get: HttpGet | None = None,
    budget: int = DEFAULT_BUDGET,
    sleep_s: float = DEFAULT_SLEEP_S,
    sleep_fn=time.sleep,
    now_ms: int | None = None,
    run_id: str | None = None,
    skip_sleeper: bool = False,
    skip_ffpc: bool = False,
) -> dict[str, Any]:
    """Refresh every reachable sharp roster on both platforms."""
    members, coverage = sharp_cohort.cohort_members(
        qualification=qualification, ledger_path=ledger_path
    )
    manager_keys = [m.manager_key for m in members]

    sleeper = (
        CollectResult()
        if skip_sleeper
        else collect_sleeper_rosters(
            manager_keys=manager_keys,
            http_get=http_get,
            budget=budget,
            sleep_s=sleep_s,
            ledger_path=ledger_path,
            sleep_fn=sleep_fn,
            now_ms=now_ms,
            run_id=run_id,
        )
    )
    ffpc = (
        CollectResult()
        if skip_ffpc
        else collect_ffpc_rosters(
            manager_keys=manager_keys,
            ledger_path=ledger_path,
            now_ms=now_ms,
            run_id=run_id,
        )
    )
    return {
        "cohortManagers": len(manager_keys),
        "cohortCoverage": coverage,
        "sleeper": sleeper.to_dict(),
        "ffpc": ffpc.to_dict(),
        "store": roster_store.coverage(path=ledger_path),
    }


def record_collection_run(
    summary: dict[str, Any],
    *,
    started_ms: int,
    finished_ms: int,
    ledger_path: Path | None = None,
    run_id: str,
    status: str = "ok",
) -> None:
    """Log the pass into ``ingestion_runs`` so freshness is inspectable.

    Filed under the pseudo-platform ``sharp_rosters`` rather than under
    ``sleeper``/``ffpc``.  ``platform_ledger.platform_coverage`` reports
    the LATEST run per platform, so filing this pass under ``sleeper``
    would make the Buy/Sell Tracker's Sleeper freshness read as a roster
    refresh.  That function iterates a fixed ``("sleeper", "ffpc")``
    tuple, so this row is invisible to it by construction.
    """
    sleeper = summary.get("sleeper") or {}
    ffpc = summary.get("ffpc") or {}
    platform_ledger.record_ingestion_run(
        run_id=run_id,
        platform="sharp_rosters",
        source_ref="cohort",
        started_ms=started_ms,
        finished_ms=finished_ms,
        status=status,
        # ``record_ingestion_run`` reads camelCase counter keys
        # (``platform_ledger.py`` — ``values.get("pagesFetched")``), not
        # the snake_case column names. Passing snake_case silently
        # records zeros, which is how a run that did real work reads as
        # one that did nothing.
        counters={
            "pagesFetched": int(sleeper.get("callsUsed") or 0),
            "pagesParsed": int(sleeper.get("leaguesExamined") or 0)
            + int(ffpc.get("leaguesExamined") or 0),
            "unmappedPlayers": int(ffpc.get("unmappedAssets") or 0),
        },
        metadata=summary,
        path=ledger_path,
    )
