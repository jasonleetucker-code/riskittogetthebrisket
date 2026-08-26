"""Sharp Roster Percentage — how much of the sharp cohort owns each player.

    Sharp Roster Percentage
      = unique ELIGIBLE sharp rosters containing the player
      ÷ total eligible sharp rosters that COULD contain him

The pool is not defined here
───────────────────────────
Membership comes from ``src/sharp/cohort.py::cohort_members`` — the same
call ``src/sharp/market.py`` makes for the Buy/Sell Tracker.  This module
never decides who is a sharp, never adds a qualification rule, and never
keeps its own list.  If the cohort changes, both boards change together.

Rosters, not people, are the denominator
────────────────────────────────────────
A manager with five legitimate dynasty teams contributes FIVE roster
observations; a manager with one contributes one.  That is deliberate
per the product definition — the question is "what share of sharp
rosters hold him", not "what share of sharp humans".  Both numbers are
published: ``uniqueSharpManagers`` collapses linked accounts to people
via ``cohort.canonical_manager_ids``, ``eligibleRosters`` does not.

The denominator is PER PLAYER, and that is not a detail
───────────────────────────────────────────────────────
A linebacker cannot be rostered in a league with no IDP slots, and a
kicker cannot be rostered in a league with no K slot.  Dividing by every
sharp roster would make every IDP player look barely owned — an artifact
of format mix, reported as a finding.  Each player is therefore measured
against the rosters whose league is KNOWN to field his position family.
Rosters whose format we could not determine are excluded from that
player's denominator and counted in ``formatUnknownRosters`` rather than
silently assumed either way.

What this board is NOT
──────────────────────
A high roster percentage is not a buy signal.  Elite players are
rostered almost everywhere, so the top of this board is mostly a
restatement of consensus value.  The interesting columns are the
comparison ones — advantage over the market, and the trend — which is
why the payload ships those beside the raw percentage rather than
leaving a caller to infer intent from rank alone.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from src.sharp import cohort as sharp_cohort
from src.sharp import roster_store

log = logging.getLogger(__name__)

# ── sample-size policy ───────────────────────────────────────────────
#
# Below MIN_ELIGIBLE_ROSTERS a percentage is not published as a ranked
# result at all: with eight rosters every player jumps in 12.5-point
# steps and the ordering is mostly noise.  Between that and
# DIRECTIONAL_ROSTER_CEILING the numbers ARE published but carry an
# explicit directional warning, because the alternative — hiding them —
# would leave a growing cohort looking permanently broken.
MIN_ELIGIBLE_ROSTERS = 8
DIRECTIONAL_ROSTER_CEILING = 40

# A player measured against fewer rosters than this is flagged
# individually even when the board as a whole is well sampled — the
# IDP-in-a-mostly-offense-cohort case.
MIN_PLAYER_DENOMINATOR = 5

# A trend is only reported when both endpoints are measured over
# substantially the same rosters.  Below this overlap the sample moved
# too much for the delta to mean anything, and we say so instead.
MIN_TREND_POPULATION_OVERLAP = 0.80

DAY_MS = 86_400_000

DEFAULT_LIMIT = 50
ALLOWED_LIMITS = (25, 50, 100, 0)  # 0 = all qualifying players

# ── position families ────────────────────────────────────────────────
_OFFENSE = {"QB", "RB", "WR", "TE", "FB"}
_DEFENSIVE_LINE = {"DL", "DE", "DT", "EDGE"}
_LINEBACKER = {"LB", "ILB", "OLB", "MLB"}
_DEFENSIVE_BACK = {"DB", "CB", "S", "SS", "FS"}
_IDP = _DEFENSIVE_LINE | _LINEBACKER | _DEFENSIVE_BACK
_KICKER = {"K", "PK"}
_TEAM_DEFENSE = {"DEF", "DST", "D/ST"}

FAMILY_OFFENSE = "offense"
FAMILY_IDP = "idp"
FAMILY_KICKER = "kicker"
FAMILY_TEAM_DEFENSE = "teamDefense"
FAMILY_UNKNOWN = "unknown"

# EVERY family a denominator can be computed for, in one place.
#
# ``FAMILY_UNKNOWN`` is a real member of this tuple, not an oversight:
# a player whose position we cannot determine has a denominator that
# cannot be narrowed, so every roster applies — exactly like offense.
# Leaving it out does not raise, it silently yields an empty denominator
# set for those players.
#
# The audit script re-derives denominators independently and MUST iterate
# the same tuple. It used to hardcode its own four-element list, which
# omitted UNKNOWN and made the audit report a false failure for every
# player whenever it ran without a contract (no contract → no positions →
# every family unknown). Exported so the two can never drift again.
POSITION_FAMILIES = (
    FAMILY_OFFENSE,
    FAMILY_IDP,
    FAMILY_KICKER,
    FAMILY_TEAM_DEFENSE,
    FAMILY_UNKNOWN,
)

POSITION_FILTERS = (
    "all",
    "QB",
    "RB",
    "WR",
    "TE",
    "DL",
    "LB",
    "DB",
    "offense",
    "idp",
)
PLATFORM_FILTERS = ("all", "sleeper", "ffpc")
FORMAT_FILTERS = ("all", "superflex", "oneQb", "tePremium", "nonTePremium")
CONTENTION_FILTERS = ("all", "contending", "rebuilding")
EXPERIENCE_FILTERS = ("all", "rookies", "veterans")

SORTS = (
    "rostered",
    "advantage",
    "negativeAdvantage",
    "valueWithoutRosters",
    "rosteredWithoutValue",
    "trend",
)


def position_family(position: str | None) -> str:
    pos = str(position or "").strip().upper()
    if not pos:
        return FAMILY_UNKNOWN
    if pos in _OFFENSE:
        return FAMILY_OFFENSE
    if pos in _IDP:
        return FAMILY_IDP
    if pos in _KICKER:
        return FAMILY_KICKER
    if pos in _TEAM_DEFENSE:
        return FAMILY_TEAM_DEFENSE
    return FAMILY_UNKNOWN


def _matches_position_filter(position: str | None, position_filter: str) -> bool:
    pos = str(position or "").strip().upper()
    if position_filter == "all":
        return True
    if position_filter == "offense":
        return pos in _OFFENSE
    if position_filter == "idp":
        return pos in _IDP
    if position_filter == "DL":
        return pos in _DEFENSIVE_LINE
    if position_filter == "LB":
        return pos in _LINEBACKER
    if position_filter == "DB":
        return pos in _DEFENSIVE_BACK
    return pos == position_filter


def _roster_supports_family(league_format: dict[str, Any], family: str) -> bool | None:
    """Can this roster's league field that position family?

    ``None`` means UNKNOWN — the format was never captured — and an
    unknown roster is excluded from that family's denominator rather
    than counted either way.
    """
    if family in (FAMILY_OFFENSE, FAMILY_UNKNOWN):
        return True
    key = {
        FAMILY_IDP: "idp",
        FAMILY_KICKER: "kicker",
        FAMILY_TEAM_DEFENSE: "teamDefense",
    }[family]
    value = (league_format or {}).get(key)
    return None if value is None else bool(value)


# ── roster filtering ─────────────────────────────────────────────────


@dataclass(frozen=True)
class RosterFilters:
    platform: str = "all"
    league_format: str = "all"
    contention: str = "all"

    def validate(self) -> None:
        if self.platform not in PLATFORM_FILTERS:
            raise ValueError(f"platform must be one of {PLATFORM_FILTERS}")
        if self.league_format not in FORMAT_FILTERS:
            raise ValueError(f"format must be one of {FORMAT_FILTERS}")
        if self.contention not in CONTENTION_FILTERS:
            raise ValueError(f"contention must be one of {CONTENTION_FILTERS}")


def _roster_passes(roster: dict[str, Any], filters: RosterFilters) -> bool:
    if filters.platform != "all" and roster.get("platform") != filters.platform:
        return False
    fmt = roster.get("format") or {}
    if filters.league_format == "superflex" and fmt.get("superflex") is not True:
        return False
    if filters.league_format == "oneQb" and fmt.get("superflex") is not False:
        return False
    if filters.league_format == "tePremium" and fmt.get("tePremium") is not True:
        return False
    if filters.league_format == "nonTePremium" and fmt.get("tePremium") is not False:
        return False
    if filters.contention != "all" and roster.get("contention") != filters.contention:
        return False
    return True


def eligible_rosters(
    rosters: Iterable[dict[str, Any]],
    *,
    cohort_manager_keys: set[str],
    now_ms: int,
    max_age_days: int = roster_store.DEFAULT_MAX_ROSTER_AGE_DAYS,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """``(eligible, {reason: dropped})``.

    Three gates on top of the ones the collector already recorded:

    * the roster's manager must STILL be in the sharp cohort — a manager
      who has since fallen below the bar must stop contributing, and
      this is the join that enforces it;
    * the observation must be fresh enough to describe the present;
    * the roster must carry at least one mappable player.
    """
    kept: list[dict[str, Any]] = []
    dropped: dict[str, int] = {}

    def drop(reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1

    cutoff = int(now_ms) - int(max_age_days) * DAY_MS
    for roster in rosters:
        if not roster.get("isEligible"):
            for reason in roster.get("exclusionReasons") or ["unspecified"]:
                drop(str(reason))
            continue
        if roster.get("managerKey") not in cohort_manager_keys:
            drop("manager_no_longer_in_cohort")
            continue
        if int(roster.get("observedMs") or 0) < cutoff:
            drop("stale_roster_data")
            continue
        if not roster.get("assets"):
            drop("incomplete_roster_data")
            continue
        kept.append(roster)
    return kept, dropped


# ── player metadata + value join ─────────────────────────────────────


def _contract_rows(contract: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = (contract or {}).get("playersArray")
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def build_player_index(contract: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """``{sleeperPlayerId: {name, position, nflTeam, value, overallRank}}``.

    Canonical asset ids ARE Sleeper player ids (``src/platforms/assets.py``
    anchors the catalog on them), and contract rows stamp that same id as
    ``playerId``, so this join is by identifier rather than by name.
    Rows without a Sleeper id cannot be joined to a roster and are
    skipped rather than name-matched — a fuzzy fallback here would
    attach one player's value to another's ownership.

    Three contract field names are easy to get wrong and are worth
    stating: the NFL team is ``team`` (there is no ``nflTeam`` on a
    ``playersArray`` row), the rookie flag is ``rookie``, and the tier
    is ``canonicalTierId``.  ``rankDerivedValue`` and
    ``canonicalConsensusRank`` are stamped only for rows inside the
    backend's ``OVERALL_RANK_LIMIT``, so a deep-roster player legitimately
    has neither — that is reported as ``playersWithoutBoardValue``, not
    filled with a zero.
    """
    index: dict[str, dict[str, Any]] = {}
    for row in _contract_rows(contract):
        player_id = str(row.get("playerId") or "").strip()
        if not player_id:
            continue
        value = row.get("rankDerivedValue")
        rank = row.get("canonicalConsensusRank")
        index.setdefault(
            player_id,
            {
                "displayName": row.get("displayName") or row.get("canonicalName"),
                "position": (str(row.get("position") or "").strip().upper() or None),
                "nflTeam": (
                    str(row.get("team") or row.get("nflTeam") or "").strip().upper() or None
                ),
                "value": int(value) if isinstance(value, (int, float)) else None,
                "overallRank": int(rank) if isinstance(rank, (int, float)) else None,
                "age": row.get("age"),
                "isRookie": bool(row.get("rookie") or row.get("isRookie")),
            },
        )
    return index


def _catalog_metadata(
    ledger_path: Path | None,
    *,
    conn: Any | None = None,
) -> dict[str, dict[str, Any]]:
    """``{canonicalAssetId: {displayName, position, nflTeam}}`` from the ledger.

    ``canonical_assets`` is the platform's own asset catalog, hydrated
    from Sleeper's directory by the roster crawl and the FFPC crawl. It
    is consulted because our BOARD only names players inside its ranked
    pool: a genuinely rostered player outside it (a deep veteran QB, for
    instance) otherwise renders as a bare Sleeper id next to a perfectly
    correct percentage, which reads as a broken row.

    ``conn`` lets the request owner reuse the already-open roster-store
    connection. The read and fallback semantics are identical either way.
    Degrades to an empty map — a name is cosmetic and must never cost a
    board its numbers.
    """
    own = conn is None
    if conn is None:
        try:
            connection = roster_store.ensure_roster_schema(ledger_path)
        except Exception:  # noqa: BLE001
            log.exception("sharp roster %%: asset catalog unavailable")
            return {}
    else:
        connection = conn
    try:
        return {
            str(row["canonical_asset_id"]): {
                "displayName": row["display_name"],
                "position": (str(row["position"] or "").strip().upper() or None),
                "nflTeam": (str(row["nfl_team"] or "").strip().upper() or None),
            }
            for row in connection.execute(
                """
                SELECT canonical_asset_id, display_name, position, nfl_team
                  FROM canonical_assets
                 WHERE display_name IS NOT NULL
                """
            ).fetchall()
        }
    except Exception:  # noqa: BLE001
        log.exception("sharp roster %%: asset catalog read failed")
        return {}
    finally:
        if own:
            connection.close()


def _fallback_metadata(asset_id: str, catalog: dict[str, dict[str, Any]] | None = None) -> dict:
    """Name/position for an asset the live contract does not price.

    Two sources, in order: the ledger's ``canonical_assets`` catalog,
    then the Buy/Sell Tracker's own file-based fallback — so both boards
    display the same name for the same id.
    """
    from src.sharp import market as sharp_market

    meta = dict((catalog or {}).get(asset_id) or {})
    if not meta.get("displayName"):
        meta = {**(sharp_market._fallback_asset_metadata(asset_id) or {}), **meta}
    return {
        "displayName": meta.get("displayName"),
        "position": meta.get("position"),
        "nflTeam": meta.get("nflTeam"),
        "value": None,
        "overallRank": None,
        "age": None,
        "isRookie": False,
    }


# ── market comparison (deliberately pluggable, empty today) ──────────

MarketOwnershipProvider = Callable[[Sequence[str]], dict[str, float]]

_market_provider: MarketOwnershipProvider | None = None


def set_market_ownership_provider(provider: MarketOwnershipProvider | None) -> None:
    """Register a general-dynasty roster-percentage source.

    THERE IS NO SUCH SOURCE IN THIS CODEBASE TODAY.  Every ingested
    ranking source publishes values or ranks, not ownership; Sleeper's
    trending endpoint publishes 24-hour ADD COUNTS, which is a flow, not
    a stock, and turning it into an ownership rate would be inventing a
    number.  So the comparison columns are null and the payload says
    ``marketComparisonAvailable: false`` rather than shipping a
    plausible-looking fabrication.

    The seam exists so that adding a real feed later is a registration,
    not a rewrite of the board.
    """
    global _market_provider
    _market_provider = provider


def _market_ownership(asset_ids: Sequence[str]) -> dict[str, float]:
    if _market_provider is None or not asset_ids:
        return {}
    try:
        raw = _market_provider(asset_ids) or {}
    except Exception:  # noqa: BLE001 — an optional comparison must never break the board
        log.exception("sharp roster %%: market ownership provider failed")
        return {}
    out: dict[str, float] = {}
    for key, value in raw.items():
        try:
            pct = float(value)
        except (TypeError, ValueError):
            continue
        if 0.0 <= pct <= 1.0:
            out[str(key)] = pct
    return out


# ── the board ────────────────────────────────────────────────────────


def _tally(
    rosters: Sequence[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, dict[str, int]]]:
    """``({assetId: {rosterKey}}, {assetId: {slot: n}})``.

    The set is what makes a player count at most once per roster at the
    aggregation layer too — the store's primary key already guarantees
    it, and this keeps the guarantee true even if a caller hands in
    hand-built rows.
    """
    holders: dict[str, set[str]] = {}
    slots: dict[str, dict[str, int]] = {}
    for roster in rosters:
        key = str(roster.get("rosterKey"))
        for asset in roster.get("assets") or []:
            asset_id = str(asset.get("canonicalAssetId") or "")
            if not asset_id:
                continue
            holders.setdefault(asset_id, set()).add(key)
            slot = str(asset.get("slot") or roster_store.SLOT_ACTIVE)
            bucket = slots.setdefault(asset_id, {})
            bucket[slot] = bucket.get(slot, 0) + 1
    return holders, slots


def _denominators(
    rosters: Sequence[dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, int]]:
    """``({family: {rosterKey}}, {family: unknownFormatRosters})``."""
    by_family: dict[str, set[str]] = {}
    unknown: dict[str, int] = {}
    families = POSITION_FAMILIES
    for family in families:
        by_family[family] = set()
        unknown[family] = 0
    for roster in rosters:
        key = str(roster.get("rosterKey"))
        fmt = roster.get("format") or {}
        for family in families:
            supported = _roster_supports_family(fmt, family)
            if supported is None:
                unknown[family] += 1
            elif supported:
                by_family[family].add(key)
    return by_family, unknown


def _trend(
    asset_id: str,
    *,
    current_holders: set[str],
    baseline_holders: dict[str, set[str]],
    current_roster_keys: set[str],
    baseline_roster_keys: set[str],
) -> dict[str, Any]:
    """Change in roster percentage between two instants.

    Measured over the INTERSECTION of the two roster populations, so a
    cohort that grew between the endpoints cannot masquerade as players
    gaining ownership.  When the overlap is too small the delta is
    withheld and the reason is returned in its place.
    """
    shared = current_roster_keys & baseline_roster_keys
    union = current_roster_keys | baseline_roster_keys
    overlap = (len(shared) / len(union)) if union else 0.0
    if not shared or overlap < MIN_TREND_POPULATION_OVERLAP:
        return {
            "available": False,
            "reason": "roster_population_changed",
            "populationOverlap": round(overlap, 4),
            "comparableRosters": len(shared),
        }
    now_held = {k for k in current_holders if k in shared}
    then_held = {k for k in baseline_holders if k in shared}
    return {
        "available": True,
        "populationOverlap": round(overlap, 4),
        "comparableRosters": len(shared),
        "rosterPctThen": round(len(then_held) / len(shared), 6),
        "rosterPctNow": round(len(now_held) / len(shared), 6),
        "rosterPctChange": round((len(now_held) - len(then_held)) / len(shared), 6),
        "rostersAdded": len(now_held - then_held),
        "rostersDropped": len(then_held - now_held),
    }


def _sample_warning(eligible_count: int) -> dict[str, Any] | None:
    if eligible_count < MIN_ELIGIBLE_ROSTERS:
        return {
            "level": "insufficient",
            "message": (
                f"Based on {eligible_count} eligible sharp roster"
                f"{'' if eligible_count == 1 else 's'}. That is below the "
                f"{MIN_ELIGIBLE_ROSTERS}-roster minimum, so these percentages are "
                "not ranked as meaningful results."
            ),
        }
    if eligible_count < DIRECTIONAL_ROSTER_CEILING:
        return {
            "level": "directional",
            "message": (
                f"Based on {eligible_count} eligible sharp rosters. Treat this "
                "result as directional because of the limited sample size."
            ),
        }
    return None


def build_board(
    *,
    contract: dict[str, Any] | None = None,
    ledger_path: Path | None = None,
    qualification: str = "all",
    position: str = "all",
    platform: str = "all",
    league_format: str = "all",
    contention: str = "all",
    experience: str = "all",
    sort: str = "rostered",
    limit: int = DEFAULT_LIMIT,
    include_picks: bool = False,
    now_ms: int | None = None,
    max_age_days: int = roster_store.DEFAULT_MAX_ROSTER_AGE_DAYS,
    buy_sell_window: str = "30d",
) -> dict[str, Any]:
    """The Sharp Roster Percentage payload."""
    if position not in POSITION_FILTERS:
        raise ValueError(f"position must be one of {POSITION_FILTERS}")
    if experience not in EXPERIENCE_FILTERS:
        raise ValueError(f"experience must be one of {EXPERIENCE_FILTERS}")
    if sort not in SORTS:
        raise ValueError(f"sort must be one of {SORTS}")
    filters = RosterFilters(platform=platform, league_format=league_format, contention=contention)
    filters.validate()
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer") from None
    if limit not in ALLOWED_LIMITS:
        raise ValueError(f"limit must be one of {ALLOWED_LIMITS}")

    now = int(now_ms if now_ms is not None else time.time() * 1000)

    members, cohort_coverage = sharp_cohort.cohort_members(
        qualification=qualification, ledger_path=ledger_path
    )
    cohort_keys = {m.manager_key for m in members}

    # One read connection owns the roster-state portion of this request.
    # Previously current rosters, catalog metadata, and four trend baselines
    # independently reopened/ensured the same SQLite schema.
    roster_conn = roster_store.ensure_roster_schema(ledger_path)
    try:
        stored = roster_store.load_rosters(path=ledger_path, conn=roster_conn)
        usable, exclusions = eligible_rosters(
            stored,
            cohort_manager_keys=cohort_keys,
            now_ms=now,
            max_age_days=max_age_days,
        )
        filtered = [r for r in usable if _roster_passes(r, filters)]
        filtered_out = len(usable) - len(filtered)

        roster_keys = {str(r["rosterKey"]) for r in filtered}
        holders, slot_counts = _tally(filtered)
        denominators, unknown_format = _denominators(filtered)
        # W15-F009 (inv 4.6): every ``filtered`` roster already passed the
        # cohort-membership gate in ``eligible_rosters``, so its ``managerKey``
        # is guaranteed present — this map is total over ``roster_keys``, not
        # a best-effort join, and needs no "unknown manager" fallback bucket.
        roster_manager = {str(r["rosterKey"]): str(r["managerKey"]) for r in filtered}
        asset_catalog = _catalog_metadata(ledger_path, conn=roster_conn)

        # The owner's stated windows are 7 / 14 / 30 day; season-to-date is kept
        # alongside them because it answers a different question.
        baselines = {
            "sevenDay": now - 7 * DAY_MS,
            "fourteenDay": now - 14 * DAY_MS,
            "thirtyDay": now - 30 * DAY_MS,
            "seasonToDate": _season_start_ms(now),
        }
        sorted_roster_keys = sorted(roster_keys)
        baseline_holdings = {
            name: roster_store.holdings_as_of(
                as_of,
                roster_keys=sorted_roster_keys,
                path=ledger_path,
                conn=roster_conn,
            )
            for name, as_of in baselines.items()
        }
    finally:
        roster_conn.close()

    player_index = build_player_index(contract)
    buy_sell = _buy_sell_index(
        members=members,
        ledger_path=ledger_path,
        window=buy_sell_window,
        now_ms=now,
    )

    market_pct = _market_ownership(sorted(holders))
    rows: list[dict[str, Any]] = []
    unpriced = 0
    for asset_id, held_by in holders.items():
        is_pick = asset_id.startswith("pick:")
        if is_pick and not include_picks:
            continue
        meta = player_index.get(asset_id) or _fallback_metadata(asset_id, asset_catalog)
        pos = meta.get("position")
        if not _matches_position_filter(pos, position):
            continue
        if experience == "rookies" and not meta.get("isRookie"):
            continue
        if experience == "veterans" and meta.get("isRookie"):
            continue

        family = FAMILY_UNKNOWN if is_pick else position_family(pos)
        denominator_keys = denominators.get(family) or set()
        # A roster that HOLDS the player proves its league fields his
        # position, so it belongs in his denominator even when the
        # format capture was incomplete. Without this an unknown-format
        # roster could contribute a numerator it was excluded from
        # counting against, and a percentage could exceed 100%.
        applicable = (denominator_keys | held_by) & roster_keys
        if not applicable:
            continue
        counted = held_by & applicable
        pct = len(counted) / len(applicable)
        if meta.get("value") is None:
            unpriced += 1

        # W15-F009 (inv 4.6): a player rostered by five teams belonging to
        # one manager is not five independent opinions. ``counted`` is
        # never empty here (every asset_id in ``holders`` has at least one
        # holding roster), so this is always a real measurement, never an
        # undefined ratio standing in for a missing one.
        manager_counts = Counter(roster_manager[rk] for rk in counted)
        distinct_managers = len(manager_counts)
        manager_concentration = max(manager_counts.values()) / len(counted)

        market = market_pct.get(asset_id)
        row = {
            "assetId": asset_id,
            "displayName": meta.get("displayName") or asset_id,
            "position": pos,
            "nflTeam": meta.get("nflTeam"),
            "assetType": "pick" if is_pick else "player",
            "positionFamily": family,
            "sharpRosters": len(counted),
            "eligibleRosters": len(applicable),
            "sharpRosterPct": round(pct, 6),
            "distinctManagers": distinct_managers,
            "managerConcentration": round(manager_concentration, 6),
            "marketRosterPct": market,
            "sharpRosterAdvantage": (round(pct - market, 6) if market is not None else None),
            "value": meta.get("value"),
            "overallRank": meta.get("overallRank"),
            "slots": slot_counts.get(asset_id, {}),
            "buySell": buy_sell.get(asset_id),
            "sampleWarning": (
                {
                    "level": "insufficient",
                    "message": (
                        f"Only {len(applicable)} eligible sharp roster"
                        f"{'' if len(applicable) == 1 else 's'} could roster this "
                        "player, so the percentage is directional at best."
                    ),
                }
                if len(applicable) < MIN_PLAYER_DENOMINATOR
                else None
            ),
            "trend": {
                name: _trend(
                    asset_id,
                    current_holders=counted,
                    baseline_holders={
                        key: assets
                        for key, assets in (baseline_holdings[name] or {}).items()
                        if asset_id in assets
                    },
                    current_roster_keys=applicable,
                    baseline_roster_keys=set(baseline_holdings[name] or {}) & applicable,
                )
                for name in baselines
            },
        }
        rows.append(row)

    rows = _sort_rows(rows, sort)
    total_qualifying = len(rows)
    if limit:
        rows = rows[:limit]
    for index, row in enumerate(rows):
        row["rank"] = index + 1

    transparency = _transparency(
        filtered,
        members=members,
        ledger_path=ledger_path,
        unknown_format=unknown_format,
    )
    warning = _sample_warning(len(filtered))

    return {
        "status": "ok"
        if filtered
        else ("cohort_building" if not stored else "no_eligible_rosters"),
        "generatedAt": now,
        "lastUpdated": transparency.get("lastRefreshedMs"),
        "methodologyVersion": cohort_coverage.get("methodologyVersion"),
        "query": {
            "position": position,
            "platform": platform,
            "format": league_format,
            "contention": contention,
            "experience": experience,
            "qualification": qualification,
            "sort": sort,
            "limit": limit,
            "includePicks": include_picks,
        },
        "players": rows,
        "totalQualifyingPlayers": total_qualifying,
        "transparency": transparency,
        "cohort": {
            **cohort_coverage,
            "selectedManagers": len(members),
        },
        "sample": {
            "eligibleRosters": len(filtered),
            "minimumForRanking": MIN_ELIGIBLE_ROSTERS,
            "directionalBelow": DIRECTIONAL_ROSTER_CEILING,
            "warning": warning,
            "rankable": len(filtered) >= MIN_ELIGIBLE_ROSTERS,
        },
        "marketComparison": {
            "available": bool(market_pct),
            "source": None if not market_pct else "registered_provider",
            "note": (
                "No general-dynasty roster-percentage feed is ingested by this "
                "platform, so sharp-vs-market advantage is unavailable. Every "
                "ranking source we ingest publishes values or ranks, and Sleeper's "
                "trending endpoint publishes 24-hour add counts — a flow, not an "
                "ownership rate. Those columns stay null rather than estimated."
            )
            if not market_pct
            else None,
        },
        "exclusions": {
            "byReason": dict(sorted(exclusions.items())),
            "excludedRosters": sum(exclusions.values()),
            "removedByFilters": filtered_out,
            "storedRosters": len(stored),
        },
        "dataQuality": {
            "playersWithoutBoardValue": unpriced,
            "formatUnknownRosters": unknown_format,
        },
        "formula": {
            "sharpRosterPct": (
                "unique eligible sharp rosters containing the player ÷ eligible "
                "sharp rosters whose league can field his position family"
            ),
            "denominator": (
                "rosters, not people — one manager's five dynasty teams are five "
                "roster observations"
            ),
            "dedup": (
                "enforced by primary key: one row per (roster, player) and one row "
                "per roster, so re-collection and duplicate imports cannot inflate"
            ),
        },
    }


def _season_start_ms(now_ms: int) -> int:
    """Start of the current NFL season, in ms.

    Approximated as 1 September of the season year, where the season
    year rolls in September — the same convention
    ``src/bdvm/actuals.py::current_nfl_season`` uses, so "season to
    date" means the same thing on both surfaces.
    """
    from datetime import datetime, timezone

    moment = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc)
    year = moment.year if moment.month >= 9 else moment.year - 1
    return int(datetime(year, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)


def _buy_sell_index(
    *,
    members: Sequence[Any],
    ledger_path: Path | None,
    window: str,
    now_ms: int,
) -> dict[str, dict[str, Any]]:
    """Recent Sharp Buy/Sell Tracker activity, keyed by canonical asset.

    Read through the tracker's OWN aggregation rather than re-querying
    the ledger, so "3 sharp buys" means exactly what it means on
    ``/market/sharp-tracker``.  A failure here degrades to no activity
    column; it never takes the roster board down.
    """
    try:
        from src.intel import platform_ledger, signals
        from src.sharp import market as sharp_market

        since, until = signals.window_bounds(window, now_ms)
        movements = platform_ledger.query_movements(
            manager_keys=[m.manager_key for m in members],
            since_ms=since,
            until_ms=until,
            canonical_only=True,
            path=ledger_path,
        )
        quality = {m.manager_key: m.quality for m in members}
        aggregated = sharp_market._aggregate_window(movements, quality)
    except Exception:  # noqa: BLE001 — optional enrichment
        log.exception("sharp roster %%: buy/sell join failed")
        return {}
    out: dict[str, dict[str, Any]] = {}
    for asset_id, item in aggregated.items():
        buys, sells = int(item.get("buys") or 0), int(item.get("sells") or 0)
        out[asset_id] = {
            "window": window,
            "buys": buys,
            "sells": sells,
            "net": buys - sells,
            "uniqueManagers": item.get("uniqueManagers"),
            "signal": _buy_sell_signal(buys, sells),
            "lastTs": item.get("lastTs"),
        }
    return out


def _buy_sell_signal(buys: int, sells: int) -> str:
    """A label for the direction, never a recommendation.

    Deliberately coarse: with the volumes a sharp cohort produces, a
    finer scale would imply precision the counts do not carry.
    """
    volume = buys + sells
    if volume == 0:
        return "none"
    net = buys - sells
    if volume < 3:
        return "thin"
    if net > 0 and buys >= 2 * max(1, sells):
        return "accumulating"
    if net < 0 and sells >= 2 * max(1, buys):
        return "distributing"
    return "mixed"


def _sort_rows(rows: list[dict[str, Any]], sort: str) -> list[dict[str, Any]]:
    """Order the board, with unavailable values sinking rather than
    sorting as zero."""

    def advantage(row: dict[str, Any]) -> float | None:
        return row.get("sharpRosterAdvantage")

    def trend_change(row: dict[str, Any]) -> float | None:
        item = (row.get("trend") or {}).get("thirtyDay") or {}
        return item.get("rosterPctChange") if item.get("available") else None

    def key(row: dict[str, Any]):
        pct = row.get("sharpRosterPct") or 0.0
        rank = row.get("overallRank")
        if sort == "advantage":
            value = advantage(row)
            return (0 if value is not None else 1, -(value or 0.0), -pct)
        if sort == "negativeAdvantage":
            value = advantage(row)
            return (0 if value is not None else 1, (value or 0.0), -pct)
        if sort == "trend":
            value = trend_change(row)
            return (0 if value is not None else 1, -(value or 0.0), -pct)
        if sort == "valueWithoutRosters":
            # Highly valued, lightly owned: sort by board rank ascending
            # among players whose ownership lags their rank.
            return (0 if rank is not None else 1, rank or 0, pct)
        if sort == "rosteredWithoutValue":
            # Widely owned, poorly ranked: heavy ownership first, then
            # the WORST board rank, so an unranked-but-owned player
            # surfaces rather than sinking.
            return (-pct, -(rank if rank is not None else 10**6))
        return (-pct, -(row.get("value") or 0), row.get("displayName") or "")

    return sorted(rows, key=key)


def _transparency(
    rosters: Sequence[dict[str, Any]],
    *,
    members: Sequence[Any],
    ledger_path: Path | None,
    unknown_format: dict[str, int],
) -> dict[str, Any]:
    manager_keys = sorted({str(r.get("managerKey")) for r in rosters if r.get("managerKey")})
    try:
        people = sharp_cohort.unique_person_count(manager_keys, ledger_path=ledger_path)
    except Exception:  # noqa: BLE001
        log.exception("sharp roster %%: person collapse failed")
        people = len(manager_keys)

    by_platform: dict[str, int] = {}
    for roster in rosters:
        name = str(roster.get("platform") or "unknown")
        by_platform[name] = by_platform.get(name, 0) + 1

    cohort_size = len(members)
    represented = len({str(r.get("managerKey")) for r in rosters})
    last_refreshed = max((int(r.get("observedMs") or 0) for r in rosters), default=None)

    return {
        "uniqueSharpManagers": people,
        "sharpManagerAccounts": len(manager_keys),
        "eligibleRosters": len(rosters),
        "sleeperRosters": by_platform.get("sleeper", 0),
        "ffpcRosters": by_platform.get("ffpc", 0),
        "otherPlatformRosters": sum(
            count for name, count in by_platform.items() if name not in ("sleeper", "ffpc")
        ),
        "cohortManagers": cohort_size,
        "cohortManagersRepresented": represented,
        "cohortCoveragePct": (round(represented / cohort_size, 4) if cohort_size else None),
        "lastRefreshedMs": last_refreshed,
        "rostersPerManager": (round(len(rosters) / represented, 2) if represented else None),
        "formatUnknownRosters": unknown_format,
    }


def audit_player(
    asset_id: str,
    *,
    ledger_path: Path | None = None,
    qualification: str = "all",
    now_ms: int | None = None,
    max_age_days: int = roster_store.DEFAULT_MAX_ROSTER_AGE_DAYS,
) -> dict[str, Any]:
    """Every roster behind one player's percentage, and every one excluded.

    This is the manual-verification surface: the numerator is listed
    roster by roster, so a count can be checked against the underlying
    rosters without a database client.
    """
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    members, _coverage = sharp_cohort.cohort_members(
        qualification=qualification, ledger_path=ledger_path
    )
    cohort_keys = {m.manager_key for m in members}
    stored = roster_store.load_rosters(path=ledger_path)
    usable, exclusions = eligible_rosters(
        stored, cohort_manager_keys=cohort_keys, now_ms=now, max_age_days=max_age_days
    )
    holding = []
    for roster in usable:
        for asset in roster.get("assets") or []:
            if str(asset.get("canonicalAssetId")) == str(asset_id):
                holding.append(
                    {
                        "rosterKey": roster["rosterKey"],
                        "platform": roster["platform"],
                        "leagueKey": roster["leagueKey"],
                        "managerKey": roster["managerKey"],
                        "sourceRosterId": roster["sourceRosterId"],
                        "slot": asset.get("slot"),
                        "observedMs": roster["observedMs"],
                        "contention": roster.get("contention"),
                        "format": roster.get("format"),
                    }
                )
                break  # at most one observation per roster, by construction
    return {
        "assetId": str(asset_id),
        "holdingRosters": sorted(holding, key=lambda r: r["rosterKey"]),
        "holdingRosterCount": len(holding),
        "eligibleRosterCount": len(usable),
        "distinctRosterKeys": len({r["rosterKey"] for r in holding}),
        "exclusions": dict(sorted(exclusions.items())),
        "generatedAt": now,
    }
