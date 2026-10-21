#!/usr/bin/env python3
"""Verify, and optionally pin, full V2.1 identity-capture evidence.

The full U2/U2b sidecar is kept OUT of git (a 90-day GitHub Actions artifact of
the refresh run, plus a 30-day box-local copy); git keeps only a manifest with
its SHA-256 (``data/scrape_state/identity_capture_manifest.json`` and a copy in
each export-archive zip).  This script is the one way to bind the two.

Owner decision 2026-10-21 ("Artifacts + pin held-out (Recommended)"): when the
V2.1 gate boards G1 / G2 are selected, their full stamps are verified against
the ARCHIVED manifest and committed (``--pin``), so the evaluation evidence is
permanent.  Procedure: ``docs/sources/outlier_integrity_v21/PIN_HELDOUT_STAMPS.md``.

USAGE
-----
    # where is the full evidence for this archived board?
    python scripts/verify_identity_capture_evidence.py \
        --archive exports/archive/dynasty_export_20261104_020000.zip

    # fetch it (the command above prints this), then verify
    gh run download <runId> -R <repo> -n identity-capture-evidence-<runId>-<attempt> -D /tmp/ev
    python scripts/verify_identity_capture_evidence.py \
        --archive exports/archive/dynasty_export_20261104_020000.zip \
        --evidence /tmp/ev/identity_capture_evidence_20261104T020000Z.json.gz

    # pin a gate board (verifies first; writes nothing unless it verifies)
    python scripts/verify_identity_capture_evidence.py --pin --label G1 \
        --archive exports/archive/dynasty_export_20261104_020000.zip \
        --evidence /tmp/ev/identity_capture_evidence_20261104T020000Z.json.gz

``--manifest PATH`` may replace ``--archive`` for verification, but ``--pin``
requires ``--archive``: a pin is bound to the archived board it describes.

Exit codes: 0 verified / pinned / already pinned (or locate-only success),
1 evidence does not verify or conflicts with an existing pin, 2 usage / missing
manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.identity import capture_evidence as ce  # noqa: E402

#: Committed home of pinned gate-board stamps (one directory per archive).
PIN_DIR_REL = Path("docs") / "sources" / "outlier_integrity_v21" / "pinned_stamps"
PIN_RECORD = "PIN.json"
PIN_SCHEMA = "identity_capture_pin.v1"


def _load_manifest(args: argparse.Namespace) -> dict | None:
    if args.manifest:
        try:
            got = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return got if isinstance(got, dict) else None
    return ce.manifest_from_archive(Path(args.archive))


def _download_hint(manifest: dict) -> str | None:
    art = ((manifest.get("storage") or {}).get("artifact")) or None
    if not isinstance(art, dict) or not art.get("runId"):
        return None
    repo = f" -R {art['repository']}" if art.get("repository") else ""
    return f"gh run download {art['runId']}{repo} -n {art['name']} -D <dir>"


def pin(
    *,
    archive: Path,
    manifest: dict,
    payload: dict,
    pin_root: Path,
    label: str | None,
) -> tuple[int, str]:
    """Write a VERIFIED payload under ``pin_root/<archive stem>/``.

    Idempotent: an existing pin of the same evidence is left as is.  A pin of
    DIFFERENT evidence for the same archive is refused, never overwritten."""
    target = Path(pin_root) / Path(archive).stem
    evidence_sha = (manifest.get("evidence") or {}).get("sha256")
    record_path = target / PIN_RECORD
    if record_path.exists():
        try:
            existing = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 1, f"existing pin at {target} is unreadable; refusing to overwrite"
        if existing.get("evidenceSha256") == evidence_sha:
            return 0, f"already pinned: {target}"
        return 1, f"a DIFFERENT evidence is already pinned at {target}; refusing to overwrite"
    gz = ce._gzip_deterministic(ce.canonical_bytes(payload))
    filename = (manifest.get("evidence") or {}).get("filename") or ce.evidence_filename(
        payload.get("scrapeTimestamp")
    )
    record = {
        "schema": PIN_SCHEMA,
        "decision": "owner 2026-10-21: Artifacts + pin held-out (Recommended)",
        "label": label,
        "archive": Path(archive).name,
        "archiveSha256": hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
        "scrapeTimestamp": manifest.get("scrapeTimestamp"),
        "evidenceFile": filename,
        "evidenceSha256": evidence_sha,
        "pinnedGzipSha256": hashlib.sha256(gz).hexdigest(),
        "artifact": (manifest.get("storage") or {}).get("artifact"),
    }
    target.mkdir(parents=True, exist_ok=True)
    ce._atomic_write(target / filename, gz)
    ce._atomic_write(target / ce.MANIFEST_FILENAME, ce.canonical_bytes(manifest))
    # The record is written LAST: its presence means the pin is complete.
    ce._atomic_write(record_path, ce.canonical_bytes(record))
    return 0, f"pinned: {target}"


def verify_pinned(directory: Path) -> str:
    """State of a committed pin: its evidence re-verified against its manifest."""
    directory = Path(directory)
    try:
        record = json.loads((directory / PIN_RECORD).read_text(encoding="utf-8"))
        manifest = json.loads((directory / ce.MANIFEST_FILENAME).read_text(encoding="utf-8"))
        blob = (directory / record["evidenceFile"]).read_bytes()
    except (OSError, ValueError, KeyError):
        return ce.STATE_UNREADABLE
    if record.get("evidenceSha256") != (manifest.get("evidence") or {}).get("sha256"):
        return ce.STATE_CHECKSUM_MISMATCH
    return ce.verify_evidence(blob, manifest)[1]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--archive", help="export-archive zip carrying the manifest")
    src.add_argument("--manifest", help="manifest JSON file")
    ap.add_argument("--evidence", help="full evidence file (.json.gz or .json)")
    ap.add_argument("--pin", action="store_true", help="commit-ready pin after verification")
    ap.add_argument("--label", help="pin label, e.g. G1 or G2")
    ap.add_argument(
        "--sealed",
        action="store_true",
        help="print hashes and timestamps only (no census) - for sealed held-out boards",
    )
    ap.add_argument(
        "--pin-root",
        default=str(_REPO / PIN_DIR_REL),
        help=f"pin destination (default: {PIN_DIR_REL.as_posix()})",
    )
    args = ap.parse_args(argv)
    if args.pin and (not args.archive or not args.evidence):
        print("--pin needs --archive (the board) and --evidence (the downloaded stamps)")
        return 2

    manifest = _load_manifest(args)
    if manifest is None:
        print("no identity-capture manifest found (board predates U2, or unreadable)")
        return 2
    ev = manifest.get("evidence") or {}
    print(f"scrapeTimestamp: {manifest.get('scrapeTimestamp')}")
    print(f"evidence file:   {ev.get('filename')}  sha256={ev.get('sha256')}")
    if not (args.pin or args.sealed):
        # Pin / sealed mode prints only hashes and timestamps: G1 / G2 are sealed
        # H boards (HELDOUT_RULE.json "seal"), and a pin is a checksum bind, not a scan.
        print(f"census:          {json.dumps(manifest.get('census'), sort_keys=True)}")
    hint = _download_hint(manifest)
    print(f"retrieve:        {hint or 'no CI artifact recorded (box-local scrape)'}")
    if not args.evidence:
        return 0
    try:
        blob = Path(args.evidence).read_bytes()
    except OSError as exc:
        print(f"cannot read evidence: {exc}")
        return 2
    payload, state = ce.verify_evidence(blob, manifest)
    print(f"verification:    {state}")
    if state != ce.STATE_BOUND or payload is None:
        return 1
    if not args.pin:
        return 0
    code, message = pin(
        archive=Path(args.archive),
        manifest=manifest,
        payload=payload,
        pin_root=Path(args.pin_root),
        label=args.label,
    )
    print(message)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
