"""LI-5 — replacement levels + separated scarcity (spec §19).

Hermetic: every fixture is synthetic.  The live-pool numbers that
motivated the design live in the PR body, not in assertions — a test
that pins live ROS values would fail on every data refresh.
"""

from __future__ import annotations

import pytest

from src.league_intel.replacement import (
    DEFAULT_BAND,
    REPLACEMENT_SCHEMA_VERSION,
    compute_replacement_levels,
    compute_scarcity,
    measure_endogenous_starters,
    normalize_base_position,
)

SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX", "LB", "LB"]


def player(pid, pos, value, fp=()):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "confidence": 1.0,
        "injured": False,
        "bye": False,
        "fantasyPositions": list(fp),
    }


def make_team(idx, scale=1.0):
    """A roster deep enough to fill every slot, scaled per team."""
    spec = [
        ("QB", 3, 40),
        ("RB", 4, 30),
        ("WR", 5, 25),
        ("TE", 2, 20),
        ("LB", 3, 15),
    ]
    players = []
    for pos, n, base in spec:
        for i in range(n):
            players.append(player(f"t{idx}-{pos}{i}", pos, round((base - i * 4) * scale, 2)))
    return {"rosterId": idx, "teamName": f"Team{idx}", "players": players}


TEAMS = [make_team(i, scale=1.0 - i * 0.05) for i in range(6)]


class TestBasePositionNormalization:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("DE", "DL"),
            ("DT", "DL"),
            ("EDGE", "DL"),
            ("OLB", "LB"),
            ("CB", "DB"),
            ("S", "DB"),
            ("SS", "DB"),
            ("WR", "WR"),
            ("k", "K"),
            ("", ""),
        ],
    )
    def test_collapses_to_slot_family(self, raw, expected):
        assert normalize_base_position(raw) == expected


class TestEndogenousStarters:
    def test_measures_actual_fill_not_preassigned_share(self):
        measured = measure_endogenous_starters(TEAMS, SLOTS)
        assert measured.team_count == 6
        # 10 slots per team, all fillable by these rosters.
        assert sum(measured.starters_per_team.values()) == pytest.approx(10.0)

    def test_super_flex_goes_to_the_best_available_not_an_even_split(self):
        """One QB-heavy roster: SUPER_FLEX must take the QB, so QB
        starters/team is 2.0 — an even 1/4 split would say 1.25."""
        team = {
            "players": [
                player("q1", "QB", 100),
                player("q2", "QB", 90),
                player("r1", "RB", 10),
                player("r2", "RB", 9),
                player("w1", "WR", 8),
                player("w2", "WR", 7),
                player("t1", "TE", 6),
            ]
        }
        measured = measure_endogenous_starters([team], ["QB", "SUPER_FLEX", "RB", "WR"])
        assert measured.starters_per_team["QB"] == 2.0
        assert measured.slot_fill["SUPER_FLEX"] == {"QB": 1}

    def test_flex_skips_a_position_that_never_wins_the_slot(self):
        team = {
            "players": [
                player("r1", "RB", 50),
                player("r2", "RB", 40),
                player("r3", "RB", 30),
                player("t1", "TE", 5),
            ]
        }
        measured = measure_endogenous_starters([team], ["RB", "FLEX"])
        assert measured.slot_fill["FLEX"] == {"RB": 1}
        assert measured.starters_per_team.get("TE", 0.0) == 0.0

    def test_hybrid_counts_against_its_own_position_pool_not_the_slot(self):
        """A DL/LB slotted at LB still consumes a DL-pool body.

        Renamed 2026-07-30.  This was
        ``test_hybrid_counts_toward_the_slot_it_actually_fills``, whose
        name asserted the OPPOSITE of its assertion — the hybrid fills the
        LB slot, yet the assertion (correctly) counts it as DL.  Acting on
        the name and switching the attribution to the slot breaks
        ``compute_scarcity``: it builds ``by_pos`` from the players'
        nominal positions and uses ``starters_n`` to index into it, so a
        slot-derived count would index a pool it no longer denotes, and
        ``lineupScarcity`` — the only live axis of the league-adjusted
        overlay — is computed off that index.

        ``starters_per_team`` answers "how many DL-pool bodies do lineups
        consume".  "How many DL does the league start" is a different
        question; ``slot_fill`` answers that one, and the test below pins
        it.
        """
        team = {
            "players": [
                player("h", "DL", 50, fp=("DL", "LB")),
                player("d", "DL", 40),
            ]
        }
        measured = measure_endogenous_starters([team], ["DL", "LB"])
        assert measured.starters_per_team["DL"] == 2.0
        assert measured.slot_fill["LB"] == {"DL": 1}

    def test_fixed_slots_are_filled_exactly_as_many_times_as_they_exist(self):
        """The league starts 3 at each IDP position — pinned on the slots.

        This is the invariant a reader expects ``starters_per_team`` to
        show and it deliberately does not (see above).  It belongs here,
        on ``slot_fill``, where it is true regardless of how many hybrids
        Sleeper labels one way and the optimizer slots another.
        """
        team = {
            "players": [
                player("h", "DL", 50, fp=("DL", "LB")),
                player("d1", "DL", 40),
                player("d2", "DL", 30),
                player("d3", "DL", 20),
                player("l1", "LB", 18),
                player("l2", "LB", 16),
                player("b1", "DB", 14),
                player("b2", "DB", 12),
                player("b3", "DB", 10),
            ]
        }
        slots = ["DL"] * 3 + ["LB"] * 3 + ["DB"] * 3
        measured = measure_endogenous_starters([team], slots)

        for pos in ("DL", "LB", "DB"):
            filled = sum(measured.slot_fill.get(pos, {}).values())
            assert filled == 3, f"{pos} slots filled {filled} times, expected 3"
        # ...and the hybrid is one of the bodies doing it, counted under
        # its own position in the diagnostic.
        assert measured.slot_fill["LB"].get("DL", 0) == 1

    def test_marginal_starter_is_the_weakest_started_at_the_position(self):
        measured = measure_endogenous_starters([make_team(0)], ["WR", "WR", "WR"])
        # WRs are 25, 21, 17, 13, 9 — three start, marginal is 17.
        assert measured.marginal_starter_values["WR"] == [17.0]


class TestReplacementLevels:
    def test_four_tiers_present(self):
        fas = [player("fa-wr", "WR", 12), player("fa-qb", "QB", 5)]
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=fas)
        assert levels["WR"].levels.keys() >= {
            "starter",
            "bestBallStarter",
            "roster",
            "waiver",
        }
        assert levels["TE"].levels.keys() >= {"starter", "bestBallStarter", "roster"}

    def test_tiers_are_ordered_starter_above_bestball_above_roster(self):
        levels = compute_replacement_levels(TEAMS, SLOTS)
        for pos in ("QB", "RB", "WR"):
            rep = levels[pos]
            assert rep.value("starter") >= rep.value("bestBallStarter")
            assert rep.value("bestBallStarter") >= rep.value("roster")

    def test_starter_level_is_median_of_team_marginals(self):
        levels = compute_replacement_levels(TEAMS, SLOTS)
        measured = measure_endogenous_starters(TEAMS, SLOTS)
        import statistics

        expected = statistics.median(measured.marginal_starter_values["WR"])
        assert levels["WR"].value("starter") == pytest.approx(expected)

    def test_bestball_is_the_deepest_dip_not_the_typical_one(self):
        levels = compute_replacement_levels(TEAMS, SLOTS)
        rep = levels["WR"]
        assert rep.value("bestBallStarter") <= rep.value("starter")

    def test_unpriced_players_excluded_from_levels_but_counted(self):
        """A bench full of unranked dart throws must not drag the
        roster tier to zero — but the roster count still shows them."""
        teams = [
            {
                "players": [
                    player("a", "WR", 30),
                    player("b", "WR", 20),
                    player("c", "WR", 10),
                    player("dead1", "WR", 0),
                    player("dead2", "WR", 0),
                ]
            }
        ]
        levels = compute_replacement_levels(teams, ["WR"], band=0)
        rep = levels["WR"]
        assert rep.value("roster") == 10.0  # not 0.0
        assert rep.rostered_count == 5
        assert rep.priced_count == 3

    def test_band_smooths_the_rank_indexed_tiers(self):
        teams = [{"players": [player(f"w{i}", "WR", 100 - i * 10) for i in range(10)]}]
        tight = compute_replacement_levels(teams, ["WR"], band=0)["WR"].value("roster")
        wide = compute_replacement_levels(teams, ["WR"], band=2)["WR"].value("roster")
        assert tight == 10.0  # exactly the last player
        assert wide > tight  # averaged with the ranks above it

    def test_default_band_is_two(self):
        assert DEFAULT_BAND == 2
        assert REPLACEMENT_SCHEMA_VERSION == 1

    def test_waiver_tier_reads_the_best_free_agent(self):
        fas = [player("fa1", "WR", 18), player("fa2", "WR", 14), player("fa3", "WR", 2)]
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=fas, band=0)
        assert levels["WR"].value("waiver") == 18.0

    def test_endogenous_measurement_can_be_reused(self):
        measured = measure_endogenous_starters(TEAMS, SLOTS)
        a = compute_replacement_levels(TEAMS, SLOTS, endogenous=measured)
        b = compute_replacement_levels(TEAMS, SLOTS)
        assert a["WR"].to_dict() == b["WR"].to_dict()

    def test_empty_league_is_not_a_crash(self):
        assert compute_replacement_levels([], SLOTS) == {}


class TestScarcityComponents:
    def test_six_components_kept_separate(self):
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=[player("fa", "WR", 5)])
        scar = compute_scarcity(levels, TEAMS)
        d = scar["WR"].to_dict()
        assert set(d) == {
            "position",
            "lineupScarcity",
            "rosterScarcity",
            "waiverScarcity",
            "eliteSeparation",
            "starterSeparation",
            "replacementGap",
        }

    def test_scarcity_ratios_are_bounded(self):
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=[player("fa", "WR", 5)])
        for comp in compute_scarcity(levels, TEAMS).values():
            for v in (comp.lineup_scarcity, comp.roster_scarcity, comp.waiver_scarcity):
                if v is not None:
                    assert 0.0 <= v <= 1.0

    def test_waiver_scarcity_high_when_nothing_available(self):
        """No free agents worth anything → losing a starter hurts."""
        levels = compute_replacement_levels(
            TEAMS, SLOTS, free_agents=[player("fa", "QB", 0.5)], band=0
        )
        scar = compute_scarcity(levels, TEAMS)
        assert scar["QB"].waiver_scarcity > 0.9

    def test_waiver_scarcity_low_when_replacements_abound(self):
        rich = [player(f"fa{i}", "QB", 40) for i in range(5)]
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=rich, band=0)
        scar = compute_scarcity(levels, TEAMS)
        assert scar["QB"].waiver_scarcity == pytest.approx(0.0)

    def test_missing_waiver_data_yields_none_not_zero(self):
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=[])
        scar = compute_scarcity(levels, TEAMS)
        assert scar["WR"].waiver_scarcity is None
        assert scar["WR"].replacement_gap is None

    def test_components_are_not_collapsed_into_one_score(self):
        """Guard the design decision: a position can be top-heavy AND
        have deep waivers, and the two must stay distinguishable."""
        levels = compute_replacement_levels(
            TEAMS, SLOTS, free_agents=[player("fa", "WR", 22)], band=0
        )
        scar = compute_scarcity(levels, TEAMS)["WR"]
        assert scar.elite_separation is not None
        assert scar.waiver_scarcity is not None
        # Distinct signals, not derived from one another.
        assert scar.elite_separation != scar.waiver_scarcity


class TestRevealedDemand:
    """Rostership measured from real rosters — the input rosterScarcity
    was waiting for.  Evidence about DEMAND, not about value."""

    REQ = {"QB": 1, "RB": 2, "TE": 2, "LB": 3}

    @staticmethod
    def _teams(te_each=5, n=6):
        out = []
        for t in range(n):
            players = []
            for pos, k in (("QB", 4), ("RB", 7), ("TE", te_each), ("LB", 6)):
                for i in range(k):
                    players.append(player(f"t{t}-{pos}{i}", pos, 5000 - i * 400))
            out.append({"players": players})
        return out

    def test_counts_and_spread_reported(self):
        from src.league_intel.replacement import measure_revealed_demand

        d = measure_revealed_demand(self._teams(), self.REQ)
        te = d["TE"]
        assert te.per_team == pytest.approx(5.0)
        assert te.team_count == 6
        assert te.total_rostered == 30
        assert te.per_team_min == te.per_team_max == 5
        assert te.per_team_sd == pytest.approx(0.0)

    def test_demand_ratio_is_rostered_over_required(self):
        from src.league_intel.replacement import measure_revealed_demand

        d = measure_revealed_demand(self._teams(), self.REQ)
        assert d["TE"].demand_ratio == pytest.approx(2.5)  # 5 rostered / 2 required

    def test_spread_is_visible_when_managers_differ(self):
        """n=12-ish leagues: the spread matters as much as the mean."""
        from src.league_intel.replacement import measure_revealed_demand

        teams = self._teams(te_each=2, n=3) + self._teams(te_each=8, n=3)
        d = measure_revealed_demand(teams, self.REQ)
        assert d["TE"].per_team == pytest.approx(5.0)
        assert d["TE"].per_team_sd > 2.5  # mean alone would hide this
        assert (d["TE"].per_team_min, d["TE"].per_team_max) == (2, 8)

    def test_supply_constraint_is_separated_from_demand(self):
        """You cannot roster what does not exist — rostership is
        jointly determined, and the flag says so."""
        from src.league_intel.replacement import measure_revealed_demand

        teams = self._teams()
        tight = measure_revealed_demand(teams, self.REQ, priced_supply={"TE": 30})
        loose = measure_revealed_demand(teams, self.REQ, priced_supply={"TE": 200})
        assert tight["TE"].share_of_supply == pytest.approx(1.0)
        assert tight["TE"].supply_constrained is True
        assert loose["TE"].supply_constrained is False

    def test_unknown_supply_is_none_not_zero(self):
        from src.league_intel.replacement import measure_revealed_demand

        d = measure_revealed_demand(self._teams(), self.REQ)
        assert d["TE"].share_of_supply is None
        assert d["TE"].supply_constrained is False

    def test_startable_floor_separates_stashes_from_depth(self):
        from src.league_intel.replacement import measure_revealed_demand

        teams = [
            {
                "players": [
                    player("a", "TE", 5000),
                    player("b", "TE", 4000),
                    player("c", "TE", 10),  # deep-bench dart throw
                ]
            }
        ]
        d = measure_revealed_demand(teams, {"TE": 2}, startable_floor=1000)
        assert d["TE"].per_team == 3.0
        assert d["TE"].startable_per_team == 2.0

    def test_scale_mismatch_yields_zero_startable_not_a_crash(self):
        """Documents the trap: a consensus-scale floor against
        rosValue-scale inputs silently returns zero."""
        from src.league_intel.replacement import measure_revealed_demand

        teams = [{"players": [player("a", "TE", 80.0), player("b", "TE", 60.0)]}]
        d = measure_revealed_demand(teams, {"TE": 2}, startable_floor=1000)
        assert d["TE"].per_team == 2.0
        assert d["TE"].startable_per_team == 0.0  # scale mismatch, not absence

    def test_serializes(self):
        from src.league_intel.replacement import measure_revealed_demand

        d = measure_revealed_demand(self._teams(), self.REQ, priced_supply={"TE": 90})
        out = d["TE"].to_dict()
        assert out["position"] == "TE"
        assert "demandRatio" in out and "supplyConstrained" in out


class TestUnpricedStarterEdgeCase:
    """A started player with no ROS read must not define the floor."""

    def test_unpriced_starter_does_not_zero_the_bestball_tier(self):
        teams = [
            {"players": [player("a", "WR", 30), player("b", "WR", 20)]},
            {"players": [player("c", "WR", 25), player("dead", "WR", 0)]},
        ]
        levels = compute_replacement_levels(teams, ["WR", "WR"], band=0)
        rep = levels["WR"]
        assert rep.value("bestBallStarter") > 0.0
        assert rep.value("starter") > 0.0
