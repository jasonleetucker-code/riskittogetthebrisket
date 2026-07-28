"""Projection consensus, snapshots, adapters, and missing-data behavior."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.bdvm.params import load_param_set
from src.bdvm.projections import (
    ProjectionError,
    ProjectionRecord,
    RealizedSeason,
    blend_consensus,
    build_reconstructed_baseline,
    latest_snapshot_path,
    load_manual_csv,
    load_snapshot,
    write_snapshot,
)

PARAMS = load_param_set("params_v1")
SCORING = {"rec": 1.0, "rec_yd": 0.1, "rec_td": 6.0}


def rec(source, fpg, *, as_of="2026-07-20", games=17.0, key="player one", pos="WR", is_proxy=False):
    return ProjectionRecord(
        source=source,
        player_key=key,
        position=pos,
        season=2026,
        as_of=as_of,
        games=games,
        fpg=fpg,
        scoring_native=True,
        is_proxy=is_proxy,
    )


class TestConsensus(unittest.TestCase):
    def test_equal_weight_mean_and_sigma(self):
        c = blend_consensus(
            [rec("a", 10.0), rec("b", 14.0)],
            scoring_settings=SCORING,
            snapshot_as_of="2026-07-27",
            params=PARAMS,
        )
        self.assertAlmostEqual(c.mu_fpg, 12.0)
        self.assertAlmostEqual(c.sigma_source, 2.0)
        self.assertEqual(c.n_sources, 2)
        self.assertFalse(c.any_proxy)

    def test_no_records_returns_none_not_zero(self):
        self.assertIsNone(
            blend_consensus(
                [], scoring_settings=SCORING, snapshot_as_of="2026-07-27", params=PARAMS
            )
        )

    def test_trimmed_mean_at_five_sources(self):
        recs = [
            rec(s, f) for s, f in [("a", 2.0), ("b", 11.0), ("c", 12.0), ("d", 13.0), ("e", 30.0)]
        ]
        c = blend_consensus(
            recs, scoring_settings=SCORING, snapshot_as_of="2026-07-27", params=PARAMS
        )
        # top+bottom trimmed → mean of 11,12,13
        self.assertAlmostEqual(c.mu_fpg, 12.0)
        self.assertEqual(c.n_sources, 3)

    def test_stale_source_downweighted_and_flagged(self):
        fresh = rec("fresh", 10.0, as_of="2026-07-25")
        stale = rec("stale", 20.0, as_of="2026-05-01")
        c = blend_consensus(
            [fresh, stale], scoring_settings=SCORING, snapshot_as_of="2026-07-27", params=PARAMS
        )
        self.assertIn("stale", c.stale_sources)
        # stale weight 0.5 → mu = (10 + 0.5*20)/1.5 = 13.333
        self.assertAlmostEqual(c.mu_fpg, 40.0 / 3.0, places=6)

    def test_single_source_cap_limits_dominance(self):
        # Weight capping only matters with unequal weights (stale mix):
        # one fresh source among 3 stale ones cannot exceed 35% share.
        recs = [
            rec("fresh", 20.0, as_of="2026-07-26"),
            rec("s1", 10.0, as_of="2026-01-01"),
            rec("s2", 10.0, as_of="2026-01-01"),
            rec("s3", 10.0, as_of="2026-01-01"),
        ]
        c = blend_consensus(
            recs, scoring_settings=SCORING, snapshot_as_of="2026-07-27", params=PARAMS
        )
        # uncapped: weights (1.0, .5, .5, .5) → fresh share 40%; capped to 35%
        # mu = 0.35*20 + 0.65*10 = 13.5
        self.assertAlmostEqual(c.mu_fpg, 13.5, places=6)

    def test_proxy_flag_propagates(self):
        c = blend_consensus(
            [rec("a", 10.0), rec("proxy", 12.0, is_proxy=True)],
            scoring_settings=SCORING,
            snapshot_as_of="2026-07-27",
            params=PARAMS,
        )
        self.assertTrue(c.any_proxy)


class TestRecordValidation(unittest.TestCase):
    def test_record_without_any_signal_raises(self):
        with self.assertRaises(ProjectionError):
            ProjectionRecord(
                source="a",
                player_key="x",
                position="WR",
                season=2026,
                as_of="2026-07-01",
                games=17.0,
            )

    def test_nonpositive_games_raises(self):
        with self.assertRaises(ProjectionError):
            ProjectionRecord(
                source="a",
                player_key="x",
                position="WR",
                season=2026,
                as_of="2026-07-01",
                games=0.0,
                fpg=10.0,
            )


class TestSnapshots(unittest.TestCase):
    def test_write_load_roundtrip_and_immutability(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            records = [rec("a", 10.0), rec("b", 12.0, key="player two")]
            path = write_snapshot(records, season=2026, as_of="2026-07-27", base_dir=base)
            as_of, loaded = load_snapshot(path)
            self.assertEqual(as_of, "2026-07-27")
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].player_key, "player one")
            with self.assertRaises(ProjectionError):
                write_snapshot(records, season=2026, as_of="2026-07-27", base_dir=base)
            self.assertEqual(latest_snapshot_path(2026, base_dir=base), path)

    def test_latest_snapshot_none_when_absent(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(latest_snapshot_path(2026, base_dir=Path(td)))


class TestManualCsvAdapter(unittest.TestCase):
    def test_stat_line_and_fpts_rows(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sourceA.csv"
            p.write_text(
                "name,position,games,receptions,receiving_yards,receiving_tds,fpts\n"
                "Alpha Man,WR,17,85,1190,8.5,\n"
                "Beta Guy,RB,16,,,,240\n",
                encoding="utf-8",
            )
            records = load_manual_csv(
                p,
                source="sourceA",
                season=2026,
                default_as_of="2026-07-01",
                name_normalizer=lambda s: s.lower(),
            )
        self.assertEqual(len(records), 2)
        alpha, beta = records
        fpg, native = alpha.resolve_fpg(SCORING)
        self.assertTrue(native)
        self.assertAlmostEqual(fpg, 15.0)  # 5 rec + 7 yds + 3 td / game
        fpg_b, native_b = beta.resolve_fpg(SCORING)
        self.assertFalse(native_b)
        self.assertAlmostEqual(fpg_b, 15.0)

    def test_missing_position_raises(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.csv"
            p.write_text("name,position,games,fpts\nNo Pos,,16,100\n", encoding="utf-8")
            with self.assertRaises(ProjectionError):
                load_manual_csv(
                    p,
                    source="x",
                    season=2026,
                    default_as_of="2026-07-01",
                    name_normalizer=lambda s: s.lower(),
                )


class TestReconstructedBaseline(unittest.TestCase):
    def test_shrinkage_math(self):
        history = {
            "steady vet": (
                "WR",
                [
                    RealizedSeason(2025, 20.0, 16.0),
                    RealizedSeason(2024, 15.0, 16.0),
                    RealizedSeason(2023, 10.0, 16.0),
                ],
            ),
        }
        out = build_reconstructed_baseline(
            history,
            season=2026,
            as_of="2026-07-27",
            positional_means={"WR": 10.0},
        )
        self.assertEqual(len(out), 1)
        r = out[0]
        # wppg = .5*20 + .3*15 + .2*10 = 16.5; shrink = .35 (full seasons)
        # mu = .65*16.5 + .35*10 = 14.225
        self.assertAlmostEqual(r.fpg, 14.225, places=6)
        self.assertTrue(r.is_proxy)
        self.assertTrue(r.scoring_native)

    def test_small_sample_shrinks_harder(self):
        history = {
            "one hit wonder": ("WR", [RealizedSeason(2025, 20.0, 4.0)]),
        }
        out = build_reconstructed_baseline(
            history,
            season=2026,
            as_of="2026-07-27",
            positional_means={"WR": 10.0},
        )
        r = out[0]
        # shrink capped at 0.90 → mu close to the positional mean
        self.assertAlmostEqual(r.fpg, 0.10 * 20.0 + 0.90 * 10.0, places=6)

    def test_future_seasons_excluded(self):
        history = {"time traveler": ("WR", [RealizedSeason(2026, 25.0, 16.0)])}
        out = build_reconstructed_baseline(
            history,
            season=2026,
            as_of="2026-07-27",
            positional_means={"WR": 10.0},
        )
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()


IDP_SCORING = {
    "idp_tkl_solo": 1.33,
    "idp_tkl_ast": 0.8,
    "idp_tkl_loss": 4.25,
    "idp_sack": 2.92,
    "idp_int": 5.32,
    "idp_pass_def": 5.32,  # alias spelling — the live league's dump
}


def _stat_rec(source, stats, *, key="dual lb", pos="LB", as_of="2026-07-25", proxy=False):
    return ProjectionRecord(
        source=source,
        player_key=key,
        position=pos,
        season=2026,
        as_of=as_of,
        games=17.0,
        stat_line=stats,
        stat_basis="season",
        is_proxy=proxy,
    )


class TestVocabularyDomination(unittest.TestCase):
    """A source whose stat line omits categories THIS league pays for
    (Clay: no TFL/PD) is biased low by construction — the blend must
    not average that bias in at full weight.  Down-weighting is a
    labelled prior, never silent imputation."""

    # Clay-style: solo/ast/sack/int only.  ~ (62*1.33+38*0.8+3*2.92+1*5.32)/17
    CLAY = {
        "def_tackles_solo": 62.0,
        "def_tackle_assists": 38.0,
        "def_sacks": 3.0,
        "def_interceptions": 1.0,
    }
    # IDP-Show-style: same core numbers PLUS the categories Clay omits.
    FULL = {
        "def_tackles_solo": 62.0,
        "def_tackle_assists": 38.0,
        "def_sacks": 3.0,
        "def_interceptions": 1.0,
        "def_tackles_for_loss": 8.0,
        "def_pass_defended": 4.0,
    }

    def _blend(self, records, scoring=IDP_SCORING):
        return blend_consensus(
            records,
            scoring_settings=scoring,
            snapshot_as_of="2026-07-27",
            params=PARAMS,
        )

    def test_subset_line_is_down_weighted_toward_the_complete_source(self):
        clay = _stat_rec("clayProjections", self.CLAY)
        full = _stat_rec("idpShowProjections", self.FULL)
        c = self._blend([clay, full])
        fpg_clay, _ = clay.resolve_fpg(IDP_SCORING)
        fpg_full, _ = full.resolve_fpg(IDP_SCORING)
        mult = PARAMS["projection_consensus"]["vocabulary_dominated_weight_mult"]
        expected = (mult * fpg_clay + 1.0 * fpg_full) / (mult + 1.0)
        self.assertEqual(c.vocabulary_limited, ("clayProjections",))
        self.assertAlmostEqual(c.mu_fpg, expected, places=6)
        # materially closer to the complete line than a plain mean
        self.assertGreater(c.mu_fpg, (fpg_clay + fpg_full) / 2)

    def test_no_domination_when_league_ignores_the_missing_categories(self):
        # Solo/ast/sack/int-only league: TFL/PD carry no weight, so the
        # two vocabularies are EQUAL after filtering — plain mean.
        scoring = {"idp_tkl_solo": 1.0, "idp_tkl_ast": 0.5, "idp_sack": 4.0, "idp_int": 4.0}
        clay = _stat_rec("clayProjections", self.CLAY)
        full = _stat_rec("idpShowProjections", self.FULL)
        c = self._blend([clay, full], scoring=scoring)
        self.assertEqual(c.vocabulary_limited, ())
        fpg_clay, _ = clay.resolve_fpg(scoring)
        fpg_full, _ = full.resolve_fpg(scoring)
        self.assertAlmostEqual(c.mu_fpg, (fpg_clay + fpg_full) / 2, places=6)

    def test_alias_scoring_key_counts_as_scored(self):
        # League spells passes-defended as idp_pass_def (alias) — PD
        # must still count as a scored category.
        scoring = {"idp_tkl_solo": 1.0, "idp_pass_def": 5.32}
        clay = _stat_rec("clayProjections", self.CLAY)
        full = _stat_rec("idpShowProjections", self.FULL)
        c = self._blend([clay, full], scoring=scoring)
        self.assertEqual(c.vocabulary_limited, ("clayProjections",))

    def test_proxy_never_dominates_a_real_source(self):
        clay = _stat_rec("clayProjections", self.CLAY)
        proxy = rec("reconstructedBaseline", 9.0, key="dual lb", pos="LB", is_proxy=True)
        c = self._blend([clay, proxy])
        self.assertEqual(c.vocabulary_limited, ())

    def test_direct_points_record_neither_dominates_nor_is_dominated(self):
        clay = _stat_rec("clayProjections", self.CLAY)
        direct = rec("idpShowProjections", 12.0, key="dual lb", pos="LB")
        c = self._blend([clay, direct])
        self.assertEqual(c.vocabulary_limited, ())

    def test_single_source_untouched(self):
        c = self._blend([_stat_rec("clayProjections", self.CLAY)])
        self.assertEqual(c.vocabulary_limited, ())

    def test_column_spelling_variants_compare_as_the_same_category(self):
        # def_passes_defended vs def_pass_defended are ONE category —
        # neither line dominates the other.
        a = _stat_rec("srcA", {**self.CLAY, "def_pass_defended": 4.0})
        b = _stat_rec("srcB", {**self.CLAY, "def_passes_defended": 5.0})
        c = self._blend([a, b])
        self.assertEqual(c.vocabulary_limited, ())
