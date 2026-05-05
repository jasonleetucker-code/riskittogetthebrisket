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
    boards = {
        "normal": {"deep reserve": 50.0},  # below floor 200
        "premium": {"deep reserve": 250.0},
    }
    boosts = tep.compute_external_market_boost(extracted, boards=boards)
    b = boosts[0]
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
