"""AL-4a — the Game Day calibration scorecard (report-only, champion only).

What it answers: when the production Game Day model (``src.ros.game_day_sim``,
published per league-week by ``src.ros.game_day_live``) said "70 %", did about
70 % of those things happen? It scores the AS-KNOWN probabilities the model
already published — the append-only ``generations.jsonl`` index — against the
host's finals. It computes no probability, changes no served value and promotes
nothing: every receipt it emits carries ``promotes: False`` through the AL-0
evaluation-receipt owner.

Inputs (both written by ``src.ros.game_day_live``, read here, never rewritten):

* **predictions** — each league-week's ``generations.jsonl`` row: ``generationId``,
  ``inputsFetchedAt`` (when the generation's inputs were fetched — the instant
  the prediction was as-known), ``mode`` (``pregame`` / ``live`` / ``final``),
  ``modelVersion`` and per roster ``winMatchupPct`` / ``beatMedianPct`` /
  ``pointsBanked`` / ``expectedFinalBestBall``.
* **outcomes** — the league-week's LATEST ``generation.json`` once its resolved
  mode is ``final``: ``resolved.opponents`` + ``resolved.hostScores`` are the
  host's own matchup points (Sleeper ``matchups`` — the scoring source of record;
  a later stat correction publishes a NEWER generation, so the latest is the
  corrected answer), and ``render.medianRace`` carries each team's final
  BEAT / MISS / TIE under ``game_day_sim``'s own threshold rule. Nothing here
  re-derives a median or re-scores a point. If the latest generation REGRESSED to
  a non-final mode after a final was published, the latest FINAL row of the
  append-only index (its host ``actualScore`` per roster and ``medianRace``
  summary) is the outcome. A week that never published a final has NO outcome --
  it is reported, never guessed.

Rules (each pinned by ``tests/model_registry/test_game_day_calibration.py``):

* **Temporal guard.** The outcome of a league-week is first known at the
  ``inputsFetchedAt`` of its first ``final``-mode generation. A prediction is
  scored only when its ``inputsFetchedAt`` is STRICTLY earlier, and never when
  its own mode is ``final``. An unprovable instant is excluded, not assumed.
* **Missing is never imputed.** A roster whose probability is ``None`` (the
  simulation withheld it) is a missing prediction — counted, never scored as
  0.5 or 0. An event with no outcome (no final generation, a missing host score)
  is not scored. A tied outcome is not a binary event and is counted apart.
* **Duplicates are deduped** by ``generationId``; an identical repeat is a
  duplicate, a different body under the same id is a CONFLICT (first kept,
  counted, never silently merged).
* **Model versions are separate cohorts.** Nothing pools two ``modelVersion``
  values; a row with none is excluded (``model_version_unrecorded``).
* **One prediction per event per state.** Within (model version, event, game
  state) the LAST as-known generation is scored, so a burst of live
  regenerations cannot outweigh a quiet stretch (the score is independent of
  collector cadence).
* **Small samples are flagged, not presented.** A cohort with fewer than
  :data:`MIN_EVENTS` scored events is ``insufficient_sample`` and carries no
  metric (the AL-0 cohort rule). No interval or significance is claimed.
* **Deterministic.** No wall clock; identical inputs give byte-identical
  summaries and receipts.

Game state. ``pregame`` is the model's own mode. ``live`` is bucketed by a
QUARTER-ISH PROXY, not the game clock (the index carries no clock): the share of
the league's expected final best-ball points already banked in that generation
(:data:`LIVE_PROGRESS_EDGES`). A generation missing any roster's banked or
expected points is ``live_progress_unknown``. A live event that was already
SETTLED when predicted -- the model published 0 % / 100 %, or no involved roster
had expected production left -- is its own cohort, ``live_decided``, so solved
games cannot flatter the late-live calibration.

Privacy. Per-league aggregates of our own predictions are private decision
intelligence (``docs/MASTER_PRODUCT_PLAN.md`` §5): the summary and receipts go to
the private learning store (``data/learning/``), never ``docs/`` or ``data/ros/``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Sequence

from src.bdvm.backtest import brier
from src.dfs.metrics import SMALL_SAMPLE
from src.model_registry.evaluation_receipt import (
    VERDICT_INCONCLUSIVE,
    CohortResult,
    Estimate,
    EvaluationReceipt,
    cohort_result,
)
from src.model_registry.learning_receipt import (
    ROLE_INPUT,
    ROLE_OUTCOME,
    LearningReceipt,
    NotApplicable,
    ReceiptError,
    StoreRef,
    Unobserved,
    canonical_json,
    iso,
    model_version_id,
    parse_instant,
    sha256_text,
)

SCHEMA = "game-day-calibration-scorecard/v1"
FAMILY = "game_day_sim"
PRODUCER = "game_day_calibration_scorecard"
STORE = "game_day_generations"

TARGET_WIN = "winMatchup"
TARGET_MEDIAN = "beatMedian"
TARGETS: tuple[str, ...] = (TARGET_WIN, TARGET_MEDIAN)

STATE_PREGAME = "pregame"
STATE_LIVE_UNKNOWN = "live_progress_unknown"
#: Live buckets by the banked share of the league's expected final points.
#: A labelled PROXY for "quarter", not a game clock.
LIVE_PROGRESS_EDGES: tuple[float, ...] = (0.25, 0.5, 0.75)
LIVE_STATES: tuple[str, ...] = ("live_q1", "live_q2", "live_q3", "live_q4")
#: A live event whose result was already settled when the prediction was made:
#: the model published a certainty (0 or 100 %), or no involved roster had any
#: expected production left. Its own cohort, so a pile of solved games cannot
#: flatter the live-q4 calibration.
STATE_LIVE_DECIDED = "live_decided"
STATES: tuple[str, ...] = (STATE_PREGAME, *LIVE_STATES, STATE_LIVE_UNKNOWN, STATE_LIVE_DECIDED)
#: Points of expected production below which a roster has nothing left to play.
NO_REMAINING_EPSILON: float = 0.005

#: Minimum scored events for a cohort to carry a metric. Reuses the repo's
#: existing declared small-sample rule (``src.dfs.metrics.SMALL_SAMPLE``) rather
#: than inventing a second number. PRIOR, not fit.
MIN_EVENTS: int = SMALL_SAMPLE
#: Equal-width reliability bins over the predicted probability.
RELIABILITY_BINS: int = 10
#: A reliability bin with fewer predictions than this reports no observed rate.
#: PRIOR.
MIN_BIN_N: int = 10
#: Log loss clips p into [eps, 1 - eps] so a confident miss is finite. PRIOR;
#: the number of clipped predictions is reported beside the metric.
LOG_LOSS_EPSILON: float = 1e-4

_FINAL_RESULT = {"BEAT": 1, "MISS": 0, "TIE": None}

POINT_IN_TIME_RULE = (
    "a league-week's outcome is first known at the inputsFetchedAt of its first final-mode "
    "generation; a prediction is scored only when its own inputsFetchedAt is strictly earlier "
    "and its mode is pregame or live; within (modelVersion, event, state) the last as-known "
    "generation is scored"
)


# ── inputs ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LeagueWeekEvidence:
    """One league-week's stored Game Day evidence, exactly as read."""

    league_key: str
    season: int
    week: int
    #: ``generations.jsonl`` rows, oldest first, as stored.
    index_rows: Sequence[Mapping[str, Any]]
    #: ``generation.json`` (the latest generation), or ``None``.
    latest_generation: Mapping[str, Any] | None


@dataclass(frozen=True)
class WeekOutcomes:
    known_at: datetime
    revision_at: datetime
    revision_id: str
    #: (a, b) canonical pair -> 1 when ``a`` won, 0 when ``a`` lost, None for a tie;
    #: a pair absent from the map had no scoreable outcome.
    matchups: Mapping[tuple[str, str], int | None]
    #: roster -> 1 BEAT, 0 MISS, None TIE; ``None`` (the whole map) when the median
    #: race did not finish as ``final``.
    median: Mapping[str, int | None] | None
    median_state: str | None
    notes: Mapping[str, int]


@dataclass(frozen=True)
class ScoredPrediction:
    league_key: str
    model_version: str
    target: str
    state: str
    event: str
    p: float
    y: int
    as_known_at: datetime
    generation_id: str
    outcome_known_at: datetime
    outcome_revision_at: datetime
    outcome_revision_id: str


@dataclass
class ScorecardResult:
    summary: dict[str, Any]
    scored: list[ScoredPrediction] = field(default_factory=list)
    #: (league, version, target) -> outcome events eligible for scoring
    eligible_events: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    #: (league, version) -> {(season, week): {"rows": str, "finals": str}} digests
    lineage: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)


# ── helpers ──────────────────────────────────────────────────────────────────


def _roster_order(rid: str) -> tuple[int, Any]:
    text = str(rid)
    return (0, int(text)) if text.isdigit() else (1, text)


def _instant(value: Any) -> datetime | None:
    try:
        return parse_instant(value, what="instant")
    except (ReceiptError, ValueError, TypeError):
        return None


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _bump(counter: dict[str, int], key: str, by: int = 1) -> None:
    counter[key] = counter.get(key, 0) + by


def dedupe_index_rows(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[Mapping[str, Any]], dict[str, int]]:
    """Unique rows by ``generationId`` (first kept) and the census of what was dropped."""
    seen: dict[str, str] = {}
    out: list[Mapping[str, Any]] = []
    census: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            _bump(census, "not_a_row")
            continue
        gid = row.get("generationId")
        if not isinstance(gid, str) or not gid.strip():
            _bump(census, "no_generation_id")
            continue
        text = canonical_json(dict(row))
        if gid in seen:
            _bump(census, "duplicate" if seen[gid] == text else "conflict")
            continue
        seen[gid] = text
        out.append(row)
    return out, census


def _latest_final_row(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    best: tuple[Any, ...] | None = None
    out = None
    for r in rows:
        if r.get("mode") != "final":
            continue
        at = _instant(r.get("inputsFetchedAt"))
        if at is None:
            continue
        key = (at, str(r.get("generationId")))
        if best is None or key > best:
            best, out = key, r
    return out


def resolve_outcomes(
    ev: LeagueWeekEvidence, unique_rows: Sequence[Mapping[str, Any]]
) -> WeekOutcomes | str:
    """The league-week's host finals, or the reason there are none.

    Source of the finals, in order:

    1. the latest ``generation.json`` when it is ``final`` (the corrected answer);
    2. otherwise, when the latest generation REGRESSED to a non-final mode after a
       final was published, the latest FINAL row of the append-only index —
       its per-roster ``actualScore`` (the host score that generation used) and its
       ``medianRace`` summary — with pairings from ``resolved.opponents`` (pairings
       do not change within a week).

    A week that never published a final has no outcome."""
    gen = ev.latest_generation
    if not isinstance(gen, Mapping):
        return "no_generation"
    if (
        str(gen.get("leagueKey")) != str(ev.league_key)
        or _int(gen.get("season")) != int(ev.season)
        or _int(gen.get("week")) != int(ev.week)
    ):
        return "generation_identity_mismatch"
    resolved = gen.get("resolved") or {}
    mode = resolved.get("mode")
    opponents = resolved.get("opponents") or {}
    notes: dict[str, int] = {}
    final_row = _latest_final_row(unique_rows)
    if mode == "final":
        revision_at = _instant(gen.get("inputsFetchedAt"))
        if revision_at is None:
            return "final_generation_instant_unproven"
        revision_id = str(gen.get("generationId"))
        host = dict(resolved.get("hostScores") or {})
        race = (gen.get("render") or {}).get("medianRace") or {}
        teams = (race.get("teams") or ()) if isinstance(race, Mapping) else ()
        median_state = race.get("state") if isinstance(race, Mapping) else None
    elif final_row is not None:
        revision_at = _instant(final_row.get("inputsFetchedAt"))
        revision_id = str(final_row.get("generationId"))
        host = {
            str(rid): (side or {}).get("actualScore")
            for rid, side in (final_row.get("outcomes") or {}).items()
        }
        summary = final_row.get("medianRace") or {}
        median_state = summary.get("state") if isinstance(summary, Mapping) else None
        teams = [
            {"rosterId": rid, "finalResult": (t or {}).get("finalResult")}
            for rid, t in ((summary or {}).get("teams") or {}).items()
        ]
        _bump(notes, f"latest_generation_regressed_to:{mode}")
    else:
        return f"latest_generation_not_final:{mode}"
    finals = [
        t
        for t in (
            _instant(r.get("inputsFetchedAt")) for r in unique_rows if r.get("mode") == "final"
        )
        if t is not None
    ]
    known_at = min([*finals, revision_at])

    matchups: dict[tuple[str, str], int | None] = {}
    for rid, opp in sorted(opponents.items(), key=lambda kv: _roster_order(kv[0])):
        if opp is None:
            _bump(notes, "no_opponent")
            continue
        rid, opp = str(rid), str(opp)
        if str(opponents.get(opp)) != rid:
            _bump(notes, "asymmetric_pairing")
            continue
        a, b = sorted((rid, opp), key=_roster_order)
        if (a, b) in matchups or a != rid:
            continue
        sa, sb = _num(host.get(a)), _num(host.get(b))
        if sa is None or sb is None:
            _bump(notes, "host_score_missing")
            continue
        matchups[(a, b)] = 1 if sa > sb else 0 if sa < sb else None
        if sa == sb:
            _bump(notes, "matchup_tie")

    median: dict[str, int | None] | None = None
    if median_state == "final":
        median = {}
        for team in teams:
            if not isinstance(team, Mapping):
                continue
            result = team.get("finalResult")
            if result not in _FINAL_RESULT:
                _bump(notes, "median_result_missing")
                continue
            median[str(team.get("rosterId"))] = _FINAL_RESULT[result]
            if result == "TIE":
                _bump(notes, "median_tie")
    return WeekOutcomes(
        known_at=known_at,
        revision_at=revision_at,
        revision_id=revision_id,
        matchups=matchups,
        median=median,
        median_state=median_state,
        notes=notes,
    )


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def game_state(row: Mapping[str, Any]) -> str | None:
    """``pregame``, a live progress bucket, or ``None`` for any other mode."""
    mode = row.get("mode")
    if mode == "pregame":
        return STATE_PREGAME
    if mode != "live":
        return None
    banked = expected = 0.0
    outcomes = row.get("outcomes") or {}
    if not outcomes:
        return STATE_LIVE_UNKNOWN
    for side in outcomes.values():
        b = _num((side or {}).get("pointsBanked"))
        e = _num((side or {}).get("expectedFinalBestBall"))
        if b is None or e is None:
            return STATE_LIVE_UNKNOWN
        banked += b
        expected += e
    if expected <= 0:
        return STATE_LIVE_UNKNOWN
    share = banked / expected
    for edge, state in zip(LIVE_PROGRESS_EDGES, LIVE_STATES):
        if share < edge:
            return state
    return LIVE_STATES[-1]


def _decided(p: float, sides: Mapping[str, Any], involved: Sequence[str]) -> bool:
    """Settled before the prediction: a published certainty, or no involved roster
    with expected production left (both read off the same generation row)."""
    if p in (0.0, 1.0):
        return True
    if not involved:
        return False
    for rid in involved:
        side = sides.get(rid) or {}
        banked, expected = _num(side.get("pointsBanked")), _num(side.get("expectedFinalBestBall"))
        if banked is None or expected is None or expected - banked > NO_REMAINING_EPSILON:
            return False
    return True


def _probability(value: Any) -> float | None | str:
    """A percent in [0, 100] as a probability; ``None`` when withheld; ``"invalid"``."""
    if value is None:
        return None
    v = _num(value)
    if v is None or v < 0.0 or v > 100.0:
        return "invalid"
    return v / 100.0


# ── evaluation ───────────────────────────────────────────────────────────────


def evaluate(evidence: Sequence[LeagueWeekEvidence]) -> ScorecardResult:
    """Score every league-week's as-known predictions against its host finals."""
    result = ScorecardResult(summary={})
    weeks_out: dict[str, list[dict[str, Any]]] = {}
    # (version, target, state, event) -> (sort key, ScoredPrediction)
    best: dict[tuple[str, str, str, str, str], tuple[tuple[Any, ...], ScoredPrediction]] = {}

    for ev in sorted(evidence, key=lambda e: (str(e.league_key), int(e.season), int(e.week))):
        league = str(ev.league_key)
        unique, census = dedupe_index_rows(ev.index_rows)
        outcome = resolve_outcomes(ev, unique)
        exclusions: dict[str, int] = {}
        missing: dict[str, int] = {}
        versions = sorted({str(r.get("modelVersion")) for r in unique if r.get("modelVersion")})
        week_row: dict[str, Any] = {
            "season": int(ev.season),
            "week": int(ev.week),
            "generationRows": len(ev.index_rows),
            "uniqueGenerations": len(unique),
            "indexCensus": dict(sorted(census.items())),
            "modelVersions": versions,
        }
        rows_digest = sha256_text(canonical_json([dict(r) for r in unique]))
        if isinstance(outcome, str):
            week_row.update(outcome={"state": "unavailable", "reason": outcome})
            weeks_out.setdefault(league, []).append(week_row)
            continue
        week_row["outcome"] = {
            "state": "final",
            "knownAt": iso(outcome.known_at),
            "revisionAt": iso(outcome.revision_at),
            "revisionGenerationId": outcome.revision_id,
            "matchupsScoreable": sum(1 for v in outcome.matchups.values() if v is not None),
            "medianState": outcome.median_state,
            "medianScoreable": (
                None
                if outcome.median is None
                else sum(1 for v in outcome.median.values() if v is not None)
            ),
            "notes": dict(sorted(outcome.notes.items())),
        }
        prefix = f"{league}|{int(ev.season)}|w{int(ev.week)}"
        win_events = {
            pair: f"{prefix}|{pair[0]}v{pair[1]}"
            for pair, y in outcome.matchups.items()
            if y is not None
        }
        median_events = (
            {rid: f"{prefix}|r{rid}" for rid, y in outcome.median.items() if y is not None}
            if outcome.median is not None
            else {}
        )
        for version in versions:
            result.eligible_events.setdefault((league, version, TARGET_WIN), set()).update(
                win_events.values()
            )
            result.eligible_events.setdefault((league, version, TARGET_MEDIAN), set()).update(
                median_events.values()
            )
            result.lineage.setdefault((league, version), {})[
                f"{int(ev.season)}-w{int(ev.week)}"
            ] = {"rowsSha256": rows_digest, "outcomeGenerationId": outcome.revision_id}

        for row in unique:
            mode = row.get("mode")
            if mode == "final":
                _bump(exclusions, "post_outcome_final_mode")
                continue
            state = game_state(row)
            if state is None:
                _bump(exclusions, "unknown_mode")
                continue
            at = _instant(row.get("inputsFetchedAt"))
            if at is None:
                _bump(exclusions, "unproven_instant")
                continue
            if at >= outcome.known_at:
                _bump(exclusions, "at_or_after_outcome")
                continue
            version = row.get("modelVersion")
            if not version:
                _bump(exclusions, "model_version_unrecorded")
                continue
            version = str(version)
            gid = str(row["generationId"])
            sides = row.get("outcomes") or {}
            targets: list[tuple[str, str, Any, int, tuple[str, ...]]] = []
            for (a, b), event in win_events.items():
                y = outcome.matchups[(a, b)]
                targets.append(
                    (TARGET_WIN, event, (sides.get(a) or {}).get("winMatchupPct"), y, (a, b))
                )
            league_rosters = tuple(str(r) for r in sides)
            for rid, event in median_events.items():
                y = outcome.median[rid]  # type: ignore[index]
                targets.append(
                    (
                        TARGET_MEDIAN,
                        event,
                        (sides.get(rid) or {}).get("beatMedianPct"),
                        y,
                        league_rosters,
                    )
                )
            for target, event, raw, y, involved in targets:
                p = _probability(raw)
                if p is None:
                    _bump(missing, f"{target}:withheld_or_absent")
                    continue
                if p == "invalid":
                    _bump(exclusions, f"{target}:invalid_probability")
                    continue
                event_state = state
                if state != STATE_PREGAME and _decided(p, sides, involved):
                    event_state = STATE_LIVE_DECIDED
                scored = ScoredPrediction(
                    league_key=league,
                    model_version=version,
                    target=target,
                    state=event_state,
                    event=event,
                    p=float(p),
                    y=int(y),
                    as_known_at=at,
                    generation_id=gid,
                    outcome_known_at=outcome.known_at,
                    outcome_revision_at=outcome.revision_at,
                    outcome_revision_id=outcome.revision_id,
                )
                key = (league, version, target, event_state, event)
                rank = (at, gid)
                if key not in best or rank > best[key][0]:
                    best[key] = (rank, scored)
        week_row["predictionExclusions"] = dict(sorted(exclusions.items()))
        week_row["predictionsMissingPerGenerationEvent"] = dict(sorted(missing.items()))
        weeks_out.setdefault(league, []).append(week_row)

    result.scored = [best[k][1] for k in sorted(best)]
    result.summary = _summary(result, weeks_out)
    return result


# ── metrics ──────────────────────────────────────────────────────────────────


def _metrics(pairs: Sequence[ScoredPrediction]) -> dict[str, Any]:
    ps = [s.p for s in pairs]
    ys = [s.y for s in pairs]
    n = len(ps)
    b = brier(ps, ys)
    clipped = 0
    total = 0.0
    for p, y in zip(ps, ys):
        q = min(1.0 - LOG_LOSS_EPSILON, max(LOG_LOSS_EPSILON, p))
        if q != p:
            clipped += 1
        total += -math.log(q if y == 1 else 1.0 - q)
    return {
        "brier": b,
        "logLoss": total / n,
        "brierSkillVsCoinFlip": 1.0 - b / 0.25,
        "meanPredicted": sum(ps) / n,
        "observedRate": sum(ys) / n,
        "logLossClipped": clipped,
    }


def reliability(pairs: Sequence[ScoredPrediction]) -> list[dict[str, Any]]:
    """Equal-width bins; a thin bin reports its n and no rate."""
    bins: list[list[ScoredPrediction]] = [[] for _ in range(RELIABILITY_BINS)]
    for s in pairs:
        bins[min(RELIABILITY_BINS - 1, int(s.p * RELIABILITY_BINS))].append(s)
    out = []
    for i, rows in enumerate(bins):
        lo, hi = i / RELIABILITY_BINS, (i + 1) / RELIABILITY_BINS
        enough = len(rows) >= MIN_BIN_N
        out.append(
            {
                "bin": f"{lo:.1f}-{hi:.1f}",
                "n": len(rows),
                "status": "ok" if enough else "insufficient_sample",
                "meanPredicted": _r(sum(s.p for s in rows) / len(rows)) if enough else None,
                "observedRate": _r(sum(s.y for s in rows) / len(rows)) if enough else None,
            }
        )
    return out


def _r(value: float) -> float:
    return round(float(value), 6)


def _cohort_summary(
    pairs: Sequence[ScoredPrediction], eligible: int, *, label: Mapping[str, str]
) -> dict[str, Any]:
    n = len(pairs)
    events = len({s.event for s in pairs})
    sufficient = events >= MIN_EVENTS
    metrics = {k: _r(v) for k, v in _metrics(pairs).items()} if sufficient and n else None
    return {
        **dict(label),
        "n": n,
        "events": events,
        "outcomeEvents": eligible,
        "missingCount": max(0, eligible - events),
        "coverage": _r(events / eligible) if eligible else None,
        "status": "ok" if sufficient else "insufficient_sample",
        "metrics": metrics,
        "reliability": reliability(pairs) if sufficient else None,
    }


def _groups(result: ScorecardResult) -> dict[tuple[str, str, str], list[ScoredPrediction]]:
    groups: dict[tuple[str, str, str], list[ScoredPrediction]] = {}
    for key in result.eligible_events:
        groups.setdefault(key, [])
    for s in result.scored:
        groups.setdefault((s.league_key, s.model_version, s.target), []).append(s)
    return groups


def _summary(result: ScorecardResult, weeks: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    leagues: dict[str, Any] = {}
    for league in sorted(weeks):
        leagues[league] = {"weeks": weeks[league], "cohorts": []}
    for (league, version, target), pairs in sorted(_groups(result).items()):
        eligible = len(result.eligible_events.get((league, version, target), ()))
        block = leagues.setdefault(league, {"weeks": [], "cohorts": []})
        block["cohorts"].append(
            _cohort_summary(
                pairs,
                eligible,
                label={"modelVersion": version, "target": target, "state": "all_states_pooled"},
            )
        )
        for state in STATES:
            in_state = [s for s in pairs if s.state == state]
            block["cohorts"].append(
                _cohort_summary(
                    in_state,
                    eligible,
                    label={"modelVersion": version, "target": target, "state": state},
                )
            )
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "reportOnly": True,
        "promotes": False,
        "pointInTimeRule": POINT_IN_TIME_RULE,
        "constants": {
            "minEvents": MIN_EVENTS,
            "minEventsBasis": "src.dfs.metrics.SMALL_SAMPLE (declared small-sample rule; PRIOR)",
            "reliabilityBins": RELIABILITY_BINS,
            "minBinN": MIN_BIN_N,
            "logLossEpsilon": LOG_LOSS_EPSILON,
            "liveProgressEdges": list(LIVE_PROGRESS_EDGES),
            "liveProgressBasis": (
                "share of the league's expected final best-ball points already banked "
                "(a quarter-ish proxy; the generation index carries no game clock)"
            ),
        },
        "notes": [
            "pooled cohorts count one prediction per (event, state): an event appears once per "
            "state it was predicted in, so pooled n is not a count of independent events",
            "coverage = scored events / outcome events in weeks where this modelVersion "
            "published at least one generation",
            "winMatchupPct excludes the simulated tie mass; tied finals are not scored",
        ],
        "leagues": leagues,
    }


# ── receipts ─────────────────────────────────────────────────────────────────


def _estimates(pairs: Sequence[ScoredPrediction]) -> dict[str, Estimate]:
    m = _metrics(pairs)
    return {k: Estimate(point=_r(v)) for k, v in m.items() if k != "logLossClipped"}


def _cohort(
    pairs: Sequence[ScoredPrediction], eligible: int, cohort: Mapping[str, str]
) -> CohortResult:
    events = len({s.event for s in pairs})
    return cohort_result(
        cohort,
        n=len(pairs),
        metrics=_estimates(pairs) if pairs and events >= MIN_EVENTS else None,
        insufficient=events < MIN_EVENTS,
        missing_count=max(0, eligible - events),
        coverage=_r(events / eligible) if eligible else None,
        note=f"{events} independent events; minimum {MIN_EVENTS}",
    )


def receipts(result: ScorecardResult, *, code_sha: str) -> list[LearningReceipt]:
    """One EVALUATION receipt per (league, modelVersion, target). Champion only."""
    if not str(code_sha or "").strip():
        raise ReceiptError("the scorecard code revision must be stated")
    out: list[LearningReceipt] = []
    for (league, version, target), pairs in sorted(_groups(result).items()):
        eligible = len(result.eligible_events.get((league, version, target), ()))
        lineage = result.lineage.get((league, version), {})
        digest = sha256_text(
            canonical_json(
                {
                    "lineage": lineage,
                    "scored": [
                        [s.event, s.state, s.generation_id, s.p, s.y, s.outcome_revision_id]
                        for s in pairs
                    ],
                }
            )
        )
        native = f"{league}|{version}|{target}|{digest}"
        if pairs:
            cutoff = max(s.as_known_at for s in pairs)
            target_at = max(s.outcome_known_at for s in pairs)
            revision_at = max(s.outcome_revision_at for s in pairs)
            prediction_set: Any = StoreRef(
                store=STORE,
                key=f"{league}/generations.jsonl#{version}:scored={len(pairs)}:sha256={digest}",
                role=ROLE_INPUT,
                known_at=cutoff,
                fidelity="exact",
                basis="the newest inputsFetchedAt among the scored generations",
            )
            outcome_set: Any = StoreRef(
                store=STORE,
                key=f"{league}/generation.json#final:weeks={len(lineage)}:sha256={digest}",
                role=ROLE_OUTCOME,
                known_at=revision_at,
                fidelity="exact",
                basis=(
                    "the latest final generation per week (host scores after any absorbed "
                    "stat correction); outcome first known at the first final-mode generation"
                ),
                revision=sha256_text(
                    canonical_json(sorted({s.outcome_revision_id for s in pairs}))
                )[:16],
            )
        else:
            cutoff = target_at = None
            prediction_set = Unobserved("no prediction passed the temporal guard")
            outcome_set = Unobserved("no scored prediction, so no outcome was joined")
        cohorts = [
            _cohort(
                [s for s in pairs if s.state == state],
                eligible,
                {"leagueKey": league, "state": state},
            )
            for state in STATES
        ]
        ev = EvaluationReceipt(
            producer=PRODUCER,
            native_id=native,
            model_family=FAMILY,
            model_version_id=model_version_id(FAMILY, version),
            role="champion",
            task=f"game_day_{target}_probability",
            target=(
                "P(roster wins its head-to-head matchup) vs the host's final points"
                if target == TARGET_WIN
                else "P(roster beats the league median) vs the final BEAT / MISS result"
            ),
            horizon="within league-week: pregame and live progress buckets",
            cohort_keys=("leagueKey", "state"),
            cutoff=cutoff,
            target_event_at=target_at,
            point_in_time_rule=POINT_IN_TIME_RULE,
            feature_manifest_hash=NotApplicable(
                "a calibration scorecard reads the model's published probabilities, not features"
            ),
            input_pins={
                "codeSha": str(code_sha),
                "sourceHashes": {"generationLineageSha256": sha256_text(canonical_json(lineage))},
                "snapshotHash": NotApplicable(
                    "Game Day predictions are league-week generations, not a board snapshot"
                ),
                "scoringFingerprint": Unobserved(
                    "the generation index does not stamp the league scoring fingerprint"
                ),
            },
            prediction_set=prediction_set,
            outcome_set=outcome_set,
            preregistration=NotApplicable(
                "report-only champion scorecard: no challenger and no decision rule"
            ),
            overall=_cohort(pairs, eligible, {"leagueKey": league, "state": "all_states_pooled"}),
            cohorts=cohorts,
            holdout_design=("chronological",),
            proposed_verdict=VERDICT_INCONCLUSIVE,
            verdict_basis=(
                "report-only calibration scorecard of the production champion; no challenger "
                "was evaluated, so no comparative verdict exists"
            ),
            extra={
                "schema": SCHEMA,
                "reliabilityByState": {
                    state: (
                        reliability(in_state)
                        if len({s.event for s in in_state}) >= MIN_EVENTS
                        else None
                    )
                    for state in STATES
                    for in_state in [[s for s in pairs if s.state == state]]
                },
                "weeks": sorted(lineage),
                "minEvents": MIN_EVENTS,
            },
        )
        out.append(ev.to_learning_receipt())
    return out
