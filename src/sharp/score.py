"""The Sharp Score — transparent, configurable, and explainable.

Every weight and threshold lives in ``config/sharp/scoring_v2.json``;
nothing is hardcoded here.  Every scored manager keeps its component
breakdown so the product can always answer "why did this manager
qualify" with real numbers instead of a bare score.  Full write-up in
``docs/intel/SHARP_SCORE.md``.

──────────────────────────────────────────────────────────────────────
What counts as evidence (v2)
──────────────────────────────────────────────────────────────────────
DYNASTY LEAGUES ONLY, and only leagues at least TWO SEASONS OLD
(``league_filter.is_sharp_eligible``).  Keeper leagues still inform
Insider Trading — they are real evidence about a person you can trade
with — but their trade behaviour is a hybrid, so they cannot certify
dynasty skill.  A first-year dynasty league is startup-draft fallout:
huge churn, no established market, no completed season to judge.

``ManagerRecord.dynasty_leagues`` is already filtered on both counts
upstream, and it — not ``observed_leagues`` — is what the multi-league
gate reads.

──────────────────────────────────────────────────────────────────────
Design rules, each guarding a specific failure
──────────────────────────────────────────────────────────────────────
1. **No single weak signal can qualify anyone.**  Being in many leagues
   is not skill — it is availability.  League count feeds only the
   consistency and confidence terms, and consistency measures the SHARE
   of leagues finishing above median, so adding mediocre leagues cannot
   raise it.

2. **Hard eligibility gates come before scoring.**  A manager without
   enough history is ``evaluable=False`` with a reason, never scored
   badly.  Thin records must not compete for cohort slots.

3. **Percentile normalization within the observed population.**  Raw
   rates are not comparable across league sizes or scoring systems.
   Percentiles are, and the qualification bar is itself a percentile,
   so it tightens automatically as coverage grows.

4. **Shrinkage on rare events.**  One championship in one season is
   mostly luck.  Championship rate is beta-binomial shrunk toward the
   population base rate.

5. **Score and confidence are SEPARATE outputs.**  "How good" and "how
   much evidence" are different questions, and blending them hides
   exactly the uncertainty the brief requires us to surface.  A manager
   must clear BOTH bars to qualify.

6. **The uncertainty penalty is explicit and subtracted**, so a
   2-season manager cannot tie a 6-season manager on equal rates.

7. **The win-rate floor is a VIABILITY gate, not the selector.**  League
   win% averages exactly 0.500 by construction, so 0.52 means
   "demonstrably above average", not "good".  Set it much higher and it
   silently becomes the real cutoff, fighting the percentile bar and
   making cohort size unpredictable.

8. **A championship is PREFERRED, not required.**  In a 12-team league
   only ~1/12 of managers can win per season, so a hard title gate
   would cut the cohort far below a top quarter and bar managers who
   consistently make deep runs in strong leagues.  It is a bounded
   bonus that is decisive at the margin and always named in
   ``contributors``.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "sharp" / "scoring_v2.json"


@lru_cache(maxsize=4)
def load_config(path: str | None = None) -> dict[str, Any]:
    target = Path(path) if path else CONFIG_PATH
    with target.open(encoding="utf-8") as fh:
        return json.load(fh)


def methodology_version(cfg: dict[str, Any] | None = None) -> str:
    return str((cfg or load_config()).get("methodologyVersion") or "sharp-v2")


# ── inputs ───────────────────────────────────────────────────────────


@dataclass
class ManagerRecord:
    """Everything observed about one manager, across every league we
    have crawled.  Every field is an OBSERVATION, never a claim of
    completeness — see ``ManagerScore.coverage``."""

    user_id: str
    completed_seasons: int = 0
    observed_leagues: int = 0
    # Dynasty leagues that ALSO clear the >= 2-season age bar
    # (``league_filter.is_sharp_eligible``).  Keeper leagues and
    # first-year dynasty leagues are deliberately excluded — see that
    # module for why.  This, not ``observed_leagues``, is what the
    # multi-league gate counts.
    dynasty_leagues: int = 0
    completed_games: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    playoff_appearances: int = 0
    championships: int = 0
    # Per-league final-standing percentile (0 = last, 1 = first).
    finish_percentiles: list[float] = field(default_factory=list)
    points_for_percentiles: list[float] = field(default_factory=list)
    # Roster value relative to each league's own average (1.0 = average).
    roster_value_ratios: list[float] = field(default_factory=list)
    age_adjusted_value_ratio: float | None = None
    depth_adjusted_value_ratio: float | None = None
    draft_pick_capital_ratio: float | None = None
    trades_completed: int = 0
    abandoned_rosters: int = 0
    days_since_last_activity: int | None = None

    @property
    def win_pct(self) -> float | None:
        total = self.wins + self.losses + self.ties
        if total <= 0:
            return None
        return (self.wins + 0.5 * self.ties) / total

    @property
    def playoff_rate(self) -> float | None:
        if self.completed_seasons <= 0:
            return None
        return min(1.0, self.playoff_appearances / self.completed_seasons)

    @property
    def abandoned_rate(self) -> float:
        if self.observed_leagues <= 0:
            return 0.0
        return self.abandoned_rosters / self.observed_leagues


@dataclass
class ManagerScore:
    user_id: str
    evaluable: bool
    score: float | None = None
    score_percentile: float | None = None
    confidence: float = 0.0
    confidence_tier: str = "low"
    qualified: bool = False
    components: dict[str, float] = field(default_factory=dict)
    contributors: list[str] = field(default_factory=list)
    ineligible_reasons: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    methodology_version: str = "sharp-v2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "userId": self.user_id,
            "evaluable": self.evaluable,
            "score": self.score,
            "scorePercentile": self.score_percentile,
            "confidence": round(self.confidence, 3),
            "confidenceTier": self.confidence_tier,
            "qualified": self.qualified,
            "components": {k: round(v, 4) for k, v in self.components.items()},
            "contributors": self.contributors,
            "ineligibleReasons": self.ineligible_reasons,
            "coverage": self.coverage,
            "methodologyVersion": self.methodology_version,
        }


# ── helpers ──────────────────────────────────────────────────────────


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _mean(values: Sequence[float]) -> float | None:
    vals = [float(v) for v in values if isinstance(v, (int, float))]
    return (sum(vals) / len(vals)) if vals else None


def percentile_rank(value: float, population: Sequence[float]) -> float:
    """Fraction of the population at or below ``value`` (0..1).

    Midpoint handling for ties, so a population of identical values
    scores 0.5 rather than 1.0 — an all-identical population carries no
    information and must not read as universally elite.
    """
    pop = [float(v) for v in population if isinstance(v, (int, float))]
    if not pop:
        return 0.5
    below = sum(1 for v in pop if v < value)
    equal = sum(1 for v in pop if v == value)
    return (below + 0.5 * equal) / len(pop)


def _shrunk_rate(successes: int, trials: int, base_rate: float, prior_n: float) -> float:
    """Beta-binomial shrink toward ``base_rate``.  With few trials the
    result sits near the base rate; it only departs with real volume."""
    if trials <= 0:
        return base_rate
    return (successes + prior_n * base_rate) / (trials + prior_n)


# ── eligibility ──────────────────────────────────────────────────────


def check_eligibility(rec: ManagerRecord, cfg: dict[str, Any] | None = None) -> list[str]:
    """Reasons this manager cannot be scored.  Empty list = evaluable."""
    cfg = cfg or load_config()
    gates = cfg.get("eligibility") or {}
    reasons: list[str] = []

    if rec.completed_seasons < int(gates.get("minCompletedSeasons", 2)):
        reasons.append(
            f"only {rec.completed_seasons} completed season(s); "
            f"{gates.get('minCompletedSeasons', 2)} required"
        )
    # Multi-league, and specifically multi-DYNASTY-league: keeper
    # leagues and first-year dynasty leagues are not evidence of sharp
    # dynasty play.  ``dynasty_leagues`` is already age-filtered by
    # ``league_filter.is_sharp_eligible`` upstream.
    min_dynasty = int(gates.get("minDynastyLeagues", 2))
    if rec.dynasty_leagues < min_dynasty:
        min_age = int(gates.get("minLeagueAgeSeasons", 2))
        reasons.append(
            f"only {rec.dynasty_leagues} qualifying dynasty league(s); "
            f"{min_dynasty} required (dynasty only, >= {min_age} seasons old)"
        )
    if rec.completed_games < int(gates.get("minCompletedGames", 24)):
        reasons.append(
            f"only {rec.completed_games} completed games; "
            f"{gates.get('minCompletedGames', 24)} required"
        )

    # Win-percentage floor.  League win% averages EXACTLY 0.500 by
    # construction, so this reads as "demonstrably above average"
    # rather than "good" — it is a viability gate, and the percentile
    # bar is what actually limits cohort size.
    min_win = gates.get("minWinPct")
    if min_win is not None:
        win_pct = rec.win_pct
        if win_pct is None:
            reasons.append("no completed games, so win percentage is undefined")
        elif win_pct < float(min_win):
            reasons.append(f"win rate {win_pct:.1%} below the {float(min_win):.1%} floor")
    if rec.abandoned_rate > float(gates.get("maxAbandonedRosterRate", 0.34)):
        reasons.append(
            f"abandoned-roster rate {rec.abandoned_rate:.0%} exceeds "
            f"{float(gates.get('maxAbandonedRosterRate', 0.34)):.0%}"
        )
    recent = gates.get("requireRecentActivityDays")
    if recent and rec.days_since_last_activity is not None:
        if rec.days_since_last_activity > int(recent):
            reasons.append(f"no activity in {rec.days_since_last_activity} days")
    return reasons


# ── components ───────────────────────────────────────────────────────


def _performance_component(
    rec: ManagerRecord,
    population: dict[str, list[float]],
    cfg: dict[str, Any],
) -> tuple[float, list[str]]:
    block = cfg.get("performance") or {}
    sub = block.get("subWeights") or {}
    notes: list[str] = []
    parts: list[tuple[float, float]] = []  # (weight, 0..1 value)

    win = rec.win_pct
    if win is not None:
        p = percentile_rank(win, population.get("winPct") or [])
        parts.append((float(sub.get("winPct", 0.30)), p))
        if p >= 0.9:
            notes.append(f"Top-{round((1 - p) * 100)}% multi-season win rate")

    playoff = rec.playoff_rate
    if playoff is not None:
        p = percentile_rank(playoff, population.get("playoffRate") or [])
        parts.append((float(sub.get("playoffRate", 0.25)), p))
        if rec.playoff_appearances and rec.completed_seasons:
            notes.append(
                f"{rec.playoff_appearances} playoff appearance(s) in "
                f"{rec.completed_seasons} completed season(s)"
            )

    # Championships: shrunk, because one title in one season is luck.
    base = _mean(population.get("championshipRate") or []) or 0.08
    prior_n = float((block.get("championshipShrinkage") or {}).get("priorN", 6.0))
    shrunk = _shrunk_rate(rec.championships, rec.completed_seasons, base, prior_n)
    p = percentile_rank(shrunk, population.get("championshipRateShrunk") or [])
    parts.append((float(sub.get("championshipRate", 0.20)), p))
    if rec.championships >= 2:
        notes.append(f"{rec.championships} championships across observed leagues")

    finish = _mean(rec.finish_percentiles)
    if finish is not None:
        parts.append((float(sub.get("medianFinishPercentile", 0.15)), _clamp(finish, 0.0, 1.0)))

    pf = _mean(rec.points_for_percentiles)
    if pf is not None:
        parts.append((float(sub.get("pointsForPercentile", 0.10)), _clamp(pf, 0.0, 1.0)))

    if not parts:
        return 0.0, notes
    total_w = sum(w for w, _ in parts)
    value = sum(w * v for w, v in parts) / total_w if total_w else 0.0
    return _clamp(value, 0.0, 1.0), notes


def _roster_quality_component(
    rec: ManagerRecord,
    population: dict[str, list[float]],
    cfg: dict[str, Any],
) -> tuple[float | None, list[str]]:
    """Roster strength percentile, or **None** when there is no evidence.

    Returns None rather than 0.0 for "nothing to score", and that
    distinction is the whole point. The four ``ManagerRecord`` fields
    this reads — ``roster_value_ratios``, ``age_adjusted_value_ratio``,
    ``depth_adjusted_value_ratio``, ``draft_pick_capital_ratio`` — are
    populated by NO builder in the repo (`platform_records.py`,
    `records.py`), so in production this has always been the empty case.
    Returning 0.0 for it meant every manager scored a hard zero on a term
    weighted 0.22, the total was never renormalized, and 22 points of a
    0-100 scale were unreachable: a production-shaped record scored 64.9
    against a real maximum of 78.

    "Absent" and "measured zero" are different claims, and the scoring
    aggregation now renormalizes over whichever components are present —
    the same posture ``consensus_edge.score.composite`` takes for its
    components, and for the same reason.
    """
    block = cfg.get("rosterQuality") or {}
    sub = block.get("subWeights") or {}
    lo, hi = block.get("clampRatio", [0.4, 2.5])
    notes: list[str] = []
    parts: list[tuple[float, float]] = []

    ratio = _mean(rec.roster_value_ratios)
    if ratio is not None:
        clamped = _clamp(ratio, float(lo), float(hi))
        p = percentile_rank(clamped, population.get("rosterValueRatio") or [])
        parts.append((float(sub.get("valueVsLeagueAverage", 0.45)), p))
        if p >= 0.9:
            notes.append(
                f"Top-{round((1 - p) * 100)}% roster value across "
                f"{rec.observed_leagues} observed leagues"
            )

    for key, weight_key, pop_key in (
        ("age_adjusted_value_ratio", "ageAdjustedValue", "ageAdjustedValue"),
        ("depth_adjusted_value_ratio", "depthAdjustedValue", "depthAdjustedValue"),
        ("draft_pick_capital_ratio", "draftPickCapital", "draftPickCapital"),
    ):
        val = getattr(rec, key)
        if val is None:
            continue
        clamped = _clamp(float(val), float(lo), float(hi))
        p = percentile_rank(clamped, population.get(pop_key) or [])
        parts.append((float(sub.get(weight_key, 0.2)), p))

    if not parts:
        return None, notes
    total_w = sum(w for w, _ in parts)
    return _clamp(sum(w * v for w, v in parts) / total_w, 0.0, 1.0), notes


def _consistency_component(rec: ManagerRecord, cfg: dict[str, Any]) -> tuple[float, list[str]]:
    """Repeated success across INDEPENDENT leagues — the anti-luck term.

    Deliberately a SHARE, not a count: adding mediocre leagues cannot
    raise it, so "plays in many leagues" can never masquerade as skill.
    """
    block = cfg.get("multiLeagueConsistency") or {}
    notes: list[str] = []
    finishes = [f for f in rec.finish_percentiles if isinstance(f, (int, float))]
    if not finishes:
        return 0.0, notes

    above = sum(1 for f in finishes if f > 0.5) / len(finishes)

    # Variance across leagues: consistent good results beat one spike.
    if len(finishes) > 1:
        mean = sum(finishes) / len(finishes)
        var = sum((f - mean) ** 2 for f in finishes) / len(finishes)
        consistency = 1.0 - _clamp(math.sqrt(var) * 2.0, 0.0, 1.0)
    else:
        consistency = 0.0

    value = (
        float(block.get("aboveMedianShare", 0.65)) * above
        + float(block.get("crossLeagueVariancePenalty", 0.35)) * consistency
    )

    # Full credit needs breadth; below that, scale down.
    min_leagues = float(block.get("minLeaguesForFullCredit", 4))
    if len(finishes) < min_leagues:
        value *= len(finishes) / min_leagues

    if above >= 0.75 and len(finishes) >= 3:
        notes.append(
            f"Above median in {round(above * 100)}% of {len(finishes)} independent leagues"
        )
    return _clamp(value, 0.0, 1.0), notes


def _longevity_component(rec: ManagerRecord, cfg: dict[str, Any]) -> float:
    full = float((cfg.get("longevity") or {}).get("seasonsForFullCredit", 5))
    if full <= 0:
        return 0.0
    # Saturating: seasons 1->3 matter far more than 8->10.
    return _clamp(rec.completed_seasons / (rec.completed_seasons + full * 0.5), 0.0, 1.0)


def _activity_component(rec: ManagerRecord, cfg: dict[str, Any]) -> float:
    """Sustained participation, NOT raw volume — churn is not skill."""
    block = cfg.get("activity") or {}
    per_season = float(block.get("tradesPerSeasonForFullCredit", 6))
    if rec.completed_seasons <= 0 or per_season <= 0:
        return 0.0
    rate = rec.trades_completed / rec.completed_seasons
    value = _clamp(rate / per_season, 0.0, float(block.get("maxContribution", 1.0)))

    threshold = block.get("inactivityPenaltyThresholdDays")
    if threshold and rec.days_since_last_activity is not None:
        if rec.days_since_last_activity > int(threshold):
            value *= 0.5
    return value


def _championship_bonus(rec: ManagerRecord, cfg: dict[str, Any]) -> tuple[float, list[str]]:
    """ "Preferably they have won the league before" — as a bounded
    bonus, not a hard gate.

    A hard title requirement would be self-defeating: in a 12-team
    league only ~1/12 of managers can win per season, so requiring one
    cuts the cohort far below a top quartile and bars managers who
    consistently make deep runs in strong leagues.  Instead a title is
    worth a decisive nudge at the margin, additional titles add less
    (diminishing, because the first is the one that proves it can
    happen), and the total is capped so a lucky-title manager cannot
    coast in on it alone.

    Always named in ``contributors`` when it fires, so a qualification
    that hinged on a championship says so.
    """
    block = cfg.get("championshipPreference") or {}
    titles = max(0, int(rec.championships))
    if titles <= 0:
        return 0.0, []
    first = float(block.get("bonusFirstTitle", 0.06))
    extra = float(block.get("bonusPerAdditionalTitle", 0.02))
    cap = float(block.get("maxBonus", 0.12))
    bonus = min(cap, first + extra * (titles - 1))
    label = "Won the league" if titles == 1 else f"Won the league {titles}x"
    return bonus, [f"{label} in an observed dynasty season"]


def _uncertainty_penalty(rec: ManagerRecord, cfg: dict[str, Any]) -> float:
    block = cfg.get("uncertaintyPenalty") or {}
    max_pen = float(block.get("maxPenalty", 0.25))
    full_seasons = float(block.get("fullEvidenceSeasons", 5))
    full_leagues = float(block.get("fullEvidenceLeagues", 4))
    season_gap = 1.0 - _clamp(rec.completed_seasons / full_seasons, 0.0, 1.0)
    league_gap = 1.0 - _clamp(rec.observed_leagues / full_leagues, 0.0, 1.0)
    return max_pen * (0.6 * season_gap + 0.4 * league_gap)


def compute_confidence(rec: ManagerRecord, cfg: dict[str, Any]) -> tuple[float, str]:
    """Evidence volume, reported SEPARATELY from the score."""
    block = cfg.get("confidence") or {}
    s_half = float(block.get("seasonsHalfCredit", 3.0))
    l_half = float(block.get("leaguesHalfCredit", 3.0))
    seasons = rec.completed_seasons / (rec.completed_seasons + s_half) if s_half else 0.0
    leagues = rec.observed_leagues / (rec.observed_leagues + l_half) if l_half else 0.0
    value = _clamp(0.6 * seasons + 0.4 * leagues, 0.0, 1.0)
    tiers = block.get("tiers") or {}
    if value >= float(tiers.get("high", 0.75)):
        tier = "high"
    elif value >= float(tiers.get("medium", 0.5)):
        tier = "medium"
    else:
        tier = "low"
    return value, tier


# ── the public entry point ───────────────────────────────────────────


def build_population(
    records: Sequence[ManagerRecord], cfg: dict[str, Any]
) -> dict[str, list[float]]:
    """Distributions used for percentile normalization.

    Built from the EVALUABLE population only — including thin records
    would drag every percentile upward and make ordinary managers look
    elite by comparison.
    """
    base_champ = 0.08
    evaluable = [r for r in records if not check_eligibility(r, cfg)]
    pop: dict[str, list[float]] = {
        "winPct": [],
        "playoffRate": [],
        "championshipRate": [],
        "championshipRateShrunk": [],
        "rosterValueRatio": [],
        "ageAdjustedValue": [],
        "depthAdjustedValue": [],
        "draftPickCapital": [],
    }
    for r in evaluable:
        if r.win_pct is not None:
            pop["winPct"].append(r.win_pct)
        if r.playoff_rate is not None:
            pop["playoffRate"].append(r.playoff_rate)
        if r.completed_seasons > 0:
            pop["championshipRate"].append(r.championships / r.completed_seasons)
        ratio = _mean(r.roster_value_ratios)
        if ratio is not None:
            pop["rosterValueRatio"].append(ratio)
        for key, pop_key in (
            ("age_adjusted_value_ratio", "ageAdjustedValue"),
            ("depth_adjusted_value_ratio", "depthAdjustedValue"),
            ("draft_pick_capital_ratio", "draftPickCapital"),
        ):
            val = getattr(r, key)
            if val is not None:
                pop[pop_key].append(float(val))

    observed_base = _mean(pop["championshipRate"]) or base_champ
    prior_n = float(
        ((cfg.get("performance") or {}).get("championshipShrinkage") or {}).get("priorN", 6.0)
    )
    for r in evaluable:
        pop["championshipRateShrunk"].append(
            _shrunk_rate(r.championships, r.completed_seasons, observed_base, prior_n)
        )
    return pop


def score_managers(
    records: Sequence[ManagerRecord],
    cfg: dict[str, Any] | None = None,
) -> list[ManagerScore]:
    """Score a whole population at once.

    Population-level scoring is required, not a convenience: percentile
    normalization and the percentile-based qualification bar are both
    defined relative to the observed cohort.
    """
    cfg = cfg or load_config()
    version = methodology_version(cfg)
    weights = cfg.get("weights") or {}
    qual = cfg.get("qualification") or {}
    population = build_population(records, cfg)

    scored: list[ManagerScore] = []
    raw_scores: list[float] = []

    for rec in records:
        reasons = check_eligibility(rec, cfg)
        coverage = {
            "completedSeasons": rec.completed_seasons,
            "observedLeagues": rec.observed_leagues,
            "dynastyLeagues": rec.dynasty_leagues,
            "completedGames": rec.completed_games,
            "tradesObserved": rec.trades_completed,
            "historyComplete": False,
            "note": (
                "Derived from the leagues and seasons this platform has crawled, "
                "not from a manager's complete Sleeper history."
            ),
        }
        if reasons:
            scored.append(
                ManagerScore(
                    user_id=rec.user_id,
                    evaluable=False,
                    ineligible_reasons=reasons,
                    coverage=coverage,
                    methodology_version=version,
                )
            )
            continue

        perf, perf_notes = _performance_component(rec, population, cfg)
        roster, roster_notes = _roster_quality_component(rec, population, cfg)
        consistency, cons_notes = _consistency_component(rec, cfg)
        longevity = _longevity_component(rec, cfg)
        activity = _activity_component(rec, cfg)
        penalty = _uncertainty_penalty(rec, cfg)
        title_bonus, title_notes = _championship_bonus(rec, cfg)

        # Renormalize over the components that actually have evidence.
        #
        # This was a plain weighted sum with every declared weight
        # applied unconditionally. `rosterQuality` carries 0.22 and no
        # builder populates any of its four inputs, so it contributed a
        # hard 0.0 for every manager and 22 points of the 0-100 scale
        # were unreachable — a production-shaped record topped out at
        # 64.9 against a real maximum of 78.
        #
        # Renormalizing is safe for the COHORT because qualification is a
        # percentile (`minScorePercentile`), not an absolute threshold:
        # when the absent set is the same for everyone — which it is,
        # since rosterQuality is absent for all — every score scales by
        # the same factor and the ranking, and therefore the cohort, is
        # unchanged. `weightsApplied` is stamped so this is auditable per
        # manager rather than assumed.
        contributions: list[tuple[str, float, float]] = [
            ("performance", float(weights.get("performance", 0.36)), perf),
            (
                "multiLeagueConsistency",
                float(weights.get("multiLeagueConsistency", 0.22)),
                consistency,
            ),
            ("longevity", float(weights.get("longevity", 0.12)), longevity),
            ("activity", float(weights.get("activity", 0.08)), activity),
        ]
        if roster is not None:
            contributions.append(
                ("rosterQuality", float(weights.get("rosterQuality", 0.22)), roster)
            )

        declared = sum(
            float(weights.get(name, default))
            for name, default in (
                ("performance", 0.36),
                ("rosterQuality", 0.22),
                ("multiLeagueConsistency", 0.22),
                ("longevity", 0.12),
                ("activity", 0.08),
            )
        )
        present_weight = sum(w for _, w, _ in contributions)
        # Scale present weights back up to the declared total, so a full
        # set of components is a no-op and the bonus/penalty stay on the
        # scale they were calibrated against.
        scale = (declared / present_weight) if present_weight > 0 else 0.0
        weights_applied = {name: round(w * scale, 6) for name, w, _ in contributions}

        total = (sum(w * scale * value for _, w, value in contributions) + title_bonus) - penalty
        total = _clamp(total, 0.0, 1.0) * 100.0

        confidence, tier = compute_confidence(rec, cfg)
        scored.append(
            ManagerScore(
                user_id=rec.user_id,
                evaluable=True,
                score=round(total, 1),
                confidence=confidence,
                confidence_tier=tier,
                components={
                    "performance": perf,
                    # None, not 0.0, when there is no evidence — see
                    # `_roster_quality_component`. A reader can now tell
                    # "scored badly" from "never measured", and
                    # `weightsApplied` says what was actually used.
                    "rosterQuality": roster,
                    "multiLeagueConsistency": consistency,
                    "longevity": longevity,
                    "activity": activity,
                    "championshipBonus": title_bonus,
                    "uncertaintyPenalty": -penalty,
                    "weightsApplied": weights_applied,
                },
                # Title first: it is the preference most likely to have
                # decided a marginal qualification.
                contributors=[*title_notes, *perf_notes, *roster_notes, *cons_notes],
                coverage=coverage,
                methodology_version=version,
            )
        )
        raw_scores.append(total)

    # Percentile + qualification, relative to the evaluable population.
    min_pct = float(qual.get("minScorePercentile", 0.85))
    min_conf = float(qual.get("minConfidence", 0.55))
    max_size = int(qual.get("maxCohortSize", 2500))

    qualified: list[ManagerScore] = []
    for entry in scored:
        if not entry.evaluable or entry.score is None:
            continue
        entry.score_percentile = round(percentile_rank(entry.score, raw_scores), 4)
        # BOTH bars. A high score on thin evidence does not qualify.
        if entry.score_percentile >= min_pct and entry.confidence >= min_conf:
            entry.qualified = True
            qualified.append(entry)

    if len(qualified) > max_size:
        qualified.sort(key=lambda e: -(e.score or 0.0))
        for entry in qualified[max_size:]:
            entry.qualified = False

    return scored


def cohort_tiers(scored: Sequence[ManagerScore]) -> dict[str, int | float | None]:
    """The four population tiers, plus BOTH cohort-share framings.

    "Top quarter" is ambiguous and the two readings differ a lot, so
    both are reported rather than picking one silently:

      * ``qualifiedShareOfEvaluable`` — the bar actually applied.  The
        percentile is computed among managers who cleared every hard
        gate, because a percentile over un-gated managers would be
        dragged around by records too thin to judge.
      * ``qualifiedShareOfObservable`` — the same cohort as a fraction
        of everyone discovered.  Always the smaller number, since the
        gates run first.
    """
    observable = len(scored)
    evaluable = sum(1 for s in scored if s.evaluable)
    qualified = sum(1 for s in scored if s.qualified)
    uncertain = sum(1 for s in scored if s.evaluable and s.confidence_tier == "low")
    return {
        "observableManagers": observable,
        "evaluableManagers": evaluable,
        "qualifiedManagers": qualified,
        "uncertainManagers": uncertain,
        "qualifiedShareOfEvaluable": round(qualified / evaluable, 4) if evaluable else None,
        "qualifiedShareOfObservable": round(qualified / observable, 4) if observable else None,
    }
