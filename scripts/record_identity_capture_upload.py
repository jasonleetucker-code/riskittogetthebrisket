#!/usr/bin/env python3
"""Record (and announce) whether this refresh's identity-evidence artifact was kept.

Runs in ``scheduled-refresh.yml`` right after the ``upload-artifact`` step, with
that step's outcome.  It appends one line to the committed, bounded ledger
``data/scrape_state/identity_capture_uploads.jsonl`` (owner:
``src/identity/capture_evidence.py``) and, when the upload did not succeed,
makes the loss LOUD: an ``::error`` annotation and a step-summary line naming
the scrapeTimestamp and evidence sha256.  A lost upload on exactly the G1 or G2
refresh would otherwise only surface months later as a missing download.

NEVER fails the refresh: every path exits 0.

    python scripts/record_identity_capture_upload.py --outcome "${{ steps.identity_upload.outcome }}"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _summary(line: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--outcome", default="", help="steps.<upload step id>.outcome")
    ap.add_argument("--root", default=str(_REPO))
    args = ap.parse_args(argv)
    try:
        from src.identity import capture_evidence as ce

        record = ce.record_upload_outcome(
            Path(args.root), step_outcome=args.outcome, env=os.environ
        )
    except Exception as exc:  # noqa: BLE001
        print(f"::warning title=Identity evidence ledger::could not record upload outcome: {exc}")
        _summary(f"- identity evidence: upload outcome NOT recorded ({exc})")
        return 0
    if record is None:
        print("[IdentityEvidence] this run wrote no evidence manifest; no upload outcome recorded")
        _summary("- identity evidence: no manifest written this run (scrape failed or skipped)")
        return 0
    what = (
        f"scrapeTimestamp={record['scrapeTimestamp']} "
        f"evidence sha256={record['evidenceSha256']} artifact={record['artifact']}"
    )
    if record["artifactUpload"] == ce.UPLOAD_UPLOADED:
        print(f"[IdentityEvidence] artifact uploaded: {what}")
        _summary(f"- identity evidence artifact uploaded: {what}")
    else:
        print(
            "::error title=Identity evidence NOT retained::"
            f"artifact upload {record['artifactUpload']} (step outcome {args.outcome!r}); {what}. "
            "If this refresh becomes V2.1 G1/G2 its wrong-player gate is BLOCKED."
        )
        _summary(
            f"- **identity evidence NOT retained** (upload {record['artifactUpload']}): {what}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
