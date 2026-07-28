#!/usr/bin/env python3
"""Fetch Mike Clay's ESPN projection guide into a BDVM snapshot.

The guide is a public PDF on ESPN's fantasy draft-kit CDN::

    https://g.espncdn.com/s/ffldraftkit/<yy>/NFLDK<season>_CS_ClayProjections<season>.pdf

Flow
----
1. Download the PDF (or take a local file via ``--pdf``).
2. Extract text with ``pdftotext -layout`` (poppler-utils — a soft
   dependency: missing binary is a soft skip with an install hint,
   never a crash).
3. Parse the 32 team pages with the schema-tolerant adapter
   (``src/bdvm/clay_projections.py``) — raw season stat lines for
   offense, combined-tackle defense rows split solo/assist.
4. Merge into the latest BDVM projection snapshot via the shared
   supersede policy: Clay replaces its own prior run and supersedes
   baseline proxies per player; IDP Show records carry through, so
   defenders covered by both feeds get a two-source consensus.

Usage::

    python3 scripts/fetch_clay_projections.py --season 2026
    python3 scripts/fetch_clay_projections.py --season 2026 --pdf ~/clay.pdf
    python3 scripts/fetch_clay_projections.py --season 2026 --dry-run

Exit codes: 0 snapshot written (or today's already exists — no-op),
1 soft failure (download failed / pdftotext missing / not a usable
guide), 2 unexpected error.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.bdvm.clay_projections import (  # noqa: E402
    SOURCE_NAME,
    merge_into_snapshot,
    parse_clay_text,
    records_from_rows,
)
from src.bdvm.projections import ProjectionError  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402


def default_url(season: int) -> str:
    yy = str(season)[-2:]
    return (
        f"https://g.espncdn.com/s/ffldraftkit/{yy}/" f"NFLDK{season}_CS_ClayProjections{season}.pdf"
    )


def _download(url: str, dest: Path) -> bool:
    try:
        import requests  # noqa: PLC0415

        resp = requests.get(url, timeout=90)
        if resp.status_code != 200 or not resp.content.startswith(b"%PDF"):
            print(
                f"download failed: HTTP {resp.status_code}, "
                f"content-type {resp.headers.get('content-type')!r}",
                file=sys.stderr,
            )
            return False
        dest.write_bytes(resp.content)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"download failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--pdf", type=Path, default=None, help="parse a local PDF instead")
    parser.add_argument("--url", default=None, help="override the CDN URL")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if shutil.which("pdftotext") is None:
        print(
            "pdftotext not found — install poppler-utils "
            "(apt-get install poppler-utils) to enable the Clay guide fetch.",
            file=sys.stderr,
        )
        return 1

    as_of = datetime.now(timezone.utc).date().isoformat()

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if args.pdf is not None:
            if not args.pdf.exists():
                print(f"ERROR: {args.pdf} not found", file=sys.stderr)
                return 2
            pdf_path = args.pdf
        else:
            url = args.url or default_url(args.season)
            print(f"fetching {url}")
            pdf_path = tmp / "clay.pdf"
            if not _download(url, pdf_path):
                return 1

        txt_path = tmp / "clay.txt"
        proc = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(txt_path)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            print(f"pdftotext failed: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        text = txt_path.read_text(encoding="utf-8", errors="replace")

    rows, report = parse_clay_text(text)
    print(json.dumps(report, indent=1))
    if not rows:
        print("not a usable projection guide — nothing written", file=sys.stderr)
        return 1

    records, rec_summary = records_from_rows(
        rows, season=args.season, as_of=as_of, name_normalizer=normalize_player_name
    )
    print(f"projection records ({SOURCE_NAME}): {json.dumps(rec_summary)}")
    if args.dry_run:
        print("dry run — snapshot not written")
        return 0
    try:
        _path, merge_summary = merge_into_snapshot(records, season=args.season, as_of=as_of)
    except ProjectionError as exc:
        # Same-day rerun collides with today's immutable snapshot —
        # the day's merge already happened; no-op success.
        print(f"snapshot for today already exists — no-op ({exc})")
        return 0
    print(json.dumps(merge_summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
