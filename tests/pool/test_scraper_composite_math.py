"""Legacy-composite math helpers inside ``Dynasty Scraper.py``.

The production scraper carries a second valuation stack that predates the
canonical pipeline: rank→value curves, the IDP anchor backbone, and the
weighted ``_composite``.  It feeds ``canonicalSiteValues`` (the INPUT to
``src/api/data_contract.py``) and the legacy ``_composite`` fallback, so
its arithmetic is board-relevant even though it never writes
``rankDerivedValue`` itself.

``Dynasty Scraper.py`` does import-time network/browser work, so — like
the rest of the suite — we do NOT import it.  These helpers are nested
inside ``run()``, so we ast-extract them by name (walking the whole tree,
not just module body) and exec the real shipped source in isolation with
the enclosing-scope constants injected.

Expected values below are hand-derived from the closed forms, never by
calling the production helper.
"""

from __future__ import annotations

import ast
import bisect
import math
import re
import textwrap
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRAPER = _REPO / "Dynasty Scraper.py"


def _scraper_src() -> str:
    return _SCRAPER.read_text(encoding="utf-8")


def _extract(names: set[str], extra_globals: dict | None = None) -> dict:
    """Exec the named (possibly nested) function defs in a bare namespace."""
    src = _scraper_src()
    tree = ast.parse(src)
    parts: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            seg = ast.get_source_segment(src, node, padded=True)
            assert seg is not None
            parts[node.name] = textwrap.dedent(seg)
    missing = names - set(parts)
    assert not missing, f"helpers not found in Dynasty Scraper.py: {sorted(missing)}"
    ns: dict = {"math": math, "bisect": bisect}
    ns.update(extra_globals or {})
    exec(compile("\n\n".join(parts[n] for n in sorted(parts)), "<scraper_math>", "exec"), ns)
    return ns


# ── M8a: no-information percentile ────────────────────────────────────


class RankPercentileTests(unittest.TestCase):
    """``_rank_percentile`` maps a source rank onto [0, 1] where 0.0 is the
    BEST rank in the observed distribution and 1.0 the worst."""

    def setUp(self) -> None:
        self.f = _extract({"_rank_percentile"})["_rank_percentile"]

    def test_degenerate_populations_agree(self) -> None:
        """Empty and single-observation lists are both 'no information'.

        They used to return 1.0 and 0.0 — opposite ends of the same scale —
        which meant an unusable calibration set priced a player at either
        the very bottom or the very top of the target curve depending only
        on whether it held zero or one observation.
        """
        empty = self.f(5, [])
        single = self.f(5, [7])
        self.assertEqual(empty, single)
        self.assertEqual(empty, 0.5)

    def test_single_observation_is_not_top_of_curve(self) -> None:
        """One observed rank must not price every player at the ceiling."""
        for rank in (1.0, 7.0, 400.0):
            self.assertEqual(self.f(rank, [7]), 0.5)

    def test_populated_distribution_unchanged(self) -> None:
        """Hand-computed against pos / (n - 1) on ranks [1, 2, 3, 4, 5]."""
        ranks = [1, 2, 3, 4, 5]
        # exact hit on the 3rd of 5 → pos 2.0 → 2/4
        self.assertAlmostEqual(self.f(3, ranks), 0.5, places=9)
        # below the best observed rank → pos 0.0
        self.assertAlmostEqual(self.f(0, ranks), 0.0, places=9)
        # past the worst observed rank → pos n-1 → 4/4
        self.assertAlmostEqual(self.f(6, ranks), 1.0, places=9)
        # halfway between the 2nd and 3rd → pos 1.5 → 1.5/4
        self.assertAlmostEqual(self.f(2.5, ranks), 0.375, places=9)


# ── M8b: IDP anchor tail ──────────────────────────────────────────────


class IdpAnchorTailTests(unittest.TestCase):
    """The IDP backbone curve must keep decaying past its deepest anchor."""

    def setUp(self) -> None:
        ns = _extract(
            {"_build_idp_anchor_points", "_interp_anchor_points"},
            extra_globals={"IDP_ANCHOR_TOP": 6250.0},
        )
        self.build = ns["_build_idp_anchor_points"]
        self.interp = ns["_interp_anchor_points"]

    def test_anchors_never_repeat_the_deepest_observation(self) -> None:
        """27 observations (the live DL bucket size) must not emit anchors
        at rank 48/72/96 all carrying the 27th value."""
        vals = [1000.0 - (10.0 * i) for i in range(27)]  # 1000 … 740
        pts = self.build(vals, 6250.0)
        ranks = [r for r, _ in pts]
        self.assertLessEqual(max(ranks), len(vals))
        # every anchor value is distinct because every source value is
        self.assertEqual(len({v for _, v in pts}), len(pts))
        # the deepest observation is represented
        self.assertEqual(pts[-1], (27, 740.0))

    def test_tail_is_rank_sensitive(self) -> None:
        """Past the last anchor the curve must still separate ranks.

        With 27 observations the old point set ended (72, 740), (96, 740),
        so the log-log slope was exactly 0 and every rank ≥ 96 priced at
        740.0.
        """
        vals = [1000.0 - (10.0 * i) for i in range(27)]
        pts = self.build(vals, 6250.0)
        v96 = self.interp(96, pts)
        v200 = self.interp(200, pts)
        self.assertLess(v200, v96)

        # Hand-derived: last two anchors are (24, 770) and (27, 740), so the
        # log-log slope is ln(740/770) / ln(27/24) and
        #   v(r) = 740 * (r / 27) ** slope
        slope = math.log(740.0 / 770.0) / math.log(27.0 / 24.0)
        self.assertAlmostEqual(v200, 740.0 * ((200.0 / 27.0) ** slope), places=6)
        self.assertAlmostEqual(v96, 740.0 * ((96.0 / 27.0) ** slope), places=6)

    def test_two_observation_curve_uses_both(self) -> None:
        """A 2-value bucket must produce a real slope, not a flat line."""
        pts = self.build([1000.0, 500.0], 6250.0)
        self.assertEqual(pts, [(1, 1000.0), (2, 500.0)])
        # slope = ln(500/1000) / ln(2/1) = -1  →  v(r) = 500 * (r/2) ** -1
        self.assertAlmostEqual(self.interp(8, pts), 125.0, places=6)
        self.assertAlmostEqual(self.interp(4, pts), 250.0, places=6)

    def test_deep_bucket_keeps_its_sampled_anchors(self) -> None:
        """With more observations than the deepest sampled rank, the full
        [1, 3, 6, 12, 24, 48, 72, 96] ladder survives plus a terminal
        anchor at the deepest observation."""
        vals = [1000.0 - (2.0 * i) for i in range(120)]
        pts = self.build(vals, 6250.0)
        self.assertEqual([r for r, _ in pts], [1, 3, 6, 12, 24, 48, 72, 96, 120])

    def test_anchor_values_are_monotone_non_increasing(self) -> None:
        vals = [500.0, 900.0, 700.0, 100.0, 300.0, 800.0]
        pts = self.build(vals, 6250.0)
        vals_only = [v for _, v in pts]
        self.assertEqual(vals_only, sorted(vals_only, reverse=True))
        self.assertEqual(pts[0], (1, 900.0))

    def test_empty_falls_back_to_anchor_top(self) -> None:
        self.assertEqual(self.build([], 6250.0), [(1, 6250.0)])


# ── M8c: the scraper's site weights are not the blend weights ─────────


class LegacyCompositeWeightNamingTests(unittest.TestCase):
    """The scraper's non-uniform per-site weights must not read as the
    canonical blend weights, which are all 1.0 by policy."""

    def test_no_bare_site_weights_identifier(self) -> None:
        src = _scraper_src()
        self.assertIsNone(
            re.search(r"(?<![_A-Za-z])SITE_WEIGHTS", src),
            "Dynasty Scraper.py still uses the bare name SITE_WEIGHTS; it reads "
            "as the canonical blend weights but is the legacy _composite's own "
            "weight table.",
        )

    def test_legacy_name_and_provenance_comment_present(self) -> None:
        src = _scraper_src()
        self.assertIn("LEGACY_COMPOSITE_SITE_WEIGHTS", src)
        idx = src.index("LEGACY_COMPOSITE_SITE_WEIGHTS")
        header = src[max(0, idx - 2200) : idx]
        # The comment must name the thing these are NOT, and the thing they are.
        self.assertIn("_RANKING_SOURCES", header)
        self.assertIn("rankDerivedValue", header)
        self.assertIn("default_weights.json", header)


# ── M8d: the elite boost and the value it multiplies ──────────────────


class EliteExpansionTests(unittest.TestCase):
    """The elite-separation boost must be decided on the same population
    that produced the composite it multiplies."""

    THRESHOLD = 0.88
    BOOST_MAX = 0.09

    def setUp(self) -> None:
        ns = _extract(
            {"_elite_expansion_multiplier"},
            extra_globals={
                "ELITE_NORM_THRESHOLD": self.THRESHOLD,
                "ELITE_BOOST_MAX": self.BOOST_MAX,
            },
        )
        self.f = ns["_elite_expansion_multiplier"]

    def test_thin_population_is_never_boosted(self) -> None:
        self.assertEqual(self.f([0.99, 0.99, 0.99], 1.0, 0.0), 1.0)

    def test_below_threshold_is_never_boosted(self) -> None:
        self.assertEqual(self.f([0.80, 0.82, 0.84, 0.86], 1.0, 0.0), 1.0)

    def test_boost_matches_closed_form(self) -> None:
        """median = (0.94 + 0.96) / 2 = 0.95
        span     = (0.95 - 0.88) / (1 - 0.88) = 0.5833333…
        agreement (cv = 0) = 1.0, conf = 1.0
        boost    = 1 + 0.09 * 0.5833333… = 1.0525
        """
        got = self.f([0.90, 0.94, 0.96, 0.98], 1.0, 0.0)
        self.assertAlmostEqual(got, 1.0 + (0.09 * (7.0 / 12.0)), places=9)

    def test_dispersion_and_confidence_scale_the_boost(self) -> None:
        """cv = 0.15 → agreement = 1 - 0.15/0.30 = 0.5; conf = 0.6."""
        got = self.f([0.90, 0.94, 0.96, 0.98], 0.6, 0.15)
        self.assertAlmostEqual(got, 1.0 + (0.09 * (7.0 / 12.0) * 0.5 * 0.6), places=9)

    def test_trimmed_outlier_cannot_veto_the_boost(self) -> None:
        """The defect, stated as behavior.

        Observed norms sorted: [0.60, 0.86, 0.87, 0.92, 0.94].  The 0.26 gap
        at the bottom is ≥ OUTLIER_TRIM_GAP (0.18), so the adaptive trim drops
        0.60 and `composite` is the weighted mean of the remaining four.

        Untrimmed median = 0.87 → below threshold → no boost.
        Trimmed   median = (0.87 + 0.92) / 2 = 0.895 → above threshold.

        The boost decision belongs to the population that produced the value,
        so the trimmed median is the one that must be consulted.
        """
        trimmed = [0.86, 0.87, 0.92, 0.94]
        span = (0.895 - self.THRESHOLD) / (1.0 - self.THRESHOLD)
        self.assertAlmostEqual(self.f(trimmed, 1.0, 0.0), 1.0 + (self.BOOST_MAX * span), places=9)
        # …and the untrimmed population is genuinely a different answer,
        # which is what makes the population choice load-bearing.
        self.assertEqual(self.f([0.60, 0.86, 0.87, 0.92, 0.94], 1.0, 0.0), 1.0)

    def test_call_site_feeds_the_trimmed_population(self) -> None:
        """Source lock: the composite loop must hand the helper the post-trim
        norms, not `norm_vals` (which is the full observation set exported as
        the market-liquidity diagnostic)."""
        src = _scraper_src()
        self.assertIn("_elite_expansion_multiplier(trimmed_norms", src)
        # the old inline block computed its median from the untrimmed list
        self.assertNotIn("sorted_vals = sorted(norm_vals)", src)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
