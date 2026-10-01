"""AL-2a target-format evidence census over the completed-trade ledger.

Synthetic lanes only (no real league, manager or trade).  What is pinned:

* every census quantity the owner directive lists is computed;
* UNKNOWN stays UNKNOWN in every distribution and in exact/near;
* the publishable output carries no league / user / transaction identifier
  (realistic id shapes are planted and grepped for verbatim);
* counts below the minimum cell are suppressed and rare values folded by
  DISTINCT LEAGUE count, trade-level distributions included;
* EXACT / NEAR require a verified dynasty state, and stale target scoring
  refuses them;
* dedupe counts are the LEDGER'S OWN groups (no second dedupe);
* the CLI writes JSON + markdown and nothing else: the canonical ledger and
  every input store are byte-identical afterwards.
"""

from __future__ import annotations

import json

import pytest

from src.intel import ledger
from src.trade import market_trade_archive as A
from src.trade import market_trade_format as F
from src.trade import market_trade_normalize as N
from src.trade import market_trade_report as R
from tests.trade.market_trade_fixtures import (
    KTC_INDEX,
    TARGET_POSITIONS,
    TARGET_SCORING,
    ctx,
    ktc_row,
    ktc_settings,
    sleeper_league,
)
from tests.trade.test_market_trade_normalize import _ev

TARGET = F.format_from_sleeper_league(sleeper_league("TGT"))

# Realistic identifier SHAPES (all invented): Sleeper league / user /
# transaction ids are 18-19 digit snowflakes; KTC trade ids are plain
# integers; MFL league ids are 5 digits.  The privacy test greps the published
# outputs for every one of these exact strings.
EXACT_LEAGUES = [str(1048293746519283700 + i) for i in range(6)]
NEAR_LEAGUES = [str(992837465012938400 + i) for i in range(5)]
OFFENSE_LEAGUE = "1120394857261738496"
PARTIAL_LEAGUE = "873465019283746512"
REDRAFT_LEAGUE = "1063829104756382910"
KEEPER_LEAGUE = "1063829104756382911"
NO_TYPE_LEAGUE = "1063829104756382912"
OWNER_IDS = ("604918273645018112", "604918273645018113")
SECRET_VIA = "731029384756102938"
SECRET_MFL = "73915"
EXACT_TX = [str(1101928374655463400 + i) for i in range(6)]
NEAR_TX = [str(1101928374655463500 + i) for i in range(5)]
OFFENSE_TX = "1101928374655463600"
PARTIAL_TX = "1101928374655463700"
NON_DYNASTY_TX = ("1101928374655463800", "1101928374655463801", "1101928374655463802")
KTC_TRADE_IDS = (731904561, 731904562, 731904563)

PLANTED_IDS = [
    *EXACT_LEAGUES,
    *NEAR_LEAGUES,
    OFFENSE_LEAGUE,
    PARTIAL_LEAGUE,
    REDRAFT_LEAGUE,
    KEEPER_LEAGUE,
    NO_TYPE_LEAGUE,
    *NON_DYNASTY_TX,
    *OWNER_IDS,
    SECRET_VIA,
    SECRET_MFL,
    *EXACT_TX,
    *NEAR_TX,
    OFFENSE_TX,
    PARTIAL_TX,
    *(str(t) for t in KTC_TRADE_IDS),
    # KTC-style composite keys the pipeline builds from those ids
    *(f"ktc:{t}" for t in KTC_TRADE_IDS),
    *(f"{N.SOURCE_KTC}:{t}" for t in KTC_TRADE_IDS),
    *(f"{N.SOURCE_SLEEPER_DISCOVERY}:{lg}" for lg in EXACT_LEAGUES),
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.intel import store

    A._reset_setup_cache_for_tests()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    # Every default market-trade path (canonical ledger, reports) resolves
    # under tmp, so "the ledger was not written" is a real assertion.
    monkeypatch.setattr(A, "DEFAULT_DIR", tmp_path / "mt")
    ledger.reset_setup_cache()
    intel = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(intel).close()
    yield {"tmp": tmp_path, "intel": intel, "archive": tmp_path / "mt" / "archive.sqlite"}
    ledger.reset_setup_cache()
    A._reset_setup_cache_for_tests()


def _events(tx: str, league: str, *, idp: bool = True) -> list[dict]:
    owner1, owner2 = OWNER_IDS
    evs = [
        _ev(tx, 2, "add", "1001", league=league, owner=owner2),
        _ev(tx, 1, "drop", "1001", league=league, owner=owner1),
        _ev(tx, 2, "add", "pick:2027:1", league=league, disc="o3", owner=owner2),
        _ev(tx, 1, "drop", "pick:2027:1", league=league, disc="o3", owner=owner1),
    ]
    if idp:
        evs += [
            _ev(tx, 1, "add", "2001", league=league, owner=owner1),
            _ev(tx, 2, "drop", "2001", league=league, owner=owner2),
        ]
    else:
        evs += [
            _ev(tx, 1, "add", "1002", league=league, owner=owner1),
            _ev(tx, 2, "drop", "1002", league=league, owner=owner2),
        ]
    return evs


def _league_row(league_id: str, lg: dict | None, *, teams: int = 12, ltype: int | None = 2) -> dict:
    settings: dict = {"bestBall": 1, "discovery": {"viaUserId": SECRET_VIA}}
    if ltype is not None:
        settings["type"] = ltype
    if lg is not None:
        settings["marketFormat"] = F.capture_sleeper_league_format(
            lg, captured_at="2026-10-01T00:00:00+00:00"
        )
    return {
        "league_id": league_id,
        "season": "2026",
        "total_rosters": teams,
        "settings_json": json.dumps(settings),
    }


def _seed(env, *, with_ktc: bool = True, non_dynasty: bool = False) -> None:
    rows = []
    for tx, lid in zip(EXACT_TX, EXACT_LEAGUES):
        ledger.ingest_events(_events(tx, lid), path=env["intel"])
        rows.append(_league_row(lid, sleeper_league(lid)))
    near_scoring = dict(TARGET_SCORING) | {"idp_sack": 4.0}
    for tx, lid in zip(NEAR_TX, NEAR_LEAGUES):
        ledger.ingest_events(_events(tx, lid), path=env["intel"])
        rows.append(_league_row(lid, sleeper_league(lid, scoring=near_scoring)))
    if non_dynasty:
        # Identical lineup AND card to the target — only the game type differs
        # (redraft, keeper) or is unstated.  None of them may ever be EXACT.
        for tx, lid, ltype in zip(
            NON_DYNASTY_TX, (REDRAFT_LEAGUE, KEEPER_LEAGUE, NO_TYPE_LEAGUE), (0, 1, None)
        ):
            lg = sleeper_league(lid, ltype=0 if ltype is None else ltype)
            if ltype is None:
                del lg["settings"]["type"]
            ledger.ingest_events(_events(tx, lid), path=env["intel"])
            rows.append(_league_row(lid, lg, ltype=ltype))
    off = sleeper_league(
        OFFENSE_LEAGUE,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"] + ["BN"] * 15,
        scoring={"rec": 1.0, "pass_td": 4.0},
        teams=10,
        best_ball=0,
    )
    ledger.ingest_events(_events(OFFENSE_TX, OFFENSE_LEAGUE, idp=False), path=env["intel"])
    rows.append(_league_row(OFFENSE_LEAGUE, off, teams=10))
    # A discovery league whose format was never captured: everything UNKNOWN.
    ledger.ingest_events(_events(PARTIAL_TX, PARTIAL_LEAGUE), path=env["intel"])
    rows.append(_league_row(PARTIAL_LEAGUE, None))
    ledger.upsert_leagues(rows, path=env["intel"])
    if not with_ktc:
        return
    index = KTC_INDEX + [{"playerName": "Echo Edge", "playerID": 21, "position": "DL"}]
    t_dup, t_mfl, t_nolg = KTC_TRADE_IDS
    dup = ktc_row(t_dup, [11, 902], [21], settings=ktc_settings(EXACT_LEAGUES[0]))
    mfl = ktc_row(t_mfl, [13], [12], settings=ktc_settings(SECRET_MFL, platform="mfl", qbs=1))
    nolg = ktc_row(t_nolg, [14], [12], settings=ktc_settings("") | {"id": None})
    f = A.FetchRecord(
        fetch_id="f1",
        source_family=N.SOURCE_KTC,
        fetched_at="2026-10-01T12:00:00+00:00",
        outcome="archived",
    )
    A.record_fetch(
        f,
        [A.RawObservation(str(r["id"]), r, "2026-10-01") for r in (dup, mfl, nolg)],
        identity_entries=index,
        path=env["archive"],
    )


def _build(env, lanes=(N.SOURCE_KTC, N.SOURCE_SLEEPER_DISCOVERY)):
    return R.build_ledger(
        archive_path=env["archive"],
        intel_ledger_path=env["intel"],
        league_keys=[],
        ctx=ctx(),
        target_format=TARGET,
        lanes=lanes,
    )


@pytest.fixture
def built(env):
    _seed(env)
    return _build(env)


def test_every_census_quantity_is_computed(built):
    c = R.target_format_census(built)
    s = c["sections"]
    raw = s["rawObservations"]
    assert raw["ktc"]["normalizedObservations"] == 3
    assert raw["ktc"]["archiveRawRevisions"] == 3
    assert raw["ktc"]["withoutHostLeagueId"] == 1
    assert raw["sharpDiscoverySleeper"] == 13
    assert raw["total"] == 16

    d = s["dedupe"]
    assert d["underlyingTradesPointEstimate"] == 15, "the KTC duplicate collapses"
    assert d["crossSourceDuplicates"]["probable"] == 1
    assert d["confirmedUnderlyingTrades"] == 14
    assert {"possibleOverlapGroups", "unresolvedGroups"} <= set(d["unresolvedOverlaps"])

    idp = s["idp"]
    # 6 exact (one of them also seen by KTC: ONE group) + 5 near + the partial league
    assert idp["tradesWithAnIdpPlayer"] == 12
    assert idp["leaguesWithIdp"] == 11
    assert idp["tradesInIdpLeagues"] == 11
    assert idp["starterStructure"]["idpLeagues"]["idpStarters"] == {"9": 11}
    assert idp["starterStructure"]["idpLeagues"]["familyDemandMinMax"]["LB"] == {"3-3": 11}

    lg = s["leagues"]
    assert lg["distinctLeagues"] == 14  # 6 + 5 + offense + partial + MFL
    assert lg["metadataSufficiency"]["scoringCardKnown"] == 12
    assert lg["metadataSufficiency"]["allThirteenAxesKnown"] == 12
    assert lg["tradesWithoutLeagueIdentity"] == 1

    m = s["matchToTarget"]
    assert m["trades"]["byState"]["EXACT"] == 6
    assert m["trades"]["byState"]["NEAR"] == 5
    assert m["trades"]["exactIdpTrades"] == 6
    assert m["trades"]["nearIdpTrades"] == 5
    assert m["trades"]["exactAndNativeComparable"] == 6
    assert m["leagues"]["byState"] == {"EXACT": 6, "NEAR": 5, "NOT_NEAR": 2, "UNKNOWN": 1}

    qb = s["qbPopulations"]
    assert qb["trades"] == {"UNKNOWN": 1, "false": 2, "true": 12}
    assert set(qb["tradesBySourceMix"]) == {
        "ktc_trade_database",
        "ktc_trade_database+sleeper_sharp_discovery",
        "sleeper_sharp_discovery",
    }

    te = s["te"]["leagues"]
    assert te["teStarterDemandMinMax"]["2-5"] == 11
    assert te["teScoringEdge"]["UNKNOWN"] == 2  # partial + MFL (KTC publishes no card)

    sim = idp["scoringSimilarity"]
    assert sim["idpLeaguesWithScoringCard"] == 11
    sack = sim["comparison"]["perKey"]["idp_sack"]
    assert sack["relation"] == {"equal": 6, "higherInSource": 5}
    assert sack["category"] == "sacks"
    assert sim["comparison"]["exactMatchShareOfTargetNonZeroIdpKeys"] == {
        "1.00": 6,
        "0.75-0.99": 5,
    }

    assert set(s["axisStates"]) == set(F.AXES)
    assert s["translatorSupportSingleDifferingAxisTrades"] == {"idpScoring": 5}
    assert s["tradesContainingPositionFamily"]["all"]["DL"] == 12


def test_unknown_format_stays_unknown(built):
    c = R.target_format_census(built)
    s = c["sections"]
    # The uncaptured discovery league: never folded into "1QB" / "no IDP".
    assert s["leagues"]["superflex"]["UNKNOWN"] == 1
    assert s["leagues"]["idpEnabled"]["UNKNOWN"] == 1
    assert s["idp"]["tradesWithAnIdpPlayerByLeagueIdpEnabled"]["UNKNOWN"] == 1
    # Unknown exact/near is UNKNOWN, not NOT_NEAR.
    assert s["matchToTarget"]["trades"]["byState"]["UNKNOWN"] == 1  # the partial league
    assert "UNKNOWN" in s["axisStates"]["qbDemand"]
    # A partial format can never be exact, whatever the target looks like.
    partial = F.format_from_sleeper_league({"settings": {"type": 2}, "total_rosters": 12})
    assert R.exact_state(partial, TARGET) is None
    assert R.near_state(partial, TARGET, F.compare_formats(partial, TARGET)) == "UNKNOWN"
    # A target without a scoring card makes the similarity block refuse, not zero.
    no_card = F.format_from_sleeper_league(sleeper_league("T2") | {"scoring_settings": None})
    groups_fmt = [F.format_from_sleeper_league(sleeper_league("X"))]
    out = R._idp_scoring_similarity(groups_fmt, no_card)
    assert out["comparison"] == {"available": False, "reason": "target_scoring_card_unknown"}


def test_dedupe_counts_are_the_ledgers_own_groups(built):
    c = R.target_format_census(built)
    d = c["sections"]["dedupe"]
    vol = built["grouping"].volume
    assert d["groupsByState"] == dict(sorted(vol["groupsByState"].items()))
    for k in ("underlyingTradesPointEstimate", "underlyingTradesLowerBound"):
        assert d[k] == vol[k]
    cov = R.coverage_report(built)
    assert d["crossSourceDuplicates"]["probable"] == cov["probableCrossSourceGroups"]
    assert d["unresolvedOverlaps"]["possibleOverlapGroups"] == cov["possibleOverlapGroups"]
    assert c["sections"]["dispositions"] == dict(sorted(cov["dispositions"].items()))


def _assert_no_planted_ids(text: str) -> None:
    for s in [*PLANTED_IDS, "utrade:", "Echo Edge", "Alpha Receiver", "player:"]:
        assert s not in text, f"identifier leaked into the census: {s}"


def test_planted_ids_reach_the_unpublished_result(built):
    # Guards the grep below: the ids ARE in the pipeline's own data, so their
    # absence from the outputs is the census's doing, not the fixture's.
    raw = json.dumps([R._jsonable_group(g) for g in built["grouping"].groups], default=str)
    for s in (EXACT_LEAGUES[0], NEAR_TX[0], str(KTC_TRADE_IDS[0]), SECRET_MFL):
        assert s in raw


def test_publishable_census_contains_no_identifiers(built):
    pub = R.build_target_format_census(built)
    _assert_no_planted_ids(json.dumps(pub, default=str))
    _assert_no_planted_ids(R.census_markdown(pub))
    assert pub["privacy"]["aggregateOnly"] is True


def test_small_cells_are_suppressed_and_rare_values_folded(built):
    pub = R.build_target_format_census(built)
    s = pub["sections"]

    def ints(obj):
        if isinstance(obj, bool):
            return
        if isinstance(obj, int):
            yield obj
        elif isinstance(obj, dict):
            for v in obj.values():
                yield from ints(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from ints(v)

    assert all(n == 0 or n >= R.CENSUS_MIN_CELL for n in ints(s))
    assert s["rawObservations"]["ktc"]["normalizedObservations"] == R.SUPPRESSED
    assert s["idp"]["leaguesWithIdp"] == 11
    # A scoring value only one league uses never appears as its own key.
    rec = s["te"]["leagues"]["teScoringKeyValues"].get("bonus_fd_te", {})
    assert all(k in ("1", R.OTHER_SMALL_CELLS, R.UNKNOWN_CELL) for k in rec)
    # Medians need n >= CENSUS_MIN_CELL leagues; one league's value is never shown.
    assert R._median([1.0, 2.0])["median"] is None
    assert R._median([1.0] * 5)["median"] == 1.0
    assert R.suppress_small_cells({"a": 3, "b": 0, "c": 7, "d": True}) == {
        "a": "<5",
        "b": 0,
        "c": 7,
        "d": True,
    }
    # UNKNOWN is never folded into OTHER_SMALL_CELLS.
    assert R._dist([None, 1, 1], fold_small=True) == {
        R.OTHER_SMALL_CELLS: 2,
        R.UNKNOWN_CELL: 1,
    }


def test_broad_context_is_reported_not_invented(built):
    c = R.target_format_census(built)
    b = c["sections"]["broadContextReconciliation"]
    assert b["expressibleByCurrentDispositions"] is False
    disp = c["sections"]["dispositions"]
    assert b["targetUnsupportedTrades"] == disp[F.TARGET_UNSUPPORTED]
    cand = b["candidateBroadContext"]
    assert (
        cand["total"] + b["unsupportedOrUnverifiedDynastyNotVerified"]
        == (b["targetUnsupportedTrades"])
    )
    # The partial league's dynasty type IS stated on its discovery row, so it is a
    # verified-dynasty unknown-only candidate; KTC rows carry a source-level claim.
    assert "source_level_claim:ktc_dynasty_trade_database" in (
        cand["verifiedDynastyKnownMismatchByDynastyBasis"]
        | cand["verifiedDynastyUnknownOnlyByDynastyBasis"]
    )
    # Dispositions are untouched: still exactly #1586's three.
    assert set(disp) <= {F.NATIVE_COMPARABLE, F.VALIDATED_TRANSFORMABLE, F.TARGET_UNSUPPORTED}


def test_census_writes_nothing_to_the_ledger_and_is_deterministic(env):
    _seed(env)
    # The env fixture points the default ledger dir at tmp, so this checks the
    # path a real rebuild would write.
    assert R._ledger_path() == env["tmp"] / "mt" / R.LEDGER_FILENAME
    a = R.build_target_format_census(_build(env))
    b = R.build_target_format_census(_build(env))
    assert a == b
    assert not R._ledger_path().exists()
    assert a["inputs"]["underlyingTradeSetSha256"] == b["inputs"]["underlyingTradeSetSha256"]


def _snapshot(root) -> dict[str, tuple[int, int, bytes]]:
    import hashlib

    return {
        str(p.relative_to(root)): (
            p.stat().st_size,
            p.stat().st_mtime_ns,
            hashlib.sha256(p.read_bytes()).digest(),
        )
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def test_cli_census_writes_json_and_markdown(env, tmp_path):
    import importlib.util
    import os
    from pathlib import Path

    _seed(env)
    # A pre-existing canonical ledger at the default path the CLI would
    # rebuild: --census must leave its bytes and mtime untouched.
    ledger_file = R._ledger_path()
    assert ledger_file == tmp_path / "mt" / R.LEDGER_FILENAME
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    ledger_file.write_bytes(b"pre-existing canonical ledger sentinel")
    os.utime(ledger_file, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    spec = importlib.util.spec_from_file_location(
        "mtl_cli", Path(__file__).resolve().parents[2] / "scripts" / "market_trade_ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    directory = tmp_path / "players.json"
    from tests.trade.market_trade_fixtures import DIRECTORY

    directory.write_text(json.dumps(DIRECTORY), encoding="utf-8")
    out = tmp_path / "census_out"
    before = _snapshot(tmp_path)
    ledger_before = (ledger_file.read_bytes(), ledger_file.stat().st_mtime_ns)
    rc = mod.main(
        [
            "--census",
            "--out",
            str(out),
            "--archive-path",
            str(env["archive"]),
            "--intel-ledger-path",
            str(env["intel"]),
            "--lanes",
            f"{N.SOURCE_KTC},{N.SOURCE_SLEEPER_DISCOVERY}",
            "--player-directory",
            str(directory),
            "--target-league",
            "no_such_league_for_test",
        ]
    )
    assert rc == 0
    jsons = list(out.glob("target_format_census_*.json"))
    mds = list(out.glob("target_format_census_*.md"))
    assert len(jsons) == 1 and len(mds) == 1
    payload = json.loads(jsons[0].read_text(encoding="utf-8"))
    assert payload["censusVersion"] == R.CENSUS_VERSION
    # An unknown target league: every comparison is UNKNOWN, never a match.
    assert payload["sections"]["matchToTarget"]["trades"]["byState"] == {"UNKNOWN": 15}
    _assert_no_planted_ids(jsons[0].read_text(encoding="utf-8"))
    _assert_no_planted_ids(mds[0].read_text(encoding="utf-8"))
    assert mds[0].read_text(encoding="utf-8").startswith("# Target-format evidence census")

    # READ-ONLY: the canonical ledger is byte- and mtime-identical, every input
    # store is unchanged, and the ONLY new files are the two census outputs.
    assert (ledger_file.read_bytes(), ledger_file.stat().st_mtime_ns) == ledger_before
    after = _snapshot(tmp_path)
    assert {k: after[k] for k in before} == before
    new = set(after) - set(before)
    # Opening an input SQLite store to READ it may leave reader sidecars; an
    # empty -wal proves no page was written.  Nothing else may appear.
    sidecars = {k for k in new if k.endswith(("-wal", "-shm"))}
    for k in sidecars:
        assert Path(tmp_path / k[: -len("-wal")]).name in {
            env["intel"].name,
            env["archive"].name,
        }, k
        if k.endswith("-wal"):
            assert after[k][0] == 0, f"{k} holds WAL frames: something was written"
    assert new - sidecars == {
        str(jsons[0].relative_to(tmp_path)),
        str(mds[0].relative_to(tmp_path)),
    }


@pytest.mark.parametrize("ltype", [0, 1, None], ids=["redraft", "keeper", "missing_type"])
def test_non_dynasty_or_unverified_league_is_never_exact_or_near(ltype):
    lg = sleeper_league("X", ltype=0 if ltype is None else ltype)
    if ltype is None:
        del lg["settings"]["type"]
    src = F.format_from_sleeper_league(lg)
    # Same card and lineup as the target: only the game type differs / is unknown.
    assert src.card_hash == TARGET.card_hash
    axes = F.compare_formats(src, TARGET)
    state = R.near_state(src, TARGET, axes)
    assert state not in ("EXACT", "NEAR")
    if ltype is None:
        assert axes["dynastyState"]["state"] == F.UNKNOWN
        assert R.exact_state(src, TARGET) is None
        assert state == R.UNKNOWN_CELL
    else:
        assert axes["dynastyState"]["state"] == F.DIFFERENT
        assert R.exact_state(src, TARGET) is False
        assert state == R.NOT_DYNASTY
    # ... and a verified dynasty twin of the same league IS exact.
    twin = F.format_from_sleeper_league(sleeper_league("X"))
    assert R.near_state(twin, TARGET, F.compare_formats(twin, TARGET)) == "EXACT"


def test_non_dynasty_leagues_stay_out_of_exact_counts(env):
    _seed(env, non_dynasty=True)
    c = R.target_format_census(_build(env))
    m = c["sections"]["matchToTarget"]
    assert m["trades"]["byState"]["EXACT"] == 6
    assert m["trades"]["byState"]["NEAR"] == 5
    assert m["trades"]["byState"][R.NOT_DYNASTY] == 2  # redraft + keeper
    assert m["trades"]["byState"][R.UNKNOWN_CELL] == 2  # partial + missing type
    assert m["trades"]["exactIdpTrades"] == 6
    assert m["trades"]["exactAndNativeComparable"] == 6
    assert m["leagues"]["byState"] == {
        "EXACT": 6,
        "NEAR": 5,
        "NOT_NEAR": 2,
        R.NOT_DYNASTY: 2,
        R.UNKNOWN_CELL: 2,
    }
    rules = c["definitions"]
    assert "dynastyState" in rules["exact"] and "dynastyState" in rules["near"]
    _assert_no_planted_ids(json.dumps(R.build_target_format_census(_build(env)), default=str))


def test_trade_level_fold_counts_distinct_leagues_not_trades():
    # One league with six trades at a rare value: folded despite six trades.
    values = ["3-3"] * 6 + ["1-2"] * 5 + ["9-9"] * 7 + [None]
    leagues = [("sleeper", "A")] * 6 + [("sleeper", str(i)) for i in range(5)] + [None] * 7
    leagues += [("sleeper", "B")]
    assert R._dist(values, fold_small=True, leagues=leagues) == {
        "1-2": 5,
        R.OTHER_SMALL_CELLS: 13,  # 6 one-league trades + 7 trades with no league identity
        R.UNKNOWN_CELL: 1,
    }
    with pytest.raises(ValueError):
        R._dist(["a"], fold_small=True, leagues=[])


def test_rare_te_scoring_key_is_not_named():
    rare = dict(TARGET_SCORING) | {"bonus_rec_te": 0.5}
    fmts = [F.format_from_sleeper_league(sleeper_league(str(i), scoring=rare)) for i in range(4)]
    fmts += [F.format_from_sleeper_league(sleeper_league(str(10 + i))) for i in range(5)]
    league_level = R._te_block(fmts)
    assert "bonus_rec_te" not in league_level["teScoringKeyValues"]
    assert "bonus_fd_te" in league_level["teScoringKeyValues"]  # all 9 leagues use it
    assert league_level["teScoringKeysFoldedBelowMinLeagues"] == 1
    # Trade level: four leagues with many trades each still do not name the key.
    trade_fmts = [f for f in fmts[:4] for _ in range(3)] + fmts[4:]
    trade_leagues = [i for i in range(4) for _ in range(3)] + list(range(10, 15))
    trade_level = R._te_block(trade_fmts, trade_leagues)
    assert "bonus_rec_te" not in trade_level["teScoringKeyValues"]
    assert trade_level["teScoringKeysFoldedBelowMinLeagues"] == 1


def test_stale_target_scoring_refuses_exact_and_near(env):
    import dataclasses

    _seed(env)
    stale = dataclasses.replace(
        TARGET,
        vendor=dict(TARGET.vendor)
        | {"scoringEvidence": "stale", "staleScoringAcceptedForResearch": True},
    )
    result = R.build_ledger(
        archive_path=env["archive"],
        intel_ledger_path=env["intel"],
        league_keys=[],
        ctx=ctx(),
        target_format=stale,
        lanes=(N.SOURCE_KTC, N.SOURCE_SLEEPER_DISCOVERY),
    )
    c = R.target_format_census(result)
    assert c["inputs"]["staleScoringAcceptedForResearch"] is True
    m = c["sections"]["matchToTarget"]
    assert m["staleTargetScoringRefusal"]["refused"] is True
    assert "EXACT" not in m["trades"]["byState"] and "NEAR" not in m["trades"]["byState"]
    assert "EXACT" not in m["leagues"]["byState"] and "NEAR" not in m["leagues"]["byState"]
    assert m["trades"]["exactIdpTrades"] == 0
    sim = c["sections"]["idp"]["scoringSimilarity"]["comparison"]
    assert sim["degraded"] == "stale_target_scoring_accepted_for_research"
    # Fresh evidence: nothing refused.
    fresh = R.target_format_census(_build(env))
    assert fresh["inputs"]["staleScoringAcceptedForResearch"] is False
    assert fresh["sections"]["matchToTarget"]["staleTargetScoringRefusal"]["refused"] is False


def test_idp_unknown_leagues_excluded_from_similarity_are_counted(built):
    s = R.target_format_census(built)["sections"]
    sim = s["idp"]["scoringSimilarity"]
    # The partial league (format never captured) has an UNKNOWN IDP state: it
    # is excluded from the similarity block and COUNTED, not dropped silently.
    assert sim["leaguesExcludedIdpEnabledUnknown"] == s["leagues"]["idpEnabled"]["UNKNOWN"] == 1


def test_target_positions_fixture_is_the_dynasty_main_shape():
    # Guards the fixture the EXACT cases rely on.
    assert TARGET.idp_starters == 9 and TARGET.superflex is True
    assert len(TARGET_POSITIONS) == 58
