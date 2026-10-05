"""Wave B (B1) — C3-TOPO-01 on every generated-trade surface.

``src/packages/construction.py::topology_is_allowed`` is the owner rule:
``abs(players_A - players_B) <= 1`` and picks are not players.  Angle sized its
counter-packages by ASSET count (N-1, N, N+1), so an offer of one player plus
two picks (N = 3) could be answered with four players — a 4-for-1 in the only
count a manager reads.
"""

from __future__ import annotations

from src.packages import UNCONSTRAINED_OUTGOING
from src.trade.angle import find_acquisition_packages, find_angle_packages


def _row(name, my_val, ktc_val, *, position="WR"):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": position,
        "rankDerivedValue": my_val,
        "canonicalSiteValues": {"ktc": ktc_val},
    }


def _players():
    rows = [
        _row("My Star", 3000, 3000),
        _row("2027 Round 1", 2500, 2500, position="PICK"),
        _row("2028 Round 1", 2500, 2500, position="PICK"),
    ]
    rows += [_row(f"B{i}", 2300 + 40 * i, 2000 + 10 * i) for i in range(8)]
    return rows


def _teams():
    return [
        {"name": "Mine", "ownerId": "me", "players": ["My Star"]},
        {"name": "Them", "ownerId": "them", "players": [f"B{i}" for i in range(8)]},
    ]


def _player_count(names, rows):
    pos = {r["canonicalName"]: r["position"] for r in rows}
    return sum(1 for n in names if pos.get(n) != "PICK")


def test_offer_with_picks_is_never_answered_with_a_lopsided_player_count():
    rows = _players()
    offer = ["My Star", "2027 Round 1", "2028 Round 1"]  # 3 assets, 1 player
    result = find_angle_packages(
        rows, offer, "me", _teams(), min_my_gain_pct=-100, max_market_gain_pct=100
    )
    assert result["thresholds"]["target_sizes"] == [2, 3, 4]
    assert result["candidates"], "fixture must produce candidates"
    for c in result["candidates"]:
        names = [p["name"] for p in c["players"]]
        assert abs(_player_count(names, rows) - 1) <= 1, names
    assert result["thresholds"]["topologyRejected"] > 0


def test_acquire_mode_obeys_the_same_rule():
    rows = _players()
    result = find_acquisition_packages(
        rows,
        ["B7"],
        "me",
        [
            {"name": "Mine", "ownerId": "me", "players": ["My Star", "B0", "B1", "B2"]},
            {"name": "Them", "ownerId": "them", "players": ["B7"]},
        ],
        min_my_gain_pct=-100,
        max_market_gain_pct=100,
    )
    for c in result["candidates"]:
        names = [p["name"] for p in c["players"]]
        assert abs(_player_count(names, rows) - 1) <= 1, names


# ── Finder ───────────────────────────────────────────────────────────


def _finder_assets(prefix: str, n: int):
    from src.trade.finder import Asset

    return [
        Asset(
            name=f"{prefix}{i}",
            position="WR",
            team="KC",
            model_value=9000 - 100 * i,
            market_value=9000 - 100 * i,
        )
        for i in range(n)
    ]


def test_finder_default_search_offers_every_owner_allowed_shape(monkeypatch):
    from src.trade import finder

    seen: set[tuple[int, int]] = set()
    monkeypatch.setattr(
        finder, "_score_trade", lambda give, receive: seen.add((len(give), len(receive)))
    )
    _results, report = finder._generate_packages(
        _finder_assets("m", 10), _finder_assets("o", 10), UNCONSTRAINED_OUTGOING
    )
    assert {(1, 1), (2, 1), (1, 2), (2, 2), (3, 2), (2, 3)} <= seen
    # Never beyond the C3-TOPO-01 bound.
    assert all(abs(a - b) <= 1 for a, b in seen)
    assert "multiPlayer" in report


def test_finder_equal_count_mode_is_unchanged(monkeypatch):
    from src.trade import finder

    seen: set[tuple[int, int]] = set()
    monkeypatch.setattr(
        finder, "_score_trade", lambda give, receive: seen.add((len(give), len(receive)))
    )
    finder._generate_packages(
        _finder_assets("m", 10),
        _finder_assets("o", 10),
        UNCONSTRAINED_OUTGOING,
        equal_count_only=True,
    )
    assert seen == {(1, 1), (2, 2)}
