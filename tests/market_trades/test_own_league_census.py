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
import itertools
import json
import re
import shutil
import statistics
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
    traded = {did: p for s in seasons.values() for did, p in s["draftTradedPicks"].items()}
    detail = {did: p for s in seasons.values() for did, p in s["draftDetail"].items()}
    monkeypatch.setattr(
        C, "fetch_draft_traded_picks_classified", lambda did: (sc.FETCH_OK, traded[did])
    )
    monkeypatch.setattr(C, "fetch_draft_detail_classified", lambda did: (sc.FETCH_OK, detail[did]))


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
    assert pr["senderMismatchesByDraftAndPickClass"] == {"future_class:2027-r3": 1}
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


#: A head SHA a reviewer's branch actually carried (bedea2fab...c68f1362637166f):
#: its decimal run 1362637166 made this test fail on that branch while PR CI,
#: which tests the merge-ref SHA instead, passed.  The middle is filler.
REVIEW_HEAD_SHA = "bedea2fab4d1e0a7bc39f5e28c68f1362637166f"


def _committed_digest_values(agg):
    """The digests the committed JSON itself carries -- ``inputs.codeSha`` and
    each season's ``formatFingerprint`` / ``scoringCardHash`` -- read from the
    written file, independently of the script's ``committed_digests``.  The
    ONLY values this test exempts; never a token for looking like a digest."""
    out = {(agg.get("inputs") or {}).get("codeSha")}
    for c in (agg.get("chain") or {}).get("seasons") or []:
        out |= {c.get("formatFingerprint"), c.get("scoringCardHash")}
    return {str(d) for d in out if d}


def _long_runs_outside_digests(text, digests):
    """Every 9+ digit run not glued to a digit or a period, except a run lying
    wholly INSIDE an occurrence of one of ``digests`` (an id glued to a digest
    runs past its span and is still reported)."""
    spans = [(m.start(), m.end()) for d in digests for m in re.finditer(re.escape(d), text)]
    return {
        m.group()
        for m in re.finditer(r"(?<![\d.])\d{9,}(?!\d)", text)
        if not any(lo <= m.start() and m.end() <= hi for lo, hi in spans)
    }


@pytest.mark.parametrize("head_sha", [None, REVIEW_HEAD_SHA], ids=["live_head", "review_head"])
def test_committed_outputs_carry_no_ids_or_names(tmp_path, bundle, ledger, monkeypatch, head_sha):
    if head_sha is not None:
        monkeypatch.setattr(C, "_code_sha", lambda: head_sha)
    rc, md, js, priv = _run_main(tmp_path, bundle, ledger)
    assert rc == C.EXIT_FINDINGS  # the planted wrong-sender pick transfer
    body_json = js.read_text(encoding="utf-8")
    text = md.read_text(encoding="utf-8") + body_json
    agg = json.loads(body_json)
    if head_sha is not None:
        assert agg["inputs"]["codeSha"] == head_sha
    # The exemption is exactly the committed digests -- the same set the
    # script's own write gate allowlisted -- so the scan cannot depend on
    # whichever commit happens to be checked out.
    digests = _committed_digest_values(agg)
    assert digests == set(C.committed_digests(agg))
    assert _long_runs_outside_digests(text, digests) <= {L25, L26}
    for s in bundle["seasons"].values():
        for u in s["users"]:
            assert u["user_id"] not in text
            assert u["display_name"] not in text
            assert u["metadata"]["team_name"] not in text
    for txid in ("300000000000000001", "300000000000000010", "400000000000000026"):
        assert txid not in text
    assert not C._TEAM_LABEL.search(text)  # no team label, not even T01
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


# ── review fixes: per-draft pick replay ──────────────────────────────────

D25, DSTART = "400000000000000025", "400000000000000027"


def _ms(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def _pick_trade(txid, at, rids, picks, status="complete"):
    return {
        "transaction_id": txid,
        "type": "trade",
        "status": status,
        "created": at - 60_000,
        "status_updated": at,
        "roster_ids": rids,
        "adds": None,
        "drops": None,
        "leg": 1,
        "draft_picks": [
            {
                "league_id": None,
                "season": str(s),
                "round": r,
                "roster_id": o,
                "previous_owner_id": p,
                "owner_id": n,
            }
            for s, r, o, p, n in picks
        ],
        "waiver_budget": [],
    }


@pytest.fixture()
def two_drafts(bundle) -> dict:
    """2025 runs TWO drafts under one season label: a 12-round startup
    (Apr 1-10) and the 3-round rookie draft (Apr 20-25), as the live 2024
    league did.  2025 round-2 origin-5 moves 5 -> 6 DURING the startup (a
    startup pick, consumed by the startup), then the rookie round-2 origin-5
    pick moves 5 -> 7 after it.  A season-only key merges the two."""
    b = copy.deepcopy(bundle)
    s = b["seasons"][L25]
    s["league"]["draft_id"] = D25
    rookie = s["drafts"][0]
    rookie["start_time"], rookie["last_picked"] = _ms(2025, 4, 20), _ms(2025, 4, 25)
    startup = copy.deepcopy(rookie)
    startup.update(
        draft_id=DSTART,
        type="snake",
        start_time=_ms(2025, 4, 1),
        last_picked=_ms(2025, 4, 10),
        settings={"player_type": 2, "rounds": 12, "teams": 10},
    )
    s["drafts"].append(startup)
    s["draftPicks"][DSTART] = []
    s["draftDetail"][DSTART] = {"slot_to_roster_id": {str(i): i for i in range(1, 11)}}
    s["draftTradedPicks"][DSTART] = [
        {"season": "2025", "round": 2, "roster_id": 5, "owner_id": 6, "previous_owner_id": 5},
        {"season": "2025", "round": 11, "roster_id": 8, "owner_id": 9, "previous_owner_id": 8},
    ]
    s["draftTradedPicks"][D25] = [
        {"season": "2025", "round": 2, "roster_id": 5, "owner_id": 7, "previous_owner_id": 5}
    ]
    # the league's /traded_picks reflects its draft_id draft (the rookie draft)
    s["tradedPicks"] = s["tradedPicks"] + [
        {"season": "2025", "round": 2, "roster_id": 5, "owner_id": 7, "previous_owner_id": 5}
    ]
    s["transactions"]["1"] = s["transactions"]["1"] + [
        _pick_trade("300000000000000021", _ms(2025, 4, 5), [5, 6], [(2025, 2, 5, 5, 6)]),
        _pick_trade("300000000000000022", _ms(2025, 4, 6), [8, 9], [(2025, 11, 8, 8, 9)]),
        _pick_trade("300000000000000023", _ms(2025, 4, 22), [5, 7], [(2025, 2, 5, 5, 7)]),
    ]
    return b


def test_two_same_season_drafts_keep_separate_replay_state(two_drafts):
    agg, private = C.build_census(two_drafts, ledger=None)
    pr = agg["validation"]["pickReplay"]
    # The rookie trade states sender 5: correct, because the startup trade
    # moved the STARTUP pick.  A season-only key would track 6 and flag it.
    assert pr["senderMismatches"] == 1  # only the fixture's planted 2027-r3
    assert "2025-D1:2025-r2" not in pr["senderMismatchesByDraftAndPickClass"]
    assert pr["transfersByDraftKind"] == {"future_class": 2, "rookie": 2, "startup_veteran": 2}
    assert [c["mismatches"] for c in pr["checkpoints"]] == [0, 0]
    by_ref = {c["draftRef"]: c for c in pr["draftCheckpoints"]}
    assert by_ref["2025-D2"]["kind"] == "startup_veteran"
    assert by_ref["2025-D2"]["mismatches"] == 0 and by_ref["2025-D1"]["mismatches"] == 0
    A = agg["deliverableA"]
    assert A["distinctStartupDraftPicks"] == 2
    assert A["tradesWithStartupDraftPicks"]["total"] == 2
    # one (2025, r2, origin 5) key before the split, two picks after it
    assert A["distinctPickKeysBeforeDraftSplit"] == A["distinctLeaguePicks"] + 1


def test_pick_traded_during_startup_is_consumed_by_the_startup(two_drafts):
    _, private = C.build_census(two_drafts, ledger=None)
    rec = _by_tx(private)["300000000000000021"]
    (a,) = rec["assets"]
    assert a["draftKind"] == "startup_veteran" and a["draftRef"] == "2025-D2"
    assert a["prices"]["idptc"]["pickDetail"] == C.REASON_STARTUP_PICK
    assert rec["classes"]["structurallyUnpriceable"]
    later = _by_tx(private)["300000000000000023"]["assets"][0]
    assert later["draftKind"] == "rookie" and later["draftRef"] == "2025-D1"
    # round 11 exists only in the startup draft
    r11 = _by_tx(private)["300000000000000022"]["assets"][0]
    assert r11["draftRef"] == "2025-D2"


def test_merged_season_key_would_flag_the_rookie_trade(two_drafts):
    """The pre-fix behaviour, reproduced: with the startup draft invisible the
    replay carries the startup move into the rookie draft and calls a correct
    sender wrong -- the defect behind 5 of the 6 live 2024 findings."""
    b = copy.deepcopy(two_drafts)
    b["seasons"][L25]["drafts"] = b["seasons"][L25]["drafts"][:1]
    b["seasons"][L25]["drafts"][0]["last_picked"] = None
    agg, _ = C.build_census(b, ledger=None)
    assert agg["validation"]["pickReplay"]["senderMismatches"] == 2


def test_attribution_rule():
    idx = [
        {
            "draftId": "S",
            "draftRef": "x-D2",
            "season": 2024,
            "rounds": 24,
            "kind": "startup_veteran",
            "startMs": 100,
            "endMs": 200,
            "candidate": True,
        },
        {
            "draftId": "R",
            "draftRef": "x-D1",
            "season": 2024,
            "rounds": 10,
            "kind": "rookie",
            "startMs": 300,
            "endMs": 400,
            "candidate": True,
        },
        {
            "draftId": "P",
            "draftRef": "x-D3",
            "season": 2024,
            "rounds": 10,
            "kind": "startup_veteran",
            "startMs": None,
            "endMs": None,
            "candidate": False,
        },
    ]
    assert C.attribute_pick(idx, 2024, 3, 150)["key"] == "S"
    assert C.attribute_pick(idx, 2024, 3, 250)["key"] == "R"
    assert C.attribute_pick(idx, 2024, 15, 250)["key"] == f"{C.AFTER_DRAFTS}:2024"
    assert C.attribute_pick(idx, 2024, 3, 500)["key"] == f"{C.AFTER_DRAFTS}:2024"
    # ... and names the draft that consumed it: the latest-ending one with the round
    assert C.attribute_pick(idx, 2024, 3, 500)["consumedBy"] == "R"
    assert C.attribute_pick(idx, 2024, 15, 500)["consumedBy"] == "S"
    # a finished draft that made picks outranks a later one that made none
    idx[1]["picks"], idx[0]["picks"] = [], [{"round": 3}]
    assert C.attribute_pick(idx, 2024, 3, 500)["consumedBy"] == "S"
    assert C.attribute_pick(idx, 2025, 1, 500) == {
        "key": f"{C.UNDRAFTED}:2025",
        "draftRef": None,
        "kind": "future_class",
    }


def test_consumption_check_names_the_side_the_picker_agrees_with(two_drafts):
    b = copy.deepcopy(two_drafts)
    # the rookie draft's pick in round 2, slot 3 (origin 3) was made by roster 4:
    # no transaction moved it, so the replay (origin keeps it) differs.
    agg, private = C.build_census(b, ledger=None)
    cons = {c["draftRef"]: c for c in agg["validation"]["pickReplay"]["draftConsumption"]}
    assert cons["2025-D1"]["replayMatchesPicker"] == 4
    b["seasons"][L25]["draftPicks"][D25][2]["roster_id"] = 4
    agg2, _ = C.build_census(b, ledger=None)
    c2 = {c["draftRef"]: c for c in agg2["validation"]["pickReplay"]["draftConsumption"]}
    assert c2["2025-D1"]["replayDiffersFromPicker"] == 1
    assert c2["2025-D1"]["differencesByPickSeasonRound"] == {"2025-r2": 1}
    assert "draft_picker_differs_from_replay_2025-D1:1" in agg2["validation"]["findings"]


def test_failed_pick_trade_is_never_replayed(bundle):
    """A failed trade that would have handed 2027-r3 (origin 2) to roster 9
    must not move it: the planted wrong-sender transfer stays a mismatch."""
    b = copy.deepcopy(bundle)
    b["seasons"][L26]["transactions"]["3"] = [
        _pick_trade("300000000000000031", _ms(2026, 8, 20), [2, 9], [(2027, 3, 2, 2, 9)], "failed")
    ]
    agg, _ = C.build_census(b, ledger=None)
    pr = agg["validation"]["pickReplay"]
    assert pr["transfersReplayed"] == 3
    assert pr["senderMismatches"] == 1


# ── review fixes: classification / pricing mutants ────────────────────────


def test_asof_position_never_reads_a_later_draft():
    drafted = {"9": [(2026, "LB")]}
    players = {"9": {"position": "CB"}}
    assert C._asof_position("9", 2025, drafted, players) == ("DB", "current_sleeper_directory")
    assert C._asof_position("9", 2026, drafted, players) == ("LB", "chain_draft_metadata_2026")


def _rec(assets, rids=(1, 2)):
    return {"rosterIds": list(rids), "assets": assets}


def test_offense_for_idp_needs_two_different_receiving_teams():
    same_team = _rec(
        [
            {"kind": "player", "family": "LB", "to": 1},
            {"kind": "player", "family": "WR", "to": 1},
            {"kind": "pick", "family": "PICK", "to": 2, "pick": {"round": 1}},
        ]
    )
    assert not C.classify_trade(same_team)["offenseForIdp"]
    swap = _rec(
        [{"kind": "player", "family": "LB", "to": 1}, {"kind": "player", "family": "WR", "to": 2}]
    )
    assert C.classify_trade(swap)["offenseForIdp"]


def test_faab_trade_is_never_fully_priced():
    priced = {"idptc": {"fidelity": "nearest-prior"}}
    rec = _rec(
        [
            {"kind": "player", "family": "LB", "to": 1, "prices": priced},
            {"kind": "player", "family": "WR", "to": 2, "prices": priced},
            {"kind": "faab", "family": "FAAB", "to": 1, "amount": 5},
        ]
    )
    assert C._trade_lane_state(rec, "idptc") == "partial"
    assert not C._assets_priced(rec, ["idptc"])
    no_faab = _rec(rec["assets"][:2])
    assert C._trade_lane_state(no_faab, "idptc") == "full"
    assert C._assets_priced(no_faab, ["idptc"])


# ── review fixes: privacy (linkage, small counts) ────────────────────────


def _committed_census_outputs() -> list[Path]:
    """The committed census outputs as Git tracks them -- never a filesystem
    glob, which on a CI checkout or a dirty tree sees a different file set."""
    out = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "ls-files",
            "--",
            "docs/market_trades/OWN_LEAGUE_HISTORY_CENSUS_*.md",
            "docs/market_trades/evidence/own_league_census_*.json",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return [REPO / p for p in out if p.strip()]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not available")
def test_committed_census_outputs_pass_the_write_refusal():
    """The committed files pass the SAME structural refusal ``main`` applies
    before writing them."""
    files = _committed_census_outputs()
    assert {p.suffix for p in files} == {".md", ".json"}, files
    js = next(p for p in files if p.suffix == ".json").read_text(encoding="utf-8")
    md = next(p for p in files if p.suffix == ".md").read_text(encoding="utf-8")
    agg = json.loads(js)
    assert C.write_refusals(agg, js, md, names=[]) == []
    assert C.disclosure_leaks(agg) == []
    assert "tradesPerTeamLabel" not in js + md and not C._TEAM_LABEL.search(js + md)


def test_synthetic_outputs_pass_the_write_refusal(tmp_path, bundle, ledger):
    rc, md, js, _ = _run_main(tmp_path, bundle, ledger)
    assert rc == C.EXIT_FINDINGS
    agg = json.loads(js.read_text(encoding="utf-8"))
    assert C.disclosure_leaks(agg) == []
    assert C.linkage_leaks(agg, md.read_text(encoding="utf-8")) == []


def test_disclosure_check_catches_a_per_team_row_and_a_max():
    bad = {
        "deliverableA": {"tradesPerTeamLabel": {"2025": {"T01": 9}}},
        "effectiveSample": {"maxFullyIdptcPricedTradesPerManager": 11},
    }
    got = C.disclosure_leaks(bad)
    assert "per_participant_key:.deliverableA.tradesPerTeamLabel" in got
    assert "participant_label_key:.deliverableA.tradesPerTeamLabel.2025.T01" in got
    assert "single_participant_count:.effectiveSample.maxFullyIdptcPricedTradesPerManager=11" in got
    assert C.linkage_leaks(bad, "T01 traded 9")[0] == "team_label:T01"


#: The second review's probes: each must be refused.
TEXT_PROBES = [
    "T1",
    "T001",
    "Team 3 made 19 of 29 trades; roster 1 sent the pick",
    "origin 5",
    "sender 9",
    "owner 12",
]
JSON_PROBES = [
    {"tradesByRoster": {"a": 3, "b": 1}},
    {"perTeam": [9, 4, 1]},
    {"topManagerTrades": 11},
    {"managerTrades": 11},
    {"mostActiveTeamShare": 0.61},
    {"rosterIds": [1, 2]},
    {"slotToRoster": {"1": 4}},
    {"seasonSplit": {"T03": 5}},
    {"distinctTradingManagers": 2},
]


@pytest.mark.parametrize("probe", TEXT_PROBES)
def test_text_probe_is_refused(probe):
    assert C.linkage_leaks({}, f"prose: {probe}.")


@pytest.mark.parametrize("probe", JSON_PROBES, ids=lambda p: next(iter(p)))
def test_json_probe_is_refused(probe):
    assert C.disclosure_leaks({"deliverableA": probe})


def test_reviewed_counts_are_not_refused():
    """Integers that name a participant word but count trades, picks or
    settings, and populations at or above K_ANON."""
    ok = {
        "teams": 12,
        "teamsInAnyTrade": 12,
        "teamCount": {"source": 10, "target": 12},
        "senderMismatches": 1,
        "topology": {"multi_team": 11, "two_team_1_for_1": 53},
        "three_or_more_teams": 11,
        "draftConsumption": [{"replayMatchesPicker": 100, "draftHostDiffersFromPicker": 0}],
        "rosterSlots": 58,
        "mostActiveTeamShareOfTrades": ">50%",
        "text": "the slot's origin: 100 picks; 12 teams; a 12-team league",
    }
    assert C.disclosure_leaks(ok) == []
    assert C.linkage_leaks(ok, json.dumps(ok)) == []


def _inject_into_aggregate(monkeypatch, extra):
    real = C.build_census

    def patched(*a, **k):
        agg, private = real(*a, **k)
        agg["deliverableA"].update(copy.deepcopy(extra))
        return agg, private

    monkeypatch.setattr(C, "build_census", patched)


@pytest.mark.parametrize("probe", JSON_PROBES, ids=lambda p: next(iter(p)))
def test_main_refuses_a_json_probe_before_any_write(tmp_path, bundle, monkeypatch, probe):
    _inject_into_aggregate(monkeypatch, probe)
    rc, md, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_BAD_INPUT
    assert not md.exists() and not js.exists()


@pytest.mark.parametrize("probe", TEXT_PROBES)
def test_main_refuses_a_markdown_probe_before_any_write(tmp_path, bundle, monkeypatch, probe):
    real = C.render_markdown
    monkeypatch.setattr(C, "render_markdown", lambda agg: real(agg) + f"\n{probe}\n")
    rc, md, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_BAD_INPUT
    assert not md.exists() and not js.exists()


def test_main_refuses_a_text_probe_inside_the_json(tmp_path, bundle, monkeypatch):
    _inject_into_aggregate(monkeypatch, {"note": TEXT_PROBES[2]})
    rc, md, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_BAD_INPUT
    assert not md.exists() and not js.exists()


def test_linkage_scan_refuses_a_team_label_write(tmp_path, bundle, monkeypatch):
    real = C.render_markdown
    monkeypatch.setattr(C, "render_markdown", lambda agg: real(agg) + "\nT03 made 11 trades\n")
    rc, md, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_BAD_INPUT
    assert not md.exists() and not js.exists()


# ── quantile publication rule: no published statistic set inverts the counts ─


def test_count_quantiles_rule():
    assert C.count_quantiles([1, 4, 9]) == (None, "fewer_than_5_teams")
    assert C.count_quantiles([1, 2, 4, 9]) == (None, "fewer_than_5_teams")
    assert C.count_quantiles([0, 1, 1, 2, 4]) == ({"median": 1}, None)
    assert C.count_quantiles(list(range(7))) == ({"median": 3}, None)
    q, why = C.count_quantiles(list(range(8)))
    assert why is None and set(q) == {"p25", "median", "p75"}


def test_per_team_distribution_has_no_single_team_count():
    d = C.per_team_distribution([0, 1, 1, 2, 4], trades=10)
    assert d == {
        "teams": 5,
        "teamsInAnyTrade": 4,
        "mostActiveTeamShareOfTrades": "25-50%",
        "quantiles": {"median": 1},
    }
    tiny = C.per_team_distribution([2, 5, 7], trades=8)
    assert tiny["quantiles"] is None and tiny["quantilesSuppressed"] == "fewer_than_5_teams"
    eight = C.per_team_distribution([0, 1, 1, 2, 3, 4, 6, 9], trades=13)
    assert set(eight["quantiles"]) == {"p25", "median", "p75"}
    assert C.share_bucket(11, 17) == ">50%" and C.share_bucket(0, 0) is None


def _published(vec, publish):
    """What a reader of the committed output sees for one season's sorted
    per-team counts: the number of teams, how many traded at all, and the
    published quantile block (min and max are never published)."""
    q, _ = publish(vec)
    return (len(vec), sum(1 for v in vec if v), tuple(sorted((q or {}).items())))


def _old_publish(vec):
    """The first-review rule: inclusive p25 / median / p75 at n >= 3."""
    vals = sorted(vec)
    if len(vals) < C.K_ANON:
        return None, "suppressed"
    q = statistics.quantiles(vals, n=4, method="inclusive")
    return {"p25": q[0], "median": statistics.median(vals), "p75": q[2]}, None


def _preimages(n, publish, top):
    """Every sorted count vector over 0..top, grouped by what it publishes."""
    out: dict = {}
    for vec in itertools.combinations_with_replacement(range(top + 1), n):
        out.setdefault(_published(list(vec), publish), set()).add(vec)
    return out


def test_old_rule_inverted_three_teams():
    """The reviewer's example: [1, 4, 9] -> 2.5 / 4 / 6.5 solves for every
    team's count, so the old rule published the whole season."""
    assert _old_publish([1, 4, 9])[0] == {"p25": 2.5, "median": 4, "p75": 6.5}
    pre = _preimages(3, _old_publish, 12)
    assert pre[_published([1, 4, 9], _old_publish)] == {(1, 4, 9)}


@pytest.mark.parametrize("n", range(3, 9))
def test_no_published_statistic_set_inverts_any_season(n):
    """For every season of n teams (3..8) whose counts lie in 0..6, at least
    one OTHER count vector (searched over 0..7) publishes exactly the same
    statistics.  So no published statistic set reveals every team's count.
    (A season where no team traded is excluded: ``teamsInAnyTrade = 0`` says
    so by itself, with or without quantiles.)"""
    pre = _preimages(n, C.count_quantiles, 7)
    for vec in itertools.combinations_with_replacement(range(7), n):
        if not any(vec):
            continue
        assert len(pre[_published(list(vec), C.count_quantiles)]) >= 2, vec


def test_manager_statistics_follow_the_publication_rule():
    assert C.manager_statistics([3, 1], trades=4) == {
        "managersInFullyIdptcPricedTrades": None,
        "mostActiveManagerShareOfFullyIdptcPricedTrades": None,
        "medianFullyIdptcPricedTradesPerManager": None,
        "managerStatisticsSuppressed": "fewer_than_3_managers",
    }
    four = C.manager_statistics([4, 2, 1, 1], trades=5)
    assert four["managersInFullyIdptcPricedTrades"] == 4
    assert four["medianFullyIdptcPricedTradesPerManager"] is None  # median needs 5
    five = C.manager_statistics([4, 2, 2, 1, 1], trades=6)
    assert five["medianFullyIdptcPricedTradesPerManager"] == 2
    assert five["mostActiveManagerShareOfFullyIdptcPricedTrades"] == ">50%"
    assert C.disclosure_leaks(four) == [] and C.disclosure_leaks(five) == []


def test_manager_median_is_suppressed_below_five_managers():
    gated = {"managersInFullyIdptcPricedTrades": 4, "medianFullyIdptcPricedTradesPerManager": 2}
    assert C.disclosure_leaks(gated) == [
        "median_over_too_few:.medianFullyIdptcPricedTradesPerManager(n=4)"
    ]
    q = {"teams": 6, "teamsInAnyTrade": 6, "mostActiveTeamShareOfTrades": ">50%"}
    bad = {"tradesPerTeamDistribution": {"2024": {**q, "quantiles": {"p25": 1, "median": 2}}}}
    assert C.disclosure_leaks(bad)
    good = {"tradesPerTeamDistribution": {"2024": {**q, "quantiles": {"median": 2}}}}
    assert C.disclosure_leaks(good) == []


# ── review fixes: the scan must not depend on the commit SHA ─────────────

#: The Linux CI merge commit of head c95390a98 (refs/pull/1985/merge): its
#: digit run 764357346 made the id scan refuse the write.  Platform had
#: nothing to do with it; the SHA differs per commit.
CI_MERGE_SHA = "9fcec1fa34d2918e55abb764357346ae5cd85279"
ID1, ID2 = "200000000000000001", "200000000000000002"


def _ids(text, digests=()):
    return C.identifier_leaks(text, allowed_ids=[], names=[], allowed_digests=digests)


def test_scan_exempts_only_allowlisted_digests():
    assert _ids(f'"codeSha": "{CI_MERGE_SHA}"', [CI_MERGE_SHA]) == []
    # NOT exempt by shape: the same SHA, not passed in, is a leak
    assert _ids(f'"codeSha": "{CI_MERGE_SHA}"') == ["764357346"]
    other = "0123456789abcdef0123456789abcdef01234567"
    assert _ids(f'"x": "{other}"', [CI_MERGE_SHA]) == ["0123456789"]
    assert _ids("1" * 40) == ["1" * 40]
    assert _ids("x123456789012 ab123456789cd z") == ["123456789", "123456789012"]


@pytest.mark.parametrize(
    "text,expected",
    [
        (f"{ID1}abcdef0123456789abcdef0123456789", ID1),  # an id glued to hex letters
        (f"{CI_MERGE_SHA}{ID1}", "85279" + ID1),  # a sha glued to an id
        (f"{ID1}e{ID2}", ID2),  # an id-e-id
        (f"league.{ID1}", ID1),  # an id after a period
        (f"0.{ID1}", ID1),  # an id spelled as a fraction
    ],
    ids=["id_glued_to_hex", "sha_glued_to_id", "id_e_id", "id_after_period", "id_as_fraction"],
)
def test_digest_probe_is_flagged(text, expected):
    assert expected in _ids(text, [CI_MERGE_SHA])


def test_float_fractions_are_not_ids():
    assert _ids("0.1111111111111111, 0.03333333333333333, -2.0333333333333") == []


def test_committed_digests_are_the_scripts_own(bundle):
    agg, _ = C.build_census(bundle, ledger=None)
    agg["inputs"]["codeSha"] = CI_MERGE_SHA
    got = C.committed_digests(agg)
    assert CI_MERGE_SHA in got
    assert {c["formatFingerprint"] for c in agg["chain"]["seasons"]} <= set(got)
    own = {c[k] for c in agg["chain"]["seasons"] for k in ("formatFingerprint", "scoringCardHash")}
    assert set(got) == {CI_MERGE_SHA} | {d for d in own if d}


def test_write_does_not_depend_on_the_commit_sha(tmp_path, bundle, monkeypatch):
    monkeypatch.setattr(C, "_code_sha", lambda: CI_MERGE_SHA)
    rc, _, js, _ = _run_main(tmp_path, bundle)
    assert rc == C.EXIT_FINDINGS
    assert json.loads(js.read_text(encoding="utf-8"))["inputs"]["codeSha"] == CI_MERGE_SHA


def test_startup_pick_reaches_the_fit_gate_unresolved_not_as_a_league_pick(two_drafts):
    _, private = C.build_census(two_drafts, ledger=None)
    startup = _by_tx(private)["300000000000000021"]
    rookie = _by_tx(private)["300000000000000023"]
    assert "includes_unresolved" in startup["fit"]["reasons"]
    assert "includes_unresolved" not in rookie["fit"]["reasons"]


def test_consumption_round_past_identity_grammar_is_not_a_difference():
    d = {
        "draftRef": "2024-D2",
        "kind": "startup_veteran",
        "type": "snake",
        "draftId": "S",
        "season": 2024,
        "slotToRoster": {"1": 5},
        "picks": [{"draft_slot": 1, "round": 21, "roster_id": 5}],
    }
    host = {(2024, 1, 5): 5}  # the owner's fold stops at round 20
    got = C._consumption_check(d, host, lambda k, s, r, o: o)
    assert got["draftHostRoundNotCompared"] == 1 and got["replayMatchesPicker"] == 1
    assert "draftHostDiffersFromPicker" not in got and got["_detail"] == []


# ── second review fixes: one draft-assignment rule, pre_draft league draft ──

D26, D28 = "400000000000000026", "400000000000000028"


@pytest.fixture()
def draft_id_not_consumer(bundle) -> dict:
    """2026, as live: the league's ``draft_id`` is a SECOND 2026 draft that
    completed with 0 picks after the rookie draft, while the rookie draft (the
    other draft object) consumed the class.  A 2026 round-2 pick moves 4 -> 5
    DURING the rookie draft, and the league's ``/traded_picks`` shows it."""
    b = copy.deepcopy(bundle)
    s = b["seasons"][L26]
    rookie = s["drafts"][0]
    rookie["start_time"], rookie["last_picked"] = _ms(2026, 5, 1), _ms(2026, 5, 10)
    phantom = copy.deepcopy(rookie)
    phantom.update(draft_id=D28, start_time=_ms(2026, 6, 18), last_picked=_ms(2026, 6, 18))
    s["drafts"].append(phantom)
    s["league"]["draft_id"] = D28
    s["draftPicks"][D28] = []
    s["draftTradedPicks"][D28] = []
    s["draftDetail"][D28] = {"draft_id": D28}
    move = {"season": "2026", "round": 2, "roster_id": 4, "owner_id": 5, "previous_owner_id": 4}
    earlier = {"season": "2026", "round": 1, "roster_id": 3, "owner_id": 4, "previous_owner_id": 3}
    s["tradedPicks"] = s["tradedPicks"] + [earlier, move]
    s["draftTradedPicks"][D26] = s["draftTradedPicks"][D26] + [move]
    s["transactions"]["1"] = s["transactions"]["1"] + [
        _pick_trade("300000000000000041", _ms(2026, 5, 5), [4, 5], [(2026, 2, 4, 4, 5)])
    ]
    return b


def test_league_checkpoint_uses_the_consuming_draft_not_draft_id(draft_id_not_consumer):
    agg, private = C.build_census(draft_id_not_consumer, ledger=None)
    pr = agg["validation"]["pickReplay"]
    (a,) = _by_tx(private)["300000000000000041"]["assets"]
    assert a["draftKey"] == D26  # the transfer: the rookie draft running at the instant
    cp26 = next(c for c in pr["checkpoints"] if c["season"] == "2026")
    assert 2026 in cp26["pickSeasonsCompared"]
    assert cp26["mismatches"] == 0  # the checkpoint: the SAME draft, not draft_id
    by_ref = {c["draftRef"]: c for c in pr["draftCheckpoints"]}
    assert by_ref["2026-D1"]["mismatches"] == 0 and by_ref["2026-D2"]["mismatches"] == 0
    assert not any(f.startswith("pick_ownership_mismatch") for f in agg["validation"]["findings"])


def test_draft_id_rule_would_miss_the_consumed_pick(draft_id_not_consumer, monkeypatch):
    """The pre-fix checkpoint rule, reproduced: keyed to the league's
    ``draft_id`` the 2026 row reads the 0-pick draft's untouched state and the
    host's correct owner looks wrong."""
    real = C.attribute_pick

    def draft_id_rule(index, season, rnd, at_ms):
        got = real(index, season, rnd, at_ms)
        if got.get("consumedBy") and season == 2026:
            return {**got, "consumedBy": D28}
        return got

    monkeypatch.setattr(C, "attribute_pick", draft_id_rule)
    agg, _ = C.build_census(draft_id_not_consumer, ledger=None)
    cp26 = next(c for c in agg["validation"]["pickReplay"]["checkpoints"] if c["season"] == "2026")
    assert cp26["mismatches"] == 2  # both 2026 rows: r1 (origin 3) and r2 (origin 4)


def _upcoming_league_draft_season():
    return {
        "season": "2026",
        "league": {"draft_id": "P"},
        "rosters": [{"roster_id": 1}, {"roster_id": 2}],
        "drafts": [
            {
                "draft_id": "P",
                "season": "2027",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"rounds": 4, "player_type": 1},
            },
            {
                "draft_id": "Q",
                "season": "2027",
                "status": "pre_draft",
                "type": "snake",
                "settings": {"rounds": 4, "player_type": 1},
            },
        ],
        "draftPicks": {"P": [], "Q": []},
        "draftTradedPicks": {"P": [], "Q": []},
        "draftDetail": {},
    }


def test_pre_draft_league_draft_owns_its_picks():
    """A league draft that has not run yet and has no picks is still the
    draft its season's picks belong to (``or is_league``); a non-league
    ``pre_draft`` board (2024's abandoned one) owns none."""
    idx = {d["draftId"]: d for d in C.draft_index([_upcoming_league_draft_season()])}
    assert idx["P"]["candidate"] and idx["P"]["isLeagueDraft"]
    assert not idx["Q"]["candidate"]
    got = C.attribute_pick(list(idx.values()), 2027, 1, _ms(2026, 12, 1))
    assert got["key"] == "P" and got["kind"] == "rookie"


def test_scan_helper_exempts_only_the_committed_digest_values():
    """The test-side scan is not weakened by its exemption: a SHA it was not
    handed is still flagged, and an id glued to a handed SHA runs past it."""
    blob = f'"codeSha": "{REVIEW_HEAD_SHA}"'
    assert _long_runs_outside_digests(blob, {REVIEW_HEAD_SHA}) == set()
    assert _long_runs_outside_digests(blob, set()) == {"1362637166"}
    assert _long_runs_outside_digests(blob, {CI_MERGE_SHA}) == {"1362637166"}
    glued = f"{REVIEW_HEAD_SHA}{ID1}"
    assert _long_runs_outside_digests(glued, {REVIEW_HEAD_SHA}) == {ID1}
