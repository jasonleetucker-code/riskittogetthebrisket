"""Out-of-sample evaluation for the Hill scope masters.

Why this module exists
──────────────────────
The refit workflow's only guard is
``tests/canonical/test_ktc_reconciliation.py``, and that guard cannot
fail after a refit, for two independent reasons:

1. ``scripts/auto_refit_hill_curves.py::rebaseline_ktc_reconciliation``
   REWRITES the test's expected values from the new constants before
   the test runs.  Both assertions — the exact ``ours == pinned_ours``
   pin and the ``pct_diff`` band — are recomputed from the challenger
   itself against the same ``ktc.csv`` the test reads.  The residual is
   zero by construction.
2. Even with honest pins, KTC is a TRAINING source: ``ktc.csv`` is in
   ``fit_hill_curve_percentile.OFFENSE_SOURCES``, and the OFFENSE
   master it trains is exactly the ``HILL_PERCENTILE_C/S`` pair that
   ``percentile_to_value`` uses.  Scoring the fit against its own
   training data is ORCHESTRATION.md §2b: the assumption reflected
   back.

So this module evaluates the curve against value-publishing markets
that the fit never sees, using the fit's own metric so the numbers are
comparable.

What the criterion measures — and what it does not
──────────────────────────────────────────────────
It measures GENERALIZATION ACROSS MARKETS: does a curve fitted to six
dynasty value boards also describe boards it was not fitted to?  A
challenger that improves here is describing the shape of the dynasty
market more faithfully than the incumbent.

It does NOT measure accuracy against reality.  Every holdout source is
another consensus market, correlated with the training sources by
construction — they price the same players off the same news.  There
is no ground truth for what a dynasty asset is "really" worth, so no
check here can establish that the curve is CORRECT.  It can only
establish that the curve is not overfitted to the particular six
boards it was trained on.  Anyone citing these numbers must say which
of those two claims they are making.

Pure computation over supplied files.  No network.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.canonical.player_valuation import training_percentiles

REPO = Path(__file__).resolve().parents[2]

# Mirrors scripts/fit_hill_curve_percentile.py::OFFENSE_SOURCES.  Kept
# as a literal rather than imported because that file is a script with
# side-effecting module scope; a parity test pins the two together so
# this cannot silently drift.
OFFENSE_TRAINING_SOURCES: dict[str, tuple[str, str]] = {
    "KTC": ("CSVs/site_raw/ktc.csv", "value"),
    "DynastyDaddy": ("CSVs/site_raw/dynastyDaddySf.csv", "value"),
    "DynastyNerds": ("CSVs/site_raw/dynastyNerdsSfTep.csv", "Value"),
    "YahooBoone": ("CSVs/site_raw/yahooBoone.csv", "boone_value"),
    "Fitzmaurice": ("CSVs/site_raw/fantasyProsFitzmaurice.csv", "value"),
    "DraftSharks": ("CSVs/site_raw/draftSharksSf.csv", "3D Value +"),
}

# Value-publishing offense boards that the fit does NOT consume.
#
# ktcSfTep is deliberately EXCLUDED despite not appearing in the fit's
# source dict: it is KeepTradeCut's own SF-TEP board, the same market
# maker as the ``KTC`` training source.  Treating it as held out would
# smuggle a training source back in under a different filename, which
# is the subtler version of the defect this module exists to catch.
OFFENSE_HOLDOUT_SOURCES: dict[str, tuple[str, str]] = {
    "FantasyCalc": ("CSVs/site_raw/fantasyCalc.csv", "value"),
    "OTCFFB": ("CSVs/site_raw/otcffbSf.csv", "value"),
    "PFKDynasty": ("CSVs/site_raw/pfkDynasty.csv", "value"),
    "FantasyNavigator": ("CSVs/site_raw/fantasyNavigatorSf.csv", "value"),
}

# The fit truncates every source to its top 400 before computing
# percentiles.  Matched exactly so train and holdout RMSE are the same
# quantity measured on different data.
FIT_TOP_N: int = 400
MIN_ROWS_FOR_SCORING: int = 100


class HoldoutError(RuntimeError):
    """Raised when an evaluation would be meaningless if it succeeded."""


@dataclass(frozen=True)
class SourceRole:
    """Which side of the train/holdout line a source sits on."""

    label: str
    path: str
    value_column: str
    role: str  # "train" | "holdout"


def source_roles() -> tuple[SourceRole, ...]:
    """Every offense value source, labelled by role.

    Exported so a caller can print the split rather than trust it.
    """
    out: list[SourceRole] = []
    for label, (path, col) in sorted(OFFENSE_TRAINING_SOURCES.items()):
        out.append(SourceRole(label, path, col, "train"))
    for label, (path, col) in sorted(OFFENSE_HOLDOUT_SOURCES.items()):
        out.append(SourceRole(label, path, col, "holdout"))
    return tuple(out)


def _load_values(path: Path, column: str) -> list[float]:
    """Positive values from ``column``, descending.  Mirrors the fit."""
    values: list[float] = []
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw = row.get(column)
            try:
                v = float(raw) if raw not in (None, "") else 0.0
            except (TypeError, ValueError):
                continue
            if v > 0:
                values.append(v)
    values.sort(reverse=True)
    return values


def _percentile_pairs(values: Sequence[float]) -> list[tuple[float, float]]:
    """``[(p, normalized_value)]`` with the top anchored at 9999.

    Identical to ``fit_hill_curve_percentile._percentile_pairs`` — the
    percentile is native to the source's own pool, and the top value
    normalizes to the curve's anchor.
    """
    vs = list(values[:FIT_TOP_N])
    n = len(vs)
    if n < 2:
        return []
    top = vs[0]
    if top <= 0:
        return []
    # Percentiles come from the canonical coordinate owner, not from the
    # length of the truncated list. FIT_TOP_N still selects WHICH rows
    # are scored; it no longer decides what universe they are scored
    # against (audit finding W30-F008). Grading a curve on a different
    # coordinate system than it was trained on is exactly the mismatch
    # this module exists to detect.
    ps = training_percentiles(n)
    return [(ps[i], vs[i] / top * 9999.0) for i in range(n)]


def hill(p: float, c: float, s: float) -> float:
    """``V(p) = 9999 / (1 + (p/c)^s)`` — the fit's model, standalone.

    Duplicated from ``player_valuation.percentile_to_value`` on
    purpose: this module must be able to score an ARBITRARY (c, s)
    pair, including a challenger that is not installed anywhere, and
    the production function reads committed module constants.
    """
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (min(p, 1.0) / c) ** s)


def _rmse(pairs: Sequence[tuple[float, float]], c: float, s: float) -> float:
    return (sum((hill(p, c, s) - v) ** 2 for p, v in pairs) / len(pairs)) ** 0.5


@dataclass(frozen=True)
class HoldoutResult:
    """Out-of-sample score for one (c, s) pair.

    ``criterion`` is the mean per-source RMSE across held-out boards.
    Mean rather than pooled: pooling would weight a 400-row board four
    times a 100-row one, letting one market dominate the verdict.
    """

    criterion: float
    per_source: dict[str, float]
    per_source_rows: dict[str, int]
    skipped: dict[str, str]
    params: dict[str, float]
    holdout_labels: tuple[str, ...]
    training_labels: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        # ``measuredAt`` exists because the criterion's absolute level
        # drifts with the market — ~19 points on IDENTICAL parameters in
        # 7 days, measured 2026-08-05, against a 25-point promotion
        # margin.  Without a date, three scores taken on three different
        # days sit in one file looking directly comparable, and the only
        # way to tell them apart was hand-written prose in ``notes``.
        # That is what let the registry record a verdict its own stored
        # numbers disagree with (v3's note says +22.4; the stored pair
        # gives +12.79).
        #
        # ``cmd_validate`` no longer trusts a stored criterion at all —
        # it re-scores both curves — but it prints this date when the
        # stored figure differs, so a stale registry is visible rather
        # than silently bypassed.
        return {
            "criterion": round(self.criterion, 4),
            "measuredAt": datetime.now(timezone.utc).isoformat(),
            "criterionName": "mean_per_source_rmse",
            "criterionUnits": "points on the 0-9999 value scale (lower is better)",
            "perSource": {k: round(v, 4) for k, v in sorted(self.per_source.items())},
            "perSourceRows": dict(sorted(self.per_source_rows.items())),
            "skipped": dict(sorted(self.skipped.items())),
            "params": dict(self.params),
            "holdoutSources": list(self.holdout_labels),
            "trainingSources": list(self.training_labels),
            "_semantics": {
                "measures": (
                    "generalization across dynasty markets — whether a curve fitted "
                    "to the training boards also describes boards it never saw"
                ),
                "doesNotMeasure": (
                    "accuracy against reality; every holdout board is another "
                    "consensus market correlated with the training boards, and no "
                    "ground truth for dynasty value exists"
                ),
            },
        }


def evaluate_offense_master(
    c: float,
    s: float,
    *,
    repo_root: Path | None = None,
    holdout_sources: Mapping[str, tuple[str, str]] | None = None,
    training_sources: Mapping[str, tuple[str, str]] | None = None,
) -> HoldoutResult:
    """Score an OFFENSE Hill master on boards the fit never consumed.

    Raises :class:`HoldoutError` rather than returning a number when
    the evaluation would be vacuous — an overlap between the training
    and holdout sets, or no usable holdout board.  A validation gate
    that silently degrades to "no data, therefore pass" is worse than
    no gate, because it reports success.
    """
    root = repo_root or REPO
    # `is None`, not `or`: an explicitly EMPTY holdout set is a caller
    # saying "I have no held-out data", and falling back to the default
    # set would answer a question they did not ask — with a passing
    # score, which is the exact failure this function exists to refuse.
    holdout = dict(OFFENSE_HOLDOUT_SOURCES if holdout_sources is None else holdout_sources)
    training = dict(OFFENSE_TRAINING_SOURCES if training_sources is None else training_sources)

    overlap = sorted(set(holdout) & set(training))
    if overlap:
        raise HoldoutError(
            f"sources {overlap} are in BOTH the training and holdout sets; "
            "scoring a fit against its own training data measures nothing"
        )
    train_paths = {p for p, _ in training.values()}
    path_overlap = sorted({label for label, (p, _) in holdout.items() if p in train_paths})
    if path_overlap:
        raise HoldoutError(
            f"holdout sources {path_overlap} point at a training CSV; the split is "
            "by FILE, not by label"
        )
    if not holdout:
        raise HoldoutError("no holdout sources configured")

    per_source: dict[str, float] = {}
    per_source_rows: dict[str, int] = {}
    skipped: dict[str, str] = {}

    for label, (rel_path, column) in sorted(holdout.items()):
        path = root / rel_path
        if not path.exists():
            skipped[label] = "csv missing"
            continue
        values = _load_values(path, column)
        if len(values) < MIN_ROWS_FOR_SCORING:
            skipped[label] = f"only {len(values)} priced rows (need {MIN_ROWS_FOR_SCORING})"
            continue
        pairs = _percentile_pairs(values)
        if not pairs:
            skipped[label] = "no usable percentile pairs"
            continue
        per_source[label] = _rmse(pairs, c, s)
        per_source_rows[label] = len(pairs)

    if not per_source:
        raise HoldoutError(
            f"no holdout board could be scored (skipped: {skipped}); refusing to "
            "report a passing evaluation with no evidence behind it"
        )

    return HoldoutResult(
        criterion=sum(per_source.values()) / len(per_source),
        per_source=per_source,
        per_source_rows=per_source_rows,
        skipped=skipped,
        params={"c": c, "s": s},
        holdout_labels=tuple(sorted(per_source)),
        training_labels=tuple(sorted(training)),
    )
