"""Host-golden: Sleeper's ``idp_fum_rec`` is a DEFENSIVE opponent recovery.

The realized engine used to read ``fumble_recovery_own`` for the IDP
fumble-recovery rule.  For a defender, "own" is recovering HIS OWN team's
fumble (e.g. a teammate's botched interception return) — the host pays
nothing for it.  The host pays a defender for recovering the OFFENSE's
fumble, which nflverse files under ``fumble_recovery_opp`` — and that column
also counts special-teams recoveries, which the host pays under the separate
``st_fum_rec`` rule.

Measured on dynasty_main 2025 REG weeks 1-18 against the PUBLIC Sleeper API
(``docs/research/bdvm-v1/fumble-recovery-host-golden-2026-10-01/``):

* host ``idp_fum_rec`` == nflverse ``own`` on 21 / 244 IDP player-weeks,
  ``opp`` on 223 / 244, and ``opp − st_fum_rec`` on **244 / 244** — with the
  host's own ``st_fum_rec`` and with the play-by-play-derived one alike;
* host ``idp_fum_ret_yd`` == ``fumble_recovery_yards_opp`` on 63 / 65 (two
  per-play charting differences), ``_own`` on 0 / 65;
* the host pays both rules on its own stat line: ``players_points`` minus the
  line rescored without them equals the line scored with only them on
  7,140 / 7,140 rostered player-weeks.

The fixture is NUMBERS ONLY: the nflverse columns, the play-by-play special-
teams count, the host's stats, and the host-AWARDED contribution
(``players_points`` minus the no-fumble-recovery rescoring) for every rostered
IDP player-week with recovery activity on either side.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nfl_data import realized_points as rp
from src.nfl_data.realized_points import PBP_SUPPLEMENT_ROW_KEY

FIXTURE = Path(__file__).parent / "fixtures" / "idp_fumble_recovery_host_golden_2025.json"
DATA = json.loads(FIXTURE.read_text(encoding="utf-8"))
ROWS = DATA["rows"]
CARD = DATA["cardRates"]
TOL = DATA["tolerance"]


def _nflverse_row(fx: dict, *, with_pbp: bool) -> dict:
    row = {
        "season": 2025,
        "week": fx["week"],
        "position": fx["position"],
        "fumble_recovery_own": fx["fumble_recovery_own"],
        "fumble_recovery_opp": fx["fumble_recovery_opp"],
        "fumble_recovery_yards_own": fx["fumble_recovery_yards_own"],
        "fumble_recovery_yards_opp": fx["fumble_recovery_yards_opp"],
    }
    if with_pbp and fx["pbp_st_fum_rec"] is not None:
        st = fx["pbp_st_fum_rec"]
        row[PBP_SUPPLEMENT_ROW_KEY] = {"st_fum_rec": st} if st else {}
    return row


def test_fixture_is_discriminating():
    """Guard the guard: the fixture must contain every case that separates
    the candidate columns, or a wrong mapping could pass it."""
    assert len(ROWS) >= 80
    own_only = [r for r in ROWS if r["fumble_recovery_own"] and not r["fumble_recovery_opp"]]
    special_teams = [r for r in ROWS if r["host_st_fum_rec"] and r["fumble_recovery_opp"]]
    defensive = [r for r in ROWS if r["host_idp_fum_rec"]]
    assert own_only and all(r["host_idp_fum_rec"] == 0 for r in own_only)
    assert special_teams and all(r["host_idp_fum_rec"] == 0 for r in special_teams)
    assert len(defensive) >= 60


def test_fixture_host_rule_is_the_host_stat_times_the_card():
    """The host-awarded points ARE ``idp_fum_rec × rate + idp_fum_ret_yd × rate``
    on the host's own line — what the engine has to reproduce."""
    for fx in ROWS:
        expected = (
            fx["host_idp_fum_rec"] * CARD["idp_fum_rec"]
            + fx["host_idp_fum_ret_yd"] * CARD["idp_fum_ret_yd"]
        )
        assert fx["host_awarded_fr_points"] == pytest.approx(expected, abs=TOL)


def test_engine_reproduces_host_awarded_fumble_recovery_points():
    """RED against the ``fumble_recovery_own`` mapping (1 / 92 matched)."""
    misses = []
    for fx in ROWS:
        out = rp.compute_weekly_points(
            _nflverse_row(fx, with_pbp=True), dict(CARD), position=fx["position"]
        )
        got = out.fantasy_points if out else 0.0
        if abs(got - fx["host_awarded_fr_points"]) > TOL:
            misses.append((fx, got))
    assert not misses, f"{len(misses)}/{len(ROWS)} player-weeks miss the host: {misses[:3]}"


def test_without_play_by_play_special_teams_recoveries_are_inseparable():
    """No supplement → the weekly feed cannot split a special-teams recovery
    from a defensive one, so ``fumble_recovery_opp`` is taken whole.  Pinned so
    the one approximation the weekly-only path makes stays visible: every row
    matches except those where the host paid ``st_fum_rec`` instead, and those
    overpay by exactly the special-teams count at the IDP rate."""
    for fx in ROWS:
        out = rp.compute_weekly_points(
            _nflverse_row(fx, with_pbp=False), dict(CARD), position=fx["position"]
        )
        got = out.fantasy_points if out else 0.0
        st = fx["host_st_fum_rec"]
        assert got == pytest.approx(
            fx["host_awarded_fr_points"] + st * CARD["idp_fum_rec"], abs=TOL
        )


def test_own_recovery_scores_nothing_for_a_defender():
    row = {"season": 2025, "week": 1, "position": "LB", "fumble_recovery_own": 1}
    out = rp.compute_weekly_points(row, {"idp_fum_rec": 3.19}, position="LB")
    assert out.fantasy_points == 0.0


def test_host_vocabulary_count_is_taken_as_is_never_reduced_twice():
    """A row that already carries the host's own ``idp_fum_rec`` (the
    league-comparison translation keeps Sleeper's key) is ST-exclusive by the
    host's definition.  Subtracting the play-by-play special-teams count from
    it again would remove that recovery twice."""
    row = {
        "season": 2025,
        "week": 3,
        "position": "SAF",
        "idp_fum_rec": 1.0,
        "idp_fum_ret_yd": 12.0,
        PBP_SUPPLEMENT_ROW_KEY: {"st_fum_rec": 1.0},
    }
    out = rp.compute_weekly_points(row, {"idp_fum_rec": 3.0, "idp_fum_ret_yd": 0.1}, position="S")
    assert out.fantasy_points == pytest.approx(3.0 + 1.2)


def test_supplement_can_never_drive_the_count_negative():
    row = {
        "season": 2025,
        "week": 3,
        "position": "LB",
        "fumble_recovery_opp": 0,
        PBP_SUPPLEMENT_ROW_KEY: {"st_fum_rec": 1.0},
    }
    out = rp.compute_weekly_points(row, {"idp_fum_rec": 3.0}, position="LB")
    assert out.fantasy_points == 0.0


def test_idp_show_projected_recoveries_land_on_the_scored_column():
    """The IDP Show adapter mapped ``FR`` to ``fumble_recovery_own``, so every
    projected recovery scored zero under the corrected engine — the two must
    name the same column."""
    from src.bdvm.idpshow_projections import parse_projection_csv
    from src.bdvm.scoring import score_stat_line_per_game

    rows, report = parse_projection_csv("Player,Pos,Solo,Sacks,FR\nProbe Defender,LB,60,4,2\n")
    assert report["usable"], report
    stats = rows[0]["stats"]
    assert stats.get("fumble_recovery_opp") == 2.0
    assert "fumble_recovery_own" not in stats
    pts = score_stat_line_per_game(stats, {"idp_fum_rec": 3.0}, position="LB")
    assert pts == pytest.approx(6.0)


def test_league_comparison_translation_scores_the_host_count_once():
    """The Sleeper→nflverse translation renames the host's keys AND keeps the
    originals; the corrected engine must pay the host's own count exactly once
    even with a play-by-play supplement attached by the scoring engine."""
    from src.league_comparison.sleeper_stats import _translate_stats

    row = {
        "season": 2025,
        "week": 11,
        "position": "LB",
        **_translate_stats({"idp_fum_rec": 1.0, "idp_fum_ret_yd": 9.0, "st_fum_rec": 1.0}),
        PBP_SUPPLEMENT_ROW_KEY: {"st_fum_rec": 1.0},
    }
    out = rp.compute_weekly_points(row, {"idp_fum_rec": 3.0, "idp_fum_ret_yd": 0.1}, position="LB")
    breakdown = {label: pts for label, _stat, pts in out.breakdown}
    assert breakdown["FR"] == pytest.approx(3.0)
    assert breakdown["FR Ret Yds"] == pytest.approx(0.9)
