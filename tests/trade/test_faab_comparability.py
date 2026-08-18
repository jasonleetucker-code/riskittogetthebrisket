"""External-league FAAB comparability — normalization, gating, tiers.

The owner spec (``docs/FAAB_MARKET_SIGNAL_NORMALIZATION_2026-08-14.md``) makes
three demands of any external waiver observation, and these tests are the ones
that hold:

* §3  every bid is normalized to percent of that season's ORIGINAL budget, and
      a missing budget is UNAVAILABLE — never an assumed $100 denominator;
* §5  a league we cannot prove comparable is excluded (fail closed);
* §7  format differences matter differently by position — offense-only leagues
      may never supply an IDP clearing-price comp.

Measured against the live KTC feed on 2026-08-18 (200 rows / 86 leagues), the
gate these tests describe removes 39 multi-copy rows (median 0.20% of budget
against 1.00% for single-copy leagues) and 5-7 rows from leagues whose entire
FAAB budget is a dollar.
"""

from __future__ import annotations

import pytest

from src.trade import faab_comparability as FC


BRISKET = FC.TargetFormat(
    teams=12, superflex=True, tep=True, is_2te=True, idp=True, original_budget=100.0
)


def _fmt(**kw):
    base = dict(
        superflex=True,
        tep_level=1,
        is_2te=True,
        teams=12,
        rosters_per_player=1,
        has_idp_slots=False,
        original_budget=200.0,
    )
    base.update(kw)
    return FC.SourceFormat(**base)


# ── §3 Budget normalization ──────────────────────────────────────────


class TestNormalization:
    @pytest.mark.parametrize(
        "bid,budget,share",
        [
            (40, 200, 0.20),  # the owner's own worked example
            (100, 1000, 0.10),
            (20, 100, 0.20),  # already on the $100 basis — identity
            (0, 200, 0.0),  # a $0 bid is a REAL observation
            (200, 200, 1.0),  # all-in
        ],
    )
    def test_share_is_percent_of_original_budget(self, bid, budget, share):
        assert FC.normalized_bid_share(bid, budget) == pytest.approx(share)

    def test_percentage_is_invariant_across_the_budget_eras(self):
        """This league ran $1,000, then $200, then $100.  The same
        proportional commitment must read identically in all three."""
        eras = [(100, 1000), (20, 200), (10, 100)]
        for bid, budget in eras:
            assert FC.normalized_bid_share(bid, budget) == pytest.approx(0.10)

    @pytest.mark.parametrize(
        "bid,budget",
        [(40, None), (40, 0), (40, -5), (40, "unknown"), (None, 200), (-1, 200)],
    )
    def test_missing_or_invalid_budget_is_unavailable_not_a_default(self, bid, budget):
        """MISSING IS NEVER ZERO — and never an assumed $100 either.  The
        budget is the DENOMINATOR, so fabricating one produces a percentage
        wrong by up to 10x, not slightly off."""
        assert FC.normalized_bid_share(bid, budget) is None

    def test_equivalent_on_the_current_hundred_dollar_scale(self):
        assert FC.equivalent_on_budget(FC.normalized_bid_share(40, 200), 100) == pytest.approx(20.0)
        assert FC.equivalent_on_budget(FC.normalized_bid_share(100, 1000), 100) == pytest.approx(
            10.0
        )

    def test_unknown_propagates_through_the_conversion(self):
        assert FC.equivalent_on_budget(None, 100) is None
        assert FC.equivalent_on_budget(0.2, None) is None
        assert FC.equivalent_on_budget(0.2, 0) is None


# ── Parsing the vendor's format evidence ─────────────────────────────


class TestSourceFormatParsing:
    RAW = {
        "id": "41915",
        "teams": 12,
        "qBs": 2,
        "tep": 3,
        "is2TE": True,
        "rostersPerPlayer": 1,
        "totalBlindBidWaiverAmount": "1000",
        "leagueStartingLineup": {
            "position": [{"name": "QB"}, {"name": "RB"}, {"name": "TE"}, {"name": "Def"}]
        },
    }

    def test_reads_the_raw_vendor_shape(self):
        fmt = FC.source_format_from_settings(self.RAW)
        assert (fmt.superflex, fmt.tep_level, fmt.is_2te, fmt.teams) == (True, 3, True, 12)
        assert fmt.rosters_per_player == 1
        assert fmt.original_budget == 1000.0

    def test_a_team_defence_slot_is_not_idp(self):
        """``Def`` is a team D/ST.  Measured, every non-offense slot in the
        live feed is one — reading it as IDP would let offense-only leagues
        price linebackers."""
        assert FC.source_format_from_settings(self.RAW).has_idp_slots is False

    def test_an_individual_defender_slot_is_idp(self):
        raw = dict(self.RAW)
        raw["leagueStartingLineup"] = {"position": [{"name": "QB"}, {"name": "LB"}]}
        assert FC.source_format_from_settings(raw).has_idp_slots is True

    def test_a_missing_lineup_is_unknown_not_offense_only(self):
        raw = {k: v for k, v in self.RAW.items() if k != "leagueStartingLineup"}
        assert FC.source_format_from_settings(raw).has_idp_slots is None

    def test_a_renamed_key_reads_as_unstated_never_as_a_default(self):
        """If KTC renames ``qBs``, every league must become UNKNOWN — not
        1QB.  Silently defaulting is what turns a parse failure into a
        confident, wrong market."""
        fmt = FC.source_format_from_settings({"teams": 12})
        assert fmt.superflex is None and fmt.tep_level is None and fmt.tep is None
        assert fmt.rosters_per_player is None and fmt.original_budget is None

    def test_the_persisted_shape_classifies_identically(self):
        """A stored row and a freshly fetched one must reach the same verdict,
        or re-classification on read would disagree with the fetch gate."""
        stored = {
            "superflex": True,
            "tepLevel": 3,
            "is2TE": True,
            "teams": 12,
            "rostersPerPlayer": 1,
            "originalBudget": 1000.0,
            "hasIdpSlots": False,
        }
        assert FC.classify(FC.source_format_from_settings(stored), BRISKET) == FC.classify(
            FC.source_format_from_settings(self.RAW), BRISKET
        )

    def test_tep_level_and_tep_on_off_are_different_questions(self):
        assert FC.source_format_from_settings({"tep": 0}).tep is False
        assert FC.source_format_from_settings({"tep": 1}).tep is True
        assert FC.source_format_from_settings({"tep": 3}).tep is True


# ── §5 Hard eligibility — fail closed ────────────────────────────────


class TestHardExclusions:
    def _reasons(self, **kw):
        return set(FC.classify(_fmt(**kw), BRISKET).reasons)

    def test_a_multi_copy_league_is_excluded(self):
        """``rostersPerPlayer`` > 1 means the same player may sit on several
        rosters at once, so there is no waiver scarcity and claims clear near
        nothing.  Measured: 39 of the 106 rows the old gate admitted, at a 5x
        lower median."""
        v = FC.classify(_fmt(rosters_per_player=3), BRISKET)
        assert v.excluded and "multi_copy_league" in v.reasons

    def test_unstated_roster_exclusivity_is_excluded_too(self):
        """Silence is not evidence of exclusivity."""
        v = FC.classify(_fmt(rosters_per_player=None), BRISKET)
        assert v.excluded and "roster_exclusivity_unknown" in v.reasons

    def test_multi_copy_can_be_admitted_by_explicit_policy(self):
        policy = FC.ComparabilityPolicy(allow_multi_copy_leagues=True)
        assert not FC.classify(_fmt(rosters_per_player=3), BRISKET, policy=policy).excluded

    def test_a_degenerate_budget_is_excluded(self):
        """A league whose entire FAAB is $1 cannot express a price, only
        claimed / did not.  Measured: 7 such rows, every one 0.00%."""
        assert "degenerate_budget" in self._reasons(original_budget=1.0)

    def test_a_missing_budget_is_excluded(self):
        assert "budget_unknown" in self._reasons(original_budget=None)
        assert "budget_unknown" in self._reasons(original_budget=0)

    def test_superflex_mismatch_and_unknown_both_exclude(self):
        assert "superflex_mismatch" in self._reasons(superflex=False)
        assert "superflex_unknown" in self._reasons(superflex=None)

    def test_tep_mismatch_and_unknown_both_exclude(self):
        assert "tep_mismatch" in self._reasons(tep_level=0)
        assert "tep_unknown" in self._reasons(tep_level=None)

    def test_team_count_tolerance(self):
        assert not FC.classify(_fmt(teams=14), BRISKET).excluded
        assert "team_count_mismatch" in self._reasons(teams=16)
        assert "team_count_unknown" in self._reasons(teams=None)

    def test_a_one_qb_target_excludes_superflex_evidence(self):
        """The gate is symmetric — it is about the TARGET league, not about
        superflex being intrinsically better (spec §7: QB comparability)."""
        one_qb = FC.TargetFormat(teams=12, superflex=False, tep=True, is_2te=True)
        assert FC.classify(_fmt(superflex=True), one_qb).excluded
        assert not FC.classify(_fmt(superflex=False), one_qb).excluded

    def test_every_failing_reason_is_reported_not_just_the_first(self):
        v = FC.classify(_fmt(superflex=False, tep_level=0, rosters_per_player=4), BRISKET)
        assert {"superflex_mismatch", "tep_mismatch", "multi_copy_league"} <= set(v.reasons)


# ── §7 Tiers — reported, never weighted ──────────────────────────────


class TestTiers:
    def test_an_exact_format_match_is_tier_a(self):
        assert FC.classify(_fmt(), BRISKET).tier == FC.TIER_A

    def test_a_single_soft_mismatch_demotes_to_b(self):
        v = FC.classify(_fmt(is_2te=False), BRISKET)
        assert v.tier == FC.TIER_B and "two_te_mismatch" in v.reasons and not v.excluded

    def test_two_soft_mismatches_demote_to_c(self):
        v = FC.classify(_fmt(is_2te=False, teams=13), BRISKET)
        assert v.tier == FC.TIER_C
        assert {"two_te_mismatch", "team_count_offset"} <= set(v.reasons)

    def test_an_unstated_two_te_setting_demotes_rather_than_excludes(self):
        """Unknown must not pass as a match — but a soft setting is not worth
        discarding an otherwise comparable league over."""
        v = FC.classify(_fmt(is_2te=None), BRISKET)
        assert not v.excluded and "two_te_unknown" in v.reasons

    def test_tep_severity_gap_needs_a_known_target_level(self):
        """TE+ and TE+++ are both 'TEP on' and are not the same market — but
        the gap can only be measured when the target's own level is known.
        An unknown target level demotes nothing rather than guessing."""
        assert "tep_severity_gap" not in FC.classify(_fmt(tep_level=3), BRISKET).reasons
        levelled = FC.TargetFormat(
            teams=12, superflex=True, tep=True, is_2te=True, tep_level=1, idp=True
        )
        assert "tep_severity_gap" in FC.classify(_fmt(tep_level=3), levelled).reasons
        assert "tep_severity_gap" not in FC.classify(_fmt(tep_level=2), levelled).reasons

    def test_a_tier_is_never_an_exclusion(self):
        for kw in ({}, {"is_2te": False}, {"is_2te": False, "teams": 14}):
            assert not FC.classify(_fmt(**kw), BRISKET).excluded


# ── §7 Position comparability ────────────────────────────────────────


class TestPositionComparability:
    @pytest.mark.parametrize("pos", ["LB", "DL", "DB", "EDGE", "CB", "S"])
    def test_idp_positions_need_idp_evidence(self, pos):
        assert FC.is_idp_position(pos)
        assert not FC.population_prices_position(pos, any_idp_source=False)

    @pytest.mark.parametrize("pos", ["QB", "RB", "WR", "TE", "K", None, ""])
    def test_offense_is_priceable_by_an_offense_only_population(self, pos):
        assert FC.population_prices_position(pos, any_idp_source=False)

    def test_an_idp_league_in_the_population_unlocks_idp_pricing(self):
        """Derived from what the retained rows actually contain, so it
        self-corrects the day the feed carries an IDP league."""
        assert FC.population_prices_position("LB", any_idp_source=True)


# ── Target profile comes from the league, not from Brisket ───────────


class TestTargetFormat:
    def test_derived_from_the_target_leagues_own_settings(self):
        target = FC.TargetFormat.from_roster_settings(
            {"teamCount": 10, "starters": {"QB": 1, "TE": 1, "SFLEX": 1}},
            league_key="other",
            scoring_profile="superflex_ppr1",
            idp_enabled=False,
        )
        assert (target.teams, target.superflex, target.is_2te, target.tep, target.idp) == (
            10,
            True,
            False,
            False,
            False,
        )

    def test_the_shipped_brisket_entry_resolves_to_its_real_format(self):
        """Read from the shipped registry JSON directly.  ``conftest`` points
        the live registry at a nonexistent path so tests never touch Sleeper,
        so this pins the CONFIG rather than the process-wide singleton."""
        import json

        from src.utils.config_loader import repo_root

        registry = json.loads(
            (repo_root() / "config" / "leagues" / "registry.json").read_text(encoding="utf-8")
        )
        entry = next(e for e in registry["leagues"] if e["key"] == "dynasty_main")
        target = FC.TargetFormat.from_roster_settings(
            entry["rosterSettings"],
            league_key=entry["key"],
            scoring_profile=entry["scoringProfile"],
            idp_enabled=entry["idpEnabled"],
        )
        assert (target.teams, target.superflex, target.is_2te, target.tep, target.idp) == (
            12,
            True,
            True,
            True,
            True,
        )

    def test_an_unresolvable_league_degrades_rather_than_raising(self):
        """A registry that cannot answer must not take the waiver page down.
        The result is a documented generic shape, and every observation it
        admits is still gated by the hard rules above."""
        target = FC.TargetFormat.from_registry("no_such_league")
        assert isinstance(target, FC.TargetFormat)


# ── Policy plumbing ──────────────────────────────────────────────────


class TestPolicy:
    def test_reads_the_shipped_faab_config(self):
        from src.trade.faab_engine import FaabConfig

        policy = FC.ComparabilityPolicy.from_config(FaabConfig())
        assert policy.allow_multi_copy_leagues is False
        assert policy.min_original_budget > 0
        assert policy.max_file_age_days > 0

    def test_a_plain_dict_works_too(self):
        policy = FC.ComparabilityPolicy.from_config(
            {"crowdComparability": {"minOriginalBudget": 25}}
        )
        assert policy.min_original_budget == 25

    def test_no_config_degrades_to_the_documented_defaults(self):
        assert FC.ComparabilityPolicy.from_config(None) == FC.ComparabilityPolicy()

    def test_the_dataclass_defaults_match_the_shipped_config(self):
        """``ComparabilityPolicy`` carries defaults in two places — the field
        declarations and the ``num(...)`` fallbacks in ``from_config``.  The
        parity test pins the second against ``faab.json``; this pins the
        first, so a corrupt config degrades to what the config says rather
        than to a third, silent set of numbers."""
        from src.trade.faab_engine import FaabConfig

        assert FC.ComparabilityPolicy.from_config(FaabConfig()) == FC.ComparabilityPolicy()
