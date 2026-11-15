"""LI-5 — replacement levels + separated scarcity (spec §19).

Hermetic: every fixture is synthetic.  The live-pool numbers that
motivated the design live in the PR body, not in assertions — a test
that pins live ROS values would fail on every data refresh.
"""

from __future__ import annotations

import hashlib
import json
import random
import statistics

import pytest

from src.league_intel.replacement import (
    DEFAULT_BAND,
    REPLACEMENT_SCHEMA_VERSION,
    compute_replacement_levels,
    compute_scarcity,
    measure_endogenous_starters,
    normalize_base_position,
    waiver_levels,
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


# ── waiver_levels: the one waiver-tier algorithm (LI-5 design P1) ──────
#
# docs/valuation/LI5_REPLACEMENT_CONSOLIDATION_DESIGN_2026-10-21.md §4.1 /
# §8 items 1-2.  ``compute_replacement_levels`` produces its waiver tier by
# calling ``waiver_levels``; these tests pin (a) that the extraction moved
# no byte of the existing output and (b) the helper's own contract.


def _legacy_waiver_tier(free_agents, positions, band):
    """The pre-extraction waiver block of ``compute_replacement_levels``,
    transcribed verbatim (origin/main before LI-5 P1).  Frozen here so the
    parity below compares against what shipped, not against itself."""
    from src.league_intel.replacement import ReplacementLevel, _banded_value

    fa: dict[str, list[float]] = {}
    for p in free_agents:
        base = normalize_base_position(str(p.get("position") or ""))
        if not base:
            continue
        value = float(p.get("rosValue") or 0.0)
        if value > 0:
            fa.setdefault(base, []).append(value)
    for values in fa.values():
        values.sort(reverse=True)
    out = {}
    for pos in positions:
        fa_pool = fa.get(pos, [])
        if fa_pool:
            value, rank, lo, hi = _banded_value(fa_pool, 1, band)
            out[pos] = ReplacementLevel(
                position=pos,
                tier="waiver",
                value=value,
                threshold_rank=rank,
                band_low=lo,
                band_high=hi,
                sample_size=len(fa_pool),
            )
    return out


_FUZZ_POSITIONS = ["QB", "RB", "WR", "TE", "DL", "DE", "DT", "LB", "OLB", "CB", "S", "K", "", None]


def _fuzz_value(rng):
    r = rng.random()
    if r < 0.08:
        return None
    if r < 0.14:
        return 0
    if r < 0.18:
        return -rng.random() * 5
    if r < 0.26:
        return rng.choice([10, 10.0, 25, 50])  # ties
    return round(rng.random() * 100, rng.choice([0, 1, 2, 6]))


def _fuzz_row(rng, pid):
    row = player(pid, rng.choice(_FUZZ_POSITIONS), _fuzz_value(rng))
    if rng.random() < 0.05:
        row.pop("rosValue")
    return row


# Recorded on origin/main BEFORE the extraction (a scratch harness importing
# the pre-change module): sha256 of the sorted-key JSON of
# compute_replacement_levels(TEAMS, SLOTS, free_agents=_GOLDEN_FAS) plus
# compute_scarcity over it.  Covers a tie inside the band, a zero, a DE/OLB
# family collapse, an empty position, and free-agent-only positions (DL, K)
# that the four-tier function must still drop.
_GOLDEN_SHA256 = "a9b348fa423df93a2c689474683a49b6f143cea58975418ad31e1e9d84f331be"
_GOLDEN_FAS = [
    player("fa-wr1", "WR", 18.5),
    player("fa-wr2", "WR", 14),
    player("fa-wr3", "WR", 14),
    player("fa-wr4", "WR", 3),
    player("fa-qb", "QB", 5),
    player("fa-de", "DE", 7),
    player("fa-lb", "OLB", 9),
    player("fa-te0", "TE", 0),
    player("fa-k", "K", 4),
    player("fa-none", "", 30),
]


class TestComputeReplacementLevelsUnchangedByExtraction:
    def test_golden_output_recorded_before_the_extraction(self):
        levels = compute_replacement_levels(TEAMS, SLOTS, free_agents=_GOLDEN_FAS)
        scarcity = compute_scarcity(levels, TEAMS)
        blob = json.dumps(
            {
                "levels": {k: v.to_dict() for k, v in levels.items()},
                "scarcity": {k: v.to_dict() for k, v in scarcity.items()},
            },
            sort_keys=True,
        )
        assert hashlib.sha256(blob.encode()).hexdigest() == _GOLDEN_SHA256
        # The readable half of the same pin.
        assert {k: v.value("waiver") for k, v in levels.items()} == {
            "QB": 5.0,
            "RB": None,
            "WR": 15.5,
            "TE": None,
            "LB": 9.0,
        }

    def test_waiver_tier_equals_the_frozen_legacy_block_over_fuzzed_pools(self):
        for seed in range(400):
            rng = random.Random(seed)
            teams = [
                {"players": [_fuzz_row(rng, f"t{t}-{j}") for j in range(rng.randint(0, 20))]}
                for t in range(rng.randint(0, 6))
            ]
            fas = [_fuzz_row(rng, f"fa{j}") for j in range(rng.randint(0, 30))]
            band = rng.choice([0, 1, 2, 2, 3, 5])
            got = compute_replacement_levels(teams, SLOTS, free_agents=fas, band=band)
            expected = _legacy_waiver_tier(fas, got.keys(), band)
            got_waiver = {
                pos: rep.levels["waiver"].to_dict()
                for pos, rep in got.items()
                if "waiver" in rep.levels
            }
            assert got_waiver == {k: v.to_dict() for k, v in expected.items()}, seed
            # Tier order inside each position is part of the serialized shape.
            for rep in got.values():
                if "waiver" in rep.levels:
                    assert list(rep.levels)[-1] == "waiver", seed

    def test_no_free_agents_still_means_no_waiver_tier(self):
        """The gameplan call passes no free agents, so scarcity stays inert
        (design D8)."""
        levels = compute_replacement_levels(TEAMS, SLOTS)
        assert all("waiver" not in rep.levels for rep in levels.values())
        assert all(
            comp.waiver_scarcity is None for comp in compute_scarcity(levels, TEAMS).values()
        )


class TestWaiverLevels:
    def test_level_is_the_mean_of_free_agent_ranks_one_to_three(self):
        """A targeted mutation of the band index (rank 1 -> 2, or band ->
        band + 1) changes this number."""
        fas = [player(f"w{i}", "WR", v) for i, v in enumerate([40, 30, 20, 10, 5])]
        lvl = waiver_levels(fas, value_key="rosValue")["WR"]
        assert lvl.value == pytest.approx(30.0)
        assert (lvl.threshold_rank, lvl.band_low, lvl.band_high) == (1, 20, 40)
        assert lvl.sample_size == 5
        assert lvl.tier == "waiver"
        assert lvl.position == "WR"

    def test_parity_with_compute_replacement_levels_in_its_own_unit(self):
        """Design §8 item 1: every position both sides emit agrees exactly;
        a position only one side emits is named, not ignored."""
        for seed in range(300):
            rng = random.Random(seed)
            values = [round(rng.random() * 100, 2) for _ in range(rng.randint(1, 15))]
            pos = rng.choice(["QB", "RB", "WR", "TE", "LB"])
            band = rng.choice([0, 1, 2, 3])
            fas = [player(f"fa{i}", pos, v) for i, v in enumerate(values)]
            ref = compute_replacement_levels(TEAMS, SLOTS, free_agents=fas, band=band)
            got = waiver_levels(fas, value_key="rosValue", band=band)
            assert set(got) == {pos}
            assert got[pos] == ref[pos].levels["waiver"], seed

        # A free-agent-only position: the helper emits it, the four-tier
        # function (which needs a priced rostered pool) does not.
        fas = [player("fa-k", "K", 4)]
        assert "K" in waiver_levels(fas, value_key="rosValue")
        assert "K" not in compute_replacement_levels(TEAMS, SLOTS, free_agents=fas)

    def test_unit_is_the_callers_choice_and_the_other_field_is_ignored(self):
        rows = [
            {"position": "DB", "rankDerivedValue": 2000, "rosValue": 1},
            {"position": "DB", "rankDerivedValue": 1800, "rosValue": 99},
            {"position": "DB", "rankDerivedValue": 1600, "rosValue": 50},
        ]
        by_board = waiver_levels(rows, value_key="rankDerivedValue")["DB"]
        by_ros = waiver_levels(rows, value_key="rosValue")["DB"]
        assert by_board.value == pytest.approx(1800.0)
        assert by_ros.value == pytest.approx(50.0)

    def test_value_key_is_required_and_must_name_a_field(self):
        with pytest.raises(TypeError):
            waiver_levels([player("a", "WR", 10)])  # type: ignore[call-arg]
        for bad in ("", None):
            with pytest.raises(ValueError):
                waiver_levels([player("a", "WR", 10)], value_key=bad)  # type: ignore[arg-type]

    def test_missing_zero_and_negative_values_are_excluded_never_zero(self):
        rows = [
            {"position": "WR", "rankDerivedValue": 1500},
            {"position": "WR", "rankDerivedValue": None},
            {"position": "WR", "rankDerivedValue": 0},
            {"position": "WR", "rankDerivedValue": -3},
            {"position": "WR"},
        ]
        lvl = waiver_levels(rows, value_key="rankDerivedValue")["WR"]
        assert lvl.value == 1500.0
        assert lvl.sample_size == 1

    def test_a_position_with_nothing_priced_has_no_level_not_a_zero(self):
        rows = [{"position": "TE", "rankDerivedValue": 0}, {"position": "TE"}]
        assert waiver_levels(rows, value_key="rankDerivedValue") == {}
        assert waiver_levels([], value_key="rankDerivedValue") == {}

    @pytest.mark.parametrize(
        "values,expected",
        [([700], 700.0), ([900, 500], 700.0), ([900, 900, 900, 100], 900.0)],
    )
    def test_thin_pools_and_ties_use_what_exists(self, values, expected):
        rows = [{"position": "LB", "v": x} for x in values]
        lvl = waiver_levels(rows, value_key="v")["LB"]
        assert lvl.value == pytest.approx(expected)
        assert lvl.sample_size == len(values)

    def test_default_position_key_is_the_roster_slot_family(self):
        rows = [
            {"position": "DE", "v": 10},
            {"position": "dt", "v": 8},
            {"position": "CB", "v": 6},
            {"position": "SS", "v": 4},
            {"position": "", "v": 99},
            {"v": 99},
        ]
        got = waiver_levels(rows, value_key="v")
        assert set(got) == {"DL", "DB"}
        assert got["DL"].value == pytest.approx(9.0)

    def test_custom_position_key_keeps_raw_board_positions(self):
        """Displacement keys by the raw upper-cased board position (design
        §4.2); a caller-supplied ``position_of`` is not re-collapsed."""
        rows = [{"position": "de", "v": 10}, {"position": "DL", "v": 4}, {"position": "", "v": 9}]
        got = waiver_levels(
            rows, value_key="v", position_of=lambda r: str(r.get("position") or "").upper()
        )
        assert set(got) == {"DE", "DL"}

    def test_properties_over_seeded_random_pools(self):
        """No Hypothesis dependency in the repo; seeded loops are the
        precedent.  Permutation-invariant, inside its own band, exactly the
        mean of the top 1 + band, and monotone: adding a free agent never
        lowers the level."""
        for seed in range(500):
            rng = random.Random(seed)
            values = [
                rng.choice([rng.randint(1, 50) * 100, 1500]) for _ in range(rng.randint(1, 12))
            ]
            band = rng.choice([0, 1, 2, 3])
            rows = [{"position": "DB", "v": x} for x in values]
            lvl = waiver_levels(rows, value_key="v", band=band)["DB"]

            shuffled = rows[:]
            rng.shuffle(shuffled)
            assert waiver_levels(shuffled, value_key="v", band=band)["DB"] == lvl, seed

            top = sorted(values, reverse=True)[: 1 + band]
            assert lvl.value == pytest.approx(statistics.fmean(top)), seed
            assert lvl.band_low <= lvl.value <= lvl.band_high, seed
            assert lvl.band_high == max(values), seed

            added = lvl.value + rng.randint(0, 30) * 100
            grown_rows = rows + [{"position": "DB", "v": added}]
            grown = waiver_levels(grown_rows, value_key="v", band=band)["DB"]
            assert grown.value >= lvl.value - 1e-9, seed

    def test_a_thin_pool_is_a_mean_of_what_exists_so_a_low_add_can_lower_it(self):
        """Stated rather than hidden: below 1 + band players the window is
        the whole pool, so a weak free agent joining it lowers the level.
        That is LI-5's existing thin-pool behaviour (design §4.4), and
        ``sample_size`` is how a consumer sees it."""
        one = waiver_levels([{"position": "DB", "v": 3100}], value_key="v")["DB"]
        two = waiver_levels(
            [{"position": "DB", "v": 3100}, {"position": "DB", "v": 1000}], value_key="v"
        )["DB"]
        assert (one.value, one.sample_size) == (3100.0, 1)
        assert (two.value, two.sample_size) == (2050.0, 2)

    def test_free_agents_are_read_once_and_not_mutated(self):
        rows = [{"position": "WR", "v": 3}, {"position": "WR", "v": 9}]
        snapshot = json.dumps(rows)
        assert waiver_levels(iter(rows), value_key="v")["WR"].value == pytest.approx(6.0)
        assert json.dumps(rows) == snapshot
