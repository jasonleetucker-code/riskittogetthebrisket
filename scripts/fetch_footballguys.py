#!/usr/bin/env python3
"""Fetch FootballGuys dynasty rankings with the operator's league
synced, then write the offense + IDP slices to the source CSVs the
canonical pipeline already consumes.

FootballGuys' dynasty rankings page renders differently based on the
active league selection (scoring rules, TEP, IDP starters).  The two
URLs this script hits use ``leagueid=16023`` which is the operator's
"Risk It To Get The Brisket" FBG league — the ranks returned are the
league-synced view, not the generic public board.

Authentication
--------------

Reads ``FOOTBALLGUYS_EMAIL`` + ``FOOTBALLGUYS_PASSWORD`` from
``.env`` at the repo root (gitignored).  On each run we try the
cached session cookies first (``footballguys_session.json``); if
the authenticated rankings response looks logged-out we launch a
headless Playwright login to mint fresh cookies, save them back to
the session file, and retry the HTTP scrape — no manual cookie
refresh required.

The session file is still honoured as a pre-warmed cache so
routine runs don't need to pay the Playwright cost.

Run
---

    python3 scripts/fetch_footballguys.py

Writes:
    CSVs/site_raw/footballGuysSf.csv   (offense: QB/RB/WR/TE)
    CSVs/site_raw/footballGuysIdp.csv  (IDP: DL/LB/DB)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "footballguys_session.json"
ENV_PATH = REPO / ".env"
OUT_SF = REPO / "CSVs" / "site_raw" / "footballGuysSf.csv"
OUT_IDP = REPO / "CSVs" / "site_raw" / "footballGuysIdp.csv"

LOGIN_URL = "https://www.footballguys.com/login"
# The league-select cookie is set on login but defaults to the
# operator's primary league.  We enforce ``leagueid=16023`` via URL
# query and via a cookie override when persisting, so the scrape is
# always pinned to "Risk It To Get The Brisket".
LEAGUE_ID = "16023"

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


def _load_env_dotfile(path: Path) -> None:
    """Parse ``.env`` and populate ``os.environ`` for any keys it
    doesn't already set.  Minimal inline replacement for
    ``python-dotenv`` so we don't add a runtime dependency."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_cookies() -> dict[str, str]:
    if not SESSION_PATH.exists():
        return {}
    try:
        data = json.loads(SESSION_PATH.read_text())
    except Exception:
        return {}
    return {
        c["name"]: c["value"]
        for c in data.get("cookies", [])
        if isinstance(c, dict) and "name" in c and "value" in c
    }


def _save_cookies(cookies: list[dict]) -> None:
    """Persist Playwright-captured cookies into the session file."""
    payload = {
        "_comment_": (
            "FootballGuys cookies auto-refreshed by "
            "scripts/fetch_footballguys.py using FOOTBALLGUYS_EMAIL / "
            "FOOTBALLGUYS_PASSWORD.  Gitignored."
        ),
        "cookies": [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".footballguys.com"),
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", True)),
                "sameSite": str(c.get("sameSite") or "Lax"),
            }
            for c in cookies
            if isinstance(c, dict)
            and "name" in c
            and c.get("name") in {
                "prodwww",
                "TN_token",
                "TN_tvid",
                "FBG_LeagueSelect_Type",
                "League_selectedid",
            }
        ],
    }
    SESSION_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    try:
        SESSION_PATH.chmod(0o600)
    except Exception:
        pass


def _response_is_authenticated(html: str) -> bool:
    """FBG rankings are paywalled.  Unauthenticated responses render
    exactly 15 "teaser" rows plus a nav "Log In" button wired to the
    login modal via ``data-bs-target="#login_modal"``.  Authenticated
    sessions never render that button.  The button marker is a more
    reliable signal than row count because the teaser table still
    carries ``data-playerid`` attributes."""
    return 'data-bs-target="#login_modal"' not in html


async def _playwright_login() -> list[dict]:
    """Run the browser login flow and return Playwright cookie
    dicts.  Invoked only when the cached cookies fail auth."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:
        raise SystemExit(
            "playwright is required for FG auto-login.  "
            "Install with: pip install playwright && playwright install chromium."
        ) from exc

    email = os.environ.get("FOOTBALLGUYS_EMAIL", "").strip()
    password = os.environ.get("FOOTBALLGUYS_PASSWORD", "").strip()
    if not email or not password:
        raise SystemExit(
            "FOOTBALLGUYS_EMAIL / FOOTBALLGUYS_PASSWORD not set in .env; "
            "cannot auto-refresh cookies.  Either add the credentials to "
            "the server's .env or paste fresh cookies into "
            "footballguys_session.json."
        )

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            context = await browser.new_context(user_agent=_UA)
            page = await context.new_page()
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(1_200)
            await page.fill('input[name="login"]', email)
            await page.fill('input[name="password"]', password)
            await page.click('button[type="submit"]')
            await page.wait_for_timeout(6_000)
            cookies = await context.cookies("https://www.footballguys.com")
            if not any(c.get("name") == "TN_token" for c in cookies):
                errors = await page.evaluate(
                    "() => Array.from(document.querySelectorAll('.alert, .invalid-feedback, [role=alert]'))"
                    ".map(e => e.textContent.trim()).filter(Boolean).slice(0, 3)"
                )
                raise RuntimeError(
                    f"FG login failed — no TN_token issued.  Page errors: {errors}"
                )
            # Force the league cookie so server-side rendering is
            # pinned to the operator's league regardless of the
            # account's current default selection.
            cookies.append({
                "name": "League_selectedid",
                "value": LEAGUE_ID,
                "domain": ".footballguys.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })
            cookies.append({
                "name": "FBG_LeagueSelect_Type",
                "value": "users",
                "domain": ".footballguys.com",
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            })
            return cookies
        finally:
            await browser.close()


def _auto_refresh_session() -> dict[str, str]:
    """Run the Playwright login flow and persist fresh cookies."""
    print("[FBG] cached session rejected — logging in via Playwright …", flush=True)
    new_cookies = asyncio.run(_playwright_login())
    _save_cookies(new_cookies)
    print(
        f"[FBG] logged in; persisted {len(new_cookies)} cookie(s) to {SESSION_PATH.name}",
        flush=True,
    )
    return _load_cookies()


def _fetch(url: str, cookies: dict[str, str]) -> str:
    r = requests.get(
        url,
        cookies=cookies,
        headers={"User-Agent": _UA},
        timeout=30,
    )
    r.raise_for_status()
    if not _response_is_authenticated(r.text):
        raise RuntimeError("unauthenticated_response")
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
    """Filter rows by position family and **preserve the original
    cross-market rank** from the FBG payload.

    Up through 2026-04-20 this function dense-reranked each CSV to
    1..N within position family, which was fine while FBG was treated
    as a rank-only same-universe source.  The move to treat FBG as a
    cross-market source (alongside IDPTC and DraftSharks) means every
    row in both CSVs must carry its ORIGINAL mixed offense+IDP rank
    — e.g. Josh Allen at ``rank=1`` and Jack Campbell at some deeper
    combined rank — so the blend loop can place offense and IDP on
    one ladder.

    Canonical pipeline reads ``name`` and ``rank`` from this CSV; the
    ``position``, ``team``, ``age``, ``years_exp`` columns are
    informational.
    """
    selected = [r for r in rows if r["family"] in include_families]
    # Sort by combined rank so the CSV is still ascending-rank order
    # when the enrichment reader walks it, but DO NOT re-rank — the
    # combined rank must survive into the live pipeline.
    selected.sort(key=lambda r: int(r["rank"]))

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank", "position", "team", "age", "years_exp"])
        for row in selected:
            w.writerow([
                row["name"],
                row["rank"],  # original cross-market rank — not re-densified
                row["position"],
                row["team"],
                row["age"],
                row["years_exp"],
            ])
    return len(selected)


def _fetch_with_auto_login(
    url: str,
    cookies: dict[str, str],
    *,
    label: str,
    allow_refresh: bool = True,
) -> tuple[str, dict[str, str]]:
    """Fetch ``url``; if the response looks logged-out, refresh the
    session via Playwright and retry once.  Returns the HTML and the
    (possibly refreshed) cookie dict so subsequent fetches reuse it.
    """
    try:
        html = _fetch(url, cookies)
        return html, cookies
    except RuntimeError as exc:
        if str(exc) != "unauthenticated_response" or not allow_refresh:
            raise
        print(
            f"[FBG] {label}: session rejected — refreshing cookies …",
            flush=True,
        )
        cookies = _auto_refresh_session()
        html = _fetch(url, cookies)
        return html, cookies


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + parse but don't write the CSVs.",
    )
    args = parser.parse_args()

    _load_env_dotfile(ENV_PATH)
    cookies = _load_cookies()

    # Fetch the unified ``pos=all`` response exactly once.  It carries
    # EVERY player (offense + IDP, ~1000 rows) ordered by FBG's single
    # cross-market consensus rank, with DL / LB / DB family markers
    # resolved per row via the ``pos-XX`` span class.  We then split by
    # family to write the two CSVs the canonical pipeline consumes —
    # both preserving the original combined rank so downstream code can
    # treat FBG SF + IDP as one cross-market ranking source (same
    # pattern used for DraftSharks).  The dedicated ``pos=idp`` fetch
    # path was retired 2026-04-20 because ``pos=idp`` returns IDP rows
    # re-ranked 1..N inside the IDP universe only, which would erase
    # FBG's native offense-vs-IDP ratio.
    print("[FBG] fetching combined rankings (pos=all) …", flush=True)
    all_html, cookies = _fetch_with_auto_login(
        OFFENSE_URL, cookies, label="combined"
    )
    all_rows = parse_rows(all_html)
    print(f"[FBG] combined rows parsed: {len(all_rows)}")

    if args.dry_run:
        print("[FBG] dry-run — skipping CSV writes")
        print("top 5 (combined ranking):")
        for r in all_rows[:5]:
            print(f"  {r}")
        first_idp = next(
            (r for r in all_rows if r["family"] in _IDP_POS), None
        )
        print(f"first IDP row: {first_idp}")
        return 0

    off_written = _write_csv(OUT_SF, all_rows, include_families=_OFFENSE_POS)
    print(f"[FBG] wrote {OUT_SF} ({off_written} rows)")
    idp_written = _write_csv(OUT_IDP, all_rows, include_families=_IDP_POS)
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
