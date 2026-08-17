"""C2-U1 D3 — the lineup stamp must survive the SERVING path.

WHY THIS FILE EXISTS
────────────────────
C2-U1 shipped with a critical defect that every other test in the unit
missed, because they all tested one of the two halves:

* ``tests/lineup/test_canonical_lineup.py`` proves the solver is right.
* ``frontend/__tests__/starter-slots.test.js`` proves the client renders
  a stamp faithfully.
* Nothing proved the stamp SURVIVES from one to the other.

It did not.  ``/api/data`` splices a live Sleeper overlay over the baked
contract and rebuilds ``sleeper.teams`` wholesale from
``sleeper_overlay._build_teams_block``, which emits no ``optimalLineup``.
So on the normal path — overlay warmed after every scrape, cached 15
minutes — the stamp was discarded and the frontend failed closed. The
feature worked only while Sleeper was DOWN, which is the opposite of a
degradation.

These tests are about the SEAM, so they are deliberately written against
the overlay's real team shape rather than a convenient stub.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from src.api import sleeper_overlay
from src.api.data_contract import build_api_data_contract, stamp_optimal_lineups

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "golden" / "input_export.json.gz"


@pytest.fixture(scope="module")
def contract():
    raw = json.loads(gzip.open(FIXTURE, "rt").read())
    return build_api_data_contract(raw)


class TestTheOverlayShapeIsWhyThisBroke:
    def test_the_overlay_team_block_carries_no_lineup(self):
        """Stated as a FACT about the overlay, not an assumption.

        If ``_build_teams_block`` ever starts emitting ``optimalLineup``
        itself this test fails, and that is correct: two producers of one
        field is the defect this unit exists to prevent, and the repair
        would then be to delete one — not to leave both.
        """
        import inspect

        src = inspect.getsource(sleeper_overlay._build_teams_block)
        assert "optimalLineup" not in src

    def test_only_one_function_writes_the_stamp(self):
        """Grep-level guard: the stamp has exactly one producer."""
        repo = Path(__file__).resolve().parents[2]
        writers = set()
        for path in (repo / "src").rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if '"optimalLineup"] =' in line or "'optimalLineup'] =" in line:
                    writers.add(path.relative_to(repo).as_posix())
        assert writers == {"src/api/data_contract.py"}


class TestRestampingAfterAnOverlayMerge:
    """The repair, tested at the seam server.py actually uses."""

    @staticmethod
    def _overlay_shaped(team: dict) -> dict:
        """A team as the LIVE overlay would rebuild it — the exact key
        set of ``_build_teams_block``, and pointedly no lineup."""
        return {
            "name": team.get("name"),
            "sleeperTeamName": team.get("sleeperTeamName"),
            "ownerId": team.get("ownerId"),
            "roster_id": team.get("roster_id"),
            "players": list(team.get("players") or []),
            "playerIds": list(team.get("playerIds") or []),
            "picks": list(team.get("picks") or []),
            "pickDetails": list(team.get("pickDetails") or []),
            "faabBudget": None,
            "faabUsed": None,
            "faabRemaining": None,
        }

    def test_the_spliced_payload_loses_the_stamp_without_a_re_stamp(self, contract):
        """The defect itself, pinned so it cannot come back silently."""
        baked = contract["sleeper"]["teams"]
        assert all(t.get("optimalLineup", {}).get("available") for t in baked)

        spliced = {
            **contract,
            "sleeper": {**contract["sleeper"], "teams": [self._overlay_shaped(t) for t in baked]},
        }
        assert all("optimalLineup" not in t for t in spliced["sleeper"]["teams"])

    def test_re_stamping_restores_it(self, contract):
        baked = contract["sleeper"]["teams"]
        spliced = {
            **contract,
            "sleeper": {**contract["sleeper"], "teams": [self._overlay_shaped(t) for t in baked]},
        }
        stamp_optimal_lineups(spliced, rows=contract["playersArray"])
        after = spliced["sleeper"]["teams"]
        assert len(after) == len(baked)
        for team in after:
            assert team["optimalLineup"]["available"] is True
            assert team["optimalLineup"]["slotSource"] == "sleeper_roster_positions"
            assert team["optimalLineup"]["starters"]

    def test_it_agrees_with_the_baked_stamp_when_the_rosters_agree(self, contract):
        """Re-solving, not copying — but on an UNCHANGED roster the two
        must be identical, or the solve is not deterministic."""
        baked = contract["sleeper"]["teams"]
        spliced = {
            **contract,
            "sleeper": {**contract["sleeper"], "teams": [self._overlay_shaped(t) for t in baked]},
        }
        stamp_optimal_lineups(spliced, rows=contract["playersArray"])
        for before, after in zip(baked, spliced["sleeper"]["teams"]):
            assert after["optimalLineup"]["starters"] == before["optimalLineup"]["starters"]
            assert after["optimalLineup"]["assignments"] == before["optimalLineup"]["assignments"]

    def test_a_fresher_roster_gets_a_FRESH_lineup_not_the_stale_one(self, contract):
        """Why the repair re-solves instead of copying the baked stamp.

        The overlay's rosters are newer than the baked ones. If a starter
        was dropped since the scrape, a copied lineup would still start
        them.
        """
        baked = contract["sleeper"]["teams"]
        team = next(t for t in baked if t["optimalLineup"]["starters"])
        dropped = team["optimalLineup"]["starters"][0]

        fresh = self._overlay_shaped(team)
        fresh["players"] = [p for p in fresh["players"] if p != dropped]

        spliced = {
            **contract,
            "sleeper": {**contract["sleeper"], "teams": [fresh]},
        }
        stamp_optimal_lineups(spliced, rows=contract["playersArray"])
        starters = spliced["sleeper"]["teams"][0]["optimalLineup"]["starters"]
        assert dropped not in starters, "a dropped player is still being started"

    def test_it_never_mutates_the_teams_it_was_given(self, contract):
        """The overlay's teams are entries in a 15-minute shared cache.

        Stamping them in place would leak one request's lineup into every
        later request that hit the same cache entry — including, on the
        cross-league path, a DIFFERENT league's.
        """
        baked = contract["sleeper"]["teams"]
        cached = [self._overlay_shaped(t) for t in baked]
        snapshot = [dict(t) for t in cached]

        spliced = {**contract, "sleeper": {**contract["sleeper"], "teams": cached}}
        stamp_optimal_lineups(spliced, rows=contract["playersArray"])

        for original, before in zip(cached, snapshot):
            assert original == before, "the caller's team dict was mutated"
            assert "optimalLineup" not in original

    def test_values_come_from_the_supplied_rows_not_a_reduced_view(self, contract):
        """``server.py`` pops ``playersArray`` for the runtime view, so a
        re-stamp that read the SERVED payload would price every player as
        UNKNOWN and report an empty lineup as if measured."""
        baked = contract["sleeper"]["teams"]
        reduced = {
            "sleeper": {**contract["sleeper"], "teams": [self._overlay_shaped(t) for t in baked]},
            "meta": contract.get("meta"),
        }
        assert "playersArray" not in reduced

        stamp_optimal_lineups(reduced, rows=contract["playersArray"])
        assert reduced["sleeper"]["teams"][0]["optimalLineup"]["starters"]

        # ...and without the rows, it honestly reports nobody priced
        # rather than inventing a lineup.
        reduced2 = {
            "sleeper": {**contract["sleeper"], "teams": [self._overlay_shaped(baked[0])]},
            "meta": contract.get("meta"),
        }
        stamp_optimal_lineups(reduced2)
        stamp = reduced2["sleeper"]["teams"][0]["optimalLineup"]
        assert stamp["starters"] == []
        assert stamp["unpriced"], "unpriced must be reported, not silently empty"


class TestTheServingPathIsWired:
    """Structural: ``server.py`` must actually call the re-stamp at the
    seam where it replaces ``sleeper.teams``."""

    def test_server_re_stamps_after_splicing_the_overlay(self):
        repo = Path(__file__).resolve().parents[2]
        src = (repo / "server.py").read_text(encoding="utf-8")
        idx = src.index('scrubbed["sleeper"] = overlay_full')
        window = src[idx : idx + 2000]
        assert "stamp_optimal_lineups" in window, (
            "server.py replaces sleeper.teams with the overlay's and does not re-stamp "
            "the lineup — the C2-U1 stamp is discarded on the normal serving path"
        )

    def test_the_re_stamp_supplies_rows_explicitly(self):
        repo = Path(__file__).resolve().parents[2]
        src = (repo / "server.py").read_text(encoding="utf-8")
        idx = src.index('scrubbed["sleeper"] = overlay_full')
        window = src[idx : idx + 2000]
        assert "rows=" in window and "playersArray" in window
