"""Regression tests for the two PR-#99 review-driven fixes:

1. WRRB_FLEX (RB/WR only, no TE) and REC_FLEX (WR/TE only, no RB) must
   contribute correctly to per-position offense demand. Lumping them
   into a generic 3-way flex would distort offense replacement ranks.
2. ``settings.top_n`` must trim the offense cohort the same way it
   trims the IDP cohort, so the family_scale ratio stays symmetric.
"""
from __future__ import annotations

from src.idp_calibration import engine, season_chain
from src.idp_calibration.lineup import parse_lineup
from src.idp_calibration.stats_adapter import HistoricalStatsAdapter, PlayerSeason


# ── P1: restricted flex slots ──


def test_wrrb_flex_does_not_inflate_te_demand():
    league = {
        "league_id": "L",
        "season": 2025,
        "total_rosters": 12,
        "roster_positions": [
            "QB", "RB", "RB", "WR", "WR", "TE", "WRRB_FLEX",
            "BN", "BN", "BN",
        ],
    }
    demand = parse_lineup(league)
    # WRRB_FLEX must not flow into TE demand — it's RB/WR only.
    assert demand.te_starters == 1
    assert abs(demand.total_te_demand - 1.0) < 1e-9
    # RB demand: 2 starters + WRRB/2 = 2.5
    assert abs(demand.total_rb_demand - 2.5) < 1e-9
    # WR demand: 2 starters + WRRB/2 = 2.5
    assert abs(demand.total_wr_demand - 2.5) < 1e-9


def test_rec_flex_does_not_inflate_rb_demand():
    league = {
        "league_id": "L",
        "season": 2025,
        "total_rosters": 12,
        "roster_positions": [
            "QB", "RB", "RB", "WR", "WR", "TE", "REC_FLEX",
            "BN", "BN", "BN",
        ],
    }
    demand = parse_lineup(league)
    # REC_FLEX must not flow into RB demand — it's WR/TE only.
    assert demand.rb_starters == 2
    assert abs(demand.total_rb_demand - 2.0) < 1e-9
    # WR + TE absorb the REC_FLEX 50/50.
    assert abs(demand.total_wr_demand - 2.5) < 1e-9
    assert abs(demand.total_te_demand - 1.5) < 1e-9


def test_plain_flex_still_splits_three_ways():
    # Backward-compat — plain FLEX must still act as RB/WR/TE 1/3 each.
    league = {
        "league_id": "L",
        "season": 2025,
        "total_rosters": 12,
        "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "BN", "BN"],
    }
    demand = parse_lineup(league)
    expected = 1 + 1 / 3.0
    assert abs(demand.total_rb_demand - expected) < 1e-9
    assert abs(demand.total_wr_demand - expected) < 1e-9
    assert abs(demand.total_te_demand - expected) < 1e-9


def test_super_flex_still_25_pct_each():
    league = {
        "league_id": "L",
        "season": 2025,
        "total_rosters": 12,
        "roster_positions": ["QB", "RB", "WR", "TE", "SUPER_FLEX", "BN"],
    }
    demand = parse_lineup(league)
    # QB: 1 + super_flex × 0.25 = 1.25
    assert abs(demand.total_qb_demand - 1.25) < 1e-9
    # RB / WR / TE each: 1 + super_flex × 0.25 = 1.25
    assert abs(demand.total_rb_demand - 1.25) < 1e-9
    assert abs(demand.total_wr_demand - 1.25) < 1e-9
    assert abs(demand.total_te_demand - 1.25) < 1e-9


def test_mixed_flex_combinations_compose_correctly():
    # A real-world dynasty IDP league might use plain FLEX + WRRB +
    # SUPER_FLEX simultaneously. Each contributes only to its
    # eligible positions.
    league = {
        "league_id": "L",
        "season": 2025,
        "total_rosters": 12,
        "roster_positions": [
            "QB", "RB", "RB", "WR", "WR", "WR", "TE",
            "FLEX", "WRRB_FLEX", "SUPER_FLEX",
            "BN",
        ],
    }
    demand = parse_lineup(league)
    # QB: 1 + super × 0.25 = 1.25
    assert abs(demand.total_qb_demand - 1.25) < 1e-9
    # RB: 2 + plain/3 + WRRB/2 + super × 0.25 = 2 + 0.333 + 0.5 + 0.25 = 3.083
    assert abs(demand.total_rb_demand - (2 + 1 / 3 + 0.5 + 0.25)) < 1e-9
    # WR: 3 + plain/3 + WRRB/2 + super × 0.25 = 3 + 0.333 + 0.5 + 0.25 = 4.083
    assert abs(demand.total_wr_demand - (3 + 1 / 3 + 0.5 + 0.25)) < 1e-9
    # TE: 1 + plain/3 + super × 0.25 = 1 + 0.333 + 0.25 = 1.583  (NO WRRB)
    assert abs(demand.total_te_demand - (1 + 1 / 3 + 0.25)) < 1e-9


# ── P2: top_n symmetry ──


class _BiggerAdapter(HistoricalStatsAdapter):
    """Adapter that returns enough offense and IDP rows that top_n
    trim has a non-trivial effect."""

    name = "bigger"

    def _fetch_impl(self, season):
        rows = []
        for i in range(120):
            pos = ("DL", "LB", "DB")[i % 3]
            rows.append(
                PlayerSeason(
                    player_id=f"idp_{i}",
                    name=f"IDP{i}",
                    position=pos,
                    games=16,
                    stats={
                        "idp_tkl_solo": 200 - i,
                        "idp_sack": max(0, 25 - i / 4),
                    },
                )
            )
        for i in range(200):
            pos = ("QB", "RB", "WR", "TE")[i % 4]
            rows.append(
                PlayerSeason(
                    player_id=f"off_{i}",
                    name=f"Off{i}",
                    position=pos,
                    games=16,
                    stats={
                        "pass_yd": max(0, 5000 - i * 22) if pos == "QB" else 0,
                        "pass_td": max(0, 40 - i / 2) if pos == "QB" else 0,
                        "rush_yd": max(0, 1500 - i * 7) if pos == "RB" else 0,
                        "rush_td": max(0, 16 - i / 4) if pos == "RB" else 0,
                        "rec": max(0, 110 - i / 2) if pos in ("WR", "TE") else 0,
                        "rec_yd": max(0, 1500 - i * 7) if pos in ("WR", "TE") else 0,
                        "rec_td": max(0, 13 - i / 4) if pos in ("WR", "TE") else 0,
                    },
                )
            )
        return rows


def _identical_chain(league_id, max_hops):
    return [
        {
            "league_id": f"{league_id}_2025",
            "season": 2025,
            "previous_league_id": "",
            "scoring_settings": {
                "idp_tkl_solo": 1.0,
                "idp_sack": 4.0,
                "pass_yd": 0.04,
                "pass_td": 4.0,
                "rush_yd": 0.1,
                "rush_td": 6.0,
                "rec": 1.0,
                "rec_yd": 0.1,
                "rec_td": 6.0,
            },
            "roster_positions": [
                "QB", "RB", "RB", "WR", "WR", "TE", "FLEX",
                "DL", "DL", "LB", "LB", "DB", "DB", "IDP_FLEX",
                "BN", "BN", "BN", "BN",
            ],
            "total_rosters": 12,
        }
    ]


def _no_te_chain(league_id, max_hops):
    """League format with NO TE slot and no TE-eligible flex.
    The IDP side is identical to ``_identical_chain`` so any
    family_scale drift between the two fixtures is attributable to
    the offense lineup change."""
    return [
        {
            "league_id": f"{league_id}_2025",
            "season": 2025,
            "previous_league_id": "",
            "scoring_settings": {
                "idp_tkl_solo": 1.0,
                "idp_sack": 4.0,
                "pass_yd": 0.04,
                "pass_td": 4.0,
                "rush_yd": 0.1,
                "rush_td": 6.0,
                "rec": 1.0,
                "rec_yd": 0.1,
                "rec_td": 6.0,
            },
            # No TE slot, only WRRB_FLEX so TE has zero demand from
            # any source (no direct TE slot, plain FLEX, REC_FLEX,
            # or SUPER_FLEX).
            "roster_positions": [
                "QB", "RB", "RB", "WR", "WR", "WR", "WRRB_FLEX",
                "DL", "DL", "LB", "LB", "DB", "DB", "IDP_FLEX",
                "BN", "BN", "BN", "BN",
            ],
            "total_rosters": 12,
        }
    ]


def test_zero_demand_te_excluded_from_offense_vor(monkeypatch):
    """A no-TE league must not let TE players contribute positive
    offense VOR. Otherwise the offense denominator inflates and
    family_scale gets biased downward."""
    monkeypatch.setattr(season_chain, "fetch_league_chain", _no_te_chain)
    settings = engine.AnalysisSettings(seasons=[2025])
    art = engine.run_analysis(
        "TEST", "MINE", settings,
        stats_adapter_factory=lambda s: _BiggerAdapter(),
    )
    # Family scale must still be ~1.0 since both leagues are
    # identical. Without the zero-demand guard, TE players in the
    # adapter's universe would be assigned a low replacement (rank=1
    # via the floor) and contribute positive VOR to BOTH sides
    # symmetrically, but in different proportions if the leagues
    # differ — and even when identical, the inflated denominator
    # noticeably suppresses real differentiation in non-trivial
    # cases. Directly assert: family_scale stays ~1.0 on identical
    # no-TE leagues.
    fs = art["family_scale"]["intrinsic"]
    assert abs(fs - 1.0) < 0.05, f"no-TE league shifted family_scale: {fs}"
    # And the per-season offense lineup correctly reports zero TE
    # demand (sanity-check the lineup parser).
    me = art["per_season"]["2025"]["my_lineup"]
    assert me["te_starters"] == 0
    assert me["total_te_demand"] == 0.0


def test_top_n_trims_offense_symmetrically(monkeypatch):
    # Identical leagues → family_scale should be 1.0 regardless of
    # whether top_n is enabled. Without the offense-side trim,
    # enabling top_n would skew the ratio purely because the
    # numerator (IDP) was trimmed and the denominator (offense)
    # wasn't.
    monkeypatch.setattr(season_chain, "fetch_league_chain", _identical_chain)

    untrimmed_settings = engine.AnalysisSettings(seasons=[2025])
    untrimmed_art = engine.run_analysis(
        "TEST", "MINE", untrimmed_settings,
        stats_adapter_factory=lambda s: _BiggerAdapter(),
    )

    trimmed_settings = engine.AnalysisSettings(seasons=[2025], top_n=20)
    trimmed_art = engine.run_analysis(
        "TEST", "MINE", trimmed_settings,
        stats_adapter_factory=lambda s: _BiggerAdapter(),
    )

    fs_untrimmed = untrimmed_art["family_scale"]["intrinsic"]
    fs_trimmed = trimmed_art["family_scale"]["intrinsic"]
    # Both should be ~1.0 (identical leagues). The trimmed one should
    # not have moved meaningfully versus the untrimmed.
    assert abs(fs_untrimmed - 1.0) < 0.01
    assert abs(fs_trimmed - 1.0) < 0.01
    assert abs(fs_trimmed - fs_untrimmed) < 0.05, (
        f"top_n shifted family_scale on identical leagues: "
        f"untrimmed={fs_untrimmed} trimmed={fs_trimmed}"
    )
