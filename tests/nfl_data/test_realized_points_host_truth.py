"""B7 / W18-F003 — realized points measured against the LEAGUE HOST.

WHY THIS FILE EXISTS
--------------------
``src/league_intel/scorer.py::score_stat_line`` is validated against
Sleeper's own ``players_points`` (``tests/league_intel/test_golden_scoring.py``,
1,339 player-weeks, max |Δ| 0.0050) and has one non-test caller.
``src/nfl_data/realized_points.py::compute_weekly_points`` reaches every
production consumer of realized points and **has no host-truth test at
all**.  That absence is the finding, not a gap in coverage: every
existing test of the production engine asserts against hand-computed
expectations written in the same vocabulary the engine reads, so a
column the feed stopped publishing looks correct from inside.

Each test below pins ONE root cause with the host's own arithmetic, and
each is expected to FAIL until the B7 repair lands.  They are written
against real committed fixtures and the real live scoring card — no
synthetic rates, because a synthetic rate cannot show that the engine
disagrees with the league.

Fixtures: ``docs/master-site-audit/evidence/W18/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nfl_data.realized_points import compute_weekly_points
from src.nfl_data.scoring_coverage import Coverage, audit_scoring_settings, classify

EVIDENCE = Path(__file__).resolve().parents[2] / "docs" / "master-site-audit" / "evidence" / "W18"

#: The three columns the 2025 unified nflverse release renamed.  The
#: engine still asks for the left-hand name; the feed only publishes the
#: right-hand one, so ``stat_row.get`` returns ``None`` -> 0.0 and the
#: rule is skipped in silence.
RENAMED_COLUMNS = {
    "interceptions": "passing_interceptions",
    "sacks": "sacks_suffered",
    "fumbles_lost": "fumbles_lost_total",
}


def _live_card(league_file: str) -> dict:
    doc = json.loads((EVIDENCE / league_file).read_text(encoding="utf-8"))
    return doc.get("scoring_settings") or {}


@pytest.fixture(scope="module")
def dynasty_main_card() -> dict:
    return _live_card("sleeper_league_1312006700437352448.json")


@pytest.fixture(scope="module")
def dynasty_new_card() -> dict:
    return _live_card("sleeper_league_dynasty_new.json")


class TestRenamedColumnsStillScore:
    """The same football, spelled the way the live feed spells it."""

    def test_penalties_are_charged_under_live_column_names(self, dynasty_main_card):
        base = {
            "passing_yards": 300,
            "passing_tds": 2,
            "completions": 25,
            "attempts": 35,
            "rushing_yards": 20,
            "carries": 4,
        }
        legacy = dict(base, interceptions=3, sacks=2, fumbles_lost=1)
        live = dict(base, passing_interceptions=3, sacks_suffered=2, fumbles_lost_total=1)

        legacy_pts = compute_weekly_points(legacy, dynasty_main_card, position="QB")
        live_pts = compute_weekly_points(live, dynasty_main_card, position="QB")

        # The rules are worth real points on the live card: -4 / -1 / -4.
        expected_penalty = (
            3 * dynasty_main_card["pass_int"]
            + 2 * dynasty_main_card["pass_sack"]
            + 1 * dynasty_main_card["fum_lost"]
        )
        assert expected_penalty < 0

        assert live_pts.fantasy_points == pytest.approx(legacy_pts.fantasy_points, abs=1e-6), (
            "the same football scored differently depending on how the feed spells "
            f"its columns: legacy={legacy_pts.fantasy_points:.2f} "
            f"live={live_pts.fantasy_points:.2f}; the live row is missing "
            f"{abs(expected_penalty):.2f} points of penalties"
        )

    @pytest.mark.parametrize(("dead", "live"), sorted(RENAMED_COLUMNS.items()))
    def test_each_renamed_column_is_read(self, dynasty_main_card, dead, live):
        """A rule the card pays for must respond to the column the feed ships."""
        row = {"passing_yards": 100, live: 2}
        scored = compute_weekly_points(row, dynasty_main_card, position="QB")
        baseline = compute_weekly_points({"passing_yards": 100}, dynasty_main_card, position="QB")
        assert scored.fantasy_points != pytest.approx(
            baseline.fantasy_points, abs=1e-6
        ), f"{live!r} changed nothing — the engine only reads the retired {dead!r}"


class TestFirstDownBonusMatchesHost:
    """Sleeper EXCLUDES touchdown plays from pass_fd/rush_fd/rec_fd.

    nflverse's ``*_first_downs`` INCLUDE them, so the position-scoped
    first-down bonus over-charges by exactly the player's touchdown
    count — an over-statement, opposite in sign to the other defects,
    which is why a partial repair makes some positions worse.
    """

    @pytest.mark.parametrize(
        ("player_id", "name", "position", "bonus_key"),
        [("4984", "Josh Allen", "QB", "bonus_fd_qb")],
    )
    def test_engine_first_down_count_matches_host(
        self, dynasty_main_card, player_id, name, position, bonus_key
    ):
        host = json.loads((EVIDENCE / "sleeper_stats_2025_wk14.json").read_text(encoding="utf-8"))
        line = host.get(player_id) or {}
        assert line, f"fixture missing {name}"

        host_first_downs = float(line["bonus_fd_qb"])
        touchdowns = float(line.get("pass_td", 0)) + float(line.get("rush_td", 0))
        # The host's own bonus stat agrees with its own play-type counts,
        # which is what establishes that it excludes scoring plays.
        assert host_first_downs == pytest.approx(
            float(line.get("pass_fd", 0)) + float(line.get("rush_fd", 0)), abs=1e-6
        )
        assert touchdowns > 0, "fixture must include a scoring player to be meaningful"

        # The same week as nflverse spells it: first-down columns with TD
        # plays folded in.  Only first-down inputs, so the breakdown line
        # under test is isolated.
        nflverse_row = {
            "passing_first_downs": float(line.get("pass_fd", 0)) + float(line.get("pass_td", 0)),
            "rushing_first_downs": float(line.get("rush_fd", 0)) + float(line.get("rush_td", 0)),
            "passing_tds": float(line.get("pass_td", 0)),
            "rushing_tds": float(line.get("rush_td", 0)),
        }
        result = compute_weekly_points(
            nflverse_row, {bonus_key: dynasty_main_card[bonus_key]}, position=position
        )
        counted = next(
            (stat for (label, stat, _pts) in result.breakdown if label == "First Downs"),
            None,
        )
        assert counted is not None, "engine emitted no First Downs line"
        assert counted == pytest.approx(host_first_downs, abs=1e-6), (
            f"{name}: engine counts {counted:.0f} first downs where the host counts "
            f"{host_first_downs:.0f} — over by exactly the {touchdowns:.0f} touchdowns, "
            "because nflverse includes scoring plays and Sleeper does not"
        )


class TestCoverageAuditorIsNotFooled:
    """The guard must not be defeated by the defect it exists to catch.

    ``engine_reads_key`` probes with ``_MAXIMAL_ROW``.  While that row
    was written only in the engine's own vocabulary, a rule mapped to a
    column the feed no longer published read as SCORED — behaviourally
    true of the probe, factually false of every production row — and the
    audit reported an empty gap set.

    The durable requirement is therefore about the PROBE, not about any
    one key: the probe must be written in the vocabulary the feed ships,
    so this guard catches the NEXT rename instead of ratifying it. A test
    asserting "``pass_int`` is not SCORED" would only encode the symptom,
    and would go false the moment the mapping is repaired.
    """

    @pytest.mark.parametrize(("dead", "live"), sorted(RENAMED_COLUMNS.items()))
    def test_the_probe_row_speaks_the_feeds_vocabulary(self, dead, live):
        from src.nfl_data.scoring_coverage import _MAXIMAL_ROW

        assert live in _MAXIMAL_ROW, (
            f"the probe row does not carry {live!r} — the name the live feed "
            f"publishes — so a rule mapped only to the retired {dead!r} would be "
            "classified SCORED and no gap would ever be reported"
        )

    @pytest.mark.parametrize("key", ["pass_int", "pass_sack", "fum_lost"])
    def test_a_repaired_rule_scores_from_the_live_column_alone(self, key, dynasty_main_card):
        """SCORED must be earned on a row the feed could actually produce."""
        column = {
            "pass_int": "passing_interceptions",
            "pass_sack": "sacks_suffered",
            "fum_lost": "fumbles_lost_total",
        }[key]
        row = {"passing_yards": 100, column: 2}
        with_rule = compute_weekly_points(row, {key: dynasty_main_card[key]}, position="QB")
        without = compute_weekly_points(row, {}, position="QB")
        assert with_rule.fantasy_points != pytest.approx(without.fantasy_points, abs=1e-6), (
            f"{key!r} scored nothing from {column!r}, the only spelling the 2025 "
            "unified release publishes"
        )
        assert classify(key) is Coverage.SCORED


class TestEveryNonzeroRuleIsAccountedFor:
    """The structural requirement W18-F003 asks for, on BOTH live cards.

    ``dynasty_new`` is included deliberately: it is absent from the CI
    fixture today, and its card yields empty gap AND empty unscorable
    sets — zero disclosure of anything.
    """

    @pytest.mark.parametrize("league", ["dynasty_main", "dynasty_new"])
    def test_no_nonzero_rule_is_silently_dropped(self, league, request):
        card = request.getfixturevalue(f"{league}_card")
        assert card, f"{league} card fixture is empty"
        audit = audit_scoring_settings(card)
        accounted = (
            set(audit[Coverage.SCORED])
            | set(audit[Coverage.NOT_APPLICABLE])
            | set(audit[Coverage.UNSCORABLE])
        )
        gaps = set(audit[Coverage.GAP])
        nonzero = {
            k
            for k, v in card.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v != 0
        }
        unaccounted = nonzero - accounted - gaps
        assert not unaccounted, f"{league}: {sorted(unaccounted)} classified as nothing"
        assert not gaps, (
            f"{league}: {sorted(gaps)} are scorable from data already on the feed "
            "and are not scored"
        )


class TestPlayerSpecialTeamsIsNotAnUnvaluedAssetClass:
    """``kr_yd`` / ``pr_yd`` / ``st_*`` are earned by RB, WR, TE and LB.

    They are currently classified NOT_APPLICABLE — the state reserved
    for team defense and kickers, asset classes this platform does not
    value — which suppresses them from ``describe_gaps`` AND from
    ``Provenance.inputGaps``.  DST's ``def_st_*`` / ``def_kr_*`` /
    ``def_pr_*`` keep that classification correctly.
    """

    @pytest.mark.parametrize("key", ["kr_yd", "pr_yd", "st_td", "st_tkl_solo"])
    def test_player_special_teams_is_not_not_applicable(self, key, dynasty_main_card):
        if not dynasty_main_card.get(key):
            pytest.skip(f"{key} is not paid on this card")
        assert classify(key) is not Coverage.NOT_APPLICABLE, (
            f"{key!r} is paid {dynasty_main_card[key]}/event to players this platform "
            "ranks and starts; NOT_APPLICABLE hides it from every disclosure surface"
        )

    @pytest.mark.parametrize("key", ["def_st_td", "def_kr_yd", "def_pr_yd"])
    def test_dst_special_teams_stays_not_applicable(self, key, dynasty_main_card):
        if not dynasty_main_card.get(key):
            pytest.skip(f"{key} is not paid on this card")
        assert (
            classify(key) is Coverage.NOT_APPLICABLE
        ), f"{key!r} is a team-defense rule and this platform values no DST asset"
