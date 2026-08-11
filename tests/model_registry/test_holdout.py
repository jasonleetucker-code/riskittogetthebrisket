"""Tests for the held-out evaluation.

The headline requirement is that this gate CAN FAIL.  The gate it
replaces could not: ``auto_refit_hill_curves.rebaseline_ktc_reconciliation``
rewrites the KTC test's expectations from the challenger before the
test runs, and KTC is a training source besides.  A validation gate
whose only outcome is "pass" is worse than no gate, because it reports
success.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src.canonical.player_valuation import training_percentiles
from src.model_registry.holdout import (
    MIN_ROWS_FOR_SCORING,
    OFFENSE_HOLDOUT_SOURCES,
    OFFENSE_TRAINING_SOURCES,
    HoldoutError,
    evaluate_offense_master,
    hill,
    source_roles,
)

REPO = Path(__file__).resolve().parents[2]


def _write_board(path: Path, values: list[float], column: str = "value") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", column])
        w.writeheader()
        for i, v in enumerate(values):
            w.writerow({"name": f"player{i}", column: v})


def _curve_board(c: float, s: float, n: int = 400) -> list[float]:
    """A board that a curve with (c, s) fits exactly.

    "Exactly" is defined by the coordinate system the holdout grades in,
    so this generates rows at the CANONICAL percentile for their ordinal
    rank. It previously used ``i / (n - 1)`` — the local-length
    convention W30-F008 removed — which made the fixture agree with the
    old holdout by construction and would now manufacture a mismatch
    that says nothing about the gate.
    """
    return [hill(p, c, s) for p in training_percentiles(n)]


class TestTrainHoldoutSeparation:
    """The split is the whole mechanism. Guard it from every angle."""

    def test_no_source_is_in_both_sets(self):
        assert not (set(OFFENSE_TRAINING_SOURCES) & set(OFFENSE_HOLDOUT_SOURCES))

    def test_no_holdout_csv_is_a_training_csv(self):
        """MECHANISM TEST. The split is by FILE, not by label — renaming
        a training source would otherwise smuggle it into the holdout."""
        train_paths = {p for p, _ in OFFENSE_TRAINING_SOURCES.values()}
        for label, (path, _) in OFFENSE_HOLDOUT_SOURCES.items():
            assert path not in train_paths, f"{label} points at a training CSV"

    def test_overlapping_sets_raise_rather_than_score(self, tmp_path):
        """A gate that scores a model on its own training data must
        refuse, not return a good-looking number."""
        board = tmp_path / "b.csv"
        _write_board(board, _curve_board(0.118, 1.17))
        shared = {"KTC": ("b.csv", "value")}
        with pytest.raises(HoldoutError, match="BOTH the training and holdout"):
            evaluate_offense_master(
                0.118, 1.17, repo_root=tmp_path, holdout_sources=shared, training_sources=shared
            )

    def test_same_file_under_a_different_label_still_raises(self):
        """MECHANISM TEST for the subtle version: relabel, same data."""
        with pytest.raises(HoldoutError, match="point at a training CSV"):
            evaluate_offense_master(
                0.118,
                1.17,
                holdout_sources={"KTC_Renamed": ("CSVs/site_raw/ktc.csv", "value")},
                training_sources=OFFENSE_TRAINING_SOURCES,
            )

    def test_ktc_sf_tep_is_not_treated_as_held_out(self):
        """ktcSfTep is KTC's own board. Holding it out would be the
        same market maker scoring its own fit."""
        holdout_paths = {p for p, _ in OFFENSE_HOLDOUT_SOURCES.values()}
        assert not any("ktc" in p.lower() for p in holdout_paths)

    def test_roles_cover_every_configured_source(self):
        roles = source_roles()
        assert {r.label for r in roles if r.role == "train"} == set(OFFENSE_TRAINING_SOURCES)
        assert {r.label for r in roles if r.role == "holdout"} == set(OFFENSE_HOLDOUT_SOURCES)


class TestGateCanFail:
    """The property the replaced gate lacked."""

    def test_a_wrong_curve_scores_worse_than_the_right_one(self, tmp_path):
        """MECHANISM TEST. If this ever stops discriminating, the
        criterion has gone constant and the gate is decorative."""
        _write_board(tmp_path / "h.csv", _curve_board(0.118, 1.17))
        sources = {"H": ("h.csv", "value")}

        exact = evaluate_offense_master(
            0.118, 1.17, repo_root=tmp_path, holdout_sources=sources, training_sources={}
        )
        wrong = evaluate_offense_master(
            0.200, 1.60, repo_root=tmp_path, holdout_sources=sources, training_sources={}
        )
        assert exact.criterion < 1.0, "a curve fitted exactly should score ~0"
        assert wrong.criterion > 100.0
        assert wrong.criterion > exact.criterion

    def test_criterion_responds_monotonically_to_error(self, tmp_path):
        _write_board(tmp_path / "h.csv", _curve_board(0.118, 1.17))
        sources = {"H": ("h.csv", "value")}
        scores = [
            evaluate_offense_master(
                c, 1.17, repo_root=tmp_path, holdout_sources=sources, training_sources={}
            ).criterion
            for c in (0.118, 0.128, 0.148, 0.188)
        ]
        assert scores == sorted(scores), f"criterion not monotonic in error: {scores}"


class TestRefusesVacuousSuccess:
    """No-evidence must not read as pass."""

    def test_missing_boards_raise_rather_than_pass(self, tmp_path):
        with pytest.raises(HoldoutError, match="no holdout board could be scored"):
            evaluate_offense_master(
                0.118,
                1.17,
                repo_root=tmp_path,
                holdout_sources={"Gone": ("nope.csv", "value")},
                training_sources={},
            )

    def test_thin_boards_are_skipped_and_named(self, tmp_path):
        _write_board(tmp_path / "thin.csv", _curve_board(0.118, 1.17, n=10))
        _write_board(tmp_path / "fat.csv", _curve_board(0.118, 1.17, n=400))
        result = evaluate_offense_master(
            0.118,
            1.17,
            repo_root=tmp_path,
            holdout_sources={"Thin": ("thin.csv", "value"), "Fat": ("fat.csv", "value")},
            training_sources={},
        )
        assert "Thin" in result.skipped
        assert str(MIN_ROWS_FOR_SCORING) in result.skipped["Thin"]
        assert "Fat" in result.per_source

    def test_empty_holdout_config_raises(self):
        with pytest.raises(HoldoutError, match="no holdout sources"):
            evaluate_offense_master(0.118, 1.17, holdout_sources={}, training_sources={})


class TestPayloadStatesItsLimits:
    def test_serialized_result_says_what_it_does_not_measure(self, tmp_path):
        _write_board(tmp_path / "h.csv", _curve_board(0.118, 1.17))
        result = evaluate_offense_master(
            0.118,
            1.17,
            repo_root=tmp_path,
            holdout_sources={"H": ("h.csv", "value")},
            training_sources={},
        )
        blob = result.to_dict()
        assert "doesNotMeasure" in blob["_semantics"]
        assert "ground truth" in blob["_semantics"]["doesNotMeasure"]
        assert blob["criterionUnits"]
        assert blob["trainingSources"] is not None


@pytest.mark.livedata
class TestAgainstRealBoards:
    """The criterion must discriminate on the actual CSVs, not just
    synthetic ones — the `_positional_coverage` lesson."""

    def test_real_holdout_boards_produce_varying_scores(self):
        result = evaluate_offense_master(0.118, 1.17)
        assert len(result.per_source) >= 3
        scores = list(result.per_source.values())
        assert len(set(round(v, 2) for v in scores)) == len(scores)
        assert max(scores) - min(scores) > 100, "all real boards score alike — suspicious"

    def test_criterion_moves_on_real_boards(self):
        base = evaluate_offense_master(0.118, 1.17).criterion
        moved = evaluate_offense_master(0.098, 1.17).criterion
        assert abs(base - moved) > 50, "real-board criterion is insensitive to the curve"


@pytest.mark.livedata
class TestTheBoardsDisagree:
    """Pins the disagreement that narrowed ADR-008's headline claim.

    A first pass reported "the champion is ~200 points off the holdout
    optimum". Measuring per board rather than on the mean showed that
    to be too strong: the improvement is three boards outvoting one,
    and the mean-optimal point sits on the edge of the search grid
    rather than at a bracketed minimum.

    These tests exist so the narrower claim cannot quietly drift back
    to the stronger one, and so a data refresh that changes the picture
    surfaces here rather than in a confident sentence.

    RE-CHARACTERISED 2026-08-11 (B1 / W30-F008), and the cause was NOT a
    data refresh — it was the fit/serve percentile-coordinate repair.
    Grading on the canonical coordinate instead of the holdout's local
    ``i / (n - 1)`` moved every number, and it dissolved the
    disagreement these tests were written to pin:

        board             OLD champ -> prop      NEW champ -> prop
        FantasyCalc          851.00    566.49     1255.01    923.03
        FantasyNavigator    1185.15    889.84     1589.10   1250.29
        OTCFFB              1012.59    708.05     1514.87   1169.48
        PFKDynasty           254.34    335.27      552.03    283.81
        criterion (mean)     825.77    624.91     1227.75    906.65

    Two things changed, and both matter:

    1. The champion scores materially WORSE on every board once graded
       honestly (825.77 -> 1227.75). That is the expected consequence of
       the defect, not a regression: the champion was fit in a
       coordinate system that placed each training row at a larger
       percentile than serving used, so the curve was never scored
       against the coordinates it is actually served on.

    2. **The disagreement is gone.** Under the old coordinates the
       improvement was three boards outvoting PFKDynasty, which
       worsened. Under the corrected ones all four improve, PFKDynasty
       most of all (552.03 -> 283.81, a 49% drop). The board that
       "already sat near its own optimum" was an artifact of grading it
       on a mismatched scale.

    ADR-008 narrowed its headline claim on the strength of that
    disagreement. The narrowing may no longer be justified — that is an
    owner-facing finding recorded in the B1 report, not something these
    tests decide.
    """

    CHAMPION = (0.118, 1.17)
    PROPOSED = (0.098, 1.17)

    def test_the_mean_improves(self):
        champ = evaluate_offense_master(*self.CHAMPION)
        proposed = evaluate_offense_master(*self.PROPOSED)
        assert proposed.criterion < champ.criterion

    def test_every_board_now_agrees(self):
        """The re-characterised claim: unanimity, not a 3-1 vote.

        Fails if a board starts dissenting again — which would mean
        either a data refresh moved the picture, or the coordinate
        contract regressed.
        """
        champ = evaluate_offense_master(*self.CHAMPION)
        proposed = evaluate_offense_master(*self.PROPOSED)
        worsened = [b for b in champ.per_source if proposed.per_source[b] > champ.per_source[b]]
        assert not worsened, (
            f"boards {worsened} now dissent under the canonical coordinate; the "
            "unanimity recorded on 2026-08-11 has broken and ADR-008's revisit "
            "needs re-deriving"
        )

    def test_the_board_the_champion_fits_best_now_improves_too(self):
        """PFKDynasty was the dissenter; it is now the biggest gainer.

        The inversion is the single clearest piece of evidence that the
        old disagreement was a coordinate artifact rather than a real
        property of that board.
        """
        champ = evaluate_offense_master(*self.CHAMPION)
        proposed = evaluate_offense_master(*self.PROPOSED)
        best_fit = min(champ.per_source, key=lambda b: champ.per_source[b])
        assert proposed.per_source[best_fit] < champ.per_source[best_fit]

    def test_the_mean_optimum_is_not_bracketed_by_the_search_grid(self):
        """MECHANISM TEST. If the criterion still falls at the grid
        floor, no interior optimum has been located and no specific
        (c, s) may be reported as "the optimum"."""
        floor = evaluate_offense_master(0.080, 1.30).criterion
        inside = evaluate_offense_master(0.090, 1.30).criterion
        assert floor < inside, (
            "the criterion now has an interior minimum above c=0.080; an optimum "
            "can be quoted, which ADR-008 currently says it cannot"
        )

    def test_training_and_holdout_objectives_disagree_in_direction(self):
        """The evidence that the gate is not a rubber stamp: a change
        that hurts the training mean helps the holdout mean."""
        base = evaluate_offense_master(0.118, 1.17).criterion
        moved = evaluate_offense_master(0.118, 1.37).criterion
        assert moved < base, "holdout no longer prefers s=1.37 over s=1.17"
