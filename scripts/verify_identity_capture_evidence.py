#!/usr/bin/env python3
"""Verify full V2.1 identity-capture evidence against its committed manifest.

The full U2/U2b sidecar is kept OUT of git (a GitHub Actions artifact of the
refresh run, plus a 30-day box-local copy); git keeps only a manifest with its
SHA-256 (``data/scrape_state/identity_capture_manifest.json`` and a copy in
each export-archive zip).  This script is the one way to bind the two.

USAGE
-----
    # where is the full evidence for this archived board?
    python scripts/verify_identity_capture_evidence.py \
        --archive exports/archive/dynasty_export_20261104_020000.zip

    # fetch it (prints this command), then verify
    gh run download <runId> -R <repo> -n identity-capture-evidence-<runId>-<attempt> -D /tmp/ev
    python scripts/verify_identity_capture_evidence.py \
        --archive exports/archive/dynasty_export_20261104_020000.zip \
        --evidence /tmp/ev/identity_capture_evidence_20261104T020000Z.json.gz

``--manifest PATH`` may replace ``--archive``.

Exit codes: 0 verified (or locate-only success), 1 evidence does not verify,
2 usage / missing manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.identity import capture_evidence as ce  # noqa: E402


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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--archive", help="export-archive zip carrying the manifest")
    src.add_argument("--manifest", help="manifest JSON file")
    ap.add_argument("--evidence", help="full evidence file (.json.gz or .json)")
    args = ap.parse_args(argv)

    manifest = _load_manifest(args)
    if manifest is None:
        print("no identity-capture manifest found (board predates U2, or unreadable)")
        return 2
    ev = manifest.get("evidence") or {}
    print(f"scrapeTimestamp: {manifest.get('scrapeTimestamp')}")
    print(f"evidence file:   {ev.get('filename')}  sha256={ev.get('sha256')}")
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
    _data, state = ce.verify_evidence(blob, manifest)
    print(f"verification:    {state}")
    return 0 if state == ce.STATE_BOUND else 1


if __name__ == "__main__":
    raise SystemExit(main())
