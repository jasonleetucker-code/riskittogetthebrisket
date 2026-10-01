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

from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.canonical.player_valuation import PERCENTILE_REFERENCE_N, training_percentiles
from src.canonical.tail_policy import clamp_percentile
from src.model_registry.training_manifest import (
    FIT_TOP_N,
    MEASURED_DEPENDENCES,
    ROLE_HOLDOUT,
    ROLE_TRAIN,
    MissingColumnError,
    default_manifest,
    family_for_path,
    load_board_values,
    source_key_for_path,
)

REPO = Path(__file__).resolve().parents[2]

# Both lists are DERIVED from the one training manifest
# (``src/model_registry/training_manifest.py``), whose paths, signal types and
# provider families come from the live source registry.  They used to be two
# hand-maintained literals — here and in the fit script — tied together by a
# text-parsing test and to nothing else (H8).  Fantasy Navigator is no longer a
# holdout: it is KTC-derived (``ktcCrowd`` family) and KTC trains the curve, so
# the manifest excludes it as confirmed common ancestry (H5).  KeepTradeCut's own
# TE++ board stays out for the same reason it always did, now by family rather
# than by a comment.
#
# Built LAZILY, never at import. ``src/api/data_contract.py`` imports this
# package (outside any try) to stamp ``hillCurves.provenance`` on every
# ``/api/data`` build; building the manifest reads the live source registry and
# can raise ``ManifestError`` by design. Built at import, one future registry
# edit that made ``build_manifest`` raise would have crashed every contract
# build for a metadata stamp. Importing ``src.model_registry`` therefore costs
# nothing and cannot fail on the manifest; the tables are built on first use.


@lru_cache(maxsize=1)
def _offense_tables() -> tuple[dict[str, tuple[str, str]], dict[str, tuple[str, str]]]:
    manifest = default_manifest()
    return manifest.csv_table("OFFENSE", ROLE_TRAIN), manifest.csv_table("OFFENSE", ROLE_HOLDOUT)


def offense_training_sources() -> dict[str, tuple[str, str]]:
    """``{label: (path, value_column)}`` of the OFFENSE trainers (a copy)."""
    return dict(_offense_tables()[0])


def offense_holdout_sources() -> dict[str, tuple[str, str]]:
    """``{label: (path, value_column)}`` of the OFFENSE holdouts (a copy)."""
    return dict(_offense_tables()[1])


def __getattr__(name: str) -> Any:
    """``OFFENSE_TRAINING_SOURCES`` / ``OFFENSE_HOLDOUT_SOURCES`` stay importable
    by name (PEP 562) for their existing consumers, but resolve on first access."""
    if name == "OFFENSE_TRAINING_SOURCES":
        return offense_training_sources()
    if name == "OFFENSE_HOLDOUT_SOURCES":
        return offense_holdout_sources()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# The fit truncates every source to its top FIT_TOP_N before computing
# percentiles.  Matched exactly so train and holdout RMSE are the same
# quantity measured on different data.  Owned by the manifest.
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
    for label, (path, col) in sorted(offense_training_sources().items()):
        out.append(SourceRole(label, path, col, "train"))
    for label, (path, col) in sorted(offense_holdout_sources().items()):
        out.append(SourceRole(label, path, col, "holdout"))
    return tuple(out)


def _load_values(path: Path, column: str) -> list[float]:
    """Players-only positive values from ``column``, descending.

    Delegates to the manifest's one population rule, so a holdout can never
    score a pick row the fit would not have trained on (E3)."""
    return list(load_board_values(path, column).values)


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

    What is NOT duplicated is the tail bound. This used to clamp
    ``min(p, 1.0)`` on its own, so a repaired serving curve would have
    been graded by a still-saturated evaluator — a challenger scored
    against a shape production no longer serves. The (c, s) pair stays
    free; where the tail ends is the canonical owner's answer.
    """
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (clamp_percentile(p, reference_n=PERCENTILE_REFERENCE_N) / c) ** s)


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
    #: label -> provider family, for every SCORED holdout board.
    holdout_family_by_board: dict[str, str] = field(default_factory=dict)
    training_families: tuple[str, ...] = ()
    #: label -> training families the board has a MEASURED dependence on.
    measured_dependence: dict[str, list[str]] = field(default_factory=dict)

    @property
    def independent_criterion(self) -> float | None:
        """Mean RMSE over scored boards with NO measured dependence on a trainer.

        ``None`` — never a number — when every scored board is dependent."""
        free = [v for k, v in self.per_source.items() if not self.measured_dependence.get(k)]
        return sum(free) / len(free) if free else None

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
            "holdoutFamilies": sorted(set(self.holdout_family_by_board.values())),
            "holdoutFamilyByBoard": dict(sorted(self.holdout_family_by_board.items())),
            "trainingFamilies": list(self.training_families),
            # Measured dependence is NOT confirmed ancestry (ancestry is refused
            # outright); it is reported so a reader can discount a board whose
            # score is partly flattered by its correlate in training.
            "measuredDependence": dict(sorted(self.measured_dependence.items())),
            "independentCriterion": (
                None if self.independent_criterion is None else round(self.independent_criterion, 4)
            ),
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
    holdout = dict(offense_holdout_sources() if holdout_sources is None else holdout_sources)
    training = dict(offense_training_sources() if training_sources is None else training_sources)

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
    # The split is by PROVIDER FAMILY too: a held-out board that shares a
    # family with a training board (Fantasy Navigator vs KTC) is training
    # evidence under another site's name (H5). Unknown paths are their own
    # singleton family — unprovable shared ancestry is not assumed.
    train_families = {family_for_path(p) for p, _ in training.values()}
    holdout_family = {label: family_for_path(p) for label, (p, _) in holdout.items()}
    family_overlap = sorted(
        f"{label}:{fam}" for label, fam in holdout_family.items() if fam in train_families
    )
    if family_overlap:
        raise HoldoutError(
            f"holdout sources {family_overlap} share a provider family with a training "
            "source; a derivative board cannot be independent evidence about its ancestor"
        )

    per_source: dict[str, float] = {}
    per_source_rows: dict[str, int] = {}
    skipped: dict[str, str] = {}

    for label, (rel_path, column) in sorted(holdout.items()):
        path = root / rel_path
        if not path.exists():
            skipped[label] = "csv missing"
            continue
        try:
            values = _load_values(path, column)
        except MissingColumnError:
            # A renamed vendor column is MISSING, not a board of zeros: the
            # board is skipped with the reason named, never scored as empty.
            skipped[label] = f"missing_column:{column}"
            continue
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

    dependence: dict[str, list[str]] = {}
    for label in per_source:
        key = source_key_for_path(holdout[label][0])
        fams = sorted(
            {
                d.trainer_family
                for d in MEASURED_DEPENDENCES
                if key is not None and d.source_key == key and d.trainer_family in train_families
            }
        )
        if fams:
            dependence[label] = fams

    return HoldoutResult(
        criterion=sum(per_source.values()) / len(per_source),
        per_source=per_source,
        per_source_rows=per_source_rows,
        skipped=skipped,
        params={"c": c, "s": s},
        holdout_labels=tuple(sorted(per_source)),
        training_labels=tuple(sorted(training)),
        holdout_family_by_board={label: holdout_family[label] for label in per_source},
        training_families=tuple(sorted(train_families)),
        measured_dependence=dependence,
    )
