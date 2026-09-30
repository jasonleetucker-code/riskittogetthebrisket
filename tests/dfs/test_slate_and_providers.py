"""Phase A — canonical slate, platform-file detection, licensed-feed adapter, failure states.

All inline CSV / JSON here is SYNTHETIC (invented teams, names and IDs) and is
shaped after the documented layouts; it is not a real platform template.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import feature_flags
from src.dfs import api as dfs_api
from src.dfs import providers
from src.dfs.imports import ImportError_
from src.dfs.slate import canonical_from_platform_file, detect_platform_file

FIX = Path(__file__).parent / "fixtures"
DK_HEAD = "Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame"
FD_HEAD = "Id,Position,First Name,Nickname,Last Name,FPPG,Played,Salary,Game,Team,Opponent,Injury Indicator,Injury Details,Tier,Roster Position"


def _dk(rows):
    return (
        DK_HEAD
        + "\n"
        + "\n".join(
            f"{pos},X ({i}),Syn {i},{i},{roster},5000,AAA@BBB 10/04/2026 07:00PM ET,{team},1.0"
            for i, (pos, roster, team) in enumerate(rows, start=100)
        )
    )


def _fd(rows):
    return (
        FD_HEAD
        + "\n"
        + "\n".join(
            f"1-{i},{pos},Syn,Syn {i},{i},1.0,3,5000,AAA@BBB,{team},BBB,,,,{roster}"
            for i, (pos, roster, team) in enumerate(rows, start=100)
        )
    )


# ── detection ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            _dk([("QB", "QB", "AAA"), ("RB", "RB/FLEX", "AAA"), ("DST", "DST", "BBB")]),
            ("draftkings", "nfl", "classic"),
        ),
        (
            _dk([("QB", "CPT", "AAA"), ("QB", "FLEX", "AAA"), ("WR", "CPT", "BBB")]),
            ("draftkings", "nfl", "showdown_captain"),
        ),
        (
            _dk([("PG", "PG/G/UTIL", "AAA"), ("C", "C/UTIL", "BBB")]),
            ("draftkings", "nba", "classic"),
        ),
        (
            _dk([("C", "C/UTIL", "AAA"), ("W", "W/UTIL", "AAA"), ("G", "G", "BBB")]),
            ("draftkings", "nhl", "classic"),
        ),
        (_dk([("F", "F", "AAA"), ("F", "F", "BBB")]), ("draftkings", "mma", "classic")),
        (_fd([("QB", "QB", "AAA"), ("D", "D", "BBB")]), ("fanduel", "nfl", "classic")),
        (_fd([("PG", "PG", "AAA"), ("C", "C", "BBB")]), ("fanduel", "nba", "classic")),
        (
            _fd([("C", "C", "AAA"), ("D", "D", "AAA"), ("G", "G", "BBB")]),
            ("fanduel", "nhl", "classic"),
        ),
    ],
)
def test_detects_platform_sport_and_format(text, expected):
    d = detect_platform_file(text)
    assert (d.platform, d.sport, d.format) == expected, d.reasons


def test_ambiguous_or_unknown_files_are_not_guessed():
    only_centers = _dk([("C", "C/UTIL", "AAA")])  # NBA and NHL both have C: ambiguous
    assert detect_platform_file(only_centers).sport is None
    assert detect_platform_file("Player,Cost\nA,1\n").platform is None


# ── canonical slate from a platform file ──────────────────────────────


def test_dk_file_becomes_a_canonical_slate_with_provenance_and_unknown_columns():
    text = (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    lines = text.splitlines()
    lines[0] += ",Late Swap Note"
    lines[1] += ",keep me"
    slate, rs, extra = canonical_from_platform_file(
        "\n".join(lines), ("draftkings", "nfl", "classic")
    )
    assert rs.key == "draftkings.nfl.classic@2026.1"
    assert len(slate.events) == 3 and all(e.start_time_utc for e in slate.events)
    assert slate.unknown_columns == ["Late Swap Note"]
    assert slate.athletes[0].extra == {"Late Swap Note": "keep me"}
    assert slate.provenance["sourceKind"] == "platform_csv"
    assert slate.provenance["layoutVerification"] == "assumed"
    assert len(slate.provenance["fileSha256"]) == 64
    assert extra["eligibilityCrossCheck"]["state"] == "agrees"


def test_platform_eligibility_disagreement_is_surfaced_not_resolved():
    # The synthetic FD file labels its defense roster slot "D"; the encoded
    # rule set calls that slot "DEF". The cross-check must say so.
    text = (FIX / "synthetic_fd_nfl_classic_players.csv").read_text(encoding="utf-8")
    _slate, _rs, extra = canonical_from_platform_file(text, ("fanduel", "nfl", "classic"))
    check = extra["eligibilityCrossCheck"]
    assert check["state"] == "disagrees" and check["mismatched"] > 0


def test_wrong_platform_file_is_refused_not_switched():
    text = (FIX / "synthetic_fd_nfl_classic_players.csv").read_text(encoding="utf-8")
    with pytest.raises(ImportError_) as exc:
        canonical_from_platform_file(text, ("draftkings", "nfl", "classic"))
    assert exc.value.code == "CSV_WRONG_PLATFORM"


@pytest.mark.parametrize(
    "text,sport",
    [
        (_dk([("F", "F", "AAA"), ("F", "F", "BBB")]), "mma"),
    ],
)
def test_recognised_but_unencoded_formats_say_so(text, sport):
    with pytest.raises(ImportError_) as exc:
        canonical_from_platform_file(text)
    assert exc.value.code == "UNSUPPORTED_FORMAT"
    assert exc.value.detail["sport"] == sport


# ── licensed feed (SportsDataIO, schema-shaped synthetic payload) ─────

SDIO_SLATE = {
    "SlateID": 9001,
    "Operator": "DraftKings",
    "OperatorSlateID": 777,
    "OperatorName": "Main",
    "OperatorGameType": "Classic",
    "OperatorStartTime": "2026-10-04T13:00:00",
    "NumberOfGames": 1,
    "SalaryCap": 50000,
    "SlateRosterSlots": ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "DST"],
    "RemovedByOperator": False,
    "DfsSlateGames": [
        {
            "SlateGameID": 1,
            "GameID": 55,
            "OperatorGameID": 66,
            "RemovedByOperator": False,
            "Game": {"AwayTeam": "AAA", "HomeTeam": "BBB", "DateTime": "2026-10-04T13:00:00"},
        }
    ],
    "DfsSlatePlayers": [
        {
            "OperatorPlayerID": "501",
            "OperatorPlayerName": "Syn QB",
            "OperatorPosition": "QB",
            "OperatorRosterSlots": ["QB"],
            "OperatorSalary": 7000,
            "SlateGameID": 1,
            "Team": "AAA",
            "PlayerID": 1,
        },
        {
            "OperatorPlayerID": "502",
            "OperatorPlayerName": "Syn Gone",
            "OperatorPosition": "RB",
            "OperatorRosterSlots": ["RB", "FLEX"],
            "OperatorSalary": 5000,
            "SlateGameID": 1,
            "Team": "BBB",
            "RemovedByOperator": True,
        },
        {
            "OperatorPlayerID": "503",
            "OperatorPlayerName": "Syn NoSalary",
            "OperatorPosition": "WR",
            "OperatorRosterSlots": ["WR", "FLEX"],
            "OperatorSalary": None,
            "SlateGameID": 1,
            "Team": "BBB",
        },
    ],
}


def test_sdio_slate_maps_to_canonical_and_refuses_missing_salary():
    slate, report = providers.canonical_from_sportsdataio(SDIO_SLATE, "nfl")
    assert (slate.platform, slate.format, slate.name) == ("draftkings", "classic", "Main")
    assert [a.player_id for a in slate.athletes] == ["501"]
    a = slate.athletes[0]
    assert a.opponent == "BBB" and a.game == "AAA@BBB" and a.eligible_slots == ["QB"]
    assert a.start_time_utc == "2026-10-04T17:00:00+00:00"  # naive ET → UTC
    assert report["removedByOperator"] == 1
    assert report["refused"][0]["reason"] == "missing_salary"
    assert slate.source_salary_cap == 50000
    assert slate.external_ids == {"sportsdataioSlateID": "9001", "operatorSlateID": "777"}


def test_sdio_unknown_operator_or_game_type_is_not_mapped_by_guess():
    with pytest.raises(providers.ProviderError) as exc:
        providers.canonical_from_sportsdataio({**SDIO_SLATE, "Operator": "Yahoo"}, "nfl")
    assert exc.value.code == "UNSUPPORTED_SLATE"
    with pytest.raises(providers.ProviderError) as exc:
        providers.canonical_from_sportsdataio({**SDIO_SLATE, "OperatorGameType": "Tiers"}, "nfl")
    assert exc.value.code == "UNSUPPORTED_FORMAT"


@pytest.fixture()
def flags(monkeypatch):
    def set_(on: bool, key: str | None):
        monkeypatch.setenv("RISKIT_FEATURE_DFS_SPORTSDATAIO_SLATES", "1" if on else "0")
        if key is None:
            monkeypatch.delenv("SPORTSDATAIO_API_KEY", raising=False)
        else:
            monkeypatch.setenv("SPORTSDATAIO_API_KEY", key)
        feature_flags.reload()

    yield set_
    feature_flags.reload()


def test_provider_failure_states(flags):
    flags(False, None)
    with pytest.raises(providers.ProviderError) as exc:
        providers.fetch_slates("nfl", "2026-10-04")
    assert exc.value.code == "PROVIDER_UNAVAILABLE"
    flags(True, None)
    with pytest.raises(providers.ProviderError) as exc:
        providers.fetch_slates("nfl", "2026-10-04")
    assert exc.value.code == "SOURCE_PERMISSION_REQUIRED"
    flags(True, "k")
    for code, expected in (
        (429, "QUOTA_EXCEEDED"),
        (403, "SOURCE_PERMISSION_REQUIRED"),
        (503, "PROVIDER_UNAVAILABLE"),
    ):
        with pytest.raises(providers.ProviderError) as exc:
            providers.fetch_slates("nfl", "2026-10-04", http_get=lambda u, h, t, c=code: (c, b""))
        assert exc.value.code == expected
    with pytest.raises(providers.ProviderError) as exc:
        providers.fetch_slates("mma", "2026-10-04")
    assert exc.value.code == "UNSUPPORTED_SLATE"


def test_credential_goes_in_the_header_never_the_url(flags):
    flags(True, "secret-abc")
    seen = {}

    def http_get(url, headers, timeout):
        seen["url"], seen["headers"] = url, dict(headers)
        return 200, json.dumps([SDIO_SLATE]).encode()

    providers.fetch_slates("nfl", "2026-10-04", http_get=http_get)
    assert "secret-abc" not in seen["url"]
    assert seen["headers"]["Ocp-Apim-Subscription-Key"] == "secret-abc"


# ── API ───────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RISKIT_FEATURE_DFS_WORKSPACE", raising=False)
    feature_flags.reload()
    app = FastAPI()
    app.include_router(dfs_api.router)
    dfs_api.configure_session_resolver(
        lambda req: {"username": req.headers["x-user"]} if req.headers.get("x-user") else None
    )
    yield TestClient(app)
    feature_flags.reload()


def test_auto_detected_import_carries_slate_header_and_honest_freshness(client):
    text = (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    snap = client.post("/api/dfs/slates", json={"salaryCsv": text}, headers={"x-user": "a"}).json()
    assert snap["ruleset"]["key"] == "draftkings.nfl.classic@2026.1"
    assert snap["slate"]["provenance"]["sourceKind"] == "platform_csv"
    fresh = {f["class"]: f for f in snap["freshness"]}
    assert fresh["salary"]["state"] == "as_imported"
    assert fresh["projection"]["state"] == "unavailable"  # none imported: never "current"
    for cls in ("ownership", "sportsbook", "news", "podcast"):
        assert fresh[cls]["state"] == "unavailable"


def test_wrong_platform_is_409_and_detect_does_not_save(client):
    text = (FIX / "synthetic_fd_nfl_classic_players.csv").read_text(encoding="utf-8")
    r = client.post(
        "/api/dfs/slates",
        json={"ruleset": "draftkings.nfl.classic", "salaryCsv": text},
        headers={"x-user": "a"},
    )
    assert r.status_code == 409 and r.json()["error"] == "CSV_WRONG_PLATFORM"
    d = client.post(
        "/api/dfs/slates/detect", json={"salaryCsv": text}, headers={"x-user": "a"}
    ).json()
    assert (
        d["detection"]["platform"] == "fanduel" and d["capability"]["readiness"] == "research_only"
    )


def test_providers_endpoint_reports_status_without_leaking_the_key(client, flags):
    flags(True, "secret-abc")
    r = client.get("/api/dfs/providers", headers={"x-user": "a"})
    assert "secret-abc" not in r.text
    body = r.json()
    assert body["status"]["sportsdataio"]["state"] == "configured_unverified"
    assert {c["sport"] for c in body["matrix"]} == {"nfl", "nba", "nhl", "mma"}
    assert all(c["status"] != "verified" for c in body["matrix"])


def test_provider_slates_unavailable_names_the_fallback(client, flags):
    flags(False, None)
    r = client.get("/api/dfs/provider-slates?sport=nfl&date=2026-10-04", headers={"x-user": "a"})
    assert r.status_code == 503 and r.json()["error"] == "PROVIDER_UNAVAILABLE"
    assert "salary CSV" in r.json()["detail"]["fallback"]


def test_provider_import_creates_a_snapshot_with_cap_cross_check(client, monkeypatch):
    monkeypatch.setattr(providers, "fetch_slates", lambda sport, date, http_get=None: [SDIO_SLATE])
    r = client.post(
        "/api/dfs/provider-slates/import",
        json={"sport": "nfl", "date": "2026-10-04", "providerSlateId": 9001},
        headers={"x-user": "a"},
    )
    assert r.status_code == 201, r.text
    snap = r.json()
    assert snap["salaryCapCrossCheck"] == {"source": 50000, "ruleset": 50000, "agrees": True}
    assert snap["providerReport"]["removedByOperator"] == 1
    assert snap["slate"]["provenance"]["sourceKind"] == "licensed_feed"


def test_contest_links_only_to_the_owners_matching_slate(client):
    text = (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    snap = client.post("/api/dfs/slates", json={"salaryCsv": text}, headers={"x-user": "a"}).json()
    contest = {
        "name": "C",
        "platform": "draftkings",
        "sport": "nfl",
        "format": "classic",
        "entryFee": "5",
        "payoutText": "1 10",
        "slateId": snap["snapshotId"],
    }
    ok = client.post("/api/dfs/contests", json={"contest": contest}, headers={"x-user": "a"})
    assert ok.status_code == 201 and ok.json()["contest"]["slate_id"] == snap["snapshotId"]
    assert (
        client.post(
            "/api/dfs/contests", json={"contest": contest}, headers={"x-user": "b"}
        ).status_code
        == 404
    )
    bad = client.post(
        "/api/dfs/contests",
        json={"contest": {**contest, "platform": "fanduel"}},
        headers={"x-user": "a"},
    )
    assert bad.status_code == 422 and bad.json()["error"] == "INVALID_CONTEST"


def test_end_to_end_slate_contest_projections_constraints_build_validate_export_reimport(client):
    """Addendum §29: the one true end-to-end fixture (synthetic data, real code path)."""
    import csv
    import io

    from src.dfs.optimizer import validate_lineup
    from src.dfs.rules import get_ruleset

    h = {"x-user": "owner"}
    salaries = (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    projections = (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    snap = client.post(
        "/api/dfs/slates", json={"salaryCsv": salaries, "projectionCsv": projections}, headers=h
    ).json()
    assert snap["coverage"]["projected"] == 84
    contest = {
        "name": "Synthetic 20-max",
        "platform": "draftkings",
        "sport": "nfl",
        "format": "classic",
        "entryFee": "20",
        "capacity": 1000,
        "currentEntries": 900,
        "maxEntriesPerUser": 20,
        "existingUserEntries": 0,
        "tieRule": "split_positions",
        "payoutText": "1 $4,000\n2 $2,000\n3-10 $500\n11-200 $50",
        "slateId": snap["snapshotId"],
    }
    saved = client.post("/api/dfs/contests", json={"contest": contest}, headers=h)
    assert saved.status_code == 201
    qb = next(a["player_id"] for a in snap["athletes"] if a["positions"] == ["QB"])
    constraints = {
        "lineups": 5,
        "minUnique": 2,
        "maxExposure": 0.8,
        "locks": [qb],
        "stacks": [
            {"primary": ["QB"], "secondary": ["WR", "TE"], "minSecondary": 1, "bringBack": 0}
        ],
    }
    build = client.post(
        "/api/dfs/builds",
        json={
            "snapshotId": snap["snapshotId"],
            "objective": "projection_baseline",
            "constraints": constraints,
        },
        headers=h,
    ).json()
    assert build["result"]["built"] == 5 and build["result"]["shortfall"] is None
    exported = client.get(f"/api/dfs/builds/{build['buildId']}/export", headers=h)
    assert exported.status_code == 200
    rows = list(csv.reader(io.StringIO(exported.text)))
    rs = get_ruleset("draftkings.nfl.classic")
    assert rows[0] == [s.name for s in rs.slots]
    from src.dfs.imports import parse_draftkings_salaries

    athletes, _ = parse_draftkings_salaries(salaries)
    by_id = {a.player_id: a for a in athletes}
    for row in rows[1:]:  # re-import the export and validate every lineup independently
        assert validate_lineup(list(zip(rows[0], row)), rs, by_id) == []
        assert qb in row
    assert len({tuple(sorted(r)) for r in rows[1:]}) == 5
