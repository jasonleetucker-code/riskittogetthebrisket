#!/usr/bin/env python3
"""Fetch DraftSharks dynasty rankings (offense + IDP) as a single
cross-universe CSV that matches the shape the existing
``draftSharks`` source entry expects.

DraftSharks exposes a server-side CSV export at
``/dynasty-rankings/export`` that accepts a ``pprSuperflexSlug``
query param and returns the full ranked board — offense AND IDP
mixed on one scale by ``3D Value +`` — in a single response.
We use that as-is; no merging required.  (The separate
``&fantasyPosition=IDP`` call returns only IDPs, which is a subset
of the full export, so pulling both would duplicate every IDP.)

Authentication
--------------

Cookies are loaded from ``draftsharks_session.json`` at the repo
root (gitignored).  To refresh:

1. Log in to https://www.draftsharks.com/ in a browser.
2. Open DevTools → Application → Cookies → ``www.draftsharks.com``.
3. Copy the values of ``PHPSESSID`` (HttpOnly), ``_identity``
   (HttpOnly), and ``_frontendCSRF`` into the session file.

Run
---

    python3 scripts/fetch_draftsharks.py

Writes ``CSVs/site_raw/draftSharks.csv`` with the same header the
existing CSV uses (``Rank,Team,Player,"Fantasy Position",ADP,Bye,
Age,"1yr. Proj","3yr. Proj","5yr. Proj","10yr. Proj","DS Analysis",
"3D Value +"``).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "draftsharks_session.json"
OUT_PATH = REPO / "CSVs" / "site_raw" / "draftSharks.csv"

FULL_URL = (
    "https://www.draftsharks.com/dynasty-rankings/export"
    "?pprSuperflexSlug=te-premium-superflex"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0 Safari/537.36"
)


def _load_cookies() -> dict[str, str]:
    if not SESSION_PATH.exists():
        raise SystemExit(
            f"Session file not found: {SESSION_PATH}\n"
            "See this script's docstring for how to capture cookies."
        )
    data = json.loads(SESSION_PATH.read_text())
    return {c["name"]: c["value"] for c in data.get("cookies", []) if isinstance(c, dict) and "name" in c}


def _fetch(url: str, cookies: dict[str, str], *, referer: str) -> str:
    headers = {
        "User-Agent": _UA,
        "Referer": referer,
    }
    r = requests.get(url, cookies=cookies, headers=headers, timeout=30)
    ctype = r.headers.get("content-type", "")
    if r.status_code != 200 or "text/csv" not in ctype.lower():
        snippet = r.text[:200].replace("\n", " ")
        raise RuntimeError(
            f"DS export request failed ({r.status_code} {ctype}): {snippet}"
        )
    return r.text


def _parse_csv(text: str) -> tuple[list[str], list[list[str]]]:
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + merge but don't write the CSV.",
    )
    args = parser.parse_args()

    cookies = _load_cookies()

    print("[DS] fetching full cross-universe export …", flush=True)
    text = _fetch(
        FULL_URL,
        cookies,
        referer="https://www.draftsharks.com/dynasty-rankings/te-premium-superflex",
    )
    header, rows = _parse_csv(text)
    print(f"[DS] rows: {len(rows)}")

    if not rows:
        print("[DS] ERROR: export returned zero rows", file=sys.stderr)
        return 1

    # Sanity-check: this export should span both offense and IDP
    # families.  If we got zero IDP rows the URL probably lost its
    # cross-universe mode and we're only getting offense back.
    try:
        pos_idx = header.index("Fantasy Position")
    except ValueError:
        pos_idx = 3  # expected column order
    idp_families = {"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S"}
    idp_count = sum(
        1 for r in rows if len(r) > pos_idx and r[pos_idx].upper() in idp_families
    )
    off_count = len(rows) - idp_count
    print(f"[DS] family split: offense={off_count} idp={idp_count}")
    if idp_count == 0:
        print(
            "[DS] ERROR: no IDP rows in export — endpoint may have "
            "changed or cookies don't include the right league.",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print("[DS] dry-run — skipping CSV write")
        print("Top 10:")
        for r in rows[:10]:
            print("  " + ",".join(r[:7]))
        return 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f"[DS] wrote {OUT_PATH} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
