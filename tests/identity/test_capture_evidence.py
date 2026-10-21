"""U2 / U2b identity evidence of a scraper capture (outlier-integrity V2.1 §3.7).

Pins the identity owner's capture-evidence vocabulary
(``src/identity/capture_evidence.py``): what the scraper adapter records, how a
stamp survives only while it still describes its payload row, how the sidecar
binds to one payload, and the U2b rule that an unobservable format state is
``None`` rather than the requested state restated.

Replay fixture: ``tests/fixtures/identity_capture/ktc_players_array_2026-10-13.json``
— the identity fields of the committed KTC capture
(``tests/fixtures/ktc/trade_calculator_2026-10-13.html``) verbatim, with
SYNTHETIC value blocks (the trimmed capture carries none).  No live request.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from src.identity import capture_evidence as ce
from src.identity import resolution as r
from src.sources import ktc_value_sources as kvs

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests/fixtures/identity_capture/ktc_players_array_2026-10-13.json"
TS = "2026-10-20T17:35:27.000000+00:00"


def _clean(name: str) -> str:
    return " ".join(str(name).split())


def _ktc_capture():
    rows = json.loads(FIXTURE.read_text())["playersArray"]
    obs = kvs.observations_from_players_array(rows, kvs.KTC_CROWD)

    class _Cap:
        page_url = "https://keeptradecut.com/dynasty-rankings?sf=true&tep=0"
        content_hash = kvs._content_hash(obs)

    cap = _Cap()
    cap.rows = obs
    return cap


# ── the replay fixture is the committed capture's identity, verbatim ──


def test_fixture_identity_fields_match_the_committed_ktc_capture():
    html = (REPO / "tests/fixtures/ktc/trade_calculator_2026-10-13.html").read_text()
    from src.sources.ktc_identity import extract_embedded_array

    committed = {r_["playerID"]: r_ for r_ in extract_embedded_array(html, "playersArray") or []}
    rows = json.loads(FIXTURE.read_text())["playersArray"]
    assert rows
    for row in rows:
        src = committed[row["playerID"]]
        for key in ("playerName", "position", "team", "age"):
            assert row[key] == src[key], (row["playerID"], key)


def test_ktc_observation_carries_team_and_age_but_not_in_the_content_hash():
    rows = json.loads(FIXTURE.read_text())["playersArray"]
    obs = kvs.observations_from_players_array(rows, kvs.KTC_CROWD)
    gibbs = next(o for o in obs if o.name == "Jahmyr Gibbs")
    assert (gibbs.position, gibbs.team, gibbs.age, gibbs.player_id) == ("RB", "DET", 24.6, 1415)
    stripped = [{k: v for k, v in row.items() if k not in ("team", "age")} for row in rows]
    assert kvs._content_hash(obs) == kvs._content_hash(
        kvs.observations_from_players_array(stripped, kvs.KTC_CROWD)
    )


# ── U2: entries, attachments, rungs ────────────────────────────────────


def test_ktc_capture_records_page_position_fields_and_observed_format():
    col = ce.CaptureEvidenceCollector()
    col.record_ktc_capture(_ktc_capture(), _clean, True)
    col.attach(
        "ktc", "Jahmyr Gibbs", "Jahmyr Gibbs", 9000, ["roster_exact", "identity:exact_clean"]
    )
    side = col.build_sidecar({"Jahmyr Gibbs": {"ktc": 9000}}, scrape_timestamp=TS)
    stamp = side["sources"]["ktc"]["attached"]["Jahmyr Gibbs"]
    assert stamp["pagePosition"] == 1
    assert (stamp["position"], stamp["team"], stamp["vendorId"]) == ("RB", "DET", "1415")
    assert stamp["acquisition"] == ce.ACQ_VALUE_SOURCE_CAPTURE
    assert stamp["via"] == ce.VIA_SCRAPER_EXACT
    assert stamp["valueKey"] == "superflexValues.value"
    tog = side["sources"]["ktc"]["toggles"]
    assert tog["superflex"]["observed"] is True
    assert tog["tePremium"] == {
        "requested": "none",
        "observed": "none",
        "evidence": "superflexValues.value",
        "rowsObserved": tog["rows"] - 1,  # the pick row carries no value
    }
    assert tog["urlParams"] == {"sf": "true", "tep": "0"}
    tep = side["sources"]["ktcSfTep"]["toggles"]["tePremium"]
    assert tep["observed"] == "TE++" and tep["evidence"] == "superflexValues.tepp"


def test_cache_capture_observes_no_format_state():
    col = ce.CaptureEvidenceCollector()
    col.record_cache_capture("ktc", {"Jahmyr Gibbs": 9000}, True, "none")
    col.attach("ktc", "Jahmyr Gibbs", "Jahmyr Gibbs", 9000, ["roster_exact"])
    side = col.build_sidecar({"Jahmyr Gibbs": {"ktc": 9000}}, scrape_timestamp=TS)
    tog = side["sources"]["ktc"]["toggles"]
    assert tog["superflex"] == {"requested": True, "observed": None}
    assert tog["tePremium"]["observed"] is None
    stamp = side["sources"]["ktc"]["attached"]["Jahmyr Gibbs"]
    assert stamp["acquisition"] == ce.ACQ_CACHE
    assert "pagePosition" not in stamp and "position" not in stamp


def test_checkbox_toggles_only_a_boolean_read_is_observed():
    col = ce.CaptureEvidenceCollector()
    col.record_checkbox_toggles("idpTradeCalc", True, True, True, None, {"value_sftep": 3})
    side = col.build_sidecar({}, scrape_timestamp=TS)
    tog = side["sources"]["idpTradeCalc"]["toggles"]
    assert tog["superflex"] == {"requested": True, "observed": True}
    assert tog["tePremium"] == {"requested": True, "observed": None}
    assert tog["valueKeys"] == {"value_sftep": 3}


@pytest.mark.parametrize(
    ("steps", "acq", "via"),
    [
        (["roster_exact", "identity:exact_clean"], ce.ACQ_API_INTERCEPT, ce.VIA_SCRAPER_EXACT),
        (["roster_lookup", "identity:exact_lookup"], ce.ACQ_API_INTERCEPT, ce.VIA_SCRAPER_EXACT),
        (["roster_unmapped"], ce.ACQ_API_INTERCEPT, ce.VIA_SCRAPER_EXACT),
        (["roster_initial"], ce.ACQ_API_INTERCEPT, ce.VIA_SCRAPER_SURNAME),
        (["roster_exact", "identity:initial_last"], None, ce.VIA_SCRAPER_SURNAME),
        (["roster_exact"], ce.ACQ_AUTOCOMPLETE, ce.VIA_SCRAPER_SURNAME),
        (["roster_fuzzy"], ce.ACQ_AUTOCOMPLETE, ce.VIA_SCRAPER_FUZZY),
        (["roster_exact", "identity:fuzzy_guarded"], None, ce.VIA_SCRAPER_FUZZY),
        (["roster_exact", ce.RUNG_MERGE_FIRST_NAME], None, ce.VIA_SCRAPER_FIRST_NAME),
        (["roster_exact", ce.RUNG_MERGE_PUNCTUATION], None, ce.VIA_SCRAPER_EXACT),
    ],
)
def test_the_weakest_step_decides_the_via(steps, acq, via):
    assert ce.via_for_steps(steps, acq) == via


def test_only_the_exact_scraper_rung_is_an_exact_join_rung():
    assert ce.VIA_SCRAPER_EXACT in r.EXACT_JOIN_RUNGS
    for low in (ce.VIA_SCRAPER_SURNAME, ce.VIA_SCRAPER_FUZZY, ce.VIA_SCRAPER_FIRST_NAME):
        assert low not in r.EXACT_JOIN_RUNGS


def test_a_stamp_survives_only_while_it_describes_its_payload_row():
    col = ce.CaptureEvidenceCollector()
    for name, val in (("A One", 100), ("B Two", 200), ("C Three", 300)):
        col.add_entry("idpTradeCalc", name, val, acquisition=ce.ACQ_API_INTERCEPT, page_position=1)
    col.attach("idpTradeCalc", "A One", "A One", 100, ["roster_exact"])
    col.attach("idpTradeCalc", "B Two", "B Two", 200, ["roster_exact"])  # row repriced
    col.attach("idpTradeCalc", "C Three", "C Three", 300, ["roster_exact"])  # row gone
    col.attach("idpTradeCalc", "D Four", "D Four", 400, ["roster_exact"])  # never captured
    players = {
        "A One": {"idpTradeCalc": 100},
        "B Two": {"idpTradeCalc": 250},
        "D Four": {"idpTradeCalc": 400},
    }
    side = col.build_sidecar(players, scrape_timestamp=TS)
    attached = side["sources"]["idpTradeCalc"]["attached"]
    assert set(attached) == {"A One", "D Four"}
    assert attached["D Four"]["entry"] == "not_captured"
    assert side["census"]["idpTradeCalc"]["dropped"] == {
        "entryNotCaptured": 1,
        "rowMissing": 1,
        "valueMismatch": 1,
    }


def test_merges_move_only_the_slots_the_primary_took():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "TJ Watt", 5000, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE)
    col.add_entry("idpTradeCalc", "TJ Watt", 4000, acquisition=ce.ACQ_API_INTERCEPT)
    col.attach("ktc", "TJ Watt", "TJ Watt", 5000, ["roster_unmapped"])
    col.attach("idpTradeCalc", "TJ Watt", "TJ Watt", 4000, ["roster_unmapped"])
    col.merge("TJ Watt", "T.J. Watt", ce.RUNG_MERGE_PUNCTUATION, ["ktc"])
    side = col.build_sidecar(
        {"T.J. Watt": {"ktc": 5000, "idpTradeCalc": 3900}}, scrape_timestamp=TS
    )
    stamp = side["sources"]["ktc"]["attached"]["T.J. Watt"]
    assert stamp["rung"] == ["roster_unmapped", ce.RUNG_MERGE_PUNCTUATION]
    assert side["sources"]["idpTradeCalc"]["attached"] == {}
    assert side["census"]["idpTradeCalc"]["mergeDiscarded"] == 1


def test_in_source_duplicates_are_carried_as_candidates_for_a4():
    col = ce.CaptureEvidenceCollector()
    col.add_entry(
        "idpTradeCalc",
        "Byron Murphy",
        3000,
        acquisition=ce.ACQ_API_INTERCEPT,
        position="DT",
        team="SEA",
        page_position=40,
    )
    col.add_entry(
        "idpTradeCalc",
        "Byron Murphy",
        2500,
        acquisition=ce.ACQ_API_INTERCEPT,
        position="CB",
        team="MIN",
        page_position=90,
    )
    col.attach("idpTradeCalc", "Byron Murphy II", "Byron Murphy", 3000, ["roster_lookup"])
    side = col.build_sidecar({"Byron Murphy II": {"idpTradeCalc": 3000}}, scrape_timestamp=TS)
    stamp = side["sources"]["idpTradeCalc"]["attached"]["Byron Murphy II"]
    assert stamp["chosen"] == 0 and len(stamp["candidates"]) == 2
    cands, chosen = ce.entry_candidates(stamp)
    assert [c.position for c in cands] == ["DT", "CB"] and chosen == 0
    assert cands[0].raw_name == "Byron Murphy" and cands[1].value == 2500.0


def test_an_ambiguous_entry_writes_no_u3_cells():
    col = ce.CaptureEvidenceCollector()
    col.add_entry(
        "ktc", "Same Name", 100, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="WR", team="NYJ"
    )
    col.add_entry(
        "ktc", "Same Name", 100, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="RB", team="DAL"
    )
    assert col.entry_fields("ktc", "Same Name", 100) == {}
    col.add_entry(
        "ktc", "Solo", 50, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="te", team="buf "
    )
    assert col.entry_fields("ktc", "Solo", 50) == {"position": "TE", "team": "BUF"}
    assert col.entry_fields("ktc", "Solo", 51) == {}


def test_an_unknown_acquisition_path_is_refused():
    with pytest.raises(ValueError):
        ce.CaptureEvidenceCollector().add_entry("ktc", "X", 1, acquisition="guess")


def test_recovered_partial_marks_every_stamp_of_the_capture():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("idpTradeCalc", "Q", 10, acquisition=ce.ACQ_AUTOCOMPLETE, queried_name="Q")
    col.attach("idpTradeCalc", "Q", "Q", 10, ["roster_exact"])
    col.mark_recovered_partial("idpTradeCalc")
    side = col.build_sidecar({"Q": {"idpTradeCalc": 10}}, scrape_timestamp=TS)
    block = side["sources"]["idpTradeCalc"]
    assert block["capture"] == ce.CAPTURE_RECOVERED_PARTIAL
    assert block["attached"]["Q"]["capturePartial"] is True
    assert block["attached"]["Q"]["via"] == ce.VIA_SCRAPER_SURNAME


def test_reset_all_forgets_a_previous_run():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "Q", 10, acquisition=ce.ACQ_CACHE)
    col.attach("ktc", "Q", "Q", 10, ["roster_exact"])
    col.reset_all()
    side = col.build_sidecar({"Q": {"ktc": 10}}, scrape_timestamp=TS)
    assert side["sources"]["ktc"]["attached"] == {}


def test_reset_source_forgets_a_retried_attempt():
    col = ce.CaptureEvidenceCollector()
    col.add_entry("idpTradeCalc", "Q", 10, acquisition=ce.ACQ_API_INTERCEPT)
    col.reset_source("idpTradeCalc")
    assert col.build_sidecar({}, scrape_timestamp=TS)["sources"]["idpTradeCalc"]["entryCount"] == 0


# ── the sidecar: written next to the payload, bound to it ──────────────


def _write(tmp_path, payload):
    path = tmp_path / ce.SIDECAR_REL
    ce.write_sidecar(payload, path)
    return path


def test_sidecar_binds_only_to_its_own_payload(tmp_path):
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A", 1, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="QB")
    col.attach("ktc", "A", "A", 1, ["roster_exact"])
    _write(tmp_path, col.build_sidecar({"A": {"ktc": 1}}, scrape_timestamp=TS))
    ev, state = ce.load_capture_evidence(tmp_path, "2026-10-20T17:35:27Z")
    assert state == ce.STATE_BOUND and ev.stamp_for("ktc", "A")["position"] == "QB"
    assert ev.stamp_for("ktc", "B") is None and ev.stamp_for("nope", "A") is None
    assert ce.load_capture_evidence(tmp_path, "2026-10-20T19:35:27Z") == (
        None,
        ce.STATE_TIMESTAMP_MISMATCH,
    )
    assert ce.load_capture_evidence(tmp_path, None)[1] == ce.STATE_TIMESTAMP_MISMATCH
    assert ce.load_capture_evidence(tmp_path / "x", TS) == (None, ce.STATE_MISSING)


def test_sidecar_schema_and_garbage_are_not_evidence(tmp_path):
    path = tmp_path / ce.SIDECAR_REL
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    assert ce.load_capture_evidence(tmp_path, TS)[1] == ce.STATE_UNREADABLE
    path.write_text(json.dumps({"schema": "other", "scrapeTimestamp": TS, "sources": {}}))
    assert ce.load_capture_evidence(tmp_path, TS)[1] == ce.STATE_SCHEMA_MISMATCH


def test_archive_sidecar_installs_into_a_replay_tree(tmp_path):
    col = ce.CaptureEvidenceCollector()
    payload = col.build_sidecar({}, scrape_timestamp=TS)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(ce.SIDECAR_FILENAME, json.dumps(payload))
    assert ce.install_sidecar_from_archive(buf.getvalue(), tmp_path) is True
    assert ce.load_capture_evidence(tmp_path, TS)[1] == ce.STATE_BOUND
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as zf:
        zf.writestr("manifest.json", "{}")
    assert ce.install_sidecar_from_archive(empty.getvalue(), tmp_path / "other") is False


def test_published_cells_are_verbatim_never_guessed():
    assert ce.published_position(" wr ") == "WR"
    assert ce.published_position("WR12") == "WR12"  # no positional rank stripped
    assert ce.published_position(None) == ""
    assert ce.published_team(" det") == "DET"
    assert ce.IDENTITY_CSV_COLUMNS == ("position", "team")
