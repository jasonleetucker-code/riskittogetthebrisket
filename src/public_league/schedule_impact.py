"""Schedule Intelligence — the canonical schedule-impact owner (Milestone A).

Question: *how good were a team's weekly performances, what actually
happened, and how differently would those SAME performances have turned out
against other opponents?*  Every surface (League Hub table, team pages,
Power Rankings context, recaps, awards, share cards) reads this module's
contract; none recomputes it.  Full specification:
``docs/SCHEDULE_INTELLIGENCE_SPEC.md``.  Owner directive 2026-09-29.

What this module computes (one conventional head-to-head game per team-week)
──────────────────────────────────────────────────────────────────────────────
Scores are FIXED observations.  Only the head-to-head opponent is hypothetical.

    c(a, b)          = 1 if a > b, 0.5 if a == b, 0 if a < b
    eligible(w)      = the teams that actually played a head-to-head game in
                       finalized week w (a bye team scored but played no game)
    allPlayRate(i,w) = mean over j in eligible(w), j != i, of c(s_iw, s_jw)
    equalOpponentExpectedH2HCredits(i) = sum_w allPlayRate(i, w)
    actualH2HCredits(i)                = sum_w c(s_iw, s_opp(i,w),w)
    scheduleImpact(i)                  = actual - expected

The named model is ``equal_opponent_v1``: in each finalized week, each
eligible opponent is equally likely.  Under that model the expectation above
is EXACT (no sampling), and it does not require weeks to be independent.
It is also the exact expectation under the uniform distribution OVER all
labelled single round-robin calendars (averaged over those calendars, each
team's week-w opponent is uniform), which the test oracle verifies by full
enumeration.  League-VALID calendar models (repeat opponents, divisions,
timing-only swaps) are Milestone B and carry their own model ids; nothing
here claims to be one.

Median / league-average games are a SEPARATE standings component.  Changing
a head-to-head opponent while holding every score fixed cannot change a
median result, so this module never recomputes, reshuffles or attributes
median results to schedule.  The official record is the host's (median
included); the median component is reported only when the host record and
the head-to-head record line up over the same finalized weeks.

This is analysis of the past, not a forecast, and not a schedule generator
(the schedule generator is permanently removed, X-01): nothing here
produces, recommends or publishes a schedule.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

_LOG = logging.getLogger(__name__)

ALGORITHM_VERSION = "schedule-impact-2026.09-a1"
MODEL_EQUAL_OPPONENT = "equal_opponent_v1"

STATE_COMPLETE = "complete"
STATE_PARTIAL = "partial"
STATE_UNAVAILABLE = "unavailable"
STATE_UNSUPPORTED = "unsupported"

MODEL_DESCRIPTION = {
    "id": MODEL_EQUAL_OPPONENT,
    "baseline": "equal-opponent",
    "fixed": [
        "every team's weekly score",
        "points for",
        "median / league-average game results",
        "which weeks each team played a head-to-head game",
    ],
    "varies": ["the head-to-head opponent in each finalized week"],
    "distribution": (
        "each team that played a head-to-head game that week is an equally likely opponent"
    ),
    "method": "exact_analytic",
    "sampling": None,
    "notA": ["forecast", "league-valid calendar model", "schedule to adopt"],
}


def comparison_credit(a: float, b: float) -> float:
    """Head-to-head standings credit for scoring ``a`` against ``b``."""
    if a > b:
        return 1.0
    if a < b:
        return 0.0
    return 0.5


@dataclass(frozen=True)
class WeekInput:
    """One finalized scoring period: observed scores and the actual pairs."""

    week: int
    scores: Mapping[str, float]
    pairs: Sequence[tuple[str, str]]
    #: Teams that scored and had no matchup (a real bye).
    byes: Sequence[str] = ()
    #: Structure the adapter could not turn into pairs: ``group_size:<n>:...``
    #: (more than two teams in one matchup -> unsupported) or
    #: ``unpaired:<team>`` (a matchup whose partner row is missing -> partial).
    structural_issues: Sequence[str] = ()


def _week_issues(week: WeekInput) -> tuple[list[str], list[tuple[str, str]]]:
    """Structural problems and the evaluable pairs for one week."""
    issues: list[str] = []
    seen: dict[str, int] = {}
    evaluable: list[tuple[str, str]] = []
    issues.extend(week.structural_issues)
    for a, b in week.pairs:
        if a == b:
            issues.append(f"self_matchup:{a}")
            continue
        for t in (a, b):
            seen[t] = seen.get(t, 0) + 1
        if a not in week.scores or b not in week.scores:
            for t in (a, b):
                if t not in week.scores:
                    issues.append(f"missing_score:{t}")
            issues.append(f"game_excluded:{a}:{b}")
            continue
        evaluable.append((a, b))
    multi = sorted(t for t, n in seen.items() if n > 1)
    for t in multi:
        issues.append(f"multiple_games:{t}")
    return issues, evaluable


def compute_schedule_impact(weeks: Sequence[WeekInput]) -> dict[str, Any]:
    """The equal-opponent schedule-impact contract for a set of finalized weeks.

    Pure: no snapshot, no clock, no I/O.  Returns ``state`` plus per-team
    season rows and per-team weekly rows.  A structural format this model
    does not support (a team in two games in one week, a self-matchup) is
    ``unsupported`` -- never a plausible number from a simplified format.
    A game whose score is missing is left out and the result is ``partial``.
    """
    ordered = sorted(weeks, key=lambda w: w.week)
    if not ordered:
        return {
            "state": STATE_UNAVAILABLE,
            "reason": "no_finalized_weeks",
            "teams": {},
            "weeks": [],
        }

    all_issues: list[str] = []
    teams: dict[str, dict[str, Any]] = {}
    week_rows: list[dict[str, Any]] = []
    unsupported = False
    excluded: dict[str, list[int]] = {}
    byes: dict[str, list[int]] = {}

    for wk in ordered:
        issues, evaluable = _week_issues(wk)
        if any(i.startswith(("self_matchup", "multiple_games", "group_size")) for i in issues):
            unsupported = True
        all_issues.extend(f"week{wk.week}:{i}" for i in issues)
        if unsupported:
            continue
        for i in issues:
            if i.startswith("game_excluded:"):
                for t in i.split(":")[1:]:
                    excluded.setdefault(t, []).append(wk.week)
            elif i.startswith(("unpaired:", "unscored:")):
                excluded.setdefault(i.split(":", 1)[1], []).append(wk.week)
        for t in wk.byes:
            byes.setdefault(t, []).append(wk.week)
        eligible = sorted({t for pair in evaluable for t in pair})
        opponent = {}
        for a, b in evaluable:
            opponent[a] = b
            opponent[b] = a
        for team in eligible:
            s = float(wk.scores[team])
            others = [o for o in eligible if o != team]
            k = len(others)
            beats = sum(1 for o in others if s > float(wk.scores[o]))
            ties = sum(1 for o in others if s == float(wk.scores[o]))
            rate = (beats + 0.5 * ties) / k
            opp = opponent[team]
            opp_score = float(wk.scores[opp])
            credit = comparison_credit(s, opp_score)
            # Same-week difficulty of the opponent actually faced, measured
            # only against the other teams this team could have faced.
            field = [o for o in others if o != opp]
            opp_pct = (
                (
                    sum(1 for o in field if opp_score > float(wk.scores[o]))
                    + 0.5 * sum(1 for o in field if opp_score == float(wk.scores[o]))
                )
                / len(field)
                if field
                else None
            )
            mean_others = sum(float(wk.scores[o]) for o in others) / k
            row = {
                "week": wk.week,
                "teamKey": team,
                "score": round(s, 2),
                "opponentKey": opp,
                "opponentScore": round(opp_score, 2),
                "h2hResult": "W" if credit == 1.0 else ("L" if credit == 0.0 else "T"),
                "h2hCredit": credit,
                "allPlayWins": beats,
                "allPlayTies": ties,
                "allPlayLosses": k - beats - ties,
                "allPlayRate": rate,
                "scheduleImpact": credit - rate,
                "opponentScorePercentile": opp_pct,
                "pointsFacedVsField": opp_score - mean_others,
            }
            week_rows.append(row)
            t = teams.setdefault(
                team,
                {
                    "teamKey": team,
                    "games": 0,
                    "h2hWins": 0,
                    "h2hLosses": 0,
                    "h2hTies": 0,
                    "actualH2HCredits": 0.0,
                    "allPlayWins": 0,
                    "allPlayLosses": 0,
                    "allPlayTies": 0,
                    "equalOpponentExpectedH2HCredits": 0.0,
                    "pointsFor": 0.0,
                    "pointsFaced": 0.0,
                    "pointsFacedVsField": 0.0,
                    "_pctSum": 0.0,
                    "_pctN": 0,
                },
            )
            t["games"] += 1
            t["h2hWins"] += int(credit == 1.0)
            t["h2hLosses"] += int(credit == 0.0)
            t["h2hTies"] += int(credit == 0.5)
            t["actualH2HCredits"] += credit
            t["allPlayWins"] += beats
            t["allPlayTies"] += ties
            t["allPlayLosses"] += k - beats - ties
            t["equalOpponentExpectedH2HCredits"] += rate
            t["pointsFor"] += s
            t["pointsFaced"] += opp_score
            t["pointsFacedVsField"] += opp_score - mean_others
            if opp_pct is not None:
                t["_pctSum"] += opp_pct
                t["_pctN"] += 1

    if unsupported:
        return {
            "state": STATE_UNSUPPORTED,
            "reason": "format_not_one_game_per_team_week",
            "issues": all_issues,
            "teams": {},
            "weeks": [],
        }

    for key, t in teams.items():
        t["excludedWeeks"] = sorted(excluded.get(key, []))
        t["byeWeeks"] = sorted(byes.get(key, []))
    for t in teams.values():
        ap_n = t["allPlayWins"] + t["allPlayLosses"] + t["allPlayTies"]
        t["allPlayRate"] = (t["allPlayWins"] + 0.5 * t["allPlayTies"]) / ap_n if ap_n else None
        t["scheduleImpact"] = t["actualH2HCredits"] - t["equalOpponentExpectedH2HCredits"]
        t["avgOpponentScorePercentile"] = t["_pctSum"] / t["_pctN"] if t["_pctN"] else None
        del t["_pctSum"], t["_pctN"]

    state = STATE_PARTIAL if all_issues else STATE_COMPLETE
    if not teams:
        state, all_issues = STATE_UNAVAILABLE, all_issues or ["no_evaluable_games"]
    return {
        "state": state,
        "issues": all_issues,
        # A team every one of whose games was excluded has no row; name it.
        "teamsWithoutEvaluableGames": sorted(set(excluded) - set(teams)),
        "teams": teams,
        "weeks": sorted(week_rows, key=lambda r: (r["week"], r["teamKey"])),
        "finalizedWeeks": [w.week for w in ordered],
    }


# ── Snapshot adapter ─────────────────────────────────────────────────────


def _team_key(registry: Any, league_id: str, roster_id: Any) -> str | None:
    """A TEAM identity for one season: its owner when resolvable, else the
    roster itself.  An orphan roster (no owner that season) still played real
    games that other teams' records depend on, so it stays a participant --
    dropping it silently removed those games (measured: dynasty_new 2024,
    rosters 3 and 5)."""
    owner = metrics.resolve_owner(registry, league_id, roster_id)
    if owner:
        return owner
    try:
        return f"roster:{int(roster_id)}"
    except (TypeError, ValueError):
        return None


def week_matchup_structure(
    entries: Sequence[Mapping[str, Any]],
    key_of: Callable[[Mapping[str, Any]], Any],
) -> tuple[list[tuple[Any, Any]], tuple[Any, ...], list[str]]:
    """``(pairs, byes, structural_issues)`` for one week's matchup rows.

    THE grouping rule for "who played whom".  Deliberately not
    ``metrics.matchup_pairs``, which silently drops any group that is not
    exactly two rows -- a broken matchup would then look like a bye and
    the season like complete.  ``key_of`` maps a row to a team identity
    (``None`` skips the row), so a consumer keyed by roster id shares this
    rule instead of re-deriving it:

    * no ``matchup_id`` and a score -> a real bye;
    * no ``matchup_id`` and no score -> ``unscored:<team>`` (missing data);
    * a one-row group -> ``unpaired:<team>`` (partner row missing);
    * a group of three or more -> ``group_size:<n>:<teams>`` (unsupported).
    """
    groups: dict[Any, list[Any]] = {}
    bye_teams: list[Any] = []
    structural: list[str] = []
    for entry in entries:
        key = key_of(entry)
        if key is None or key == "":
            continue
        mid = entry.get("matchup_id")
        if mid is None:
            if entry.get("points") is not None:
                bye_teams.append(key)
            else:
                # Neither a score nor a matchup in a finalized week is
                # missing data, not a quiet bye.
                structural.append(f"unscored:{key}")
            continue
        groups.setdefault(mid, []).append(key)
    pairs: list[tuple[Any, Any]] = []
    for mid in sorted(groups, key=str):
        members = groups[mid]
        if len(members) == 2:
            pairs.append((members[0], members[1]))
        elif len(members) == 1:
            structural.append(f"unpaired:{members[0]}")
        else:
            structural.append(
                f"group_size:{len(members)}:{','.join(sorted(str(m) for m in members))}"
            )
    return pairs, tuple(sorted(bye_teams, key=str)), structural


def season_week_inputs(
    season: SeasonSnapshot, registry: Any, *, cutoff_week: int | None = None
) -> list[WeekInput]:
    """Finalized regular-season weeks as pure inputs.

    Week gate: ``metrics.final_regular_season_weeks`` (the canonical
    finished-week rule shared with Luck and Power Rankings).  Inside a
    counted week an absent score is missing and ``0.0`` is an observation,
    exactly as ``luck._season_weekly_scores`` treats them.
    """
    out: list[WeekInput] = []
    for wk in metrics.final_regular_season_weeks(season):
        if cutoff_week is not None and wk > cutoff_week:
            continue
        entries = season.matchups_by_week.get(wk) or []
        scores: dict[str, float] = {}
        for entry in entries:
            if entry.get("points") is None:
                continue
            key = _team_key(registry, season.league_id, entry.get("roster_id"))
            if key:
                scores[key] = float(metrics.matchup_points(entry))
        pairs, bye_teams, structural = week_matchup_structure(
            entries, lambda entry: _team_key(registry, season.league_id, entry.get("roster_id"))
        )
        if scores or structural:
            out.append(
                WeekInput(
                    week=wk,
                    scores=scores,
                    pairs=pairs,
                    byes=bye_teams,
                    structural_issues=tuple(structural),
                )
            )
    return out


def _digest(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _score_median_records(inputs: Sequence[WeekInput]) -> dict[str, dict[str, int]]:
    """Median-game results derived from the fixed scores: each team-week
    against the median of every score posted that week (>: win, <: loss,
    ==: tie).  Used only to CROSS-CHECK the host record; a disagreement makes
    the median component unavailable rather than published."""
    import statistics

    out: dict[str, dict[str, int]] = {}
    for wk in inputs:
        if len(wk.scores) < 2:
            continue
        med = statistics.median(float(v) for v in wk.scores.values())
        for team, score in wk.scores.items():
            rec = out.setdefault(team, {"wins": 0, "losses": 0, "ties": 0})
            score = float(score)
            rec["wins" if score > med else "losses" if score < med else "ties"] += 1
    return out


def _official_records(season: SeasonSnapshot, registry: Any) -> dict[str, dict[str, Any]]:
    """The host's official record per team.  A roster whose settings carry no
    record is left out (``official_record_missing``), never read as 0-0."""
    out: dict[str, dict[str, Any]] = {}
    for roster in season.rosters or []:
        oid = _team_key(registry, season.league_id, roster.get("roster_id"))
        settings = roster.get("settings") or {}
        if not oid or not all(k in settings for k in ("wins", "losses")):
            continue
        rec = metrics.regular_season_settings_record(roster)
        out[oid] = {"wins": rec["wins"], "losses": rec["losses"], "ties": rec["ties"]}
    return out


#: Mirrors ``schedule_timing.ALGORITHM_VERSION`` (pinned by a test); kept
#: here so the generation id does not need the deferred import.
TIMING_ALGORITHM_VERSION = "schedule-timing-2026.09-b2"


def _timing_block(inputs: list[WeekInput], cache_key: str) -> dict[str, Any]:
    """Timing-only summaries; a failure here must never cost the season its
    equal-opponent contract."""
    from . import schedule_timing  # deferred: schedule_timing imports this module

    try:
        return schedule_timing.timing_summary(inputs, cache_key=cache_key)
    except Exception:  # noqa: BLE001 -- isolate the second model
        _LOG.exception("timing_only_v1 failed")
        return {"state": "failed", "teams": {}}


def season_contract(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    cutoff_week: int | None = None,
    include_weeks: bool = True,
) -> dict[str, Any]:
    """The versioned, typed schedule-impact contract for one season."""
    registry = snapshot.managers
    inputs = season_week_inputs(season, registry, cutoff_week=cutoff_week)
    core = compute_schedule_impact(inputs)
    median = metrics.median_game_enabled(season)
    official = _official_records(season, registry)
    score_median = _score_median_records(inputs) if median else {}

    rows: list[dict[str, Any]] = []
    for oid, t in core["teams"].items():
        rec = official.get(oid)
        h2h_games = t["h2hWins"] + t["h2hLosses"] + t["h2hTies"]
        component = {"state": "unavailable", "reason": "official_record_missing"}
        if rec is not None:
            off_games = rec["wins"] + rec["losses"] + rec["ties"]
            per_week = 2 if median else 1
            if median is None:
                component = {"state": "unavailable", "reason": "median_setting_unknown"}
            elif off_games != h2h_games * per_week:
                # The host record covers a different set of weeks than the
                # finalized head-to-head games (or counts something else):
                # never derive a median record from misaligned totals.
                component = {"state": "unavailable", "reason": "official_record_unaligned"}
            elif median:
                derived = {
                    "wins": rec["wins"] - t["h2hWins"],
                    "losses": rec["losses"] - t["h2hLosses"],
                    "ties": rec["ties"] - t["h2hTies"],
                }
                from_scores = score_median.get(oid)
                if (
                    all(0 <= v <= h2h_games for v in derived.values())
                    and from_scores is not None
                    and from_scores == derived
                    and not t["excludedWeeks"]
                ):
                    component = {"state": "complete", **derived}
                else:
                    # The host's head-to-head half differs from the scores
                    # (stat correction, commissioner edit, tie rule) -- never
                    # blame that difference on the median game.
                    component = {"state": "unavailable", "reason": "official_record_inconsistent"}
            else:
                component = {"state": "not_applicable"}
        if oid.startswith("roster:"):
            rid = int(oid.split(":", 1)[1])
            display = None  # an orphan roster has no manager that season
        else:
            rid = next(
                (
                    r
                    for (lid, r), o in registry.roster_to_owner.items()
                    if lid == season.league_id and o == oid
                ),
                None,
            )
            display = metrics.display_name_for(snapshot, oid)
        rows.append(
            {
                **{k: v for k, v in t.items()},
                "ownerId": None if oid.startswith("roster:") else oid,
                "teamKey": oid,
                "rosterId": rid,
                "orphanRoster": oid.startswith("roster:"),
                "displayName": display,
                "teamName": metrics.team_name(snapshot, season.league_id, rid),
                "officialRecord": rec,
                "medianComponent": component,
            }
        )
    score_hash = _digest(
        [
            (w.week, sorted(w.scores.items()), sorted(tuple(sorted(p)) for p in w.pairs))
            for w in inputs
        ]
    )
    # Milestone B (timing_only_v1): same finalized weeks, same scores; a
    # different model id, published beside -- never blended into -- the
    # equal-opponent numbers above.
    # The cache key must cover everything the timing model reads: scores,
    # pairs AND structural issues (they decide supported vs unsupported).
    timing_key = _digest([score_hash, [(w.week, sorted(w.structural_issues)) for w in inputs]])
    timing = _timing_block(inputs, timing_key)
    for row in rows:
        row["timingOnly"] = timing["teams"].get(row["teamKey"])
    rows.sort(key=lambda r: (-r["scheduleImpact"], r["teamKey"]))

    config = {"medianGame": median, "teams": len(season.rosters or [])}
    config_hash = _digest(config)
    official_hash = _digest(sorted(official.items()))
    generation = _digest(
        [
            ALGORITHM_VERSION,
            MODEL_EQUAL_OPPONENT,
            TIMING_ALGORITHM_VERSION,
            season.league_id,
            season.season,
            score_hash,
            config_hash,
            official_hash,
        ]
    )
    return {
        "state": core["state"],
        "issues": core.get("issues", []),
        "reason": core.get("reason"),
        "teamsWithoutEvaluableGames": core.get("teamsWithoutEvaluableGames", []),
        "season": season.season,
        "leagueId": season.league_id,
        "cutoffWeek": (core.get("finalizedWeeks") or [None])[-1],
        "finalizedWeeks": core.get("finalizedWeeks", []),
        "model": MODEL_DESCRIPTION,
        "algorithmVersion": ALGORITHM_VERSION,
        "scoreHash": score_hash,
        "configHash": config_hash,
        "config": config,
        "generationId": generation,
        "teams": rows,
        "timingOnly": {k: v for k, v in timing.items() if k != "teams"},
        "weeks": core["weeks"] if include_weeks else None,
    }


def build_block(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """The public block: every covered season's contract (summary rows;
    weekly detail is available from ``season_contract`` but not published
    until a surface uses it)."""
    current = snapshot.current_season
    by_season = {}
    for season in snapshot.seasons:
        # Weekly rows (~60 KB for a finished 12-team season) stay off the
        # public payload until a surface renders them (team pages, C).
        by_season[season.season] = season_contract(snapshot, season, include_weeks=False)
    return {
        "currentSeason": current.season if current else None,
        "bySeason": by_season,
    }
