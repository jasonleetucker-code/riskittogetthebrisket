#!/usr/bin/env python3
"""Calibrate the KTC-style Value Adjustment formula against all observed
KTC data points.

13 data points across 4 topologies (1-vs-2, 1-vs-3, 2-vs-3, 3-vs-5)
collected from the KTC trade calculator (Superflex, TEP=1).  The
original 3-point calibration from PR #82 fit a simple
top-gap-scarcity + exponential-decay formula; adding 10 more points
revealed the formula structurally under-predicts whenever (a) the
"extra" piece is a low-value throw-in or (b) many nearly-equal
pieces are being consolidated (3-vs-5 case).

This script:
    * Declares every data point as (small, large, observed_va).
    * Defines several candidate formula families.
    * Runs a brute-force grid search over the free parameters of each.
    * Reports per-case errors + aggregate statistics (mean, max, RMS).

Run: ``python3 scripts/calibrate_va_formula.py``

The frontend keeps its formula in ``frontend/lib/trade-logic.js``.  When
a winning candidate is found, port its predict() body over there and
update the pinned regression tests in
``frontend/__tests__/trade-logic.test.js``.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OBSERVATIONS = REPO_ROOT / "scripts" / "ktc_va_observations.json"
DEFAULT_FIXTURE = REPO_ROOT / "scripts" / "ktc_va_fixture.json"


@dataclass(frozen=True)
class DataPoint:
    """Observed KTC Value Adjustment.

    ``small`` is the side with fewer pieces — the side that receives
    the VA.  ``large`` has more pieces.  Both are raw value lists in
    KTC's 1-9999 display scale.
    """
    label: str
    small: tuple[float, ...]
    large: tuple[float, ...]
    ktc_va: float
    topology: str = ""

    def sorted_small(self) -> list[float]:
        return sorted(self.small, reverse=True)

    def sorted_large(self) -> list[float]:
        return sorted(self.large, reverse=True)

    def top_gap(self) -> float:
        s = self.sorted_small()
        L = self.sorted_large()
        if not s or not L:
            return 0.0
        return max(0.0, (s[0] - L[0]) / s[0])

    def extras(self) -> list[float]:
        """Multi-side pieces beyond what the small side can pair with."""
        return self.sorted_large()[len(self.small):]

    def small_top(self) -> float:
        return self.sorted_small()[0] if self.small else 0.0


def _load_fixture_labels(fixture_path: Path) -> set[str] | None:
    """Return the set of labels currently in the fixture, or None when
    the fixture is missing or unreadable (in which case we skip the
    orphan-filter step rather than fail).  The fixture itself is
    committed and should always be present in normal usage; this is
    purely defensive."""
    if not fixture_path.exists():
        return None
    try:
        with fixture_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception:
        return None
    if not isinstance(entries, list):
        return None
    labels: set[str] = set()
    for e in entries:
        if isinstance(e, dict) and isinstance(e.get("label"), str):
            labels.add(e["label"])
    return labels or None


def load_observations(
    path: Path = DEFAULT_OBSERVATIONS,
    fixture_path: Path = DEFAULT_FIXTURE,
) -> list[DataPoint]:
    """Load observations from ``scripts/ktc_va_observations.json``.

    Each observation is converted to a DataPoint.  The ``small`` side is
    the one with fewer pieces (unequal) or higher top asset (equal) —
    matching the convention the frontend uses.  Observations without a
    reportable VA (``valueAdjustmentTeam1 == 0`` AND
    ``valueAdjustmentTeam2 == 0``) are still loaded with ktc_va=0 so
    the fit can honor the "no adjustment" signal.

    Observations whose label is no longer present in the current fixture
    are silently skipped (with a warning printed so the orphan count is
    visible).  This prevents stale carryover when the fixture is
    renamed or trimmed: ``collect_ktc_va.py`` doesn't prune stale
    captures from the JSON, so without this filter a renamed fixture
    would mix old + new datasets and quietly bias the fit toward
    whichever local capture history a developer happens to have.
    """
    # "File doesn't exist" is a legitimate state (no observations
    # captured yet); fall through quietly and let main() print a
    # baseline-only message.  Anything else — bad JSON, wrong shape,
    # IO error — is a real failure that would silently mask stale or
    # corrupt data and produce a misleading calibration if swallowed,
    # so we let it propagate.
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    observations = payload.get("observations") if isinstance(payload, dict) else payload
    if not isinstance(observations, list):
        raise ValueError(
            f"{path}: expected an 'observations' list (or top-level array); "
            f"got {type(observations).__name__}"
        )
    points: list[DataPoint] = []
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        team1 = [v for v in (obs.get("team1Values") or []) if v]
        team2 = [v for v in (obs.get("team2Values") or []) if v]
        va1 = obs.get("valueAdjustmentTeam1", 0) or 0
        va2 = obs.get("valueAdjustmentTeam2", 0) or 0
        label = obs.get("label") or "?"
        topo = obs.get("topology") or f"{len(team1)}v{len(team2)}"
        if not team1 or not team2:
            continue

        # Pick which side is "small" (VA recipient).
        #   - Unequal counts: smaller-count side.
        #   - Equal counts: side reporting VA > 0, else side with
        #     higher top asset (default to team1 if tied).
        if len(team1) != len(team2):
            small_is_team1 = len(team1) < len(team2)
        else:
            if va1 > 0 and va2 == 0:
                small_is_team1 = True
            elif va2 > 0 and va1 == 0:
                small_is_team1 = False
            else:
                small_is_team1 = max(team1) >= max(team2)

        small = tuple(sorted(team1 if small_is_team1 else team2, reverse=True))
        large = tuple(sorted(team2 if small_is_team1 else team1, reverse=True))
        ktc_va = va1 if small_is_team1 else va2
        points.append(DataPoint(label, small, large, float(ktc_va), topo))

    fixture_labels = _load_fixture_labels(fixture_path)
    if fixture_labels is not None:
        kept = [p for p in points if p.label in fixture_labels]
        orphans = [p.label for p in points if p.label not in fixture_labels]
        if orphans:
            preview = ", ".join(orphans[:5])
            suffix = f", … (+{len(orphans) - 5} more)" if len(orphans) > 5 else ""
            print(
                f"WARNING: {len(orphans)} observation(s) have labels not in "
                f"current fixture {fixture_path.name}; skipping: {preview}{suffix}"
            )
        return kept
    return points


DATA: list[DataPoint] = [
    DataPoint("A", (9999,), (7846, 5717), 3712, "1v2"),
    DataPoint("B", (7846,), (5717, 4829), 3034, "1v2"),
    DataPoint("C", (7846,), (6949, 5717), 1166, "1v2"),
    DataPoint("D", (4342,), (2667, 2324, 1172), 1820, "1v3"),
    DataPoint("E", (7798,), (4519, 4208, 2906), 3834, "1v3"),
    DataPoint("F", (9999,), (7471, 4862, 2215), 4879, "1v3"),
    DataPoint("G", (7795,), (6883, 2950), 2077, "1v2"),
    DataPoint("H", (7795,), (5086, 4021, 2950), 3587, "1v3"),
    DataPoint("I", (9999,), (7813, 5086), 4103, "1v2"),
    DataPoint("J", (9999,), (7813, 3811, 2756), 4848, "1v3"),
    DataPoint("K", (7509,), (6737, 2179), 1887, "1v2"),
    DataPoint("L", (9999, 9983, 5086), (9603, 7687, 7298, 4206, 2670), 4586, "3v5"),
    DataPoint("M", (7795, 1914), (5086, 4021, 3943), 3371, "2v3"),
]


# ── Formula candidates ──────────────────────────────────────────────────
#
# Each predict function returns the predicted VA for one DataPoint
# given a params dict.  Signatures must match so the grid-search loop
# can iterate uniformly.

def predict_v1_current(pt: DataPoint, p: dict) -> float:
    """V1 (current production): top-gap scarcity * exponential-decay extras."""
    top_gap = pt.top_gap()
    raw = p["slope"] * top_gap - p["intercept"]
    scarcity = max(0.0, min(p["cap"], raw))
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        total += extra * scarcity * (p["decay"] ** i)
    return total


def predict_v2_per_extra(pt: DataPoint, p: dict) -> float:
    """V2: per-extra scarcity based on each extra's own gap ratio.

    Each extra gets a scarcity from ``(single - extra) / single`` — a
    bigger gap means more consolidation premium on that piece.  No
    decay; each piece's contribution is fully independent.
    """
    small_top = pt.small_top()
    total = 0.0
    for extra in pt.extras():
        gap = max(0.0, (small_top - extra) / small_top) if small_top else 0.0
        scarcity = max(0.0, min(p["cap"], p["slope"] * gap - p["intercept"]))
        total += extra * scarcity
    return total


def predict_v3_hybrid(pt: DataPoint, p: dict) -> float:
    """V3: top-gap scarcity modulated per-extra by extras-ratio.

    Idea: the top-gap scarcity sets a ceiling, but each extra's
    effective weight scales up (toward 1.0) as the extra becomes more
    "filler" (smaller relative to the single).

        effective_i = top_scarcity + boost * max(0, extra_gap_i - top_gap)

    where ``extra_gap_i = (small_top - extra_i) / small_top``.  This
    reduces to V1 when all extras are near the top-large value.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    top_scarcity = max(0.0, min(p["cap"], p["slope"] * top_gap - p["intercept"]))
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        if small_top > 0:
            extra_gap = max(0.0, (small_top - extra) / small_top)
        else:
            extra_gap = 0.0
        effective = top_scarcity + p["boost"] * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(p["effective_cap"], effective))
        total += extra * effective * (p["decay"] ** i)
    return total


def predict_v4_additive(pt: DataPoint, p: dict) -> float:
    """V4: additive model — base floor + top_gap term + (1 - extras_ratio) term.

    For each extra, effective weight is::

        w_i = floor + alpha * top_gap + beta * (1 - extra_i / small_top)

    Clamped to [0, cap].  Captures the insight that smaller extras
    carry a HIGHER consolidation premium (lower extras_ratio → higher
    w_i from the beta term), while still responding to top-gap for
    overall magnitude.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        ratio = (extra / small_top) if small_top else 1.0
        w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
        w = max(0.0, min(p["cap"], w))
        total += extra * w * (p["decay"] ** i)
    return total


def predict_v5_additive_with_roster(pt: DataPoint, p: dict) -> float:
    """V5: V4 + a roster-slot baseline that doesn't vanish at top_gap=0.

    Same as V4 but the floor is a flat addition that survives even
    when top_gap and extras_ratio both push the weight down.  Designed
    to salvage case L (3v5 with near-equal tops, all pieces bulky).
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        ratio = (extra / small_top) if small_top else 1.0
        # Additive terms.
        w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
        w = max(p["min_weight"], min(p["cap"], w))
        total += extra * w * (p["decay"] ** i)
    return total


def predict_v6_equal_count(pt: DataPoint, p: dict) -> float:
    """V6: V3_hybrid + explicit equal-count branch.

    When small.length < large.length, identical to V3_hybrid (the
    current production formula).  When small.length == large.length,
    the extras loop has nothing to iterate, so we apply a single
    elite-premium term: ``top_small · top_scarcity · equal_factor``.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    top_scarcity = max(0.0, min(p["cap"], p["slope"] * top_gap - p["intercept"]))
    sorted_small = pt.sorted_small()
    sorted_large = pt.sorted_large()
    if len(sorted_small) == len(sorted_large):
        return small_top * top_scarcity * p["equal_factor"]
    if len(sorted_small) > len(sorted_large):
        return 0.0
    total = 0.0
    for i, extra in enumerate(pt.extras()):
        extra_gap = max(0.0, (small_top - extra) / small_top) if small_top else 0.0
        effective = top_scarcity + p["boost"] * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(p["effective_cap"], effective))
        total += extra * effective * (p["decay"] ** i)
    return total


def predict_v7_full_loop(pt: DataPoint, p: dict) -> float:
    """V7: loop over every piece of the large side with positional decay.

    V3_hybrid only iterates extras beyond the matched pair; V7 treats
    all large-side pieces as contributing to the VA, which makes the
    formula graceful at equal counts (no separate branch).  The first
    matched piece is at p=0 with full weight; deeper pieces decay.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    top_scarcity = max(0.0, min(p["cap"], p["slope"] * top_gap - p["intercept"]))
    sorted_small = pt.sorted_small()
    sorted_large = pt.sorted_large()
    if len(sorted_small) > len(sorted_large):
        return 0.0
    total = 0.0
    for i, piece in enumerate(sorted_large):
        extra_gap = max(0.0, (small_top - piece) / small_top) if small_top else 0.0
        effective = top_scarcity + p["boost"] * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(p["effective_cap"], effective))
        total += piece * effective * (p["decay"] ** i)
    return total


def predict_v8_stud_factor(pt: DataPoint, p: dict) -> float:
    """V8: V7 full-loop + an explicit ``stud factor`` magnitude term.

    Motivation — KTC's own FAQ for Value Adjustment names ``"stud
    factor"`` as a distinct input alongside value-difference and
    lesser-piece-count.  V7's per-piece weight is purely ratio-based
    (``top_gap`` is a percentage), so a 9000-vs-5000 trade and a
    4500-vs-2500 trade get identical per-piece weights even though
    the first one involves a true stud.  V8 amplifies the per-piece
    weight when the small side's top piece is elite in absolute
    terms::

        stud_excess = max(0, top_small - stud_threshold) / 10000
        stud_mult   = 1 + stud_coeff · stud_excess

    When ``stud_coeff = 0`` V8 collapses to V7 exactly — so the grid
    search will tell us if the stud factor adds real signal or is
    just absorbed by the existing terms.  Threshold defaults to
    7000 (loosely "top-50 dynasty value" on the 0-9999 canonical
    scale) but is also a grid-searched parameter.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    top_scarcity = max(0.0, min(p["cap"], p["slope"] * top_gap - p["intercept"]))
    sorted_small = pt.sorted_small()
    sorted_large = pt.sorted_large()
    if len(sorted_small) > len(sorted_large):
        return 0.0

    stud_threshold = p.get("stud_threshold", 7000.0)
    stud_excess = max(0.0, small_top - stud_threshold) / 10000.0
    stud_mult = 1.0 + p["stud_coeff"] * stud_excess

    total = 0.0
    for i, piece in enumerate(sorted_large):
        extra_gap = max(0.0, (small_top - piece) / small_top) if small_top else 0.0
        effective = top_scarcity + p["boost"] * max(0.0, extra_gap - top_gap)
        effective = max(0.0, min(p["effective_cap"], effective))
        total += piece * effective * (p["decay"] ** i) * stud_mult
    return total


def predict_v9_split(pt: DataPoint, p: dict) -> float:
    """V9: split formula — V4-style additive for unequal counts,
    a separate ``small_top * top_gap * stud_coeff + offset`` branch
    for equal-count trades.

    The V1-V8 family all share one structural problem: they treat
    "equal piece counts" as either "no extras → predict 0" (V1-V5)
    or "iterate over the whole large side, including matched pieces"
    (V6-V8).  Neither matches KTC's actual behavior.  KTC's VA on
    equal-count trades:

      * Fires on stud-vs-pile shapes (e.g. Chase + throw-in vs two
        mids → VA ~4000)
      * Goes silent when the trade is too lopsided for VA to salvage
        (huge value gap → VA = 0)
      * Caps in magnitude (5v5 equal almost always silent)

    V9 separates the unequal-count and equal-count branches and lets
    the grid search learn each independently.  The unequal branch is
    V4 (the best of the original family at handling unequal counts).
    The equal branch is a deliberately small parameterization::

        eq_va = max(0, eq_offset
                       + eq_top_coeff   * small_top * top_gap
                       + eq_count_coeff * count_size)

    where ``count_size = len(small) = len(large)``.  ``eq_count_coeff``
    can go negative to suppress the term at deep counts (the 4v4/5v5
    suppression KTC seems to apply).

    When all equal-count params are 0, V9 collapses to V4.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    extras = pt.extras()

    if extras:
        # Unequal-count: V4 additive formula
        total = 0.0
        for i, extra in enumerate(extras):
            ratio = (extra / small_top) if small_top else 1.0
            w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
            w = max(0.0, min(p["cap"], w))
            total += extra * w * (p["decay"] ** i)
        return total

    # Equal-count branch
    if not pt.small or not pt.large:
        return 0.0
    count_size = len(pt.small)
    eq_va = (
        p["eq_offset"]
        + p["eq_top_coeff"] * small_top * top_gap
        + p["eq_count_coeff"] * count_size
    )
    return max(0.0, eq_va)


def predict_v10_classifier(pt: DataPoint, p: dict) -> float:
    """V10: V9 + a two-gate classifier on the equal-count branch.

    The V9 grid rejected a simple linear equal-count term because
    KTC's behavior is bimodal: VA = 0 in some equal-count shapes and
    nonzero in others.  V10 adds two interpretable gates that turn
    the linear term off when KTC clearly reports zero:

      Gate 1 — ``min_top_gap``:  Skip when ``small_top - large_top``
        is a tiny percentage.  Captures shapes like EQ_3v3_g where
        the "stud advantage" is only ~5% — KTC reports VA=0.

      Gate 2 — ``dom_count_thresh``:  Skip when ``small`` dominates
        ``large`` piece-by-piece (after sorting both desc) AND the
        roster count is at or above the threshold.  Captures shapes
        like EQ_3v3_a / EQ_4v4_a / EQ_5v5_a where every small piece
        outranks the matched large piece — KTC declines to fire VA
        on totally lopsided trades, especially at deep roster counts.

    When BOTH gates pass, V10 falls back to V9's linear term::

        eq_va = max(0, eq_offset + eq_top_coeff * small_top * top_gap
                                 + eq_count_coeff * count)

    Unequal-count branch is unchanged from V4.
    """
    small_top = pt.small_top()
    top_gap = pt.top_gap()
    extras = pt.extras()

    if extras:
        # Unequal-count branch (V4)
        total = 0.0
        for i, extra in enumerate(extras):
            ratio = (extra / small_top) if small_top else 1.0
            w = p["floor"] + p["alpha"] * top_gap + p["beta"] * max(0.0, 1 - ratio)
            w = max(0.0, min(p["cap"], w))
            total += extra * w * (p["decay"] ** i)
        return total

    # Equal-count branch
    if not pt.small or not pt.large:
        return 0.0
    sm = pt.sorted_small()
    lg = pt.sorted_large()
    count_size = len(sm)

    # Gate 1: top must be meaningfully bigger.
    if top_gap < p["min_top_gap"]:
        return 0.0

    # Gate 2: full piece-dominance + deep count → KTC silences VA.
    fully_dominates = all(sm[i] > lg[i] for i in range(count_size))
    if fully_dominates and count_size >= p["dom_count_thresh"]:
        return 0.0

    eq_va = (
        p["eq_offset"]
        + p["eq_top_coeff"] * small_top * top_gap
        + p["eq_count_coeff"] * count_size
    )
    return max(0.0, eq_va)


# ── Scoring + grid search ───────────────────────────────────────────────

# Floor for the relative-error divisor.  Dividing by pt.ktc_va is
# ideal when KTC reports a nonzero VA (gives a true percentage), but
# breaks on observations where KTC reports 0 — those are meaningful
# calibration signal ("formula should predict near-0 here") rather
# than noise, so skipping them is wrong.  Using max(|target|, floor)
# scales all errors to a common magnitude: zero-target points still
# penalize nonzero predictions proportionally, and nonzero-target
# points behave identically to the original pure-relative metric as
# long as |target| ≥ floor (which is true for every one of the 13
# baseline anchors — smallest is 1166).
_ERROR_FLOOR = 500.0


def errors(predict_fn, params: dict) -> list[tuple[str, float, float, float, str]]:
    rows = []
    for pt in DATA:
        pred = predict_fn(pt, params)
        denom = max(abs(pt.ktc_va), _ERROR_FLOOR)
        err = (pred - pt.ktc_va) / denom
        rows.append((pt.label, pred, pt.ktc_va, err, pt.topology))
    return rows


def objective(predict_fn, params: dict, metric: str = "rms") -> float:
    errs = [abs(r[3]) for r in errors(predict_fn, params)]
    if metric == "mean":
        return sum(errs) / len(errs)
    if metric == "rms":
        return (sum(e * e for e in errs) / len(errs)) ** 0.5
    if metric == "max":
        return max(errs)
    if metric == "blend":  # mean + worst/4
        return sum(errs) / len(errs) + max(errs) / 4
    raise ValueError(metric)


def report(predict_fn, params: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"  params: {params}")
    rows = errors(predict_fn, params)
    print(f"  {'case':<4} {'topo':>5} {'pred':>6} {'ktc':>6} {'err%':>8}")
    for label, pred, ktc, err, topo in rows:
        print(f"  {label:<4} {topo:>5} {pred:>6.0f} {ktc:>6.0f} {err*100:>+7.2f}%")
    abs_errs = [abs(r[3]) for r in rows]
    mean = sum(abs_errs) / len(abs_errs) * 100
    mx = max(abs_errs) * 100
    rms = ((sum(e * e for e in abs_errs) / len(abs_errs)) ** 0.5) * 100
    over_10 = sum(1 for e in abs_errs if e > 0.10)
    over_20 = sum(1 for e in abs_errs if e > 0.20)
    print(f"  mean |err|={mean:5.2f}%  max={mx:5.2f}%  rms={rms:5.2f}%  "
          f"(>10%: {over_10}, >20%: {over_20})")


def grid_search(predict_fn, param_grid: dict[str, list], metric: str = "rms") -> dict:
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    best = None
    count = 0
    for combo in itertools.product(*values):
        params = dict(zip(keys, combo))
        loss = objective(predict_fn, params, metric=metric)
        count += 1
        if best is None or loss < best["loss"]:
            best = {"loss": loss, "params": params}
    return best


def _linspace(lo, hi, n):
    if n == 1:
        return [lo]
    return [lo + (hi - lo) / (n - 1) * i for i in range(n)]


# ── Main ────────────────────────────────────────────────────────────────
def main() -> None:
    # Extend DATA with any observations collected via
    # ``scripts/collect_ktc_va.py``.  The baseline 13 anchors stay
    # in-source so the calibration always pins against the same
    # reference set.
    extra_points = load_observations()
    if extra_points:
        print(f"Loaded {len(extra_points)} observations from {DEFAULT_OBSERVATIONS}")
        DATA.extend(extra_points)
    else:
        print(
            f"No observations file at {DEFAULT_OBSERVATIONS} — calibrating "
            f"against the {len(DATA)} in-source anchors only."
        )

    # V1 — CURRENT PRODUCTION FORMULA.
    v1_prod = {"slope": 4.27, "intercept": 0.288, "cap": 0.64, "decay": 0.70}
    report(predict_v1_current, v1_prod, "V1 (current production)")

    # V1 best refit — establish baseline for what the current formula
    # family can achieve against all 13 points.
    print("\n--- V1 grid refit ---")
    v1_best = grid_search(
        predict_v1_current,
        {
            "slope": _linspace(3.0, 6.0, 16),
            "intercept": _linspace(0.10, 0.50, 9),
            "cap": _linspace(0.45, 0.85, 9),
            "decay": _linspace(0.40, 0.95, 12),
        },
        metric="rms",
    )
    report(predict_v1_current, v1_best["params"], "V1 best refit (RMS)")

    # V2 — per-extra scarcity.
    print("\n--- V2 grid refit ---")
    v2_best = grid_search(
        predict_v2_per_extra,
        {
            "slope": _linspace(0.3, 1.6, 14),
            "intercept": _linspace(-0.3, 0.3, 13),
            "cap": _linspace(0.30, 0.90, 13),
        },
        metric="rms",
    )
    report(predict_v2_per_extra, v2_best["params"], "V2 per-extra scarcity (RMS)")

    # V3 — hybrid with boost on sub-top extras.
    print("\n--- V3 grid refit ---")
    v3_best = grid_search(
        predict_v3_hybrid,
        {
            "slope": _linspace(3.0, 6.0, 7),
            "intercept": _linspace(0.10, 0.45, 8),
            "cap": _linspace(0.45, 0.80, 8),
            "decay": _linspace(0.45, 0.95, 6),
            "boost": _linspace(0.0, 2.0, 11),
            "effective_cap": _linspace(0.50, 1.20, 8),
        },
        metric="rms",
    )
    report(predict_v3_hybrid, v3_best["params"], "V3 hybrid (RMS)")

    # V4 — additive model (floor + alpha*top_gap + beta*(1-ratio)).
    print("\n--- V4 grid refit ---")
    v4_best = grid_search(
        predict_v4_additive,
        {
            "floor": _linspace(-0.3, 0.4, 15),
            "alpha": _linspace(-0.5, 2.0, 11),
            "beta": _linspace(0.0, 2.0, 11),
            "cap": _linspace(0.50, 1.20, 8),
            "decay": _linspace(0.5, 1.0, 6),
        },
        metric="rms",
    )
    report(predict_v4_additive, v4_best["params"], "V4 additive (RMS)")

    # V5 — V4 with flat minimum weight (to rescue case L).
    print("\n--- V5 grid refit ---")
    v5_best = grid_search(
        predict_v5_additive_with_roster,
        {
            "floor": _linspace(-0.3, 0.4, 8),
            "alpha": _linspace(-0.5, 2.0, 6),
            "beta": _linspace(0.0, 2.0, 6),
            "cap": _linspace(0.6, 1.1, 6),
            "decay": _linspace(0.5, 1.0, 6),
            "min_weight": _linspace(0.0, 0.3, 7),
        },
        metric="rms",
    )
    report(predict_v5_additive_with_roster, v5_best["params"], "V5 additive + roster floor (RMS)")

    # V6 — V3 with equal-count elite-premium branch.
    print("\n--- V6 grid refit ---")
    v6_best = grid_search(
        predict_v6_equal_count,
        {
            "slope": _linspace(3.0, 6.0, 7),
            "intercept": _linspace(0.10, 0.50, 5),
            "cap": _linspace(0.45, 1.10, 10),
            "decay": _linspace(0.30, 0.90, 7),
            "boost": _linspace(0.8, 2.0, 7),
            "effective_cap": _linspace(0.80, 1.40, 7),
            "equal_factor": _linspace(0.0, 1.20, 13),
        },
        metric="rms",
    )
    report(predict_v6_equal_count, v6_best["params"], "V6 equal-count extended (RMS)")

    # V7 — full-loop over all large pieces (no separate extras slice).
    print("\n--- V7 grid refit ---")
    v7_best = grid_search(
        predict_v7_full_loop,
        {
            "slope": _linspace(2.5, 5.5, 7),
            "intercept": _linspace(0.10, 0.50, 5),
            "cap": _linspace(0.35, 0.90, 8),
            "decay": _linspace(0.20, 0.65, 7),
            "boost": _linspace(0.4, 1.8, 8),
            "effective_cap": _linspace(0.80, 1.40, 7),
        },
        metric="rms",
    )
    report(predict_v7_full_loop, v7_best["params"], "V7 full-loop (RMS)")

    # V8 — V7 + stud-factor magnitude term.
    # KTC's FAQ explicitly names "stud factor" as a distinct input.
    # V7's per-piece weight is purely ratio-based (top_gap is a
    # percentage), so V8 adds a multiplier that amplifies elite-top-
    # piece trades.  When stud_coeff=0 V8 collapses to V7 exactly,
    # so the grid search can decide whether the stud term improves
    # the fit or is just absorbed by other parameters.
    #
    # Grid is intentionally wider on stud_coeff (0.0 to 1.5) so the
    # search can choose to NOT apply it (coeff=0).  Threshold range
    # 5000-8500 spans "top-100 dynasty" through "top-25 elite-only".
    print("\n--- V8 grid refit ---")
    v8_best = grid_search(
        predict_v8_stud_factor,
        {
            "slope": _linspace(2.5, 5.5, 6),
            "intercept": _linspace(0.10, 0.50, 4),
            "cap": _linspace(0.35, 0.90, 6),
            "decay": _linspace(0.20, 0.65, 5),
            "boost": _linspace(0.4, 1.8, 6),
            "effective_cap": _linspace(0.80, 1.40, 5),
            "stud_coeff": _linspace(0.0, 1.5, 7),
            "stud_threshold": [5000.0, 6500.0, 7000.0, 7500.0, 8500.0],
        },
        metric="rms",
    )
    report(predict_v8_stud_factor, v8_best["params"], "V8 stud-factor (RMS)")

    # V9: split formula — V4 additive for unequal counts + a separate
    # equal-count branch.  V1-V8 all share one structural problem:
    # they treat equal piece counts as either "no extras" (V1-V5) or
    # "iterate over the whole large side" (V6-V8).  Neither matches
    # KTC, which fires VA on stud-vs-pile shapes for equal counts but
    # silences it when the trade is too lopsided.  V9 separates the
    # branches and lets the grid learn each independently.
    print("\n--- V9 grid (split formula, equal-count branch) ---")
    v9_best = grid_search(
        predict_v9_split,
        {
            # V4 unequal-count params (same ranges as V4)
            "floor": _linspace(-0.30, 0.10, 5),
            "alpha": _linspace(0.6, 2.4, 6),
            "beta": _linspace(0.0, 0.8, 5),
            "cap": _linspace(0.6, 1.5, 5),
            "decay": _linspace(0.5, 0.95, 5),
            # Equal-count branch params
            "eq_offset": _linspace(0.0, 2500.0, 6),
            "eq_top_coeff": _linspace(0.0, 1.2, 7),
            "eq_count_coeff": _linspace(-800.0, 200.0, 6),
        },
        metric="rms",
    )
    report(predict_v9_split, v9_best["params"], "V9 split (RMS)")

    # V10: V9 + a two-gate classifier on the equal-count branch.
    # Gate 1 (min_top_gap) silences trades where the top advantage is
    # under a few percent; gate 2 (dom_count_thresh) silences trades
    # where small dominates large piece-by-piece at deep counts.
    # Inside the gates, the linear stud-vs-pile term fires.
    #
    # V4 unequal-count params are narrowed around V4's known optimum
    # (floor=-0.25, alpha=2.0, beta=0.6, cap=1.2, decay=0.7) to keep
    # the grid tractable while still letting the equal-count branch
    # flex.
    print("\n--- V10 grid (V9 + classifier gates) ---")
    v10_best = grid_search(
        predict_v10_classifier,
        {
            # V4 unequal — narrow grid around known optimum
            "floor": [-0.30, -0.25, -0.20],
            "alpha": [1.6, 2.0, 2.4],
            "beta": [0.4, 0.6, 0.8],
            "cap": [1.0, 1.2, 1.5],
            "decay": [0.6, 0.7, 0.8],
            # Classifier gates
            "min_top_gap": [0.05, 0.10, 0.15],
            "dom_count_thresh": [3, 4],
            # Equal-count linear term (only fires when both gates pass)
            "eq_offset": [0.0, 1000.0, 2000.0],
            "eq_top_coeff": [0.0, 0.3, 0.6, 0.9],
            "eq_count_coeff": [-500.0, 0.0, 500.0],
        },
        metric="rms",
    )
    report(predict_v10_classifier, v10_best["params"], "V10 classifier (RMS)")

    # Summary ranking.
    total_points = len(DATA)
    print("\n=== CANDIDATE RANKING (by RMS) ===")
    candidates = [
        ("V1 prod", predict_v1_current, v1_prod),
        ("V1 refit", predict_v1_current, v1_best["params"]),
        ("V2", predict_v2_per_extra, v2_best["params"]),
        ("V3", predict_v3_hybrid, v3_best["params"]),
        ("V4", predict_v4_additive, v4_best["params"]),
        ("V5", predict_v5_additive_with_roster, v5_best["params"]),
        ("V6", predict_v6_equal_count, v6_best["params"]),
        ("V7", predict_v7_full_loop, v7_best["params"]),
        ("V8", predict_v8_stud_factor, v8_best["params"]),
        ("V9", predict_v9_split, v9_best["params"]),
        ("V10", predict_v10_classifier, v10_best["params"]),
    ]
    for name, fn, params in candidates:
        errs = [abs(r[3]) for r in errors(fn, params)]
        mean = sum(errs) / len(errs) * 100
        mx = max(errs) * 100
        rms = ((sum(e * e for e in errs) / len(errs)) ** 0.5) * 100
        over_10 = sum(1 for e in errs if e > 0.10)
        over_20 = sum(1 for e in errs if e > 0.20)
        print(f"  {name:<10}  rms={rms:5.2f}%  mean={mean:5.2f}%  max={mx:5.2f}%  "
              f">10%: {over_10}/{total_points}  >20%: {over_20}/{total_points}")


if __name__ == "__main__":
    main()
