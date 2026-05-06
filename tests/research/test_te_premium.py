"""Unit tests for the TE Premium Lab sandbox analysis.

Coverage:

* Boost math (raw, percentage, log-ratio, near-zero handling)
* TE row extraction from both ``players`` dict and ``playersArray``
* Internal scoring effect — toggles off TE reception bonus, TE 1D
  bonus, or both
* Scarcity effect — VOR delta is positive going from 12 to 24 starters
* Tier assignment — rank thresholds + age tags
* End-to-end run_analysis returns the documented payload shape
* MUTATION SAFETY — analysis never modifies the input contract or the
  TE rows passed in (the contract dict is deep-compared before/after)
* Graceful degradation when external boards are unavailable
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from src.research import te_premium as tep


def _make_te_row(
    name: str,
    *,
    sleeper_id: str | None = None,
    composite: float = 5000,
    age: int = 26,
    team: str = "BUF",
    rule_contributions: dict | None = None,
    rule_contributions_detail: dict | None = None,
    ppg_baseline: float = 12.0,
    ppg_league: float = 11.5,
    ktc: float | None = 6500,
    ktc_sf_tep: float | None = 7000,
    rookie: bool = False,
) -> dict:
    """Build a synthetic players-dict row that mimics the live contract.

    By default ``rule_contributions_detail`` is omitted (matching the
    pre-refactor contract shape) so most tests exercise the
    sandbox's fallback path.  Tests that want to exercise the
    precise per-rule path pass an explicit ``rule_contributions_detail``."""
    if rule_contributions is None:
        rule_contributions = {
            "te_premium": -0.4,
            "first_downs": 2.5,
            "receptions": -2.0,
        }
    scoring_adj = {
        "final_scoring_delta_points": (
            rule_contributions.get("te_premium", 0.0)
            + rule_contributions.get("first_downs", 0.0)
            + rule_contributions.get("receptions", 0.0)
        ),
        "rule_contributions": dict(rule_contributions),
        "archetype": "chain_mover",
        "confidence": 0.7,
    }
    if rule_contributions_detail is not None:
        scoring_adj["rule_contributions_detail"] = dict(rule_contributions_detail)
    return {
        "displayName": name,
        "_sleeperId": sleeper_id or name.lower().replace(" ", "_"),
        "position": "TE",
        "age": age,
        "team": team,
        "_composite": composite,
        "rankDerivedValue": composite,
        "ktc": ktc,
        "ktcSfTep": ktc_sf_tep,
        "_formatFitPPGTest": ppg_baseline,
        "_formatFitPPGCustom": ppg_league,
        "rookie": rookie,
        "_scoringAdjustment": scoring_adj,
    }


def _make_contract(te_rows: list[dict]) -> dict:
    """Wrap TE rows in a minimal ``players`` dict contract."""
    return {
        "players": {row["displayName"]: row for row in te_rows},
    }


# ── Extraction ───────────────────────────────────────────────────────


def test_extract_te_players_from_players_dict():
    contract = _make_contract([_make_te_row("Brock Bowers", composite=8000)])
    rows = tep.extract_te_players_from_contract(contract)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Brock Bowers"
    assert rows[0]["position"] == "TE"
    assert rows[0]["te_pool_rank"] == 1
    assert rows[0]["current_value"] == 8000


def test_extract_te_players_from_players_array():
    row = _make_te_row("Sam LaPorta", composite=6000)
    row["displayName"] = "Sam LaPorta"
    contract = {"playersArray": [row]}
    rows = tep.extract_te_players_from_contract(contract)
    assert len(rows) == 1
    assert rows[0]["display_name"] == "Sam LaPorta"


def test_extract_skips_non_te():
    contract = {
        "players": {
            "Josh Allen": {
                "displayName": "Josh Allen",
                "position": "QB",
                "_composite": 9999,
                "_sleeperId": "qb1",
            },
            "Brock Bowers": _make_te_row("Brock Bowers"),
        }
    }
    rows = tep.extract_te_players_from_contract(contract)
    names = [r["display_name"] for r in rows]
    assert names == ["Brock Bowers"]


def test_extract_dedupes_by_sleeper_id_when_both_shapes_present():
    row = _make_te_row("Brock Bowers", sleeper_id="11604")
    contract = {
        "players": {"Brock Bowers": row},
        "playersArray": [row],
    }
    rows = tep.extract_te_players_from_contract(contract)
    assert len(rows) == 1


def test_extract_assigns_te_pool_rank_descending_by_value():
    rows = [
        _make_te_row("Mid TE", composite=5000),
        _make_te_row("Top TE", composite=9000),
        _make_te_row("Low TE", composite=1000),
    ]
    contract = _make_contract(rows)
    extracted = tep.extract_te_players_from_contract(contract)
    by_name = {r["display_name"]: r["te_pool_rank"] for r in extracted}
    assert by_name == {"Top TE": 1, "Mid TE": 2, "Low TE": 3}


# ── External boost math ──────────────────────────────────────────────


def test_boost_basic_math():
    rows = [_make_te_row("Brock Bowers", composite=8000)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"brock bowers": 9000.0},
        "premium": {"brock bowers": 9500.0},
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    assert len(boosts) == 1
    b = boosts[0]
    assert b.normal_value == 9000.0
    assert b.premium_value == 9500.0
    assert b.boost_abs == pytest.approx(500.0)
    assert b.boost_pct == pytest.approx(500.0 / 9000.0)
    assert b.log_ratio == pytest.approx(__import__("math").log(9500.0 / 9000.0))
    assert b.reliable is True
    assert b.note == ""


def test_boost_near_zero_flagged_unreliable():
    # Use a name without a trailing position-letter pair so the
    # name-normaliser doesn't strip it (it strips " te"/" rb"/etc.).
    rows = [_make_te_row("Deep Reserve", composite=400)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    # Board max=9999 puts us in the legacy 200-floor branch (the
    # board is on the canonical KTC-style scale), so a deep-reserve
    # value of 50 is well below the floor and should be flagged.
    # Including a top player anchors the board's scale.
    boards = {
        "normal": {
            "deep reserve": 50.0,        # below floor 200
            "elite te": 9999.0,           # anchors scale to 0-9999
        },
        "premium": {
            "deep reserve": 250.0,
            "elite te": 9999.0,
        },
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    b = next(b for b in boosts if b.player_id == "deep_reserve")
    assert b.reliable is False
    assert "below floor" in b.note
    # boost_pct uses floor as denominator, never returns infinity
    assert b.boost_pct is not None
    assert abs(b.boost_pct) < 5.0  # sanity bound


def test_boost_missing_premium_value_flagged_unreliable():
    rows = [_make_te_row("Brock Bowers", composite=8000)]
    boards = {
        "normal": {"brock bowers": 9000.0},
        "premium": {},
    }
    # The orchestrator returns no boards if either side is empty.
    boosts = tep.compute_external_market_boost(rows, boards=boards)
    assert boosts == []


def test_boost_partial_normal_only_skips_player():
    """If both boards exist but a single player only appears in one,
    we still emit a row with reliable=False so the operator sees
    the gap explicitly."""
    rows = [_make_te_row("Brock Bowers", composite=8000)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"brock bowers": 9000.0, "other te": 5000.0},
        "premium": {"other te": 6000.0},
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    assert len(boosts) == 1
    assert boosts[0].reliable is False
    assert "missing on premium" in boosts[0].note


def test_boost_rank_change_signed():
    rows = [
        _make_te_row("Alpha Player", composite=9000),
        _make_te_row("Beta Player", composite=5000),
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"alpha player": 9000.0, "beta player": 5000.0},
        "premium": {"alpha player": 9000.0, "beta player": 9500.0},
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    by_name = {b.display_name: b for b in boosts}
    # Beta jumps to premium #1 (was #2) → rank_change = +1
    assert by_name["Beta Player"].rank_change == 1
    # Alpha drops to premium #2 (was #1) → rank_change = -1
    assert by_name["Alpha Player"].rank_change == -1


# ── Scoring effect ───────────────────────────────────────────────────


def test_scoring_effect_removes_te_premium_only():
    rows = [
        _make_te_row(
            "Bowers",
            rule_contributions={"te_premium": -0.4, "first_downs": 2.5, "receptions": -2.0},
        )
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    eff = tep.compute_internal_scoring_effect(
        extracted,
        remove_te_reception_bonus=True,
        remove_te_first_down_bonus=False,
    )
    assert len(eff) == 1
    # current = -0.4 + 2.5 - 2.0 = 0.1; remove te_premium (-0.4) → +0.5
    assert eff[0].current_ppg_delta == pytest.approx(0.1)
    assert eff[0].te_premium_ppg == pytest.approx(-0.4)
    assert eff[0].te_first_down_ppg == pytest.approx(2.5)
    assert eff[0].proposed_ppg_delta == pytest.approx(0.5)
    # Removing a negative-contribution rule lifts the projection
    assert eff[0].scoring_swing_ppg == pytest.approx(0.4)


def test_scoring_effect_removes_both_rules():
    rows = [
        _make_te_row(
            "Bowers",
            rule_contributions={"te_premium": -0.4, "first_downs": 2.5, "receptions": -2.0},
        )
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    eff = tep.compute_internal_scoring_effect(
        extracted,
        remove_te_reception_bonus=True,
        remove_te_first_down_bonus=True,
    )
    # Drop both: +0.4 (rec) + -2.5 (1d) → swing -2.1
    assert eff[0].scoring_swing_ppg == pytest.approx(-2.1)
    assert eff[0].proposed_ppg_delta == pytest.approx(0.1 - 2.1)


def test_scoring_effect_uses_detail_map_when_available():
    """When the contract carries `rule_contributions_detail.bonus_fd_te`,
    the sandbox isolates ONLY that rule for the first-down toggle —
    not the aggregate `first_downs` category which on TE rows pools
    `rec_fd` / `rush_fd` contributions too.

    This is the fix for the Codex P1 review: removing the entire
    `first_downs` category over-removes when league rec_fd/rush_fd
    differs from baseline."""
    rows = [
        _make_te_row(
            "Bowers",
            rule_contributions={
                "te_premium": -0.4,
                # Aggregate `first_downs` of 2.5 = bonus_fd_te (1.5)
                # + rec_fd contribution (1.0) for a league with
                # non-zero rec_fd delta.  Removing the aggregate
                # would over-remove by 1.0 PPG.
                "first_downs": 2.5,
                "receptions": -2.0,
            },
            rule_contributions_detail={
                "bonus_fd_te": 1.5,
                "bonus_rec_te": -0.4,
            },
        )
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    eff = tep.compute_internal_scoring_effect(
        extracted,
        remove_te_reception_bonus=False,
        remove_te_first_down_bonus=True,
    )
    # Removing only the TE first-down BONUS (not the rec_fd portion)
    # should swing PPG by exactly bonus_fd_te = -1.5, not the
    # aggregate -2.5.
    assert eff[0].te_first_down_ppg == pytest.approx(1.5)
    assert eff[0].scoring_swing_ppg == pytest.approx(-1.5)
    assert eff[0].te_fd_estimated is False
    assert eff[0].te_fd_source == "rule_contributions_detail.bonus_fd_te"


def test_scoring_effect_falls_back_with_estimation_flag_when_detail_missing():
    """When the detail map isn't in the contract (older scrape), the
    sandbox falls back to the aggregate `first_downs` category and
    flags the row `te_fd_estimated=True` so the operator sees the
    precision is limited."""
    rows = [
        _make_te_row(
            "Legacy",
            rule_contributions={
                "te_premium": -0.4,
                "first_downs": 2.5,
                "receptions": -2.0,
            },
            # No rule_contributions_detail — older contract shape.
            rule_contributions_detail=None,
        )
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    eff = tep.compute_internal_scoring_effect(
        extracted, remove_te_first_down_bonus=True,
    )
    assert eff[0].te_fd_estimated is True
    assert "estimated" in eff[0].te_fd_source.lower()
    # Falls back to aggregate first_downs.
    assert eff[0].te_first_down_ppg == pytest.approx(2.5)


def test_run_analysis_warns_when_any_te_uses_estimated_first_down():
    rows = [
        _make_te_row(f"Legacy {i}", composite=9000 - i * 200) for i in range(5)
    ]
    contract = _make_contract(rows)
    payload = tep.run_analysis(contract)
    warnings_text = " ".join(payload.get("warnings") or [])
    assert "rule_contributions_detail" in warnings_text or "estimated" in warnings_text.lower()


def test_run_analysis_does_not_warn_when_detail_present():
    rows = [
        _make_te_row(
            f"Modern {i}",
            composite=9000 - i * 200,
            rule_contributions_detail={"bonus_fd_te": 0.5, "bonus_rec_te": -0.4},
        )
        for i in range(5)
    ]
    contract = _make_contract(rows)
    boards = {
        "normal": {f"modern {i}": 9000 - i * 200 for i in range(5)},
        "premium": {f"modern {i}": (9000 - i * 200) * 1.1 for i in range(5)},
        "normal_available": True,
        "premium_available": True,
    }
    payload = tep.run_analysis(contract, boards=boards)
    warnings_text = " ".join(payload.get("warnings") or [])
    assert "estimated" not in warnings_text.lower()
    assert "rule_contributions_detail" not in warnings_text


def test_overview_warns_when_detail_map_missing():
    rows = [_make_te_row("Legacy", composite=8000)]
    contract = _make_contract(rows)
    ov = tep.build_overview(
        contract,
        boards={"normal": {"legacy": 8000}, "premium": {"legacy": 8500},
                "normal_available": True, "premium_available": True},
    )
    assert any("rule_contributions_detail" in w for w in ov["warnings"])


def test_scoring_effect_removes_neither_is_noop():
    rows = [
        _make_te_row(
            "Bowers",
            rule_contributions={"te_premium": -0.4, "first_downs": 2.5},
        )
    ]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    eff = tep.compute_internal_scoring_effect(
        extracted,
        remove_te_reception_bonus=False,
        remove_te_first_down_bonus=False,
    )
    assert eff[0].scoring_swing_ppg == pytest.approx(0.0)
    assert eff[0].proposed_ppg_delta == pytest.approx(eff[0].current_ppg_delta)


# ── Scarcity effect ──────────────────────────────────────────────────


def test_scarcity_two_te_lowers_replacement_pace():
    rows = [_make_te_row(f"TE{i}", composite=8000 - i * 100, ppg_league=14 - i * 0.4) for i in range(40)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    sc_rows, summary = tep.compute_scarcity_effect(
        extracted,
        one_te_starters=12,
        two_te_starters=24,
    )
    assert summary["replacement_two_te_ppg"] < summary["replacement_one_te_ppg"]
    # VOR rises for every TE when we go to 2-TE start
    assert all(r.vor_two_te >= r.vor_one_te - 1e-6 for r in sc_rows)
    assert summary["avg_vor_delta"] > 0


def test_scarcity_skips_players_with_no_ppg():
    row = _make_te_row("Bowers")
    row["_formatFitPPGTest"] = None
    row["_formatFitPPGCustom"] = None
    extracted = tep.extract_te_players_from_contract(_make_contract([row]))
    sc_rows, summary = tep.compute_scarcity_effect(extracted)
    assert sc_rows == []
    assert summary["evaluable_tes"] == 0


# ── Tier assignment ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "rank,age,expected_tier_key,expected_age",
    [
        (1, 22, "elite_te1", "young_upside"),
        (3, 26, "elite_te1", ""),
        (8, 31, "strong_te1", "older_productive"),
        (12, 24, "back_te1", "young_upside"),
        (20, 27, "te2", ""),
        (50, 30, "depth", "older_productive"),
        (200, 22, "deep", "young_upside"),
        (None, 25, "deep", "young_upside"),
    ],
)
def test_assign_te_tier(rank, age, expected_tier_key, expected_age):
    out = tep.assign_te_tier(rank, age)
    assert out["tier_key"] == expected_tier_key
    assert out["age_tag"] == expected_age


# ── Recommendations ──────────────────────────────────────────────────


def test_recommendations_clip_to_safety_bounds():
    """Even with absurdly large signals, recommended_pct stays in ±25%."""
    rows = [_make_te_row("Brock Bowers", composite=8000)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"brock bowers": 5000.0},
        "premium": {"brock bowers": 50000.0},  # +900% boost
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    scoring = tep.compute_internal_scoring_effect(extracted)
    scarcity, _ = tep.compute_scarcity_effect(extracted)
    recs = tep.build_recommendations(
        extracted,
        boost_rows=boosts,
        scoring_rows=scoring,
        scarcity_rows=scarcity,
        market_available=True,
    )
    assert -0.25 <= recs[0].recommended_adjustment_pct <= 0.25
    assert any("clipped" in n for n in recs[0].notes)


def test_recommendations_skip_market_unwind_when_no_tep_rule_removed():
    """Codex P1 fix: when neither TEP rule is being removed, the
    market unwind should be zero so a lineup-only scenario doesn't
    spuriously knock down TE values via the external KTC TEP signal.

    A 2-TE-start scenario with TEP scoring still in place should
    produce a positive (or zero) recommendation, not a negative one
    driven by the KTC premium that's still applicable."""
    rows = [_make_te_row("Brock Bowers", composite=8000, ppg_league=14.0)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"brock bowers": 5000.0},
        "premium": {"brock bowers": 7500.0},  # +50% market boost
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    scoring_no_removal = tep.compute_internal_scoring_effect(
        extracted,
        remove_te_reception_bonus=False,
        remove_te_first_down_bonus=False,
    )
    scarcity, _ = tep.compute_scarcity_effect(extracted)
    recs = tep.build_recommendations(
        extracted,
        boost_rows=boosts,
        scoring_rows=scoring_no_removal,
        scarcity_rows=scarcity,
        market_available=True,
        remove_te_reception_bonus=False,
        remove_te_first_down_bonus=False,
    )
    # No TEP rule removed → market unwind = 0.  With a single-player
    # pool the scarcity delta is also ~0, so the rec collapses to ~0
    # rather than the -25% it would be if the market were unwound.
    assert recs[0].recommended_adjustment_pct >= -0.05
    # And the market_boost_pct is still surfaced for transparency.
    assert recs[0].market_boost_pct is not None


def test_recommendations_apply_market_unwind_when_either_tep_rule_removed():
    """Removing only the reception bonus (not the first-down bonus)
    is still a TEP-removal scenario, so market unwind should fire."""
    rows = [_make_te_row("Brock Bowers", composite=8000)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    boards = {
        "normal": {"brock bowers": 5000.0},
        "premium": {"brock bowers": 6000.0},
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    scoring = tep.compute_internal_scoring_effect(extracted)
    scarcity, _ = tep.compute_scarcity_effect(extracted)
    recs_only_rec = tep.build_recommendations(
        extracted,
        boost_rows=boosts,
        scoring_rows=scoring,
        scarcity_rows=scarcity,
        market_available=True,
        remove_te_reception_bonus=True,
        remove_te_first_down_bonus=False,
    )
    recs_neither = tep.build_recommendations(
        extracted,
        boost_rows=boosts,
        scoring_rows=scoring,
        scarcity_rows=scarcity,
        market_available=True,
        remove_te_reception_bonus=False,
        remove_te_first_down_bonus=False,
    )
    # The "remove rec only" recommendation must be more negative than
    # the "remove neither" recommendation (the difference is the
    # market unwind, which only applies in the first case).
    assert recs_only_rec[0].recommended_adjustment_pct < recs_neither[0].recommended_adjustment_pct


def test_run_analysis_run_id_has_subsecond_entropy():
    """Codex P2: two analyses started in the same wallclock second
    must produce distinct run_ids so persist=true never overwrites
    a prior file."""
    rows = [_make_te_row(f"TE{i}", composite=9000 - i * 200) for i in range(3)]
    contract = _make_contract(rows)
    p1 = tep.run_analysis(contract)
    p2 = tep.run_analysis(contract)
    assert p1["run_id"] != p2["run_id"]
    # Sanity: the new format includes a microsecond block + uuid suffix.
    parts = p1["run_id"].rstrip("Z").split("_")
    assert len(parts) == 3, f"unexpected run_id format: {p1['run_id']}"


def test_run_analysis_persist_does_not_overwrite_in_rapid_succession(tmp_path):
    rows = [_make_te_row(f"TE{i}", composite=9000 - i * 200) for i in range(3)]
    contract = _make_contract(rows)
    tep.run_analysis(contract, persist=True, sandbox_dir=tmp_path)
    tep.run_analysis(contract, persist=True, sandbox_dir=tmp_path)
    files = list(tmp_path.glob("te_premium_*.json"))
    assert len(files) == 2, "second persist run silently overwrote the first"


def test_lineup_settings_two_te_is_noop_when_league_already_starts_two():
    """Codex P2 fix: in a league whose starters.TE is already 2,
    the "Start 2 TEs" toggle should be a no-op rather than adding
    another TE per team (which would over-model scarcity)."""
    class _FakeCfg:
        roster_settings = {
            "teamCount": 12,
            "starters": {
                "QB": 1, "RB": 2, "WR": 3, "TE": 2,  # already 2
                "FLEX": 1, "SFLEX": 1,
            },
        }

    out = tep._league_lineup_settings(_FakeCfg())
    assert out["te_starters_one"] == out["te_starters_two"]
    assert out["two_te_is_noop"] is True
    assert out["direct_te_per_team_current"] == 2


def test_lineup_settings_two_te_adds_one_te_per_team_when_league_starts_one():
    """Default case: TE=1 → 2-TE toggle adds one direct starter per team."""
    class _FakeCfg:
        roster_settings = {
            "teamCount": 12,
            "starters": {
                "QB": 1, "RB": 2, "WR": 3, "TE": 1,
                "FLEX": 2, "SFLEX": 1,
            },
        }

    out = tep._league_lineup_settings(_FakeCfg())
    assert out["te_starters_two"] == out["te_starters_one"] + 12
    assert out["two_te_is_noop"] is False
    assert out["direct_te_per_team_current"] == 1
    assert out["direct_te_per_team_proposed"] == 2


def test_lineup_settings_two_te_handles_zero_direct_te():
    """Edge: a league with no direct TE slot (TE only via flex).
    Going to "Start 2 TEs" should add 2 starters per team."""
    class _FakeCfg:
        roster_settings = {
            "teamCount": 10,
            "starters": {
                "QB": 1, "RB": 2, "WR": 3, "FLEX": 2, "SFLEX": 1,
            },
        }

    out = tep._league_lineup_settings(_FakeCfg())
    # 2 TEs/team × 10 teams = 20 added on top of flex contributions.
    assert out["te_starters_two"] - out["te_starters_one"] == 20
    assert out["two_te_is_noop"] is False
    assert out["direct_te_per_team_current"] == 0


def test_recommendations_use_tier_default_when_no_market():
    rows = [_make_te_row("Bowers", composite=8000)]
    extracted = tep.extract_te_players_from_contract(_make_contract(rows))
    scoring = tep.compute_internal_scoring_effect(extracted)
    scarcity, _ = tep.compute_scarcity_effect(extracted)
    recs = tep.build_recommendations(
        extracted,
        boost_rows=[],
        scoring_rows=scoring,
        scarcity_rows=scarcity,
        market_available=False,
    )
    assert any("tier default" in n for n in recs[0].notes)


# ── End-to-end + safety ──────────────────────────────────────────────


def test_run_analysis_returns_documented_shape(monkeypatch):
    rows = [
        _make_te_row(f"TE{i}", composite=9000 - i * 200, ppg_league=14 - i * 0.3)
        for i in range(20)
    ]
    contract = _make_contract(rows)
    boards = {
        "normal": {f"te{i}": 9000 - i * 200 for i in range(20)},
        "premium": {f"te{i}": (9000 - i * 200) * 1.1 for i in range(20)},
        "normal_available": True,
        "premium_available": True,
    }
    payload = tep.run_analysis(contract, boards=boards)
    assert payload["sandbox"] is True
    assert payload["scenario"]["remove_te_reception_bonus"] is True
    assert "summary" in payload
    assert "recommendations" in payload
    assert "tier_summary" in payload
    assert "external_boost" in payload
    assert "scoring_effect" in payload
    assert "scarcity_effect" in payload
    assert payload["summary"]["te_count"] == 20


def test_run_analysis_does_not_mutate_input_contract():
    """The single most important safety property: every analysis is a
    pure read.  Deep-compare the contract before and after."""
    rows = [_make_te_row(f"TE{i}", composite=9000 - i * 200) for i in range(15)]
    contract = _make_contract(rows)
    snapshot = json.dumps(contract, sort_keys=True, default=str)
    tep.run_analysis(contract)
    after = json.dumps(contract, sort_keys=True, default=str)
    assert snapshot == after, "run_analysis mutated its input contract"


def test_run_analysis_does_not_persist_unless_asked(tmp_path):
    rows = [_make_te_row(f"TE{i}", composite=9000 - i * 200) for i in range(10)]
    contract = _make_contract(rows)
    payload = tep.run_analysis(contract, sandbox_dir=tmp_path)
    # Nothing written on the default path
    assert list(tmp_path.glob("*.json")) == []
    assert "persisted_path" not in payload


def test_run_analysis_persists_when_asked(tmp_path):
    rows = [_make_te_row(f"TE{i}", composite=9000 - i * 200) for i in range(5)]
    contract = _make_contract(rows)
    payload = tep.run_analysis(contract, persist=True, sandbox_dir=tmp_path)
    files = list(tmp_path.glob("te_premium_*.json"))
    assert len(files) == 1
    assert payload.get("persisted_path") == str(files[0])
    on_disk = json.loads(files[0].read_text())
    assert on_disk["sandbox"] is True


def test_build_overview_warns_when_no_te_rows():
    contract = {"players": {}}
    ov = tep.build_overview(contract, boards={"normal": {}, "premium": {}, "normal_available": False, "premium_available": False})
    assert ov["te_count"] == 0
    assert any("No TE rows" in w for w in ov["warnings"])
    assert ov["sandbox"] is True


def test_run_analysis_handles_empty_contract():
    payload = tep.run_analysis({}, boards={"normal": {}, "premium": {}})
    assert payload["summary"]["te_count"] == 0
    assert payload["recommendations"] == []


# ── External board loader ────────────────────────────────────────────


def test_load_external_ktc_boards_handles_missing_files(tmp_path):
    boards = tep.load_external_ktc_boards(
        normal_path=tmp_path / "missing_normal.csv",
        premium_path=tmp_path / "missing_premium.csv",
    )
    assert boards["normal_available"] is False
    assert boards["premium_available"] is False
    assert boards["normal"] == {}
    assert boards["premium"] == {}


def test_load_external_ktc_boards_reads_real_files(tmp_path):
    csv_path = tmp_path / "ktc.csv"
    csv_path.write_text("name,value\nBrock Bowers,9000\nSam LaPorta,7500\n")
    premium_path = tmp_path / "ktcSfTep.csv"
    premium_path.write_text("name,value\nBrock Bowers,9500\nSam LaPorta,8200\n")
    boards = tep.load_external_ktc_boards(
        normal_path=csv_path, premium_path=premium_path,
    )
    assert boards["normal_available"] is True
    assert boards["premium_available"] is True
    assert boards["normal"]["brock bowers"] == 9000.0
    assert boards["premium"]["sam laporta"] == 8200.0


# ── Multi-source comparison ───────────────────────────────────────────


def test_load_external_source_pairs_handles_capitalized_columns(tmp_path):
    """DynastyNerds' fetcher emits ``Name,Rank,Value`` (uppercase
    headers); the loader must read it case-insensitively to round-trip
    through the comparison cleanly.
    """
    csv_dir = tmp_path / "CSVs" / "site_raw"
    csv_dir.mkdir(parents=True)
    (csv_dir / "dynastyNerdsSf.csv").write_text(
        "Name,Rank,Value,SleeperId,Pos,Team\n"
        "Brock Bowers,1,8500,11604,TE,LV\n"
    )
    (csv_dir / "dynastyNerdsSfTep.csv").write_text(
        "Name,Rank,Value,SleeperId,Pos,Team\n"
        "Brock Bowers,1,9700,11604,TE,LV\n"
    )
    pairs = tep.load_external_source_pairs(repo_root=tmp_path)
    dn = next(p for p in pairs if p["key"] == "dynastyNerds")
    assert dn["available"] is True
    assert dn["normal"]["brock bowers"] == 8500.0
    assert dn["premium"]["brock bowers"] == 9700.0


def test_load_external_source_pairs_marks_missing_pairs_unavailable(tmp_path):
    """Pairs whose CSVs aren't on disk surface with ``available=False``
    so the API can skip them without raising; downstream UI then shows
    them as "configured but unavailable" instead of dropping them
    silently.
    """
    pairs = tep.load_external_source_pairs(repo_root=tmp_path)
    by_key = {p["key"]: p for p in pairs}
    assert all(p["available"] is False for p in pairs)
    assert by_key["ktc"]["normal"] == {}
    assert by_key["dynastyDaddy"]["premium"] == {}


def test_compute_top_te_source_comparison_aggregates_per_source():
    """End-to-end: pair_data + te_rows in, comparison out with per-row
    boost data and per-source aggregates.  Sources with at least one
    reliable row contribute to the aggregate; missing pairs are
    surfaced in ``sources`` meta with ``available=False``.
    """
    pair_data = [
        {
            "key": "ktc",
            "label": "KeepTradeCut",
            "mode": "value",
            "premium_label": "TE++",
            "note": "test",
            "normal_path": "ktc.csv",
            "premium_path": "ktcSfTep.csv",
            "normal_available": True,
            "premium_available": True,
            "available": True,
            "normal": {
                "brock bowers": 7800.0,
                "sam laporta": 6500.0,
                "tyler warren": 5500.0,
            },
            "premium": {
                "brock bowers": 9500.0,
                "sam laporta": 8200.0,
                "tyler warren": 6800.0,
            },
        },
        {
            "key": "dynastyDaddy",
            "label": "Dynasty Daddy",
            "mode": "value",
            "premium_label": "TEP",
            "note": "test",
            "normal_path": "ddBase.csv",
            "premium_path": "dd.csv",
            "normal_available": False,
            "premium_available": False,
            "available": False,
            "normal": {},
            "premium": {},
        },
    ]
    te_rows = [
        {
            "player_id": "p1",
            "display_name": "Brock Bowers",
            "te_pool_rank": 1,
            "current_value": 9999,
            "team": "LV",
            "age": 23,
        },
        {
            "player_id": "p2",
            "display_name": "Sam LaPorta",
            "te_pool_rank": 2,
            "current_value": 7000,
            "team": "DET",
            "age": 25,
        },
        {
            "player_id": "p3",
            "display_name": "Tyler Warren",
            "te_pool_rank": 3,
            "current_value": 6500,
            "team": "IND",
            "age": 24,
        },
    ]
    result = tep.compute_top_te_source_comparison(
        te_rows, pair_data=pair_data, top_n=3,
    )
    assert result["te_count"] == 3
    assert result["top_n"] == 3
    keys = [s["key"] for s in result["sources"]]
    assert "ktc" in keys and "dynastyDaddy" in keys
    dd_meta = next(s for s in result["sources"] if s["key"] == "dynastyDaddy")
    assert dd_meta["available"] is False

    # KTC ran successfully on all 3 rows.
    bowers = next(r for r in result["rows"] if r["display_name"] == "Brock Bowers")
    ktc_cell = bowers["by_source"]["ktc"]
    assert abs(ktc_cell["boost_pct"] - ((9500 - 7800) / 7800)) < 1e-6
    assert ktc_cell["normal"] == 7800
    assert ktc_cell["premium"] == 9500

    # DynastyDaddy is unavailable so by_source has no entry for it.
    assert "dynastyDaddy" not in bowers["by_source"]

    assert "ktc" in result["source_aggregates"]
    ktc_agg = result["source_aggregates"]["ktc"]
    assert ktc_agg["n"] == 3
    assert ktc_agg["avg_boost_pct"] is not None


def test_compute_external_market_boost_floor_scales_for_small_boards():
    """Fitzmaurice publishes 0-100 — the legacy 200 floor would flag
    every row unreliable and zero out the aggregate.  The
    scale-relative floor lets small-scale boards contribute.
    """
    boards = {
        "normal": {"brock bowers": 70, "sam laporta": 44},
        "premium": {"brock bowers": 83, "sam laporta": 53},
    }
    te_rows = [
        {"player_id": "p1", "display_name": "Brock Bowers"},
        {"player_id": "p2", "display_name": "Sam LaPorta"},
    ]
    boosts = tep.compute_external_market_boost(
        te_rows, boards=boards, source="fitzmaurice",
    )
    assert all(b.reliable for b in boosts)
    assert all(b.boost_pct is not None and b.boost_pct > 0 for b in boosts)


def test_compute_top_te_source_comparison_empty_when_no_pairs_available():
    """When no pair_data is available the comparison still returns a
    well-formed payload with empty rows + an empty aggregate; the API
    + UI should handle this case without errors.
    """
    pair_data = [
        {
            "key": "ktc", "label": "KTC", "mode": "value",
            "premium_label": "TE++", "note": "",
            "normal_path": "", "premium_path": "",
            "normal_available": False, "premium_available": False,
            "available": False,
            "normal": {}, "premium": {},
        },
    ]
    result = tep.compute_top_te_source_comparison(
        [{"player_id": "p1", "display_name": "Bowers", "te_pool_rank": 1}],
        pair_data=pair_data, top_n=24,
    )
    assert result["rows"] == []
    assert result["te_count"] == 0
    assert result["source_aggregates"] == {}
    # Sources meta still surfaces the unavailable source.
    assert any(s["key"] == "ktc" for s in result["sources"])
