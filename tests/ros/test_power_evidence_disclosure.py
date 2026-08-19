"""The power ranking must say what its dominant input rests on.

WHY THIS BELONGS AT THE SECTION LEVEL, NOT PER OWNER
----------------------------------------------------
``power_v2`` weights ``team_ros_strength`` at 0.41, and in preseason —
once every historical-results component is dropped — it is the **only**
surviving component, so the published ranking is that one number's
percentile and nothing else.

V1-53 measured that the seasonal board it comes from is substantially
dynasty-derived: 18.1% of players priced by nothing but dynasty boards,
31.4% of contributing weight. So in preseason the public Power tab can
be showing a largely dynasty-derived ordering, labelled rest-of-season,
with nothing saying so.

The obvious fix — stamp each owner's ``dynastyProxyValueShare`` on their
ranking row — is the WRONG one, and the module says why in its own
words. ``teamRosStrength``'s inclusive percentile is public "by owner
decision", and *"publishing only that rank is what keeps it safe — the
composite is 0.72S + 0.18D + 0.05C + 0.05H and a rank over 12 owners is
11 ordering constraints against 36 unknowns"*. Twelve more per-team
numbers on a public payload adds constraints to exactly that system, and
"which sources could price your roster" reads as a roster-weakness
signal — the private side of CLAUDE.md §5's boundary.

So the disclosure is about the RANKING, not about any team: one
league-wide, value-weighted share plus how many teams are affected. That
is the claim a reader actually needs — *how much of this ordering is
dynasty-derived* — and it adds no per-owner constraint.
"""

from __future__ import annotations

import json

import pytest

from src.ros import power_v2


@pytest.fixture
def _strength_rows(tmp_path, monkeypatch):
    """Write a team-strength snapshot and point the loader at it."""

    def _write(rows):
        path = tmp_path / "latest.json"
        path.write_text(json.dumps(rows))
        monkeypatch.setattr(
            power_v2, "_load_team_strength_rows", lambda: json.loads(path.read_text())
        )
        return rows

    return _write


def _row(owner, strength, *, share, basis=None):
    if basis is None:
        basis = (
            "rest_of_season" if share == 0 else ("dynasty_proxy_only" if share == 1 else "mixed")
        )
    return {
        "ownerId": owner,
        "teamRosStrength": strength,
        "dynastyProxyValueShare": share,
        "evidenceBasis": basis,
    }


def test_the_league_wide_share_is_reported(_strength_rows):
    _strength_rows([_row("o1", 80.0, share=1.0), _row("o2", 20.0, share=0.0)])
    ev = power_v2.ros_strength_evidence()
    assert ev["dynastyProxyValueShare"] == pytest.approx(0.8, abs=1e-6), ev
    assert ev["basis"] == "mixed"
    assert ev["teamsWithAnyDynastyProxy"] == 1
    assert ev["teamCount"] == 2


def test_it_is_weighted_by_strength_not_by_team_count(_strength_rows):
    """One dominant dynasty-priced team is a different exposure from one
    trivial one, and a headcount calls them equal."""
    _strength_rows([_row("o1", 90.0, share=1.0), _row("o2", 10.0, share=0.0)])
    assert power_v2.ros_strength_evidence()["dynastyProxyValueShare"] == pytest.approx(0.9)
    _strength_rows([_row("o1", 10.0, share=1.0), _row("o2", 90.0, share=0.0)])
    assert power_v2.ros_strength_evidence()["dynastyProxyValueShare"] == pytest.approx(0.1)


def test_no_per_owner_share_reaches_the_public_payload(_strength_rows):
    """The disclosure boundary. Twelve per-team numbers would add
    constraints to the system the module deliberately protects."""
    _strength_rows([_row(f"o{i}", 50.0 + i, share=0.5) for i in range(1, 5)])
    ev = power_v2.ros_strength_evidence()
    assert "perOwner" not in ev
    assert not any(isinstance(v, (list, dict)) for v in ev.values()), ev


def test_an_absent_snapshot_reports_unavailable_not_zero(_strength_rows):
    """0.0 means 'measured, none of it dynasty'. No snapshot means we
    cannot say, and those must not read the same."""
    _strength_rows([])
    ev = power_v2.ros_strength_evidence()
    assert ev["dynastyProxyValueShare"] is None
    assert ev["basis"] == "unavailable"


def test_rows_predating_the_stamp_are_unavailable_not_clean(_strength_rows):
    """A snapshot written before V1-53 carries no share. Treating that
    absence as 0.0 would report a dynasty-derived board as pure
    rest-of-season — the exact silence this unit removes."""
    _strength_rows([{"ownerId": "o1", "teamRosStrength": 80.0}])
    ev = power_v2.ros_strength_evidence()
    assert ev["dynastyProxyValueShare"] is None
    assert ev["basis"] == "unavailable"


def test_the_section_carries_it(_strength_rows):
    """It has to reach the payload, or it is another stamp nobody reads."""
    from tests.ros.test_power_v2 import _make_snapshot

    _strength_rows([_row("o1", 80.0, share=1.0), _row("o2", 20.0, share=0.0)])
    rosters = [{"roster_id": i, "owner_id": f"o{i}"} for i in (1, 2)]
    matchups = {
        wk: [
            {"roster_id": 1, "matchup_id": 1, "points": 120.0 + wk},
            {"roster_id": 2, "matchup_id": 1, "points": 100.0 - wk},
        ]
        for wk in (1, 2, 3)
    }
    section = power_v2.build_section(_make_snapshot(rosters, matchups))
    assert "rosStrengthEvidence" in section
    assert section["rosStrengthEvidence"]["dynastyProxyValueShare"] == pytest.approx(0.8)
