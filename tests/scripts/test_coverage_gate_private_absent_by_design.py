"""The served-board coverage gate must not fail a board for a private source
that board declares it carries no vote from (2026-10-05 Rankings outage).

The hotfix deploy built a healthy board (1,043 players) and was then rolled
back by ``verify_live_source_coverage``: the three Signals IDP boards are fresh
in the checkout and, by design, on no served row (they run in SHADOW), so the
fresh-but-absent rule read them as a degraded board.  The contract validator
already excused exactly these through the board's own
``privateSourceAvailability`` stamp; the gate now reads the same stamp through
the same owner, ``data_contract.private_sources_absent_by_design``.

Synthetic payloads only; nothing here reads the live board.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import scripts.verify_live_source_coverage as live
import scripts.watchdog_contract_coverage as wcc
from src.api.data_contract import private_sources_absent_by_design

SHADOW = ("signalsIdpDb", "signalsIdpDl", "signalsIdpLb")
FRESH = {
    k: {"lastFetched": "2026-10-05T09:00:00+00:00", "ageHours": 1.0} for k in (*SHADOW, "signalsSf")
}
THRESHOLDS = {"signals": 24}


def _stamp(**overrides) -> dict:
    base = {
        k: {
            "state": "present",
            "provisioned": True,
            "csvPresent": True,
            "rolledBack": False,
            "heldFromVote": "shared_market_crosswalk_in_shadow_pending_promotion",
            "votes": False,
            "voteState": "shadow",
        }
        for k in SHADOW
    }
    base["signalsSf"] = {
        "state": "present",
        "provisioned": True,
        "csvPresent": True,
        "rolledBack": False,
        "heldFromVote": None,
        "votes": True,
        "voteState": "active",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _csvs_present(monkeypatch):
    monkeypatch.setattr(wcc, "_csv_nonempty", lambda key: key in FRESH)


class TestOneOwner:
    def test_shadow_held_rolled_back_and_unprovisioned_are_absent_by_design(self):
        stamp = _stamp(
            signalsSf={"state": "present", "rolledBack": True, "heldFromVote": None},
        )
        assert private_sources_absent_by_design(stamp) == frozenset((*SHADOW, "signalsSf"))
        assert private_sources_absent_by_design({"x": {"state": "not_provisioned"}}) == {"x"}

    def test_a_voting_or_missing_source_is_not_excused(self):
        stamp = _stamp(signalsIdpDb={"state": "missing", "rolledBack": False, "heldFromVote": None})
        out = private_sources_absent_by_design(stamp)
        assert "signalsSf" not in out  # voting
        assert "signalsIdpDb" not in out  # provisioned host, CSV gone: a real failure

    @pytest.mark.parametrize("bad", [None, [], "signalsIdpDb", {"signalsIdpDb": "shadow"}])
    def test_malformed_stamp_excuses_nothing(self, bad):
        assert private_sources_absent_by_design(bad) == frozenset()


class TestLiveDeployGate:
    def _live(self, monkeypatch):
        monkeypatch.setattr(live, "_read_freshness", lambda: FRESH)
        monkeypatch.setattr(live, "load_thresholds", lambda: THRESHOLDS)

    def test_shadow_sources_on_no_served_row_are_not_a_degraded_board(self, monkeypatch):
        """The exact 2026-10-05 failure: signalsSf voted on the board, the
        three shadow IDP boards on none."""
        self._live(monkeypatch)
        status = {
            "served_source_coverage": {"signalsSf": 400},
            "served_private_absent_by_design": list(SHADOW),
        }
        violations, ok, skipped = live._coverage_result(status)
        assert violations == []
        assert ("signalsSf", 400) in ok
        assert set(SHADOW) <= set(skipped)

    def test_a_voting_private_source_missing_from_the_board_still_fails(self, monkeypatch):
        self._live(monkeypatch)
        status = {
            "served_source_coverage": {"ktcSfTep": 400},
            "served_private_absent_by_design": list(SHADOW),
        }
        violations, _ok, _skipped = live._coverage_result(status)
        assert [v[0] for v in violations] == ["signalsSf"]

    @pytest.mark.parametrize("extra", [{}, {"served_private_absent_by_design": "signalsIdpDb"}])
    def test_fails_closed_without_the_served_declaration(self, monkeypatch, extra):
        self._live(monkeypatch)
        violations, _ok, _skipped = live._coverage_result(
            {"served_source_coverage": {"signalsSf": 400}, **extra}
        )
        assert sorted(v[0] for v in violations) == sorted(SHADOW)


def test_ci_watchdog_reads_the_same_stamp_from_the_built_contract():
    contract = {
        "playersArray": [{"sourceRankMeta": {"signalsSf": {}}} for _ in range(10)],
        "privateSourceAvailability": _stamp(),
    }
    violations, _ok, skipped = wcc.evaluate_coverage(contract, FRESH, THRESHOLDS)
    assert violations == []
    assert set(SHADOW) <= set(skipped)


def test_server_publishes_the_served_boards_declaration():
    import server

    assert server._compute_served_private_absent_by_design(
        {"privateSourceAvailability": _stamp()}
    ) == sorted(SHADOW)
    assert server._compute_served_private_absent_by_design(None) == []
    src = Path(server.__file__).read_text(encoding="utf-8")
    assert '"served_private_absent_by_design": served_private_absent_by_design' in src
    # Swapped with the coverage map, so the two always describe one board.
    assert "served_private_absent_by_design = new_private_absent_by_design" in src
    assert "served_private_absent_by_design = []" in src
