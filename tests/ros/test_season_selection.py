"""The ROS sims must run on the newest season, not the oldest.

``luck._season_sort_key`` is typed for a season *string* and does
``int(season)`` inside ``except (TypeError, ValueError): return 0``. All
four ROS call sites (``playoff_sim.py:464,546,562`` and
``power_v2.py:325``) handed it a ``SeasonSnapshot`` **object**, so
``int()`` raised ``TypeError``, the except swallowed it, every key came
back 0, ``sorted()`` became a stable no-op on a newest-first list, and
``seasons_sorted[-1]`` returned the **oldest** season. The sims resolved
2024 while 2025 sat loaded and ignored.

Every other module in the repo passes ``s.season`` correctly —
``luck.py:193``, ``power.py:79``, ``weekly_recap.py:613``. Only
``src/ros/`` did not. Found by the master site audit (``W17-F001``).

The sibling defect from the same audit finding — absence from the sim
coerced into a confident 0.0, which told the strongest roster in the
league to sell — is fixed separately on main (Critical batch C3) and
covered by ``tests/ros/test_trade_deadline_unknown.py``. This file is
only the season-selection half.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass

from src.public_league import luck
from src.ros import playoff_sim, power_v2


@dataclass
class _FakeSeason:
    """Minimal stand-in carrying only what the sort key needs."""

    season: str


def test_the_sort_key_orders_objects_by_their_season():
    """Snapshots arrive newest-first, so a no-op sort leaves the OLDEST
    at ``[-1]`` — which is the slot every ROS caller reads as "current"."""
    seasons = [_FakeSeason("2026"), _FakeSeason("2025"), _FakeSeason("2024")]
    ordered = sorted(seasons, key=lambda s: luck._season_sort_key(s.season))
    assert [s.season for s in ordered] == ["2024", "2025", "2026"]
    assert ordered[-1].season == "2026"


def test_passing_the_object_itself_still_collapses_every_key():
    """Pin the trap, so nobody reintroduces it thinking it is harmless.

    This is the *broken* call shape. It does not raise — that is the
    whole problem — it silently returns 0 for everything, and the
    resulting sort quietly selects the wrong year.
    """
    seasons = [_FakeSeason("2026"), _FakeSeason("2025"), _FakeSeason("2024")]
    assert [luck._season_sort_key(s) for s in seasons] == [0, 0, 0]
    assert sorted(seasons, key=luck._season_sort_key)[-1].season == "2024"


def test_no_ros_module_passes_the_snapshot_object_to_the_sort_key():
    """A source check, because the runtime symptom is silent.

    There is no exception and no log line — the sims just answer about
    the wrong year — so the cheapest durable guard is to assert the call
    shape itself rather than wait for a number to look wrong.
    """
    for module in (playoff_sim, power_v2):
        source = inspect.getsource(module)
        assert "key=luck._season_sort_key" not in source, (
            f"{module.__name__} passes the SeasonSnapshot object to a key typed "
            "for a season string; use key=lambda s: luck._season_sort_key(s.season)"
        )
