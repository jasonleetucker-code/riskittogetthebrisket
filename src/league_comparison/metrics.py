"""Pure stat math for league comparison.

Every function here is deterministic and side-effect-free so the test
suite can exhaustively pin behaviour without standing up any I/O.

Two scoring methods are computed in parallel and reported side-by-side:

* **Legacy / Simple**:  ``(average + median) / 2``
  The user's original heuristic, preserved so they can sanity-check
  the new method against an established reference.

* **Improved**:  ``0.35*median + 0.25*avg + 0.20*p75 + 0.10*p25
                 + 0.10*replacement_adj``
  More robust than legacy: median anchors the central tendency,
  average captures the mean shift, p75 picks up elite-end skew, p25
  picks up replacement-end compression, and the replacement-adjusted
  value rewards positions whose starters are well-separated from the
  bottom of the startable pool.

Multi-season combination uses **equal weighting** by design (no recency
weighting).  Each available season counts as 1/N of the combined value,
where N is the number of available seasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median, quantiles
from typing import Iterable, Sequence

from .scoring_engine import PlayerSeasonScore
from src.ros import lineup as lineup_owner


# ── Constants ─────────────────────────────────────────────────────────

OFFENSE_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")
# Read from the canonical slot owner (C2-U1) rather than restated.
FLEX_POSITIONS: tuple[str, ...] = lineup_owner.ordered_positions(
    lineup_owner.slot_eligible_positions("FLEX")
)  # excludes QB

# Improved-method coefficients.  Documented in the user-facing
# methodology section so changes here flow into the UI explanation.
IMPROVED_WEIGHT_MEDIAN: float = 0.35
IMPROVED_WEIGHT_AVERAGE: float = 0.25
IMPROVED_WEIGHT_P75: float = 0.20
IMPROVED_WEIGHT_P25: float = 0.10
IMPROVED_WEIGHT_REPL_ADJ: float = 0.10


# ── Sampling ──────────────────────────────────────────────────────────
#
# Ranking is by ``blended_score`` (the volume+pace composite from
# :func:`src.league_comparison.scoring_engine.compute_blended_score`),
# not raw ``total_points``.  Players who missed weeks at an elite pace
# get partial credit; full-season starters score the same as before
# (blended == total when games_played == 17).


def top_n_by_position(
    scores: Iterable[PlayerSeasonScore],
    position: str,
    n: int,
) -> list[PlayerSeasonScore]:
    """Return the top-N season scores for ``position``, sorted DESC by
    blended score.

    Ties are broken by ``player_id`` for stable output across runs
    (so tests pin reliably).
    """
    pool = [s for s in scores if s.position == position]
    pool.sort(key=lambda s: (-s.blended_score, s.player_id))
    return pool[: max(0, int(n))]


def flex_top_n(
    scores: Iterable[PlayerSeasonScore],
    n: int = 96,
) -> list[PlayerSeasonScore]:
    """Top-N RB/WR/TE pool, QB excluded, ranked by blended score.

    Same tie-break and ranking signal as :func:`top_n_by_position`.
    """
    pool = [s for s in scores if s.position in FLEX_POSITIONS]
    pool.sort(key=lambda s: (-s.blended_score, s.player_id))
    return pool[: max(0, int(n))]


# ── Per-position metrics ──────────────────────────────────────────────


@dataclass(frozen=True)
class PositionMetrics:
    average: float
    median: float
    p25: float
    p75: float
    replacement_level: float  # the Nth player's points (e.g. QB24)
    elite: float  # mean of top 3
    replacement_adj: float  # average - replacement_level
    sample_size: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "average": round(self.average, 2),
            "median": round(self.median, 2),
            "p25": round(self.p25, 2),
            "p75": round(self.p75, 2),
            "replacementLevel": round(self.replacement_level, 2),
            "elite": round(self.elite, 2),
            "replacementAdj": round(self.replacement_adj, 2),
            "sampleSize": self.sample_size,
        }


_EMPTY_METRICS = PositionMetrics(
    average=0.0,
    median=0.0,
    p25=0.0,
    p75=0.0,
    replacement_level=0.0,
    elite=0.0,
    replacement_adj=0.0,
    sample_size=0,
)


def _percentile(sorted_desc: Sequence[float], pct: float) -> float:
    """Compute the ``pct`` percentile from a DESC-sorted list of floats.

    Uses Python's ``statistics.quantiles`` with method='exclusive' for
    n=100, indexed at ``pct - 1`` (0-based).  For tiny samples (<2) we
    return the single value or 0.
    """
    n = len(sorted_desc)
    if n == 0:
        return 0.0
    if n == 1:
        return float(sorted_desc[0])
    asc = sorted(sorted_desc)
    try:
        qs = quantiles(asc, n=100, method="exclusive")
    except Exception:  # noqa: BLE001
        return float(asc[int(round((pct / 100) * (n - 1)))])
    idx = int(round(pct)) - 1
    idx = max(0, min(idx, len(qs) - 1))
    return float(qs[idx])


def position_metrics(samples: Sequence[PlayerSeasonScore]) -> PositionMetrics:
    """Compute the per-position summary stats for a top-N sample.

    Operates on each player's ``blended_score`` (volume+pace composite)
    so a position whose elite tier missed games-but-played-fast is
    fairly represented.  Empty samples return zeroed metrics with
    ``sample_size=0`` rather than raising — the orchestrator surfaces
    that via warnings instead.
    """
    if not samples:
        return _EMPTY_METRICS
    pts = [float(s.blended_score) for s in samples]
    pts_desc = sorted(pts, reverse=True)
    avg = mean(pts)
    med = float(median(pts))
    p25 = _percentile(pts_desc, 25)
    p75 = _percentile(pts_desc, 75)
    repl = float(pts_desc[-1])  # the Nth (last in top-N == replacement-level)
    top3 = pts_desc[:3]
    elite = float(mean(top3)) if top3 else 0.0
    return PositionMetrics(
        average=float(avg),
        median=med,
        p25=p25,
        p75=p75,
        replacement_level=repl,
        elite=elite,
        replacement_adj=float(avg) - repl,
        sample_size=len(samples),
    )


# ── Blended scores (the two methods) ──────────────────────────────────


def legacy_blended(m: PositionMetrics) -> float:
    """The user's original ``(average + median) / 2`` formula."""
    return (m.average + m.median) / 2.0


def improved_blended(m: PositionMetrics) -> float:
    """Multi-signal weighted blend; coefficients defined as module
    constants and documented in the UI methodology section."""
    return (
        IMPROVED_WEIGHT_MEDIAN * m.median
        + IMPROVED_WEIGHT_AVERAGE * m.average
        + IMPROVED_WEIGHT_P75 * m.p75
        + IMPROVED_WEIGHT_P25 * m.p25
        + IMPROVED_WEIGHT_REPL_ADJ * m.replacement_adj
    )


# ── Positional shares ─────────────────────────────────────────────────


def position_shares(blended_by_pos: dict[str, float]) -> dict[str, float]:
    """Return each position's share of the total positional scoring pool.

    Empty / all-zero input returns 0 shares for everything (rather than
    NaN / division-by-zero).  Shares are returned as percentages
    (0..100), not 0..1.
    """
    total = sum(max(0.0, v) for v in blended_by_pos.values())
    if total <= 0:
        return {pos: 0.0 for pos in blended_by_pos}
    return {pos: (max(0.0, v) / total) * 100.0 for pos, v in blended_by_pos.items()}


# ── Multi-season combine (equal-weight) ───────────────────────────────


def combine_seasons_equal_weight(values: Sequence[float]) -> float:
    """Average a list of per-season values with equal weight per season.

    None values are dropped (used for "missing season" passthrough).
    Empty input returns 0.0 — caller is responsible for emitting a
    "no data" warning before calling.
    """
    finite = [float(v) for v in values if v is not None]
    if not finite:
        return 0.0
    return sum(finite) / len(finite)


def combine_metrics_equal_weight(
    metrics_by_season: dict[int, PositionMetrics | None],
) -> PositionMetrics:
    """Combine per-season metrics into one combined PositionMetrics.

    Each available season weighted equally; missing seasons skipped.
    Uses the average of the per-season computed values, NOT a re-pool
    of all top-N samples (that would over-weight high-volume seasons).
    """
    available = [m for m in metrics_by_season.values() if m and m.sample_size > 0]
    if not available:
        return _EMPTY_METRICS
    n = len(available)
    avg = sum(m.average for m in available) / n
    med = sum(m.median for m in available) / n
    p25 = sum(m.p25 for m in available) / n
    p75 = sum(m.p75 for m in available) / n
    repl = sum(m.replacement_level for m in available) / n
    elite = sum(m.elite for m in available) / n
    repl_adj = sum(m.replacement_adj for m in available) / n
    sample = int(round(sum(m.sample_size for m in available) / n))
    return PositionMetrics(
        average=avg,
        median=med,
        p25=p25,
        p75=p75,
        replacement_level=repl,
        elite=elite,
        replacement_adj=repl_adj,
        sample_size=sample,
    )


# ── Status labels ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class StatusBands:
    """Thresholds (in absolute pp difference) for status labels.

    These are deliberately tunable in one place so the frontend
    methodology section can reference the exact same numbers.
    """

    excellent: float = 0.5
    good: float = 1.5
    slight: float = 3.0
    over: float = 5.0  # above this -> "Too high/low"


_BANDS = StatusBands()


def status_label(diff_pp: float, *, bands: StatusBands = _BANDS) -> str:
    """Map a positional-share difference (in percentage points) to a
    status label.  Sign of ``diff_pp`` determines high vs low.
    """
    abs_d = abs(diff_pp)
    if abs_d <= bands.excellent:
        return "Excellent match"
    if abs_d <= bands.good:
        return "Good match"
    if abs_d <= bands.slight:
        return "Slightly high" if diff_pp > 0 else "Slightly low"
    if abs_d <= bands.over:
        # Mid-band noun stays "high/low"; severity escalates after ``over``.
        return "High" if diff_pp > 0 else "Low"
    return "Too high" if diff_pp > 0 else "Too low"


# ── Similarity score ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SimilarityResult:
    score: int  # 0..100
    label: str  # human descriptor
    distortion_label: str  # "Low" / "Moderate" / "High" / "Severe"
    total_share_dev_pp: float  # sum of |share diffs| in pp
    flex_dev_pct: float  # |my_flex - baseline_flex| / baseline_flex * 100


def similarity_score(
    my_shares: dict[str, float],
    baseline_shares: dict[str, float],
    my_flex: float,
    baseline_flex: float,
) -> SimilarityResult:
    """Convert positional-share differences + flex difference to a
    0..100 similarity score.

    Approach:

    1. Sum |my_share - baseline_share| in percentage points across the
       four offensive positions.  This is the "share deviation" signal
       — already a normalized number that doesn't depend on the
       absolute scale of fantasy points.
    2. Compute the flex-pool blended-score relative deviation as a
       percentage.
    3. Combined deviation = total_share_dev_pp + 0.4 * flex_dev_pct.
       The flex weighting is intentionally less than the share signal
       because the flex score is correlated with the per-position
       scores (it's not fully independent).
    4. Map combined deviation through a piecewise-linear curve to 0..100
       using the bands documented in the methodology section.

    Banding:

    | Combined deviation | Score range | Label                  |
    |--------------------|-------------|------------------------|
    | <= 2               | 95–100      | Extremely close        |
    | 2 – 5              | 85–94       | Very close             |
    | 5 – 10             | 75–84       | Some noticeable diffs  |
    | 10 – 20            | 60–74       | Meaningfully different |
    | > 20               | < 60        | Very distorted         |
    """
    pos_dev = sum(
        abs(my_shares.get(p, 0.0) - baseline_shares.get(p, 0.0)) for p in OFFENSE_POSITIONS
    )
    if baseline_flex > 0:
        flex_dev = abs(my_flex - baseline_flex) / baseline_flex * 100.0
    else:
        flex_dev = 0.0
    combined = pos_dev + 0.4 * flex_dev

    # Piecewise-linear: lower deviation -> higher score.
    if combined <= 2:
        score = 95 + (2 - combined) / 2 * 5  # 95..100
        label = "Extremely close to standard"
        distortion = "Low"
    elif combined <= 5:
        score = 85 + (5 - combined) / 3 * 9  # 85..94
        label = "Very close"
        distortion = "Low"
    elif combined <= 10:
        score = 75 + (10 - combined) / 5 * 9  # 75..84
        label = "Some noticeable differences"
        distortion = "Moderate"
    elif combined <= 20:
        score = 60 + (20 - combined) / 10 * 14  # 60..74
        label = "Meaningfully different"
        distortion = "High"
    else:
        # Below 60.  Floor at 0; decay rapidly past 20.
        score = max(0.0, 60 - (combined - 20) * 2)
        label = "Very distorted"
        distortion = "Severe"

    return SimilarityResult(
        score=int(round(max(0, min(100, score)))),
        label=label,
        distortion_label=distortion,
        total_share_dev_pp=round(pos_dev, 2),
        flex_dev_pct=round(flex_dev, 2),
    )


# ── Recommendations ───────────────────────────────────────────────────

# Heuristic culprit hints by position.  Plain English + rough cause —
# never prescriptive, never auto-applied.  The UI surfaces these
# verbatim under each position row.
_CULPRIT_HINTS: dict[str, list[str]] = {
    "QB": [
        "passing TD value (4-pt vs 6-pt swings QB share most)",
        "passing yard rate (e.g. 1/25 vs 1/40)",
        "interception penalty",
        "passing-yard threshold bonuses (300/400)",
        "rushing scoring (mobile QBs benefit)",
    ],
    "RB": [
        "PPR amount (full PPR pushes WR/TE up at RB's expense)",
        "rushing yard rate (e.g. 0.1 vs 0.05)",
        "rushing TD value",
        "rushing-yard threshold bonuses (100/200)",
        "first-down bonuses (if applied unequally)",
    ],
    "WR": [
        "PPR amount",
        "receiving yard rate",
        "100/200-yard receiving bonuses",
        "TE premium (a higher TEP eats into WR share)",
    ],
    "TE": [
        "TE premium (bonus_rec_te)",
        "PPR amount (TEs gain disproportionately at full PPR)",
        "receiving yard rate",
    ],
}


def recommendation(
    position: str,
    diff_pp: float,
    my_share: float,
    baseline_share: float,
) -> str:
    """Build a plain-English recommendation string.

    Always non-prescriptive — surfaces the gap and a list of likely
    scoring-setting culprits, never auto-changes anything.
    """
    direction = "higher" if diff_pp > 0 else "lower"
    abs_d = abs(diff_pp)
    if abs_d <= 0.5:
        return (
            f"{position} scoring is essentially aligned with the "
            f"baseline ({my_share:.1f}% vs {baseline_share:.1f}%). "
            f"No adjustment recommended."
        )
    severity = (
        "slightly"
        if abs_d <= 1.5
        else "noticeably"
        if abs_d <= 3.0
        else "meaningfully"
        if abs_d <= 5.0
        else "substantially"
    )
    hints = _CULPRIT_HINTS.get(position, [])
    hint_text = ""
    if hints and abs_d > 1.5:
        hint_text = " Likely scoring-setting drivers: " + "; ".join(hints[:3]) + "."
    return (
        f"{position} scoring is {severity} {direction} than the "
        f"baseline ({my_share:.1f}% vs {baseline_share:.1f}%, "
        f"{diff_pp:+.1f} pp).{hint_text}"
    )


# ── Convenience aggregator (used by service.py) ───────────────────────


@dataclass(frozen=True)
class PositionComparison:
    position: str
    my_metrics: PositionMetrics
    baseline_metrics: PositionMetrics
    my_legacy_score: float
    baseline_legacy_score: float
    my_improved_score: float
    baseline_improved_score: float

    def to_dict(
        self,
        my_share_legacy: float,
        my_share_improved: float,
        base_share_legacy: float,
        base_share_improved: float,
        recommendation_text: str,
    ) -> dict[str, object]:
        diff_legacy = my_share_legacy - base_share_legacy
        diff_improved = my_share_improved - base_share_improved
        rel = (diff_improved / base_share_improved * 100.0) if base_share_improved > 0 else 0.0
        return {
            "position": self.position,
            "my": {
                "metrics": self.my_metrics.to_dict(),
                "legacyScore": round(self.my_legacy_score, 2),
                "improvedScore": round(self.my_improved_score, 2),
                "shareLegacy": round(my_share_legacy, 2),
                "shareImproved": round(my_share_improved, 2),
            },
            "baseline": {
                "metrics": self.baseline_metrics.to_dict(),
                "legacyScore": round(self.baseline_legacy_score, 2),
                "improvedScore": round(self.baseline_improved_score, 2),
                "shareLegacy": round(base_share_legacy, 2),
                "shareImproved": round(base_share_improved, 2),
            },
            "diffPpLegacy": round(diff_legacy, 2),
            "diffPpImproved": round(diff_improved, 2),
            "relDiffPct": round(rel, 2),
            "status": status_label(diff_improved),
            "recommendation": recommendation_text,
        }
