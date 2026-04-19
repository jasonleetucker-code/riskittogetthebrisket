#!/usr/bin/env python3
"""Fetch DraftSharks dynasty rankings with the user's league synced.

DraftSharks applies league-synced scoring CLIENT-SIDE via a
WebAssembly worker (``RankingsWorker.js`` → ``BoardProcessorDebug.js``).
The server only ever returns the public board.  So this scraper
uses Playwright: launches headless Chromium with saved cookies,
navigates to the rankings page, scrolls to trigger lazy loading of
all players, waits for the worker to finish recomputing each row's
``3D Value +`` under the user's league scoring, then dumps the
rendered DOM.

Output: ``CSVs/site_raw/draftSharks.csv`` with the same header the
manual DS export uses:

    Rank,Team,Player,"Fantasy Position",ADP,Bye,Age,"1yr. Proj",
    "3yr. Proj","5yr. Proj","10yr. Proj","DS Analysis","3D Value +"

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
    python3 scripts/fetch_draftsharks.py --dry-run   # print + skip write
    python3 scripts/fetch_draftsharks.py --headful   # launch visible browser
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "draftsharks_session.json"
OUT_PATH = REPO / "CSVs" / "site_raw" / "draftSharks.csv"

OFFENSE_URL = "https://www.draftsharks.com/dynasty-rankings/te-premium-superflex"
IDP_URL = "https://www.draftsharks.com/dynasty-rankings/idp/te-premium-superflex"
LEAGUE_ID = "995704"  # "Risk It To Get The Brisket"

CSV_HEADER = [
    "Rank",
    "Team",
    "Player",
    "Fantasy Position",
    "ADP",
    "Bye",
    "Age",
    "1yr. Proj",
    "3yr. Proj",
    "5yr. Proj",
    "10yr. Proj",
    "DS Analysis",
    "3D Value +",
]


def _load_cookies() -> list[dict]:
    if not SESSION_PATH.exists():
        raise SystemExit(
            f"Session file not found: {SESSION_PATH}\n"
            "See this script's docstring for how to capture cookies."
        )
    data = json.loads(SESSION_PATH.read_text())
    # Playwright expects: name, value, domain, path, httpOnly, secure, sameSite.
    out: list[dict] = []
    for c in data.get("cookies", []):
        if not isinstance(c, dict) or c.get("name", "").startswith("_"):
            # Skip analytics cookies that Playwright rejects.
            pass
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        if c["name"].startswith("_comment"):
            continue
        out.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain") or "www.draftsharks.com",
            "path": c.get("path") or "/",
            "httpOnly": bool(c.get("httpOnly", True)),
            "secure": bool(c.get("secure", True)),
            "sameSite": str(c.get("sameSite") or "Lax").title(),
        })
    return out


# Extraction JS — walks visible ``<tbody data-player-row>`` blocks
# in DOM order.  Under league-synced view, the worker reorders the
# DOM so DOM position == league-synced rank.  The ``.rank-index``
# span isn't a reliable source once the worker runs, so we use DOM
# order instead.  Hidden rows (x-show='false' under the current
# filter) are skipped via the computed display check so the
# returned list matches what the user sees on screen.
_EXTRACT_JS = r"""() => {
    const rows = Array.from(document.querySelectorAll('tbody[data-player-row]'));
    const out = [];
    for (const tb of rows) {
        // Skip hidden rows — DS hides non-matching rows via x-show
        // when a position filter is active.  We only scrape the
        // currently-visible universe.
        if (tb.offsetParent === null) continue;
        const name = tb.getAttribute('data-player-name') || '';
        const pos = (tb.getAttribute('data-fantasy-position') || '').toUpperCase();
        if (!name) continue;

        const pick = (attr) => {
            const el = tb.querySelector(`[data-attribute="${attr}"]`);
            if (!el) return '';
            const inner = el.querySelector('.column-title');
            return (inner || el).textContent.replace(/\s+/g, ' ').trim();
        };

        // SVG className is an SVGAnimatedString — read the raw class
        // attribute instead.
        let team = '';
        const teamEl = tb.querySelector('[class*="team-abbr-"]');
        if (teamEl) {
            const cls = teamEl.getAttribute('class') || '';
            const m = cls.match(/team-abbr-([a-z]+)/i);
            if (m) team = m[1].toUpperCase();
        }
        if (!team) {
            const logo = tb.querySelector('[class*="team-logo-"]');
            if (logo) {
                const cls = logo.getAttribute('class') || '';
                const m = cls.match(/team-logo-([a-z]+)/i);
                if (m) team = m[1].toUpperCase();
            }
        }

        out.push({
            name,
            team,
            position: pos,
            adp:     pick('adp'),
            bye:     pick('player.team.bye') || pick('bye'),
            age:     pick('player.age') || pick('age'),
            oneYr:   pick('fantasy_points'),
            threeYr: pick('threeYrPts'),
            fiveYr:  pick('fiveYrPts'),
            tenYr:   pick('tenYrPts'),
            comment: pick('comment'),
            dsValue: pick('dsValue'),
        });
    }
    // DOM order IS the ranking — DS's Alpine worker sorts the
    // rendered list so the top row is the highest-valued under the
    // active league's scoring.
    return out;
}"""


async def _scrape_one(
    page,
    url: str,
    *,
    label: str,
    mahomes_threshold: float | None,
) -> list[dict]:
    """Load one DS rankings URL, activate the league, scroll to load
    all rows, and return the extracted player rows."""
    print(f"[DS] ({label}) navigating to {url}", flush=True)
    await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    # Best-effort modal dismiss.
    for sel in [
        'button[aria-label="Close"]',
        "button.dialog-close",
        "button#onetrust-accept-btn-handler",
    ]:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=500):
                await btn.click(timeout=500)
        except Exception:
            pass

    html_initial = await page.content()
    if "Risk It To Get The Brisket" not in html_initial:
        raise RuntimeError(
            f"League 'Risk It To Get The Brisket' not in {label} page HTML — "
            "cookies likely stale; refresh draftsharks_session.json"
        )

    print(f"[DS] ({label}) activating league {LEAGUE_ID} …", flush=True)
    try:
        await page.select_option(
            "#use-my-league-dropdown", value=LEAGUE_ID, timeout=5_000
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to select league {LEAGUE_ID} on {label}: {exc}"
        )

    # Wait for the WASM worker to apply the league scoring.  We poll
    # Mahomes (offense) or Schwesinger (IDP) for an expected
    # league-synced uplift — a settling signal.  If the threshold
    # probe isn't available on this page, just wait a fixed settle
    # time.
    if mahomes_threshold is not None:
        async def _applied() -> bool:
            val = await page.evaluate(r"""() => {
                const rows = Array.from(document.querySelectorAll('tbody[data-player-row]'));
                const probe = rows.find(r => {
                    const n = r.getAttribute('data-player-name') || '';
                    return n.includes('Mahomes') || n.includes('Schwesinger');
                });
                if (!probe) return null;
                const el = probe.querySelector('[data-attribute="dsValue"]');
                return el ? parseFloat(el.textContent.trim()) : null;
            }""")
            return val is not None and val >= mahomes_threshold
        for _ in range(30):
            if await _applied():
                break
            await page.wait_for_timeout(1_000)

    print(f"[DS] ({label}) scrolling to load all rows …", flush=True)
    last_count = 0
    stable = 0
    for _ in range(60):
        count = await page.locator("tbody[data-player-row]").count()
        if count == last_count and count > 50:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last_count = count
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(900)
    print(f"[DS] ({label}) rows loaded: {last_count}", flush=True)

    # Extra settle time for Alpine re-render after worker messages.
    await page.wait_for_timeout(2_000)

    rows = await page.evaluate(_EXTRACT_JS)
    print(f"[DS] ({label}) extracted visible rows: {len(rows)}", flush=True)
    return rows


async def _scrape(*, headless: bool) -> list[dict]:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise SystemExit(
            "playwright not installed.  Run `pip install playwright && "
            "playwright install chromium`."
        )

    cookies = _load_cookies()

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/147.0 Safari/537.36"
                ),
                viewport={"width": 1400, "height": 1100},
            )
            await context.add_cookies(cookies)
            page = await context.new_page()

            # Offense: load the default TEP-superflex page; Mahomes
            # public value is 74, league-synced ~81 in a
            # TE-premium + IDP-heavy league, so use 78 as settle
            # threshold.
            offense_rows = await _scrape_one(
                page,
                OFFENSE_URL,
                label="offense",
                mahomes_threshold=78,
            )

            # IDP: load the IDP-only view.  Schwesinger public 44,
            # league-synced still around 44; use 30 as a loose
            # "something loaded" threshold.
            idp_rows = await _scrape_one(
                page,
                IDP_URL,
                label="idp",
                mahomes_threshold=30,
            )

            # Merge: offense first (higher scale values) then IDP.
            # DS's 3D Value + scale is shared so the combined pool
            # orders correctly by value desc.
            def _val(r: dict) -> float:
                try:
                    return float(str(r.get("dsValue") or "0").replace(",", ""))
                except (TypeError, ValueError):
                    return 0.0
            combined = offense_rows + idp_rows
            combined.sort(key=_val, reverse=True)
            # De-dupe on (name, position) in case of overlap.
            seen: set[tuple[str, str]] = set()
            deduped: list[dict] = []
            for r in combined:
                k = (r.get("name", ""), r.get("position", ""))
                if k in seen:
                    continue
                seen.add(k)
                deduped.append(r)
            print(f"[DS] merged rows: {len(deduped)} (dedupe dropped {len(combined) - len(deduped)})")
            return deduped
        finally:
            await browser.close()


def _write_csv(rows: list[dict]) -> int:
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for i, r in enumerate(rows, 1):
            w.writerow([
                i,
                r.get("team") or "",
                r.get("name") or "",
                r.get("position") or "",
                r.get("adp") or "",
                r.get("bye") or "",
                r.get("age") or "",
                r.get("oneYr") or "",
                r.get("threeYr") or "",
                r.get("fiveYr") or "",
                r.get("tenYr") or "",
                r.get("comment") or "",
                r.get("dsValue") or "",
            ])
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape but don't write the CSV.",
    )
    parser.add_argument(
        "--headful", action="store_true",
        help="Launch the browser visibly (useful for debugging).",
    )
    args = parser.parse_args()

    rows = asyncio.run(_scrape(headless=not args.headful))

    if not rows:
        print("[DS] ERROR: no rows extracted", file=sys.stderr)
        return 1

    # Family split sanity-check.
    idp = {"DL", "LB", "DB", "DE", "DT", "EDGE", "CB", "S"}
    off_count = sum(1 for r in rows if r.get("position") in {"QB", "RB", "WR", "TE"})
    idp_count = sum(1 for r in rows if r.get("position") in idp)
    print(f"[DS] family split: offense={off_count} idp={idp_count}")
    if idp_count == 0:
        print(
            "[DS] ERROR: no IDP rows — league-synced scrape probably "
            "didn't complete (worker hung or cookies missing league context).",
            file=sys.stderr,
        )
        return 1

    if args.dry_run:
        print("[DS] dry-run — skipping CSV write")
        print("Top 15:")
        for i, r in enumerate(rows[:15], 1):
            print(
                f"  #{i:>3} {(r.get('name') or ''):<28} "
                f"[{(r.get('position') or ''):<3}] "
                f"value={r.get('dsValue') or ''}"
            )
        return 0

    n = _write_csv(rows)
    print(f"[DS] wrote {OUT_PATH} ({n} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
