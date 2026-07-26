"""Tests for ``src/roster_intel/roster_source.py``.

The module exists because WS-J reintroduced ADR-007's defect from the
data side: the ROS aggregate carries no ``fantasy_positions``, so joining
rosters to it alone hands the optimizer position-only rows and hybrid
IDPs get locked out of half their legal slots.  The optimizer is correct;
the data path feeding it was not.

These are mechanism-disconnection tests per ORCHESTRATION §2b — each
fails if eligibility enrichment is silently dropped, which is the
failure mode that produces no error and only a quietly worse lineup.
"""

from __future__ import annotations

import pytest

from src.roster_intel.marginal import position_marginals, solve_summary, to_roster_players
from src.roster_intel.roster_source import (
    build_nfl_position_index,
    build_roster_pool,
    build_value_index,
    hybrid_coverage,
    normalize_name,
)


def _agg(name, pos, value, **kw):
    return {"canonicalName": name, "position": pos, "rosValue": value, **kw}


def _nfl(pid, first, last, pos, fpos):
    return (
        pid,
        {"first_name": first, "last_name": last, "position": pos, "fantasy_positions": fpos},
    )


# ── Name normalization ─────────────────────────────────────────────


class TestNormalizeName:
    def test_strips_punctuation_case_and_spacing(self):
        assert normalize_name("Ja'Marr Chase") == normalize_name("jamarr chase")
        assert normalize_name("A.J. Brown") == normalize_name("aj brown")
        assert normalize_name("  Bijan  Robinson ") == "bijanrobinson"

    def test_empty_inputs_are_empty(self):
        assert normalize_name(None) == ""
        assert normalize_name("") == ""


# ── Value index / duplicate handling ───────────────────────────────


class TestValueIndex:
    def test_duplicate_rows_keep_the_higher_value(self):
        """The WS-E audit found the same player under two spellings with
        ROS value split across both. Taking whichever row came last
        would make the result depend on file ordering."""
        idx = build_value_index(
            [_agg("Cam Skattebo", "RB", 12.0), _agg("cam skattebo", "RB", 47.0)]
        )
        assert len(idx) == 1
        assert idx["camskattebo"]["rosValue"] == 47.0

    def test_ordering_does_not_change_the_result(self):
        a = build_value_index([_agg("Tank Dell", "WR", 5.0), _agg("tank dell", "WR", 30.0)])
        b = build_value_index([_agg("tank dell", "WR", 30.0), _agg("Tank Dell", "WR", 5.0)])
        assert a["tankdell"]["rosValue"] == b["tankdell"]["rosValue"] == 30.0

    def test_rows_without_a_name_are_skipped(self):
        assert build_value_index([{"rosValue": 10.0}]) == {}


# ── Eligibility index ──────────────────────────────────────────────


class TestNflPositionIndex:
    def test_carries_fantasy_positions(self):
        idx = build_nfl_position_index(dict([_nfl("1", "Javin", "White", "LB", ["DB", "LB"])]))
        assert idx["javinwhite"] == ("LB", ("DB", "LB"))

    def test_prefers_the_entry_that_has_eligibility(self):
        """The dump contains retired/duplicate shells with no
        fantasy_positions; those must not overwrite a good entry."""
        idx = build_nfl_position_index(
            dict(
                [
                    _nfl("1", "Javin", "White", "LB", ["DB", "LB"]),
                    _nfl("2", "Javin", "White", "LB", []),
                ]
            )
        )
        assert idx["javinwhite"][1] == ("DB", "LB")

    def test_falls_back_to_first_last_when_full_name_absent(self):
        idx = build_nfl_position_index(
            {
                "1": {
                    "first_name": "Nico",
                    "last_name": "Collins",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                }
            }
        )
        assert "nicocollins" in idx


# ── The join, and the defect it prevents ───────────────────────────


class TestBuildRosterPool:
    def test_hybrid_eligibility_reaches_the_optimizer(self):
        """MECHANISM TEST. Fails if fantasyPositions is dropped anywhere
        between the dump and the RosterPlayer rows.

        One DL/LB hybrid plus one pure DL, with a DL slot and an LB
        slot. Both slots fill ONLY when the hybrid is legal at LB.
        """
        values = build_value_index([_agg("Hybrid Guy", "DL", 30.0), _agg("Pure Dl", "DL", 28.0)])
        elig = build_nfl_position_index(
            dict(
                [
                    _nfl("1", "Hybrid", "Guy", "DL", ["DL", "LB"]),
                    _nfl("2", "Pure", "Dl", "DL", ["DL"]),
                ]
            )
        )
        rows, report = build_roster_pool(["Hybrid Guy", "Pure Dl"], values=values, eligibility=elig)
        assert report.hybrids_found == 1
        summary = solve_summary(to_roster_players(rows), ["DL", "LB"])
        assert summary.filled_slots == 2
        assert summary.score == pytest.approx(58.0)

    def test_without_eligibility_the_second_slot_goes_empty(self):
        """The defect, pinned. This is what the ROS-aggregate-only path
        produced, and why IDP marginals were a lower bound."""
        values = build_value_index([_agg("Hybrid Guy", "DL", 30.0), _agg("Pure Dl", "DL", 28.0)])
        rows, _ = build_roster_pool(["Hybrid Guy", "Pure Dl"], values=values, eligibility={})
        summary = solve_summary(to_roster_players(rows), ["DL", "LB"])
        assert summary.filled_slots == 1
        assert summary.score == pytest.approx(30.0)

    def test_dump_position_wins_over_the_aggregate(self):
        """The NFL dump is the host's own view; the aggregate is scraped
        from ranking sites that disagree on IDP labelling."""
        values = build_value_index([_agg("Edge Guy", "LB", 25.0)])
        elig = build_nfl_position_index(dict([_nfl("1", "Edge", "Guy", "DL", ["DL", "LB"])]))
        rows, _ = build_roster_pool(["Edge Guy"], values=values, eligibility=elig)
        assert rows[0]["position"] == "DL"
        assert rows[0]["fantasyPositions"] == ("DL", "LB")

    def test_unvalued_players_are_reported_not_silently_dropped(self):
        values = build_value_index([_agg("Known Guy", "WR", 40.0)])
        rows, report = build_roster_pool(
            ["Known Guy", "Ghost Player"], values=values, eligibility={}
        )
        assert len(rows) == 1
        assert report.rostered == 2 and report.valued == 1
        assert report.unmatched_names == ("Ghost Player",)
        assert report.value_join_rate == pytest.approx(0.5)

    def test_empty_roster_is_a_clean_zero(self):
        rows, report = build_roster_pool([], values={}, eligibility={})
        assert rows == []
        assert report.value_join_rate == 0.0


# ── Coverage audit ─────────────────────────────────────────────────


class TestHybridCoverage:
    def test_flags_multi_family_players_missing_eligibility(self):
        """The number that matters: a DL/LB/DB-family player with no
        fantasy_positions may be benched illegally."""
        cov = hybrid_coverage(
            [
                {"position": "DL", "fantasyPositions": ()},
                {"position": "LB", "fantasyPositions": ("DL", "LB")},
                {"position": "WR", "fantasyPositions": ()},
            ]
        )
        assert cov.multi_family == 2
        assert cov.multi_family_with_eligibility == 1
        assert cov.multi_family_without_eligibility == 1
        assert cov.eligibility_complete is False
        assert cov.true_hybrids == 1

    def test_complete_when_every_idp_carries_eligibility(self):
        cov = hybrid_coverage(
            [
                {"position": "DL", "fantasyPositions": ("DL",)},
                {"position": "DB", "fantasyPositions": ("DB", "LB")},
            ]
        )
        assert cov.eligibility_complete is True
        assert cov.multi_family_without_eligibility == 0

    def test_offense_only_pool_is_trivially_complete(self):
        cov = hybrid_coverage([{"position": "WR", "fantasyPositions": ()}])
        assert cov.multi_family == 0
        assert cov.eligibility_complete is True


# ── The lineup consequence, end to end ─────────────────────────────


class TestEligibilityChangesMarginals:
    def test_enrichment_never_lowers_the_lineup_score(self):
        """Widening eligibility can only expand the optimizer's feasible
        set, so the optimal score is monotonically non-decreasing. A
        drop would mean the optimizer is not optimal."""
        # Three DL-POSITION players, one of them LB-eligible, against
        # DL/DL/LB slots. Position-only leaves the LB slot empty; with
        # eligibility the hybrid fills it. A fixture where every slot
        # already fills both ways proves nothing.
        values = build_value_index(
            [
                _agg("Hybrid A", "DL", 30.0),
                _agg("Pure Dl", "DL", 28.0),
                _agg("Other Dl", "DL", 26.0),
            ]
        )
        elig = build_nfl_position_index(
            dict(
                [
                    _nfl("1", "Hybrid", "A", "DL", ["DL", "LB"]),
                    _nfl("2", "Pure", "Dl", "DL", ["DL"]),
                    _nfl("3", "Other", "Dl", "DL", ["DL"]),
                ]
            )
        )
        names = ["Hybrid A", "Pure Dl", "Other Dl"]
        slots = ["DL", "DL", "LB"]

        after_rows, _ = build_roster_pool(names, values=values, eligibility=elig)
        before_rows = [{**r, "fantasyPositions": ()} for r in after_rows]

        before = position_marginals(to_roster_players(before_rows), slots).lineup_score
        after = position_marginals(to_roster_players(after_rows), slots).lineup_score
        assert after >= before
        assert after > before  # this fixture is constructed to improve
