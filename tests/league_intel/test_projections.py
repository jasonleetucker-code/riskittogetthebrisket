"""Tests for LI-6 projection re-scoring + derived categories.

Covers the four things LI-6 promises:

1. the manual-import contract (the only unblocked ingestion path),
2. derived categories with provenance tiers, off realized play-by-play,
3. re-scoring through the LI-2 exact scorer,
4. cross-source disagreement.

Plus a worked end-to-end case so the path is provably exercised, not
just theoretically wired: CSV on disk → Sleeper keys → derived
categories → exact scorer → league points.

No network, no clock. The scorer is imported, never re-implemented.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.league_intel.projections import (
    DERIVED_CATEGORIES,
    MANUAL_IMPORT_COLUMNS,
    PROVENANCE_TIERS,
    TIER_CONFIDENCE,
    CategoryProvenance,
    PlayerProjection,
    build_rate_profiles,
    derive_categories,
    measure_disagreement,
    parse_manual_import,
    score_projection,
    score_projections,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="module")
def scoring():
    """The league's real 141-key scoring settings."""
    raw = json.loads((FIXTURES / "scoring_settings_2025.json").read_text())
    return raw.get("scoring_settings", raw)


@pytest.fixture(scope="module")
def import_csv():
    return (FIXTURES / "manual_projection_import.csv").read_text()


# ── Provenance contract ──────────────────────────────────────────────
class TestProvenanceContract:
    def test_tiers_ordered_best_to_worst(self):
        assert PROVENANCE_TIERS[0] == "direct"
        assert PROVENANCE_TIERS[-1] == "manual"

    def test_derived_confidence_strictly_below_direct(self):
        """The spec's core rule: a derived value never outranks a direct one."""
        direct = TIER_CONFIDENCE["direct"]
        for tier in ("derived-player-history", "derived-archetype", "derived-position"):
            assert TIER_CONFIDENCE[tier] < direct, tier

    def test_derived_tiers_monotonically_decreasing(self):
        assert (
            TIER_CONFIDENCE["derived-player-history"]
            > TIER_CONFIDENCE["derived-archetype"]
            > TIER_CONFIDENCE["derived-position"]
        )

    def test_confidence_exposed_on_provenance(self):
        p = CategoryProvenance("rec_0_4", "derived-archetype")
        assert p.confidence == TIER_CONFIDENCE["derived-archetype"]
        assert p.to_dict()["tier"] == "derived-archetype"


# ── Manual-import adapter ────────────────────────────────────────────
class TestManualImport:
    def test_parses_every_row(self, import_csv):
        projections, warnings = parse_manual_import(import_csv, source="fbg-manual")
        assert len(projections) == 5
        assert [p.player_name for p in projections][:2] == ["Josh Allen", "Bijan Robinson"]
        assert not [w for w in warnings if "skipped" in w]

    def test_stats_land_on_sleeper_keys_as_direct(self, import_csv):
        projections, _ = parse_manual_import(import_csv, source="fbg-manual")
        allen = projections[0]
        assert allen.stats["pass_yd"] == 4200.0
        assert allen.stats["pass_td"] == 32.0
        assert allen.provenance["pass_yd"].tier == "direct"
        assert allen.source == "fbg-manual"
        assert allen.horizon == "ros"

    def test_unknown_columns_warn_rather_than_vanish(self, scoring):
        csv_text = "player_name,position,rec,mystery_metric\nA Player,WR,50,9\n"
        projections, warnings = parse_manual_import(
            csv_text, source="s", scoring_keys=scoring.keys()
        )
        assert projections[0].stats == {"rec": 50.0}
        assert any("mystery_metric" in w for w in warnings)

    def test_bad_row_does_not_kill_the_import(self, scoring):
        csv_text = (
            "player_name,position,rec\n"
            ",WR,50\n"  # missing name
            "Good Player,WR,60\n"
            "Bad Number,WR,not-a-number\n"
        )
        projections, warnings = parse_manual_import(
            csv_text, source="s", scoring_keys=scoring.keys()
        )
        assert [p.player_name for p in projections] == ["Good Player"]
        assert len(warnings) >= 2

    def test_weekly_rows_flip_horizon(self, scoring):
        csv_text = "player_name,position,week,rec\nA Player,WR,7,6\n"
        projections, _ = parse_manual_import(csv_text, source="s", scoring_keys=scoring.keys())
        assert projections[0].horizon == "week"
        assert projections[0].week == 7

    def test_empty_csv_is_reported_not_raised(self):
        projections, warnings = parse_manual_import("", source="s")
        assert projections == []
        assert warnings

    def test_import_contract_documents_identity_columns(self):
        assert "player_name" in MANUAL_IMPORT_COLUMNS
        assert "position" in MANUAL_IMPORT_COLUMNS


# ── Rate profiles from play-by-play ──────────────────────────────────
def _pbp(receiver=None, rusher=None, passer=None, yards=0, first_down=0, complete=1):
    return {
        "receiver_player_name": receiver,
        "rusher_player_name": rusher,
        "passer_player_name": passer,
        "yards_gained": yards,
        "first_down": first_down,
        "complete_pass": complete if receiver else 0,
    }


class TestRateProfiles:
    def test_band_shares_and_fd_rate_from_receptions(self):
        rows = (
            [_pbp(receiver="X", yards=3, first_down=0) for _ in range(4)]
            + [_pbp(receiver="X", yards=12, first_down=1) for _ in range(4)]
            + [_pbp(receiver="X", yards=45, first_down=1) for _ in range(2)]
        )
        profiles = build_rate_profiles(rows)
        prof = profiles["X"]
        assert prof.sample_size == 10
        assert prof.band_shares["rec_0_4"] == pytest.approx(0.4)
        assert prof.band_shares["rec_10_19"] == pytest.approx(0.4)
        assert prof.band_shares["rec_40p"] == pytest.approx(0.2)
        assert prof.fd_per_reception == pytest.approx(0.6)

    def test_rush_and_completion_rates(self):
        rows = [_pbp(rusher="R", yards=5, first_down=1) for _ in range(3)]
        rows += [_pbp(rusher="R", yards=1, first_down=0) for _ in range(7)]
        rows += [_pbp(receiver="W", passer="Q", yards=15, first_down=1) for _ in range(5)]
        profiles = build_rate_profiles(rows)
        assert profiles["R"].fd_per_rush == pytest.approx(0.3)
        assert profiles["Q"].fd_per_completion == pytest.approx(1.0)

    def test_empty_input_is_safe(self):
        assert build_rate_profiles([]) == {}


# ── Derived categories ───────────────────────────────────────────────
class TestDerivedCategories:
    def test_bands_derived_from_own_history(self):
        rows = [_pbp(receiver="Star WR", yards=12, first_down=1) for _ in range(30)]
        profiles = build_rate_profiles(rows)
        proj = PlayerProjection(
            player_name="Star WR", position="WR", stats={"rec": 100.0, "rec_yd": 1200.0}
        )
        out = derive_categories(proj, profiles=profiles)
        # All 30 sampled catches were 10-19 yards, so the whole
        # projected reception volume lands in that band.
        assert out.stats["rec_10_19"] == pytest.approx(100.0)
        assert out.provenance["rec_10_19"].tier == "derived-player-history"

    def test_falls_back_to_position_average_without_history(self):
        proj = PlayerProjection(player_name="Rookie Unknown", position="WR", stats={"rec": 40.0})
        out = derive_categories(proj, profiles={})
        assert out.provenance["rec_0_4"].tier == "derived-position"
        # Position shares are a distribution — they must conserve volume.
        band_total = sum(out.stats[k] for k, _lo, _hi in _bands())
        assert band_total == pytest.approx(40.0, rel=1e-6)

    def test_thin_sample_does_not_qualify_as_player_history(self):
        rows = [_pbp(receiver="Thin", yards=3, first_down=0) for _ in range(5)]
        profiles = build_rate_profiles(rows)
        proj = PlayerProjection(player_name="Thin", position="WR", stats={"rec": 50.0})
        out = derive_categories(proj, profiles=profiles, min_sample=20)
        assert out.provenance["rec_0_4"].tier == "derived-position"

    def test_direct_categories_are_never_overwritten(self):
        proj = PlayerProjection(
            player_name="Direct Guy",
            position="WR",
            stats={"rec": 80.0, "rec_0_4": 11.0},
            provenance={"rec_0_4": CategoryProvenance("rec_0_4", "direct", "source")},
        )
        out = derive_categories(proj, profiles={})
        assert out.stats["rec_0_4"] == 11.0
        assert out.provenance["rec_0_4"].tier == "direct"

    def test_no_volume_means_no_fabricated_category(self):
        """Rule 1: we never invent a volume, only distribute a given one."""
        proj = PlayerProjection(
            player_name="No Rec Projection", position="WR", stats={"rec_yd": 900.0}
        )
        out = derive_categories(proj, profiles={})
        for key, _lo, _hi in _bands():
            assert key not in out.stats
        assert "bonus_fd_wr" not in out.stats

    def test_first_down_bonus_uses_position_keyed_slot(self):
        proj = PlayerProjection(player_name="A TE", position="TE", stats={"rec": 90.0})
        out = derive_categories(proj, profiles={})
        assert "bonus_fd_te" in out.stats
        assert "bonus_fd_wr" not in out.stats

    def test_rb_first_downs_blend_rush_and_receiving(self):
        rows = [_pbp(rusher="Back", yards=6, first_down=1) for _ in range(50)]
        rows += [_pbp(receiver="Back", yards=3, first_down=0) for _ in range(50)]
        profiles = build_rate_profiles(rows)
        proj = PlayerProjection(
            player_name="Back", position="RB", stats={"rush_att": 200.0, "rec": 50.0}
        )
        out = derive_categories(proj, profiles=profiles)
        # 200 carries at 1.0 + 50 catches at 0.0, over 250 opportunities.
        assert out.stats["bonus_fd_rb"] == pytest.approx(200.0)
        assert out.provenance["bonus_fd_rb"].tier == "derived-player-history"

    def test_qb_first_downs_come_from_completions(self):
        proj = PlayerProjection(player_name="A QB", position="QB", stats={"pass_cmp": 400.0})
        out = derive_categories(proj, profiles={})
        assert out.stats["bonus_fd_qb"] > 0
        assert out.provenance["bonus_fd_qb"].tier == "derived-position"

    def test_input_projection_is_not_mutated(self):
        proj = PlayerProjection(player_name="X", position="WR", stats={"rec": 10.0})
        before = dict(proj.stats)
        derive_categories(proj, profiles={})
        assert proj.stats == before

    def test_all_declared_derived_categories_are_reachable(self):
        """Every key in DERIVED_CATEGORIES must actually be derivable."""
        produced: set[str] = set()
        for pos, stats in [
            ("WR", {"rec": 50.0}),
            ("TE", {"rec": 50.0}),
            ("RB", {"rush_att": 100.0, "rec": 30.0}),
            ("QB", {"pass_cmp": 300.0}),
        ]:
            out = derive_categories(
                PlayerProjection(player_name=f"{pos} guy", position=pos, stats=stats),
                profiles={},
            )
            produced |= set(out.stats) - set(stats)
        assert set(DERIVED_CATEGORIES) <= produced


# ── Re-scoring ───────────────────────────────────────────────────────
class TestScoring:
    def test_rescoring_matches_hand_computed_dot_product(self, scoring):
        proj = PlayerProjection(
            player_name="Simple", position="WR", stats={"rec_yd": 100.0, "rec_td": 2.0}
        )
        scored = score_projection(proj, scoring)
        expected = 100.0 * scoring["rec_yd"] + 2.0 * scoring["rec_td"]
        assert scored.points == pytest.approx(expected)

    def test_all_direct_projection_scores_full_confidence(self, scoring):
        proj = PlayerProjection(
            player_name="Direct",
            position="WR",
            stats={"rec_yd": 100.0},
            provenance={"rec_yd": CategoryProvenance("rec_yd", "direct")},
        )
        assert score_projection(proj, scoring).confidence == pytest.approx(1.0)

    def test_derived_categories_drag_confidence_below_direct(self, scoring):
        direct = PlayerProjection(
            player_name="D",
            position="WR",
            stats={"rec": 100.0, "rec_10_19": 100.0},
            provenance={
                "rec": CategoryProvenance("rec", "direct"),
                "rec_10_19": CategoryProvenance("rec_10_19", "direct"),
            },
        )
        derived = PlayerProjection(
            player_name="D",
            position="WR",
            stats={"rec": 100.0, "rec_10_19": 100.0},
            provenance={
                "rec": CategoryProvenance("rec", "direct"),
                "rec_10_19": CategoryProvenance("rec_10_19", "derived-position"),
            },
        )
        assert (
            score_projection(derived, scoring).confidence
            < score_projection(direct, scoring).confidence
        )

    def test_confidence_is_volume_weighted_not_category_counted(self, scoring):
        """A tiny derived category must not tank an otherwise-direct line."""
        proj = PlayerProjection(
            player_name="Mostly Direct",
            position="WR",
            stats={"rec_yd": 1400.0, "rec_0_4": 0.5},
            provenance={
                "rec_yd": CategoryProvenance("rec_yd", "direct"),
                "rec_0_4": CategoryProvenance("rec_0_4", "derived-position"),
            },
        )
        assert score_projection(proj, scoring).confidence > 0.95

    def test_score_projections_preserves_order(self, scoring):
        projs = [
            PlayerProjection(player_name=n, position="WR", stats={"rec_yd": 10.0})
            for n in ("A", "B", "C")
        ]
        assert [s.projection.player_name for s in score_projections(projs, scoring)] == [
            "A",
            "B",
            "C",
        ]

    def test_serialization_is_explainable(self, scoring):
        proj = PlayerProjection(player_name="X", position="WR", source="s", stats={"rec_yd": 50.0})
        payload = score_projection(proj, scoring).to_dict()
        assert payload["playerName"] == "X"
        assert payload["leaguePoints"] > 0
        assert payload["breakdown"]["components"]


# ── Source disagreement ──────────────────────────────────────────────
class TestDisagreement:
    def _scored(self, scoring, per_source):
        projs = [
            PlayerProjection(
                player_name="Contested", position="WR", source=src, stats={"rec_yd": yds}
            )
            for src, yds in per_source.items()
        ]
        return score_projections(projs, scoring)

    def test_agreement_high_when_sources_align(self, scoring):
        d = measure_disagreement(self._scored(scoring, {"a": 1000.0, "b": 1010.0}))[0]
        assert d.source_count == 2
        assert d.agreement > 0.98

    def test_agreement_falls_as_sources_diverge(self, scoring):
        tight = measure_disagreement(self._scored(scoring, {"a": 1000.0, "b": 1010.0}))[0]
        wide = measure_disagreement(self._scored(scoring, {"a": 400.0, "b": 1600.0}))[0]
        assert wide.agreement < tight.agreement
        assert wide.spread_points > tight.spread_points

    def test_single_source_is_zero_agreement_not_perfect(self, scoring):
        """One source agreeing with itself is absence of evidence."""
        d = measure_disagreement(self._scored(scoring, {"only": 1000.0}))[0]
        assert d.source_count == 1
        assert d.agreement == 0.0
        assert d.confidence == 0.0

    def test_most_contested_players_sort_first(self, scoring):
        contested = self._scored(scoring, {"a": 400.0, "b": 1600.0})
        calm = score_projections(
            [
                PlayerProjection(player_name="Calm", position="WR", source=s, stats={"rec_yd": v})
                for s, v in (("a", 900.0), ("b", 905.0))
            ],
            scoring,
        )
        out = measure_disagreement(calm + contested)
        assert [d.player_name for d in out] == ["Contested", "Calm"]

    def test_li7_handoff_keys_on_displayname_like_playervalues(self, scoring):
        """The cross-workstream interface must join to PlayerValues by key."""
        d = measure_disagreement(self._scored(scoring, {"a": 900.0, "b": 1100.0}))[0]
        sig = d.to_li7_signal()
        assert sig["displayName"] == "Contested"
        assert 0.0 <= sig["agreement"] <= 1.0
        assert sig["sourceCount"] == 2
        assert set(sig) == {
            "displayName",
            "position",
            "sourceCount",
            "medianPoints",
            "spreadPoints",
            "agreement",
        }

    def test_li7_signal_marks_single_source_unadjustable(self, scoring):
        sig = measure_disagreement(self._scored(scoring, {"only": 900.0}))[0].to_li7_signal()
        assert sig["sourceCount"] == 1
        assert sig["agreement"] == 0.0

    def test_per_source_points_are_retained_for_explanation(self, scoring):
        d = measure_disagreement(self._scored(scoring, {"fbg": 1000.0, "rw": 1200.0}))[0]
        assert set(d.per_source) == {"fbg", "rw"}
        assert d.to_dict()["perSource"]["fbg"] > 0


# ── Worked end-to-end case ───────────────────────────────────────────
class TestEndToEnd:
    """CSV on disk → Sleeper keys → derived categories → exact scorer.

    This is the proof the manual-import path actually works, not just
    that its parts do.
    """

    def test_full_path_produces_league_points(self, import_csv, scoring):
        projections, warnings = parse_manual_import(
            import_csv, source="fbg-manual", scoring_keys=scoring.keys()
        )
        assert not [w for w in warnings if "skipped" in w]

        # Realized history for one player only — so the fixture
        # exercises tier B and tier D in the same run.
        pbp = [_pbp(receiver="Ja'Marr Chase", yards=14, first_down=1) for _ in range(60)]
        profiles = build_rate_profiles(pbp)

        enriched = [derive_categories(p, profiles=profiles) for p in projections]
        scored = score_projections(enriched, scoring)
        by_name = {s.projection.player_name: s for s in scored}

        # Every player scores real points under the league's own rules.
        for s in scored:
            assert s.points > 0, s.projection.player_name

        # The distance-banded PPR actually bit: Chase's catches were
        # all 10-19 yard grabs in the sample, so his reception points
        # come through rec_10_19, not a flat PPR.
        chase = by_name["Ja'Marr Chase"]
        assert chase.projection.stats["rec_10_19"] == pytest.approx(104.0)
        assert chase.projection.provenance["rec_10_19"].tier == "derived-player-history"
        keys = {c.scoring_key for c in chase.breakdown.components}
        assert "rec_10_19" in keys
        assert "bonus_fd_wr" in keys

        # The rookie with no history still scores, on tier-D priors.
        rookie = by_name["Rookie Unknown"]
        assert rookie.projection.provenance["rec_0_4"].tier == "derived-position"
        assert rookie.confidence < chase.confidence

        # QB first downs route to the QB bonus slot.
        allen = by_name["Josh Allen"]
        assert "bonus_fd_qb" in allen.projection.stats

        # And the whole thing is explainable end to end.
        payload = chase.to_dict()
        assert payload["provenance"]["rec_10_19"]["tier"] == "derived-player-history"
        assert payload["confidence"] < 1.0  # derived categories present


def _bands():
    from src.league_intel.projections import _RECEPTION_BANDS

    return _RECEPTION_BANDS
