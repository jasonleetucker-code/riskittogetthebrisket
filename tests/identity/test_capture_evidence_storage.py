"""Bounded storage of the V2.1 identity-capture evidence (owner request on #1910).

The full U2/U2b sidecar (~450 KB raw / ~35 KB gzipped per scrape) must NOT enter
git, because the refresh force-adds ``data/scrape_state/`` and commits the export
archive every two hours.  These tests pin the split:

* the full evidence lives only in a gitignored directory that no refresh step
  force-adds, as a byte-reproducible gzip, uploaded as a run artifact;
* git receives a manifest of checksums and aggregate counts - no player row,
  no vendor name - that is small and bounded;
* the full evidence verifies against the committed checksum, and anything else
  (tampered, truncated, another scrape's) does not;
* box-local copies are pruned on a stated window.
"""

from __future__ import annotations

import gzip
import json
import re
import subprocess
from pathlib import Path

import pytest

from scripts import verify_identity_capture_evidence as cli
from src.identity import capture_evidence as ce
from src.maintenance import retention

REPO = Path(__file__).resolve().parents[2]
WORKFLOW = REPO / ".github" / "workflows" / "scheduled-refresh.yml"
TS = "2026-11-04T02:00:00+00:00"
CI_ENV = {
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "123456789",
    "GITHUB_RUN_ATTEMPT": "2",
    "GITHUB_REPOSITORY": "owner/repo",
}


def _realistic_payload(n: int = 900) -> dict:
    """A sidecar shaped like a real refresh: ``n`` stamped rows per source."""
    col = ce.CaptureEvidenceCollector()
    players: dict = {}
    for source in ce.STAMPED_SOURCES:
        for i in range(n):
            name = f"Player Number {i:04d}"
            col.add_entry(
                source,
                name,
                1000 + i,
                acquisition=ce.ACQ_API_INTERCEPT,
                page_position=i + 1,
                position=("QB", "RB", "WR", "TE", "LB")[i % 5],
                team="DET",
                vendor_id=str(10_000 + i),
                value_key="value_sftep",
            )
            col.attach(source, name, name, 1000 + i, ["roster_exact", "identity:exact_clean"])
            players.setdefault(name, {})[source] = 1000 + i
    col.record_checkbox_toggles("idpTradeCalc", True, True, True, True, {"value_sftep": n})
    return col.build_sidecar(players, scrape_timestamp=TS, generated_at=TS)


@pytest.fixture(scope="module")
def payload() -> dict:
    return _realistic_payload()


# ── what git receives ──────────────────────────────────────────────────


def test_the_manifest_is_small_and_carries_no_player_row(payload, tmp_path):
    manifest = ce.write_evidence(payload, tmp_path, env=CI_ENV)
    committed = (tmp_path / ce.MANIFEST_REL).read_bytes()
    full = gzip.decompress(
        (tmp_path / ce.EVIDENCE_DIR_REL / manifest["evidence"]["filename"]).read_bytes()
    )
    assert len(full) > 300_000  # the realistic sidecar really is large
    assert len(committed) < 6_000  # bounded: independent of the row count
    text = committed.decode()
    assert "Player Number" not in text and "10001" not in text
    # Doubling the rows does not grow the manifest beyond the digits of its counts.
    bigger = ce.build_manifest(
        _realistic_payload(1800),
        evidence_bytes=b"x",
        gzip_bytes=b"y",
        filename="f",
        artifact=None,
    )
    assert len(json.dumps(bigger)) < 6_000


def test_the_manifest_keeps_what_readiness_needs(payload, tmp_path):
    """Readiness (prereg 3.7): G1/G2 must carry U2, U2b and U3.  U3 is in the
    archived CSVs; U2b and the U2 census are in the manifest itself; the full U2
    stamps are bound by checksum."""
    m = ce.write_evidence(payload, tmp_path, env=CI_ENV)
    assert m["scrapeTimestamp"] == TS and m["evidenceSchema"] == ce.SCHEMA_VERSION
    assert set(m["sources"]) == set(ce.STAMPED_SOURCES)
    assert m["census"] == payload["census"]
    assert m["sources"]["idpTradeCalc"]["toggles"] == payload["sources"]["idpTradeCalc"]["toggles"]
    assert m["sources"]["ktc"]["stampsByVia"] == {ce.VIA_SCRAPER_EXACT: 900}
    assert m["sources"]["ktc"]["stampsWithField"]["position"] == 900
    assert re.fullmatch(r"[0-9a-f]{64}", m["evidence"]["sha256"])
    assert m["storage"]["artifact"] == {
        "kind": "github_actions_artifact",
        "repository": "owner/repo",
        "runId": "123456789",
        "runAttempt": "2",
        "name": "identity-capture-evidence-123456789-2",
        "retentionDays": 90,
    }


def test_off_ci_no_artifact_is_claimed(payload, tmp_path):
    assert ce.write_evidence(payload, tmp_path, env={})["storage"]["artifact"] is None
    assert ce.artifact_pointer({"GITHUB_RUN_ID": "1"}) is None  # not inside Actions


# ── the full evidence verifies against git, and nothing else does ──────


def test_full_evidence_verifies_against_the_committed_checksum(payload, tmp_path):
    m = ce.write_evidence(payload, tmp_path, env=CI_ENV)
    blob = (tmp_path / ce.EVIDENCE_DIR_REL / m["evidence"]["filename"]).read_bytes()
    data, state = ce.verify_evidence(blob, m)
    assert state == ce.STATE_BOUND and data == payload
    # also as plain JSON (the checksum covers canonical bytes, not the container)
    assert ce.verify_evidence(gzip.decompress(blob), m)[1] == ce.STATE_BOUND


def test_tampered_or_foreign_evidence_does_not_verify(payload, tmp_path):
    m = ce.write_evidence(payload, tmp_path)
    blob = (tmp_path / ce.EVIDENCE_DIR_REL / m["evidence"]["filename"]).read_bytes()
    doctored = json.loads(gzip.decompress(blob))
    doctored["sources"]["ktc"]["attached"]["Player Number 0001"]["team"] = "SF"
    assert ce.verify_evidence(ce.canonical_bytes(doctored), m)[1] == ce.STATE_CHECKSUM_MISMATCH
    other = dict(payload, scrapeTimestamp="2026-11-04T04:00:00+00:00")
    m_other = ce.build_manifest(
        other,
        evidence_bytes=ce.canonical_bytes(other),
        gzip_bytes=b"",
        filename="x",
        artifact=None,
    )
    m_other["scrapeTimestamp"] = TS  # a manifest claiming the wrong scrape
    assert ce.verify_evidence(ce.canonical_bytes(other), m_other)[1] == (
        ce.STATE_TIMESTAMP_MISMATCH
    )
    assert ce.verify_evidence(blob[:50], m)[1] == ce.STATE_UNREADABLE
    assert ce.verify_evidence(blob, {"schema": "nope"})[1] == ce.STATE_SCHEMA_MISMATCH


def test_the_cli_verifies_and_locates(payload, tmp_path, capsys):
    m = ce.write_evidence(payload, tmp_path, env=CI_ENV)
    manifest = str(tmp_path / ce.MANIFEST_REL)
    evidence = str(tmp_path / ce.EVIDENCE_DIR_REL / m["evidence"]["filename"])
    assert cli.main(["--manifest", manifest]) == 0
    out = capsys.readouterr().out
    assert "gh run download 123456789 -R owner/repo -n identity-capture-evidence-123456789-2" in out
    assert cli.main(["--manifest", manifest, "--evidence", evidence]) == 0
    Path(evidence).write_bytes(b"\x1f\x8b broken")
    assert cli.main(["--manifest", manifest, "--evidence", evidence]) == 1
    assert cli.main(["--manifest", str(tmp_path / "missing.json")]) == 2


def test_filenames_are_utc_and_sortable():
    assert ce.evidence_filename("2026-11-04T02:00:00+00:00") == (
        "identity_capture_evidence_20261104T020000Z.json.gz"
    )
    assert ce.evidence_filename("2026-11-03T21:00:00-05:00") == (
        "identity_capture_evidence_20261104T020000Z.json.gz"
    )
    assert ce.evidence_filename(None) == "identity_capture_evidence_unknown.json.gz"


# ── it stays out of git, and the artifact name cannot drift ────────────


def test_the_evidence_directory_is_gitignored():
    probe = (ce.EVIDENCE_DIR_REL / "identity_capture_evidence_20261104T020000Z.json.gz").as_posix()
    got = subprocess.run(
        ["git", "-C", str(REPO), "check-ignore", "-q", "--no-index", probe],
        capture_output=True,
        check=False,
    )
    assert got.returncode == 0, f"{probe} is not ignored by .gitignore"


def test_no_refresh_step_force_adds_the_evidence_directory():
    text = WORKFLOW.read_text(encoding="utf-8")
    adds = [ln for ln in text.splitlines() if re.search(r"git add\b", ln) or "for p in " in ln]
    joined = "\n".join(adds)
    assert "identity_capture_evidence" not in joined
    # a blanket force-add of data/ would carry it in too
    assert not re.search(r"git add[^\n]*\s-f\s+(--\s+)?data/?(\s|$)", joined)
    assert not re.search(r"for p in [^\n]*\sdata/\s", joined)


def test_the_workflow_uploads_under_the_name_the_manifest_records():
    text = WORKFLOW.read_text(encoding="utf-8")
    m = re.search(
        r"uses: actions/upload-artifact@v\d+\s+with:\s+name: ([^\r\n]+)\s+path: (\S+)"
        r"\s+retention-days: (\d+)",
        text,
    )
    assert m, "identity evidence upload step missing"
    name, path, days = (g.strip() for g in m.groups())
    assert name == "identity-capture-evidence-${{ github.run_id }}-${{ github.run_attempt }}"
    assert ce.artifact_name("${{ github.run_id }}", "${{ github.run_attempt }}") == name
    assert path == (ce.EVIDENCE_DIR_REL / "*.json.gz").as_posix()
    assert int(days) == ce.ARTIFACT_RETENTION_DAYS


# ── box-local retention ────────────────────────────────────────────────


def test_box_local_copies_are_pruned_after_the_stated_window(tmp_path):
    from datetime import datetime, timezone

    d = tmp_path / ce.EVIDENCE_DIR_REL
    d.mkdir(parents=True)
    old = d / "identity_capture_evidence_20260901T000000Z.json.gz"
    fresh = d / "identity_capture_evidence_20261101T000000Z.json.gz"
    unrelated = d / "notes.txt"
    for p in (old, fresh, unrelated):
        p.write_bytes(b"x")
    now = datetime(2026, 11, 4, tzinfo=timezone.utc).timestamp()
    report = retention.prune_data_dir(tmp_path, now=now)
    assert not old.exists() and fresh.exists() and unrelated.exists()
    cat = next(c for c in report.categories if c.name == "identity_capture_evidence")
    assert (cat.deleted, cat.kept) == (1, 1)
    assert ce.BOX_EVIDENCE_RETENTION_DAYS == 30
