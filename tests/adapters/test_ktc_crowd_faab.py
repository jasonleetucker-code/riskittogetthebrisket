"""Tests for ``src/adapters/ktc_crowd_faab.py``.

Bridge between KTC's crowd waiver database (collected by Dynasty
Scraper.py::scrape_ktc_waiver_database) and the FAAB recommender's
``ktc_crowd_bids`` calibration parameter.
"""

from __future__ import annotations

from src.adapters.ktc_crowd_faab import (
    build_crowd_bid_map,
    crowd_bid_map_from_contract,
)


def _wv(added, bid=None, bid_pct=None, dropped="", settings=None):
    """Shape one waiver entry the way Dynasty Scraper emits."""
    return {
        "source": "ktc",
        "date": "2026-01-01",
        "added": added,
        "dropped": dropped,
        "bid": bid if bid is not None else 0,
        "bidPct": bid_pct if bid_pct is not None else "",
        "settings": settings or {"waiver_budget": 100},
    }


def test_empty_or_malformed_input_returns_empty_map():
    assert build_crowd_bid_map(None) == {}
    assert build_crowd_bid_map({}) == {}
    assert build_crowd_bid_map({"waivers": None}) == {}
    assert build_crowd_bid_map({"waivers": "not a list"}) == {}
    assert build_crowd_bid_map({"waivers": []}) == {}


def test_directly_provided_bid_pct_lifts_through():
    """When KTC supplies ``bidPct`` directly, no division needed
    — the bridge takes the value verbatim and medians across
    samples."""
    ktc = {
        "waivers": [
            _wv("Hot Player", bid_pct="22"),
            _wv("Hot Player", bid_pct="28"),
            _wv("Hot Player", bid_pct="25"),
            # other players get their own samples
            _wv("Cold Player", bid_pct="3"),
            _wv("Cold Player", bid_pct="5"),
        ],
    }
    out = build_crowd_bid_map(ktc, min_samples=2)
    assert "hotplayer" in out
    assert out["hotplayer"] == 25.0  # median of 22, 25, 28
    assert "coldplayer" in out
    assert out["coldplayer"] == 4.0


def test_derives_pct_from_bid_and_settings_when_pct_missing():
    """Older KTC entries omit ``bidPct`` — the bridge derives
    from ``bid / settings.waiver_budget * 100`` so multi-budget
    leagues normalize correctly."""
    ktc = {
        "waivers": [
            _wv("Player X", bid=20, settings={"waiver_budget": 100}),  # 20%
            _wv("Player X", bid=40, settings={"waiver_budget": 200}),  # 20%
            _wv("Player X", bid=10, settings={"waiver_budget": 100}),  # 10%
        ],
    }
    out = build_crowd_bid_map(ktc, min_samples=2)
    # Median of [20, 20, 10] = 20.
    assert out["playerx"] == 20.0


def test_min_samples_filters_noisy_singletons():
    """Single-bid samples are too noisy — bridge requires
    min_samples=2 by default, drops anything below."""
    ktc = {
        "waivers": [
            _wv("Solo", bid=15, settings={"waiver_budget": 100}),
            _wv("Together A", bid=10, settings={"waiver_budget": 100}),
            _wv("Together A", bid=20, settings={"waiver_budget": 100}),
        ],
    }
    out = build_crowd_bid_map(ktc, min_samples=2)
    assert "solo" not in out
    assert "togethera" in out


def test_skips_entries_missing_added_or_bid():
    """Entries without an ``added`` player or without any
    resolvable bid percentage are silently skipped."""
    ktc = {
        "waivers": [
            _wv("", bid=10, settings={"waiver_budget": 100}),  # no name
            _wv("Bad Bid", bid=0, bid_pct=""),  # no pct
            _wv("Good", bid_pct="20"),
            _wv("Good", bid_pct="30"),
        ],
    }
    out = build_crowd_bid_map(ktc, min_samples=2)
    assert out == {"good": 25.0}


def test_normalizes_name_keys():
    """Output keys are normalized (lowercase + alnum-only) so they
    line up with the recommender endpoint's lookup."""
    ktc = {
        "waivers": [
            _wv("Ja'Marr Chase", bid_pct="40"),
            _wv("ja'marr chase", bid_pct="38"),
            _wv("D.J. Moore", bid_pct="22"),
            _wv("DJ Moore", bid_pct="24"),
        ],
    }
    out = build_crowd_bid_map(ktc, min_samples=2)
    assert "jamarrchase" in out
    assert "djmoore" in out


def test_contract_wrapper_pulls_ktcCrowd_block():
    """``crowd_bid_map_from_contract`` is the typical entry point
    from the server — it accepts a full contract payload and
    surfaces the ``ktcCrowd`` block."""
    contract = {
        "ktcCrowd": {
            "waivers": [
                _wv("X", bid_pct="10"),
                _wv("X", bid_pct="14"),
            ],
        },
    }
    assert crowd_bid_map_from_contract(contract) == {"x": 12.0}

    # Missing/null contract returns empty map (defensive default).
    assert crowd_bid_map_from_contract(None) == {}
    assert crowd_bid_map_from_contract({}) == {}
    assert crowd_bid_map_from_contract({"ktcCrowd": None}) == {}
