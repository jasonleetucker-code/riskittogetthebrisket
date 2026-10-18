"""Trade discovery on a REAL dynasty_main board (owner directive 2026-10-18).

Read-only over the newest COMPLETE archived scrape (``tests/archive_fixtures``)
— deterministic, tracked, and it SKIPS rather than passing vacuously.  Every
assertion is an INVARIANT, never a count of the live board (CI two-lane rule):
the default discovery results are never led by a deep bench player, every
default result brings back a player inside Target Quality, and the order is
the declared one.
"""

from __future__ import annotations

import pytest

from src.trade import discovery as disc
from src.trade import finder
from src.trade import golden_upgrades as gu


@pytest.fixture(scope="module")
def board():
    from src.api.data_contract import build_api_data_contract
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, label = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape available")
    contract = build_api_data_contract(raw)
    teams = (contract.get("sleeper") or {}).get("teams") or []
    if len(teams) < 2:
        pytest.skip(f"{label}: fewer than two rosters")
    return raw, contract, teams


DEFAULT = disc.DiscoveryFilters(quality="top250", scope="both", sort="most_impactful")


def test_default_golden_upgrades_are_never_led_by_filler(board):
    raw, contract, teams = board
    index = disc.CanonicalIndex(contract)
    any_result = False
    for team in teams:
        out = gu.find_golden_upgrades(
            raw["players"], team["name"], teams, contract=contract, discovery=DEFAULT
        )
        ups = out["upgrades"]
        any_result = any_result or bool(ups)
        for u in ups:
            rank = u["target"]["rank"]
            assert rank is not None and rank <= 250, (team["name"], u["target"])
            assert u["discovery"]["meetsTargetQuality"] is True
        impacts = [u["discovery"]["impact"] for u in ups]
        assert impacts == sorted(impacts, reverse=True)
        if not ups:
            # An empty default says why and how to broaden — never padded.
            assert out["noResultReason"]
        legacy = gu.find_golden_upgrades(raw["players"], team["name"], teams, contract=contract)
        if legacy["upgrades"] and ups:
            lead = legacy["upgrades"][0]["target"]["name"]
            if (index.rank(lead) or 10**9) > 250:
                assert ups[0]["target"]["name"] != lead
    if not any_result:
        pytest.skip("no Top 250 Golden Upgrade on this board for any team")


def test_default_package_scan_brings_back_a_top_250_player(board):
    raw, contract, teams = board
    me = max(teams, key=lambda t: len(t.get("players") or []))["name"]
    out = finder.find_trades(
        raw["players"],
        me,
        [t["name"] for t in teams if t["name"] != me]
        + [{"__arbitrageControl": {"equalCountOnly": True}}],
        teams,
        contract=contract,
        use_team_context=False,
        discovery=DEFAULT,
    )
    trades = out["trades"]
    if not trades:
        assert out["metadata"]["discovery"].get("emptyReason")
        pytest.skip("no default Package Scan result on this board")
    for t in trades:
        best = t["discovery"]["bestIncoming"]
        assert best and best["rank"] is not None and best["rank"] <= 250
        assert t["boardDelta"] > 0  # the finder's own gate still holds
    impacts = [t["discovery"]["impact"] for t in trades]
    assert impacts == sorted(impacts, reverse=True)
