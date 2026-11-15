"""Hardening of the V2.1 upstream identity-capture prerequisites (U2 / U2b / U3 / VID).

These prerequisites only COLLECT evidence.  They must never move a canonical
value, a vote, a rank or a verdict, so the properties pinned here are the ones
that keep "collect" from turning into "decide":

* missing is never zero or a guess (a field the vendor did not publish is absent);
* similar names are never conflated;
* the sidecar and the vendor-id map are deterministic and append-only;
* a failure while recording leaves the previous evidence intact;
* mixed source formats degrade to "no evidence", not to an error or a default;
* nothing here is reachable from a public route.
"""

from __future__ import annotations

import io
import json
import random
import zipfile
from pathlib import Path

import pytest

from src.identity import capture_evidence as ce
from src.identity import resolution as r
from src.identity import vendor_ids as v

REPO = Path(__file__).resolve().parents[2]
TS = "2026-10-21T00:00:00+00:00"
GEN = "2026-10-21T00:00:05+00:00"


def _col_with_rows(order: list[int]) -> tuple[ce.CaptureEvidenceCollector, dict]:
    rows = [
        ("Jahmyr Gibbs", 9000, "RB", "DET"),
        ("Josh Allen", 8800, "QB", "BUF"),
        ("Fred Warner", 5200, "LB", "SF"),
        ("No Fields", 100, None, None),
    ]
    col = ce.CaptureEvidenceCollector()
    players: dict = {}
    for i in order:
        name, val, pos, team = rows[i]
        col.add_entry(
            "idpTradeCalc",
            name,
            val,
            acquisition=ce.ACQ_API_INTERCEPT,
            page_position=i + 1,
            position=pos,
            team=team,
        )
    for i in order:
        name, val, *_ = rows[i]
        col.attach("idpTradeCalc", name, name, val, ["roster_exact"])
        players[name] = {"idpTradeCalc": val}
    return col, players


# ── determinism ────────────────────────────────────────────────────────


def test_sidecar_is_byte_deterministic_for_identical_input():
    first, players = _col_with_rows([0, 1, 2, 3])
    second, _ = _col_with_rows([0, 1, 2, 3])
    a = first.build_sidecar(players, scrape_timestamp=TS, generated_at=GEN)
    b = second.build_sidecar(players, scrape_timestamp=TS, generated_at=GEN)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_attach_order_does_not_change_the_stamps():
    base, players = _col_with_rows([0, 1, 2, 3])
    shuffled = list(range(4))
    random.Random(7).shuffle(shuffled)
    other, _ = _col_with_rows(shuffled)
    a = base.build_sidecar(players, scrape_timestamp=TS, generated_at=GEN)["sources"][
        "idpTradeCalc"
    ]["attached"]
    b = other.build_sidecar(players, scrape_timestamp=TS, generated_at=GEN)["sources"][
        "idpTradeCalc"
    ]["attached"]
    # Stamps are keyed by payload row and sorted on output.  The page position
    # is the ENTRY's own ordinal (it travels with the entry), so it is equal too.
    assert list(a) == sorted(a) and list(b) == sorted(b)
    assert {k: v_ for k, v_ in a.items()} == {k: v_ for k, v_ in b.items()}


def test_written_evidence_and_manifest_are_byte_reproducible(tmp_path):
    col, players = _col_with_rows([0, 1, 2, 3])
    payload = col.build_sidecar(players, scrape_timestamp=TS, generated_at=GEN)
    m1 = ce.write_evidence(payload, tmp_path / "a")
    m2 = ce.write_evidence(payload, tmp_path / "b")
    assert m1 == m2
    for rel in (ce.MANIFEST_REL, ce.EVIDENCE_DIR_REL / m1["evidence"]["filename"]):
        assert (tmp_path / "a" / rel).read_bytes() == (tmp_path / "b" / rel).read_bytes()
    assert (tmp_path / "a" / ce.MANIFEST_REL).read_bytes().endswith(b"\n")


# ── missing is never zero / never a guess ──────────────────────────────


def test_unpublished_fields_are_absent_not_blank_zero_or_requested():
    col, players = _col_with_rows([0, 3])
    stamp = col.build_sidecar(players, scrape_timestamp=TS)["sources"]["idpTradeCalc"]["attached"][
        "No Fields"
    ]
    for key in ("position", "team", "age", "vendorId", "valueKey", "queriedName"):
        assert key not in stamp
    assert stamp["value"] == 100 and stamp["pagePosition"] == 4


@pytest.mark.parametrize("age", [0, -3, 61, float("nan"), float("inf"), True, "n/a", None, ""])
def test_implausible_or_unreadable_age_is_no_evidence(age):
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A", 1, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, age=age)
    col.attach("ktc", "A", "A", 1, ["roster_exact"])
    stamp = col.build_sidecar({"A": {"ktc": 1}}, scrape_timestamp=TS)["sources"]["ktc"]["attached"][
        "A"
    ]
    assert "age" not in stamp


@pytest.mark.parametrize("value", [None, "", "abc", float("nan"), float("inf"), object()])
def test_an_unreadable_value_records_no_entry(value):
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A", value, acquisition=ce.ACQ_CACHE)
    assert col.build_sidecar({}, scrape_timestamp=TS)["sources"]["ktc"]["entryCount"] == 0


def test_a_nameless_entry_records_nothing():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "", 5, acquisition=ce.ACQ_CACHE)
    assert col.build_sidecar({}, scrape_timestamp=TS)["sources"]["ktc"]["entryCount"] == 0


def test_an_unattached_source_never_gets_a_stamp():
    col = ce.CaptureEvidenceCollector()
    col.attach("fantasyCalc", "A", "A", 1, ["roster_exact"])  # not a stamped source
    side = col.build_sidecar({"A": {"fantasyCalc": 1}}, scrape_timestamp=TS)
    assert "fantasyCalc" not in side["sources"]


def test_a_value_that_changed_after_capture_is_dropped_not_restamped():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A", 100, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="QB")
    col.attach("ktc", "A", "A", 100, ["roster_exact"])
    side = col.build_sidecar({"A": {"ktc": 101}}, scrape_timestamp=TS)
    assert side["sources"]["ktc"]["attached"] == {}
    assert side["census"]["ktc"]["dropped"] == {"valueMismatch": 1}


# ── mixed source formats ───────────────────────────────────────────────


def test_entry_dicts_with_mixed_shapes_degrade_to_no_evidence_not_errors():
    col = ce.CaptureEvidenceCollector()
    census: dict[str, int] = {}
    col.record_entry_dicts(
        "idpTradeCalc",
        [
            {"name": "A", "value": 10, "position": "dl", "team": "det", "valueKey": "value_sftep"},
            {"name": "B", "value": "20", "valueKey": "value_sf"},  # string value
            {"name": "C", "value": None},  # no value
            "not a mapping",  # type: ignore[list-item]
            {"name": "", "value": 5},  # no name
            {"name": "D", "value": 30, "pagePosition": 4, "position": 7, "team": ["x"]},
        ],
        ce.ACQ_API_INTERCEPT,
        census,
    )
    assert census == {"value_sf": 1, "value_sftep": 1}
    side = col.build_sidecar({}, scrape_timestamp=TS)
    assert side["sources"]["idpTradeCalc"]["entryCount"] == 3  # A, B, D
    assert side["sources"]["idpTradeCalc"]["acquisition"] == {ce.ACQ_API_INTERCEPT: 3}


def test_the_same_name_from_two_acquisition_paths_stays_two_candidates():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("idpTradeCalc", "A", 10, acquisition=ce.ACQ_API_INTERCEPT, position="DL")
    col.add_entry("idpTradeCalc", "A", 12, acquisition=ce.ACQ_BULK_JS)
    col.attach("idpTradeCalc", "A", "A", 12, ["roster_exact"])
    side = col.build_sidecar({"A": {"idpTradeCalc": 12}}, scrape_timestamp=TS)
    stamp = side["sources"]["idpTradeCalc"]["attached"]["A"]
    # the entry that CARRIED the payload value is the stamped one
    assert stamp["acquisition"] == ce.ACQ_BULK_JS and "position" not in stamp
    assert [c["value"] for c in stamp["candidates"]] == [10.0, 12.0] and stamp["chosen"] == 1


def test_csv_with_no_vendor_id_column_records_nothing():
    assert v.csv_rows_with_vendor_ids("name,value,rank\nA,1,1\n") == []
    assert v.csv_rows_with_vendor_ids("") == []


def test_csv_with_bom_and_alternate_header_spellings_is_read():
    text = "﻿Name,Value,Rank,Player ID,Pos,NFL Team\nJahmyr Gibbs,9000,1,1415,rb,det\n"
    (row,) = v.csv_rows_with_vendor_ids(text)
    assert row == {
        "name": "Jahmyr Gibbs",
        "vendorId": "1415",
        "sleeperId": "",
        "position": "rb",
        "team": "det",
    }


def test_a_similarly_named_column_is_not_a_vendor_id():
    text = "name,value,player_id_source\nA,1,x\n"
    assert v.csv_rows_with_vendor_ids(text) == []


# ── similar names are never conflated ──────────────────────────────────

SIMILAR = {
    "1": {"full_name": "Michael Pittman", "position": "WR", "team": "IND"},
    "2": {"full_name": "Michael Pittman Jr.", "position": "WR", "team": "IND"},
    "3": {"full_name": "Marvin Harrison", "position": "WR", "team": "ARI"},
    "4": {"full_name": "Marvin Harrison Jr.", "position": "WR", "team": "ARI"},
    "5": {"full_name": "Kenneth Walker", "position": "RB", "team": "SEA"},
    "6": {"full_name": "Kenneth Walker III", "position": "RB", "team": "SEA"},
}


@pytest.fixture(scope="module")
def similar_index():
    return r.build_sleeper_index(SIMILAR)


@pytest.mark.parametrize(
    ("raw", "pos", "team"),
    [
        ("Michael Pittman Sr.", "WR", "IND"),  # near name, no such directory player
        ("M. Pittman", "WR", "IND"),  # no initial expansion in a verified join
        ("Marvin Harrisson", "WR", "ARI"),  # typo -> no fuzzy
        ("Kenneth Walker II", "RB", "SEA"),
    ],
)
def test_near_names_never_verified_join(similar_index, raw, pos, team):
    assert v.verified_join(similar_index, raw_name=raw, position=pos, team=team) is None


def test_suffix_collisions_abstain_never_guess(similar_index):
    """The name key drops suffixes, so a directory holding both "X" and "X Jr." on
    one team and family cannot tell the vendor row apart: no mapping, not a pick."""
    for name, pos, team in (
        ("Michael Pittman Jr.", "WR", "IND"),
        ("Marvin Harrison Jr.", "WR", "ARI"),
        ("Kenneth Walker III", "RB", "SEA"),
    ):
        assert v.verified_join(similar_index, raw_name=name, position=pos, team=team) is None


def test_a_unique_suffixed_player_joins_only_on_family_and_team():
    index = r.build_sleeper_index(
        {"4": {"full_name": "Marvin Harrison Jr.", "position": "WR", "team": "ARI"}}
    )
    assert v.verified_join(index, raw_name="Marvin Harrison Jr.", position="WR", team="ARI") == "4"
    assert v.verified_join(index, raw_name="Marvin Harrison Jr.", position="WR", team="IND") is None
    assert v.verified_join(index, raw_name="Marvin Harrison Jr.", position="TE", team="ARI") is None


def test_collector_keeps_suffix_variants_as_distinct_entries():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("idpTradeCalc", "Kenneth Walker", 4000, acquisition=ce.ACQ_API_INTERCEPT)
    col.add_entry("idpTradeCalc", "Kenneth Walker III", 6000, acquisition=ce.ACQ_API_INTERCEPT)
    col.attach("idpTradeCalc", "Kenneth Walker III", "Kenneth Walker III", 6000, ["roster_exact"])
    stamp = col.build_sidecar({"Kenneth Walker III": {"idpTradeCalc": 6000}}, scrape_timestamp=TS)[
        "sources"
    ]["idpTradeCalc"]["attached"]["Kenneth Walker III"]
    assert stamp["vendorName"] == "Kenneth Walker III" and "candidates" not in stamp


def test_a_vendor_id_that_maps_to_two_players_is_never_resolved(tmp_path):
    ns = "provider:keepTradeCut"
    store = tmp_path / "map.jsonl"
    first = v.VidObservation(
        ns, "9", "1", v.BASIS_VENDOR_SLEEPER_ID, "s", "h1", "2026-10-21T00:00:00+00:00"
    )
    other = v.VidObservation(
        ns, "9", "2", v.BASIS_VENDOR_SLEEPER_ID, "s", "h2", "2026-10-21T01:00:00+00:00"
    )
    assert v.append_observations(store, [first, other]) == 2
    assert v.VendorIdMap.load(store).state(ns, "9") == v.STATE_CONFLICT
    # appending the first player again cannot clear the conflict
    v.append_observations(store, [first])
    assert v.VendorIdMap.load(store).resolve(ns, "9") is None


# ── failure and recovery ───────────────────────────────────────────────


def test_a_failed_serialization_leaves_the_previous_evidence_intact(tmp_path):
    col, players = _col_with_rows([0, 1])
    ce.write_evidence(col.build_sidecar(players, scrape_timestamp=TS), tmp_path)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(TypeError):
        ce.write_evidence({"schema": ce.SCHEMA_VERSION, "bad": object()}, tmp_path)
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert after == before
    assert not list(tmp_path.rglob("*.tmp"))


def test_a_sidecar_for_another_scrape_is_never_read(tmp_path):
    col, players = _col_with_rows([0, 1])
    manifest = ce.write_evidence(
        col.build_sidecar(players, scrape_timestamp="2026-10-21T00:00:00+00:00"), tmp_path
    )
    assert ce.load_capture_evidence(tmp_path, "2026-10-21T02:00:00+00:00") == (
        None,
        ce.STATE_TIMESTAMP_MISMATCH,
    )
    # A truncated file (crash mid-copy elsewhere) is unreadable evidence, not partial evidence.
    path = tmp_path / ce.EVIDENCE_DIR_REL / manifest["evidence"]["filename"]
    path.write_bytes(path.read_bytes()[:40])
    assert ce.load_capture_evidence(tmp_path, "2026-10-21T00:00:00+00:00")[1] == (
        ce.STATE_UNREADABLE
    )


def test_recorder_failure_leaves_the_store_untouched(tmp_path):
    index = r.build_sleeper_index(
        {"9221": {"full_name": "Jahmyr Gibbs", "position": "RB", "team": "DET"}}
    )
    site = tmp_path / "site_raw"
    site.mkdir()
    (site / "ktcCrowdSfTep.csv").write_text(
        "name,value,rank,player_id,position,team\nJahmyr Gibbs,9000,1,1415,RB,DET\n",
        encoding="utf-8",
    )
    store = tmp_path / v.STORE_REL
    v.record_from_site_raw(site, index=index, store_path=store, observed_at=TS)
    before = store.read_bytes()
    # an unreadable CSV in the folder is skipped; a changed board appends only
    (site / "broken.csv").write_bytes(b"\xff\xfe\x00bad")
    (site / "ktcTradesSfTep.csv").write_text("", encoding="utf-8")  # empty file: no rows, no error
    again = v.record_from_site_raw(site, index=index, store_path=store, observed_at=TS)
    assert again["appended"] == 0 and store.read_bytes() == before
    # the store path being unwritable raises to the caller (the scraper wraps it), never corrupts
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a directory", encoding="utf-8")
    (site / "ktcCrowdSfTep.csv").write_text(
        "name,value,rank,player_id,position,team\nJahmyr Gibbs,9100,1,1415,RB,DET\n",
        encoding="utf-8",
    )
    with pytest.raises(OSError):
        v.record_from_site_raw(site, index=index, store_path=blocker / "map.jsonl", observed_at=TS)
    assert store.read_bytes() == before


def test_vendor_id_store_survives_a_torn_final_line(tmp_path):
    ns = "provider:keepTradeCut"
    store = tmp_path / "map.jsonl"
    good = v.VidObservation(
        ns, "1", "9", v.BASIS_VENDOR_SLEEPER_ID, "s", "h", "2026-10-21T00:00:00+00:00"
    )
    v.append_observations(store, [good])
    with store.open("a", encoding="utf-8") as fh:
        fh.write('{"namespace": "provider:keepTradeCut", "vendor_id": "2"')  # torn
    assert v.VendorIdMap.load(store).resolve(ns, "1") == "9"
    # the next run appends a NEW line after the torn tail; the torn line stays skipped
    later = v.VidObservation(
        ns, "3", "8", v.BASIS_VENDOR_SLEEPER_ID, "s", "h", "2026-10-21T01:00:00+00:00"
    )
    v.append_observations(store, [later])
    loaded = v.VendorIdMap.load(store)
    assert loaded.resolve(ns, "1") == "9"


# ── archive compatibility ──────────────────────────────────────────────


def test_a_bundle_without_a_manifest_is_absent_evidence_not_an_error(tmp_path):
    old = io.BytesIO()
    with zipfile.ZipFile(old, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("site_raw/ktc.csv", "name,value\nA,1\n")  # pre-U3 shape
    assert ce.manifest_from_archive(old.getvalue()) is None
    assert ce.load_capture_evidence(tmp_path, TS) == (None, ce.STATE_MISSING)
    assert ce.manifest_from_archive(b"not a zip") is None


def test_trailing_columns_do_not_change_the_dataset_a_board_is():
    from src.sources.dataset_integrity import parse_board

    plain = "name,value,rank\nA,100,1\nB,90,2\n"
    wider = "name,value,rank,position,team\nA,100,1,WR,DET\nB,90,2,,\n"
    assert parse_board(plain, signal="value").rows == parse_board(wider, signal="value").rows
    assert v.dataset_hash_of_csv(plain) == v.dataset_hash_of_csv(wider)


# ── no public route can reach the evidence ─────────────────────────────

_EVIDENCE_TOKENS = (
    "identity_capture_evidence",
    "identity_capture_manifest",
    "vendor_id_map",
    "capture_evidence",
    "src.identity.vendor_ids",
)


def test_no_public_surface_references_the_sidecar_or_the_vendor_id_store():
    """``server.py`` (every route) and the frontend never name the evidence files.

    The sidecar lives in ``data/scrape_state`` and the map in ``data/identity``;
    neither directory is mounted or served, and no route handler reads them.
    """
    offenders = []
    for path in [REPO / "server.py", *sorted((REPO / "frontend").glob("app/**/*.js*"))]:
        if "node_modules" in path.parts or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders += [f"{path.name}: {tok}" for tok in _EVIDENCE_TOKENS if tok in text]
    assert not offenders, offenders


def test_the_evidence_directories_are_not_static_mounts():
    text = (REPO / "server.py").read_text(encoding="utf-8")
    assert "app.mount(" in text
    mounts = [ln for ln in text.splitlines() if "app.mount(" in ln]
    assert all("scrape_state" not in ln and "identity" not in ln for ln in mounts)
