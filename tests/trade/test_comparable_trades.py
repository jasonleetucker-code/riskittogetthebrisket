"""C4-MTL-03 — comparable-trade matching.

``_classify`` is tested directly as a pure function over format dicts
(the shape ``market_trade_ledger._format_metadata`` produces), since that
is where the real decision logic lives and it needs no registry or
acquisition-store fixtures to exercise. ``comparable_trades_for_asset``'s
wiring (grouping, self-exclusion, sorting) is tested with the registry
and ledger reads replaced by simple stand-ins, so these tests stay
invariant-based rather than coupled to live registry/scoring-snapshot
state.
"""

from __future__ import annotations

from types import SimpleNamespace

import src.trade.comparable_trades as ct
from src.trade.comparable_trades import (
    TIER_BROAD,
    TIER_EXACT,
    TIER_NEAR,
    TIER_UNSUPPORTED,
    _classify,
    comparable_trades_for_asset,
)


def _fmt(*, teams=None, superflex=None, tep=None, is2te=None, idp=None):
    return {
        "teams": teams,
        "superflex": superflex,
        "tep": tep,
        "tepLevel": None,
        "is2Te": is2te,
        "idp": idp,
    }


# ── _classify ────────────────────────────────────────────────────────


def test_exact_when_every_core_dimension_and_team_count_match():
    target = _fmt(teams=12, superflex=True, tep=True, is2te=True, idp=True)
    source = _fmt(teams=12, superflex=True, tep=True, is2te=True, idp=True)
    tier, reasons = _classify(target, source)
    assert tier == TIER_EXACT
    assert reasons


def test_near_when_core_matches_but_team_count_is_close():
    target = _fmt(teams=12, superflex=True, tep=True, idp=False)
    source = _fmt(teams=10, superflex=True, tep=True, idp=False)
    tier, _ = _classify(target, source)
    assert tier == TIER_NEAR


def test_broad_when_team_count_is_far_apart_despite_core_match():
    target = _fmt(teams=12, superflex=True, tep=True, idp=False)
    source = _fmt(teams=8, superflex=True, tep=True, idp=False)
    tier, reasons = _classify(target, source)
    assert tier == TIER_BROAD
    assert any("team count" in r for r in reasons)


def test_broad_when_a_core_dimension_differs():
    target = _fmt(teams=12, superflex=True, tep=True, idp=False)
    source = _fmt(teams=12, superflex=False, tep=True, idp=False)
    tier, reasons = _classify(target, source)
    assert tier == TIER_BROAD
    assert any("superflex" in r for r in reasons)


def test_unsupported_when_a_required_dimension_is_unknown_on_either_side():
    target = _fmt(teams=12, superflex=True, tep=None, idp=False)
    source = _fmt(teams=12, superflex=True, tep=True, idp=False)
    tier, reasons = _classify(target, source)
    assert tier == TIER_UNSUPPORTED
    assert any("tep" in r for r in reasons)


def test_unknown_dimension_is_never_treated_as_a_broad_mismatch():
    """An unproven dimension must fail closed to UNSUPPORTED, not be
    silently treated as a match OR a mismatch (which would land it in
    BROAD instead)."""
    target = _fmt(teams=12, superflex=None, tep=True, idp=True)
    source = _fmt(teams=12, superflex=True, tep=True, idp=True)
    tier, _ = _classify(target, source)
    assert tier == TIER_UNSUPPORTED


def test_near_when_is_2te_mismatches_but_teams_and_core_match():
    target = _fmt(teams=12, superflex=True, tep=True, idp=False, is2te=True)
    source = _fmt(teams=12, superflex=True, tep=True, idp=False, is2te=False)
    tier, _ = _classify(target, source)
    assert tier == TIER_NEAR


# ── comparable_trades_for_asset wiring ─────────────────────────────────


def _trade(source_ref, *, asset_id="player:4034", occurred_at_ms=None, fmt=None, rid1=1, rid2=2):
    return {
        "leagueKey": "src_league",
        "sourceRef": source_ref,
        "season": "2026",
        "week": 3,
        "occurredAtMs": occurred_at_ms,
        "timeFidelity": "exact" if occurred_at_ms is not None else "undated",
        "assetCount": 1,
        "teamCount": 2,
        "teams": {
            str(rid1): {"received": [], "sent": [{"assetId": asset_id, "assetKind": "player"}]},
            str(rid2): {"received": [{"assetId": asset_id, "assetKind": "player"}], "sent": []},
        },
        "format": fmt or _fmt(teams=12, superflex=True, tep=True, idp=False),
        "sourceFamily": "own_league_sleeper",
        "dynastyVerified": True,
    }


def test_comparable_trades_excludes_the_target_league_and_untouched_trades(monkeypatch):
    monkeypatch.setattr(
        ct,
        "TargetFormat",
        SimpleNamespace(
            from_registry=lambda key: SimpleNamespace(
                teams=12, superflex=True, tep=True, tep_level=None, is_2te=True, idp=False
            )
        ),
    )
    monkeypatch.setattr(
        ct,
        "active_leagues",
        lambda: [SimpleNamespace(key="target"), SimpleNamespace(key="other")],
    )

    def _fake_market_trades(league_key, *, path=None):
        if league_key == "target":
            # Should never be reached: the target league is excluded before
            # market_trades is even called for it.
            raise AssertionError("target league must not be queried")
        return [
            _trade("tx:1", asset_id="player:4034", occurred_at_ms=100),
            _trade("tx:2", asset_id="player:9999", occurred_at_ms=200),  # untouched asset
        ]

    monkeypatch.setattr(ct, "market_trades", _fake_market_trades)

    results = comparable_trades_for_asset("player:4034", "target")

    assert len(results) == 1
    assert results[0]["sourceRef"] == "tx:1"
    assert results[0]["matchTier"] == TIER_EXACT


def test_comparable_trades_sorts_newest_first_with_undated_last(monkeypatch):
    monkeypatch.setattr(
        ct,
        "TargetFormat",
        SimpleNamespace(
            from_registry=lambda key: SimpleNamespace(
                teams=12, superflex=True, tep=True, tep_level=None, is_2te=True, idp=False
            )
        ),
    )
    monkeypatch.setattr(ct, "active_leagues", lambda: [SimpleNamespace(key="other")])
    monkeypatch.setattr(
        ct,
        "market_trades",
        lambda league_key, **kw: [
            _trade("tx:old", occurred_at_ms=100),
            _trade("tx:new", occurred_at_ms=300),
            _trade("tx:undated", occurred_at_ms=None),
        ],
    )

    results = comparable_trades_for_asset("player:4034", "target")

    assert [r["sourceRef"] for r in results] == ["tx:new", "tx:old", "tx:undated"]


def test_no_leagues_returns_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(
        ct,
        "TargetFormat",
        SimpleNamespace(
            from_registry=lambda key: SimpleNamespace(
                teams=None, superflex=None, tep=None, tep_level=None, is_2te=None, idp=None
            )
        ),
    )
    monkeypatch.setattr(ct, "active_leagues", lambda: [])
    assert comparable_trades_for_asset("player:4034", "target") == []
