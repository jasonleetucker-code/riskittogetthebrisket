"""Pinning G1 / G2 stamps (owner decision 2026-10-21, "Artifacts + pin held-out").

A pin is a VERIFIED, permanent, committed copy of one archived board's full
U2/U2b stamps.  It is written only when the downloaded evidence hashes to the
manifest archived WITH that board, is idempotent, never overwrites a different
pin, prints nothing but hashes and timestamps (the boards are sealed), and can
be re-verified from the repository alone.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

from scripts import verify_identity_capture_evidence as cli
from src.identity import capture_evidence as ce

REPO = Path(__file__).resolve().parents[2]
TS = "2026-11-04T02:00:00+00:00"
CI_ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "987654321",
    "GITHUB_RUN_ATTEMPT": "1",
    "GITHUB_REPOSITORY": "owner/repo",
}


def _payload(ts: str = TS, value: int = 9000) -> dict:
    col = ce.CaptureEvidenceCollector()
    col.add_entry("ktc", "A Player", value, acquisition=ce.ACQ_VALUE_SOURCE_CAPTURE, position="QB")
    col.attach("ktc", "A Player", "A Player", value, ["roster_exact"])
    return col.build_sidecar({"A Player": {"ktc": value}}, scrape_timestamp=ts, generated_at=ts)


@pytest.fixture
def board(tmp_path):
    """A refresh's outputs: the archive zip (with its manifest) and the artifact file."""
    root = tmp_path / "run"
    manifest = ce.write_evidence(_payload(), root, env=CI_ENV)
    archive = tmp_path / "dynasty_export_20261104_020000.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("dynasty_data_2026-11-04.json", "{}")
        zf.writestr(ce.MANIFEST_FILENAME, (root / ce.MANIFEST_REL).read_text(encoding="utf-8"))
    evidence = root / ce.EVIDENCE_DIR_REL / manifest["evidence"]["filename"]
    return archive, evidence, manifest, tmp_path / "pins"


def _pin(archive, evidence, pins, label="G1"):
    return cli.main(
        [
            "--pin",
            "--label",
            label,
            "--archive",
            str(archive),
            "--evidence",
            str(evidence),
            "--pin-root",
            str(pins),
        ]
    )


def test_a_verified_board_is_pinned_and_reverifies_from_the_repo_alone(board):
    archive, evidence, manifest, pins = board
    assert _pin(archive, evidence, pins) == 0
    target = pins / archive.stem
    assert sorted(p.name for p in target.iterdir()) == sorted(
        [cli.PIN_RECORD, ce.MANIFEST_FILENAME, manifest["evidence"]["filename"]]
    )
    record = json.loads((target / cli.PIN_RECORD).read_text(encoding="utf-8"))
    assert record["schema"] == cli.PIN_SCHEMA and record["label"] == "G1"
    assert record["decision"] == "owner 2026-10-21: Artifacts + pin held-out (Recommended)"
    assert record["archiveSha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert record["evidenceSha256"] == manifest["evidence"]["sha256"]
    assert record["artifact"]["name"] == "identity-capture-evidence-987654321-1"
    # deterministic: the pinned gzip is byte-identical to what the refresh wrote
    assert record["pinnedGzipSha256"] == manifest["evidence"]["gzipSha256"]
    assert cli.verify_pinned(target) == ce.STATE_BOUND


def test_pinning_is_idempotent(board, capsys):
    archive, evidence, _m, pins = board
    assert _pin(archive, evidence, pins) == 0
    before = {p.name: p.read_bytes() for p in (pins / archive.stem).iterdir()}
    assert _pin(archive, evidence, pins) == 0
    assert "already pinned" in capsys.readouterr().out
    assert {p.name: p.read_bytes() for p in (pins / archive.stem).iterdir()} == before


def test_a_plain_json_download_pins_the_same_bytes(board, tmp_path):
    archive, evidence, manifest, pins = board
    plain = tmp_path / "plain.json"
    plain.write_bytes(gzip.decompress(evidence.read_bytes()))
    assert _pin(archive, plain, pins) == 0
    pinned = pins / archive.stem / manifest["evidence"]["filename"]
    assert pinned.read_bytes() == evidence.read_bytes()


def test_unverified_evidence_writes_nothing(board, tmp_path):
    archive, evidence, _m, pins = board
    doctored = json.loads(gzip.decompress(evidence.read_bytes()))
    doctored["sources"]["ktc"]["attached"]["A Player"]["position"] = "WR"
    bad = tmp_path / "bad.json"
    bad.write_bytes(ce.canonical_bytes(doctored))
    assert _pin(archive, bad, pins) == 1
    assert not pins.exists()
    other = tmp_path / "other.json"  # another scrape's (genuine) stamps
    other.write_bytes(ce.canonical_bytes(_payload(ts="2026-11-04T04:00:00+00:00")))
    assert _pin(archive, other, pins) == 1
    assert not pins.exists()


def test_a_different_existing_pin_is_never_overwritten(board):
    archive, evidence, _m, pins = board
    target = pins / archive.stem
    target.mkdir(parents=True)
    (target / cli.PIN_RECORD).write_text(json.dumps({"evidenceSha256": "0" * 64}), encoding="utf-8")
    assert _pin(archive, evidence, pins) == 1
    assert sorted(p.name for p in target.iterdir()) == [cli.PIN_RECORD]


def test_tampering_with_a_committed_pin_is_detected(board):
    archive, evidence, manifest, pins = board
    assert _pin(archive, evidence, pins) == 0
    target = pins / archive.stem
    blob = target / manifest["evidence"]["filename"]
    data = json.loads(gzip.decompress(blob.read_bytes()))
    data["sources"]["ktc"]["attached"]["A Player"]["team"] = "SF"
    blob.write_bytes(ce.canonical_bytes(data))
    assert cli.verify_pinned(target) == ce.STATE_CHECKSUM_MISMATCH
    (target / cli.PIN_RECORD).unlink()
    assert cli.verify_pinned(target) == ce.STATE_UNREADABLE


def test_pin_mode_prints_no_census_and_requires_the_archive(board, capsys, tmp_path):
    archive, evidence, _m, pins = board
    assert _pin(archive, evidence, pins) == 0
    out = capsys.readouterr().out
    assert "census:" not in out and "sha256=" in out
    manifest_file = tmp_path / "m.json"
    with zipfile.ZipFile(archive) as zf:
        manifest_file.write_bytes(zf.read(ce.MANIFEST_FILENAME))
    code = cli.main(["--pin", "--manifest", str(manifest_file), "--evidence", str(evidence)])
    assert code == 2
    assert cli.main(["--sealed", "--archive", str(archive)]) == 0
    assert "census:" not in capsys.readouterr().out


def test_the_default_pin_root_is_committed_not_ignored():
    assert cli.PIN_DIR_REL.as_posix() == "docs/sources/outlier_integrity_v21/pinned_stamps"
    probe = (
        cli.PIN_DIR_REL / "dynasty_export_x" / "identity_capture_evidence_x.json.gz"
    ).as_posix()
    got = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", probe],
        capture_output=True,
        check=False,
    )
    assert got.returncode == 1, f"{probe} would be gitignored"


def test_the_procedure_doc_sits_beside_the_heldout_rule_and_names_the_command():
    doc = REPO / "docs" / "sources" / "outlier_integrity_v21" / "PIN_HELDOUT_STAMPS.md"
    assert (doc.parent / "HELDOUT_RULE.json").is_file()
    text = doc.read_text(encoding="utf-8")
    assert "Artifacts + pin held-out (Recommended)" in text
    assert "scripts/verify_identity_capture_evidence.py --pin" in text
    assert cli.PIN_DIR_REL.as_posix() in text
