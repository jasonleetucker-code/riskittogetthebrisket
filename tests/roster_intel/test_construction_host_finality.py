"""An unfinalized host week is not a rules contradiction (production defect 2026-11-03).

Sleeper scores a best-ball week as its games end (its own ``last_scored_leg``
counts it) but awards the optimized lineups only once it stops displaying the
week (``/state/nfl`` ``display_week``).  On 2026-11-03 week 8 sat in between:
every team's recorded lineup was provisional, the contradiction test read that
as "the best-ball rule is contradicted", and the season gate withheld ALL of
2026 on the live page.

Fixture: the real dynasty_main 2026 weeks 1-7 (``dynasty_main_2026_w1_7.json``)
plus a week 8 built from week 7's rosters whose host lineups are NOT the
optimum (one starter swapped for a lower-scoring bench player of the same
position, score = the counted players) -- exactly the unfinalized shape.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.api import roster_construction_api as api
from src.public_league import player_impact as pi
from src.public_league.identity import ManagerRegistry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.roster_intel import construction as rc
from tests.roster_intel.rc_support import build_snapshot, league_of

FIX = Path(__file__).resolve().parent / "fixtures" / "dynasty_main_2026_w1_7.json"
STATE_W8_DISPLAYED = {"season": "2026", "season_type": "regular", "week": 9, "display_week": 8}


def _family(meta: dict) -> str:
    return str(meta.get("position") or "")


def _unfinalized_week(rows: list[dict], players: dict) -> list[dict]:
    """Week 7's rosters replayed as a provisional (non-optimal) week 8."""
    out = []
    for row in copy.deepcopy(rows):
        starters = [p for p in row["starters"] if p and p != "0"]
        pts = row["players_points"]
        bench = [p for p in row["players"] if p not in starters and p in pts]
        swapped = False
        for s in sorted(starters, key=lambda p: -pts.get(p, 0.0)):
            fam = _family(players.get(s, {}))
            lower = [
                b for b in bench if _family(players.get(b, {})) == fam and pts[b] < pts.get(s, 0.0)
            ]
            if lower:
                b = max(lower, key=lambda p: pts[p])
                row["starters"] = [b if p == s else p for p in row["starters"]]
                swapped = True
                break
        assert swapped, row["roster_id"]
        row["points"] = round(sum(pts[p] for p in row["starters"] if p and p != "0"), 2)
        out.append(row)
    return out


def _snapshot(raw: dict, *, slots_override: list[str] | None = None) -> PublicLeagueSnapshot:
    league = copy.deepcopy(raw["league"])
    league["league_id"] = "RC2026W8"
    league["settings"]["last_scored_leg"] = 8  # the host clock already counts week 8
    if slots_override is not None:
        league["roster_positions"] = slots_override + ["BN"] * 30
    weeks = {int(w): rows for w, rows in raw["matchupsByWeek"].items()}
    weeks[8] = _unfinalized_week(weeks[7], raw["players"])
    rids = sorted({r["roster_id"] for r in weeks[1]})
    season = SeasonSnapshot(
        season="2026",
        league_id="RC2026W8",
        league=league,
        users=[],
        rosters=[{"roster_id": rid, "owner_id": "", "players": []} for rid in rids],
        matchups_by_week=weeks,
        transactions_by_week={},
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="RC2026W8",
        generated_at="2026-11-03T10:11:13+00:00",
        seasons=[season],
        managers=ManagerRegistry(),
        nfl_players=raw["players"],
    )


@pytest.fixture(scope="module")
def snap():
    return _snapshot(json.loads(FIX.read_text(encoding="utf-8")))


def test_the_defect_week_8_alone_used_to_withhold_the_season(snap):
    season = snap.seasons[0]
    si = api.season_input_from_snapshot(snap, season)  # no host-finality rule
    assert {wk: list(r) for wk, r in si.contradicted.items()} == {8: [pi.CONTRA_BEST_BALL]}
    assert sorted(si.weeks) == list(range(1, 9))


def test_unfinalized_week_is_excluded_and_labelled_not_a_contradiction(snap):
    season = snap.seasons[0]
    finality = api.host_open_from_week(season, STATE_W8_DISPLAYED)
    assert finality == (8, api.R_HOST_WEEK_NOT_FINAL)
    si = api.season_input_from_snapshot(snap, season, host_finality=finality)
    assert sorted(si.weeks) == list(range(1, 8))
    assert si.contradicted == {}
    assert {"week": 8, "reason": "host_week_not_final"} in list(si.excluded_weeks)
    status = api.lineup_config_status(si, is_current=True)
    assert status["available"] is True and status["contradictedWeeksWithheld"] == []
    # Parity on the finalized weeks: 84/84 reproduce the host exactly.
    ls = rc.compute_league_season(si, api.load_priors())
    sols = [s for wk in ls.included_weeks for s in ls.solutions[wk].values()]
    assert len(sols) == 84
    assert all(s.valid and s.parity == rc.PARITY_REPRODUCED for s in sols)
    # The excluded week is never a zero: it is absent from production, and the
    # payload names it.
    payload = api.build_payload(
        ls,
        league_key="k",
        roster_id=1,
        value=rc.ValueInput(available=False, reason="x"),
        posture=None,
    )
    assert {"week": 8, "reason": "host_week_not_final"} in payload["coverage"]["weeksExcluded"]
    assert payload["coverage"]["weeksIncluded"] == list(range(1, 8))
    assert payload["team"]["validWeeks"] == list(range(1, 8))


def test_unreadable_host_state_withholds_only_the_newest_week(snap):
    season = snap.seasons[0]
    finality = api.host_open_from_week(season, None)
    assert finality == (None, api.R_HOST_WEEK_FINALITY_UNKNOWN)
    si = api.season_input_from_snapshot(snap, season, host_finality=finality)
    assert sorted(si.weeks) == list(range(1, 8))
    assert {"week": 8, "reason": "host_week_finality_unknown"} in list(si.excluded_weeks)
    assert api.lineup_config_status(si, is_current=True)["available"] is True


def test_a_finalized_slot_count_contradiction_still_withholds_the_season():
    raw = json.loads(FIX.read_text(encoding="utf-8"))
    seventeen = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "FLEX", "SUPER_FLEX", "K",
                 "DL", "DL", "LB", "LB", "DB", "DB"]  # fmt: skip
    snap = _snapshot(raw, slots_override=seventeen)
    season = snap.seasons[0]
    si = api.season_input_from_snapshot(
        snap, season, host_finality=api.host_open_from_week(season, STATE_W8_DISPLAYED)
    )
    status = api.lineup_config_status(si, is_current=True)
    assert status["available"] is False
    assert status["reason"] == api.R_LINEUP_CONFIG_UNVERIFIED
    assert status["contradictions"] == [pi.CONTRA_SLOT_COUNT]


def test_best_ball_contradicted_on_most_finalized_weeks_withholds_the_season():
    # The 2024 shape: the league says best ball, but the recorded lineups are
    # managed (the first N players, not the optimum) in every finalized week.
    snap = build_snapshot(
        league_of(4),
        best_ball=1,
        managed_starters=lambda rid, wk, roster: list(roster[:21]),
        status="complete",
    )
    season = snap.seasons[0]
    si = api.season_input_from_snapshot(
        snap, season, host_finality=api.host_open_from_week(season, STATE_W8_DISPLAYED)
    )
    assert len(si.contradicted) == len(si.weeks) > 0
    status = api.lineup_config_status(si, is_current=False)
    assert status["available"] is False
    assert status["reason"] == api.R_LINEUP_CONFIG_UNVERIFIED_HISTORICAL


def test_a_minority_finalized_best_ball_contradiction_is_withheld_per_week(snap):
    # Without the finality rule week 8 is a finalized-looking contradicted
    # week: one of eight is a minority, so the season is SERVED and week 8 alone
    # is withheld and labelled (owner decision D1: per observation).
    si = api.season_input_from_snapshot(snap, snap.seasons[0])
    status = api.lineup_config_status(si, is_current=True)
    assert status["available"] is True and status["contradictedWeeksWithheld"] == [8]
    ls = rc.compute_league_season(si, api.load_priors())
    assert all(s.reason == rc.X_CONTRADICTED for s in ls.solutions[8].values())


@pytest.mark.parametrize(
    "state, expected",
    [
        ({"season": "2027", "display_week": 1}, (None, None)),  # a past season is final
        ({"season": "2026", "display_week": 8}, (8, "host_week_not_final")),
        ({"season": "2025", "display_week": 18}, (1, "host_week_not_final")),
        ({"season": "2026", "display_week": None}, (None, "host_week_finality_unknown")),
        ({"season": "2026", "display_week": "x"}, (None, "host_week_finality_unknown")),
        ({"season": "", "display_week": 8}, (None, "host_week_finality_unknown")),
        (None, (None, "host_week_finality_unknown")),
    ],
)
def test_host_open_from_week(snap, state, expected):
    assert api.host_open_from_week(snap.seasons[0], state) == expected


def test_a_complete_season_is_final_whatever_the_state_says():
    s = build_snapshot(league_of(2), status="complete").seasons[0]
    assert api.host_open_from_week(s, None) == (None, None)
    assert api.host_open_from_week(s, {"season": "2025", "display_week": 3}) == (None, None)
