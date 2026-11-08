"""W05-F003 / W05-F004: a registered source can no longer fail silently.

Every payload and CSV here is SYNTHETIC (CLAUDE.md "Rule for new tests"): these
are statements about our ingestion code, provable with no live board.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api import data_contract as dc
from src.api.data_contract import (
    _load_source_row_floors,
    get_ranking_source_keys,
    validate_api_data_contract,
)

REGISTERED = tuple(sorted(get_ranking_source_keys()))


def _entry(key: str) -> tuple[str, str]:
    cfg = dc._SOURCE_CSV_PATHS[key]
    return (
        (cfg, "value") if isinstance(cfg, str) else (cfg["path"], str(cfg.get("signal", "value")))
    )


def _ingest(tmp_path: Path, key: str, body: str | bytes) -> list[dict]:
    rel, _ = _entry(key)
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    errors: list[dict] = []
    health: dict = {}
    dc._enrich_from_source_csvs(
        [{"canonicalName": "josh allen", "displayName": "Josh Allen", "position": "QB"}],
        parse_errors=errors,
        csv_root=tmp_path,
        ingest_health=health,
    )
    return [e for e in errors if e.get("source") == key]


def _good(key: str, rows: list[tuple[str, str]]) -> str:
    cfg = dc._SOURCE_CSV_PATHS[key]
    _, signal = _entry(key)
    if isinstance(cfg, dict) and cfg.get("rank_from") == "value_order":
        head = "name,value"
    elif signal == "rank":
        head = "name,rank"
    else:
        head = "name,value"
    return head + "\n" + "\n".join(f"{n},{v}" for n, v in rows) + "\n"


def _valid_rows(n: int, rank: bool) -> list[tuple[str, str]]:
    return [
        (f"Player Number{chr(65 + i % 26)}{i}", str(i + 1 if rank else 9000 - i)) for i in range(n)
    ]


# ---- ingestion: every registered source, not a hard-coded four -------------------


@pytest.mark.parametrize("key", REGISTERED)
def test_renamed_header_is_a_schema_mismatch_for_every_registered_source(tmp_path, key):
    errs = _ingest(tmp_path, key, "colA,colB\nJosh Allen,9000\n")
    assert [e["error"] for e in errs] == ["schema_mismatch"], key


@pytest.mark.parametrize("key", REGISTERED)
def test_empty_file_and_header_only_file_are_named_for_every_registered_source(tmp_path, key):
    assert [e["error"] for e in _ingest(tmp_path, key, b"")] == ["source_empty"], key
    assert [e["error"] for e in _ingest(tmp_path, key, _good(key, []))] == ["source_empty"], key


def test_missing_required_column_is_named_with_the_column(tmp_path):
    errs = _ingest(tmp_path, "ktcSfTep", "name,team\nJosh Allen,BUF\n")
    assert errs[0]["error"] == "schema_mismatch"
    assert errs[0]["missingColumns"] == "value"
    errs = _ingest(tmp_path, "dlfIdp", "foo,rank\nJosh Allen,1\n")
    assert errs[0]["error"] == "schema_mismatch"


def test_all_invalid_numeric_fields_report_no_usable_rows(tmp_path):
    errs = _ingest(tmp_path, "ktcSfTep", "name,value\nA Alpha,n/a\nB Beta,--\nC Gamma,x\n")
    assert [e["error"] for e in errs] == ["no_usable_rows"]
    assert errs[0]["invalidNumeric"] == "3"


def test_invalid_numeric_share_is_counted_and_reported_past_the_prior(tmp_path):
    rows = _valid_rows(8, rank=False) + [("Bad One", "oops"), ("Bad Two", "???")]
    errs = _ingest(tmp_path, "ktcSfTep", _good("ktcSfTep", rows))
    assert [e["error"] for e in errs] == ["invalid_numeric_fields"]
    assert errs[0]["invalidNumeric"] == "2" and errs[0]["dataRows"] == "10"


def test_a_few_invalid_fields_are_stamped_but_not_reported(tmp_path):
    rows = _valid_rows(40, rank=False) + [("Bad One", "oops")]
    assert _ingest(tmp_path, "ktcSfTep", _good("ktcSfTep", rows)) == []
    stats = dc._SOURCE_CSV_INGEST_STATS[str(tmp_path / _entry("ktcSfTep")[0])]
    assert stats["invalidNumeric"] == 1 and stats["dataRows"] == 41


def test_duplicate_player_rows_at_scale_are_reported(tmp_path):
    rows = [("Josh Allen", str(9000 - i)) for i in range(6)] + _valid_rows(4, rank=False)
    errs = _ingest(tmp_path, "ktcSfTep", _good("ktcSfTep", rows))
    assert [e["error"] for e in errs] == ["duplicate_rows"]
    assert errs[0]["duplicateNames"] == "5"


def test_duplicate_pick_rows_at_scale_are_reported(tmp_path):
    rows = [("2027 Early 1st", "7000")] * 5 + _valid_rows(5, rank=False)
    errs = _ingest(tmp_path, "ktcSfTep", _good("ktcSfTep", rows))
    assert [e["error"] for e in errs] == ["duplicate_rows"]


def test_a_vendor_listing_one_same_name_player_twice_is_not_a_failure(tmp_path):
    """Healthy vendor boards carry same-name players (<= 2.8% measured)."""
    rows = _valid_rows(60, rank=False) + [(_valid_rows(1, False)[0][0], "100")]
    assert _ingest(tmp_path, "ktcSfTep", _good("ktcSfTep", rows)) == []


def test_a_valid_board_with_a_different_size_passes_cleanly(tmp_path):
    """Seasonal population change: a rookie class of 12 or of 140 is not a defect."""
    for n in (12, 140):
        assert _ingest(tmp_path, "dlfRookieSf", _good("dlfRookieSf", _valid_rows(n, True))) == []


# ---- validator: source-health lane, not the structural lane -----------------------


def _payload(counts: dict[str, int], total: int = 1000, parse_errors=None, **extra) -> dict:
    keys = set(REGISTERED) | set(_load_source_row_floors())
    rows = []
    for i in range(total):
        sites = {k: 5000 - i for k in keys if i < counts.get(k, total)}
        rows.append(
            {
                "displayName": f"P{i}",
                "canonicalName": f"p{i}",
                "playerId": str(1000 + i),
                "position": "WR",
                "team": "FA",
                "age": 25,
                "rookie": False,
                "sourceCount": len(sites),
                "confidenceBucket": "medium",
                "anomalyFlags": [],
                "values": {"rankDerivedValue": 5000 - i},
                "canonicalSiteValues": sites,
            }
        )
    payload = {
        "contractVersion": "2026-03-10.v2",
        "generatedAt": "2026-11-08T00:00:00+00:00",
        "maxValues": {k: 9999 for k in keys},
        "players": {r["displayName"]: {} for r in rows},
        "valueAuthority": {},
        "playersArray": rows,
        "sites": [],
        "sourceParseErrors": parse_errors or [],
    }
    payload.update(extra)
    return payload


def test_every_registered_source_declares_a_thin_floor():
    unfloored = sorted(set(REGISTERED) - set(_load_source_row_floors()))
    assert not unfloored, f"no row-count floor: {unfloored}"


@pytest.mark.parametrize("key", REGISTERED)
def test_abrupt_collapse_is_below_floor_for_every_registered_source(key):
    floor = _load_source_row_floors()[key]
    report = validate_api_data_contract(_payload({key: max(1, floor // 3)}))
    assert any(w.startswith(f"source_below_floor:{key}:") for w in report["warnings"])
    assert f"source_missing:{key}" not in report["sourceHealthErrors"]  # thin, not gone


@pytest.mark.parametrize("key", REGISTERED)
def test_a_population_at_or_above_floor_does_not_warn(key):
    floor = _load_source_row_floors()[key]
    report = validate_api_data_contract(_payload({key: floor}))
    assert not any(w.startswith(f"source_below_floor:{key}:") for w in report["warnings"])


def test_partial_vendor_response_is_degraded_not_structural():
    """Two thin sources flip ``degraded`` and stay out of the structural lane."""
    floors = _load_source_row_floors()
    k1, k2 = "fantasyCalc", "pfkDynasty"
    report = validate_api_data_contract(_payload({k1: floors[k1] // 2, k2: floors[k2] // 2}))
    assert all(
        any(w.startswith(f"source_below_floor:{k}:") for w in report["warnings"]) for k in (k1, k2)
    )
    assert not [e for e in report["sourceHealthErrors"] if e.startswith("source_below_floor")]
    assert not [e for e in report["structuralErrors"] if "below_floor" in e]


def test_unexpectedly_large_population_is_reported_never_refused(monkeypatch):
    monkeypatch.setattr(dc, "_load_source_row_ceilings", lambda: {"fantasyCalc": 500})
    report = validate_api_data_contract(_payload({"fantasyCalc": 900}))
    assert "source_above_expected:fantasyCalc:900:500" in report["warnings"]
    assert not [e for e in report["errors"] if "fantasyCalc" in e]


def test_seasonal_population_change_within_bounds_passes():
    floors = _load_source_row_floors()
    report = validate_api_data_contract(_payload({"dlfRookieSf": floors["dlfRookieSf"] + 20}))
    assert not any(w.startswith("source_below_floor:dlfRookieSf") for w in report["warnings"])


@pytest.mark.parametrize("kind", ["schema_mismatch", "source_empty", "no_usable_rows"])
def test_ingest_failures_are_source_health_errors(kind):
    pe = [{"source": "ktcSfTep", "path": "CSVs/site_raw/ktcSfTep.csv", "error": kind}]
    report = validate_api_data_contract(_payload({}, parse_errors=pe))
    expected = f"source_ingest_failure:ktcSfTep:{kind}"
    assert expected in report["sourceHealthErrors"]
    assert expected not in report["structuralErrors"]
    assert report["ok"] is False


@pytest.mark.parametrize("kind", ["duplicate_rows", "invalid_numeric_fields", "file_not_found"])
def test_quality_findings_warn_without_erroring(kind):
    pe = [{"source": "ktcSfTep", "path": "x", "error": kind}]
    report = validate_api_data_contract(_payload({}, parse_errors=pe))
    assert f"source_parse_error:ktcSfTep:{kind}" in report["warnings"]
    assert not [e for e in report["errors"] if e.startswith("source_ingest_failure")]


def test_unrecognised_seasonal_stamp_fails_closed_for_an_empty_source():
    """The excusal is read through the seasonal owner; a stamp it does not
    recognise excuses nothing, so the failure stands."""
    pe = [{"source": "flockFantasySfRookies", "path": "x", "error": "source_empty"}]
    payload = _payload({"flockFantasySfRookies": 0}, parse_errors=pe)
    payload["sourceSeasonalState"] = {"flockFantasySfRookies": {"state": "garbage"}}
    report = validate_api_data_contract(payload)
    assert (
        "source_ingest_failure:flockFantasySfRookies:source_empty" in report["sourceHealthErrors"]
    )


def test_floor_config_is_valid_json_with_floors_and_ceilings():
    cfg = json.loads(
        (
            Path(dc.__file__).resolve().parents[2] / "config/weights/source_row_floors.json"
        ).read_text(encoding="utf-8")
    )
    assert all(isinstance(v, int) and v > 0 for v in cfg["floors"].values())
    assert all(cfg["ceilings"][k] > cfg["floors"][k] for k in cfg["ceilings"])
