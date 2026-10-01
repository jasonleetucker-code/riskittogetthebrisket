"""AL-2a target-format evidence census over the completed-trade ledger.

Synthetic lanes only (no real league, manager or trade).  What is pinned:

* every census quantity the owner directive lists is computed;
* UNKNOWN stays UNKNOWN in every distribution and in exact/near;
* the publishable output carries no league / user / transaction identifier;
* counts below the minimum cell are suppressed and rare values folded;
* dedupe counts are the LEDGER'S OWN groups (no second dedupe);
* the CLI writes JSON + markdown and rebuilds no canonical ledger.
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

EXACT_LEAGUES = [f"L-SECRET-EXACT-{i}" for i in range(6)]
NEAR_LEAGUES = [f"L-SECRET-NEAR-{i}" for i in range(5)]
OFFENSE_LEAGUE = "L-SECRET-OFF-1QB"
PARTIAL_LEAGUE = "L-SECRET-PARTIAL"
SECRET_USER = "MGR-SECRET-OWNER"
SECRET_VIA = "VIA-SECRET-USER"
SECRET_MFL = "MFL-SECRET-99"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from src.intel import store

    A._reset_setup_cache_for_tests()
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    intel = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(intel).close()
    yield {"tmp": tmp_path, "intel": intel, "archive": tmp_path / "mt" / "archive.sqlite"}
    ledger.reset_setup_cache()
    A._reset_setup_cache_for_tests()


def _events(tx: str, league: str, *, idp: bool = True) -> list[dict]:
    owner1, owner2 = f"{SECRET_USER}-1", f"{SECRET_USER}-2"
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


def _league_row(league_id: str, lg: dict | None, *, teams: int = 12) -> dict:
    settings: dict = {"type": 2, "bestBall": 1, "discovery": {"viaUserId": SECRET_VIA}}
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


def _seed(env, *, with_ktc: bool = True) -> None:
    rows = []
    for i, lid in enumerate(EXACT_LEAGUES):
        ledger.ingest_events(_events(f"TX-SECRET-E{i}", lid), path=env["intel"])
        rows.append(_league_row(lid, sleeper_league(lid)))
    near_scoring = dict(TARGET_SCORING) | {"idp_sack": 4.0}
    for i, lid in enumerate(NEAR_LEAGUES):
        ledger.ingest_events(_events(f"TX-SECRET-N{i}", lid), path=env["intel"])
        rows.append(_league_row(lid, sleeper_league(lid, scoring=near_scoring)))
    off = sleeper_league(
        OFFENSE_LEAGUE,
        roster_positions=["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX"] + ["BN"] * 15,
        scoring={"rec": 1.0, "pass_td": 4.0},
        teams=10,
        best_ball=0,
    )
    ledger.ingest_events(_events("TX-SECRET-O", OFFENSE_LEAGUE, idp=False), path=env["intel"])
    rows.append(_league_row(OFFENSE_LEAGUE, off, teams=10))
    # A discovery league whose format was never captured: everything UNKNOWN.
    ledger.ingest_events(_events("TX-SECRET-P", PARTIAL_LEAGUE), path=env["intel"])
    rows.append(_league_row(PARTIAL_LEAGUE, None))
    ledger.upsert_leagues(rows, path=env["intel"])
    if not with_ktc:
        return
    index = KTC_INDEX + [{"playerName": "Echo Edge", "playerID": 21, "position": "DL"}]
    dup = ktc_row(501, [11, 902], [21], settings=ktc_settings(EXACT_LEAGUES[0]))
    mfl = ktc_row(502, [13], [12], settings=ktc_settings(SECRET_MFL, platform="mfl", qbs=1))
    nolg = ktc_row(503, [14], [12], settings=ktc_settings("") | {"id": None})
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


def test_publishable_census_contains_no_identifiers(built):
    pub = R.build_target_format_census(built)
    blob = json.dumps(pub, default=str) + R.census_markdown(pub)
    secrets = [
        *EXACT_LEAGUES,
        *NEAR_LEAGUES,
        OFFENSE_LEAGUE,
        PARTIAL_LEAGUE,
        SECRET_USER,
        SECRET_VIA,
        SECRET_MFL,
        "TX-SECRET",
        "SECRET",
        "utrade:",
        "Echo Edge",
        "Alpha Receiver",
        "player:",
    ]
    for s in secrets:
        assert s not in blob, f"identifier leaked into the census: {s}"
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
    a = R.build_target_format_census(_build(env))
    b = R.build_target_format_census(_build(env))
    assert a == b
    assert not (env["tmp"] / "mt" / R.LEDGER_FILENAME).exists()
    assert a["inputs"]["underlyingTradeSetSha256"] == b["inputs"]["underlyingTradeSetSha256"]


def test_cli_census_writes_json_and_markdown(env, tmp_path):
    import importlib.util
    from pathlib import Path

    _seed(env)
    spec = importlib.util.spec_from_file_location(
        "mtl_cli", Path(__file__).resolve().parents[2] / "scripts" / "market_trade_ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    directory = tmp_path / "players.json"
    from tests.trade.market_trade_fixtures import DIRECTORY

    directory.write_text(json.dumps(DIRECTORY), encoding="utf-8")
    out = tmp_path / "census_out"
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
    assert "SECRET" not in jsons[0].read_text(encoding="utf-8")
    assert "SECRET" not in mds[0].read_text(encoding="utf-8")
    assert mds[0].read_text(encoding="utf-8").startswith("# Target-format evidence census")
    assert not (tmp_path / "mt" / R.LEDGER_FILENAME).exists()


def test_target_positions_fixture_is_the_dynasty_main_shape():
    # Guards the fixture the EXACT cases rely on.
    assert TARGET.idp_starters == 9 and TARGET.superflex is True
    assert len(TARGET_POSITIONS) == 58
