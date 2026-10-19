"""League-maturity census (Chase Upside Trade Market, P1 / G2).

Synthetic trades and synthetic league ids only.  Pins: BOTH maturity readings
reported, the three-season primary bar never relaxed, the two-season research
cohort reported separately, a lower bound never counted as primary, the
exclusion waterfall accounts for EVERY trade, Sleeper-observed vs KTC lanes and
their overlap, small-cell suppression, the long-id refusal, and the read-only
``--census-from-ledger`` CLI over persisted stores with zero network.
"""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from src.intel import ledger
from src.intel import league_filter as lf
from src.trade import market_trade_normalize as norm
from src.trade import market_trade_report as report

REPO = Path(__file__).resolve().parents[2]

SLEEPER = [norm.SOURCE_SLEEPER_DISCOVERY]
KTC = [norm.SOURCE_KTC]


def hop(lid, season, prev=None, *, type_=2, status="complete"):
    return lf.ChainHop(lid, prev, str(season), type_, status, False)


#: Lineage M: 2023..2026 (three completed before 2026).  Lineage N: 2025..2026
#: (one completed).  Lineage P: 2024..2026 with 2024's predecessor unwalked.
CHAIN = {
    h.league_id: h
    for h in (
        hop("SYN-M26", 2026, "SYN-M25", status="in_season"),
        hop("SYN-M25", 2025, "SYN-M24"),
        hop("SYN-M24", 2024, "SYN-M23"),
        hop("SYN-M23", 2023, None),
        hop("SYN-N26", 2026, "SYN-N25", status="in_season"),
        hop("SYN-N25", 2025, None),
        hop("SYN-P26", 2026, "SYN-P25", status="in_season"),
        hop("SYN-P25", 2025, "SYN-P24"),
        hop("SYN-P24", 2024, "SYN-PX"),
    )
}


_SEQ = iter(range(10**6))


def trade(
    lid, *, families=SLEEPER, host="sleeper", dynasty="dynasty", sf=True, dedupe="CONFIRMED_UNIQUE"
):
    n = next(_SEQ)
    return {
        "underlyingTradeId": f"ut:{n:06d}",
        "observationCount": 1,
        "members": [f"obs:{n:06d}"],
        "host": host,
        "hostLeagueId": lid,
        "sourceFamilies": list(families),
        "dedupeState": dedupe,
        "marketFormat": {"general": {"dynastyState": dynasty}, "offense": {"superflex": sf}},
        "sides": [
            [{"kind": "player", "canonicalId": "player:1", "position": "WR"}],
            [{"kind": "player", "canonicalId": "player:2", "position": "RB"}],
        ],
    }


def _groups():
    g = []
    g += [trade("SYN-M26") for _ in range(6)]  # A under both readings
    g += [trade("SYN-M25") for _ in range(5)]  # B point-in-time, A league-level
    g += [trade("SYN-N26") for _ in range(5)]  # below two
    g += [trade("SYN-P26") for _ in range(5)]  # >=2 lower bound -> unresolved
    g += [trade("SYN-Q26") for _ in range(5)]  # chain never walked
    g += [trade("SYN-M26", families=SLEEPER + KTC) for _ in range(5)]  # overlap, A
    g += [trade("KTC-MFL-1", families=KTC, host="mfl") for _ in range(5)]  # no Sleeper chain
    g += [trade("SYN-M26", dynasty=None) for _ in range(5)]  # dynasty unverified
    g += [trade("SYN-M26", dedupe="POSSIBLE_OVERLAP") for _ in range(5)]  # fit unsuitable
    return g


@pytest.fixture
def census():
    return report.maturity_census(_groups(), CHAIN, chain_state="available")


def _stage(rows, name):
    return next(r for r in rows if r["stage"] == name)


def test_both_readings_are_reported(census):
    assert set(census["readings"]) == set(lf.MATURITY_READINGS)


def test_point_in_time_primary_population(census):
    pit = census["readings"][lf.READING_POINT_IN_TIME]
    assert pit["primaryThreeSeasonTrades"] == 11  # 6 + 5 overlap
    assert pit["researchTwoSeasonTrades"] == 10  # M25 exact two + P26 unresolved
    assert pit["cohorts"][lf.COHORT_A]["trades"] == 6 + 5 + 5 + 5  # quality-failed still A
    assert pit["cohorts"][lf.COHORT_B_EXACT]["trades"] == 5
    assert pit["cohorts"][lf.COHORT_B_UNRESOLVED]["trades"] == 5
    assert pit["cohorts"][lf.COHORT_NOT_WALKED]["trades"] == 5


def test_league_level_reading_differs_and_is_not_chosen_silently(census):
    lvl = census["readings"][lf.READING_LEAGUE_LEVEL]
    # The 2025 trades belong to a lineage with three completed seasons today.
    assert lvl["primaryThreeSeasonTrades"] == 16
    assert census["readings"][lf.READING_POINT_IN_TIME]["primaryThreeSeasonTrades"] == 11


def test_waterfall_accounts_for_every_trade(census):
    for reading in census["readings"].values():
        rows = reading["exclusionWaterfall"]
        assert sum(r["tradesRemoved"] for r in rows) + reading["primaryThreeSeasonTrades"] == len(
            _groups()
        )
        assert rows[-1]["tradesRemaining"] == reading["primaryThreeSeasonTrades"]


def test_each_exclusion_is_counted(census):
    rows = census["readings"][lf.READING_POINT_IN_TIME]["exclusionWaterfall"]
    assert _stage(rows, report.STAGE_NON_SLEEPER_HOST)["tradesRemoved"] == 5
    assert _stage(rows, report.STAGE_DYNASTY_UNVERIFIED)["tradesRemoved"] == 5
    fit = _stage(rows, report.STAGE_FIT)
    assert fit["tradesRemoved"] == 5 and fit["byReason"] == {"dedupe_state:POSSIBLE_OVERLAP": 5}
    assert _stage(rows, report.STAGE_CHAIN_NOT_WALKED)["tradesRemoved"] == 5
    assert _stage(rows, report.STAGE_BELOW_TWO)["tradesRemoved"] == 5
    assert _stage(rows, report.STAGE_TWO_SEASON)["tradesRemoved"] == 5
    assert _stage(rows, report.STAGE_TWO_PLUS_UNRESOLVED)["tradesRemoved"] == 5
    lost = census["readings"][lf.READING_POINT_IN_TIME]["dataLostToThreeSeasonRule"]
    assert lost == {"tradesPassingQualityButBelowThree": 20, "ofWhichMaturityUnknown": 10}


def test_independent_counts_include_overlapping_reasons():
    g = [trade("KTC-X", families=KTC, host="mfl", dynasty=None) for _ in range(5)]
    c = report.maturity_census(g, CHAIN, chain_state="available")
    ind = c["readings"][lf.READING_POINT_IN_TIME]["exclusionIndependent"]
    assert ind[report.STAGE_NON_SLEEPER_HOST] == 5 and ind[report.STAGE_DYNASTY_UNVERIFIED] == 5


def test_lanes_and_ktc_overlap(census):
    assert census["lanes"] == {
        report.LANE_BOTH: 5,
        report.LANE_KTC: 5,
        report.LANE_SLEEPER: 36,
    }
    assert census["ktcOverlap"]["groupsInBothLanes"] == 5
    by_lane = census["readings"][lf.READING_POINT_IN_TIME]["cohortByLane"][lf.COHORT_A]
    assert by_lane[report.LANE_BOTH] == 5


def test_leagues_and_lineages_are_counted_not_named(census):
    a = census["readings"][lf.READING_POINT_IN_TIME]["cohorts"][lf.COHORT_A]
    assert a == {"trades": 21, "leagues": 1, "lineages": 1}
    assert "SYN" not in json.dumps(census)


def test_missing_chain_store_is_a_state():
    c = report.maturity_census(_groups(), {}, chain_state="missing")
    pit = c["readings"][lf.READING_POINT_IN_TIME]
    assert c["inputs"]["chainStoreState"] == "missing"
    assert pit["primaryThreeSeasonTrades"] == 0  # unknown, never a pass
    # every trade with a Sleeper season-league (all but the 5 non-Sleeper hosts)
    assert pit["cohorts"][lf.COHORT_NOT_WALKED]["trades"] == len(_groups()) - 5


def test_publishable_census_suppresses_and_refuses_ids():
    g = _groups()[:3]
    pub = report.build_maturity_census(g, CHAIN, chain_state="available")
    pit = pub["readings"][lf.READING_POINT_IN_TIME]
    assert pit["primaryThreeSeasonTrades"] == report.SUPPRESSED
    md = report.maturity_census_markdown(pub)
    assert "Experimental" in md and "Not Voting" in md
    with pytest.raises(ValueError):
        report.assert_no_long_ids('{"x": "' + "9" * 16 + '"}')  # synthetic, built at runtime


def _cli():
    spec = importlib.util.spec_from_file_location(
        "market_trade_ledger_cli", REPO / "scripts/market_trade_ledger.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_census_from_ledger_cli_reads_persisted_stores_only(tmp_path, monkeypatch, capsys):
    root = tmp_path / "mt"
    report.persist_canonical_ledger(_groups(), root=root, built_at="2026-10-19T00:00:00+00:00")
    ipath = tmp_path / "intel.sqlite3"
    conn = sqlite3.connect(ipath)
    ledger.ensure_league_chain_schema(conn)
    for h in CHAIN.values():
        ledger.record_league_chain_hop(
            conn,
            {
                "league_id": h.league_id,
                "season": h.season,
                "status": h.status,
                "previous_league_id": h.previous_league_id or "0",
                "settings": {"type": h.league_type},
            },
            observed_ms=1,
            source="t",
        )
    conn.commit()
    conn.close()

    def no_network(*a, **k):  # pragma: no cover - the assertion is that it never runs
        raise AssertionError("the census must make zero network calls")

    import requests

    monkeypatch.setattr(requests.Session, "request", no_network)
    out = tmp_path / "out"
    rc = _cli().main(
        [
            "--census-from-ledger",
            "--ledger-root",
            str(root),
            "--intel-ledger-path",
            str(ipath),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    printed = json.loads(capsys.readouterr().out)
    body = json.loads(Path(printed["census"]).read_text())
    pit = body["readings"][lf.READING_POINT_IN_TIME]
    assert pit["primaryThreeSeasonTrades"] == 11
    assert body["inputs"]["chainStoreState"] == "available"
    assert "SYN" not in Path(printed["census"]).read_text()
    assert Path(printed["markdown"]).exists()


def test_census_from_ledger_without_a_ledger_exits_3(tmp_path):
    rc = _cli().main(["--census-from-ledger", "--ledger-root", str(tmp_path / "none")])
    assert rc == 3
