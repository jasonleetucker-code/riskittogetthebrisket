"""Own-league historical trade and draft census (research script) — pinned on a
recorded SYNTHETIC bundle (``tests/fixtures/own_league_census/``).  No network:
every Sleeper fetcher the collector touches is replaced by a fixture reader.

What is pinned:

* the chain walk and its stop conditions, and that an unverified chain or a
  failed week stops the run before any committed output is written;
* week pagination covers week 0, weeks 1-18 and the 19-25 probe;
* dedupe by ``transaction_id`` across weeks, and the status filter;
* pick-transfer replay against the ``/traded_picks`` ownership fold;
* DL / LB / DB classification with the as-of (drafted) position;
* the historical cutoff: a value observed after the trade instant is never
  selected, even on the same day; ``before_history_boundary`` labelling;
* missing is missing (``None`` + a reason), never 0;
* a season-format change (10 vs 12 teams) is reported;
* the committed outputs carry no Sleeper-id-shaped digit run and no member
  name, and the private output path is gitignored.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import own_league_history_census as C
from src.history import store
from src.public_league import sleeper_client as sc

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "fixtures" / "own_league_census" / "synthetic_bundle.json"
L25, L26 = "100000000000000025", "100000000000000026"


@pytest.fixture()
def bundle() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _obs(key, cls, day, at, value, source="idpTradeCalc"):
    return {
        "asset_key": key,
        "asset_class": cls,
        "lane": store.LANE_SOURCE,
        "source_key": source,
        "observed_date": day,
        "observed_at": at,
        "observed_at_zone": "utc",
        "value": value,
        "origin": "test:census",
        "display_name": key,
        "position": None,
        "player_id": key.split(":", 1)[1],
        "scope": None,
        "pipeline_version": None,
        "rank": None,
        "tier": None,
        "confidence": None,
    }


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    """The 2026-08-01T12:01Z trade (2003 <-> 2004): a prior-day value, a
    same-day value scraped AFTER the trade, and a next-day value."""
    path = tmp_path / "ledger.sqlite"
    rows = []
    for key, prior in (("player:2003", 3000.0), ("player:2004", 2800.0)):
        rows.append(_obs(key, "idp", "2026-07-31", "2026-07-31T20:00:00+00:00", prior))
        rows.append(_obs(key, "idp", "2026-08-01", "2026-08-01T18:00:00+00:00", 9999.0))
        rows.append(_obs(key, "idp", "2026-08-02", "2026-08-02T18:00:00+00:00", 9999.0))
    out = store.write_observations(rows, path=path)
    assert out["written"] == 6 and not out["rejected"]
    return path


def _by_tx(private: dict) -> dict:
    return {r["txid"]: r for r in private["trades"]}


# ── collection: chain walk, stop conditions, weeks ───────────────────────


def _patch_sleeper(monkeypatch, bundle, *, fail_week=None, calls=None):
    seasons = bundle["seasons"]
    picks = {did: p for s in seasons.values() for did, p in s["draftPicks"].items()}

    def rec(name, *args):
        if calls is not None:
            calls.append((name, *args))

    def league(lid):
        rec("league", lid)
        s = seasons.get(str(lid))
        return (sc.FETCH_OK, s["league"]) if s else (sc.FETCH_NOT_FOUND, None)

    def tx(lid, week):
        rec("tx", lid, week)
        if fail_week is not None and week == fail_week:
            return sc.FETCH_ERROR, None
        return sc.FETCH_OK, seasons[lid]["transactions"].get(str(week), [])

    monkeypatch.setattr(sc, "fetch_league_classified", league)
    monkeypatch.setattr(sc, "fetch_transactions_classified", tx)
    monkeypatch.setattr(
        sc, "fetch_league_users_classified", lambda lid: (sc.FETCH_OK, seasons[lid]["users"])
    )
    monkeypatch.setattr(
        sc, "fetch_rosters_classified", lambda lid: (sc.FETCH_OK, seasons[lid]["rosters"])
    )
    monkeypatch.setattr(
        sc, "fetch_traded_picks_classified", lambda lid: (sc.FETCH_OK, seasons[lid]["tradedPicks"])
    )
    monkeypatch.setattr(
        sc, "fetch_drafts_classified", lambda lid: (sc.FETCH_OK, seasons[lid]["drafts"])
    )
    monkeypatch.setattr(sc, "fetch_draft_picks_classified", lambda did: (sc.FETCH_OK, picks[did]))


def test_collect_walks_chain_to_terminator_and_every_week(monkeypatch, bundle):
    calls: list = []
    _patch_sleeper(monkeypatch, bundle, calls=calls)
    got = C.collect(L26, C.Fetcher(pace=0))
    assert got["chainOrder"] == [L26, L25]
    assert got["chainCoverage"]["state"] == sc.CHAIN_COMPLETE
    for lid in (L26, L25):
        weeks = sorted(c[2] for c in calls if c[0] == "tx" and c[1] == lid)
        assert weeks == list(range(0, 26))  # week 0, 1-18 and the 19-25 probe
    assert got["fetch"]["failures"] == []


def test_chain_stops_at_non_dynasty_predecessor(monkeypatch, bundle):
    b = copy.deepcopy(bundle)
    b["seasons"][L25]["league"]["settings"]["type"] = 0
    _patch_sleeper(monkeypatch, b)
    got = C.collect(L26, C.Fetcher(pace=0))
    assert got["chainOrder"] == [L26]
    assert got["chainCoverage"]["state"] == sc.CHAIN_NON_DYNASTY


def test_chain_unverified_when_predecessor_unreadable(monkeypatch, bundle):
    b = copy.deepcopy(bundle)
    b["seasons"][L26]["league"]["previous_league_id"] = "999999999999999999"
    _patch_sleeper(monkeypatch, b)
    got = C.collect(L26, C.Fetcher(pace=0))
    assert got["chainCoverage"]["state"] == sc.CHAIN_UNVERIFIED


def test_failed_week_is_recorded_not_read_as_empty(monkeypatch, bundle):
    _patch_sleeper(monkeypatch, bundle, fail_week=3)
    got = C.collect(L26, C.Fetcher(pace=0, retries=0))
    assert got["seasons"][L25]["transactions"]["3"] is None
    assert {f["call"] for f in got["fetch"]["failures"]} == {"transactions:3"}
    txs, stats = C.season_transactions(got["seasons"][L25])
    assert 3 in stats["weeksFailed"]


def test_rate_limit_is_retried_with_backoff():
    sleeps: list[float] = []
    answers = iter([(sc.FETCH_RATE_LIMITED, None), (sc.FETCH_OK, [1])])
    f = C.Fetcher(pace=0.2, retries=3, sleep=sleeps.append)
    assert f("x", lambda: next(answers)) == [1]
    assert sleeps == [0.2, 2.0, 0.2]
    assert f.failures == []


def test_incomplete_collection_writes_no_committed_output(tmp_path, bundle):
    b = copy.deepcopy(bundle)
    b["fetch"]["failures"] = [{"call": "transactions:4", "args": [], "kind": "error"}]
    src = tmp_path / "bundle.json"
    src.write_text(json.dumps(b), encoding="utf-8")
    md, js = tmp_path / "c.md", tmp_path / "c.json"
    rc = C.main(
        ["--bundle", str(src), "--private-dir", str(tmp_path / "p"), "--doc-md", str(md)]
        + ["--doc-json", str(js), "--reconcile-archive", str(tmp_path / "none.zip")]
    )
    assert rc == C.EXIT_INCOMPLETE
    assert not md.exists() and not js.exists()


# ── dedupe, status, legs, picks ──────────────────────────────────────────


def test_dedupe_across_weeks_and_status_filter(bundle):
    agg, private = C.build_census(bundle, ledger=None)
    txs = _by_tx(private)
    # tx ...10 is listed under weeks 1 and 2; counted once, at its first week.
    assert sorted(txs) == [
        "300000000000000001",
        "300000000000000003",
        "300000000000000010",
        "300000000000000011",
        "300000000000000012",
    ]
    assert txs["300000000000000010"]["week"] == 1
    assert agg["transactions"]["2026"]["duplicatesAcrossWeeks"] == 1
    # the failed trade is excluded and counted
    assert agg["transactions"]["2025"]["tradeStatuses"] == {"complete": 2, "failed": 1}
    assert "300000000000000002" not in txs
    assert agg["transactions"]["2025"]["week0Transactions"] == 1
    assert agg["validation"]["groupingStates"] == {"CONFIRMED_UNIQUE": 5}
    assert agg["deliverableA"]["completedTradesBySeason"] == {"2025": 2, "2026": 3}


def test_duplicate_id_across_seasons_is_a_finding(bundle):
    b = copy.deepcopy(bundle)
    b["seasons"][L26]["transactions"]["6"] = [
        copy.deepcopy(b["seasons"][L25]["transactions"]["1"][0])
    ]
    agg, _ = C.build_census(b, ledger=None)
    assert agg["validation"]["duplicateTransactionIdsAcrossSeasons"] == 1
    assert agg["deliverableA"]["completedTradesTotal"] == 5


def test_leg_findings():
    t = {
        "roster_ids": [1, 2],
        "adds": {"10": 2, "11": 3},
        "drops": {"10": 1, "12": 2},
        "draft_picks": [{"season": "2027", "round": 1, "owner_id": 1, "previous_owner_id": 1}],
        "waiver_budget": [{"amount": 0, "sender": 2, "receiver": 1}],
    }
    got = C.leg_findings(t)
    assert "add_roster_not_party" in got and "add_without_sender" in got
    assert "released_in_trade" in got and "pick_self_transfer" in got
    assert "faab_amount_missing_or_zero" in got
    clean = {"roster_ids": [1, 2], "adds": {"10": 2}, "drops": {"10": 1}}
    assert C.leg_findings({**clean, "draft_picks": [], "waiver_budget": []}) == [
        "party_receives_nothing"
    ]


def test_pick_replay_matches_ownership_fold_and_flags_wrong_sender(bundle):
    agg, private = C.build_census(bundle, ledger=None)
    pr = agg["validation"]["pickReplay"]
    assert pr["transfersReplayed"] == 3
    assert pr["senderMismatches"] == 1  # tx ...12 states sender 9, origin 2 holds it
    assert pr["senderMismatchesByPickSeasonRound"] == {"2027-r3": 1}
    assert [c["mismatches"] for c in pr["checkpoints"]] == [0, 0]
    # A host row the replay cannot reproduce is a checkpoint mismatch.
    b = copy.deepcopy(bundle)
    b["seasons"][L26]["tradedPicks"].append(
        {"season": "2027", "round": 1, "roster_id": 5, "owner_id": 6, "previous_owner_id": 5}
    )
    agg2, _ = C.build_census(b, ledger=None)
    assert agg2["validation"]["pickReplay"]["checkpoints"][1]["mismatches"] == 1
    assert "pick_ownership_mismatch_season_2026:1" in agg2["validation"]["findings"]


# ── classification ───────────────────────────────────────────────────────


def test_idp_family_classification_uses_as_of_position(bundle):
    agg, private = C.build_census(bundle, ledger=None)
    txs = _by_tx(private)
    swap = txs["300000000000000010"]
    fam = {a["playerId"]: (a["family"], a["positionBasis"]) for a in swap["assets"]}
    # 2004 is a safety today but was drafted as an LB in 2025: the trade
    # (2026) reads the drafted position, not today's.
    assert fam["2004"] == ("LB", "chain_draft_metadata_2025")
    assert fam["2003"] == ("DB", "chain_draft_metadata_2026")
    assert swap["classes"]["idpForIdp"] and swap["classes"]["oneForOne"]
    first = txs["300000000000000001"]["classes"]
    assert first["offenseForIdp"] and first["idpFamilies"] == ["DL"]
    A = agg["deliverableA"]
    assert A["idpTradesByFamily"]["DL"]["total"] == 2
    assert A["idpTradesByFamily"]["LB"]["total"] == 2
    assert A["idpTradesByFamily"]["DB"]["total"] == 1
    assert A["multiTeamTrades"]["total"] == 1
    assert A["tradesWithFaab"]["total"] == 1


def test_draft_census_auction_amounts_and_snake_none(bundle):
    agg, _ = C.build_census(bundle, ledger=None)
    d25, d26 = agg["draftCensus"]["drafts"]
    assert d25["auction"] == {"amountStates": {"not_applicable_non_auction": 4}}
    assert d26["auction"]["amountStates"] == {"recorded": 2, "missing": 1}
    assert d26["auction"]["totalSpent"] == 52  # the missing amount is not $0
    assert d26["idpSelectionOrder"]["firstIdpPickNo"] == 1
    assert d25["kind"] == "rookie" and d26["kind"] == "rookie"


# ── prices: cutoff, boundary, missing ────────────────────────────────────


def test_value_after_trade_instant_is_never_selected(bundle, ledger):
    _, private = C.build_census(bundle, ledger=ledger)
    swap = _by_tx(private)["300000000000000010"]
    for a in swap["assets"]:
        p = a["prices"]["idptc"]
        assert p["fidelity"] == "nearest-prior"
        assert p["observedDate"] == "2026-07-31" and p["ageDays"] == 1
        assert p["value"] in (3000.0, 2800.0)  # never the 9999 seen later


def test_before_history_boundary_label(bundle, ledger):
    _, private = C.build_census(bundle, ledger=ledger)
    old = _by_tx(private)["300000000000000001"]
    for a in old["assets"]:
        for lane in ("canonical", "idptc", "ktc"):
            assert a["prices"][lane] == {
                "fidelity": "missing",
                "value": None,
                "reason": C.REASON_BOUNDARY,
            }


def test_missing_is_never_zero(bundle, ledger):
    agg, private = C.build_census(bundle, ledger=ledger)
    reasons = set()
    for r in private["trades"]:
        for a in r["assets"]:
            for p in (a.get("prices") or {}).values():
                if p["fidelity"] == "missing":
                    assert p["value"] is None
                    reasons.add(p["reason"])
                else:
                    assert p["value"] not in (None, 0)
    assert {C.REASON_NO_OBS, C.REASON_PICK, C.REASON_BOUNDARY} <= reasons
    # KTC has no IDP rows in this ledger; the swap stays unpriced there.
    assert agg["effectiveSample"]["allOneForOnePlayerSwapsWithIdptcBothAssets"] == 1
    assert agg["deliverableA"]["historicalValueCoverage"]["ktc"]["2026"]["exact"] == 0


def test_unresolved_player_is_unresolved_identity(bundle, ledger):
    b = copy.deepcopy(bundle)
    del b["players"]["1004"]
    agg, private = C.build_census(b, ledger=ledger)
    a = next(x for x in _by_tx(private)["300000000000000012"]["assets"] if x.get("playerId"))
    assert a["kind"] == "unresolved"
    assert a["prices"]["idptc"]["reason"] == C.REASON_UNRESOLVED
    assert "unresolved_player_ids:1" in agg["validation"]["findings"]


# ── format ───────────────────────────────────────────────────────────────


def test_season_format_change_is_reported(bundle):
    agg, _ = C.build_census(bundle, ledger=None)
    f25, f26 = agg["formatValidation"]["2025"], agg["formatValidation"]["2026"]
    assert "teamCount" in f25["differentAxes"]
    assert f25["differences"]["teamCount"] == {"source": 10, "target": 12}
    assert f26["allAxesMatchToday"]
    cov = agg["deliverableA"]["coverageAfterFormatValidation"]
    assert cov["tradesInSeasonsMatchingTodayOnEveryAxis"] == 3


# ── anonymization and privacy ────────────────────────────────────────────


def _run_main(tmp_path, bundle, ledger=None):
    src = tmp_path / "bundle.json"
    src.write_text(json.dumps(bundle), encoding="utf-8")
    md, js, priv = tmp_path / "c.md", tmp_path / "c.json", tmp_path / "private"
    argv = ["--bundle", str(src), "--private-dir", str(priv), "--doc-md", str(md)]
    argv += ["--doc-json", str(js), "--reconcile-archive", str(tmp_path / "none.zip")]
    if ledger:
        argv += ["--ledger", str(ledger)]
    return C.main(argv), md, js, priv


def test_committed_outputs_carry_no_ids_or_names(tmp_path, bundle, ledger):
    rc, md, js, priv = _run_main(tmp_path, bundle, ledger)
    assert rc == C.EXIT_FINDINGS  # the planted wrong-sender pick transfer
    text = md.read_text(encoding="utf-8") + js.read_text(encoding="utf-8")
    long_runs = set(re.findall(r"(?<![\d.])\d{9,}(?!\d)", text))
    assert long_runs <= {L25, L26}
    for s in bundle["seasons"].values():
        for u in s["users"]:
            assert u["user_id"] not in text
            assert u["display_name"] not in text
            assert u["metadata"]["team_name"] not in text
    for txid in ("300000000000000001", "300000000000000010", "400000000000000026"):
        assert txid not in text
    assert "T01" in text
    # ... while the private evidence keeps them.
    private = (priv / "census_private.json").read_text(encoding="utf-8")
    assert "300000000000000010" in private and "200000000000000005" in private


def test_scan_refuses_a_leaking_write(tmp_path, bundle, monkeypatch):
    real = C.render_markdown
    monkeypatch.setattr(C, "render_markdown", lambda agg: real(agg) + "\nSynthManager03\n")
    rc, md, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_BAD_INPUT
    assert not md.exists() and not js.exists()


def test_identifier_scan():
    leaks = C.identifier_leaks(
        "league 100000000000000026, user 200000000000000001, weight 0.0333333333333, Bob",
        allowed_ids=[L26],
        names=["Bob", "Al"],
    )
    assert leaks == ["200000000000000001", "name:Bob"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_private_output_path_is_gitignored():
    target = C.DEFAULT_PRIVATE_DIR / "census_private.json"
    rel = target.relative_to(REPO).as_posix()
    rc = subprocess.run(["git", "-C", str(REPO), "check-ignore", "-q", rel]).returncode
    assert rc == 0, f"{rel} must be gitignored"
    assert C.DEFAULT_DOC_MD.relative_to(REPO).as_posix().startswith("docs/")


def test_instant_is_utc_completion_time(bundle):
    _, private = C.build_census(bundle, ledger=None)
    r = _by_tx(private)["300000000000000010"]
    assert r["instantBasis"] == "status_updated"
    assert datetime.fromisoformat(r["instant"]) == datetime(2026, 8, 1, 12, 1, tzinfo=timezone.utc)
