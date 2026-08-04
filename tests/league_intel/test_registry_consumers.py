"""LI-1 — registry rosterSettings fix: every consumer verified.

``config/leagues/registry.json`` dynasty_main rosterSettings were stale
on 8 fields (TE 1→2, K missing→1, DL/LB/DB 2→3, IDP_FLEX 2→0,
rosterSize 30→58, taxiSize 5→0; see SETTINGS_AUDIT.md).  These tests
pin (a) the corrected registry values against the canonical snapshot
and (b) that every consumer of rosterSettings behaves correctly with
the corrected shape:

1. src/api/league_registry.py            — loader / passthrough
2. src/ros/scrape.py::_flatten_starter_slots + src/ros/lineup.py
3. src/ros/playoff_sim.py::_load_starter_slots + _eligible_for_slot
4. src/trade/team_impact.py (via src/api/trade_simulator.py)
5. src/trade/suggestions.py::DEFAULT_STARTER_NEEDS (hardcoded mirror)
6. server.py draft-capital teamCount read (value unchanged: 12)
7. frontend useTeam.js / LeagueSwitcher.jsx read only teamCount /
   passthrough — covered by the registry-shape assertions here plus
   tests/e2e/specs/multi-league.spec.js existence checks.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def real_registry(monkeypatch):
    """Point the league registry at the real repo file (the global
    conftest points it at /nonexistent to keep other suites hermetic),
    reloading on the way in and back out."""
    from src.api import league_registry

    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(REPO / "config" / "leagues" / "registry.json"))
    league_registry.reload_registry()
    yield league_registry
    monkeypatch.undo()
    league_registry.reload_registry()


def _registry_main() -> dict:
    registry = json.loads((REPO / "config" / "leagues" / "registry.json").read_text())
    return next(lg for lg in registry["leagues"] if lg["key"] == "dynasty_main")


# ── 0. Registry file matches the canonical snapshot truth ─────────────


class TestRegistryMatchesSnapshot:
    def test_starters_match_live_sleeper_structure(self):
        from src.league_intel.config import load_canonical_config

        cfg = load_canonical_config()
        starters = _registry_main()["rosterSettings"]["starters"]
        # Registry uses SFLEX where Sleeper says SUPER_FLEX
        translated = {
            ("SFLEX" if k == "SUPER_FLEX" else k): v for k, v in cfg.starter_counts.items()
        }
        non_zero = {k: v for k, v in starters.items() if v > 0}
        assert non_zero == translated
        assert starters.get("IDP_FLEX", 0) == 0  # explicit: league has no IDP flex
        assert sum(starters.values()) == 21

    def test_roster_size_and_taxi(self):
        from src.league_intel.config import load_canonical_config

        cfg = load_canonical_config()
        rs = _registry_main()["rosterSettings"]
        assert rs["rosterSize"] == cfg.roster_size == 58
        assert rs["taxiSize"] == cfg.taxi_slots == 0
        assert rs["teamCount"] == cfg.team_count == 12


# ── 1. league_registry loader ─────────────────────────────────────────


class TestLeagueRegistryLoader:
    def test_get_league_roster_settings_serves_corrected_values(self, real_registry):
        rs = real_registry.get_league_roster_settings("dynasty_main")
        assert rs["starters"]["TE"] == 2
        assert rs["starters"]["K"] == 1
        assert rs["starters"]["DL"] == rs["starters"]["LB"] == rs["starters"]["DB"] == 3
        assert rs["starters"]["IDP_FLEX"] == 0
        assert rs["rosterSize"] == 58
        assert rs["taxiSize"] == 0


# ── 2. ros scrape flatten + lineup optimizer ──────────────────────────


def _flatten(starters: dict) -> list[str]:
    from src.ros.scrape import _flatten_starter_slots

    return _flatten_starter_slots(starters)


class TestRosLineupPath:
    def test_flatten_produces_21_slots(self):
        slots = _flatten(_registry_main()["rosterSettings"]["starters"])
        assert len(slots) == 21
        assert slots.count("TE") == 2
        assert slots.count("K") == 1
        assert slots.count("DL") == slots.count("LB") == slots.count("DB") == 3
        assert "IDP_FLEX" not in slots  # zero-count slots dropped
        assert slots.count("SUPER_FLEX") == 1  # SFLEX alias translated

    def test_optimizer_fills_all_21_slots(self):
        from src.ros.lineup import RosterPlayer, optimize_lineup

        slots = _flatten(_registry_main()["rosterSettings"]["starters"])
        roster = []
        pid = 0
        for pos, n in [
            ("QB", 3),
            ("RB", 4),
            ("WR", 6),
            ("TE", 3),
            ("K", 1),
            ("DE", 2),  # DL family alias
            ("DT", 2),
            ("LB", 4),
            ("CB", 2),  # DB family alias
            ("S", 2),
        ]:
            for _ in range(n):
                pid += 1
                roster.append(
                    RosterPlayer(
                        player_id=str(pid),
                        canonical_name=f"{pos}{pid}",
                        position=pos,
                        ros_value=100.0 - pid,
                    )
                )
        solution = optimize_lineup(roster, starter_slots=slots)
        assert solution.unfilled_slots == []
        assert len(solution.starting_lineup) == 21
        filled = [r["slot"] for r in solution.starting_lineup]
        assert filled.count("K") == 1
        assert filled.count("DL") == 3

    def test_optimizer_reports_unfilled_k_without_kicker(self):
        from src.ros.lineup import RosterPlayer, optimize_lineup

        slots = _flatten(_registry_main()["rosterSettings"]["starters"])
        roster = [RosterPlayer(player_id="1", canonical_name="QB1", position="QB", ros_value=50.0)]
        solution = optimize_lineup(roster, starter_slots=slots)
        assert "K" in solution.unfilled_slots


# ── 3. playoff sim slot loading ───────────────────────────────────────


class TestPlayoffSimPath:
    def test_load_starter_slots_reads_corrected_registry(self, real_registry):
        # LI-8 removed playoff_sim's private duplicates of the flattener
        # and the eligibility rules (ADR-007 flagged both for this task).
        # The module now re-exports the canonical lineup.py versions, so
        # this test asserts the same behavior through the one
        # implementation that survives.
        from src.ros.lineup import _eligible_for_slot
        from src.ros.playoff_sim import _load_starter_slots

        slots = _load_starter_slots()
        assert len(slots) == 21
        assert slots.count("K") == 1 and slots.count("DB") == 3
        # K slot eligibility falls through to exact-position match
        assert _eligible_for_slot("K", "K") is True
        assert _eligible_for_slot("K", "QB") is False
        # DB slot accepts family aliases
        assert _eligible_for_slot("DB", "CB") is True


# ── 4. trade team-impact fit analysis ─────────────────────────────────


def _asset(name: str, pos: str, value: int) -> dict:
    return {"name": name, "pos": pos, "basePos": pos, "value": value, "assetClass": "player"}


class TestTeamImpactPath:
    def test_project_starters_with_corrected_settings(self):
        from src.trade.team_impact import project_starters

        rs = _registry_main()["rosterSettings"]
        assets = []
        for pos, n in [("QB", 2), ("RB", 3), ("WR", 5), ("TE", 3), ("DL", 4), ("LB", 4), ("DB", 4)]:
            assets.extend(_asset(f"{pos}{i}", pos, 5000 - i) for i in range(n))
        starters = project_starters(assets, rs)
        assert len(starters["TE"]) >= 2  # 2 dedicated TE slots fill
        assert len(starters["DL"]) == 3  # fixed 3, no IDP_FLEX overflow
        assert len(starters["LB"]) == 3
        assert len(starters["DB"]) == 3
        total = sum(len(v) for v in starters.values())
        # 20 fillable slots: 21 minus the K slot, which the fit engine
        # deliberately excludes (K not in _FILL_ORDER/_BASE_POSITIONS —
        # kickers carry no dynasty trade value).
        assert total == 20

    def test_needed_at_reflects_three_db(self):
        from src.trade.team_impact import _needed_at

        rs = _registry_main()["rosterSettings"]
        assert _needed_at("DB", rs) == 3.0  # 3 fixed + no IDP_FLEX share
        assert _needed_at("TE", rs) > 2.0  # 2 fixed + FLEX share

    def test_league_active_positions_all_seven(self):
        from src.trade.team_impact import _league_active_positions

        rs = _registry_main()["rosterSettings"]
        assert _league_active_positions(rs) == ["QB", "RB", "WR", "TE", "DL", "LB", "DB"]


# ── 5. suggestions starter-needs mirror ───────────────────────────────


class TestSuggestionsNeeds:
    def test_default_starter_needs_match_live_lineup(self):
        from src.trade.suggestions import DEFAULT_STARTER_NEEDS

        assert DEFAULT_STARTER_NEEDS["TE"] == 2
        assert DEFAULT_STARTER_NEEDS["DB"] == 3
        assert DEFAULT_STARTER_NEEDS["DL"] == 3
        assert DEFAULT_STARTER_NEEDS["LB"] == 3
        assert "K" not in DEFAULT_STARTER_NEEDS  # kickers not tradeable assets

    # NOTE: every derived-needs test below takes ``real_registry``.  The
    # global conftest points LEAGUE_REGISTRY_PATH at /nonexistent, and
    # ``starter_needs_for_league`` falls back to DEFAULT_STARTER_NEEDS
    # when the registry has nothing — so without the fixture the
    # dynasty_main assertion passes by comparing the fallback to itself,
    # and the dynasty_new one fails for the wrong reason.
    def test_derived_needs_reproduce_the_constant_for_dynasty_main(self, real_registry):
        """The derivation must be a NO-OP for the live league.

        ``DEFAULT_STARTER_NEEDS`` was hand-derived: base slots plus an
        allocation of the 3 flex slots as +1 QB / +1 RB / +1 WR.  If the
        registry-driven version disagrees, it is the derivation that is
        wrong, not the constant — this league's trade suggestions have
        been computed against those numbers and are correct.
        """
        from src.trade.suggestions import DEFAULT_STARTER_NEEDS, starter_needs_for_league

        derived = starter_needs_for_league("dynasty_main")
        # Guard against the vacuous pass: prove the registry is actually
        # loaded, so this is a real comparison and not fallback == fallback.
        assert real_registry.get_league_roster_settings("dynasty_main").get("starters")
        assert derived == DEFAULT_STARTER_NEEDS

    def test_derived_needs_follow_the_league_not_the_scoring_profile(self, real_registry):
        """dynasty_new shares the scoring profile and not the lineup.

        Both leagues are ``superflex_tep15_ppr1``, but dynasty_new is
        10-team, starts 1 TE and rosters no IDP.  Serving it
        dynasty_main's demand model told it to chase a second TE and
        nine defenders it cannot start.
        """
        from src.trade.suggestions import starter_needs_for_league

        needs = starter_needs_for_league("dynasty_new")

        assert needs["TE"] == 1, "dynasty_new starts one TE"
        assert "DL" not in needs and "LB" not in needs and "DB" not in needs
        # Superflex + 2 FLEX are allocated the same way in both leagues.
        assert needs["QB"] == 2
        assert needs["RB"] == 3
        assert needs["WR"] == 4
        assert "K" not in needs

    def test_derived_needs_fall_back_rather_than_returning_nothing(self, real_registry):
        """An unknown league must not read as 'this roster needs nobody'.

        An empty demand map silences every surplus/need suggestion, which
        looks identical to a roster with no holes.
        """
        from src.trade.suggestions import DEFAULT_STARTER_NEEDS, starter_needs_for_league

        assert starter_needs_for_league("no_such_league") == DEFAULT_STARTER_NEEDS
        assert starter_needs_for_league(None)


# ── 6. server draft-capital teamCount read ────────────────────────────


class TestServerTeamCountRead:
    def test_team_count_still_twelve(self, real_registry):
        cfg = real_registry.get_league_by_key("dynasty_main")
        assert cfg.roster_settings.get("teamCount", 12) == 12
