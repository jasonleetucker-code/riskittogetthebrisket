"""Fetch DraftSharks ROS rankings via authenticated Playwright session.

Sister of ``scripts/fetch_draftsharks.py`` — but instead of the
dynasty Superflex page (a season-long valuation board used as a
ROS proxy), this hits the actual ROS-specific pages:

  * ``/ros-rankings/superflex`` — combined offense + IDP ROS list
  * ``/ros-rankings/idp``       — despite the name, NOT an IDP-only
                                  list: a second FULL board over the
                                  same universe, ranked for a
                                  1QB format

These pages render ~25 rows server-side and lazy-load the rest via
JS scroll, so we need a real browser to capture the full ranked
universe (~990 players on the SF page in late April 2026).

Reuses the same ``draftsharks_session.json`` cookie store + login
flow that ``fetch_draftsharks.py`` already established — no new
auth dependency.

Output: writes per-asset CSVs into ``CSVs/site_raw/`` (see
``ROS_RAW_DIR`` below for why that path and not ``data/ros/sources/``),
where the adapter ``src/ros/sources/draftsharks_ros.py`` reads them:

  * ``CSVs/site_raw/draftSharksRosSf.csv``  (offense + IDP, position-tagged)
  * ``CSVs/site_raw/draftSharksRosIdp.csv`` (the ``/ros-rankings/idp``
                                             page verbatim)

WHAT THE IDP FILE ACTUALLY IS (measured 2026-07-30, corrected here —
this docstring previously claimed it was "IDP-only … filtered to IDP
positions", which it has never been).  Both files carry 978 rows over
the *identical* 978 players — zero names unique to either side — and
the SF board already contains all 424 IDP-family rows by itself.  What
differs is the FORMAT: 974 of 978 players sit at a different rank, and
the deltas are positional (RB −171, QB +104, WR +109), i.e. the idp
page is a 1QB board.  ``jahmyr gibbs`` is 1 there against ``josh
allen``'s 17; on the SF board those are 2 and 1.

It is therefore kept as forward-compat / pagination overflow, NOT as a
second opinion.  The adapter unions it name-first behind the SF board
so it contributes only players the SF page did not list (today: zero).
Do not restore the ``_IDP_FAMILIES`` filter to the success branch to
"make the file match its name": ``_write_csv`` renumbers ``rank`` 1..N
and stamps ``total_ranked = N``, so a filtered file would arrive on a
424-player scale for players already carried at 978, and every one of
them would still be excluded by the union — a file nothing reads.

The CSV schema matches the ROS orchestrator's existing format
(``canonicalName,sourceName,position,team,rank,total_ranked,projection``).
``canonicalName`` is left empty — the orchestrator's resolver
fills it on the next scrape pass.
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
from pathlib import Path

from playwright.async_api import Page, async_playwright


REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "draftsharks_session.json"
ENV_PATH = REPO / ".env"
# Output to ``CSVs/site_raw/`` so the artefacts live alongside the
# existing ``draftSharksSf.csv`` / ``draftSharksIdp.csv`` dynasty
# proxies.  The ROS orchestrator's own output path under
# ``data/ros/sources/`` is reserved for the post-resolution CSV the
# adapter pipeline writes — keeping the raw-fetch staging file
# separate prevents the orchestrator's idempotent re-write from
# colliding with our pre-fetch output.
ROS_RAW_DIR = REPO / "CSVs" / "site_raw"

ROS_SF_URL = "https://www.draftsharks.com/ros-rankings/superflex"
ROS_IDP_URL = "https://www.draftsharks.com/ros-rankings/idp"

_OFFENSE_FAMILIES: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})
_IDP_FAMILIES: frozenset[str] = frozenset(
    {"DL", "LB", "DB", "DE", "DT", "EDGE", "NT", "ILB", "OLB", "MLB", "CB", "S", "SS", "FS"}
)

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

CSV_HEADER = [
    "canonicalName",
    "sourceName",
    "position",
    "team",
    "rank",
    "total_ranked",
    "projection",
]


def _load_env_dotfile(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def _load_cookies() -> list[dict]:
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
        out.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain") or "www.draftsharks.com",
                "path": c.get("path") or "/",
                "httpOnly": bool(c.get("httpOnly", True)),
                "secure": bool(c.get("secure", True)),
                "sameSite": str(c.get("sameSite") or "Lax").title(),
            }
        )
    return out


async def _scroll_to_bottom(page: Page, *, max_iters: int = 12) -> None:
    """Lazy-scroll until the row count stops growing."""
    last = 0
    stable = 0
    for _ in range(max_iters):
        rows = await page.locator("[data-player-name]").count()
        if rows == last:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        last = rows
        await page.evaluate("window.scrollBy(0, document.body.scrollHeight)")
        await page.wait_for_timeout(700)


async def _extract_rows(page: Page) -> list[dict]:
    """Pull (rank, name, position) per player in DOM order."""
    rows = await page.evaluate("""
        () => {
            const out = [];
            const seen = new Set();
            for (const el of document.querySelectorAll('[data-player-name]')) {
                const name = el.getAttribute('data-player-name');
                if (!name || seen.has(name)) continue;
                seen.add(name);
                const pos = el.getAttribute('data-fantasy-position') || '';
                out.push({ name, pos });
            }
            return out;
        }
    """)
    return rows or []


async def _fetch_page(page: Page, url: str) -> list[dict]:
    await page.goto(url, wait_until="networkidle", timeout=45000)
    await page.wait_for_timeout(2000)
    await _scroll_to_bottom(page)
    return await _extract_rows(page)


def _classify_position(raw_pos: str) -> str:
    p = (raw_pos or "").strip().upper()
    if not p:
        return ""
    # Take first family on slashed labels like "EDGE/DL".
    p = p.split("/")[0]
    return p


def _write_csv(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = len(rows)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_HEADER)
        w.writeheader()
        for i, r in enumerate(rows, start=1):
            w.writerow(
                {
                    "canonicalName": "",
                    "sourceName": r["name"],
                    "position": _classify_position(r.get("pos") or ""),
                    "team": "",
                    "rank": i,
                    "total_ranked": n,
                    "projection": "",
                }
            )
    return n


async def main_async() -> int:
    _load_env_dotfile(ENV_PATH)
    cookies = _load_cookies()
    if not cookies:
        print(
            "[ds-ros] No DraftSharks session cookies found.  "
            "Run scripts/fetch_draftsharks.py first to mint them."
        )
        return 2

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_USER_AGENT)
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        try:
            sf_rows = await _fetch_page(page, ROS_SF_URL)
            print(f"[ds-ros] superflex page yielded {len(sf_rows)} unique rows")
        except Exception as exc:
            print(f"[ds-ros] superflex fetch failed: {exc}")
            sf_rows = []

        # The IDP-specific page mirrors SF for the IDP positions; we
        # re-fetch it explicitly to pick up any IDPs the SF view paginated
        # off (rare but possible in a deep IDP league).  Fall back to
        # filtering the SF list on failure.
        idp_only_rows: list[dict] = []
        idp_page_failed = False
        try:
            idp_only_rows = await _fetch_page(page, ROS_IDP_URL)
            print(f"[ds-ros] idp page yielded {len(idp_only_rows)} unique rows")
        except Exception as exc:
            idp_page_failed = True
            print(f"[ds-ros] idp fetch failed: {exc}; preserving last-good if present")

        await browser.close()

    if not sf_rows and not idp_only_rows:
        print("[ds-ros] both pages empty; aborting CSV write")
        return 1

    sf_csv = ROS_RAW_DIR / "draftSharksRosSf.csv"
    idp_csv = ROS_RAW_DIR / "draftSharksRosIdp.csv"

    # SF CSV gets every row from the SF page (offense + IDP combined,
    # which is how DS publishes their ROS list).  Position is preserved.
    n_sf = _write_csv(sf_csv, sf_rows)

    # IDP CSV — written verbatim from ``/ros-rankings/idp``, which is a
    # full 1QB board rather than an IDP subset (see the module
    # docstring).  The adapter unions it behind the SF board name-first,
    # so it only ever contributes players the SF page did not list.
    #
    # The SF-filter fallback below is acceptable when the IDP page
    # merely loaded empty, but a FAILED IDP fetch must NOT silently
    # overwrite the last-good IDP CSV with a degraded SF-filtered board
    # (this was a silent-degradation bug).  On failure: preserve
    # last-good if it exists and fail loud; only fall back when there is
    # no prior good CSV (genuine first run).
    idp_degraded = False
    if idp_page_failed and idp_csv.exists():
        print(
            f"[ds-ros] ERROR: IDP page fetch failed — preserving "
            f"last-good {idp_csv.relative_to(REPO)} (NOT overwriting "
            f"with the SF-filtered fallback).",
            file=sys.stderr,
        )
        idp_degraded = True
        n_idp = -1
    else:
        if idp_only_rows:
            idp_filtered = idp_only_rows
        else:
            if idp_page_failed:
                print(
                    "[ds-ros] WARN: IDP page failed and no prior "
                    "draftSharksRosIdp.csv — writing SF-filtered "
                    "fallback (first run only).",
                    file=sys.stderr,
                )
            idp_filtered = [
                r for r in sf_rows if _classify_position(r.get("pos") or "") in _IDP_FAMILIES
            ]
        n_idp = _write_csv(idp_csv, idp_filtered)

    print(f"[ds-ros] wrote {n_sf} rows → {sf_csv.relative_to(REPO)}")
    if n_idp >= 0:
        print(f"[ds-ros] wrote {n_idp} rows → {idp_csv.relative_to(REPO)}")
    return 1 if idp_degraded else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
