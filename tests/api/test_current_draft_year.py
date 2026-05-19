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


def _offset_cfg():
    return {
        "currentDraftYear": None,
        "offsetDiscounts": {"0": 1.00, "1": 0.82, "2": 0.66, "3": 0.53},
        "fallbackBase": 0.80,
    }


def test_next_draft_has_no_penalty():
    cfg = _offset_cfg()
    # Active draft = 2026 (offset 0): the user's "take the penalty off
    # the next draft" requirement.
    assert dc._pick_year_discount_for(2026, cfg, current_draft_year=2026) == 1.0
    # A past class is never penalized either.
    assert dc._pick_year_discount_for(2025, cfg, current_draft_year=2026) == 1.0


def test_offset_discounts_apply_by_distance():
    cfg = _offset_cfg()
    assert dc._pick_year_discount_for(2027, cfg, current_draft_year=2026) == 0.82
    assert dc._pick_year_discount_for(2028, cfg, current_draft_year=2026) == 0.66
    assert dc._pick_year_discount_for(2029, cfg, current_draft_year=2026) == 0.53
    # Beyond the configured offsets → exponential fallback.
    assert dc._pick_year_discount_for(2030, cfg, current_draft_year=2026) == pytest.approx(
        0.80**4
    )


def test_discount_self_rolls_when_active_year_advances():
    cfg = _offset_cfg()
    # Once sources roll to 2027 as the active class, 2027 loses its
    # penalty and 2028 becomes the offset-1 year automatically — no
    # config edit.
    assert dc._pick_year_discount_for(2027, cfg, current_draft_year=2027) == 1.0
    assert dc._pick_year_discount_for(2028, cfg, current_draft_year=2027) == 0.82


def test_legacy_absolute_schema_still_honored():
    cfg = {
        "currentDraftYear": None,
        "offsetDiscounts": {},
        "discounts": {"2027": 0.5},
        "fallbackBase": 0.80,
    }
    assert dc._pick_year_discount_for(2027, cfg, current_draft_year=2026) == 0.5
