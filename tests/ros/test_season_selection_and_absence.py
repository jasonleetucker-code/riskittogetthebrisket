"""The ROS sims must run on the newest season, and absence is not 0%.

Two defects, one family — both are "we could not measure this" rendered as
a confident measurement. Found by the master site audit (``W17-F001``,
``W17-F002`` / ``W20-F002``) against a running stack.

**Defect A — the sort key.** ``luck._season_sort_key`` is typed for a
season *string* and does ``int(season)`` inside
``except (TypeError, ValueError): return 0``. Every ROS call site handed
it a ``SeasonSnapshot`` **object**, so ``int()`` raised ``TypeError``, the
except swallowed it, every key came back 0, ``sorted()`` became a stable
no-op on a newest-first list, and ``seasons_sorted[-1]`` returned the
**oldest** season. The sims ran on 2024 while 2025 sat loaded and ignored.
Every other module in the repo passes ``s.season`` correctly — only
``src/ros/`` did not.

**Defect B — absence as measurement.** ``build_team_directions`` walks the
union of the two sim maps and the team-strength snapshot, so a manager can
arrive with a roster and no simulated season at all. Coercing that to
``0.0`` handed the classifier a confident zero, and it told the strongest
roster in the league to *"Sell aging win-now players."*
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.public_league import luck
from src.ros import trade_deadline
from src.ros.trade_deadline import (
    ODDS_SOURCE_NOT_SIMULATED,
    ODDS_SOURCE_SIMULATED,
    build_team_directions,
)


# ── Defect A: the newest season wins ──────────────────────────────────


@dataclass
class _FakeSeason:
    """Minimal stand-in carrying only what the sort key needs."""

    season: str


def test_the_sort_key_orders_objects_by_their_season_not_all_equal():
    """The regression, stated at the level the bug lived at.

    Snapshots arrive newest-first, so a no-op sort leaves the oldest at
    ``[-1]``. This asserts the ordering the ROS modules depend on.
    """
    seasons = [_FakeSeason("2026"), _FakeSeason("2025"), _FakeSeason("2024")]
    ordered = sorted(seasons, key=lambda s: luck._season_sort_key(s.season))
    assert [s.season for s in ordered] == ["2024", "2025", "2026"]
    assert ordered[-1].season == "2026"


def test_passing_the_object_itself_still_collapses_every_key():
    """Pin the trap, so nobody reintroduces it thinking it is harmless.

    This is the *broken* call shape. It does not raise — that is the whole
    problem — it silently returns 0 for everything.
    """
    seasons = [_FakeSeason("2026"), _FakeSeason("2025"), _FakeSeason("2024")]
    assert [luck._season_sort_key(s) for s in seasons] == [0, 0, 0]
    # ...and therefore the "newest" it would pick is actually the oldest.
    assert sorted(seasons, key=luck._season_sort_key)[-1].season == "2024"


def test_no_ros_module_passes_the_snapshot_object_to_the_sort_key():
    """A source check, because the runtime symptom is silent.

    The failure mode has no exception and no log line — the sims just
    quietly answer about the wrong year — so the cheapest durable guard is
    to assert the call shape itself.
    """
    import inspect

    from src.ros import playoff_sim, power_v2

    for module in (playoff_sim, power_v2):
        source = inspect.getsource(module)
        assert "key=luck._season_sort_key" not in source, (
            f"{module.__name__} passes the SeasonSnapshot object to a key "
            "typed for a season string; use key=lambda s: "
            "luck._season_sort_key(s.season)"
        )


# ── Defect B: absent from the sim is not 0% ───────────────────────────


def _directions(**kwargs: Any) -> list[dict[str, Any]]:
    return build_team_directions(teams=[], **kwargs)


SIM_MAPS = {
    "playoff_odds_map": {
        "strong": {"playoffOdds": 0.80},
        "weak": {"playoffOdds": 0.05},
    },
    "championship_map": {
        "strong": {"championshipOdds": 0.20},
        "weak": {"championshipOdds": 0.001},
    },
}


def test_a_manager_absent_from_the_sim_is_reported_as_absent():
    rows = _directions(
        **SIM_MAPS,
        team_strength_map={
            "strong": {"ownerId": "strong", "teamName": "Simulated Strong", "rank": 1},
            "newcomer": {"ownerId": "newcomer", "teamName": "Joined Last Year", "rank": 2},
        },
    )
    newcomer = next(r for r in rows if r["ownerId"] == "newcomer")

    # The whole point: no invented number, and no verb derived from one.
    assert newcomer["playoffOdds"] is None
    assert newcomer["championshipOdds"] is None
    assert newcomer["oddsSource"] == ODDS_SOURCE_NOT_SIMULATED
    assert newcomer["label"] == "Not simulated"
    assert "Sell" not in newcomer["recommendation"]
    assert "Seller" not in newcomer["label"]


def test_a_simulated_manager_still_gets_a_real_call():
    rows = _directions(
        **SIM_MAPS,
        team_strength_map={"strong": {"ownerId": "strong", "teamName": "S", "rank": 1}},
    )
    strong = next(r for r in rows if r["ownerId"] == "strong")
    assert strong["playoffOdds"] == 0.80
    assert strong["oddsSource"] == ODDS_SOURCE_SIMULATED
    assert strong["label"] == "Strong Buyer"


def test_a_genuine_zero_is_not_confused_with_absence():
    """0% *is* a measurement when the owner was in the simulated season.

    The fix must not turn every low number into "unknown" — that would
    trade one lie for another.
    """
    rows = _directions(
        playoff_odds_map={"real_zero": {"playoffOdds": 0.0}},
        championship_map={"real_zero": {"championshipOdds": 0.0}},
        team_strength_map={"real_zero": {"ownerId": "real_zero", "teamName": "Z", "rank": 1}},
    )
    row = rows[0]
    assert row["playoffOdds"] == 0.0
    assert row["oddsSource"] == ODDS_SOURCE_SIMULATED
    assert row["label"] != "Not simulated"


def test_unsimulated_teams_sort_last_rather_than_as_the_worst_team():
    rows = _directions(
        **SIM_MAPS,
        team_strength_map={
            "strong": {"ownerId": "strong", "teamName": "A", "rank": 1},
            "weak": {"ownerId": "weak", "teamName": "B", "rank": 2},
            "newcomer": {"ownerId": "newcomer", "teamName": "C", "rank": 3},
        },
    )
    assert [r["ownerId"] for r in rows] == ["strong", "weak", "newcomer"]


def test_the_not_simulated_payload_has_the_same_shape_as_a_real_one():
    """Consumers spread both branches identically, so the keys must match."""
    real = set(
        _directions(
            **SIM_MAPS,
            team_strength_map={"strong": {"ownerId": "strong", "teamName": "A", "rank": 1}},
        )[0]
    )
    absent = set(
        _directions(
            playoff_odds_map={},
            championship_map={},
            team_strength_map={"newcomer": {"ownerId": "newcomer", "teamName": "C", "rank": 1}},
        )[0]
    )
    assert real == absent, f"shape drift: {real ^ absent}"


def test_the_direction_constant_carries_no_buy_or_sell_verb():
    payload = trade_deadline.DIRECTION_NOT_SIMULATED
    assert payload["label"] == "Not simulated"
    for field in ("label", "summary", "recommendation"):
        assert "Buyer" not in payload[field]
        assert "Seller" not in payload[field]
