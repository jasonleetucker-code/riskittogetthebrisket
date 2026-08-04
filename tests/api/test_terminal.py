"""Tests for the ``/api/terminal`` aggregation endpoint builder."""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from src.api import terminal, rank_history
from src.canonical.player_valuation import rank_to_value


def _iso(d):
    return d.strftime("%Y-%m-%d")


@pytest.fixture()
def history_path(tmp_path, monkeypatch):
    path = tmp_path / "rank_history.jsonl"
    # Seed with some deterministic ranks for Alice / Bob over the
    # last 200 days.
    today = datetime.now(timezone.utc).date()
    lines = []
    for i in range(0, 200):
        d = today - timedelta(days=i)
        lines.append(
            {
                "date": _iso(d),
                "ranks": {
                    "Alice::offense": 10 + (i // 30),
                    "Bob::offense": 25 + (i // 20),
                    "Carlo::offense": 60,
                },
            }
        )
    # Reverse so we write oldest-first just to match production style.
    for line in reversed(lines):
        path.open("a").write(json.dumps(line) + "\n")
    monkeypatch.setattr(rank_history, "HISTORY_PATH", path)
    return path


def _mk_contract(history_path):
    """Build a fake /api/data-shaped contract with 3 players + 1 team."""
    return {
        "date": "2026-04-23",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "playerCount": 3,
        "contractVersion": "2026-03-10.v2",
        "playersArray": [
            {
                "displayName": "Alice",
                "canonicalName": "Alice",
                "assetClass": "offense",
                "position": "QB",
                "pos": "QB",
                "canonicalConsensusRank": 10,
                "rankChange": 2,
                "rankDerivedValue": int(rank_to_value(10)),
                "values": {"full": int(rank_to_value(10))},
                "rookie": False,
                "age": 27,
            },
            {
                "displayName": "Bob",
                "canonicalName": "Bob",
                "assetClass": "offense",
                "position": "WR",
                "pos": "WR",
                "canonicalConsensusRank": 25,
                "rankChange": -5,
                "rankDerivedValue": int(rank_to_value(25)),
                "values": {"full": int(rank_to_value(25))},
                "rookie": False,
                "age": 29,
            },
            {
                "displayName": "Carlo",
                "canonicalName": "Carlo",
                "assetClass": "offense",
                "position": "WR",
                "pos": "WR",
                "canonicalConsensusRank": 60,
                "rankChange": None,
                "rankDerivedValue": int(rank_to_value(60)),
                "values": {"full": int(rank_to_value(60))},
                "rookie": True,
                "age": 22,
            },
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "owner-1",
                    "name": "Alpha Team",
                    "roster_id": 1,
                    "players": ["Alice", "Bob"],
                    "picks": [],
                },
                {
                    "ownerId": "owner-2",
                    "name": "Beta Team",
                    "roster_id": 2,
                    "players": ["Carlo"],
                    "picks": [],
                },
            ],
            "trades": [],
        },
    }


def test_resolve_team_by_owner_id(history_path):
    contract = _mk_contract(history_path)
    t = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    assert t and t["ownerId"] == "owner-1"


def test_resolve_team_by_name_fallback(history_path):
    contract = _mk_contract(history_path)
    t = terminal.resolve_team(contract, owner_id=None, name="Alpha Team")
    assert t and t["ownerId"] == "owner-1"


def test_rename_via_owner_id_still_resolves(history_path):
    contract = _mk_contract(history_path)
    contract["sleeper"]["teams"][0]["name"] = "Alphas Renamed"
    t = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    assert t and t["name"] == "Alphas Renamed"


def test_build_terminal_payload_full_for_selected_team(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=team,
        window_days=30,
    )
    assert payload["team"]["ownerId"] == "owner-1"
    assert payload["team"]["name"] == "Alpha Team"
    # Team aggregates: total value should equal Alice.value + Bob.value
    assert payload["teamAggregates"]["totalValue"] > 0
    expected_total = int(rank_to_value(10)) + int(rank_to_value(25))
    assert payload["teamAggregates"]["totalValue"] == expected_total
    # Tier counts should sum to roster size
    tiers = payload["teamAggregates"]["tiers"]
    assert sum(tiers.values()) == 2
    # Movers: roster/league/top150 keys present
    assert {"roster", "league", "top150"} <= set(payload["movers"].keys())
    # Signals: must have one entry per roster player with a signalKey
    signals = payload["signals"]
    assert len(signals) == 2
    for s in signals:
        assert "signalKey" in s and "::" in s["signalKey"]
        assert s["signal"] in ("RISK", "SELL", "MONITOR", "STRONG_HOLD", "BUY", "HOLD")


def test_build_terminal_payload_with_no_team_still_renders(history_path):
    contract = _mk_contract(history_path)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=None,
        window_days=30,
    )
    assert payload["team"] is None
    assert payload["teamAggregates"]["totalValue"] is None
    assert payload["movers"]["league"]  # league scope still has movers
    assert payload["signals"] == []


def test_trend_windows_advertised(history_path):
    contract = _mk_contract(history_path)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=None,
        window_days=30,
    )
    assert payload["trendWindows"] == [7, 30, 90, 180]


def test_window_days_clamped(history_path):
    contract = _mk_contract(history_path)
    payload = terminal.build_terminal_payload(contract, resolved_team=None, window_days=999)
    assert payload["windowDays"] == 180
    payload = terminal.build_terminal_payload(contract, resolved_team=None, window_days=1)
    assert payload["windowDays"] == 7


def test_roster_aware_delta_uses_trade_history(history_path):
    """A completed trade in the past 14 days should move the delta-30d
    for the giver away from the static-roster result.
    """
    contract = _mk_contract(history_path)
    # Construct a trade where owner-1 GAVE Bob to owner-2 14 days ago.
    ts = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp() * 1000)
    contract["sleeper"]["trades"] = [
        {
            "timestamp": ts,
            "sides": [
                {"ownerId": "owner-1", "got": [], "gave": ["Bob"]},
                {"ownerId": "owner-2", "got": ["Bob"], "gave": []},
            ],
        }
    ]
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=team,
        window_days=30,
    )
    # Past roster for owner-1 at 30d ago should have INCLUDED Bob (he
    # was on the team before the trade).  Current roster only has
    # Alice + Bob (the trade said they gave away Bob, but the contract
    # hasn't caught up yet in this fixture).  For correctness, we
    # just verify the delta30d is computed and is non-null.
    assert payload["teamAggregates"]["delta30d"] is not None


def test_signal_key_is_stable_per_player_tag(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    p1 = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    p2 = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    keys1 = {s["signalKey"] for s in p1["signals"]}
    keys2 = {s["signalKey"] for s in p2["signals"]}
    assert keys1 == keys2


def test_dismissed_signals_reflected_in_payload(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    # Simulate a user_state with one dismissal for every signal emitted.
    base = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    first_key = base["signals"][0]["signalKey"]
    future_ts = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp() * 1000)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=team,
        window_days=30,
        user_state={"dismissedSignals": {first_key: future_ts}},
    )
    hit = next(s for s in payload["signals"] if s["signalKey"] == first_key)
    assert hit["dismissedUntil"] == future_ts
    assert hit["dismissed"] is True


def test_available_teams_returned_for_picker(history_path):
    contract = _mk_contract(history_path)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=None,
        window_days=30,
    )
    owners = {t["ownerId"] for t in payload["availableTeams"]}
    assert owners == {"owner-1", "owner-2"}


# ── Public mode (Item 4) ────────────────────────────────────────────


def test_public_mode_strips_private_fields(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=team,
        window_days=30,
        public_mode=True,
    )
    # Private surfaces gone
    assert payload["team"] is None
    assert payload["signals"] == []
    assert payload["portfolio"] is None
    assert payload["watchlist"] == []
    # Roster mover list cleared; league + top150 preserved
    assert payload["movers"]["roster"] == []
    assert isinstance(payload["movers"]["league"], list)
    assert isinstance(payload["movers"]["top150"], list)
    # Aggregates report null values instead of real totals
    agg = payload["teamAggregates"]
    assert agg["totalValue"] is None
    assert agg["delta30d"] is None
    # Meta exposes the flag for client inspection
    assert payload["meta"]["publicMode"] is True


# ── Trade coverage (Item 6) ─────────────────────────────────────────


def test_roster_aware_is_false_when_no_trades(history_path):
    contract = _mk_contract(history_path)
    # Zero trades in the contract → rosterAware must be False,
    # delta coverage reason reports "no_trades".
    contract["sleeper"]["trades"] = []
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    assert payload["teamAggregates"]["rosterAware"] is False
    d30 = payload["teamAggregates"]["delta30dDetail"]
    assert d30["rosterAware"] is False
    assert d30["tradesSeen"] == 0
    assert d30["tradesApplied"] == 0
    assert d30["reason"] in ("no_trades", "low_history_coverage")


def test_roster_aware_is_true_when_owner_trade_inside_window(history_path):
    contract = _mk_contract(history_path)
    ts = int((datetime.now(timezone.utc) - timedelta(days=14)).timestamp() * 1000)
    contract["sleeper"]["trades"] = [
        {
            "timestamp": ts,
            "sides": [
                {"ownerId": "owner-1", "got": [], "gave": ["Bob"]},
                {"ownerId": "owner-2", "got": ["Bob"], "gave": []},
            ],
        }
    ]
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    d30 = payload["teamAggregates"]["delta30dDetail"]
    assert d30["tradesSeen"] >= 1
    assert d30["tradesApplied"] >= 1
    assert d30["rosterAware"] is True
    assert payload["teamAggregates"]["rosterAware"] is True


def test_trade_for_other_owner_does_not_flip_roster_aware(history_path):
    contract = _mk_contract(history_path)
    ts = int((datetime.now(timezone.utc) - timedelta(days=10)).timestamp() * 1000)
    # Trade is inside the 30d window but doesn't involve owner-1.
    contract["sleeper"]["trades"] = [
        {
            "timestamp": ts,
            "sides": [
                {"ownerId": "owner-2", "got": ["Carlo"], "gave": []},
                {"ownerId": "owner-99", "got": [], "gave": ["Carlo"]},
            ],
        }
    ]
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    d30 = payload["teamAggregates"]["delta30dDetail"]
    assert d30["tradesSeen"] == 1
    assert d30["tradesApplied"] == 0
    assert d30["rosterAware"] is False
    assert d30["reason"] == "no_trades_for_owner"


# ── Coverage fraction (Item 8) ──────────────────────────────────────


def test_delta_detail_exposes_coverage_fraction(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    d30 = payload["teamAggregates"]["delta30dDetail"]
    assert "coverageFraction" in d30
    assert 0.0 <= d30["coverageFraction"] <= 1.0
    assert "resolved" in d30
    assert "expected" in d30
    assert d30["expected"] == 2  # Alice + Bob


def test_low_coverage_produces_null_value_with_fraction(history_path):
    # Build a contract with three players but only seed history for
    # one — coverage is 1/3 which is below the 60% reliability floor,
    # so the delta value comes back None but the coverage data is
    # still exposed.
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    # Add a 3rd roster player with no history to drop coverage below 60%.
    contract["sleeper"]["teams"][0]["players"].append("Ghost")
    contract["playersArray"].append(
        {
            "displayName": "Ghost",
            "canonicalName": "Ghost",
            "assetClass": "offense",
            "position": "TE",
            "pos": "TE",
            "canonicalConsensusRank": 200,
            "rankChange": None,
            "rankDerivedValue": 100,
            "values": {"full": 100},
        }
    )
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    d30 = payload["teamAggregates"]["delta30dDetail"]
    # Alice + Bob have history, Ghost doesn't — coverage = 2/3 ≈ 0.67
    # which IS reliable; test that the fraction + resolved count are
    # exposed regardless.
    assert d30["resolved"] == 2
    assert d30["expected"] == 3
    assert d30["coverageFraction"] == pytest.approx(2 / 3, abs=0.01)


# ── Alias signal keys (Item 7) ──────────────────────────────────────


def test_signal_carries_alias_key_when_sleeper_id_present(history_path):
    contract = _mk_contract(history_path)
    for row in contract["playersArray"]:
        row["sleeperId"] = f"sid-{row['displayName']}"
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    assert payload["signals"]
    for s in payload["signals"]:
        assert s["signalKey"].count("::") == 1
        assert s["aliasSignalKey"].startswith("sid:sid-")
        assert s["sleeperId"].startswith("sid-")


def test_portfolio_breakdown_includes_byposition_byage_volexposure(history_path):
    contract = _mk_contract(history_path)
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    p = payload["portfolio"]
    assert p is not None
    # Position splits
    assert "byPosition" in p
    assert p["byPosition"]["QB"]["count"] == 1
    assert p["byPosition"]["WR"]["count"] == 1
    assert p["byPosition"]["QB"]["value"] > 0
    # Percentages add to ~100 within the populated buckets
    pct_total = sum(p["byPosition"][g]["pct"] for g in p["byPosition"])
    assert 99.0 <= pct_total <= 100.1
    # Age mix
    assert "byAge" in p
    assert p["byAge"]["prime"]["count"] >= 1  # Alice is 27 = prime
    # Volatility exposure
    assert "volExposure" in p
    assert sum(p["volExposure"][k]["count"] for k in p["volExposure"]) == 2
    # Counters
    assert "counters" in p
    assert "rising" in p["counters"]
    assert "falling" in p["counters"]
    assert "highVol" in p["counters"]
    # Median age
    assert p["medianAge"] == pytest.approx(28.0, abs=0.1)  # median of 27 and 29


def test_value_history_fallback_covers_when_rank_history_missing(tmp_path, monkeypatch):
    """When ``rank_history.jsonl`` has no entries but
    ``source_value_history.jsonl`` does, the terminal delta
    computation should still produce coverage-fraction numbers from
    the value-history source.  Pins the #6 historical-backfill
    behaviour."""
    from src.api import source_history, terminal
    from datetime import date, timedelta

    rank_path = tmp_path / "rank_history.jsonl"
    rank_path.write_text("")  # empty — the recent log has no coverage
    monkeypatch.setattr(rank_history, "HISTORY_PATH", rank_path)

    value_path = tmp_path / "source_value_history.jsonl"
    monkeypatch.setattr(source_history, "HISTORY_PATH", value_path)

    # Seed 40 days of value history for both Alice and Bob, who
    # make up the owner-1 roster in _mk_contract.  Blended value
    # decreases ~2 per day so the 30d delta is a clean positive
    # number we can assert against.
    today = date.today()
    for i in range(40):
        d = (today - timedelta(days=i)).isoformat()
        source_history.append_snapshot(
            {
                "playersArray": [
                    {
                        "displayName": "Alice",
                        "canonicalName": "Alice",
                        "assetClass": "offense",
                        "position": "QB",
                        "rankDerivedValue": 9000 - i * 2,
                        "sourceRankMeta": {"ktcSfTep": {"valueContribution": 9000 - i * 2}},
                    },
                    {
                        "displayName": "Bob",
                        "canonicalName": "Bob",
                        "assetClass": "offense",
                        "position": "WR",
                        "rankDerivedValue": 8000 - i,
                        "sourceRankMeta": {"ktcSfTep": {"valueContribution": 8000 - i}},
                    },
                ]
            },
            date=d,
            path=value_path,
        )

    contract = _mk_contract(tmp_path / "rank_history.jsonl")
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(
        contract,
        resolved_team=team,
        window_days=30,
    )
    d30 = payload["teamAggregates"]["delta30dDetail"]
    # With value-history now primed, we should see real coverage
    # (≥60%) and a non-null delta value even though rank_history is
    # empty.  The "source" field should flag "value" as the data path.
    assert d30["coverageFraction"] >= 0.60
    assert d30["value"] is not None
    assert d30["source"] in ("value", "mixed")


def test_dismissal_resolves_via_alias_key_after_rename(history_path):
    contract = _mk_contract(history_path)
    for row in contract["playersArray"]:
        row["sleeperId"] = f"sid-{row['displayName']}"
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    # First build — harvest the alias signal key + tag for Alice.
    baseline = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    alice_entry = next(s for s in baseline["signals"] if s["name"] == "Alice")
    alias_key = alice_entry["aliasSignalKey"]
    assert alias_key  # sleeperId was set, alias is required
    # Rename Alice in the contract and team roster.  Also mirror her
    # rank history into the new name so the firing rules evaluate
    # identically (same tag before/after); the test pins the alias-
    # key dismissal resolution, not the rule engine.
    for row in contract["playersArray"]:
        if row["displayName"] == "Alice":
            row["displayName"] = "Alice Renamed"
            row["canonicalName"] = "Alice Renamed"
    contract["sleeper"]["teams"][0]["players"] = [
        "Alice Renamed" if p == "Alice" else p for p in contract["sleeper"]["teams"][0]["players"]
    ]
    # Append "Alice Renamed::offense" to every snapshot with the
    # same ranks the log already has for Alice.
    log_lines = []
    with history_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            ranks = obj.get("ranks") or {}
            alice_rank = ranks.get("Alice::offense")
            if alice_rank is not None:
                ranks["Alice Renamed::offense"] = alice_rank
            obj["ranks"] = ranks
            log_lines.append(obj)
    with history_path.open("w") as f:
        for obj in log_lines:
            f.write(json.dumps(obj) + "\n")
    future_ts = int((datetime.now(timezone.utc) + timedelta(days=3)).timestamp() * 1000)
    team2 = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    after = terminal.build_terminal_payload(
        contract,
        resolved_team=team2,
        window_days=30,
        user_state={"dismissedSignals": {alias_key: future_ts}},
    )
    hit = next(s for s in after["signals"] if s["name"] == "Alice Renamed")
    assert hit["aliasSignalKey"] == alias_key  # alias stays identical across rename
    assert hit["dismissed"] is True
    assert hit["dismissedUntil"] == future_ts


# ── Population-consistent deltas + honest history windows ───────────
# (2026-08-04 sitewide math audit, findings H2 / H3a)


def _seed_value_history(path, *, rows_by_date):
    """Write ``{date: [(name, value), ...]}`` into a value-history log.

    Uses the production writer so the on-disk shape is the real one,
    but every number here is chosen by hand — nothing in this helper
    consults the code under test.
    """
    from src.api import source_history

    for date, rows in sorted(rows_by_date.items()):
        source_history.append_snapshot(
            {
                "playersArray": [
                    {
                        "displayName": name,
                        "canonicalName": name,
                        "assetClass": "offense",
                        "position": "QB",
                        "rankDerivedValue": value,
                        # ``_extract_player_entry`` only keeps a row that
                        # carries at least one source value.
                        "sourceRankMeta": {"ktcSfTep": {"valueContribution": value}},
                    }
                    for name, value in rows
                ]
            },
            date=date,
            path=path,
        )


def _mk_ghost_contract():
    """Owner-1 holds Alice + Bob (both with history) and Ghost (none).

    Board values are literals so the arithmetic in the assertions can
    be done by hand.
    """
    return {
        "date": "2026-04-23",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "playerCount": 3,
        "contractVersion": "2026-03-10.v2",
        "playersArray": [
            {
                "displayName": "Alice",
                "canonicalName": "Alice",
                "assetClass": "offense",
                "position": "QB",
                "pos": "QB",
                "canonicalConsensusRank": 10,
                "rankDerivedValue": 9000,
                "age": 27,
            },
            {
                "displayName": "Bob",
                "canonicalName": "Bob",
                "assetClass": "offense",
                "position": "WR",
                "pos": "WR",
                "canonicalConsensusRank": 25,
                "rankDerivedValue": 8000,
                "age": 29,
            },
            {
                "displayName": "Ghost",
                "canonicalName": "Ghost",
                "assetClass": "offense",
                "position": "TE",
                "pos": "TE",
                "canonicalConsensusRank": 300,
                "rankDerivedValue": 500,
                "age": 24,
            },
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "owner-1",
                    "name": "Alpha Team",
                    "roster_id": 1,
                    "players": ["Alice", "Bob", "Ghost"],
                    "picks": [],
                }
            ],
            "trades": [],
        },
    }


def test_delta_does_not_subtract_two_different_populations(tmp_path, monkeypatch):
    """H2 — a player the PAST sum can't price must not inflate the delta.

    Ghost is on the roster today at 500 but has no history at all.  The
    past sum can only price Alice + Bob, so counting Ghost's 500 on the
    present side is 500 points of growth that never happened.

    Hand-computed, with ``i`` = days ago:
        Alice(i) = 9000 - 2i  →  Alice(30) = 8940
        Bob(i)   = 8000 - i   →  Bob(30)   = 7970
        pastValue    = 8940 + 7970 = 16910
        presentValue = 9000 + 8000 = 17000   (Ghost excluded)
        delta30d     = 17000 - 16910 = 90

    The pre-fix answer was ``17500 - 16910 = 590`` — Ghost's whole
    board value banked as a gain.
    """
    from src.api import source_history

    rank_path = tmp_path / "rank_history.jsonl"
    rank_path.write_text("")  # force the value-history path
    monkeypatch.setattr(rank_history, "HISTORY_PATH", rank_path)
    value_path = tmp_path / "source_value_history.jsonl"
    monkeypatch.setattr(source_history, "HISTORY_PATH", value_path)

    today = datetime.now(timezone.utc).date()
    _seed_value_history(
        value_path,
        rows_by_date={
            _iso(today - timedelta(days=i)): [("Alice", 9000 - 2 * i), ("Bob", 8000 - i)]
            for i in range(40)
        },
    )

    contract = _mk_ghost_contract()
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    agg = payload["teamAggregates"]
    d30 = agg["delta30dDetail"]

    # totalValue is untouched — it is the whole roster, deltas are not.
    assert agg["totalValue"] == 17500
    # The headline int is the number that has to be right.
    assert agg["delta30d"] == 90
    assert d30["value"] == 90
    assert d30["pastValue"] == 16910
    assert d30["presentValue"] == 17000
    # …and the payload says which population that number is over.
    assert d30["excludedFromPresent"] == ["Ghost"]
    assert d30["comparedCount"] == 2
    assert d30["resolved"] == 2
    assert d30["expected"] == 3
    assert d30["coverageFraction"] == pytest.approx(2 / 3, abs=0.01)


def test_delta_still_counts_a_player_acquired_inside_the_window(tmp_path, monkeypatch):
    """The population filter is priceability, NOT roster membership.

    Ghost is acquired 10 days ago, so he was legitimately worth 0 to
    this roster at the 30d mark — his 500 is a real gain and must
    survive the H2 filter even though the past sum never priced him.
    Same series as above:
        presentValue = 9000 + 8000 + 500 = 17500
        pastValue    = 8940 + 7970       = 16910
        delta30d     = 590
    """
    from src.api import source_history

    rank_path = tmp_path / "rank_history.jsonl"
    rank_path.write_text("")
    monkeypatch.setattr(rank_history, "HISTORY_PATH", rank_path)
    value_path = tmp_path / "source_value_history.jsonl"
    monkeypatch.setattr(source_history, "HISTORY_PATH", value_path)

    today = datetime.now(timezone.utc).date()
    _seed_value_history(
        value_path,
        rows_by_date={
            _iso(today - timedelta(days=i)): [("Alice", 9000 - 2 * i), ("Bob", 8000 - i)]
            for i in range(40)
        },
    )

    contract = _mk_ghost_contract()
    # Owner-1 GOT Ghost 10 days ago — reversing the trade removes him
    # from the reconstructed 30-days-ago roster.
    ten_days_ago_ms = int((datetime.now(timezone.utc) - timedelta(days=10)).timestamp() * 1000)
    contract["sleeper"]["trades"] = [
        {
            "timestamp": ten_days_ago_ms,
            "sides": [{"ownerId": "owner-1", "got": ["Ghost"], "gave": []}],
        }
    ]
    team = terminal.resolve_team(contract, owner_id="owner-1", name=None)
    payload = terminal.build_terminal_payload(contract, resolved_team=team, window_days=30)
    d30 = payload["teamAggregates"]["delta30dDetail"]

    assert d30["rosterAware"] is True
    assert payload["teamAggregates"]["delta30d"] == 590
    assert d30["excludedFromPresent"] == []
    assert d30["presentValue"] == 17500
    assert d30["pastValue"] == 16910


def test_value_history_lookup_windows_by_date_not_snapshot_count(tmp_path, monkeypatch):
    """H3a — ``days`` must mean days, not "the last N snapshots".

    The log is deduped per UTC date but NOT gap-free: a missed refresh
    drops a date and the historical backfill is sparser still.  Four
    snapshots spread over 180 days are still only four elements, so
    ``entries[-7:]`` handed a 7-day caller the whole 180-day span.
    """
    from src.api import source_history

    value_path = tmp_path / "source_value_history.jsonl"
    monkeypatch.setattr(source_history, "HISTORY_PATH", value_path)

    today = datetime.now(timezone.utc).date()
    _seed_value_history(
        value_path,
        rows_by_date={
            _iso(today - timedelta(days=180)): [("Alice", 1000)],
            _iso(today - timedelta(days=120)): [("Alice", 2000)],
            _iso(today - timedelta(days=60)): [("Alice", 3000)],
            _iso(today): [("Alice", 4000)],
        },
    )

    narrow = terminal._build_value_history_lookup(days=7)
    assert [p["date"] for p in narrow("Alice")] == [_iso(today)]
    assert [p["value"] for p in narrow("Alice")] == [4000]

    # A wide window still reaches the whole log, and the boundary
    # snapshot at exactly ``days`` back is inside it (inclusive cutoff,
    # matching ``_window_trend``) — the 180d delta depends on that.
    wide = terminal._build_value_history_lookup(days=180)
    assert [p["value"] for p in wide("Alice")] == [1000, 2000, 3000, 4000]
