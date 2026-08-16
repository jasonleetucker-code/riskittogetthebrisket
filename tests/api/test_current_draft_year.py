"""Current-rookie-draft-year derivation + offset pick discount.

Pins the self-rolling behavior so the "stale baseline" bug can't
return: the active draft year is derived from the scrape's slot picks,
the next draft carries NO penalty, and the discount rolls forward on
its own when the data sources advance.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import src.api.data_contract as dc


@pytest.fixture(autouse=True)
def _isolate_module_state():
    """Reset the per-build globals + config cache around each test."""
    saved_cache = dc._PICK_YEAR_DISCOUNT_CACHE
    saved_obs = dc._OBSERVED_CURRENT_DRAFT_YEAR
    dc._PICK_YEAR_DISCOUNT_CACHE = None
    dc._OBSERVED_CURRENT_DRAFT_YEAR = None
    yield
    dc._PICK_YEAR_DISCOUNT_CACHE = saved_cache
    dc._OBSERVED_CURRENT_DRAFT_YEAR = saved_obs


def test_derive_from_slot_names_picks_lowest_slot_year():
    names = [
        "Josh Allen",
        "2026 Pick 1.01",
        "2026 Pick 6.12",
        "2027 Early 1st",  # generic tier — not a slot, ignored
        "2027 Pick 1.05",  # a later slot year is present too
    ]
    assert dc._derive_current_draft_year_from_names(names) == 2026


def test_derive_returns_none_without_slot_rows():
    assert dc._derive_current_draft_year_from_names(["2027 Early 1st", "Bijan Robinson"]) is None


def test_config_override_wins_over_observed_and_date():
    dc._PICK_YEAR_DISCOUNT_CACHE = {
        "currentDraftYear": 2031,
        "offsetDiscounts": {},
        "fallbackBase": 0.80,
        "rolloverMonth": 5,
        "rolloverDay": 15,
    }
    dc.set_observed_current_draft_year(2026)
    assert dc.current_rookie_draft_year(today=_dt.date(2026, 1, 1)) == 2031


def test_observed_data_used_when_no_override():
    dc._PICK_YEAR_DISCOUNT_CACHE = {
        "currentDraftYear": None,
        "offsetDiscounts": {},
        "fallbackBase": 0.80,
        "rolloverMonth": 5,
        "rolloverDay": 15,
    }
    dc.set_observed_current_draft_year(2026)
    # Date would say 2027 here, but the scrape-derived value wins.
    assert dc.current_rookie_draft_year(today=_dt.date(2026, 12, 31)) == 2026


def test_date_fallback_rolls_at_configured_boundary():
    dc._PICK_YEAR_DISCOUNT_CACHE = {
        "currentDraftYear": None,
        "offsetDiscounts": {},
        "fallbackBase": 0.80,
        "rolloverMonth": 5,
        "rolloverDay": 15,
    }
    dc.set_observed_current_draft_year(None)  # no scrape (cold start)
    assert dc.current_rookie_draft_year(today=_dt.date(2026, 5, 14)) == 2026
    assert dc.current_rookie_draft_year(today=_dt.date(2026, 5, 15)) == 2027


def _step_cfg():
    return {
        "currentDraftYear": None,
        "horizonYears": 3,
        "yearStepByTierRound": {"early.1": 0.7138, "late.4": 0.7726},
        "yearStepByRound": {"1": 0.8078, "2": 0.8662},
        "yearStepFallback": 0.8407,
        "roundStepByRound": {"5": 0.929, "6": 0.916},
    }


# The retired ``_pick_year_discount_for`` (offsetDiscounts
# 1.00/0.82/0.66/0.53 + fallbackBase**offset) is DELETED — C1-U6 replaced
# the offset-from-current multiplier family with the measured vendor
# year-step applied at injection (audit V-12/C-11; challenger record in
# docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md).  The properties the old
# tests pinned survive in the successor and are pinned below.


def test_retired_discount_machinery_is_gone():
    assert not hasattr(dc, "_pick_year_discount_for")


def test_vendor_years_carry_no_penalty_structurally():
    # "Take the penalty off the next draft" survives STRUCTURALLY: the
    # year-step is only ever applied to names the injection synthesised
    # (_SYNTHETIC_PICK_DERIVATIONS gate), and the injection only mints
    # years with no vendor rows.  The current draft, the past, and every
    # vendor-priced future year never receive any factor — pinned
    # end-to-end by tests/api/test_pick_year_discount_gate.py.
    players = [
        {"assetClass": "pick", "canonicalName": "2026 Pick 1.01"},
        {"assetClass": "pick", "canonicalName": "2027 Early 1st"},
    ]
    out, applied = dc._apply_pick_year_discount_to_blend([(1000.0, 0), (900.0, 1)], players)
    assert [v for v, _ in out] == [1000.0, 900.0]
    assert applied == {}
    assert all("pickYearDiscount" not in p for p in players)


def test_year_step_lookup_order_cell_round_fallback():
    cfg = _step_cfg()
    assert dc._year_step_for("Early", 1, cfg) == 0.7138  # cell
    assert dc._year_step_for("Mid", 1, cfg) == 0.8078  # round
    assert dc._year_step_for("Mid", 3, cfg) == 0.8407  # pooled fallback
    assert dc._year_step_for(None, None, cfg) == 0.8407


def test_year_step_rejects_pathological_parameters():
    # A step above 1.0 (a "future year worth MORE" parameter) or at/near
    # zero is a config pathology, not a valid derivation — clamped to
    # (0.05, 1.0].
    cfg = {"yearStepByRound": {"1": 4.2}, "yearStepFallback": 0.0}
    assert dc._year_step_for("Early", 1, cfg) == 1.0
    assert dc._year_step_for("Early", 2, cfg) == 0.05
    cfg_bad = {"yearStepFallback": "not-a-number"}
    assert dc._year_step_for("Early", 1, cfg_bad) == 0.84


def test_injection_self_rolls_and_compounds_across_gaps():
    # Once sources roll to 2027 as the active class, the horizon becomes
    # 2030 and the injection derives it from the deepest published year
    # automatically — no config edit.  A multi-year gap compounds
    # step**gap.
    prev_cache = dc._PICK_YEAR_DISCOUNT_CACHE
    dc._PICK_YEAR_DISCOUNT_CACHE = _step_cfg()
    try:
        players = {
            "2028 Early 1st": {"idpTradeCalc": 5000.0},
        }
        added = dc._inject_far_future_pick_sources(players, 2027)
        # 2029 clones 2028 (gap 1), 2030 clones synthetic 2029 (gap 1).
        assert added == 2
        assert players["2029 Early 1st"]["idpTradeCalc"] == pytest.approx(5000 * 0.7138, abs=0.1)
        assert players["2030 Early 1st"]["idpTradeCalc"] == pytest.approx(
            5000 * 0.7138 * 0.7138, abs=0.1
        )
        key = dc._canonical_match_key("2030 Early 1st")
        assert dc._SYNTHETIC_PICK_DERIVATIONS[key]["classification"] == "PRIOR"
    finally:
        dc._PICK_YEAR_DISCOUNT_CACHE = prev_cache
        dc._SYNTHETIC_FAR_FUTURE_PICK_NAMES = set()
        dc._SYNTHETIC_PICK_DERIVATIONS = {}
