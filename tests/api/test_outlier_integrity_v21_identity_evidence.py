"""Outlier integrity V2.1 §3.7: upstream identity evidence on the board path.

U2 / U2b (the scraper's capture sidecar), U3 (identity columns on name-only
boards) and VID (the vendor-id map) are prerequisites P-ID of the wrong-player
gate.  Registered: each is "flags off or stamps only, zero value change (a
byte-identical board is required)"; §9 property 25: with every V2.1 flag OFF
the default board is byte-identical with or without them.

Consumption is V2.1 Layer A only, behind repairs ``U2`` / ``VID`` of the
default-OFF ``outlier_integrity_v21`` flag:

* ``U2`` grades a payload-attached value (``ktc`` / ``ktcSfTep`` /
  ``idpTradeCalc``) on the capture's own stamp, with the §3.5 table: exact
  attach rung → the CSV-join rules; surname / fuzzy rung → A5; A2 on a
  non-exact rung = the vendor name re-resolved through the identity owner names
  a different player.
* ``VID`` gives A1 the vendor-id branch, from the append-only map as it stood
  strictly before the board.

Synthetic rows only (the ``test_source_integrity`` payload); no DEV, R, SPENT
or held-out board is read.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from src.api import data_contract as dc
from src.api import source_integrity as si
from src.identity import capture_evidence as ce
from src.identity import resolution as r
from src.identity import vendor_ids as v
from tests.api.test_source_integrity import ALL_ON, META, PAYLOAD, _csvs, _flags, _rows

V21_ON = (*ALL_ON, "outlier_integrity_v21")
TS = "2026-10-20T17:35:27+00:00"
SRC = "idpTradeCalc"


def _payload():
    payload = copy.deepcopy(PAYLOAD)
    payload["scrapeTimestamp"] = TS
    return payload


def _u3_csvs():
    """The synthetic boards with U3 columns appended to the name-only one
    (fantasyCalc) and a vendor-id column, as the fetchers now write them."""
    csvs = _csvs(META)
    players = PAYLOAD["players"]
    lines = csvs["fantasyCalc.csv"].splitlines()
    out = ["name,value,rank,player_id,position,team"]
    for i, ln in enumerate(lines[1:]):
        name = ln.split(",")[0]
        out.append(f"{ln},{9000 + i},{players[name]['position']},{players[name]['team']}")
    csvs["fantasyCalc.csv"] = "\n".join(out) + "\n"
    return csvs


def _sidecar(stamps: dict[str, dict], ts: str = TS) -> dict:
    col = ce.CaptureEvidenceCollector()
    players = {}
    for row_name, spec in stamps.items():
        value = PAYLOAD["players"][row_name][SRC]
        col.add_entry(
            SRC,
            spec.get("vendorName", row_name),
            value,
            acquisition=spec.get("acquisition", ce.ACQ_API_INTERCEPT),
            page_position=spec.get("pagePosition", 1),
            position=spec.get("position"),
            team=spec.get("team"),
        )
        col.attach(
            SRC,
            row_name,
            spec.get("vendorName", row_name),
            value,
            spec.get("steps", ["roster_exact"]),
        )
        players[row_name] = {SRC: value}
    return col.build_sidecar(players, scrape_timestamp=ts)


def _build(flags=(), *, csvs=None, sidecar=None, vid=None, directory=None):
    with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
        root = Path(tmp)
        d = root / "CSVs" / "site_raw"
        d.mkdir(parents=True)
        for name, text in (csvs if csvs is not None else _csvs(META)).items():
            (d / name).write_text(text)
        # Production always has the state directory; every build here does too,
        # so a comparison isolates the sidecar's own effect.
        (root / ce.SIDECAR_REL).parent.mkdir(parents=True, exist_ok=True)
        if sidecar is not None:
            ce.write_sidecar(sidecar, root / ce.SIDECAR_REL)
        store = root / v.STORE_REL
        store.parent.mkdir(parents=True, exist_ok=True)
        if vid is not None:
            v.append_observations(store, vid)
        else:
            store.write_text("")
        with (
            _flags(*flags),
            mock.patch(
                "src.identity.directory_cache.get_default_sleeper_index",
                return_value=directory,
            ),
        ):
            return dc.build_api_data_contract(_payload(), csv_root=root)


def _canon(contract) -> str:
    c = copy.deepcopy(contract)
    c.pop("generatedAt", None)
    fresh = c.get("dataFreshness")
    if isinstance(fresh, dict):
        fresh.pop("generatedAt", None)
        for stamp in (fresh.get("sourceTimestamps") or {}).values():
            if isinstance(stamp, dict):
                stamp.pop("mtime", None)
    return json.dumps(c, sort_keys=True, default=str)


# ── §9 property 25: byte identity with every V2.1 flag OFF ─────────────


def test_flags_off_board_is_byte_identical_with_u2_u3_and_vid_present():
    side = _sidecar({"Off Vet 001": {"position": "LB", "steps": ["roster_fuzzy"]}})
    vid = [
        v.VidObservation(
            "source:fantasyCalc",
            "9000",
            "2000",
            v.BASIS_VENDOR_SLEEPER_ID,
            "fantasyCalc",
            "h",
            "2026-10-01T00:00:00+00:00",
        )
    ]
    plain = _build()
    full = _build(csvs=_u3_csvs(), sidecar=side, vid=vid)
    assert _canon(full) == _canon(plain)


def test_v2_without_v21_ignores_the_sidecar_and_the_vid_map():
    side = _sidecar({"Off Vet 001": {"position": "LB", "steps": ["roster_fuzzy"]}})
    vid = [
        v.VidObservation(
            "source:fantasyCalc",
            "9000",
            "2000",
            v.BASIS_VENDOR_SLEEPER_ID,
            "fantasyCalc",
            "h",
            "2026-10-01T00:00:00+00:00",
        )
    ]
    a = _build(ALL_ON, csvs=_u3_csvs())
    b = _build(ALL_ON, csvs=_u3_csvs(), sidecar=side, vid=vid)
    assert json.dumps(a["playersArray"], sort_keys=True) == json.dumps(
        b["playersArray"], sort_keys=True
    )
    assert "captureEvidence" not in b["sourceIntegrity"]


# ── U2: payload-attached values graded on the capture's stamp ──────────


def test_u2_exact_rung_with_agreeing_fields_votes_verified():
    row = PAYLOAD["players"]["Off Vet 003"]
    side = _sidecar({"Off Vet 003": {"position": row["position"], "team": row["team"]}})
    got = _rows(_build(V21_ON, sidecar=side))["Off Vet 003"]
    stamp = got["sourceIntegrity"][SRC]["identity"]
    assert stamp["verdict"] == r.ID_VERIFIED and stamp["basis"] == "capture_evidence_u2"
    assert SRC in got["canonicalSiteValues"]


def test_u2_surname_rung_without_position_is_refused_absent_and_explained():
    side = _sidecar(
        {
            "Off Vet 004": {
                "vendorName": "O. Vet 004",
                "steps": ["roster_initial"],
                "acquisition": ce.ACQ_AUTOCOMPLETE,
            }
        }
    )
    contract = _build(V21_ON, sidecar=side)
    got = _rows(contract)["Off Vet 004"]
    block = got["sourceIntegrity"][SRC]
    assert block["status"] == si.STATUS_REFUSED
    assert block["primaryReason"] == r.ID_REASON_LOW_EVIDENCE_RUNG
    assert block["identity"]["via"] == ce.VIA_SCRAPER_SURNAME
    assert SRC not in got["canonicalSiteValues"]  # absent, never zero
    assert block["refusedObservation"]["value"] is not None
    meta = got["sourceRankMeta"][SRC]
    assert meta["contributedToBlend"] is False and meta["appliedWeight"] == 0.0
    graded = contract["sourceIntegrity"]["captureEvidence"]
    assert graded["state"] == ce.STATE_BOUND
    assert graded["graded"][SRC] == {r.ID_UNRESOLVED: 1}


def test_u2_refusal_moves_only_its_own_row():
    """R6 / §9 property 19 on the payload path: every other row's idpTradeCalc
    effective rank and vote value are what they are without the sidecar."""
    side = _sidecar({"Off Vet 004": {"position": "LB"}})  # exact rung, wrong family
    base = _rows(_build(V21_ON))
    graded = _rows(_build(V21_ON, sidecar=side))
    assert (
        graded["Off Vet 004"]["sourceIntegrity"][SRC]["primaryReason"]
        == r.ID_REASON_POSITION_FAMILY
    )
    for name, row in base.items():
        if name == "Off Vet 004" or SRC not in (row.get("sourceRanks") or {}):
            continue
        assert graded[name]["sourceRanks"][SRC] == row["sourceRanks"][SRC], name
        assert (
            graded[name]["sourceRankMeta"][SRC]["valueContribution"]
            == row["sourceRankMeta"][SRC]["valueContribution"]
        ), name


def test_u2_a2_the_vendor_name_re_resolving_to_another_player_contradicts():
    directory = r.build_sleeper_index(
        {"5555": {"full_name": "Other Guy", "position": "RB", "team": "NYJ"}}
    )
    side = _sidecar({"Off Vet 006": {"vendorName": "Other Guy", "steps": ["roster_fuzzy"]}})
    got = _rows(_build(V21_ON, sidecar=side, directory=directory))["Off Vet 006"]
    assert got["sourceIntegrity"][SRC]["primaryReason"] == r.ID_REASON_JOIN_INCONSISTENT


def test_u2_an_unresolvable_vendor_name_is_no_a2_evidence():
    side = _sidecar(
        {
            "Off Vet 006": {
                "vendorName": "Nobody Known",
                "steps": ["roster_fuzzy"],
                "position": PAYLOAD["players"]["Off Vet 006"]["position"],
                "team": PAYLOAD["players"]["Off Vet 006"]["team"],
            }
        }
    )
    directory = r.build_sleeper_index({})
    got = _rows(_build(V21_ON, sidecar=side, directory=directory))["Off Vet 006"]
    # family AND team agree: A5 is satisfied, the fuzzy attach votes
    assert got["sourceIntegrity"][SRC]["identity"]["verdict"] == r.ID_VERIFIED


def test_u2_team_only_mismatch_at_cold_start_votes_team_unconfirmed():
    row = PAYLOAD["players"]["Off Vet 007"]
    side = _sidecar({"Off Vet 007": {"position": row["position"], "team": "ARI"}})
    got = _rows(_build(V21_ON, sidecar=side))["Off Vet 007"]
    assert got["sourceIntegrity"][SRC]["identity"]["verdict"] == r.ID_TEAM_UNCONFIRMED
    assert SRC in got["canonicalSiteValues"]


def test_u2_a_sidecar_from_another_scrape_is_never_read():
    side = _sidecar({"Off Vet 004": {"position": "LB"}}, ts="2026-10-20T15:35:27+00:00")
    contract = _build(V21_ON, sidecar=side)
    assert contract["sourceIntegrity"]["captureEvidence"] == {
        "state": ce.STATE_TIMESTAMP_MISMATCH,
        "graded": {},
    }
    assert SRC in _rows(contract)["Off Vet 004"]["canonicalSiteValues"]


def test_u2_needs_its_repair():
    side = _sidecar({"Off Vet 004": {"position": "LB"}})
    with si.repairs_override(si.Repairs.all_on().without("U2")):
        got = _rows(_build(V21_ON, sidecar=side))["Off Vet 004"]
    assert SRC in got["canonicalSiteValues"]
    assert "sourceIntegrity" not in got or SRC not in got["sourceIntegrity"]


# ── VID: A1 vendor ids through the map, ARRIVING only ──────────────────


def _vid_for(name: str, other_sid: str, at: str):
    """fantasyCalc's vendor id of ``name`` mapped to ANOTHER player."""
    lines = _u3_csvs()["fantasyCalc.csv"].splitlines()
    vendor_id = next(ln.split(",")[3] for ln in lines[1:] if ln.split(",")[0] == name)
    return [
        v.VidObservation(
            v.namespace_for("fantasyCalc"),
            vendor_id,
            other_sid,
            v.BASIS_VENDOR_SLEEPER_ID,
            "fantasyCalc",
            "h",
            at,
        )
    ]


def test_vid_a_vendor_id_naming_another_player_is_contradicted():
    name = "Off Vet 010"
    contract = _build(
        V21_ON, csvs=_u3_csvs(), vid=_vid_for(name, "2001", "2026-10-01T00:00:00+00:00")
    )
    got = _rows(contract)[name]
    assert got["sourceIntegrity"]["fantasyCalc"]["primaryReason"] == r.ID_REASON_VENDOR_ID
    assert "fantasyCalc" not in got["canonicalSiteValues"]
    assert contract["sourceIntegrity"]["vendorIdMap"]["state"] == "loaded_tree"


def test_vid_reads_only_evidence_from_before_the_board():
    name = "Off Vet 010"
    got = _rows(_build(V21_ON, csvs=_u3_csvs(), vid=_vid_for(name, "2001", TS)))[name]
    assert "fantasyCalc" in got["canonicalSiteValues"]


def test_vid_agreeing_vendor_id_verifies():
    name = "Off Vet 010"
    sid = PAYLOAD["players"][name]["_sleeperId"]
    got = _rows(
        _build(V21_ON, csvs=_u3_csvs(), vid=_vid_for(name, sid, "2026-10-01T00:00:00+00:00"))
    )[name]
    stamp = got["sourceIntegrity"]["fantasyCalc"]["identity"]
    assert stamp["verdict"] == r.ID_VERIFIED and stamp["evidence"] == ["id"]


@pytest.mark.parametrize("flags", [(), ALL_ON])
def test_u3_columns_change_nothing_outside_v21(flags):
    a = _build(flags)
    b = _build(flags, csvs=_u3_csvs())
    if not flags:
        assert _canon(a) == _canon(b)
    else:
        # V2 reads U1 evidence, so the new team / position columns may grade
        # fantasyCalc joins; values must not move where the evidence agrees.
        va = {x["displayName"]: x.get("rankDerivedValue") for x in a["playersArray"]}
        vb = {x["displayName"]: x.get("rankDerivedValue") for x in b["playersArray"]}
        assert va == vb
