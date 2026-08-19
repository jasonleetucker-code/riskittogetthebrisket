"""V1-52 — a power ranking with no surviving component must REFUSE.

THE DEFECT, AND WHY IT IS NOT A CORNER CASE
-------------------------------------------
``build_section`` drops a component into ``missing_inputs`` when its
input is unavailable, then renormalises the remaining weights.  That is
right, and it is what makes the two lenses one engine rather than two
formulas.

But nothing stopped it dropping *all* of them.  When every component is
missing, ``active_weights`` is empty, ``weight_total`` falls back to
``1.0``, and every owner scores exactly ``0.0`` — at which point the
sort is a stable sort over equal keys, so the published ``rank`` is
whatever order ``_enumerate_owner_ids`` produced.  An identifier
ordering, presented as a power ranking.

**This is reachable, structurally, for the whole offseason.**  It does
not depend on any data file:

* ``preseason`` drops all seven ``_HISTORICAL_RESULTS_COMPONENTS``;
* the results-only lens drops ``team_ros_strength`` *by definition*;
* ``schedule_adjusted`` needs a schedule.

So results-only + preseason is **always** every-component-missing —
every day between the last game of one season and the first of the
next.  The forward-looking lens reaches the same state whenever the
team-strength file has not landed yet, which is exactly a fresh deploy.

Measured on the committed dev snapshot, results-only lens: five owners,
every ``powerScore`` 0.0, ranks 1-5 handed out in owner-id order — and
the order **contradicts the components published beside it**, since
``owner-B`` leads ``owner-A`` on five of seven components and ranks
below it.

Same defect family as the playoff-odds one fixed in V1-51 (a placeholder
made every matchup a tie, so the third tiebreak — the ownerId string —
became the answer, and the published order was the lexically-first
seven Sleeper ids).  A ranking nobody can justify is worse than no
ranking, because the reader cannot tell the difference.

THE RULE
--------
No surviving component → no ranking.  ``powerScore`` and ``rank`` are
``None`` (never 0.0, never 1..N), and an ``unrankable`` block names the
reason.  The owners are still listed; only the certainty is withheld —
the same posture ``playoff_structure`` takes for an unknown bracket and
``RealizedPoints.unscored`` takes for a rule it cannot score.
"""

from __future__ import annotations

import json
from pathlib import Path

from src.ros import power_v2

REPO = Path(__file__).resolve().parents[2]


def _preseason_snapshot():
    """Real seasons with real scores, but the CURRENT season unplayed —
    which is the live state of every league right now."""
    from tests.ros.test_power_v2 import _make_snapshot

    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    # No matchups at all in the current season → _is_preseason is True.
    return _make_snapshot(rosters, {})


def test_results_only_in_preseason_refuses_rather_than_ordering_by_id():
    """The structural case: this lens ALWAYS loses every component here."""
    snapshot = _preseason_snapshot()
    section = power_v2.build_section(snapshot, lens=power_v2.LENS_RESULTS_ONLY)

    assert section["preseason"] is True
    assert section["effectiveWeights"] == {}, (
        "fixture no longer reaches the every-component-missing state; "
        "the test below would pass vacuously"
    )

    assert section.get("unrankable"), (
        "every component is missing, so there is nothing to rank on — "
        "the section must say so instead of publishing an order"
    )
    assert section["unrankable"].get("reason")
    assert section["unrankable"].get("missingInputs")

    for row in section["currentRanking"]:
        assert row["powerScore"] is None, (
            f"{row['ownerId']} scored {row['powerScore']!r} with no surviving "
            f"component — 0.0 is a real score and this is not one"
        )
        assert row["rank"] is None, (
            f"{row['ownerId']} was ranked {row['rank']!r} on identically-zero "
            f"scores, so the rank is the owner-id order"
        )


def test_the_owners_are_still_listed_when_it_refuses():
    """Withhold the certainty, not the league. A blank tab is a worse
    answer than an honest one, and the same posture playoff_structure
    already takes for an unknown bracket."""
    section = power_v2.build_section(_preseason_snapshot(), lens=power_v2.LENS_RESULTS_ONLY)
    owners = {r["ownerId"] for r in section["currentRanking"]}
    assert owners == {"o1", "o2", "o3", "o4"}


def test_a_lens_that_keeps_one_component_still_ranks():
    """NON-VACUITY. A repair that refused whenever anything was missing
    would satisfy every assertion above and destroy the renormalisation
    that makes the two lenses one engine."""
    from tests.ros.test_power_v2 import _make_snapshot

    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2, 3, 4)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 120.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0 + wk},
            {"roster_id": 3, "matchup_id": 2, "points": 95.0 + wk},
            {"roster_id": 4, "matchup_id": 2, "points": 80.0 + wk},
        ]
        for wk in (1, 2, 3)
    }
    section = power_v2.build_section(
        _make_snapshot(rosters, matchups), lens=power_v2.LENS_RESULTS_ONLY
    )

    assert not section.get("unrankable")
    assert section["effectiveWeights"], "components survived; this must rank"
    scores = [r["powerScore"] for r in section["currentRanking"]]
    assert all(s is not None for s in scores)
    assert len(set(scores)) > 1, "real data must not produce one flat score"
    assert [r["rank"] for r in section["currentRanking"]] == [1, 2, 3, 4]


def test_the_trend_is_unaffected_because_it_is_never_preseason():
    """The trend scores each week AS OF that week with preseason=False,
    so its components survive. Pinned because the refusal must not
    silently blank the series it is not about."""
    from tests.ros.test_power_v2 import _make_snapshot

    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 120.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0 - wk},
        ]
        for wk in (1, 2, 3)
    }
    section = power_v2.build_section(
        _make_snapshot(rosters, matchups), lens=power_v2.LENS_RESULTS_ONLY
    )
    weeks = (section.get("trend") or {}).get("weeks") or []
    assert len(weeks) == 3
    for wk in weeks:
        for row in wk["rankings"]:
            assert row["powerScore"] is not None
            assert row["rank"] is not None


def test_the_committed_dev_snapshot_reproduces_the_defect_shape():
    """The measurement quoted in this module's docstring, pinned so the
    claim cannot quietly stop being true."""
    path = REPO / "data" / "public_league" / "snapshot.json"
    if not path.exists():  # pragma: no cover - data/ is gitignored
        import pytest

        pytest.skip("data/public_league/snapshot.json not present")

    from src.public_league.snapshot_store import snapshot_from_dict

    snapshot = snapshot_from_dict(json.loads(path.read_text()))
    section = power_v2.build_section(snapshot, lens=power_v2.LENS_RESULTS_ONLY)
    assert section["preseason"] is True
    assert section["effectiveWeights"] == {}
    assert section.get("unrankable")
    assert all(r["rank"] is None for r in section["currentRanking"])
