"""The N-team engine (``analyze_service.analyze_trade_n``; spec
``docs/trade/NTEAM_TRADE_ENGINE_SPEC.md`` §2.5-§2.11).

Two boards:

* the LABELLED synthetic 4-team league (``multi_team_support``) for exact
  worked numbers (I14), the adversarial matrix and the mode rules;
* the newest COMPLETE archived scrape (real dynasty_main rosters, values and
  picks), for the seeded property sweep (I1-I3, I5-I7, I10, I13, I15, I18,
  I20) and real recorded own-league trades replayed in reverse.

Every property here is an INVARIANT — no count or value of the live board is
asserted (CI two-lane rule).
"""

from __future__ import annotations

import copy
import itertools
import json
import random
from datetime import timedelta
from unittest import mock

import pytest

from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from tests.trade import multi_team_support as mts

POLICY = tl.LedgerPolicy()


@pytest.fixture(autouse=True)
def _pinned_scarcity(monkeypatch):
    """R1-2: no live / TTL-cached team-strength read may decide a comparison
    (``multi_team_support.pin_league_scarcity``).  The once-per-request tests
    below re-patch the same seam with their own source."""
    return mts.pin_league_scarcity(monkeypatch)


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, default=str)


def _ledger(snap, teams, legs, policy=POLICY):
    return tl.validate_ledger(
        snap, teams=teams, legs=[{"id": a, "from": f, "to": t} for a, f, t in legs], policy=policy
    )


def _no_posture(*_a, **_k):
    return {"available": False, "unavailableReason": "test_pinned"}


def _run(snap, ledger, mode="market_fairness", **kw):
    if mode == "team_context":
        kw.setdefault("posture_resolver", _no_posture)
    return svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False, **kw)


def _strip_team(team: dict) -> dict:
    """A team result minus the per-request receipt fields (I3 exclusions)."""
    t = copy.deepcopy(team)
    t.get("analysis", {}).pop("decisionRunId", None)
    return t


I14_LEGS = [("p:101", 1, 2), ("p:102", 1, 3), ("p:201", 2, 1), ("p:301", 3, 1)]


# ══ Worked numbers (I14) and directional correctness ═══════════════════════


@pytest.mark.parametrize("mode", ["market_fairness", "asset_only", "team_context"])
def test_i14_one_to_many_directional_numbers(mode):
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode)
    f = {rid: t["fairness"] for rid, t in out["teams"].items()}
    # fairness_bands_v2 (OD-F2): relative to the larger PACKAGE UTILITY
    # (U_R = 7000 + 0.78 x 2500 = 8950 for team 1), not the larger adjusted
    # side (9610, v1's 6.35 %); the adjusted side stays as a display number.
    assert (
        f[1]["gap"],
        f[1]["largerAdjustedSide"],
        f[1]["largerPackageUtility"],
        f[1]["relativePct"],
        f[1]["level"],
    ) == (610, 9610.0, 8950.0, 6.82, "slight")
    assert (f[2]["largerPackageUtility"], f[3]["largerPackageUtility"]) == (7000.0, 3000.0)
    assert (f[2]["gap"], f[2]["largerAdjustedSide"], f[2]["relativePct"], f[2]["level"]) == (
        -1000,
        7000.0,
        14.29,
        "unfair",
    )
    assert (f[3]["gap"], f[3]["largerAdjustedSide"], f[3]["relativePct"], f[3]["level"]) == (
        500,
        3000.0,
        16.67,
        "unfair",
    )
    assert {t["state"] for t in f.values()} == {"NOT_FAIR"}
    assert out["summary"]["fairnessOverall"]["state"] == "NOT_FAIR"
    # Raw conservation (I15) — the adjusted gaps do NOT sum to zero (610 - 1000 + 500).
    cons = out["summary"]["conservation"]
    assert cons["pricedRawSent"] == cons["pricedRawReceived"] == 18500 and cons["balanced"]


def test_fairness_is_gross_and_identical_in_every_mode():
    """I11's engine half: per-team fairness reads the gross market band, so
    the public mode and both private modes agree exactly."""
    snap = mts.synthetic_snapshot()
    ledger = _ledger(snap, [1, 2, 3], I14_LEGS)
    by_mode = {m: _run(snap, ledger, m) for m in svc.MODES}
    for rid in ledger.teams:
        states = {_canon(by_mode[m]["teams"][rid]["fairness"]) for m in svc.MODES}
        assert len(states) == 1, rid
    overall = {_canon(by_mode[m]["summary"]["fairnessOverall"]) for m in svc.MODES}
    assert len(overall) == 1


def test_i15_one_for_one_cycle_gaps_sum_to_zero():
    snap = mts.synthetic_snapshot()
    legs = [("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 4), ("p:401", 4, 1)]
    out = _run(snap, _ledger(snap, [1, 2, 3, 4], legs))
    assert sum(t["fairness"]["gap"] for t in out["teams"].values()) == 0


def test_i19_small_private_gift_is_fair_by_the_band_floor():
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 2], [("p:204", 2, 1)]))
    assert {t["fairness"]["state"] for t in out["teams"].values()} == {"FAIR"}


# ══ Simultaneity, locality, order, determinism ═════════════════════════════


def test_i10_locality_a_leg_between_other_teams_leaves_a_team_unchanged():
    snap = mts.synthetic_snapshot()
    base = [("p:101", 1, 2), ("p:201", 2, 1), ("p:302", 3, 4), ("p:401", 4, 3)]
    more = [*base, ("p:303", 3, 4)]
    for mode in svc.MODES:
        a = _run(snap, _ledger(snap, [1, 2, 3, 4], base), mode)
        b = _run(snap, _ledger(snap, [1, 2, 3, 4], more), mode)
        for rid in (1, 2):
            assert _canon(_strip_team(a["teams"][rid])) == _canon(_strip_team(b["teams"][rid]))
        assert _canon(a["teams"][3]) != _canon(b["teams"][3])


def test_i1_i2_i3_order_and_determinism_exhaustive_on_four_teams():
    snap = mts.synthetic_snapshot()
    legs = [
        ("p:101", 1, 2),
        ("pick:synth:2027:r1:o1", 1, 3),
        ("p:201", 2, 3),
        ("p:301", 3, 4),
        ("p:401", 4, 1),
        ("p:305", 3, 1),
    ]
    reference = _canon(_run(snap, _ledger(snap, [1, 2, 3, 4], legs), "asset_only"))
    for teams in itertools.permutations([1, 2, 3, 4]):
        out = _run(snap, _ledger(snap, list(teams), legs), "asset_only")
        assert _canon(out) == reference
    rng = random.Random(14)
    for _ in range(12):
        shuffled = legs[:]
        rng.shuffle(shuffled)
        assert _canon(_run(snap, _ledger(snap, [4, 2, 3, 1], shuffled), "asset_only")) == reference


def test_i9_renaming_teams_and_labels_changes_no_verdict():
    contract = mts.synthetic_league()
    snap = mts.synthetic_snapshot(contract)
    ledger = _ledger(snap, [1, 2, 3], I14_LEGS)
    base = _run(snap, ledger, "asset_only")
    renamed = copy.deepcopy(contract)
    for t in renamed["sleeper"]["teams"]:
        t["name"] = t["name"][::-1] + " FC"
    for r in renamed["playersArray"]:
        if r.get("playerId"):
            r["displayName"] = r["canonicalName"] = f"Renamed {r['playerId']}"
    for t in renamed["sleeper"]["teams"]:
        t["players"] = [f"Renamed {pid}" for pid in t["playerIds"]]
    snap2 = mts.synthetic_snapshot(renamed)
    other = _run(snap2, _ledger(snap2, [1, 2, 3], I14_LEGS), "asset_only")
    for rid in (1, 2, 3):
        a, b = base["teams"][rid], other["teams"][rid]
        assert (a["category"], a["analysis"]["decision"]["headline"]) == (
            b["category"],
            b["analysis"]["decision"]["headline"],
        )
        assert _canon(a["fairness"]) == _canon(b["fairness"])
        assert [g["value"] for g in a["gives"]] == [g["value"] for g in b["gives"]]


# ══ Conservation, phantoms, one value per asset ════════════════════════════


def _assert_ledger_reconciles(out, ledger):
    legs = {leg.asset_id: leg for leg in ledger.legs}
    seen_ids = set()
    for rid, team in out["teams"].items():
        gives = {g["assetId"] for g in team["gives"]}
        recv = {r["assetId"] for r in team["receives"]}
        assert gives == {a for a, leg in legs.items() if leg.from_roster_id == rid}
        assert recv == {a for a, leg in legs.items() if leg.to_roster_id == rid}
        seen_ids |= gives | recv
        for side in ("sending", "receiving"):
            for asset in team["simulation"].get(side) or []:
                aid = asset.get("assetId") or (
                    f"p:{asset['playerId']}" if asset.get("playerId") else None
                )
                if aid is not None:
                    assert aid in legs, f"phantom asset {aid}"  # I7
    assert seen_ids == set(legs)
    assert out["summary"]["conservation"]["balanced"] is True


def test_conservation_violation_is_raised_never_published():
    snap = mts.synthetic_snapshot()
    ledger = _ledger(snap, [1, 2], [("p:101", 1, 2), ("p:201", 2, 1)])
    good = _run(snap, ledger)
    broken = copy.deepcopy(good["teams"])
    broken[2]["receives"][0]["value"] += 1
    with pytest.raises(svc.ConservationViolation):
        svc._assert_conserved(ledger, broken)
    missing = copy.deepcopy(good["teams"])
    missing[1]["gives"] = []
    with pytest.raises(svc.ConservationViolation):
        svc._assert_conserved(ledger, missing)
    doubled = copy.deepcopy(good["teams"])
    doubled[1]["gives"] = doubled[1]["gives"] * 2
    with pytest.raises(svc.ConservationViolation):
        svc._assert_conserved(ledger, doubled)


def test_unknown_slot_future_pick_has_one_generic_value_and_is_not_a_gap():
    """I13 for picks: the slot is unknown, so identity resolves the GENERIC
    grade — the same value for sender and receiver, never an evidence gap."""
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 4], [("pick:synth:2027:r1:o1", 1, 4), ("p:402", 4, 1)]))
    sent = out["teams"][1]["gives"][0]
    got = out["teams"][4]["receives"][0]
    assert sent["value"] == got["value"] == 3600 and sent["valueState"] == "priced"
    for team in out["teams"].values():
        assert team["fairness"]["state"] != "UNABLE"


def test_unpriced_and_off_board_players_make_the_touching_teams_unable():
    contract = mts.synthetic_league()
    contract["sleeper"]["teams"][0]["playerIds"].append("106")  # rostered, no board row
    contract["sleeper"]["teams"][0]["players"].append("A Ghost")
    snap = mts.synthetic_snapshot(contract)
    legs = [("p:105", 1, 2), ("p:106", 1, 3), ("p:201", 2, 1), ("p:301", 3, 1), ("p:401", 4, 2)]
    legs.append(("p:202", 2, 4))
    for mode in svc.MODES:
        out = _run(snap, _ledger(snap, [1, 2, 3, 4], legs), mode)
        a = out["teams"][1]
        states = {g["assetId"]: (g["value"], g["valueState"]) for g in a["gives"]}
        assert states["p:105"] == (None, "unpriced")
        assert states["p:106"] == (None, "off_board")
        for rid in (1, 2, 3):
            f = out["teams"][rid]["fairness"]
            assert (f["state"], f["reasonCode"]) == ("UNABLE", "asset_not_evaluable")
            assert out["teams"][rid]["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
        # Team 4 touches neither asset (locality): it is judged on its own legs.
        assert out["teams"][4]["fairness"]["state"] in ("FAIR", "NOT_FAIR")
        assert out["summary"]["fairnessOverall"]["state"] in ("NOT_FAIR", "UNABLE")


# ══ Ownership gate (R1 / I17) ══════════════════════════════════════════════


@pytest.mark.parametrize("mode", ["market_fairness", "asset_only", "team_context"])
def test_i17_stale_rosters_make_every_team_unable(mode):
    snap = mts.synthetic_snapshot(roster_source="last_good")
    out = _run(snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode)
    for team in out["teams"].values():
        assert team["fairness"]["state"] == "UNABLE"
        assert team["fairness"]["reasonCode"] == "ownership_unverifiable"
        assert team["analysis"]["decision"]["headline"] in ("NOT_ENOUGH_EVIDENCE", "NO")
        assert team["analysis"]["decision"]["headline"] != "YES"
        assert team["simulation"]["ownershipEvidence"]["unverifiableAssetIds"]
    assert out["summary"]["fairnessOverall"]["state"] == "UNABLE"


def test_i17_multi_holder_player_touches_only_its_teams():
    contract = mts.synthetic_league()
    contract["sleeper"]["teams"][1]["playerIds"].append("101")  # 101 on teams 1 and 2
    snap = mts.synthetic_snapshot(contract)
    legs = [("p:101", 1, 2), ("p:201", 2, 1), ("p:302", 3, 4), ("p:401", 4, 3)]
    out = _run(snap, _ledger(snap, [1, 2, 3, 4], legs), "asset_only")
    for rid in (1, 2):
        t = out["teams"][rid]
        assert t["unverifiableAssetIds"] == ["p:101"]
        assert t["fairness"]["reasonCode"] == "ownership_unverifiable"
        gaps = [g["code"] for g in t["analysis"]["decision"]["missingEvidence"]]
        assert "ownership_unverifiable" in gaps
    for rid in (3, 4):
        assert out["teams"][rid]["unverifiableAssetIds"] == []
        assert "ownershipEvidence" not in out["teams"][rid]["simulation"]


def test_unknown_pick_ownership_is_unverifiable_not_guessed():
    contract = mts.synthetic_league()
    t3 = contract["sleeper"]["teams"][2]
    t3.update(
        pickDetails=None,
        picks=None,
        pickOwnershipState="unavailable",
        pickOwnershipReason="traded_picks_fetch_failed",
    )
    snap = mts.synthetic_snapshot(contract)
    out = _run(snap, _ledger(snap, [1, 3], [("pick:synth:2027:r1:o3", 3, 1), ("p:101", 1, 3)]))
    for team in out["teams"].values():
        assert team["fairness"]["reasonCode"] == "ownership_unverifiable"
    # The pick still carries ONE value in both views (generic grade by label).
    sent = out["teams"][3]["gives"][0]
    got = out["teams"][1]["receives"][0]
    assert sent["value"] == got["value"]


# ══ Roster capacity (I16) and the execution side ══════════════════════════


def test_i16_forced_drops_come_from_the_post_trade_roster_and_are_not_legs():
    contract = mts.synthetic_league()
    settings = {**mts.SYNTH_SETTINGS, "rosterSize": 5}
    snap = tl.build_trade_snapshot(
        contract, league_key=mts.SYNTH_KEY, roster_settings=settings, now=mts.PINNED_NOW
    )
    # Team 2 holds 4, receives 3 and sends 1 -> 6 of 5: one forced release.
    legs = [
        ("p:101", 1, 2),
        ("p:102", 1, 2),
        ("p:104", 1, 2),
        ("p:201", 2, 1),
        ("p:401", 4, 1),
        ("p:103", 1, 4),
    ]
    ledger = _ledger(snap, [1, 2, 4], legs)
    leg_ids = {leg.asset_id for leg in ledger.legs}
    out = _run(snap, ledger, "asset_only")
    cap2 = out["teams"][2]["simulation"]["rosterCapacity"]
    assert cap2["sizeAfter"] == 6 and cap2["overLimitAfter"] == 1
    assert len(cap2["forcedDrops"]) == 1
    for rid, team in out["teams"].items():
        cap = team["simulation"]["rosterCapacity"]
        drops = {str(d["playerId"]) for d in cap.get("forcedDrops") or []}
        gives = {g["assetId"][2:] for g in team["gives"] if g["kind"] == "player"}
        assert not drops & gives, rid  # disjoint from G_i
        post = set(snap.teams_by_roster_id[rid]["playerIds"]) - gives | {
            r["assetId"][2:] for r in team["receives"] if r["kind"] == "player"
        }
        assert drops <= post, rid  # chosen from post_i
        listed = {g["assetId"] for g in (*team["gives"], *team["receives"])}
        assert listed <= leg_ids  # never legs, never in gives/receives
        assert not {f"p:{d}" for d in drops} & listed
    assert out["summary"]["conservation"]["assetsSent"] == len(legs)


def test_capacity_matches_outgoing_players_by_id_not_display_name():
    """A board label that differs from the Sleeper roster name still frees
    the spot (``roster_capacity.outgoing_roster_names``)."""
    contract = mts.synthetic_league()
    contract["sleeper"]["teams"][0]["players"][0] = "A. Six (Sleeper spelling)"
    snap = mts.synthetic_snapshot(contract)
    out = _run(snap, _ledger(snap, [1, 2], [("p:101", 1, 2), ("p:201", 2, 1)]), "asset_only")
    cap = out["teams"][1]["simulation"]["rosterCapacity"]
    assert cap["outgoingNotOnRoster"] == 0
    assert cap["sizeAfter"] == cap["sizeBefore"]


def test_market_fairness_computes_no_roster_capacity():
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 2, 3], I14_LEGS), "market_fairness")
    for team in out["teams"].values():
        sim = team["simulation"]
        for key in ("rosterCapacity", "finalRosterSimulation", "rosterUtility"):
            assert key not in sim
        assert sim["competitivePosture"]["unavailableReason"] == "not_requested_market_fairness"


# ══ Mode rules: writes nothing, posture memo, identity, model gate ════════


def test_market_fairness_writes_nothing_shared_or_persistent(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("market_fairness touched a shared writer/cache")

    import src.api.gameplan as gameplan
    import src.roster_intel.best_ball_utility as bbu
    import src.trade.roster_capacity as rc
    import src.trade.trade_decision_log as log
    from src.api import trade_analyze_runtime as rt

    monkeypatch.setattr(log, "record_decision", boom)
    monkeypatch.setattr(rt.PROGRESS, "begin", boom)
    monkeypatch.setattr(gameplan, "league_competitive_postures", boom)
    monkeypatch.setattr(bbu, "evaluate_trade_utility", boom)
    monkeypatch.setattr(rc, "build_capacity_context", boom)
    monkeypatch.setattr(rc, "evaluate_final_roster_utility", boom)
    snap = mts.synthetic_snapshot()
    out = svc.analyze_trade_n(
        snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode="market_fairness", counterfactuals=False
    )
    assert len(out["teams"]) == 3


def test_team_context_reads_one_posture_bundle_per_request(monkeypatch):
    calls = []

    class _P:
        def __init__(self, oid):
            self.oid = oid

        def to_dict(self):
            return {"label": "HOLD", "owner": self.oid, "notes": ["LABELLED synthetic"]}

    def fake(league_key, profile, contract, *, build_if_missing):
        calls.append(build_if_missing)
        return {f"owner{i}": _P(f"owner{i}") for i in range(1, 5)}, {"bundleFreshness": "fresh"}

    import src.api.gameplan as gameplan
    from src.api import trade_simulator

    monkeypatch.setattr(gameplan, "league_competitive_postures", fake)
    snap = mts.synthetic_snapshot()
    out = svc.analyze_trade_n(
        snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode="team_context", counterfactuals=False
    )
    assert calls == [True]
    for rid, team in out["teams"].items():
        expect = trade_simulator.competitive_posture_for(
            snap.contract, snap.league_key, snap.teams_by_roster_id[rid], build_if_missing=True
        )
        assert team["simulation"]["competitivePosture"] == expect
    calls.clear()
    svc.analyze_trade_n(
        snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode="asset_only", counterfactuals=False
    )
    assert calls == [False]


_SCARCITY_DOWN = "positional scarcity unavailable (GameplanUnavailable) — multiplier inert"
CYCLE_4 = [("p:101", 1, 2), ("p:201", 2, 3), ("p:301", 3, 4), ("p:401", 4, 1)]


def _flapping_scarcity(reads):
    """A scarcity source that answers the FIRST read and fails every later one
    — what the gameplan bundle does when its 120 s live-compute fallback
    expires part-way through a request.  Records every read."""
    from src.league_intel.replacement import ScarcityComponents

    ok = {
        pos: ScarcityComponents(pos, 0.5, 0.5, w, None, None, None)
        for pos, w in (("QB", 0.9), ("RB", 0.4), ("WR", 0.3), ("TE", 0.7))
    }

    def fake(league_key, contract):
        reads.append(league_key)
        return (ok, None) if len(reads) == 1 else (None, _SCARCITY_DOWN)

    return fake


def _scarcity_down(team) -> bool:
    return _SCARCITY_DOWN in (team["simulation"]["rosterCapacity"].get("notes") or [])


@pytest.mark.parametrize("mode", ["team_context", "asset_only"])
def test_scarcity_is_read_once_per_request_and_shared_by_every_team(monkeypatch, mode):
    """R1-1: the league scarcity bundle is read ONCE per N-team request and the
    same reading reaches every team's capacity context — never once per team,
    which let teams of one trade be scored against different scarcity."""
    from src.trade import roster_capacity

    reads: list = []
    monkeypatch.setattr(roster_capacity, "_league_scarcity", _flapping_scarcity(reads))
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 2, 3, 4], CYCLE_4), mode)
    assert reads == [snap.league_key]
    assert [_scarcity_down(t) for t in out["teams"].values()] == [False] * 4
    # A second request reads again — no cross-request memo, so a request sees
    # the scarcity current when it runs — and again every team agrees.
    out2 = _run(snap, _ledger(snap, [1, 2, 3, 4], CYCLE_4), mode)
    assert reads == [snap.league_key] * 2
    assert [_scarcity_down(t) for t in out2["teams"].values()] == [True] * 4


def test_market_fairness_reads_no_scarcity(monkeypatch):
    from src.trade import roster_capacity

    reads: list = []
    monkeypatch.setattr(roster_capacity, "_league_scarcity", _flapping_scarcity(reads))
    snap = mts.synthetic_snapshot()
    _run(snap, _ledger(snap, [1, 2, 3, 4], CYCLE_4), "market_fairness")
    assert reads == []


def test_per_team_helper_still_reads_scarcity_itself_by_default(monkeypatch):
    """The 2-team routes' path is unchanged: with no reading handed in,
    ``simulate_for_team`` reads scarcity itself, once."""
    from src.trade import roster_capacity

    reads: list = []
    monkeypatch.setattr(roster_capacity, "_league_scarcity", _flapping_scarcity(reads))
    snap = mts.synthetic_snapshot()
    sim = svc.simulate_for_team(
        dict(snap.contract),
        league_key=snap.league_key,
        roster_settings=dict(snap.roster_settings or {}),
        resolved_team=snap.teams_by_roster_id[1],
        players_in=["B Seven"],
        players_out=["A Six"],
        player_ids_in=["201"],
        player_ids_out=["101"],
        team_context=False,
        for_analysis=True,
        posture_resolver=_no_posture,
    )
    assert reads == [snap.league_key]
    assert _SCARCITY_DOWN not in (sim["rosterCapacity"].get("notes") or [])


def test_orphan_or_shared_owner_ids_never_borrow_another_teams_posture(monkeypatch):
    import src.api.gameplan as gameplan

    monkeypatch.setattr(
        gameplan,
        "league_competitive_postures",
        lambda *a, **k: ({"": object()}, {}),
    )
    contract = mts.synthetic_league()
    contract["sleeper"]["teams"][0]["ownerId"] = ""
    contract["sleeper"]["teams"][1]["ownerId"] = ""
    snap = mts.synthetic_snapshot(contract)
    out = svc.analyze_trade_n(
        snap, _ledger(snap, [1, 2, 3], I14_LEGS), mode="team_context", counterfactuals=False
    )
    for rid in (1, 2):
        posture = out["teams"][rid]["simulation"]["competitivePosture"]
        assert posture == {"available": False, "unavailableReason": "owner_identity_ambiguous"}
        gaps = [g["code"] for g in out["teams"][rid]["analysis"]["decision"]["missingEvidence"]]
        assert "posture_unknown" in gaps
        assert out["teams"][rid]["category"] == "UNAVAILABLE"


def test_team_context_never_falls_back_to_an_asset_only_verdict():
    snap = mts.synthetic_snapshot()
    out = _run(snap, _ledger(snap, [1, 2, 3], I14_LEGS), "team_context")
    for team in out["teams"].values():
        assert team["analysis"]["teamContext"]["mode"] == "team"
        assert team["analysis"]["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
        assert team["category"] == "UNAVAILABLE"
        assert team["analysis"]["decision"]["recommendationOnly"] is True
        assert team["analysis"]["decision"]["executes"] is False


def test_refuses_under_the_ktc_rollback_model(monkeypatch):
    from src.valuation_math import package_model

    monkeypatch.setattr(
        package_model, "_config", lambda: {"active": "ktc_2026_04", "shadow": [], "state": "ok"}
    )
    snap = mts.synthetic_snapshot()
    with pytest.raises(svc.PackageModelUnavailable):
        _run(snap, _ledger(snap, [1, 2], [("p:101", 1, 2), ("p:201", 2, 1)]))
    monkeypatch.setattr(
        package_model,
        "_config",
        lambda: {"active": "geom_q078_v1", "shadow": [], "state": "unreadable"},
    )
    assert svc.package_model_ready() is False


def test_comparables_stamp_at_three_or_more_teams_and_provider_at_two():
    snap = mts.synthetic_snapshot()
    seen = []

    def provider(flows, simulation):
        seen.append((flows.roster_id, len(simulation["receiving"])))
        return {"state": "unavailable", "reason": "test"}

    out3 = svc.analyze_trade_n(
        snap,
        _ledger(snap, [1, 2, 3], I14_LEGS),
        mode="asset_only",
        counterfactuals=False,
        comparables_provider=provider,
    )
    assert seen == []
    for team in out3["teams"].values():
        assert team["comparables"] == {"state": "not_computed_multi_team"}
    out2 = svc.analyze_trade_n(
        snap,
        _ledger(snap, [1, 2], [("p:101", 1, 2), ("p:201", 2, 1)]),
        mode="asset_only",
        counterfactuals=False,
        comparables_provider=provider,
    )
    assert seen == [(1, 1), (2, 1)]
    for team in out2["teams"].values():
        lens = team["analysis"]["lenses"]["comparables"]
        assert lens["unavailableReason"] == "test"
        assert "comparables" not in team


def test_stage_hook_names_each_teams_stages():
    from contextlib import contextmanager

    names = []

    @contextmanager
    def stage(name):
        names.append(name)
        yield

    snap = mts.synthetic_snapshot()
    _run(snap, _ledger(snap, [1, 2], [("p:101", 1, 2), ("p:201", 2, 1)]), "asset_only", stage=stage)
    assert names == [
        "team:1:posture",
        "team:1:simulation",
        "team:1:decision",
        "team:2:posture",
        "team:2:simulation",
        "team:2:decision",
    ]


# ══ Category / fairness consistency (R5 / I20) on the synthetic board ═════


def _consistency(out, mode):
    for team in out["teams"].values():
        d = team["analysis"]["decision"]
        f = team["fairness"]["state"]
        if team["category"] == "STRONGLY_FAVORABLE":  # C1
            assert f == "NOT_FAIR"
        if f == "UNABLE":  # C3
            assert d["headline"] == "NOT_ENOUGH_EVIDENCE" or (
                d["headline"] == "NO" and d["deciding"] == "executionGate"
            )
        if (
            mode != "team_context"
            and not d.get("missingEvidence")
            and d["headline"]
            in (
                "YES",
                "NO",
                "NO_TOO_CLOSE",
            )
        ):  # C2
            assert (d["headline"] == "NO_TOO_CLOSE") == (f == "FAIR")


# ══ Real archived board: seeded property sweep ═════════════════════════════


@pytest.fixture(scope="module")
def board():
    return mts.real_board()


def test_property_sweep_on_the_real_board(board):
    _contract, snap, _label = board
    rng = random.Random(20261020)
    rows = snap.rows_by_player_id
    for i in range(18):
        teams, legs = mts.random_ledger(snap, rng)
        ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=POLICY)
        mode = "asset_only" if i % 3 == 0 else "market_fairness"
        out = svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False)
        _assert_ledger_reconciles(out, ledger)  # I6 / I7
        _consistency(out, mode)  # I20
        ref = _canon(out)
        # I1: team order; I2: leg order; I3: determinism.
        perm_teams = teams[::-1]
        perm_legs = legs[:]
        rng.shuffle(perm_legs)
        again = tl.validate_ledger(snap, teams=perm_teams, legs=perm_legs, policy=POLICY)
        assert _canon(svc.analyze_trade_n(snap, again, mode=mode, counterfactuals=False)) == ref
        # I13: one canonical value per player, equal to its board value.
        for team in out["teams"].values():
            for row in (*team["gives"], *team["receives"]):
                if row["kind"] == "player" and row["valueState"] == "priced":
                    board_row = rows.get(row["assetId"][2:])
                    assert board_row is not None
                    assert row["value"] == int(board_row["rankDerivedValue"])
        # I15: raw conservation.
        cons = out["summary"]["conservation"]
        assert cons["pricedRawSent"] == cons["pricedRawReceived"]
        # I5 / I18 at N = 2.
        if len(ledger.teams) == 2:
            a, b = (out["teams"][r]["fairness"] for r in ledger.teams)
            assert a["state"] == b["state"]
            if a["state"] != "UNABLE":
                assert a["gap"] == -b["gap"]
                assert a["largerAdjustedSide"] == b["largerAdjustedSide"]
                assert a["level"] == b["level"]


def test_real_board_four_team_exhaustive_team_order(board):
    _contract, snap, _label = board
    rng = random.Random(4)
    teams, legs = mts.random_ledger(snap, rng, n_teams=4, max_per_team=2)
    ref = None
    for perm in itertools.permutations(teams):
        ledger = tl.validate_ledger(snap, teams=list(perm), legs=legs, policy=POLICY)
        out = _canon(
            svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
        )
        ref = ref or out
        assert out == ref


def test_real_recorded_trades_replayed_in_reverse(board):
    _contract, snap, _label = board
    replays = mts.reverse_replays(snap)
    if not replays:
        pytest.skip("no recorded own-league trade still matches today's rosters")
    for r in replays:
        ledger = tl.validate_ledger(snap, teams=r["teams"], legs=r["legs"], policy=POLICY)
        for mode in ("market_fairness", "asset_only"):
            out = svc.analyze_trade_n(snap, ledger, mode=mode, counterfactuals=False)
            _assert_ledger_reconciles(out, ledger)
            _consistency(out, mode)
            assert out["summary"]["teamCount"] == len(r["teams"])


def test_real_three_team_structures_on_todays_rosters(board):
    """The recorded 3-team own-league trades, routing kept, assets held today."""
    _contract, snap, _label = board
    replays = mts.structure_replays(snap, sides=3)
    if not replays:
        pytest.skip("no recorded 3-team own-league trade in this archive")
    for r in replays:
        ledger = tl.validate_ledger(snap, teams=r["teams"], legs=r["legs"], policy=POLICY)
        for mode in svc.MODES:
            out = svc.analyze_trade_n(
                snap,
                ledger,
                mode=mode,
                counterfactuals=False,
                posture_resolver=_no_posture if mode == "team_context" else None,
            )
            _assert_ledger_reconciles(out, ledger)
            _consistency(out, mode)
            assert len(out["summary"]["lines"]) == 3
            # Simultaneity: each team equals a fresh evaluation of only its own legs
            # inside the same snapshot (the other teams' legs never leak in).
            for rid in ledger.teams:
                mine = [leg for leg in r["legs"] if rid in (leg["from"], leg["to"])]
                partners = sorted({leg["from"] for leg in mine} | {leg["to"] for leg in mine})
                if len(partners) < 2:
                    continue
                solo = tl.validate_ledger(snap, teams=partners, legs=mine, policy=POLICY)
                alone = svc.analyze_trade_n(
                    snap,
                    solo,
                    mode="market_fairness",
                    counterfactuals=False,
                )
                if mode == "market_fairness":
                    assert _canon(alone["teams"][rid]["fairness"]) == _canon(
                        out["teams"][rid]["fairness"]
                    )


def test_two_way_player_carries_one_value_in_every_view(board):
    _contract, snap, _label = board
    hunter = [
        pid
        for pid, row in snap.rows_by_player_id.items()
        if row and str(row.get("displayName") or "") == "Travis Hunter"
    ]
    holders = [r for pid in hunter for r in snap.player_owners.get(pid, ())]
    if len(hunter) != 1 or len(holders) != 1:
        pytest.skip("two-way player not on exactly one roster in this archive")
    pid, owner = hunter[0], holders[0]
    other = next(r for r in sorted(snap.teams_by_roster_id) if r != owner)
    back = mts.team_assets(snap, other)[0]
    ledger = tl.validate_ledger(
        snap,
        teams=[owner, other],
        legs=[
            {"id": f"p:{pid}", "from": owner, "to": other},
            {"id": back, "from": other, "to": owner},
        ],
        policy=POLICY,
    )
    out = svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
    sent = next(g for g in out["teams"][owner]["gives"] if g["assetId"] == f"p:{pid}")
    got = next(g for g in out["teams"][other]["receives"] if g["assetId"] == f"p:{pid}")
    assert sent["value"] == got["value"] == int(snap.rows_by_player_id[pid]["rankDerivedValue"])


def test_rosters_older_than_the_budget_fail_closed_on_the_real_board(board):
    contract, _snap, _label = board
    snap = tl.build_trade_snapshot(
        contract,
        league_key="dynasty_main",
        roster_settings=mts._dynasty_main_settings(),
        now=mts.PINNED_NOW + timedelta(hours=12),
    )
    assert snap.rosters_state == "stale"
    teams, legs = mts.random_ledger(snap, random.Random(9), n_teams=3)
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=POLICY)
    out = svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
    assert out["summary"]["fairnessOverall"]["state"] == "UNABLE"
    for team in out["teams"].values():
        # An unpriced asset gates first (gate order); ownership always fires.
        assert team["fairness"]["state"] == "UNABLE"
        assert team["fairness"]["reasonCode"] in ("ownership_unverifiable", "asset_not_evaluable")
        assert team["simulation"]["ownershipEvidence"]["unverifiableAssetIds"]
        codes = [g["code"] for g in team["analysis"]["decision"]["missingEvidence"]]
        assert "ownership_unverifiable" in codes


def test_engine_is_not_gated_by_the_private_flag(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "0")
    snap = mts.synthetic_snapshot()
    with mock.patch("src.api.feature_flags.is_enabled", side_effect=AssertionError("gated")):
        out = _run(snap, _ledger(snap, [1, 2, 3], I14_LEGS))
    assert len(out["teams"]) == 3
