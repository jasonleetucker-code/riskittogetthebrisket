"""chaseTradeMarket P2 — evidence fields on the completed-trade ledger (G8, G9).

Everything here is ADDITIVE evidence for the shadow trade-market estimator:

* per observation: acquisition channel (``sleeper_observed`` / ``ktc_database``),
  the point-in-time collection clock, which crawl wrote an intel-ledger row,
  sender attribution + pick origin + optional pseudonymous manager keys;
* per underlying trade: channels, collection clocks, the widest overlap
  cluster and an explicit KTC-overlap state, roster exclusivity, the league
  maturity hook (both readings) and the estimator's evidence flags;
* report level: the measured Sleeper/KTC overlap and per-exclusion losses.

And the guarantee that makes it additive: every listed consumer (TC-07
reference, TC-08 database, TC-09 comparable trades, the Signals on-box
verifier) produces IDENTICAL output whether or not a ledger record carries the
new fields; Trade History and the public League Hub cannot reach the ledger.

All fixtures are synthetic (``tests/trade/market_trade_fixtures.py``).
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from src.intel import ledger
from src.sources.ktc_identity import identity_from_rows
from src.trade import comparable_trades as ct
from src.trade import faab_comparability as fc
from src.trade import market_trade_database as db
from src.trade import market_trade_eval as E
from src.trade import market_trade_format as F
from src.trade import market_trade_groups as G
from src.trade import market_trade_normalize as N
from src.trade import market_trade_reference as ref
from src.trade import market_trade_report as R
from tests.trade.market_trade_fixtures import KTC_INDEX, ctx, ktc_row, ktc_settings
from tests.trade.test_market_trade_normalize import _ev, _trade_events
from tests.trade.test_market_trade_report import _build, _seed, env  # noqa: F401 — fixture

REPO = Path(__file__).resolve().parents[2]
IDENT = identity_from_rows(KTC_INDEX, source="synthetic")
SECRET = b"synthetic-test-secret-not-a-real-key"


def _raw(row, *, fetched="2026-10-02T09:00:00+00:00", revision_count=1):
    return {
        "sourceNativeId": str(row["id"]),
        "payloadSha256": "y" * 64,
        "payload": row,
        "revision": revision_count,
        "revisionCount": revision_count,
        "firstFetchedAt": fetched,
    }


@pytest.fixture
def intel(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    path = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(path).close()
    yield path
    ledger.reset_setup_cache()


def _ingest_at(intel, events, ms, monkeypatch):
    monkeypatch.setattr(ledger, "_now_ms", lambda: ms)
    ledger.ingest_events(events, path=intel)


def _sleeper_obs(intel, **kw):
    rows, status = N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx(), **kw)
    return rows, status


# ── observation level ─────────────────────────────────────────────────────


class TestKtcObservationEvidence:
    def test_channel_and_collection_clock(self):
        obs = N.normalize_ktc_row(
            _raw(ktc_row(1, [11], [12]), revision_count=2),
            IDENT,
            ctx(),
            first_fetched_at="2026-10-01T08:00:00Z",
        )
        assert obs["observationChannel"] == "ktc_database"
        # The revision used here did not exist on the box before its own fetch.
        assert obs["collectedAt"] == "2026-10-02T09:00:00+00:00"
        assert obs["firstCollectedAt"] == "2026-10-01T08:00:00+00:00"
        assert obs["collectedAtBasis"] == N.COLLECTED_BASIS_KTC_TRADE

    def test_packages_name_no_sender_and_no_manager(self):
        obs = N.normalize_ktc_row(_raw(ktc_row(1, [11], [12, 13])), IDENT, ctx())
        ev = obs["sideEvidence"]
        assert ev["attribution"] == N.SIDE_ATTRIBUTION_PACKAGES
        assert ev["managerKeyState"] == N.MANAGER_KEY_NOT_OBSERVED
        assert [len(s["assets"]) for s in ev["sides"]] == [len(s) for s in obs["sides"]]
        assert all(
            a == {"senderSideIndex": None, "pickOriginRosterSlot": None}
            for s in ev["sides"]
            for a in s["assets"]
        )

    def test_unparseable_fetch_time_is_unknown_not_the_trade_date(self):
        obs = N.normalize_ktc_row(_raw(ktc_row(1, [11], [12]), fetched=None), IDENT, ctx())
        assert obs["collectedAt"] is None
        assert obs["collectedAtBasis"] == N.COLLECTED_BASIS_UNKNOWN


class TestSleeperObservationEvidence:
    def test_collection_clock_is_ingest_time_first_and_complete(self, intel, monkeypatch):
        events = _trade_events()
        _ingest_at(intel, events[:4], 1_791_000_000_000, monkeypatch)
        _ingest_at(intel, events[4:], 1_791_086_400_000, monkeypatch)  # +1 day
        obs = _sleeper_obs(intel)[0][0]
        assert obs["observationChannel"] == "sleeper_observed"
        assert obs["firstCollectedAt"] == N._iso_from_ms(1_791_000_000_000)
        # The record was complete only once its last movement landed.
        assert obs["collectedAt"] == N._iso_from_ms(1_791_086_400_000)
        assert obs["collectedAtBasis"] == N.COLLECTED_BASIS_SLEEPER

    def test_sender_attribution_and_pick_origin(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        obs = _sleeper_obs(intel)[0][0]
        ev = obs["sideEvidence"]
        assert ev["attribution"] == N.SIDE_ATTRIBUTION_RECEIVED
        # Rosters sort "1", "2": side 0 received the edge from side 1, side 1
        # received the receiver and the 2027 1st (origin roster 3) from side 0.
        got = [
            [
                (a["canonicalId"], e["senderSideIndex"], e["pickOriginRosterSlot"])
                for a, e in zip(side, ev_side["assets"])
            ]
            for side, ev_side in zip(obs["sides"], ev["sides"])
        ]
        assert got == [
            [("player:2001", 1, None)],
            [("player:1001", 0, None), ("mpick:2027:r1", 0, "3")],
        ]

    def test_missing_drop_leaves_sender_unknown(self, intel):
        events = [
            e for e in _trade_events() if not (e["action"] == "drop" and e["assetId"] == "1001")
        ]
        ledger.ingest_events(events, path=intel)
        obs = _sleeper_obs(intel)[0][0]
        senders = {
            a["canonicalId"]: e["senderSideIndex"]
            for side, ev_side in zip(obs["sides"], obs["sideEvidence"]["sides"])
            for a, e in zip(side, ev_side["assets"])
        }
        assert senders["player:1001"] is None
        assert senders["player:2001"] == 1

    def test_three_team_trade_senders_recovered(self, intel):
        events = [
            _ev("T3", 1, "add", "1001"),
            _ev("T3", 2, "drop", "1001"),
            _ev("T3", 2, "add", "1002"),
            _ev("T3", 3, "drop", "1002"),
            _ev("T3", 3, "add", "1003"),
            _ev("T3", 1, "drop", "1003"),
        ]
        ledger.ingest_events(events, path=intel)
        obs = _sleeper_obs(intel)[0][0]
        assert obs["teamCount"] == 3
        senders = [
            [e["senderSideIndex"] for e in s["assets"]] for s in obs["sideEvidence"]["sides"]
        ]
        assert senders == [[1], [2], [0]]

    def test_collection_path_names_the_crawl(self, intel):
        ledger.ingest_events(_trade_events("T1", "L-A") + _trade_events("T2", "L-B"), path=intel)
        conn = ledger.connect(intel)
        conn.execute("INSERT INTO sharp_league_fetch (league_id) VALUES ('L-A')")
        conn.commit()
        conn.close()
        rows, status = _sleeper_obs(intel)
        paths = {o["hostLeagueId"]: o["collectionPath"] for o in rows}
        assert paths == {"L-A": N.COLLECTION_PATH_SHARP, "L-B": N.COLLECTION_PATH_INSIDER}
        assert status["tradesByCollectionPath"] == {
            N.COLLECTION_PATH_INSIDER: 1,
            N.COLLECTION_PATH_SHARP: 1,
        }

    def test_no_secret_no_manager_key(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        ev = _sleeper_obs(intel)[0][0]["sideEvidence"]
        assert ev["managerKeyState"] == N.MANAGER_KEY_NO_SECRET
        assert all(s["managerKey"] is None for s in ev["sides"])

    def test_manager_keys_are_keyed_hmacs(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        ev = _sleeper_obs(intel, side_key_secret=SECRET)[0][0]["sideEvidence"]
        keys = [s["managerKey"] for s in ev["sides"]]
        assert ev["managerKeyState"] == N.MANAGER_KEY_KEYED
        assert all(k and k.startswith("mk:") for k in keys) and keys[0] != keys[1]
        # Stable, and never a plain hash anyone holding the public id can redo.
        assert keys[0] == N.manager_key("user1", SECRET)
        assert "user1" not in keys[0]
        assert keys[0][3:] not in hashlib.sha256(b"user1").hexdigest()
        assert N.manager_key("user1", b"another-secret") != keys[0]


class TestOwnLeagueSideEvidence:
    def test_senders_origins_and_keys_from_the_acquisition_shape(self):
        teams = [
            (
                "1",
                {
                    "received": [{"assetId": "pick:dynasty_main:2027:r1:o4", "assetKind": "pick"}],
                    "sent": [{"assetId": "player:1001", "assetKind": "player"}],
                    "ownerUserId": "u1",
                },
            ),
            (
                "2",
                {
                    "received": [{"assetId": "player:1001", "assetKind": "player"}],
                    "sent": [{"assetId": "pick:dynasty_main:2027:r1:o4", "assetKind": "pick"}],
                    "ownerUserId": None,
                },
            ),
        ]
        ev = N._own_side_evidence(teams, SECRET)
        assert ev["sides"][0]["assets"] == [{"senderSideIndex": 1, "pickOriginRosterSlot": "4"}]
        assert ev["sides"][1]["assets"] == [{"senderSideIndex": 0, "pickOriginRosterSlot": None}]
        assert ev["sides"][0]["managerKey"] == N.manager_key("u1", SECRET)
        assert ev["sides"][1]["managerKey"] is None  # unattributed stays unattributed

    def test_collection_times_come_from_first_recorded_at(self, tmp_path):
        from src.acquisition import store
        from src.trade.market_trade_ledger import trade_collection_times

        path = tmp_path / "acq.sqlite"
        store.connect(path).close()
        conn = sqlite3.connect(path)
        cols = ", ".join(store._EVENT_COLS)
        for asset, recorded in (
            ("player:1", "2026-10-01T00:00:00+00:00"),
            ("player:2", "2026-10-03T00:00:00+00:00"),
        ):
            values = {c: None for c in store._EVENT_COLS} | {
                "league_key": "dynasty_main",
                "source_ref": "tx:9",
                "asset_id": asset,
                "asset_kind": "player",
                "event_type": "trade",
                "time_fidelity": "undated",
                "source": "test",
                "content_hash": asset,
            }
            conn.execute(
                f"INSERT INTO acquisition_events ({cols}, first_recorded_at, last_seen_at) "
                f"VALUES ({', '.join('?' * len(store._EVENT_COLS))}, ?, ?)",
                [values[c] for c in store._EVENT_COLS] + [recorded, "2026-10-19T00:00:00+00:00"],
            )
        conn.commit()
        conn.close()
        assert trade_collection_times("dynasty_main", path=path) == {
            "tx:9": {"first": "2026-10-01T00:00:00+00:00", "complete": "2026-10-03T00:00:00+00:00"}
        }


# ── group level (end to end over the synthetic lanes) ─────────────────────


def _groups_by_family(result):
    return {"+".join(g["sourceFamilies"]): g for g in result["grouping"].groups}


def test_cross_feed_overlap_and_collection_on_groups(env):  # noqa: F811
    _seed(env)
    result = _build(env)
    by = _groups_by_family(result)
    both = by["ktc_trade_database+sleeper_sharp_discovery"]
    assert both["observationChannels"] == ["ktc_database", "sleeper_observed"]
    assert both["crossFeed"]["ktcOverlap"] == G.KTC_OVERLAP_SAME_PROBABLE
    assert both["crossFeed"]["ktcLinked"] is True
    assert set(both["collectedAtByChannel"]) == {"ktc_database", "sleeper_observed"}
    assert both["collectedAt"] == min(
        both["collectedAtByChannel"].values(), key=lambda v: G._parse_ts(v)
    )
    # The other KTC trade (MFL) and the offense-only Sleeper trade.
    others = [g for g in result["grouping"].groups if g is not both]
    states = sorted(g["crossFeed"]["ktcOverlap"] for g in others)
    assert states == sorted([G.KTC_OVERLAP_KTC_ONLY, G.KTC_OVERLAP_NONE_DETECTED])
    for g in result["grouping"].groups:
        assert g["crossFeed"]["overlapClusterId"].startswith("ocluster:")
        assert "_root" not in g
        assert len(g["sideEvidence"]["sides"]) == len(g["sides"])

    measured = R.coverage_report(result)["crossFeedOverlap"]
    assert measured["sleeperObservedUnderlyingTrades"] == 2
    assert measured["ktcDatabaseUnderlyingTrades"] == 2
    s = measured["sleeperObservedAlsoInKtcDatabase"]
    assert (s["confirmed"], s["probable"], s["possible"]) == (0, 1, 0)
    assert (s["shareLowerBound"], s["sharePointEstimate"], s["shareUpperBound"]) == (0.0, 0.5, 0.5)
    coll = R.coverage_report(result)["collection"]
    assert coll["sleeper_observed"]["collectedAtKnown"] == coll["sleeper_observed"]["observations"]
    assert coll["ktc_database"]["collectedAtUnknown"] == 0


def test_possible_overlap_shares_one_cluster_and_is_flagged():
    def obs(oid, family, lid, sides, *, tx=None):
        return {
            "observationId": oid,
            "sourceFamily": family,
            "sourceNativeId": oid,
            "host": "sleeper",
            "hostLeagueId": lid,
            "hostTxId": tx,
            "occurredDate": "2026-10-01",
            "teamCount": 2,
            "sides": sides,
            "caveats": [],
        }

    a = {"kind": "player", "canonicalId": "player:1", "matchKey": "player:1"}
    b = {"kind": "player", "canonicalId": "player:2", "matchKey": "player:2"}
    u = {"kind": "unresolved", "canonicalId": None, "matchKey": "unresolved:x"}
    res = G.group_observations(
        [
            obs("k1", "ktc_trade_database", "L1", [[a], [u]]),
            obs("s1", "sleeper_sharp_discovery", "L1", [[a], [b]], tx="T1"),
        ]
    )
    assert [g["dedupeState"] for g in res.groups] == ["POSSIBLE_OVERLAP", "POSSIBLE_OVERLAP"]
    assert {g["crossFeed"]["ktcOverlap"] for g in res.groups} == {G.KTC_OVERLAP_POSSIBLE}
    assert len({g["crossFeed"]["overlapClusterId"] for g in res.groups}) == 1
    m = G.cross_feed_overlap(res.groups)["sleeperObservedAlsoInKtcDatabase"]
    assert (m["shareLowerBound"], m["sharePointEstimate"], m["shareUpperBound"]) == (0.0, 0.0, 1.0)


def test_empty_population_shares_are_none_not_zero():
    m = G.cross_feed_overlap([])
    assert m["sleeperObservedAlsoInKtcDatabase"]["sharePointEstimate"] is None


# ── G9: roster exclusivity ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("rpp", "state"),
    [
        (1, "exclusive"),
        ("1", "exclusive"),
        (2, "multi_copy"),
        (4, "multi_copy"),
        (None, "unknown"),
        (0, "unknown"),
        ("x", "unknown"),
    ],
)
def test_shared_exclusivity_rule_fails_closed(rpp, state):
    assert fc.roster_exclusivity(rpp) == state


def test_trade_format_exclusivity_reads_the_shared_rule():
    mfl = F.format_from_ktc_settings(ktc_settings("99", platform="mfl") | {"rostersPerPlayer": 3})
    assert F.roster_exclusivity(mfl, host="mfl") == {
        "state": "multi_copy",
        "basis": F.EXCLUSIVITY_BASIS_KTC_VENDOR,
    }
    unstated = dict(ktc_settings("99", platform="mfl"))
    unstated.pop("rostersPerPlayer")
    assert (
        F.roster_exclusivity(F.format_from_ktc_settings(unstated), host="mfl")["state"] == "unknown"
    )
    assert F.roster_exclusivity(F.TradeMarketFormat(source=F.SOURCE_UNKNOWN), host="sleeper") == {
        "state": "exclusive",
        "basis": F.EXCLUSIVITY_BASIS_SLEEPER_PLATFORM,
    }
    assert F.roster_exclusivity(None)["state"] == "unknown"


def test_faab_classify_is_not_migrated_yet():
    """Pinned so the follow-up is deliberate: FAAB ``classify`` still treats a
    non-positive ``rostersPerPlayer`` as exclusive (served behaviour)."""
    tgt = fc.TargetFormat(superflex=True, tep=False, teams=12, is_2te=False)
    src = fc.SourceFormat(
        superflex=True, tep_level=0, teams=12, rosters_per_player=0, original_budget=100
    )
    reasons = fc.classify(src, tgt).reasons
    assert "multi_copy_league" not in reasons and "roster_exclusivity_unknown" not in reasons


# ── maturity hook ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("n", "certainty", "cohort"),
    [
        (3, "exact", E.COHORT_A),
        (5, "exact", E.COHORT_A),
        (2, "exact", E.COHORT_B),
        (1, "exact", E.COHORT_BELOW_TWO),
        (0, "exact", E.COHORT_BELOW_TWO),
        (3, "lower_bound", E.COHORT_A),
        (2, "lower_bound", E.COHORT_B_PLUS_UNRESOLVED),
        (1, "lower_bound", E.COHORT_UNKNOWN),
        (None, "exact", E.COHORT_UNKNOWN),
        (True, "exact", E.COHORT_UNKNOWN),
        (-1, "exact", E.COHORT_UNKNOWN),
        (4, "unknown", E.COHORT_UNKNOWN),
    ],
)
def test_maturity_cohort_fails_closed(n, certainty, cohort):
    assert E.maturity_cohort(n, certainty) == cohort


def test_without_a_resolver_both_readings_are_unknown():
    groups = [{"underlyingTradeId": "u1"}]
    R.attach_league_maturity(groups, None)
    lm = groups[0]["leagueMaturity"]
    assert lm["state"] == R.MATURITY_NOT_RESOLVED and lm["reason"] == R.MATURITY_NO_RESOLVER
    for reading in ("pointInTime", "asOfBuild"):
        assert lm[reading] == {
            "completedSeasons": None,
            "certainty": "unknown",
            "cohort": "unknown",
        }


def test_resolver_readings_are_kept_separately_and_validated():
    def resolver(g):
        return {
            "pointInTime": {"completedSeasons": 2, "certainty": "exact"},
            "asOfBuild": {"completedSeasons": 3, "certainty": "exact"},
            "lineageId": "lineage:synthetic",
            "basis": "previous_league_id_chain",
        }

    groups = [{"underlyingTradeId": "u1"}]
    R.attach_league_maturity(groups, resolver)
    lm = groups[0]["leagueMaturity"]
    assert lm["state"] == R.MATURITY_RESOLVED
    assert lm["pointInTime"]["cohort"] == E.COHORT_B
    assert lm["asOfBuild"]["cohort"] == E.COHORT_A
    assert E.estimator_evidence(groups[0])["maturityCohort"] == {
        "pointInTime": E.COHORT_B,
        "asOfBuild": E.COHORT_A,
    }

    def bad(g):
        return {"pointInTime": {"completedSeasons": "3", "certainty": "exact"}}

    R.attach_league_maturity(groups, bad)
    assert groups[0]["leagueMaturity"]["pointInTime"]["cohort"] == E.COHORT_UNKNOWN


def test_resolver_failure_stays_local_and_names_no_data():
    def boom(g):
        raise LookupError("league L-SYN-SECRET missing")

    groups = [{"underlyingTradeId": "u1"}, {"underlyingTradeId": "u2"}]
    R.attach_league_maturity(groups, boom)
    assert {g["leagueMaturity"]["state"] for g in groups} == {R.MATURITY_RESOLVER_ERROR}
    assert groups[0]["leagueMaturity"]["reason"] == "LookupError"  # never the message


# ── estimator evidence flags ──────────────────────────────────────────────


def test_estimator_flags_end_to_end(env):  # noqa: F811
    _seed(env)
    result = _build(env)
    by = _groups_by_family(result)
    sleeper_only = next(
        g for g in result["grouping"].groups if g["sourceFamilies"] == ["sleeper_sharp_discovery"]
    )
    e = E.estimator_evidence(sleeper_only)
    assert sleeper_only["rosterExclusivity"]["state"] == "exclusive"
    # The seed's offense-league copy drops the edge, so one roster only gave.
    assert e["hardExclusions"] == ["one_side_empty"]
    assert "faab_unobserved" in e["populationFlags"]
    assert "insider_pool_crawl" in e["populationFlags"]  # no Sharp cursor row seeded
    assert "ktc_database_channel" not in e["populationFlags"]
    assert e["maturityCohort"] == {"pointInTime": "unknown", "asOfBuild": "unknown"}
    linked = E.estimator_evidence(by["ktc_trade_database+sleeper_sharp_discovery"])
    assert "ktc_database_channel" in linked["populationFlags"]

    summary = R.evaluation_report(result, contract=None, board_date=None)["estimatorEvidence"]
    assert summary["underlyingTrades"] == len(result["grouping"].groups)
    assert summary["anyHardExclusion"] + summary["representable"] == summary["underlyingTrades"]


def _trade(**over):
    base = {
        "sides": [
            [{"kind": "player", "canonicalId": "player:1", "position": "WR"}],
            [{"kind": "player", "canonicalId": "player:2", "position": "RB"}],
        ],
        "dedupeState": "CONFIRMED_UNIQUE",
        "marketFormat": {"general": {"dynastyState": "dynasty"}, "offense": {"superflex": True}},
        "rosterExclusivity": {"state": "exclusive"},
        "occurredDate": "2026-10-01",
        "collectedAt": "2026-10-02T00:00:00+00:00",
        "representativeCollectedAt": "2026-10-02T00:00:00+00:00",
        "observationChannels": ["sleeper_observed"],
        "sideEvidence": {"managerKeyState": "keyed", "sides": []},
    }
    return base | over


@pytest.mark.parametrize(
    ("over", "reason"),
    [
        ({"rosterExclusivity": {"state": "multi_copy"}}, "multi_copy_league"),
        ({"rosterExclusivity": None}, "roster_exclusivity_unknown"),
        (
            {
                "marketFormat": {
                    "general": {"dynastyState": "redraft"},
                    "offense": {"superflex": True},
                }
            },
            "not_dynasty",
        ),
        ({"marketFormat": {"general": {}, "offense": {"superflex": True}}}, "dynasty_unverified"),
        (
            {"marketFormat": {"general": {"dynastyState": "dynasty"}, "offense": {}}},
            "qb_format_unknown",
        ),
        ({"occurredDate": None}, "undated_trade"),
        ({"collectedAt": None, "representativeCollectedAt": None}, "collected_at_unknown"),
        (
            {
                "sides": [
                    [{"kind": "faab", "canonicalId": None, "faabAmount": 5.0}],
                    [{"kind": "player", "canonicalId": "player:2"}],
                ]
            },
            "faab_unrepresentable",
        ),
    ],
)
def test_each_hard_exclusion(over, reason):
    assert reason in E.estimator_evidence(_trade(**over))["hardExclusions"]


def test_clean_trade_has_no_hard_exclusion_and_fit_suitability_is_unchanged():
    t = _trade()
    assert E.estimator_evidence(t)["hardExclusions"] == []
    topo = E.classify_topology(t)
    assert E.fit_suitability(t, topo) == {"fit": "clean_1_for_1", "reasons": []}


def test_summary_separates_overlapping_and_sole_exclusion_losses():
    trades = [
        _trade(),
        _trade(rosterExclusivity={"state": "multi_copy"}),
        _trade(rosterExclusivity={"state": "multi_copy"}, occurredDate=None),
    ]
    s = E.summarize_estimator_evidence(trades)
    assert s["representable"] == 1 and s["anyHardExclusion"] == 2
    assert s["lostToEachHardExclusion"] == {"multi_copy_league": 2, "undated_trade": 1}
    # Relaxing the multi-copy rule alone recovers one trade, not two.
    assert s["lostOnlyToHardExclusion"] == {"multi_copy_league": 1}


def test_multi_team_needs_every_sender():
    sides = [[{"kind": "player", "canonicalId": f"player:{i}"}] for i in (1, 2, 3)]
    known = {
        "managerKeyState": "keyed",
        "sides": [{"assets": [{"senderSideIndex": j}]} for j in (1, 2, 0)],
    }
    partial = {
        "managerKeyState": "keyed",
        "sides": [{"assets": [{"senderSideIndex": j}]} for j in (1, None, 0)],
    }
    assert (
        "multi_team_senders_unattributed"
        not in E.estimator_evidence(_trade(sides=sides, sideEvidence=known))["hardExclusions"]
    )
    assert (
        "multi_team_senders_unattributed"
        in E.estimator_evidence(_trade(sides=sides, sideEvidence=partial))["hardExclusions"]
    )


# ── consumers: identical output with or without the new fields ───────────

#: Every group key this unit added.  A record stripped of them is the
#: pre-P2 record shape.
P2_GROUP_KEYS = (
    "observationChannels",
    "collectedAt",
    "firstCollectedAt",
    "representativeCollectedAt",
    "collectedAtByChannel",
    "collectedAtUnknownMembers",
    "timeFidelity",
    "collectionPaths",
    "sideEvidence",
    "crossFeed",
    "rosterExclusivity",
    "leagueMaturity",
)


def _strip(groups):
    return [{k: v for k, v in g.items() if k not in P2_GROUP_KEYS} for g in groups]


def _privacy_all_visible(groups):
    cohort = {}
    for g in groups:
        for m in g["members"]:
            if m.startswith("sleeper_sharp_discovery:"):
                _, lid, tx = m.split(":")[:3]
                cohort[(lid, tx)] = True
    return lambda: ref.PrivacyContext(
        registry_league_ids=frozenset(),
        chain_resolved=True,
        sharp_trade_has_cohort_manager=lambda lid, tx: cohort.get((lid, tx)),
    )


def _verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_signals_onbox_p2", REPO / "scripts" / "verify_signals_onbox.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_ledger_consumer_is_identical_with_or_without_evidence(env, tmp_path):  # noqa: F811
    _seed(env)
    result = _build(env, side_key_secret=SECRET)
    groups = result["grouping"].groups
    assert all(k in groups[0] for k in P2_GROUP_KEYS), "the build stamps every new field"
    with_root, without_root = tmp_path / "with", tmp_path / "without"
    for root, gs in ((with_root, groups), (without_root, _strip(groups))):
        R.persist_canonical_ledger(
            gs,
            root=root,
            built_at="2026-10-08T08:52:00Z",
            extra_meta={"targetLeague": "dynasty_main"},
        )
    # The new fields really are in the persisted record of one ledger only.
    rec = json.loads(
        sqlite3.connect(with_root / R.LEDGER_FILENAME)
        .execute("SELECT record_json FROM underlying_trades LIMIT 1")
        .fetchone()[0]
    )
    assert "crossFeed" in rec and "sideEvidence" in rec

    privacy = _privacy_all_visible(groups)
    names = {
        "1001": {"name": "Alpha Receiver", "position": "WR"},
        "2001": {"name": "Echo Edge", "position": "DL"},
    }
    today = date(2026, 10, 8)

    def run_all(root):
        return {
            "tc07": ref.reference_trades(
                "dynasty_main",
                player_ids=["1001", "2001", "1003"],
                names=names,
                today=today,
                root=root,
                privacy=privacy,
            ),
            "tc08": db.browse_trades(
                "dynasty_main",
                db.TradeFilters(),
                names=names,
                today=today,
                root=root,
                privacy=privacy,
            ),
            "tc09": ct.comparable_trades(
                "dynasty_main",
                side_a=ct.SideRefs(player_ids=["1001"]),
                side_b=ct.SideRefs(player_ids=["2001"]),
                names=names,
                today=today,
                root=root,
                privacy=privacy,
            ),
        }

    a, b = run_all(with_root), run_all(without_root)
    assert a["tc07"]["state"] == "ok" and a["tc07"]["trades"], "the comparison is not vacuous"
    assert a["tc08"]["trades"] and a["tc09"]["state"] == "ok"
    assert a == b

    # Signals on-box verifier (§10.7 completed-trade check) reads record_json.
    verifier = _verifier()
    contract = {
        "playersArray": [{"displayName": "Echo Edge", "playerId": "2001", "rankDerivedValue": 3000}]
    }
    out = {}
    for label, root in (("with", with_root), ("without", without_root)):
        app = tmp_path / f"app_{label}"
        (app / "data" / "market_trades").mkdir(parents=True)
        (app / "data" / "market_trades" / R.LEDGER_FILENAME).write_bytes(
            (root / R.LEDGER_FILENAME).read_bytes()
        )
        out[label] = verifier.trade_check(app, contract, contract)
    assert out["with"]["available"] and out["with"]["idpTradesByDisposition"]
    assert out["with"] == out["without"]


def test_projection_never_exposes_the_new_fields(env):  # noqa: F811
    """TC-07 projects a fixed field set: no manager key, roster slot, cluster
    id or collection clock can reach a viewer through it."""
    _seed(env)
    groups = _build(env, side_key_secret=SECRET)["grouping"].groups
    q = ref.build_query("dynasty_main", player_ids=["1001"])
    for g in groups:
        rec = json.loads(json.dumps(R._jsonable_group(g), default=str))
        row = json.dumps(ref.project_trade(rec, None, q, "dynasty_main", {}, own_this_league=False))
        for needle in (
            "mk:",
            "managerKey",
            "senderSideIndex",
            "pickOriginRosterSlot",
            "ocluster:",
            "collectedAt",
            "leagueMaturity",
        ):
            assert needle not in row


#: Modules that must never import the ledger family: Trade History grades
#: league trades without it, and the public League Hub (where the Brisket
#: Trade Advisor lands) must not reach outside-league evidence.
_LEDGER_FAMILY = (
    "src.trade.market_trade_archive",
    "src.trade.market_trade_normalize",
    "src.trade.market_trade_groups",
    "src.trade.market_trade_format",
    "src.trade.market_trade_eval",
    "src.trade.market_trade_report",
    "src.trade.market_trade_reference",
    "src.trade.market_trade_database",
    "src.trade.market_trade_ledger",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def test_trade_history_and_public_league_cannot_reach_the_ledger():
    files = sorted((REPO / "src" / "public_league").rglob("*.py"))
    assert any(f.name == "trade_grading.py" for f in files)
    for f in files:
        hit = _imports(f) & set(_LEDGER_FAMILY)
        assert not hit, f"{f.relative_to(REPO)} imports {sorted(hit)}"


def _cli():
    spec = importlib.util.spec_from_file_location(
        "market_trade_ledger_cli_p2", REPO / "scripts" / "market_trade_ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cli_side_key_secret_must_be_owner_only_and_long(tmp_path):
    cli = _cli()
    f = tmp_path / "secret"
    f.write_bytes(b"x" * 40)
    f.chmod(0o644)
    with pytest.raises(PermissionError):
        cli.read_side_key_secret(f)
    f.chmod(0o600)
    assert cli.read_side_key_secret(f) == b"x" * 40
    f.write_bytes(b"short")
    with pytest.raises(ValueError):
        cli.read_side_key_secret(f)
