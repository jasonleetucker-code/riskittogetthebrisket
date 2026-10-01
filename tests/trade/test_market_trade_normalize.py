"""Every lane -> one normalized shape, identities through the canonical owners."""

from __future__ import annotations

import json

import pytest

from src.intel import ledger
from src.sharp import discovery
from src.sources.ktc_identity import identity_from_rows
from src.trade import market_trade_archive as A
from src.trade import market_trade_normalize as N
from tests.trade.market_trade_fixtures import (
    KTC_INDEX,
    ctx,
    ktc_row,
    sleeper_league,
)

IDENT = identity_from_rows(KTC_INDEX, source="synthetic")


def _raw(row):
    return {
        "sourceNativeId": str(row["id"]),
        "payloadSha256": "x" * 64,
        "payload": row,
        "revision": 1,
        "revisionCount": 1,
        "firstFetchedAt": "2026-10-01T12:00:00+00:00",
    }


def _assets(obs):
    return [a for side in obs["sides"] for a in side]


class TestKtcIdentity:
    def test_player_resolves_through_canonical_v2_with_position(self):
        obs = N.normalize_ktc_row(_raw(ktc_row(1, [11], [12])), IDENT, ctx())
        a = _assets(obs)
        assert [x["canonicalId"] for x in a] == ["player:1001", "player:1002"]
        assert a[0]["resolution"]["policy"] == "canonical_v2"

    def test_unknown_name_stays_unresolved_with_reason(self):
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, [16], [12])), IDENT, ctx()))[0]
        assert a["kind"] == "unresolved" and a["canonicalId"] is None
        assert a["resolution"]["reason"] == "no_candidate"

    def test_ambiguous_homonym_is_refused_not_guessed(self):
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, [15], [12])), IDENT, ctx()))[0]
        assert a["canonicalId"] is None
        assert a["resolution"]["reason"] == "ambiguous"
        assert set(a["resolution"]["candidateIds"]) == {"1005", "1006"}

    def test_no_directory_means_unresolved_never_a_guess(self):
        empty = N.IdentityContext.from_directory(None)
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, [11], [12])), IDENT, empty))[0]
        assert a["resolution"]["reason"] == "identity_directory_unavailable"

    def test_unknown_vendor_id_is_unresolved_with_vendor_reason(self):
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, [99999], [12])), IDENT, ctx()))[0]
        assert a["resolution"]["reason"] == "id_not_in_index"


class TestPickGrades:
    @pytest.mark.parametrize(
        "ref,cid,grade,note",
        [
            ("2026 Pick 1.02", "mpick:2026:r1:s2", "slot", None),
            ("901", "mpick:2027:r1:tearly", "tier", None),
            # KTC's Mid is its default when the host never said: downgraded.
            ("902", "mpick:2027:r1", "generic", "ktc_mid_is_vendor_default"),
            ("2028 Round 5", "mpick:2028:r5", "generic", None),
        ],
    )
    def test_real_grade_is_kept_never_refined(self, ref, cid, grade, note):
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, [ref], [12])), IDENT, ctx()))[0]
        assert a["canonicalId"] == cid
        assert a["pick"]["grade"] == grade
        assert a["pick"]["gradeNote"] == note
        assert a["matchKey"] == cid.split(":s")[0].split(":t")[0], "matching is at generic grade"

    def test_startup_pick_is_kept_but_not_a_market_ref(self):
        a = _assets(
            N.normalize_ktc_row(_raw(ktc_row(1, ["Startup Pick 26.01"], [12])), IDENT, ctx())
        )[0]
        assert a["kind"] == "pick" and a["canonicalId"] is None
        assert a["resolution"]["reason"] == "startup_pick_not_a_market_ref"

    def test_faab_in_a_trade_is_its_own_asset_kind(self):
        a = _assets(N.normalize_ktc_row(_raw(ktc_row(1, ["$3.00"], [12])), IDENT, ctx()))[0]
        assert a["kind"] == "faab" and a["faabAmount"] == 3.0


class TestKtcObservationShape:
    def test_host_and_provenance_and_missing_tx_id(self):
        obs = N.normalize_ktc_row(_raw(ktc_row(1, [11], [12])), IDENT, ctx())
        assert (obs["host"], obs["hostLeagueId"], obs["hostTxId"]) == ("sleeper", "L-SYN-1", None)
        assert obs["provenance"] == ["KTC_MARKET"]
        assert obs["timeFidelity"] == "day"
        assert obs["vendorFlags"]["isUsedInVft"] is True

    def test_archive_lane_reads_latest_revision_and_its_identity_snapshot(self, tmp_path):
        A._reset_setup_cache_for_tests()
        path = tmp_path / "a.sqlite"
        f = A.FetchRecord(
            fetch_id="f1",
            source_family=N.SOURCE_KTC,
            fetched_at="2026-10-01T00:00:00+00:00",
            outcome="archived",
        )
        A.record_fetch(
            f,
            [A.RawObservation("1", ktc_row(1, [11], [12]), "2026-10-01")],
            identity_entries=KTC_INDEX,
            path=path,
        )
        f2 = A.FetchRecord(
            fetch_id="f2",
            source_family=N.SOURCE_KTC,
            fetched_at="2026-10-01T01:00:00+00:00",
            outcome="archived",
        )
        A.record_fetch(f2, [A.RawObservation("1", ktc_row(1, [11], [13]), "2026-10-01")], path=path)
        rows, status = N.ktc_observations(archive_path=path, ctx=ctx())
        assert status["distinctTrades"] == 1 and status["tradesWithRevisions"] == 1
        assert rows[0]["revision"] == 2
        assert [a["canonicalId"] for a in _assets(rows[0])] == ["player:1001", "player:1003"]
        A._reset_setup_cache_for_tests()


# ── Sleeper Sharp-discovery lane ──────────────────────────────────────────


@pytest.fixture
def intel(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    path = tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.connect(path).close()
    yield path
    ledger.reset_setup_cache()


def _ev(
    tx,
    rid,
    action,
    asset,
    *,
    league="L-SYN-1",
    owner=None,
    ts=1_790_866_800_000,
    atype=None,
    disc="",
):
    eid = f"{tx}:r{rid}:{action}:{asset}" + (f":{disc}" if disc else "")
    return {
        "eventId": eid,
        "txId": tx,
        "leagueId": league,
        "ownerId": owner or f"user{rid}",
        "rosterId": str(rid),
        "assetId": asset,
        "assetType": atype or ("pick" if asset.startswith("pick:") else "player"),
        "action": action,
        "txType": "trade",
        "ts": ts,
        "week": 4,
    }


def _trade_events(tx="T1", league="L-SYN-1"):
    return [
        _ev(tx, 1, "add", "2001", league=league),
        _ev(tx, 2, "drop", "2001", league=league),
        _ev(tx, 2, "add", "1001", league=league),
        _ev(tx, 1, "drop", "1001", league=league),
        _ev(tx, 2, "add", "pick:2027:1", league=league, disc="o3"),
        _ev(tx, 1, "drop", "pick:2027:1", league=league, disc="o3"),
    ]


def _league_row(league_id="L-SYN-1", *, captured=True, via="u9"):
    lg = sleeper_league(league_id)
    settings = {"type": 2, "bestBall": 1, "signalEligible": True, "sharpEligible": True}
    if captured:
        from src.trade.market_trade_format import capture_sleeper_league_format

        settings["marketFormat"] = capture_sleeper_league_format(
            lg, captured_at="2026-10-01T00:00:00+00:00"
        )
    settings["discovery"] = {"generation": 1, "viaUserId": via}
    return {
        "league_id": league_id,
        "season": "2026",
        "total_rosters": 12,
        "settings_json": json.dumps(settings),
    }


class TestSleeperDiscoveryLane:
    def test_trade_sides_assets_and_true_idp_position(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        ledger.upsert_leagues([_league_row()], path=intel)
        rows, status = N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx())
        assert status["available"] and len(rows) == 1
        obs = rows[0]
        assert (obs["host"], obs["hostLeagueId"], obs["hostTxId"]) == ("sleeper", "L-SYN-1", "T1")
        sigs = sorted(sorted(a["canonicalId"] for a in s) for s in obs["sides"])
        assert sigs == [["mpick:2027:r1", "player:1001"], ["player:2001"]]
        edge = next(a for a in _assets(obs) if a["canonicalId"] == "player:2001")
        assert edge["position"] == "DL" and edge["truePosition"] == "DE"
        assert obs["formatSource"] == "host_capture_via_discovery"
        assert obs["_format"].idp_enabled is True
        assert obs["sampleProvenance"]["discovery"] == {"generation": 1, "viaUserId": "u9"}

    def test_reads_are_read_only_and_never_migrate(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        before = intel.stat().st_mtime_ns
        N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx())
        assert intel.stat().st_mtime_ns == before

    def test_missing_ledger_is_an_unavailable_lane_not_zero_trades(self, tmp_path):
        rows, status = N.sleeper_discovery_observations(
            ledger_path=tmp_path / "x.sqlite3", ctx=ctx()
        )
        assert rows == [] and status == {"available": False, "reason": "intel_ledger_missing"}

    def test_uncaptured_league_format_is_unknown_not_inferred(self, intel):
        ledger.ingest_events(_trade_events(), path=intel)
        ledger.upsert_leagues([_league_row(captured=False)], path=intel)
        obs = N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx())[0][0]
        fmt = obs["_format"]
        assert obs["formatSource"] == "discovery_row_partial"
        assert fmt.teams == 12 and fmt.dynasty_state == "dynasty"
        assert fmt.demand is None and fmt.scoring is None and fmt.idp_enabled is None

    def test_released_player_inside_a_trade_is_not_an_exchanged_asset(self, intel):
        ev = _trade_events() + [_ev("T1", 1, "drop", "1002")]  # dropped to waivers in the trade
        ledger.ingest_events(ev, path=intel)
        obs = N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx())[0][0]
        assert "player:1002" not in {a["canonicalId"] for a in _assets(obs)}
        assert "released_in_trade:1" in obs["caveats"]


def test_discovery_captures_the_real_league_format_without_extra_calls(intel):
    base = discovery.SLEEPER_BASE
    lg = sleeper_league("L-DISC")
    calls = []

    def http(url):
        calls.append(url)
        return {f"{base}/user/u1/leagues/nfl/2026": [lg], f"{base}/league/L-DISC/users": []}.get(
            url
        )

    seeds = {
        "seedLeagues": [],
        "seedUsers": [{"userId": "u1"}],
        "traversal": {
            "maxGenerations": 2,
            "seasons": ["2026"],
            "perUserLeagueCap": 40,
            "maxLeagueRosters": 32,
            "minLeagueRosters": 6,
            "callBudgetPerRun": 50,
            "sleepSecondsBetweenCalls": 0,
        },
        "limits": {"maxUsersPerRun": 100, "maxLeaguesPerRun": 100},
    }
    discovery.discover(http_get=http, seeds=seeds, ledger_path=intel)
    conn = ledger.connect(intel)
    try:
        settings = json.loads(
            conn.execute("SELECT settings_json FROM leagues WHERE league_id='L-DISC'").fetchone()[0]
        )
    finally:
        conn.close()
    mf = settings["marketFormat"]
    assert mf["roster_positions"][:2] == ["QB", "RB"]
    assert mf["scoring_settings"]["idp_sack"] == 2.92
    assert settings["discovery"]["viaUserId"] == "u1"
    assert not any("/league/L-DISC" == c.split(base)[-1] for c in calls), "no extra league fetch"


def test_host_capture_upgrades_a_ktc_row_from_the_same_league(intel):
    ledger.ingest_events(_trade_events(), path=intel)
    ledger.upsert_leagues([_league_row()], path=intel)
    sleeper_rows, _ = N.sleeper_discovery_observations(ledger_path=intel, ctx=ctx())
    k = N.normalize_ktc_row(_raw(ktc_row(1, [11], [12])), IDENT, ctx())
    obs = sleeper_rows + [k]
    assert N.attach_host_formats(obs) == 1
    assert k["formatSource"] == "host_capture_via_discovery"
    assert k["vendorFormat"]["source"] == "ktc_vendor_settings"
