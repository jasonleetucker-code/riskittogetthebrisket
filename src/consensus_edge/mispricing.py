"""How wrong is the market about this player, on a scale that compares?

A raw point difference cannot be ranked across a board.  "500 points
above market" is a rounding error on an elite quarterback near 9999 and a
doubling on a deep linebacker near 500.  Sorting a buy list by raw gap
therefore sorts it by player value, and the top of the list fills with
expensive players regardless of how mispriced they are.

Two transforms fix that, in order:

1. **Log ratio.**  ``log(fair / market)`` makes the gap multiplicative:
   +0.10 means "10% underpriced" whether the player is worth 9000 or 900.
   It is also symmetric, which a percentage is not — a 50% overprice and
   a 50% underprice are the same distance from fair in log space, but
   ``(f-m)/m`` scores them −0.33 and +0.50.

2. **Cohort-conditioned robust z-score.**  Even in log space, gaps are
   not identically distributed: deep IDP rows disagree more than top-24
   offense rows, because fewer sources cover them and the ones that do
   disagree more.  Scoring against the whole board would fill the buy
   list with deep IDPs whose gap is ordinary *for a deep IDP*.  So each
   gap is measured against the median and MAD of its own cohort
   (position family × value tier).

MAD, not standard deviation, because a handful of extreme gaps is
exactly what we are hunting and they would inflate an SD enough to hide
themselves.  The 1.4826 factor rescales MAD to be comparable to an SD
under normality.

Degenerate cohorts are refused rather than fudged: with too few members
or a zero MAD there is no dispersion to measure against, and returning
0.0 would read as "priced fairly" when the truth is "not measurable".
That distinction is the whole reason this module returns a reason string
alongside every ``None``.
"""

from __future__ import annotations

import math
import statistics
from typing import Any, Iterable, Sequence

# Guards the log against a zero/near-zero denominator.  Values live on a
# 1-9999 scale, so 1.0 is below the smallest real value and cannot
# meaningfully shift a ratio between two real numbers.
EPSILON = 1.0

# A cohort needs enough members for a median and a MAD to mean anything.
# Below this the dispersion estimate is noise and the z-score would be
# an artifact of which handful of players happened to be covered.
MIN_COHORT_SIZE = 12

# Scales MAD to an SD-equivalent under normality.
MAD_TO_SIGMA = 1.4826

# Where the z-score saturates.  Beyond 3 sigma we stop distinguishing
# degrees of extremity: the tail is populated by identity errors and
# stale rows as much as by genuine mispricing, and letting one row reach
# ±8 would let it dominate any ranking it appears in.
Z_CLIP = 3.0

# Value tiers, in canonical 0-9999 board units.  Boundaries are round
# numbers chosen to separate populations that genuinely disagree by
# different amounts, not fitted — they are a conditioning device, and a
# fitted boundary would need its own validation.
VALUE_TIER_EDGES: tuple[float, ...] = (1000.0, 3000.0, 6000.0)
VALUE_TIER_NAMES: tuple[str, ...] = ("deep", "mid", "high", "elite")

# Positions collapse to families for cohorting.  Keeping QB separate
# matters (superflex makes its distribution unlike any other offense
# position); the rest pool to keep cohorts above MIN_COHORT_SIZE.
_POSITION_FAMILY: dict[str, str] = {
    "QB": "QB",
    "RB": "RB_WR_TE",
    "WR": "RB_WR_TE",
    "TE": "RB_WR_TE",
    "DL": "IDP",
    "LB": "IDP",
    "DB": "IDP",
}

# Reasons a mispricing score cannot be produced.
UNSCORED_MISSING_INPUT = "missing_fair_or_market_value"
UNSCORED_NONPOSITIVE = "nonpositive_value"
UNSCORED_COHORT_TOO_SMALL = "cohort_below_minimum_size"
UNSCORED_NO_DISPERSION = "cohort_has_zero_dispersion"


def value_tier(value: float) -> str:
    """Name the value band ``value`` falls in."""
    for edge, name in zip(VALUE_TIER_EDGES, VALUE_TIER_NAMES):
        if value < edge:
            return name
    return VALUE_TIER_NAMES[-1]


def position_family(position: str | None) -> str:
    """Collapse a position to its cohorting family."""
    return _POSITION_FAMILY.get(str(position or "").upper(), "OTHER")


def cohort_key(position: str | None, market_value: float) -> str:
    """The comparison population for a row.

    Conditioned on the MARKET value, never the fair value: the cohort
    must not move when our own estimate moves, or a player would change
    peer group precisely because we decided he was mispriced — and the
    z-score would partly measure that reassignment.
    """
    return f"{position_family(position)}|{value_tier(market_value)}"


def cohort_chain(position: str | None, market_value: float) -> tuple[str, ...]:
    """Cohorts to try for a row, most specific first.

    Some genuinely important cells are small.  Measured 2026-08-04:
    ``QB|elite`` held 11 rows against a minimum of 12, so on a superflex
    board the most valuable assets in the league scored nothing at all —
    a coverage hole precisely where users care most.

    Falling back to the position family alone is a real loss of
    precision (it pools an elite QB's tight gap distribution with a deep
    QB's loose one), so it is a fallback and not the default, and the
    level actually used is stamped on the result as ``cohortLevel``.
    Refusing outright remains the last option: a coarse cohort is a
    weaker measurement, but no measurement is not a safer one — it is
    just a silent one.
    """
    return (cohort_key(position, market_value), position_family(position))


def log_gap(fair_value: float, market_value: float) -> float:
    """``log((fair + eps) / (market + eps))`` — symmetric, scale-free."""
    return math.log((fair_value + EPSILON) / (market_value + EPSILON))


def pct_gap(fair_value: float, market_value: float) -> float:
    """Plain percentage gap, for display only.

    Humans read "18% above market" far more readily than "log gap 0.166",
    so this is what the explanation text uses.  It is deliberately NOT
    the quantity that gets ranked.
    """
    return (fair_value - market_value) / market_value


def _robust_stats(values: Sequence[float]) -> tuple[float, float]:
    """Median and MAD-derived sigma of ``values``."""
    median = statistics.median(values)
    mad = statistics.median([abs(v - median) for v in values])
    return median, mad * MAD_TO_SIGMA


def build_cohorts(entries: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Compute per-cohort log-gap median and sigma.

    ``entries`` are fair-value index entries (see
    ``consensus_edge.fair_value.fair_value_index``).  Only rows with both
    a fair and a market value contribute — a row we could not price
    cannot inform the dispersion of rows we could.

    Returns ``{cohortKey: {"n", "median", "sigma", "usable", "reason"}}``.
    Unusable cohorts are RETAINED with a reason rather than dropped, so a
    caller can report why a player scored nothing instead of silently
    finding no cohort.
    """
    grouped: dict[str, list[float]] = {}
    for entry in entries:
        fair = entry.get("fairValue")
        market = entry.get("marketValue")
        if not isinstance(fair, (int, float)) or not isinstance(market, (int, float)):
            continue
        if fair <= 0 or market <= 0:
            continue
        gap = log_gap(float(fair), float(market))
        # A row contributes to every level of its own chain, so the
        # coarse fallback cohort is a real pooled population rather than
        # a second pass over a subset.
        for key in cohort_chain(entry.get("position"), float(market)):
            grouped.setdefault(key, []).append(gap)

    out: dict[str, dict[str, Any]] = {}
    for key, gaps in grouped.items():
        n = len(gaps)
        if n < MIN_COHORT_SIZE:
            out[key] = {
                "n": n,
                "median": None,
                "sigma": None,
                "usable": False,
                "reason": UNSCORED_COHORT_TOO_SMALL,
            }
            continue
        median, sigma = _robust_stats(gaps)
        if sigma <= 0:
            out[key] = {
                "n": n,
                "median": median,
                "sigma": 0.0,
                "usable": False,
                "reason": UNSCORED_NO_DISPERSION,
            }
            continue
        out[key] = {
            "n": n,
            "median": median,
            "sigma": sigma,
            "usable": True,
            "reason": None,
        }
    return out


def score_entry(
    entry: dict[str, Any],
    cohorts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Score one row's mispricing against its cohort.

    Returns a dict carrying the component score in ``[-1, 1]`` plus every
    intermediate a reader might want to check: the raw values, the
    percentage gap for prose, the log gap, the z-score, and the cohort it
    was judged against.  ``score`` is None whenever the row could not be
    scored, always alongside a ``reason``.

    Sign convention: **positive means underpriced** — our fair value is
    above the market, so the player is a buy.  This matches the
    Consensus Edge score's own convention (+100 = strongest buy) so no
    call site has to remember to flip it.
    """
    result: dict[str, Any] = {
        "score": None,
        "reason": None,
        "fairValue": entry.get("fairValue"),
        "marketValue": entry.get("marketValue"),
        "pctGap": None,
        "logGap": None,
        "z": None,
        "cohort": None,
        "cohortN": None,
        # "specific" (position × value tier) or "family" (pooled
        # fallback).  Exposed so a reader can discount a score that was
        # measured against a coarser peer group.
        "cohortLevel": None,
    }

    fair = entry.get("fairValue")
    market = entry.get("marketValue")
    if not isinstance(fair, (int, float)) or not isinstance(market, (int, float)):
        result["reason"] = UNSCORED_MISSING_INPUT
        return result
    if fair <= 0 or market <= 0:
        result["reason"] = UNSCORED_NONPOSITIVE
        return result

    fair_f, market_f = float(fair), float(market)
    result["pctGap"] = pct_gap(fair_f, market_f)
    result["logGap"] = log_gap(fair_f, market_f)

    chain = cohort_chain(entry.get("position"), market_f)
    result["cohort"] = chain[0]

    stats = None
    level = None
    last_reason = UNSCORED_COHORT_TOO_SMALL
    for candidate, candidate_level in zip(chain, ("specific", "family")):
        found = cohorts.get(candidate)
        if found is None:
            continue
        if found.get("usable"):
            stats, level = found, candidate_level
            result["cohort"] = candidate
            break
        last_reason = found.get("reason") or last_reason

    if stats is None:
        result["reason"] = last_reason
        return result

    result["cohortN"] = stats.get("n")
    result["cohortLevel"] = level

    z = (result["logGap"] - stats["median"]) / stats["sigma"]
    z = max(-Z_CLIP, min(Z_CLIP, z))
    result["z"] = z
    result["score"] = z / Z_CLIP
    return result


def score_index(index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Score an entire fair-value index. ``{playerKey: scoreEntry}``."""
    cohorts = build_cohorts(index.values())
    return {key: score_entry(entry, cohorts) for key, entry in index.items()}
