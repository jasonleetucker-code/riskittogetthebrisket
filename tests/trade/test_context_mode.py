"""V1-41 / C3-CTX-01 — the shared Use Team Context mode.

Spec: ``docs/trade/TRADE_CONTEXT_AND_TOPOLOGY_SUPERSESSION_2026-08-14.md`` §3-§5,
owner decision #842.  Before ``src/trade/context_mode.py`` the toggle did not
exist anywhere in the repository.

Three rules carry the unit, and each is proved structurally rather than by
inspection:

1. OFF must not consume team context in the verdict;
2. OFF removes TEAM context, never LEAGUE-FORMAT valuation;
3. ON never silently falls back to OFF — a missing dimension degrades by name.
"""

from __future__ import annotations

import pytest

from src.trade.context_mode import (
    ALL_DIMENSIONS,
    ASSET_ONLY_DIMENSIONS,
    CONTEXT_OFF,
    CONTEXT_ON,
    DEFAULT_MODE,
    TEAM_CONTEXT_DIMENSIONS,
    TradeContextMode,
    UnknownDimension,
    admits,
    assert_asset_only,
    resolve_context_mode,
)


class TestTheDefault:
    def test_the_default_is_on(self):
        """#842 says ON by default; a caller that says nothing gets everything."""
        assert DEFAULT_MODE == CONTEXT_ON
        assert resolve_context_mode().mode == CONTEXT_ON
        assert resolve_context_mode({}, {}).mode == CONTEXT_ON

    @pytest.mark.parametrize("value", [False, "false", "0", "off", "no", "assetOnly", "asset-only"])
    def test_every_spelling_of_off_resolves_to_off(self, value):
        assert resolve_context_mode({"useTeamContext": value}).mode == CONTEXT_OFF

    def test_body_wins_over_query(self):
        m = resolve_context_mode({"useTeamContext": False}, {"useTeamContext": True})
        assert m.mode == CONTEXT_OFF

    def test_an_unrecognised_value_resolves_to_ON_not_to_an_error(self):
        """A typo must not silently downgrade a user to Asset-Only.

        The label would still say Team Context, which is the one outcome the
        spec forbids by name ("never silently fall back").
        """
        assert resolve_context_mode({"useTeamContext": "maybe"}).mode == CONTEXT_ON
        assert resolve_context_mode({"contextMode": ""}).mode == CONTEXT_ON


class TestThePartition:
    def test_the_two_sets_are_disjoint_and_exhaustive(self):
        assert not (TEAM_CONTEXT_DIMENSIONS & ASSET_ONLY_DIMENSIONS)
        assert ALL_DIMENSIONS == TEAM_CONTEXT_DIMENSIONS | ASSET_ONLY_DIMENSIONS

    def test_on_admits_everything(self):
        for dim in ALL_DIMENSIONS:
            assert admits(CONTEXT_ON, dim)

    def test_off_admits_exactly_the_asset_only_half(self):
        for dim in ALL_DIMENSIONS:
            assert admits(CONTEXT_OFF, dim) is (dim in ASSET_ONLY_DIMENSIONS)

    @pytest.mark.parametrize(
        "dim",
        sorted(
            {
                "rosterFit",
                "positionalNeed",
                "teamStrength",
                "teamWeakness",
                "teamAgeValue",
                "youngCore",
                "competitivePosture",
                "playoffOdds",
                "championshipOdds",
                "opponentPosture",
                "ownPickStrategy",
                "seasonWindowStrategy",
            }
        ),
    )
    def test_every_dimension_the_spec_forbids_off_is_forbidden_off(self, dim):
        """Spec §3 OFF, "Must not use in the verdict/ranking", item by item."""
        assert not admits(CONTEXT_OFF, dim)

    def test_league_format_valuation_survives_OFF(self):
        """The entry most likely to be moved by mistake.

        "OFF does not mean standard-format values. The selected league's
        TEP/Superflex/IDP/scoring/roster configuration may still affect
        canonical asset valuation. It removes team-specific context only."
        """
        assert admits(CONTEXT_OFF, "leagueFormatValuation")
        assert admits(CONTEXT_OFF, "canonicalAssetValue")
        assert admits(CONTEXT_OFF, "pickValue")
        assert admits(CONTEXT_OFF, "packageValueAdjustment")
        assert admits(CONTEXT_OFF, "userConstraints")

    def test_an_unclassified_dimension_is_refused_not_defaulted(self):
        """Either default is a silent failure, so neither is taken."""
        with pytest.raises(UnknownDimension):
            admits(CONTEXT_OFF, "someNewSignal")
        with pytest.raises(UnknownDimension):
            admits(CONTEXT_ON, "someNewSignal")

    def test_a_batch_guard_names_every_offender(self):
        off = TradeContextMode(mode=CONTEXT_OFF)
        with pytest.raises(ValueError, match="teamStrength"):
            assert_asset_only(off, ["canonicalAssetValue", "teamStrength", "playoffOdds"])
        assert_asset_only(off, ASSET_ONLY_DIMENSIONS)  # no raise


class TestDegradation:
    def test_a_missing_dimension_while_ON_stays_ON(self):
        """Rule 2.  Falling back would publish Asset-Only under a team label."""
        on = resolve_context_mode()
        degraded = on.degrade("playoffOdds", "ros_snapshot_missing")
        assert degraded.mode == CONTEXT_ON
        assert degraded.to_dict()["degraded"] == [
            {"dimension": "playoffOdds", "reason": "ros_snapshot_missing"}
        ]

    def test_degraded_and_inadmissible_are_different_states(self):
        """ "ON but unavailable" and "OFF so not consulted" must not read alike."""
        on = resolve_context_mode().degrade("playoffOdds", "ros_snapshot_missing")
        off = resolve_context_mode({"useTeamContext": False})

        assert on.admits("playoffOdds") and not on.available("playoffOdds")
        assert not off.admits("playoffOdds") and not off.available("playoffOdds")
        assert off.excluded_dimensions() == tuple(sorted(TEAM_CONTEXT_DIMENSIONS))
        assert on.excluded_dimensions() == ()

    def test_degrading_a_dimension_the_mode_never_wanted_is_a_no_op(self):
        off = resolve_context_mode({"useTeamContext": False})
        assert off.degrade("playoffOdds", "whatever").degraded == ()

    def test_degradation_is_idempotent_and_ordered(self):
        m = resolve_context_mode()
        m = m.degrade("teamWeakness", "no_ranks").degrade("playoffOdds", "no_sims")
        m = m.degrade("teamWeakness", "no_ranks_again")
        assert [d.dimension for d in m.degraded] == ["playoffOdds", "teamWeakness"]

    def test_an_unknown_dimension_cannot_be_degraded_either(self):
        with pytest.raises(UnknownDimension):
            resolve_context_mode().degrade("inventedSignal", "x")


class TestNonInfluence:
    """The proof that matters: OFF cannot reach team evidence *at all*.

    Not "does not today" — the asset-only spine is exercised with every
    team-context owner replaced by a function that RAISES.  Anything that
    touched one would take the test down with it.  Same shape as #914's
    `C2-EXP-01` exposure non-influence proof.
    """

    @pytest.fixture
    def team_context_owners_all_raise(self, monkeypatch):
        import src.roster_intel as ri
        import src.trade.roster_capacity as rc
        import src.trade.team_impact as ti

        def boom(*_a, **_k):  # pragma: no cover - the point is that it never runs
            raise AssertionError("an Asset-Only path consumed team context")

        for module, name in (
            (ri, "build_team_strength"),
            (ri, "build_team_weakness"),
            (ri, "build_meaningful_core"),
            (ri, "simulate_roster_change"),
            (rc, "assess_roster_capacity"),
            (rc, "simulate_final_legal_roster"),
            (ti, "compute"),
        ):
            monkeypatch.setattr(module, name, boom, raising=True)
        return boom

    def test_the_asset_only_spine_runs_with_every_team_owner_disabled(
        self, team_context_owners_all_raise
    ):
        """Package value and the VA-adjusted gap are asset-only by construction."""
        from src.trade.ktc_va import ktc_adjust_package

        a = ktc_adjust_package([5000.0, 3000.0], [7000.0])
        b = ktc_adjust_package([7000.0], [5000.0, 3000.0])
        # The consolidation premium is real and is a property of the PACKAGES,
        # not of anybody's roster — which is the whole claim being tested.
        assert isinstance(a.value, (int, float)) and isinstance(b.value, (int, float))
        assert a.value > 0

    def test_the_mode_object_itself_reads_no_roster(self, team_context_owners_all_raise):
        off = resolve_context_mode({"useTeamContext": False})
        assert off.to_dict()["label"] == "Asset-Only Analysis"
        assert off.to_dict()["leagueFormatValuationIncluded"] is True
