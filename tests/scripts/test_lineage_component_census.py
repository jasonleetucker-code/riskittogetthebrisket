"""Manager-lineage component census (owner Package 5A, 2026-10-21).

Synthetic ids only.  Pins: the three component definitions on a hand-built
graph (links from every trade, not only the population), the concentration
statistics, the policy leakage arithmetic (one key space; partial observation
never counted as observed), replicate reporting that never hides an empty
holdout, the guard requirement in box mode, read-only stores left
byte-identical, and that no identifier can reach the output.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "lineage_component_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("lineage_component_census", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["lineage_component_census"] = mod
    spec.loader.exec_module(mod)
    return mod


lcc = _load()
Trade = lcc.Trade
Dataset = lcc.Dataset


def _ds() -> Dataset:
    """Leagues a<-b (one lineage), c, d, e.  Manager m1 trades in a, b and c,
    so P joins {a,b,c}; m9 is only a MEMBER of c and d, so M also joins d; e is
    alone under every definition; one KTC row has no league."""
    d0 = date(2026, 7, 1)

    def t(league, day, parts=(), lane=lcc.LANE_SLEEPER):
        return Trade(lane=lane, league=league, day=date.fromordinal(d0.toordinal() + day),
                     participants=tuple(parts), fit=True, estimator=True)  # fmt: skip

    trades = [
        t("a", 0, ("m1", "m2")),
        t("b", 10, ("m1", "m3")),
        t("b", 20, ("m3", "m4")),
        t("c", 30, ("m1", "m5")),
        t("d", 40, ("m6", "m7")),
        t("e", 50, ("m8", "m10")),
        t("e", 60, ("m8", "m10")),
        t(None, 70, (), lcc.LANE_KTC),
    ]
    return Dataset(
        trades=trades,
        predecessor={"b": "a"},
        members={"c": {"m1", "m5", "m9"}, "d": {"m6", "m7", "m9"}, "e": {"m8", "m10"}},
        known_leagues={"a", "b", "c", "d", "e"},
    )


def _sizes(labels: np.ndarray) -> list[int]:
    return sorted(np.bincount(labels).tolist(), reverse=True)


def test_three_definitions_on_a_known_graph():
    ds = _ds()
    idx = list(range(len(ds.trades)))
    assert _sizes(lcc.component_labels(ds, idx, "L")) == [3, 2, 1, 1, 1]
    assert _sizes(lcc.component_labels(ds, idx, "P")) == [4, 2, 1, 1]
    assert _sizes(lcc.component_labels(ds, idx, "M")) == [5, 2, 1]


def test_lineage_walk_survives_a_predecessor_loop():
    ds = _ds()
    ds.predecessor.update({"a": "b"})  # a <-> b loop: must terminate
    assert _sizes(lcc.component_labels(ds, [0, 1, 2], "L")) == [3]


def test_links_come_from_every_trade_not_only_the_population():
    ds = _ds()
    ds.trades.append(Trade(lane=lcc.LANE_SLEEPER, league="d", day=None,
                           participants=("m8", "m6"), fit=False))  # fmt: skip
    pop = [i for i, t in enumerate(ds.trades) if t.fit]
    # the non-fit trade joins d and e, although it is outside the population
    assert _sizes(lcc.component_labels(ds, pop, "P")) == [4, 3, 1]


def test_concentration_statistics():
    labels = np.array([0, 0, 0, 0, 0, 0, 1, 1, 2, 3])
    c = lcc.concentration(labels)
    assert c["components"] == 4 and c["trades"] == 10
    assert c["topKTradeShare"]["1"] == 0.6
    assert c["hhi"] == round(0.36 + 0.04 + 0.01 + 0.01, 4)
    assert c["effectiveComponents"] == round(1 / 0.42, 4)
    assert c["gini"] == 0.4
    assert c["singletonComponents"] == 2
    assert c["componentsBySize"] == {
        "1": 2, "2-4": 1, "5-9": 1, "10-49": 0, "50-249": 0, "250-999": 0, "1000+": 0,
    }  # fmt: skip
    equal = lcc.concentration(np.array([0, 1, 2, 3]))
    assert equal["gini"] == 0.0 and equal["effectiveComponents"] == 4.0


def _hand_split():
    train = np.array([True, True, False, False, True, False, False, False])
    return train, ~train


def test_leakage_arithmetic_for_a_hand_split():
    ds = _ds()
    fr = lcc._frame(ds, list(range(len(ds.trades))))
    train, ev = _hand_split()
    out = lcc._evaluate(fr, train, ev)
    assert out["train"] == 3 and out["eval"] == 5 and out["unused"] == 0
    assert out["evalShare"] == 5 / 8
    # eval: b(20) m3 also trades in b(10) -> leak; c(30) m1 -> leak; e twice no.
    assert out["participantLeak"] == 2 / 4
    assert out["participantUnobservedShare"] == 1 / 5  # the KTC row
    assert out["lineageLeak"] == 1 / 5  # only b(20): its lineage (a<-b) trained
    assert out["leakageUnmeasurableShare"] == 1 / 5
    # one key space: b(20) via m3, c(30) via m1 and m9 (a member of d, which
    # trained); e never.  The KTC row has no keys and is outside the base.
    assert out["membershipLeak"] == 2 / 4
    assert out["evalDatedBeforeTrainEnd"] == 2 / 5  # b(20), c(30) <= d(40)


def test_partial_participants_are_not_counted_as_observed():
    ds = _ds()
    ds.trades[3].participants = ("m1",)  # c(30): one side's manager unseen
    fr = lcc._frame(ds, list(range(len(ds.trades))))
    train, ev = _hand_split()
    out = lcc._evaluate(fr, train, ev)
    assert out["participantLeak"] == 1 / 3  # complete evals: b20, e50, e60
    assert out["participantLeakAnyObserved"] == 2 / 4
    assert out["participantPartialShare"] == 1 / 5


def test_component_reserve_never_leaks_through_participants():
    ds = _ds()
    out = lcc.simulate_policies(ds, list(range(len(ds.trades))), replicates=60, windows=(30,))
    for f in ("10pct", "20pct", "30pct"):
        res = out[f"componentReserve_{f}"]
        assert res["replicates"] == 60
        assert res["replicatesWithEval"] > 0  # not vacuous
        assert res["participantLeak"]["max"] == 0.0
        assert res["lineageLeak"]["max"] == 0.0
    assert out["chronologicalOnly_30d"]["evalDatedBeforeTrainEnd"]["max"] == 0.0


def test_empty_holdouts_are_counted_never_hidden():
    rows = [{"train": 8.0, "eval": 0.0, "evalShare": 0.0, "unused": 0.0}] * 3 + [
        {"train": 0.0, "eval": 8.0, "evalShare": 1.0, "unused": 0.0, "participantLeak": 0.0}
    ]
    s = lcc._summ(rows)
    assert s["replicates"] == 4 and s["replicatesWithEval"] == 1
    assert s["evalShare"]["mean"] == 0.25  # zeros included
    assert s["evalShare"]["min"] == 0.0 and s["evalShare"]["max"] == 1.0
    assert isinstance(s["participantLeak"], dict)  # never collapsed to a scalar


def test_chronological_windows_and_purge_boundaries():
    ds = _ds()
    fr = lcc._frame(ds, list(range(len(ds.trades))))
    tr, ev = lcc._windows(fr, 20, 7)  # end = day 70; eval > 50; train <= 43
    assert ev.tolist() == [False] * 6 + [True, True]
    assert tr.tolist() == [True] * 5 + [False] * 3


def test_hybrid_is_whole_league_when_one_component_covers_everything():
    ds = _ds()
    for t in ds.trades:  # one manager everywhere -> one giant P-component
        if t.league:
            t.participants = (*t.participants, "hub")
    out = lcc.simulate_policies(ds, list(range(7)), replicates=30, windows=(30,), fractions=(0.5,))
    assert out["giantComponents"] == 1 and out["giantTradeShare"] == 1.0
    hy, wl = out["hybrid_50pct_30d"], out["wholeLeagueChronological_50pct_30d"]
    assert hy["replicatesWithEval"] > 0 and wl["replicatesWithEval"] > 0
    # both hold lineages, so both leak through the hub (0 only in a replicate
    # whose training set came out empty)
    assert hy["participantLeak"]["max"] == 1.0 and wl["participantLeak"]["max"] == 1.0
    assert hy["evalComponentsP"]["max"] == 1.0  # never more than the one giant


def test_simulation_hash_is_not_the_reserve_hash():
    """The census hashes its own framing and never reads the reserve config."""
    u = lcc._unit_uniforms(1, "cmp", 0)[0]
    expected = hashlib.sha256(b"census-sim|0|cmp0").digest()
    assert u == int.from_bytes(expected[:8], "big") / 2.0**64
    src = SCRIPT.read_text(encoding="utf-8")
    assert "chase_trade_market_reserve" not in src
    assert "draw_reserve" not in src
    assert "market_trade_reserve" not in src


def test_output_refuses_identifier_like_text():
    with pytest.raises(ValueError):
        lcc.assert_aggregate_only({"x": "league 1234567890123"})
    for bad in ("mk:abc", "unknown:12345", "sleeper:7", "mfl:4421", "U:m1"):
        with pytest.raises(ValueError):
            lcc.assert_aggregate_only({"x": bad})
    lcc.assert_aggregate_only(
        {"x": 0.1234, "n": 29638, "d": "2026-10-21", "t": "2026-10-21T13:05:00+00:00"}
    )


def test_synthetic_output_passes_the_id_guard():
    args = argparse.Namespace(box=False, synthetic=0.05, seed=0, replicates=3, ledger=None)
    result, code = lcc.run(args)
    assert code == 0 and result["dataLabel"].startswith("SYNTHETIC")


def test_box_mode_refuses_to_run_without_the_guard_and_rejects_abbreviations(capsys):
    with pytest.raises(SystemExit):
        lcc.main(["--bo"])
    capsys.readouterr()
    assert lcc.main(["--box"]) == 64  # GUARD is None in this process
    assert json.loads(capsys.readouterr().out)["reason"] == "box_mode_requires_the_read_only_guard"


# ── store path: read-only, byte-identical, aggregates only ─────────────────


def _record(league, tx, day, *, fit=True, host="sleeper", fam="sleeper_sharp_discovery"):
    asset = {"kind": "player", "canonicalId": "player:1", "matchKey": "p1"}
    other = {"kind": "player", "canonicalId": "player:2", "matchKey": "p2"}
    return {
        "dedupeState": "CONFIRMED_UNIQUE",
        "host": host,
        "hostLeagueId": league,
        "hostTxId": tx,
        "occurredDate": day,
        "collectedAt": f"{day}T12:00:00+00:00",
        "rosterExclusivity": {"state": "exclusive"},
        "sourceFamilies": [fam],
        "sides": [[asset], [other]],
        "marketFormat": {
            "general": {"dynastyState": "dynasty" if fit else None},
            "offense": {"superflex": True},
        },
    }


def _stores(tmp_path: Path) -> tuple[Path, Path]:
    ledger = tmp_path / "underlying_trades.sqlite"
    conn = sqlite3.connect(ledger)
    conn.executescript(
        "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);"
        "CREATE TABLE underlying_trades (underlying_trade_id TEXT PRIMARY KEY,"
        " record_json TEXT NOT NULL);"
    )
    rows = [
        ("u1", _record("900000000000000001", "t1", "2026-09-01")),
        ("u2", _record("900000000000000002", "t2", "2026-09-20")),
        ("u3", _record("900000000000000003", "t3", "2026-10-15")),
        ("u4", _record("900000000000000003", "t4", "2026-10-16", fit=False)),
        ("u5", _record("k77", None, "2026-10-10", host="sleeper", fam="ktc_trade_database")),
        # a duplicate group whose representative is a KTC row with no host:
        # its Sleeper tx id still names the league through the intel ledger
        ("u6", _record("k88", "t9", "2026-10-11", fit=False, host="")),
    ]
    conn.executemany(
        "INSERT INTO underlying_trades VALUES (?, ?)", [(k, json.dumps(v)) for k, v in rows]
    )
    conn.execute("INSERT INTO meta VALUES ('builtAt', ?)", (json.dumps("2026-10-21T08:52:00Z"),))
    conn.commit()
    conn.close()
    intel = tmp_path / "ledger.sqlite3"
    conn = sqlite3.connect(intel)
    conn.executescript(
        "CREATE TABLE asset_movements (league_id TEXT, tx_id TEXT, tx_type TEXT, user_id TEXT);"
        "CREATE TABLE leagues (league_id TEXT PRIMARY KEY, previous_league_id TEXT);"
        "CREATE TABLE league_memberships (league_id TEXT, user_id TEXT);"
    )
    conn.executemany(
        "INSERT INTO asset_movements VALUES (?, ?, 'trade', ?)",
        [
            ("900000000000000001", "t1", "800000000000000001"),
            ("900000000000000001", "t1", "800000000000000002"),
            ("900000000000000002", "t2", "800000000000000001"),
            ("900000000000000002", "t2", "800000000000000003"),
            ("900000000000000003", "t3", "800000000000000004"),
            ("900000000000000003", "t3", "800000000000000005"),
            ("900000000000000001", "t9", "800000000000000006"),
        ],
    )
    conn.executemany(
        "INSERT INTO leagues VALUES (?, ?)",
        [("900000000000000001", "0"), ("900000000000000002", None),
         ("900000000000000003", "900000000000000099")],
    )  # fmt: skip
    conn.commit()
    conn.close()
    return ledger, intel


def _digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_store_run_is_read_only_and_aggregate(tmp_path, capsys):
    ledger, intel = _stores(tmp_path)
    before = (_digest(ledger), _digest(intel))
    code = lcc.main(["--ledger", str(ledger), "--intel", str(intel), "--replicates", "5"])
    out = capsys.readouterr().out
    assert code == 0
    assert (_digest(ledger), _digest(intel)) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "ledger.sqlite3",
        "underlying_trades.sqlite",
    ]
    assert "9000000" not in out and "8000000" not in out and "k77" not in out
    res = json.loads(out)
    pop = res["populations"]
    assert pop["allProvenDedupe"]["coverage"]["trades"] == 6
    assert pop["allProvenDedupe"]["coverage"]["leagues"] == 4  # u6 joined league 1
    assert pop["fitEligible"]["coverage"]["trades"] == 4
    assert pop["fitEligibleSleeperObserved"]["coverage"]["trades"] == 3
    assert pop["estimatorEligibleSleeperObserved"]["coverage"]["trades"] == 3
    link = pop["fitEligibleSleeperObserved"]["linkage"]
    assert link["participantsComplete"] == 3 and link["leaguesInIntelTable"] == 3
    assert link["predecessorLinksLeavingTheTable"] == 1
    # m1 trades in leagues 1 and 2 -> P joins them; league 3 stays separate.
    assert pop["fitEligibleSleeperObserved"]["components"]["L"]["components"] == 3
    assert pop["fitEligibleSleeperObserved"]["components"]["P"]["components"] == 2
    assert pop["fitEligibleSleeperObserved"]["coverage"]["byLane"] == {"sleeper_observed": "<5"}
    assert res["inputs"]["intel"]["tradesFoundInIntel"] == 4
    assert res["inputs"]["intel"]["tradesWithParticipants"] == 4
    assert res["inputs"]["ledger"]["managerKeyStates"] == {"absent": 6}
    assert res["inputs"]["clock"] == "collected"
    assert res["inputs"]["ledgerBuiltAt"] == "2026-10-21T08:52:00Z"


def test_missing_ledger_exits_2(tmp_path, capsys):
    assert lcc.main(["--ledger", str(tmp_path / "absent.sqlite")]) == 2
    assert json.loads(capsys.readouterr().out)["available"] is False
