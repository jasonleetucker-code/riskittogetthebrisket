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


def _registry_league(key: str) -> dict:
    registry = json.loads((REPO / "config" / "leagues" / "registry.json").read_text())
    return next(lg for lg in registry["leagues"] if lg["key"] == key)


def _registry_main() -> dict:
    return _registry_league("dynasty_main")


def _dynasty_new_snapshot() -> dict:
    """The committed dynasty_new host snapshot (W18-F011 / V1-25).

    dynasty_main's snapshot lives at ``config/league_intel/`` root and is
    what ``load_canonical_config`` reads; dynasty_new's lives in its own
    subdirectory so the root loader (which globs non-recursively and IS
    dynasty_main by construction) can never pick it up.  Read raw rather
    than through ``build_config_from_snapshot``: that builder's scoring
    canary requires IDP + kicker keys dynasty_new's card does not carry.
    """
    d = REPO / "config" / "league_intel" / "dynasty_new"
    candidates = sorted(d.glob("sleeper_league_snapshot_*.json"), key=lambda p: p.name)
    assert candidates, f"no committed dynasty_new snapshot in {d}"
    return json.loads(candidates[-1].read_text(encoding="utf-8"))


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


class TestRegistryMatchesSnapshotDynastyNew:
    """W18-F011 / V1-25: the registry's dynasty_new entry was wrong against
    its live host on EVERY roster field it modelled (rosterSize 24 vs 27,
    taxiSize 5 vs 3, FLEX 2 vs FLEX 1 + WRRB_FLEX 1) and nothing in the
    suite compared it to anything.  These pins are the same registry ==
    committed-snapshot contract ``TestRegistryMatchesSnapshot`` gives
    dynasty_main, against ``config/league_intel/dynasty_new/``."""

    def test_starters_match_live_sleeper_structure(self):
        snap = _dynasty_new_snapshot()
        positions = [str(p).upper() for p in snap["roster_positions"]]
        host_counts: dict[str, int] = {}
        for slot in positions:
            if slot == "BN":
                continue
            host_counts[slot] = host_counts.get(slot, 0) + 1

        starters = _registry_league("dynasty_new")["rosterSettings"]["starters"]
        # Registry uses SFLEX where Sleeper says SUPER_FLEX
        translated = {("SFLEX" if k == "SUPER_FLEX" else k): v for k, v in host_counts.items()}
        non_zero = {k: v for k, v in starters.items() if v > 0}
        assert non_zero == translated
        # The host's second flex is WR/RB-only — a TE is not a legal
        # starter there, so it must not be modelled as a third FLEX.
        assert starters["WRRB_FLEX"] == 1
        assert starters["FLEX"] == 1
        assert sum(starters.values()) == 10

    def test_wrrb_flex_eligibility_is_declared_and_excludes_te(self):
        rs = _registry_league("dynasty_new")["rosterSettings"]
        assert rs["wrrbFlexEligible"] == ["RB", "WR"]
        # And the one canonical resolver consumes it (no second table).
        from src.ros.lineup import configured_slot_eligibility

        elig = configured_slot_eligibility(rs)
        assert elig["WR_RB_FLEX"] == ("RB", "WR")
        assert "TE" not in elig["WR_RB_FLEX"]

    def test_roster_size_taxi_and_team_count(self):
        snap = _dynasty_new_snapshot()
        rs = _registry_league("dynasty_new")["rosterSettings"]
        assert rs["rosterSize"] == len(snap["roster_positions"]) == 27
        assert rs["taxiSize"] == int(snap["settings"]["taxi_slots"]) == 3
        assert rs["teamCount"] == int(snap["total_rosters"]) == 10
        # starters + bench must account for the whole roster
        bench = sum(1 for p in snap["roster_positions"] if str(p).upper() == "BN")
        assert sum(v for v in rs["starters"].values() if v > 0) + bench == rs["rosterSize"]

    def test_best_ball_is_stated_not_defaulted(self):
        snap = _dynasty_new_snapshot()
        assert int(snap["settings"].get("best_ball") or 0) == 0
        assert _registry_league("dynasty_new")["bestBall"] is False

    def test_reserve_slots_are_recorded_in_the_snapshot_only(self):
        """The host runs 3 IR slots.  The registry deliberately does NOT
        model IR yet — no consumer vocabulary for it exists (taxi is
        BRACKETED in ``src/trade/roster_capacity.py`` and reserve players
        sit inside ``players`` the same way), so a registry key would be a
        dead field implying modelling that isn't there.  The fact is
        pinned here against the committed snapshot instead, so the day a
        consumer grows the vocabulary the number is already on record."""
        snap = _dynasty_new_snapshot()
        assert int(snap["settings"]["reserve_slots"]) == 3
        rs = _registry_league("dynasty_new")["rosterSettings"]
        assert "reserveSize" not in rs and "irSize" not in rs

    def test_registry_starters_flatten_through_the_canonical_owner(self):
        """A WRRB_FLEX starters key must reach the lineup owner as the
        WR_RB_FLEX slot, not fall through as an unknown fixed slot."""
        from src.ros.lineup import resolve_starter_slots

        rs = _registry_league("dynasty_new")["rosterSettings"]
        slots, source = resolve_starter_slots(roster_settings=rs)
        assert source == "registry_starters"
        assert len(slots) == 10
        assert slots.count("WR_RB_FLEX") == 1
        assert slots.count("FLEX") == 1
        assert slots.count("SUPER_FLEX") == 1

    def test_dynasty_new_snapshot_cannot_shadow_the_canonical_loader(self):
        """``load_canonical_config`` globs ``config/league_intel/`` root
        non-recursively; the dynasty_new snapshot lives one level down so
        the League Intelligence engine's canonical config stays
        dynasty_main's.  If this ever fails, the snapshot has been moved
        into the root directory — which would silently swap the engine's
        league."""
        from src.league_intel.config import load_canonical_config

        cfg = load_canonical_config()
        assert cfg.sleeper_league_id != str(_dynasty_new_snapshot()["league_id"])


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

    def test_league_active_positions_include_the_kicker_this_league_starts(self):
        """``dynasty_main`` starts ``K: 1``, so K is an active position.

        This assertion used to demand exactly the seven offence+IDP families
        and so PINNED a defect: ``team_impact`` filtered its roster through a
        hardcoded 7-tuple, kickers never reached ``project_starters``, the K
        slot could never be filled, and a traded kicker was invisible to the
        whole payload — while the capacity path (``build_cut_ladder`` ->
        ``assign_lineup``) seated him on the same roster.

        Positions are now derived from the league's OWN resolved slots via the
        canonical eligibility owner, so this reads what the league actually
        starts rather than a constant.
        """
        from src.trade.team_impact import _league_active_positions

        rs = _registry_main()["rosterSettings"]
        assert _league_active_positions(rs) == [
            "QB",
            "RB",
            "WR",
            "TE",
            "DL",
            "LB",
            "DB",
            "K",
        ]


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

        Host truth (W18-F011 / V1-25): the second flex is ``WRRB_FLEX``
        (WR/RB only), not a second RB/WR/TE FLEX.  Under the
        ``flex_priority`` round-robin both flexes therefore open on RB
        (FLEX ranks RB first; WR_RB_FLEX ranks RB first), so demand is
        RB 4 / WR 3 — this test asserted RB 3 / WR 4 while the registry
        modelled a lineup the host does not run.
        """
        from src.trade.suggestions import starter_needs_for_league

        needs = starter_needs_for_league("dynasty_new")

        assert needs["TE"] == 1, "dynasty_new starts one TE"
        assert "DL" not in needs and "LB" not in needs and "DB" not in needs
        assert needs["QB"] == 2  # 1 QB + 1 SUPER_FLEX
        assert needs["RB"] == 4  # 2 RB + FLEX→RB + WR_RB_FLEX→RB
        assert needs["WR"] == 3  # 3 dedicated WR slots
        # Total demand equals total non-K starter slots — nothing invented.
        assert sum(needs.values()) == 10
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
