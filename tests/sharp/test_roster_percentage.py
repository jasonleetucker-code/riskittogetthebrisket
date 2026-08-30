"""Sharp Roster Percentage — the counting rules, in executable form.

The audit checklist this feature shipped against is encoded here:
one observation per roster per player, a denominator that is eligible
ROSTERS, filters that move numerator and denominator together, trends
that refuse to compare unlike populations, and a cohort that is shared
with the Buy/Sell Tracker rather than redefined.
"""

from __future__ import annotations

import pytest

from src.sharp import cohort
from src.sharp import market as sharp_market
from src.sharp import roster_percentage as rp
from src.sharp import roster_store as rs

NOW = 1_800_000_000_000
DAY = 86_400_000

OFFENSE_ONLY = {"idp": False, "kicker": True, "superflex": True, "tePremium": False}
IDP_LEAGUE = {"idp": True, "kicker": True, "superflex": True, "tePremium": True}
ONE_QB = {"idp": False, "kicker": True, "superflex": False, "tePremium": False}

CONTRACT = {
    "playersArray": [
        {
            "playerId": "wr1",
            "displayName": "Star Receiver",
            "position": "WR",
            "team": "MIN",
            "rankDerivedValue": 9500,
            "canonicalConsensusRank": 2,
        },
        {
            "playerId": "rb1",
            "displayName": "Good Back",
            "position": "RB",
            "team": "ATL",
            "rankDerivedValue": 8000,
            "canonicalConsensusRank": 12,
        },
        {
            "playerId": "lb1",
            "displayName": "Star Linebacker",
            "position": "LB",
            "team": "SF",
            "rankDerivedValue": 5000,
            "canonicalConsensusRank": 90,
        },
        {
            "playerId": "rook1",
            "displayName": "Fresh Rookie",
            "position": "WR",
            "team": "LAR",
            "rankDerivedValue": 6000,
            "canonicalConsensusRank": 45,
            "rookie": True,
        },
    ]
}


def member(key: str) -> cohort.CohortMember:
    return cohort.CohortMember(key, key.split(":", 1)[0], "automated_qualified", 0.9)


@pytest.fixture
def cohort_of(monkeypatch):
    """Pin the sharp pool so these tests measure COUNTING, not qualification.

    Qualification has its own tests (``test_score.py``); mixing the two
    would make a scoring-threshold change break arithmetic assertions.
    """

    def _install(keys):
        members = [member(k) for k in keys]
        monkeypatch.setattr(
            rp.sharp_cohort,
            "cohort_members",
            lambda **kwargs: (members, {"methodologyVersion": "sharp-v2"}),
        )
        monkeypatch.setattr(
            rp.sharp_cohort,
            "unique_person_count",
            lambda manager_keys, **kwargs: len(set(manager_keys)),
        )
        return members

    return _install


def roster(manager, league, roster_id="1", assets=(), fmt=None, observed=NOW, **kwargs):
    return rs.RosterObservation(
        platform=kwargs.pop("platform", "sleeper"),
        league_key=league,
        manager_key=manager,
        source_roster_id=roster_id,
        assets=[a if isinstance(a, rs.RosterAsset) else rs.RosterAsset(a) for a in assets],
        league_format=fmt if fmt is not None else OFFENSE_ONLY,
        observed_ms=observed,
        **kwargs,
    )


def board(ledger, **kwargs):
    kwargs.setdefault("contract", CONTRACT)
    kwargs.setdefault("now_ms", NOW)
    kwargs.setdefault("limit", 100)
    return rp.build_board(ledger_path=ledger, **kwargs)


def row_for(payload, name):
    return next((r for r in payload["players"] if r["displayName"] == name), None)


@pytest.fixture
def ledger(tmp_path):
    return tmp_path / "ledger.sqlite3"


# ── the formula ──────────────────────────────────────────────────────


def test_percentage_is_holding_rosters_over_eligible_rosters(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 5)])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1", "rb1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1", "rb1"]),
            roster("sleeper:u3", "sleeper:L3", assets=["wr1"]),
            roster("sleeper:u4", "sleeper:L4", assets=["wr1"]),
        ],
        path=ledger,
    )
    payload = board(ledger)
    wr = row_for(payload, "Star Receiver")
    rb = row_for(payload, "Good Back")
    assert (wr["sharpRosters"], wr["eligibleRosters"], wr["sharpRosterPct"]) == (4, 4, 1.0)
    assert (rb["sharpRosters"], rb["eligibleRosters"], rb["sharpRosterPct"]) == (2, 4, 0.5)


def test_denominator_equals_the_eligible_roster_count(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 4)])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"]),
            roster("sleeper:u3", "sleeper:L3", assets=["wr1"], exclusion_reasons=["best_ball"]),
        ],
        path=ledger,
    )
    payload = board(ledger)
    assert payload["sample"]["eligibleRosters"] == 2
    assert row_for(payload, "Star Receiver")["eligibleRosters"] == 2
    assert payload["exclusions"]["byReason"] == {"best_ball": 1}


def test_one_manager_many_leagues_contributes_one_roster_each(ledger, cohort_of):
    """Five real dynasty teams are five roster observations, one person."""
    cohort_of(["sleeper:u1"])
    rs.record_rosters(
        [roster("sleeper:u1", f"sleeper:L{i}", assets=["wr1"]) for i in range(1, 6)],
        path=ledger,
    )
    payload = board(ledger)
    assert payload["sample"]["eligibleRosters"] == 5
    assert row_for(payload, "Star Receiver")["sharpRosters"] == 5
    assert payload["transparency"]["uniqueSharpManagers"] == 1
    assert payload["transparency"]["rostersPerManager"] == 5.0
    # W15-F009 (inv 4.6): the pool-level stat above already proves this is
    # one person, but nothing on the PER-PLAYER row said so until this
    # field existed — an 83%-style number could read as five independent
    # opinions with no local signal otherwise.
    row = row_for(payload, "Star Receiver")
    assert row["distinctManagers"] == 1
    assert row["managerConcentration"] == 1.0


def test_manager_concentration_reflects_independent_holders_not_just_roster_count(
    ledger, cohort_of
):
    """Four managers, four rosters, one each: concentration is low, not undefined."""
    cohort_of([f"sleeper:u{i}" for i in range(1, 5)])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1", "rb1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1", "rb1"]),
            roster("sleeper:u3", "sleeper:L3", assets=["wr1"]),
            roster("sleeper:u4", "sleeper:L4", assets=["wr1"]),
        ],
        path=ledger,
    )
    payload = board(ledger)
    wr = row_for(payload, "Star Receiver")
    rb = row_for(payload, "Good Back")
    # wr1: 4 holding rosters, 4 distinct managers, nobody dominates.
    assert wr["distinctManagers"] == 4
    assert wr["managerConcentration"] == 0.25
    # rb1: 2 holding rosters (u1, u2), 2 distinct managers, still even.
    assert rb["distinctManagers"] == 2
    assert rb["managerConcentration"] == 0.5


def test_manager_concentration_flags_one_person_behind_several_rosters(ledger, cohort_of):
    """One manager's two leagues plus two independent managers: NOT three opinions."""
    cohort_of(["sleeper:u1", "sleeper:u2", "sleeper:u3"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u1", "sleeper:L2", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L3", assets=["wr1"]),
            roster("sleeper:u3", "sleeper:L4", assets=["wr1"]),
        ],
        path=ledger,
    )
    payload = board(ledger)
    wr = row_for(payload, "Star Receiver")
    assert wr["sharpRosters"] == 4
    assert wr["distinctManagers"] == 3
    # u1 holds 2 of the 4 counted rosters -> the single-manager ceiling is 0.5,
    # not 0.25 (1/4), which is what a roster-only count would imply.
    assert wr["managerConcentration"] == 0.5


def test_a_player_counts_once_per_roster_even_across_slots(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters(
        [
            roster(
                "sleeper:u1",
                "sleeper:L1",
                assets=[
                    rs.RosterAsset("wr1", slot=rs.SLOT_ACTIVE),
                    rs.RosterAsset("wr1", slot=rs.SLOT_TAXI),
                ],
            )
        ],
        path=ledger,
    )
    wr = row_for(board(ledger), "Star Receiver")
    assert wr["sharpRosters"] == 1
    assert wr["sharpRosterPct"] == 1.0


def test_taxi_and_reserve_players_still_count_as_rostered(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=[rs.RosterAsset("wr1", slot=rs.SLOT_TAXI)]),
            roster(
                "sleeper:u2", "sleeper:L2", assets=[rs.RosterAsset("wr1", slot=rs.SLOT_RESERVE)]
            ),
        ],
        path=ledger,
    )
    wr = row_for(board(ledger), "Star Receiver")
    assert wr["sharpRosterPct"] == 1.0
    assert wr["slots"] == {"taxi": 1, "reserve": 1}


# ── per-player denominator ───────────────────────────────────────────


def test_idp_players_are_measured_against_idp_leagues_only(ledger, cohort_of):
    """The finding that makes this board honest.

    Dividing a linebacker by every sharp roster would report 20% for a
    player owned in every league that can roster him.
    """
    cohort_of([f"sleeper:u{i}" for i in range(1, 6)])
    rs.record_rosters(
        [roster(f"sleeper:u{i}", f"sleeper:L{i}", assets=["wr1"]) for i in range(1, 4)]
        + [
            roster("sleeper:u4", "sleeper:L4", assets=["wr1", "lb1"], fmt=IDP_LEAGUE),
            roster("sleeper:u5", "sleeper:L5", assets=["wr1", "lb1"], fmt=IDP_LEAGUE),
        ],
        path=ledger,
    )
    payload = board(ledger)
    lb = row_for(payload, "Star Linebacker")
    assert (lb["sharpRosters"], lb["eligibleRosters"], lb["sharpRosterPct"]) == (2, 2, 1.0)
    assert row_for(payload, "Star Receiver")["eligibleRosters"] == 5


def test_a_holding_roster_is_always_inside_its_own_denominator(ledger, cohort_of):
    """A percentage can never exceed 100% through unknown formats."""
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            # Format never captured, yet the roster demonstrably holds an IDP.
            roster("sleeper:u1", "sleeper:L1", assets=["lb1"], fmt={}),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"], fmt=IDP_LEAGUE),
        ],
        path=ledger,
    )
    lb = row_for(board(ledger), "Star Linebacker")
    assert lb["sharpRosters"] <= lb["eligibleRosters"]
    assert lb["sharpRosterPct"] <= 1.0


def test_small_player_denominator_is_flagged_individually(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 11)])
    rs.record_rosters(
        [roster(f"sleeper:u{i}", f"sleeper:L{i}", assets=["wr1"]) for i in range(1, 10)]
        + [roster("sleeper:u10", "sleeper:L10", assets=["wr1", "lb1"], fmt=IDP_LEAGUE)],
        path=ledger,
    )
    payload = board(ledger)
    assert row_for(payload, "Star Linebacker")["sampleWarning"]["level"] == "insufficient"
    assert row_for(payload, "Star Receiver")["sampleWarning"] is None


# ── filters ──────────────────────────────────────────────────────────


def _twelve_rosters():
    """Six superflex/TEP rosters and six one-QB rosters; all hold wr1."""
    out = []
    for i in range(1, 13):
        fmt = IDP_LEAGUE if i <= 6 else ONE_QB
        assets = ["wr1"] + (["rb1"] if i <= 6 else [])
        out.append(
            roster(
                f"sleeper:u{i}",
                f"sleeper:L{i}",
                assets=assets,
                fmt=fmt,
                contention="contending" if i % 2 else "rebuilding",
            )
        )
    return out


def test_format_filter_moves_numerator_and_denominator_together(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 13)])
    rs.record_rosters(_twelve_rosters(), path=ledger)

    every = board(ledger)
    assert row_for(every, "Good Back")["sharpRosters"] == 6
    assert row_for(every, "Good Back")["eligibleRosters"] == 12

    superflex = board(ledger, league_format="superflex")
    assert superflex["sample"]["eligibleRosters"] == 6
    assert row_for(superflex, "Good Back")["sharpRosterPct"] == 1.0

    one_qb = board(ledger, league_format="oneQb")
    assert one_qb["sample"]["eligibleRosters"] == 6
    assert row_for(one_qb, "Good Back") is None  # nobody in a 1QB league holds him


def test_contention_filter_reduces_both_sides(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 13)])
    rs.record_rosters(_twelve_rosters(), path=ledger)
    contending = board(ledger, contention="contending")
    assert contending["sample"]["eligibleRosters"] == 6
    assert row_for(contending, "Star Receiver")["eligibleRosters"] == 6


def test_platform_filter_selects_one_source(ledger, cohort_of):
    cohort_of(["sleeper:u1", "ffpc:f1"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("ffpc:f1", "ffpc:F1", assets=["wr1"], platform="ffpc"),
        ],
        path=ledger,
    )
    assert board(ledger, platform="ffpc")["sample"]["eligibleRosters"] == 1
    assert board(ledger, platform="sleeper")["sample"]["eligibleRosters"] == 1
    assert board(ledger)["transparency"]["ffpcRosters"] == 1


def test_position_filter_selects_players_without_shrinking_the_pool(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 13)])
    rs.record_rosters(_twelve_rosters(), path=ledger)
    only_rb = board(ledger, position="RB")
    assert [r["displayName"] for r in only_rb["players"]] == ["Good Back"]
    assert only_rb["sample"]["eligibleRosters"] == 12


def test_experience_filter_splits_rookies_from_veterans(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters([roster("sleeper:u1", "sleeper:L1", assets=["wr1", "rook1"])], path=ledger)
    assert [r["displayName"] for r in board(ledger, experience="rookies")["players"]] == [
        "Fresh Rookie"
    ]
    assert "Fresh Rookie" not in [
        r["displayName"] for r in board(ledger, experience="veterans")["players"]
    ]


def test_picks_are_excluded_from_the_default_player_pool(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters(
        [roster("sleeper:u1", "sleeper:L1", assets=["wr1", "pick:2027:1"])], path=ledger
    )
    assert [r["assetId"] for r in board(ledger)["players"]] == ["wr1"]
    assert "pick:2027:1" in [r["assetId"] for r in board(ledger, include_picks=True)["players"]]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"position": "nonsense"},
        {"platform": "yahoo"},
        {"league_format": "dynasty"},
        {"contention": "tanking"},
        {"experience": "sophomores"},
        {"sort": "vibes"},
        {"limit": 37},
    ],
)
def test_unsupported_filter_values_are_rejected(ledger, cohort_of, kwargs):
    cohort_of(["sleeper:u1"])
    with pytest.raises(ValueError):
        board(ledger, **kwargs)


def test_limit_selects_the_documented_list_sizes(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 13)])
    rs.record_rosters(_twelve_rosters(), path=ledger)
    assert len(board(ledger, limit=1 if False else 25)["players"]) <= 25
    everything = board(ledger, limit=0)
    assert len(everything["players"]) == everything["totalQualifyingPlayers"]


# ── eligibility ──────────────────────────────────────────────────────


def test_a_manager_who_left_the_cohort_stops_contributing(ledger, cohort_of):
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:gone", "sleeper:L2", assets=["wr1", "rb1"]),
        ],
        path=ledger,
    )
    cohort_of(["sleeper:u1"])
    payload = board(ledger)
    assert payload["sample"]["eligibleRosters"] == 1
    assert payload["exclusions"]["byReason"]["manager_no_longer_in_cohort"] == 1
    assert row_for(payload, "Good Back") is None


def test_stale_rosters_are_excluded_with_a_reason(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"], observed=NOW - 60 * DAY),
        ],
        path=ledger,
    )
    payload = board(ledger)
    assert payload["sample"]["eligibleRosters"] == 1
    assert payload["exclusions"]["byReason"]["stale_roster_data"] == 1


def test_collector_exclusion_reasons_survive_to_the_payload(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters(
        [
            roster(
                "sleeper:u1",
                "sleeper:L1",
                assets=["wr1"],
                exclusion_reasons=["abandoned_or_inactive_league"],
            )
        ],
        path=ledger,
    )
    payload = board(ledger)
    assert payload["exclusions"]["byReason"] == {"abandoned_or_inactive_league": 1}
    assert payload["status"] == "no_eligible_rosters"


# ── sample-size safeguards ───────────────────────────────────────────


def test_a_tiny_cohort_is_labelled_not_ranked(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"]),
        ],
        path=ledger,
    )
    payload = board(ledger)
    assert payload["sample"]["rankable"] is False
    assert payload["sample"]["warning"]["level"] == "insufficient"


def test_a_mid_sized_cohort_gets_the_directional_wording(ledger, cohort_of):
    keys = [f"sleeper:u{i}" for i in range(1, 15)]
    cohort_of(keys)
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"]) for i, k in enumerate(keys)], path=ledger
    )
    warning = board(ledger)["sample"]["warning"]
    assert warning["level"] == "directional"
    assert "Based on 14 eligible sharp rosters" in warning["message"]
    assert "directional" in warning["message"]


def test_a_large_cohort_carries_no_warning(ledger, cohort_of):
    keys = [f"sleeper:u{i}" for i in range(1, 46)]
    cohort_of(keys)
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"]) for i, k in enumerate(keys)], path=ledger
    )
    payload = board(ledger)
    assert payload["sample"]["warning"] is None
    assert payload["sample"]["rankable"] is True


# ── trends ───────────────────────────────────────────────────────────


def test_thirty_day_trend_measures_the_shared_roster_population(ledger, cohort_of):
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    then = NOW - 40 * DAY
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"], observed=then) for i, k in enumerate(keys)],
        path=ledger,
    )
    rs.record_rosters(
        [
            roster(k, f"sleeper:L{i}", assets=["wr1"] + (["rb1"] if i < 4 else []))
            for i, k in enumerate(keys)
        ],
        path=ledger,
    )
    trend = row_for(board(ledger), "Good Back")["trend"]["thirtyDay"]
    assert trend["available"] is True
    assert trend["comparableRosters"] == 10
    assert trend["rostersAdded"] == 4
    assert trend["rostersDropped"] == 0
    assert trend["rosterPctChange"] == pytest.approx(0.4)


def test_trend_is_withheld_when_the_population_moved_materially(ledger, cohort_of):
    """A grown cohort must not read as players gaining ownership."""
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    rs.record_rosters(
        [roster("sleeper:u1", "sleeper:L1", assets=["wr1"], observed=NOW - 40 * DAY)], path=ledger
    )
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"]) for i, k in enumerate(keys)], path=ledger
    )
    trend = row_for(board(ledger), "Star Receiver")["trend"]["thirtyDay"]
    assert trend["available"] is False
    assert trend["reason"] == "roster_population_changed"


def test_a_dropped_player_shows_a_negative_trend(ledger, cohort_of):
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    rs.record_rosters(
        [
            roster(k, f"sleeper:L{i}", assets=["wr1", "rb1"], observed=NOW - 40 * DAY)
            for i, k in enumerate(keys)
        ],
        path=ledger,
    )
    rs.record_rosters(
        [
            roster(k, f"sleeper:L{i}", assets=["wr1"] + (["rb1"] if i < 5 else []))
            for i, k in enumerate(keys)
        ],
        path=ledger,
    )
    trend = row_for(board(ledger), "Good Back")["trend"]["thirtyDay"]
    assert trend["rostersDropped"] == 5
    assert trend["rosterPctChange"] == pytest.approx(-0.5)


def test_every_owner_stated_window_is_published(ledger, cohort_of):
    """The owner's windows are 7 / 14 / 30 day.  The 14-day baseline was
    simply absent; season-to-date is kept alongside them because it answers
    a different question."""
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"]) for i, k in enumerate(keys)], path=ledger
    )
    trend = row_for(board(ledger), "Star Receiver")["trend"]
    assert {"sevenDay", "fourteenDay", "thirtyDay", "seasonToDate"} <= set(trend)


def test_the_fourteen_day_window_sees_a_change_the_seven_day_one_cannot(ledger, cohort_of):
    """A window has to actually LOOK BACK that far to be worth publishing.
    A move 10 days old is inside 14 days and outside 7."""
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    # Nobody holds the back 20 days ago; four managers hold him from 10 days
    # ago onward.  That move is INSIDE 14 days and OUTSIDE 7.
    rs.record_rosters(
        [
            roster(k, f"sleeper:L{i}", assets=["wr1"], observed=NOW - 20 * DAY)
            for i, k in enumerate(keys)
        ],
        path=ledger,
    )
    rs.record_rosters(
        [
            roster(
                k,
                f"sleeper:L{i}",
                assets=["wr1"] + (["rb1"] if i < 4 else []),
                observed=NOW - 10 * DAY,
            )
            for i, k in enumerate(keys)
        ],
        path=ledger,
    )
    trend = row_for(board(ledger), "Good Back")["trend"]
    assert trend["fourteenDay"]["available"] is True
    assert trend["fourteenDay"]["rostersAdded"] == 4
    assert trend["fourteenDay"]["rosterPctChange"] == pytest.approx(0.4)
    # The 7-day baseline already sees him held, so the shorter window
    # reports no change — which is the whole reason the 14-day one earns
    # its place rather than duplicating a neighbour.
    assert trend["sevenDay"]["available"] is True
    assert trend["sevenDay"]["rosterPctChange"] == pytest.approx(0.0)


def test_the_fourteen_day_window_withholds_on_a_moved_population_too(ledger, cohort_of):
    """The population-overlap guard is per-baseline, so the new window
    inherits it rather than needing its own rule."""
    keys = [f"sleeper:u{i}" for i in range(1, 11)]
    cohort_of(keys)
    rs.record_rosters(
        [roster("sleeper:u1", "sleeper:L1", assets=["wr1"], observed=NOW - 12 * DAY)], path=ledger
    )
    rs.record_rosters(
        [roster(k, f"sleeper:L{i}", assets=["wr1"]) for i, k in enumerate(keys)], path=ledger
    )
    trend = row_for(board(ledger), "Star Receiver")["trend"]["fourteenDay"]
    assert trend["available"] is False
    assert trend["reason"] == "roster_population_changed"


# ── market comparison ────────────────────────────────────────────────


def test_market_comparison_is_absent_and_says_so(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters([roster("sleeper:u1", "sleeper:L1", assets=["wr1"])], path=ledger)
    payload = board(ledger)
    assert payload["marketComparison"]["available"] is False
    assert (
        "no general-dynasty roster-percentage feed" in payload["marketComparison"]["note"].lower()
    )
    wr = row_for(payload, "Star Receiver")
    assert wr["marketRosterPct"] is None
    assert wr["sharpRosterAdvantage"] is None


def test_a_registered_market_provider_produces_the_advantage_column(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"]),
        ],
        path=ledger,
    )
    rp.set_market_ownership_provider(lambda ids: {"wr1": 0.6})
    try:
        wr = row_for(board(ledger), "Star Receiver")
        assert wr["marketRosterPct"] == 0.6
        assert wr["sharpRosterAdvantage"] == pytest.approx(0.4)
    finally:
        rp.set_market_ownership_provider(None)


def test_a_failing_market_provider_never_breaks_the_board(ledger, cohort_of):
    cohort_of(["sleeper:u1"])
    rs.record_rosters([roster("sleeper:u1", "sleeper:L1", assets=["wr1"])], path=ledger)

    def boom(_ids):
        raise RuntimeError("upstream down")

    rp.set_market_ownership_provider(boom)
    try:
        payload = board(ledger)
        assert payload["status"] == "ok"
        assert payload["marketComparison"]["available"] is False
    finally:
        rp.set_market_ownership_provider(None)


# ── sorting ──────────────────────────────────────────────────────────


def test_alternate_sorts_change_the_ordering(ledger, cohort_of):
    cohort_of([f"sleeper:u{i}" for i in range(1, 11)])
    rs.record_rosters(
        [
            roster(f"sleeper:u{i}", f"sleeper:L{i}", assets=["wr1"] + (["rb1"] if i <= 2 else []))
            for i in range(1, 11)
        ],
        path=ledger,
    )
    by_ownership = [r["displayName"] for r in board(ledger, sort="rostered")["players"]]
    assert by_ownership[0] == "Star Receiver"

    lagging = board(ledger, sort="valueWithoutRosters")["players"]
    # Good Back ranks 12th on the board but sits on 2 of 10 rosters.
    assert lagging[0]["displayName"] == "Star Receiver"
    assert {r["displayName"] for r in lagging} == {"Star Receiver", "Good Back"}


def test_sort_by_advantage_sinks_rows_without_a_market_number(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1", "rb1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1", "rb1"]),
        ],
        path=ledger,
    )
    rp.set_market_ownership_provider(lambda ids: {"rb1": 0.1})
    try:
        rows = board(ledger, sort="advantage")["players"]
        assert rows[0]["displayName"] == "Good Back"
        assert rows[-1]["sharpRosterAdvantage"] is None
    finally:
        rp.set_market_ownership_provider(None)


# ── transparency + audit ─────────────────────────────────────────────


def test_transparency_reports_the_pool_behind_the_numbers(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2", "ffpc:f1", "sleeper:absent"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u1", "sleeper:L2", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L3", assets=["wr1"]),
            roster("ffpc:f1", "ffpc:F1", assets=["wr1"], platform="ffpc"),
        ],
        path=ledger,
    )
    t = board(ledger)["transparency"]
    assert t["eligibleRosters"] == 4
    assert t["sleeperRosters"] == 3
    assert t["ffpcRosters"] == 1
    assert t["otherPlatformRosters"] == 0
    assert t["uniqueSharpManagers"] == 3
    assert t["cohortManagers"] == 4
    assert t["cohortManagersRepresented"] == 3
    assert t["cohortCoveragePct"] == 0.75
    assert t["lastRefreshedMs"] == NOW


def test_audit_lists_every_roster_behind_a_count(ledger, cohort_of):
    cohort_of(["sleeper:u1", "sleeper:u2", "sleeper:u3"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"]),
            roster("sleeper:u3", "sleeper:L3", assets=["rb1"]),
        ],
        path=ledger,
    )
    audit = rp.audit_player("wr1", ledger_path=ledger, now_ms=NOW)
    assert audit["holdingRosterCount"] == 2
    assert audit["distinctRosterKeys"] == 2
    assert audit["eligibleRosterCount"] == 3
    assert {r["rosterKey"] for r in audit["holdingRosters"]} == {"sleeper:L1#1", "sleeper:L2#1"}

    payload = board(ledger)
    assert row_for(payload, "Star Receiver")["sharpRosters"] == audit["holdingRosterCount"]


# ── the shared cohort ────────────────────────────────────────────────


def test_both_boards_resolve_the_pool_through_the_same_function():
    """The core requirement: one source of truth for who is a sharp.

    ``market`` is imported at MODULE level (top of this file) on purpose.
    Its re-export is a ``from ... import`` binding taken at import time,
    so importing it lazily inside a test that had already monkeypatched
    the cohort module would capture the stub and make this assertion
    describe the test harness rather than the code.
    """
    assert sharp_market.cohort_members is cohort.cohort_members
    assert sharp_market.CohortMember is cohort.CohortMember
    assert sharp_market.load_ffpc_config is cohort.load_ffpc_config
    assert rp.sharp_cohort is cohort


def test_the_roster_board_defines_no_qualification_of_its_own():
    """A guard against the pool quietly forking.

    If this feature ever grows its own notion of who qualifies, the
    words will show up here first.
    """
    import inspect

    source = inspect.getsource(rp)
    for forbidden in ("score_managers", "qualified =", "minScorePercentile", "ManagerRecord"):
        assert (
            forbidden not in source
        ), f"roster_percentage must not re-derive qualification: {forbidden}"


# ── connection reuse (V1-61) ────────────────────────────────────────────
#
# Every DB-backed call inside build_board() (load_rosters, one
# holdings_as_of per baseline window, the buy/sell join) already accepted
# an optional ``conn`` to reuse a caller's connection, but build_board()
# never threaded one through -- each call paid for its own
# ensure_roster_schema/ensure_platform_schema round trip (a schema
# readiness check plus a commit) against the same underlying file. This
# is the real cost behind the >60s timeouts measured against this
# endpoint in production.


def test_build_board_opens_exactly_one_connection(ledger, cohort_of, monkeypatch):
    """Regression pin: one board request must open the ledger file once,
    not once per internal call. Counts real ``sqlite3.connect`` calls
    through ``src.intel.ledger.connect`` -- the one primitive every
    schema-readiness helper in this chain bottoms out at -- rather than
    trusting call counts on the higher-level wrappers, which would not
    catch a wrapper that opens its own connection internally.
    """
    from src.intel import ledger as ledger_module

    cohort_of(["sleeper:u1", "sleeper:u2"])
    rs.record_rosters(
        [
            roster("sleeper:u1", "sleeper:L1", assets=["wr1", "rb1"]),
            roster("sleeper:u2", "sleeper:L2", assets=["wr1"]),
        ],
        path=ledger,
    )

    real_connect = ledger_module.connect
    calls = []

    def _counting_connect(path=None):
        calls.append(path)
        return real_connect(path)

    monkeypatch.setattr(ledger_module, "connect", _counting_connect)
    board(ledger)
    assert len(calls) == 1, f"expected exactly one connection, opened {len(calls)}"


def test_query_movements_does_not_close_a_caller_supplied_connection(tmp_path):
    """A caller-supplied connection must survive the call (ownership
    stays with the caller) -- mirrors the same ``own = conn is None``
    contract ``ensure_platform_schema``/``ensure_roster_schema`` already
    honour. Without this, threading one shared connection through
    ``build_board`` would close it after the FIRST ``_buy_sell_index``
    call and break every subsequent read on it.
    """
    from src.intel import ledger as ledger_module
    from src.intel import platform_ledger

    db_path = tmp_path / "ledger.sqlite3"
    conn = ledger_module.connect(db_path)
    try:
        platform_ledger.ensure_platform_schema(conn=conn)
        result = platform_ledger.query_movements(
            manager_keys=["sleeper:u1"],
            since_ms=0,
            until_ms=NOW,
            path=db_path,
            conn=conn,
        )
        assert result == []
        # Still usable -- a closed connection would raise ProgrammingError.
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()


class TestTrendBaselineLoopInvariants:
    """The row loop's trend block hoists two per-baseline structures out of
    the per-asset loop (V1-61: 57.4s of a measured 128.1s production
    ``build_board`` wall, run 33303611063). It must stay byte-identical to
    the retired per-asset formulation, which rebuilt both from
    ``baseline_holdings`` for every (asset x baseline) pair.
    """

    @staticmethod
    def _retired_baseline_holders(baseline_holdings, name, asset_id):
        """Exactly what build_board used to pass as ``baseline_holders``."""
        return {
            key: assets
            for key, assets in (baseline_holdings[name] or {}).items()
            if asset_id in assets
        }

    def test_inverted_index_iterates_the_same_roster_keys_as_the_retired_filter(self):
        baseline_holdings = {
            "thirtyDay": {
                "L1#1": {"4046", "6794"},
                "L1#2": {"4046"},
                "L1#3": {"5849"},
                "L1#4": set(),
            }
        }
        inverted: dict[str, set[str]] = {}
        for roster_key, held in baseline_holdings["thirtyDay"].items():
            for asset in held:
                inverted.setdefault(asset, set()).add(roster_key)

        for asset_id in ("4046", "6794", "5849", "never-held"):
            retired = self._retired_baseline_holders(baseline_holdings, "thirtyDay", asset_id)
            current = inverted.get(asset_id, rp._NO_ROSTER_KEYS)
            # _trend only ever iterates this argument, and only for keys.
            assert set(retired) == set(current), asset_id

    def test_an_asset_held_by_nobody_at_the_baseline_is_empty_not_missing(self):
        """MISSING IS NEVER ZERO's neighbour: held-by-nobody is a real
        measurement (rosterPctThen 0.0), not absent evidence, and the
        retired filter produced an empty mapping for it rather than
        omitting the baseline."""
        shared_keys = {f"L1#{i}" for i in range(1, 11)}
        then = rp._trend(
            "never-held",
            current_holders={"L1#1"},
            baseline_holders=rp._NO_ROSTER_KEYS,
            current_roster_keys=shared_keys,
            baseline_roster_keys=shared_keys,
        )
        retired = rp._trend(
            "never-held",
            current_holders={"L1#1"},
            baseline_holders={},
            current_roster_keys=shared_keys,
            baseline_roster_keys=shared_keys,
        )
        assert then == retired
        assert then["available"] is True
        assert then["rosterPctThen"] == 0.0

    def test_trend_treats_a_key_set_and_the_retired_mapping_identically(self):
        shared_keys = {f"L1#{i}" for i in range(1, 21)}
        holders = {"L1#1", "L1#2", "L1#3"}
        mapping = {"L1#2": {"4046"}, "L1#5": {"4046"}}
        assert rp._trend(
            "4046",
            current_holders=holders,
            baseline_holders=mapping,
            current_roster_keys=shared_keys,
            baseline_roster_keys=shared_keys,
        ) == rp._trend(
            "4046",
            current_holders=holders,
            baseline_holders=set(mapping),
            current_roster_keys=shared_keys,
            baseline_roster_keys=shared_keys,
        )

    def test_every_asset_on_a_multi_asset_baseline_roster_is_indexed(self, ledger, cohort_of):
        """The per-baseline inverted index must record EVERY asset each
        baseline roster held, not just one of them.

        The retired formulation re-scanned the whole holdings map per asset,
        so it could not lose a holding. An inverted index can, and a lost
        baseline holding is invisible in the worst way: it silently deflates
        ``rosterPctThen`` and inflates ``rostersAdded``, manufacturing a buy
        signal out of an indexing bug. Every roster here holds BOTH players
        at both endpoints, so both trends must be flat.
        """
        keys = [f"sleeper:u{i}" for i in range(1, 11)]
        cohort_of(keys)
        then = NOW - 40 * DAY
        for observed in (then, NOW):
            rs.record_rosters(
                [
                    roster(k, f"sleeper:L{i}", assets=["wr1", "rb1"], observed=observed)
                    for i, k in enumerate(keys)
                ],
                path=ledger,
            )

        payload = board(ledger)
        for name in ("Star Receiver", "Good Back"):
            trend = row_for(payload, name)["trend"]["thirtyDay"]
            assert trend["available"] is True, name
            assert trend["rosterPctThen"] == 1.0, (
                f"{name} was held by all 10 baseline rosters; a lower 'then' "
                "means its baseline holdings were dropped from the index"
            )
            assert trend["rosterPctNow"] == 1.0, name
            assert trend["rosterPctChange"] == 0.0, name
            assert trend["rostersAdded"] == 0, name
            assert trend["rostersDropped"] == 0, name

    def test_baseline_roster_keys_stay_intersected_with_applicable(self, ledger, cohort_of):
        """The per-asset intersection with ``applicable`` is deliberately NOT
        hoisted, and this exercises the real ``build_board`` path rather than
        ``_trend`` in isolation.

        _trend's ``union`` is ``current_roster_keys | baseline_roster_keys``,
        so handing it the whole baseline population widens the union and
        deflates populationOverlap -- the guard that stops a cohort which
        grew between endpoints reading as ownership gain.

        An IDP player is the case that separates them: his ``applicable`` set
        is narrowed to IDP-fielding leagues, while ``baseline_holdings``
        spans every roster in the cohort. Hoisting the intersection out of
        the loop therefore measures his 3-roster IDP population against all
        15 rosters (overlap 0.20 < 0.80) and WITHHOLDS a trend that is
        genuinely available.
        """
        idp_keys = [f"sleeper:idp{i}" for i in range(1, 4)]
        offense_keys = [f"sleeper:off{i}" for i in range(1, 13)]
        cohort_of(idp_keys + offense_keys)
        then = NOW - 40 * DAY

        def _rosters(observed):
            return [
                roster(k, f"sleeper:LI{i}", assets=["lb1"], fmt=IDP_LEAGUE, observed=observed)
                for i, k in enumerate(idp_keys)
            ] + [
                roster(k, f"sleeper:LO{i}", assets=["wr1"], fmt=OFFENSE_ONLY, observed=observed)
                for i, k in enumerate(offense_keys)
            ]

        rs.record_rosters(_rosters(then), path=ledger)
        rs.record_rosters(_rosters(NOW), path=ledger)

        trend = row_for(board(ledger), "Star Linebacker")["trend"]["thirtyDay"]
        assert trend["available"] is True, (
            "the IDP population never moved, so this trend is real; seeing it "
            "withheld means baseline_roster_keys was widened past `applicable`"
        )
        assert trend["comparableRosters"] == 3
        assert trend["populationOverlap"] == 1.0

    def test_precomputed_shared_and_union_match_deriving_them(self):
        """``_trend``'s optional fast-path arguments must be exactly the
        quantities it would otherwise derive (V1-61).

        ``build_board`` passes ``current_roster_keys=applicable`` and a
        ``baseline_roster_keys`` that is ``<baseline keys> & applicable``, so
        the baseline set is a SUBSET of the current set by construction, and
        therefore ``shared == baseline_roster_keys`` and
        ``union == current_roster_keys``. Deriving them anyway costs two
        roster-key-sized set operations per (asset x baseline).
        """
        current = {f"L1#{i}" for i in range(1, 41)}
        for baseline in (
            set(),  # nothing observed at the baseline
            {"L1#1"},  # a single overlapping roster
            {f"L1#{i}" for i in range(1, 41)},  # the whole population
            {f"L1#{i}" for i in range(1, 33)},  # exactly at the 0.80 bar
            {f"L1#{i}" for i in range(1, 32)},  # just under it
        ):
            holders = {"L1#1", "L1#2", "L1#3"}
            baseline_holders = {"L1#1", "L1#2"}
            derived = rp._trend(
                "4046",
                current_holders=holders,
                baseline_holders=baseline_holders,
                current_roster_keys=current,
                baseline_roster_keys=baseline,
            )
            fast = rp._trend(
                "4046",
                current_holders=holders,
                baseline_holders=baseline_holders,
                current_roster_keys=current,
                baseline_roster_keys=baseline,
                shared=baseline,
                union_size=len(current),
            )
            assert derived == fast, baseline

    def test_board_percentages_survive_the_precomputed_denominators(self, ledger, cohort_of):
        """The row loop derives ``applicable`` and ``counted`` from
        per-family precomputes rather than intersecting roster-key-sized
        sets per asset. The published arithmetic must not move.

        Mixed formats matter here: an IDP player's denominator is narrowed
        to IDP-fielding leagues while an offense player's is not, so this
        exercises both the narrowed and the full family sets.
        """
        idp_keys = [f"sleeper:idp{i}" for i in range(1, 5)]
        off_keys = [f"sleeper:off{i}" for i in range(1, 7)]
        cohort_of(idp_keys + off_keys)
        rs.record_rosters(
            [
                roster(k, f"sleeper:LI{i}", assets=["lb1", "wr1"], fmt=IDP_LEAGUE)
                for i, k in enumerate(idp_keys)
            ]
            + [
                roster(k, f"sleeper:LO{i}", assets=["wr1"], fmt=OFFENSE_ONLY)
                for i, k in enumerate(off_keys)
            ],
            path=ledger,
        )
        payload = board(ledger)

        wr = row_for(payload, "Star Receiver")
        lb = row_for(payload, "Star Linebacker")
        # WR: held by all 10, every roster can field him.
        assert (wr["sharpRosters"], wr["eligibleRosters"]) == (10, 10)
        assert wr["sharpRosterPct"] == 1.0
        # LB: held by the 4 IDP rosters, and only those 4 can field him --
        # the offense-only rosters are correctly out of his denominator.
        assert (lb["sharpRosters"], lb["eligibleRosters"]) == (4, 4)
        assert lb["sharpRosterPct"] == 1.0

    def test_a_holding_roster_outside_the_family_still_counts_at_the_baseline(
        self, ledger, cohort_of
    ):
        """The baseline key set is built by distributing the intersection over
        ``applicable = family_keys | held_rosters``, and BOTH terms are needed.

        A roster that HOLDS an IDP player is inside his denominator even when
        its captured format says the league fields no IDP — holding him is
        proof it does. Those rosters are in ``held_rosters`` but NOT in
        ``family_keys``, so dropping the ``held_rosters`` half of the baseline
        set silently shrinks ``shared`` and can withhold a trend that is
        genuinely available. Here 6 IDP + 4 offense-only rosters all hold the
        linebacker at both endpoints: correct behaviour is overlap 1.0 and an
        available trend; dropping the term gives 6/10 = 0.60 and withholds it.
        """
        idp_keys = [f"sleeper:idp{i}" for i in range(1, 7)]
        off_keys = [f"sleeper:off{i}" for i in range(1, 5)]
        cohort_of(idp_keys + off_keys)

        def _rosters(observed):
            return [
                roster(k, f"sleeper:LI{i}", assets=["lb1"], fmt=IDP_LEAGUE, observed=observed)
                for i, k in enumerate(idp_keys)
            ] + [
                roster(k, f"sleeper:LO{i}", assets=["lb1"], fmt=OFFENSE_ONLY, observed=observed)
                for i, k in enumerate(off_keys)
            ]

        rs.record_rosters(_rosters(NOW - 40 * DAY), path=ledger)
        rs.record_rosters(_rosters(NOW), path=ledger)

        lb = row_for(board(ledger), "Star Linebacker")
        # All 10 hold him, so all 10 are in his denominator.
        assert (lb["sharpRosters"], lb["eligibleRosters"]) == (10, 10)
        trend = lb["trend"]["thirtyDay"]
        assert trend["available"] is True, (
            "the population never moved; a withheld trend means the "
            "held_rosters half of the baseline key set was dropped"
        )
        assert trend["comparableRosters"] == 10
        assert trend["populationOverlap"] == 1.0
