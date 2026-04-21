#!/usr/bin/env python3
"""Fetch The IDP Show (Adamidp) dynasty IDP rankings.

The article at ``https://www.theidpshow.com/p/idp-dynasty-rankings``
is paywalled, but the rankings themselves are embedded via a
Datawrapper iframe whose ``dataset.csv`` endpoint is publicly
accessible (Datawrapper's CDN doesn't gate the raw data).

Flow
----

1. Read session cookies from ``idpshow_session.json`` (gitignored,
   populated by the user pasting their browser cookies after a login
   — Substack/theidpshow blocks password-based auto-login via
   captcha, so a manual cookie dump is the pragmatic path).
2. ``GET /p/idp-dynasty-rankings`` with cookies attached via
   ``curl_cffi`` Chrome-131 impersonation.
3. Parse the HTML for the Datawrapper iframe URL (chart ID rotates
   whenever the author republishes the chart, so we extract it
   fresh each run rather than hardcoding).
4. Fetch ``https://datawrapper.dwcdn.net/{chart_id}/dataset.csv``.
   The CSV has ~50 columns (PLAYER, POS, OVR, TRADE VALUE +
   combine/college metrics); we only keep name + position + rank.
5. Normalise positions (ED/IDL → DL family, S/CB → DB family) and
   write ``CSVs/site_raw/idpShow.csv`` as ``name,position,rank``.

Cookie refresh
--------------

Substack's session cookie (``connect.sid``) expires on a 90-day
rolling window.  When it expires:

1. Scrape fails with ``paywall`` sentinel detection → stale banner
   surfaces within 60s.
2. User logs in to theidpshow.com in a fresh browser tab.
3. DevTools → Application → Cookies → copy ``connect.sid`` +
   ``AWSALBTG`` + ``AWSALBTGCORS`` values.
4. Edit ``idpshow_session.json`` with the new values.
5. Scraper resumes.

The 3-hour GH Actions workflow also runs this, but until an
encrypted cookie vault is set up, CI will skip ``idpShow`` when the
session file isn't present.

Run
---

    python3 scripts/fetch_idpshow.py
    python3 scripts/fetch_idpshow.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "idpshow_session.json"
ARTICLE_URL = "https://www.theidpshow.com/p/idp-dynasty-rankings"
OUT_PATH = REPO / "CSVs" / "site_raw" / "idpShow.csv"

# Position normalization.  The IDP Show groups pass rushers as ``ED``
# (edge) and interior linemen as ``IDL`` — both fall under the DL
# family in our registry.  ``S`` and ``CB`` fold into the DB family.
_POS_NORM: dict[str, str] = {
    "ED": "DE",
    "IDL": "DT",
    "LB": "LB",
    "S": "S",
    "CB": "CB",
}


def _load_cookies() -> list[dict]:
    """Read cookies from the session file; empty list means
    unauthenticated (fetcher will exit with paywall sentinel)."""
    if not SESSION_PATH.exists():
        return []
    try:
        data = json.loads(SESSION_PATH.read_text())
    except Exception:
        return []
    out: list[dict] = []
    for c in data.get("cookies", []):
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        if c["name"].startswith("_comment"):
            continue
        out.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain") or ".theidpshow.com",
            "path": c.get("path") or "/",
        })
    return out


def _build_session():
    try:
        from curl_cffi import requests as cr
    except ImportError:
        raise SystemExit(
            "curl_cffi required — Substack/theidpshow.com sits behind "
            "Cloudflare.  `pip install curl_cffi`."
        )
    session = cr.Session(impersonate="chrome131")
    for c in _load_cookies():
        try:
            session.cookies.set(
                c["name"], c["value"],
                domain=str(c.get("domain") or "").lstrip("."),
                path=c.get("path") or "/",
            )
        except Exception:
            continue
    return session


def _fetch_article_html(session) -> str:
    r = session.get(ARTICLE_URL, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {ARTICLE_URL} failed: HTTP {r.status_code}"
        )
    return r.text


def _extract_chart_id(html: str) -> str | None:
    """Locate the Datawrapper iframe and return its chart ID.

    The iframe ``src`` looks like
    ``https://datawrapper.dwcdn.net/Kwh7Y/5/`` — we pull the ID
    (``Kwh7Y``) from the path, not the version suffix, because the
    Datawrapper dataset.csv endpoint accepts any version path.
    """
    m = re.search(
        r"datawrapper\.dwcdn\.net/([A-Za-z0-9]+)/(\d+)/",
        html,
    )
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _looks_paywalled(html: str) -> bool:
    """Detect the paywall state.  Authenticated fetches still include
    ``paywall`` in related UI chrome, so we key off the specific
    sentinel phrases that only appear when content is locked."""
    sentinels = (
        "Only paid subscribers",
        "This post is for paid subscribers",
        "Subscribe to read",
        "Log in to read",
    )
    return any(s in html for s in sentinels)


def _fetch_dataset_csv(session, chart_id: str) -> str:
    url = f"https://datawrapper.dwcdn.net/{chart_id}/dataset.csv"
    r = session.get(
        url,
        headers={"Referer": "https://www.theidpshow.com/"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(
            f"GET {url} failed: HTTP {r.status_code}"
        )
    return r.text


def _parse_dataset(csv_text: str) -> list[dict]:
    """Parse the Datawrapper CSV; keep name / normalised position /
    rank and drop every other column (combine metrics, college
    notes, etc. are out of scope for a ranking source)."""
    reader = csv.DictReader(csv_text.splitlines())
    rows_out: list[dict] = []
    for row in reader:
        name = str(row.get("PLAYER") or "").strip()
        if not name:
            continue
        pos_raw = str(row.get("POS") or "").strip().upper()
        pos_norm = _POS_NORM.get(pos_raw, pos_raw)
        ovr_raw = str(row.get("OVR") or "").strip().lstrip("0")
        try:
            rank = int(ovr_raw) if ovr_raw else None
        except (TypeError, ValueError):
            continue
        if rank is None or rank <= 0:
            continue
        rows_out.append({
            "name": name,
            "position": pos_norm,
            "rank": rank,
        })
    return rows_out


def _write_csv(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows_sorted = sorted(rows, key=lambda r: r["rank"])
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "position", "rank"])
        for r in rows_sorted:
            w.writerow([r["name"], r["position"], r["rank"]])
    return len(rows_sorted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape but don't write the CSV.",
    )
    args = parser.parse_args()

    if not SESSION_PATH.exists():
        print(
            f"[idpshow] ERROR: {SESSION_PATH.relative_to(REPO)} missing.  "
            f"Paste browser cookies into that file (see the script's "
            f"module docstring for the refresh flow).",
            file=sys.stderr,
        )
        return 1

    session = _build_session()

    try:
        html = _fetch_article_html(session)
    except RuntimeError as exc:
        print(f"[idpshow] article fetch failed: {exc}", file=sys.stderr)
        return 1

    if _looks_paywalled(html):
        print(
            "[idpshow] session appears expired — article still paywalled.  "
            "Refresh cookies in idpshow_session.json.",
            file=sys.stderr,
        )
        return 1

    chart_id = _extract_chart_id(html)
    if not chart_id:
        print(
            "[idpshow] ERROR: Datawrapper iframe not found in article.  "
            "The author may have removed the chart or switched platforms.",
            file=sys.stderr,
        )
        return 1
    print(f"[idpshow] chart_id={chart_id}")

    try:
        csv_text = _fetch_dataset_csv(session, chart_id)
    except RuntimeError as exc:
        print(f"[idpshow] dataset fetch failed: {exc}", file=sys.stderr)
        return 1

    rows = _parse_dataset(csv_text)
    print(f"[idpshow] parsed {len(rows)} rows")
    if len(rows) < 100:
        print(
            f"[idpshow] WARN: only {len(rows)} rows — expected ~400.  "
            "CSV structure may have changed.",
            file=sys.stderr,
        )

    if args.dry_run:
        print("[idpshow] dry-run — top 5:")
        for r in rows[:5]:
            print(f"  #{r['rank']:<4} {r['position']:<4} {r['name']}")
        return 0

    count = _write_csv(OUT_PATH, rows)
    print(f"[idpshow] wrote {count} rows → {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
