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

The offense-combined rankings URL (``/dynasty-rankings/te-premium-superflex``)
holds the full 874-row universe in a single DOM: QB/RB/WR/TE
rows are visible, DL/LB/DB rows are rendered with ``display:none``
when the page's default position filter hides them.  We extract
ALL rows (including hidden ones) because the dsValue of every
player is a cross-universe comparable number in that view — e.g.
Carson Schwesinger shows value 44 at overall rank 36 among all
positions.  The IDP-only URL uses a DIFFERENT scale (Schwesinger
shows 81 rescaled to IDP-universe), so we deliberately do not
scrape it — merging the two scales would produce ugly value
collisions.

Output: TWO CSVs, same header as the manual DS export:

    CSVs/site_raw/draftSharksSf.csv    (QB/RB/WR/TE)
    CSVs/site_raw/draftSharksIdp.csv   (DL/LB/DB + aliases)

Authentication
--------------

Reads ``DRAFTSHARKS_EMAIL`` + ``DRAFTSHARKS_PASSWORD`` from ``.env``
at the repo root (gitignored).  On each run we try the cached
session cookies first (``draftsharks_session.json``); if the
rankings page comes back without the operator's league name we
run the in-browser DS login flow to mint fresh cookies, save them
back to the session file, and continue the scrape — no manual
cookie refresh required.

The session file is honoured as a pre-warmed cache so routine
runs don't re-log-in every time.

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
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "draftsharks_session.json"
ENV_PATH = REPO / ".env"
OUT_SF = REPO / "CSVs" / "site_raw" / "draftSharksSf.csv"
OUT_IDP = REPO / "CSVs" / "site_raw" / "draftSharksIdp.csv"

HOME_URL = "https://www.draftsharks.com/"
LOGIN_URL = "https://www.draftsharks.com/login"
RANKINGS_URL = "https://www.draftsharks.com/dynasty-rankings/te-premium-superflex"
LEAGUE_ID = "995704"  # "Risk It To Get The Brisket"

# Position-family classifier for the single combined DOM.  QB/RB/WR/TE
# go to the SF CSV; DL/LB/DB (plus all common aliases) go to the IDP
# CSV.  Rows with other or missing positions are dropped.
_OFFENSE_FAMILIES: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})
_IDP_FAMILIES: frozenset[str] = frozenset(
    {"DL", "LB", "DB", "DE", "DT", "EDGE", "NT", "ILB", "OLB", "MLB",
     "CB", "S", "SS", "FS"}
)

# Only these cookies matter for auth + league context.  Everything
# else (analytics, consent, etc.) would bloat the session file and
# cause needless churn on refresh.
_AUTH_COOKIE_NAMES: frozenset[str] = frozenset(
    {"PHPSESSID", "_identity", "_frontendCSRF", "_csrf-frontend"}
)

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


def _load_env_dotfile(path: Path) -> None:
    """Parse ``.env`` and populate ``os.environ`` for any keys it
    doesn't already set.  Minimal inline replacement for
    ``python-dotenv`` so we don't add a runtime dependency."""
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _load_cookies() -> list[dict]:
    """Return Playwright-shaped cookie dicts from the session file.
    Returns ``[]`` (not ``SystemExit``) when the file is missing so
    the caller can fall through to ``_browser_login``."""
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
            "domain": c.get("domain") or "www.draftsharks.com",
            "path": c.get("path") or "/",
            "httpOnly": bool(c.get("httpOnly", True)),
            "secure": bool(c.get("secure", True)),
            "sameSite": str(c.get("sameSite") or "Lax").title(),
        })
    return out


def _save_cookies(cookies: list[dict]) -> None:
    """Persist Playwright-captured cookies into the session file.
    Only the auth-relevant cookies are stored — analytics cookies
    add churn without buying anything."""
    payload = {
        "_comment_": (
            "DraftSharks cookies auto-refreshed by "
            "scripts/fetch_draftsharks.py using DRAFTSHARKS_EMAIL / "
            "DRAFTSHARKS_PASSWORD.  Gitignored."
        ),
        "cookies": [
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", "www.draftsharks.com"),
                "path": c.get("path", "/"),
                "httpOnly": bool(c.get("httpOnly", True)),
                "secure": bool(c.get("secure", True)),
                "sameSite": str(c.get("sameSite") or "Lax").title(),
            }
            for c in cookies
            if isinstance(c, dict)
            and "name" in c
            and c.get("name") in _AUTH_COOKIE_NAMES
        ],
    }
    SESSION_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    try:
        SESSION_PATH.chmod(0o600)
    except Exception:
        pass


async def _browser_login(context, page) -> None:
    """Run the DS login flow in the current browser context and
    persist fresh cookies.  Caller must reload any rankings page
    after this returns."""
    email = os.environ.get("DRAFTSHARKS_EMAIL", "").strip()
    password = os.environ.get("DRAFTSHARKS_PASSWORD", "").strip()
    if not email or not password:
        raise SystemExit(
            "DRAFTSHARKS_EMAIL / DRAFTSHARKS_PASSWORD not set in .env; "
            "cannot auto-refresh cookies.  Either add the credentials to "
            "the server's .env or paste fresh cookies into "
            "draftsharks_session.json."
        )

    print("[DS] cached session rejected — logging in via Playwright …", flush=True)
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
    await page.wait_for_timeout(1_200)
    await page.fill('input[name="LoginForm[email]"]', email)
    await page.fill('input[name="LoginForm[password]"]', password)
    await page.click('button[name="login-button"]')
    # Wait for the server to issue ``_identity`` (the "remember-me"
    # cookie that survives across requests).  DS's login redirects
    # to ``/`` on success so ``_identity`` appears within a couple
    # of seconds.
    authenticated = False
    for _ in range(20):
        await page.wait_for_timeout(500)
        current_cookies = await context.cookies("https://www.draftsharks.com")
        if any(c.get("name") == "_identity" for c in current_cookies):
            authenticated = True
            break
    if not authenticated:
        errors = await page.evaluate(
            "() => Array.from(document.querySelectorAll('.alert, .help-block-error, [role=alert]'))"
            ".map(e => e.textContent.trim()).filter(Boolean).slice(0, 3)"
        )
        raise RuntimeError(
            f"DS login failed — no _identity cookie issued.  Page errors: {errors}"
        )
    fresh_cookies = await context.cookies("https://www.draftsharks.com")
    _save_cookies(fresh_cookies)
    count = sum(1 for c in fresh_cookies if c.get("name") in _AUTH_COOKIE_NAMES)
    print(
        f"[DS] logged in; persisted {count} cookie(s) to {SESSION_PATH.name}",
        flush=True,
    )


# Extraction JS — walks every ``<tbody data-player-row>`` in the DOM,
# including rows that the default position filter hides with
# ``display:none``.  The offense-combined URL puts the entire 874-
# player universe in one table; IDP rows are hidden but still carry
# the correct cross-universe dsValue + rank-index from the
# WebAssembly worker (e.g. Carson Schwesinger at value 44, rank 36
# when the IDP filter is off).  We sort by DOM order so rank
# ordering matches what DS would show if the user toggled the
# position filter, and we tag each row with its raw family so
# ``main`` can split the rows into the SF / IDP CSVs.
_EXTRACT_JS = r"""() => {
    const rows = Array.from(document.querySelectorAll('tbody[data-player-row]'));
    const out = [];
    for (const tb of rows) {
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

        // ``.rank-index`` reflects DS's own cross-universe rank
        // after the worker settles — more reliable than DOM order
        // because hidden rows still carry the correct rank.
        const rankEl = tb.querySelector('.rank-index');
        const rankRaw = rankEl ? rankEl.textContent.trim() : '';
        const rankNum = rankRaw ? parseInt(rankRaw, 10) : null;

        out.push({
            name,
            team,
            position: pos,
            dsRank:  Number.isFinite(rankNum) ? rankNum : null,
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
    return out;
}"""


async def _scrape_one(page) -> list[dict]:
    """Load the DS offense-combined rankings page, activate the
    league so the WASM worker applies league scoring, scroll to
    load the full ~874-row DOM, and return every row (hidden
    included).  Rows carry their cross-universe dsValue and
    DS-assigned ``.rank-index``, which the caller splits into
    offense / IDP CSVs."""
    print(f"[DS] navigating to {RANKINGS_URL}", flush=True)
    await page.goto(RANKINGS_URL, wait_until="domcontentloaded", timeout=45_000)
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
        # Sentinel string picked up by _scrape() to trigger auto-login.
        raise RuntimeError("unauthenticated_session")

    print(f"[DS] activating league {LEAGUE_ID} …", flush=True)
    try:
        await page.select_option(
            "#use-my-league-dropdown", value=LEAGUE_ID, timeout=5_000
        )
    except Exception as exc:
        raise RuntimeError(
            f"Failed to select league {LEAGUE_ID}: {exc}"
        )

    # Wait for the WASM worker to apply the league scoring.  Mahomes
    # public value is 74, league-synced ~81 in a TE-premium + IDP-
    # heavy league; poll until his dsValue crosses 78 so we know the
    # worker has finished reshuffling.
    async def _applied() -> bool:
        val = await page.evaluate(r"""() => {
            const rows = Array.from(document.querySelectorAll('tbody[data-player-row]'));
            const probe = rows.find(r => (r.getAttribute('data-player-name') || '').includes('Mahomes'));
            if (!probe) return null;
            const el = probe.querySelector('[data-attribute="dsValue"]');
            return el ? parseFloat(el.textContent.trim()) : null;
        }""")
        return val is not None and val >= 78
    for _ in range(30):
        if await _applied():
            break
        await page.wait_for_timeout(1_000)

    print("[DS] scrolling to load all rows …", flush=True)
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
    print(f"[DS] rows loaded: {last_count}", flush=True)

    # Extra settle time for Alpine re-render after worker messages.
    await page.wait_for_timeout(2_000)

    rows = await page.evaluate(_EXTRACT_JS)
    print(f"[DS] extracted rows (incl hidden): {len(rows)}", flush=True)
    return rows


async def _scrape_with_autologin(context, page) -> list[dict]:
    """Wrapper around ``_scrape_one`` that catches the
    ``unauthenticated_session`` sentinel, runs the browser login
    once, then retries the scrape with the fresh cookies that
    Playwright now holds in-context."""
    try:
        return await _scrape_one(page)
    except RuntimeError as exc:
        if str(exc) != "unauthenticated_session":
            raise
        await _browser_login(context, page)
        # After login the context already carries the fresh cookies,
        # so re-navigating the URL picks up the authenticated view.
        return await _scrape_one(page)


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
            if cookies:
                await context.add_cookies(cookies)
            page = await context.new_page()
            return await _scrape_with_autologin(context, page)
        finally:
            await browser.close()


def _value_of(row: dict) -> float:
    try:
        return float(str(row.get("dsValue") or "0").replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def _write_csv(
    path: Path,
    rows: list[dict],
    *,
    include_families: frozenset[str],
) -> int:
    """Filter rows by position family, dense-rank 1..N by DS value,
    and write to ``path``.  Values preserved as DS rendered them
    (cross-universe scale), so Schwesinger's IDP CSV row will show
    the same value the user sees on the offense-combined page
    (e.g. 44, not the IDP-only-page rescaled 81)."""
    selected = [r for r in rows if r.get("position", "").upper() in include_families]
    # Sort by DS value desc; ties broken by DS's own rank-index, then
    # by name.  The DS worker may assign the same dsValue to multiple
    # players; use rank-index to disambiguate ordering.
    def _rank_sort_key(r: dict) -> tuple[float, int, str]:
        return (
            -_value_of(r),
            int(r.get("dsRank") or 99999),
            (r.get("name") or "").lower(),
        )
    selected.sort(key=_rank_sort_key)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for i, r in enumerate(selected, 1):
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
    return len(selected)


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

    _load_env_dotfile(ENV_PATH)
    rows = asyncio.run(_scrape(headless=not args.headful))

    if not rows:
        print("[DS] ERROR: no rows extracted", file=sys.stderr)
        return 1

    # Family split sanity-check.  We deliberately scrape only the
    # offense-combined page because its DOM carries the full
    # cross-universe universe (QB + IDP on the same dsValue scale),
    # so a missing IDP count here means the worker didn't settle
    # or the position attribute normalization changed.
    off_count = sum(
        1 for r in rows if r.get("position", "").upper() in _OFFENSE_FAMILIES
    )
    idp_count = sum(
        1 for r in rows if r.get("position", "").upper() in _IDP_FAMILIES
    )
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
        print("Top 10 offense:")
        off_sorted = sorted(
            (r for r in rows if r.get("position", "").upper() in _OFFENSE_FAMILIES),
            key=lambda r: (-_value_of(r), int(r.get("dsRank") or 99999)),
        )
        for i, r in enumerate(off_sorted[:10], 1):
            print(
                f"  #{i:>3} {(r.get('name') or ''):<28} "
                f"[{(r.get('position') or ''):<3}] "
                f"value={r.get('dsValue') or ''} "
                f"dsRank={r.get('dsRank')}"
            )
        print("Top 10 IDP:")
        idp_sorted = sorted(
            (r for r in rows if r.get("position", "").upper() in _IDP_FAMILIES),
            key=lambda r: (-_value_of(r), int(r.get("dsRank") or 99999)),
        )
        for i, r in enumerate(idp_sorted[:10], 1):
            print(
                f"  #{i:>3} {(r.get('name') or ''):<28} "
                f"[{(r.get('position') or ''):<3}] "
                f"value={r.get('dsValue') or ''} "
                f"dsRank={r.get('dsRank')}"
            )
        return 0

    off_written = _write_csv(OUT_SF, rows, include_families=_OFFENSE_FAMILIES)
    print(f"[DS] wrote {OUT_SF} ({off_written} rows)")
    idp_written = _write_csv(OUT_IDP, rows, include_families=_IDP_FAMILIES)
    print(f"[DS] wrote {OUT_IDP} ({idp_written} rows)")
    if off_written == 0 or idp_written == 0:
        print(
            "[DS] ERROR: zero rows written for one or both families — "
            "check the family classifier or scrape step output",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
