"""The routed trade ledger (N-team spec §2.2-§2.4): validation order, ownership
verification, unverifiable evidence, echo bounds, flows and the snapshot memo.

The table of cases is ``tests/fixtures/multi_team/ledger_cases.json`` (Lane A
is its producer); every case runs against the LABELLED synthetic league of
``tests/trade/multi_team_support.py``.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.trade import trade_ledger as tl
from tests.trade import multi_team_support as mts

CASES = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures/multi_team/ledger_cases.json").read_text(
        encoding="utf-8"
    )
)["cases"]


def _mutated(name: str | None) -> dict:
    if name == "stale":
        return mts.synthetic_league(roster_source="last_good")
    contract = mts.synthetic_league()
    if name == "unknown":
        del contract["sleeper"]["rosterSource"]
    elif name == "multi_holder":
        contract["sleeper"]["teams"][1]["playerIds"].append("101")
    elif name == "pick_unpublished":
        team3 = contract["sleeper"]["teams"][2]
        team3["pickDetails"] = None
        team3["picks"] = None
        team3["pickOwnershipState"] = "unavailable"
        team3["pickOwnershipReason"] = "traded_picks_fetch_failed"
    return contract


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_ledger_case(case):
    snap = mts.synthetic_snapshot(_mutated(case.get("mutate")))
    policy = replace(tl.LedgerPolicy(), **(case.get("policy") or {}))
    legs = [{"id": a, "from": f, "to": t} for a, f, t in case["legs"]]
    expect = case["expect"]
    if expect.get("ok"):
        ledger = tl.validate_ledger(snap, teams=case["teams"], legs=legs, policy=policy)
        assert list(ledger.unverifiable_asset_ids) == expect["unverifiable"]
        assert list(ledger.teams) == sorted(set(case["teams"]))
        assert [leg.asset_id for leg in ledger.legs] == sorted(a for a, _f, _t in case["legs"])
        return
    with pytest.raises(tl.LedgerError) as exc:
        tl.validate_ledger(snap, teams=case["teams"], legs=legs, policy=policy)
    err = exc.value
    assert (err.status, err.error, err.reason) == (
        expect["status"],
        expect["error"],
        expect["reason"],
    )
    assert list(err.asset_ids) == expect.get("assetIds", [])
    assert list(err.roster_ids) == expect.get("rosterIds", [])


def test_every_spec_reason_has_a_case():
    reasons = {c["expect"].get("reason") for c in CASES}
    for reason in (
        "too_few_teams",
        "duplicate_team",
        "too_many_teams",
        "team_not_in_league",
        "empty_trade",
        "too_many_assets",
        "unknown_asset",
        "duplicate_asset",
        "invalid_origin",
        "invalid_destination",
        "destination_is_origin",
        "idle_team",
        "one_sided_trade",
        "asset_not_owned",
    ):
        assert reason in reasons, reason


def test_verified_owner_cannot_be_overridden_by_request_fields():
    """No request field asserts ownership: extra keys on a leg are ignored and
    the snapshot owner decides (I8)."""
    snap = mts.synthetic_snapshot()
    legs = [
        {"id": "p:201", "from": 1, "to": 2, "owner": 1, "ownerRosterId": 1},
        {"id": "p:101", "from": 1, "to": 2},
    ]
    with pytest.raises(tl.LedgerError) as exc:
        tl.validate_ledger(snap, teams=[1, 2], legs=legs, policy=tl.LedgerPolicy())
    assert exc.value.status == 409
    # The refusal never names the actual owner (team 2).
    assert exc.value.roster_ids == ()
    assert exc.value.to_dict() == {
        "error": "stale_assets",
        "reason": "asset_not_owned",
        "assetIds": ["p:201"],
    }


def test_echo_is_bounded_to_request_ids_of_the_safe_shape():
    snap = mts.synthetic_snapshot()
    junk = ["<script>", "x" * 65, "p:777", "pick:other:2027:r1:o1"]
    legs = [{"id": a, "from": 1, "to": 2} for a in junk]
    with pytest.raises(tl.LedgerError) as exc:
        tl.validate_ledger(snap, teams=[1, 2], legs=legs, policy=tl.LedgerPolicy())
    assert exc.value.asset_ids == ("p:777", "pick:other:2027:r1:o1")
    capped = tl.LedgerError(400, "invalid_trade", "unknown_asset", asset_ids=junk, cap=1)
    assert capped.asset_ids == ("p:777",)


def test_non_integer_ids_never_validate():
    snap = mts.synthetic_snapshot()
    with pytest.raises(tl.LedgerError) as exc:
        tl.validate_ledger(
            snap,
            teams=[1, "2"],
            legs=[{"id": "p:101", "from": 1, "to": 2}],
            policy=tl.LedgerPolicy(),
        )
    assert exc.value.reason == "team_not_in_league"
    with pytest.raises(tl.LedgerError) as exc:
        tl.validate_ledger(
            snap,
            teams=[1, 2],
            legs=[{"id": "p:101", "from": True, "to": 2}, {"id": "p:201", "from": 2, "to": 1}],
            policy=tl.LedgerPolicy(),
        )
    assert exc.value.reason == "invalid_origin"


def test_parse_asset_id_accepts_only_the_canonical_forms():
    parse = tl.parse_asset_id
    assert parse("p:4046", league_key="synth") == ("player", "4046")
    assert parse("p:", league_key="synth") is None
    assert parse("p:12345678901234567", league_key="synth") is None
    assert parse("p:ab-c", league_key="synth") is None
    kind, ident = parse("pick:synth:2027:r1:o3", league_key="synth")
    assert kind == "pick" and ident.origin_roster_id == 3
    assert parse("pick:other:2027:r1:o3", league_key="synth") is None
    assert parse("2027 Round 1", league_key="synth") is None
    assert parse(4046, league_key="synth") is None


def test_team_flows_split_gives_and_receives_by_direction():
    snap = mts.synthetic_snapshot()
    ledger = tl.validate_ledger(
        snap,
        teams=[1, 2, 3],
        legs=[
            {"id": "p:101", "from": 1, "to": 2},
            {"id": "pick:synth:2027:r1:o1", "from": 1, "to": 3},
            {"id": "p:201", "from": 2, "to": 1},
            {"id": "p:301", "from": 3, "to": 1},
        ],
        policy=tl.LedgerPolicy(),
    )
    a = tl.team_flows(ledger, 1)
    assert a.player_ids_out == ("101",) and a.pick_ids_out == ("pick:synth:2027:r1:o1",)
    assert a.player_ids_in == ("201", "301") and a.pick_ids_in == ()
    assert [leg.to_roster_id for leg in a.gives] == [2, 3]
    b = tl.team_flows(ledger, 2)
    assert b.player_ids_in == ("101",) and b.player_ids_out == ("201",)
    # Net ownership per team reconciles with the transfer ledger.
    for rid in ledger.teams:
        f = tl.team_flows(ledger, rid)
        assert {g.asset_id for g in f.gives} == {
            leg.asset_id for leg in ledger.legs if leg.from_roster_id == rid
        }


def test_snapshot_reads_freshness_from_the_canonical_owner():
    fresh = mts.synthetic_snapshot()
    assert fresh.rosters_state == "current" and fresh.rosters_as_of == "2026-10-20"
    old = mts.synthetic_snapshot(fetched_at=mts.PINNED_NOW - timedelta(hours=7))
    assert old.rosters_state == "stale"
    assert mts.synthetic_snapshot(roster_source="last_good").rosters_state == "stale"


def test_snapshot_refuses_a_contract_without_rosters():
    with pytest.raises(LookupError):
        tl.build_trade_snapshot({"sleeper": {"teams": []}}, league_key="synth")


def test_snapshot_memo_reuses_one_object_and_respects_freshness():
    tl.clear_snapshot_memo()
    contract = mts.synthetic_league()
    a = tl.snapshot_for(
        contract, league_key="synth", roster_settings=mts.SYNTH_SETTINGS, now=mts.PINNED_NOW
    )
    b = tl.snapshot_for(
        contract, league_key="synth", roster_settings=mts.SYNTH_SETTINGS, now=mts.PINNED_NOW
    )
    assert a is b
    later = tl.snapshot_for(
        contract,
        league_key="synth",
        roster_settings=mts.SYNTH_SETTINGS,
        now=mts.PINNED_NOW + timedelta(hours=8),
    )
    assert later is not a and later.rosters_state == "stale"
    tl.clear_snapshot_memo()


def test_private_policy_reads_config_and_fails_closed(monkeypatch, tmp_path):
    policy = tl.private_policy()
    assert (policy.max_teams, policy.max_legs, policy.participation) == (4, 128, "any_leg")
    monkeypatch.setattr(tl, "_CONFIG_PATH", tmp_path / "missing.json")
    assert tl.private_policy().max_teams == 2
    bad = tmp_path / "bad.json"
    bad.write_text('{"maxTeams": 99, "maxLegs": 1, "participation": "any_leg"}', encoding="utf-8")
    monkeypatch.setattr(tl, "_CONFIG_PATH", bad)
    assert tl.private_policy().max_teams == 2
