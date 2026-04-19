#!/usr/bin/env python3
"""Fetch FootballGuys dynasty rankings with the operator's league
synced, then write the offense + IDP slices to the source CSVs the
canonical pipeline already consumes.

FootballGuys' dynasty rankings page renders differently based on the
active league selection (scoring rules, TEP, IDP starters).  The two
URLs this script hits use ``leagueid=16023`` which is the operator's
"Risk It To Get The Brisket" FBG league — the ranks returned are the
league-synced view, not the generic public board.

Replaces the prior workflow of manually downloading PDF / CSV exports
from FBG and running ``scripts/parse_footballguys_pdf.py``.  The PDF
parser is kept alive as a fallback when session cookies expire.

Authentication
--------------

Cookies are loaded from ``footballguys_session.json`` at the repo
root (gitignored).  To refresh:

1. Log in to https://www.footballguys.com/ in a browser.
2. Ensure the correct league is selected in the League Settings
   dropdown on the rankings page (``leagueid=16023`` for this repo).
3. Open DevTools → Application → Cookies → ``https://www.footballguys.com``
   and copy the values of:
      * ``prodwww`` (HttpOnly session cookie, the big one)
      * ``TN_token`` (HttpOnly persistent auth)
      * ``League_selectedid``
      * ``FBG_LeagueSelect_Type``
4. Paste them into ``footballguys_session.json`` (same shape as the
   existing file).  Keep domain = ``.footballguys.com``.

Run
---

    python3 scripts/fetch_footballguys.py

Writes:
    CSVs/site_raw/footballGuysSf.csv   (offense: QB/RB/WR/TE)
    CSVs/site_raw/footballGuysIdp.csv  (IDP: DL/LB/DB)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "footballguys_session.json"
OUT_SF = REPO / "CSVs" / "site_raw" / "footballGuysSf.csv"
OUT_IDP = REPO / "CSVs" / "site_raw" / "footballGuysIdp.csv"

OFFENSE_URL = (
    "https://www.footballguys.com/rankings/duration/dynasty"
    "?leagueid=16023&consensus=1&pos=all&year=2026&week=0"
    "&durationTypeKey=dynasty&userId=526907&rankerId=0"
)
IDP_URL = (
    "https://www.footballguys.com/rankings/duration/dynasty"
    "?leagueid=16023&consensus=1&pos=idp&year=2026&week=0"
    "&durationTypeKey=dynasty&userId=526907&rankerId=0"
)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0 Safari/537.36"
)

# FBG class prefix → canonical position.  EDGE / DE / DT fold up to
# DL; CB / S fold up to DB for the IDP universe.  The canonical
# pipeline normalises aliases further via ``src.utils.name_clean``.
_POS_MAP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB",
    "WR": "WR",
    "TE": "TE",
    "PK": "K",
    "K": "K",
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "SS": "DB",
    "FS": "DB",
    "IDP": "IDP",  # fallback — gets resolved via sleeper positions map downstream
}

_OFFENSE_POS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})
_IDP_POS: frozenset[str] = frozenset({"DL", "LB", "DB"})


def _load_cookies() -> dict[str, str]:
    if not SESSION_PATH.exists():
        raise SystemExit(
            f"Session file not found: {SESSION_PATH}\n"
            "See this script's docstring for how to capture cookies."
        )
    data = json.loads(SESSION_PATH.read_text())
    return {c["name"]: c["value"] for c in data.get("cookies", [])}


def _fetch(url: str, cookies: dict[str, str]) -> str:
    r = requests.get(
        url,
        cookies=cookies,
        headers={"User-Agent": _UA},
        timeout=30,
    )
    r.raise_for_status()
    if "login_modal" in r.text and "logout" not in r.text.lower():
        raise RuntimeError(
            "FBG response looks unauthenticated (login_modal present, "
            "no logout link).  Cookies likely expired — re-capture per "
            "the docstring in this script."
        )
    return r.text


_ROW_RE = re.compile(
    r'<tr[^>]*data-playerid="([^"]+)"[^>]*data-playername="([^"]+)"'
    r'[^>]*data-rank="(\d+)"[^>]*class="player-row[^"]*"[^>]*>'
    r'(.*?)</tr>',
    re.DOTALL,
)
_POS_RE = re.compile(r'<span class="pos-([A-Z]+)">([A-Z]+\d*)</span>')
_TEAM_RE = re.compile(r'<span class="team-abbr team-abbr-([A-Z]+)">')
# The last 3 standalone <td>N</td> cells on each row are age, years_exp,
# and bye week.  The regex below captures those three closing cells.
_TRAIL_RE = re.compile(
    r'<td>([^<]*)</td><td>([^<]*)</td><td>([^<]*)</td>\s*$',
    re.DOTALL,
)


def parse_rows(html: str, *, default_family: str | None = None) -> list[dict[str, str]]:
    """Return one dict per player row with the fields we need.

    The offense page (pos=all) renders ``<span class="pos-QB">QB1</span>``
    per row so we know the exact position + positional ordinal per
    player.  The IDP page (pos=idp) omits the position column —
    every row IS an IDP but the DL/LB/DB breakdown isn't surfaced.
    When ``default_family="IDP"`` we stamp ``IDP`` for missing pos
    spans; the downstream enrichment path cross-references each name
    with the sleeper positions map to assign the real DL/LB/DB
    family, so the CSV doesn't need to carry it.
    """
    out: list[dict[str, str]] = []
    for pid, name, rank_s, body in _ROW_RE.findall(html):
        try:
            rank = int(rank_s)
        except ValueError:
            continue
        pos_m = _POS_RE.search(body)
        if pos_m:
            raw_family = pos_m.group(1).upper()
            canonical_family = _POS_MAP.get(raw_family, "")
            position_display = pos_m.group(2)  # e.g. "QB1"
        elif default_family:
            canonical_family = default_family
            position_display = default_family
        else:
            continue
        team_m = _TEAM_RE.search(body)
        team = team_m.group(1) if team_m else ""
        trail_m = _TRAIL_RE.search(body)
        age = years_exp = ""
        if trail_m:
            age = trail_m.group(1).strip()
            years_exp = trail_m.group(2).strip()
            # trail_m.group(3) is bye; we don't surface it
        out.append({
            "name": name.strip(),
            "rank": str(rank),
            "position": position_display,
            "family": canonical_family,
            "team": team,
            "age": age,
            "years_exp": years_exp,
        })
    return out


def _write_csv(
    path: Path,
    rows: list[dict[str, str]],
    *,
    include_families: frozenset[str],
) -> int:
    """Filter rows by position family and dense-rank 1..N.

    Canonical pipeline reads ``name`` and ``rank`` from this CSV; the
    ``position``, ``team``, ``age``, ``years_exp`` columns are
    informational.  We write the positional ordinal (e.g. ``QB1``) in
    the position column to match the schema the PDF-parser version
    produced.
    """
    selected = [r for r in rows if r["family"] in include_families]
    # Dense rank 1..N within the filtered slice so downstream's
    # rank-signal synthesis sees a contiguous ordering.
    selected.sort(key=lambda r: int(r["rank"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank", "position", "team", "age", "years_exp"])
        for new_rank, row in enumerate(selected, 1):
            w.writerow([
                row["name"],
                new_rank,
                row["position"],
                row["team"],
                row["age"],
                row["years_exp"],
            ])
    return len(selected)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse but don't write the CSVs.",
    )
    args = parser.parse_args()

    cookies = _load_cookies()

    print("[FBG] fetching offense rankings …", flush=True)
    off_html = _fetch(OFFENSE_URL, cookies)
    off_rows = parse_rows(off_html)
    print(f"[FBG] offense rows parsed: {len(off_rows)}")

    print("[FBG] fetching IDP rankings …", flush=True)
    idp_html = _fetch(IDP_URL, cookies)
    # IDP page has no per-row position column — every row is an IDP
    # player; we pass default_family="IDP" so the rows get through
    # and the downstream pipeline's sleeper positions map assigns
    # the real DL/LB/DB family at enrichment time.
    idp_rows = parse_rows(idp_html, default_family="IDP")
    print(f"[FBG] IDP rows parsed: {len(idp_rows)}")

    if args.dry_run:
        print("[FBG] dry-run — skipping CSV writes")
        print("offense top 5:")
        for r in off_rows[:5]:
            print(f"  {r}")
        print("IDP top 5:")
        for r in idp_rows[:5]:
            print(f"  {r}")
        return 0

    off_written = _write_csv(OUT_SF, off_rows, include_families=_OFFENSE_POS)
    print(f"[FBG] wrote {OUT_SF} ({off_written} rows)")
    # IDP page has no DL/LB/DB markers per row, so every row carries
    # family="IDP" and the enrichment path resolves the real family
    # via the sleeper positions map downstream.
    idp_written = _write_csv(OUT_IDP, idp_rows, include_families=frozenset({"IDP"}))
    print(f"[FBG] wrote {OUT_IDP} ({idp_written} rows)")

    if off_written == 0 or idp_written == 0:
        print(
            "[FBG] ERROR: zero rows written for one or both sides — "
            "session likely stale or HTML structure changed",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
