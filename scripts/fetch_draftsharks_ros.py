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
universe (the SF page's size is vendor-controlled and has ranged from
several hundred to ~1000 rows across 2026; see ``_ROS_ROW_FLOORS`` for
why the floors are set well below whatever it currently is).

Reuses the same ``draftsharks_session.json`` cookie store + login
flow that ``fetch_draftsharks.py`` already established — no new
auth dependency.

Output: writes per-asset CSVs into ``CSVs/site_raw/`` (see
``ROS_RAW_DIR`` below for why that path and not ``data/ros/sources/``),
where the adapter ``src/ros/sources/draftsharks_ros.py`` reads them:

  * ``CSVs/site_raw/draftSharksRosSf.csv``  (offense + IDP, position-tagged)
  * ``CSVs/site_raw/draftSharksRosIdp.csv`` (the ``/ros-rankings/idp``
                                             page verbatim)

WHAT THE IDP FILE ACTUALLY IS.  **The two pages are distinct boards
with independent populations, and no code may assume otherwise.**

This paragraph has now been wrong twice in opposite directions, which is
the reason it is written as a rule rather than as a census.  It first
claimed the file was "IDP-only … filtered to IDP positions"; a
2026-07-30 audit replaced that with the opposite — two full boards over
an *identical* 978-player universe, zero names unique to either side, so
"the union contributes zero".  A 2026-08-25 re-measurement (V1-89)
falsified that in turn: the vendor had reshaped both pages, the SF board
was a few hundred rows rather than ~1000, the idp page was genuinely
restricted to IDP families, and the union contributed several hundred
players rather than none.

So the durable statements, none of which depend on a count:

* the SF page and the idp page are **separate acquisitions** whose
  populations, position mixes and ranking formats may differ at any
  time, and have differed in both directions;
* ``_write_csv`` renumbers ``rank`` 1..N per file and stamps
  ``total_ranked = N``, so each board carries its OWN scale.  That is
  what makes unioning them safe without renormalising anything;
* the adapter unions them name-first behind the SF board, so the idp
  page contributes exactly the players the SF page did not list.  That
  contribution may be zero, may be most of the file, and **must not be
  assumed** either way;
* nothing here may be re-derived from a remembered row count.  If a
  decision needs the populations, measure them at the time.

Do not restore an ``_IDP_FAMILIES`` filter to the success branch to
"make the file match its name".  The file is what the vendor publishes
at that URL; filtering it would renumber a subset onto a new scale and
change what the union means.

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

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import Page

# Playwright is imported INSIDE ``main_async`` rather than here, matching
# ``scripts/fetch_draftsharks.py``.  A module-level import makes the file
# unimportable wherever the browser stack is absent — which is the whole
# blocking test tier — and the auth proof below is precisely the part
# that must be exercised deterministically, without a browser or a
# credentialed session.  ``Page`` is annotation-only and
# ``from __future__ import annotations`` keeps those strings at runtime.


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

#: The operator's DraftSharks league.  Its name is rendered into the
#: rankings shell ONLY for an authenticated session with that league
#: selected — measured 2026-08-25 against the live public pages: 0
#: occurrences unauthenticated on ``/ros-rankings/superflex``,
#: ``/ros-rankings/idp`` and the dynasty board.  Kept in step with
#: ``scripts/fetch_draftsharks.LEAGUE_NAME`` by
#: ``tests/scripts/test_draftsharks_ros_auth_proof.py``.
LEAGUE_NAME = "Risk It To Get The Brisket"

#: Minimum rendered rows per ROS page below which the acquisition is
#: structurally implausible and the run fails closed.
#:
#: These are FLOORS, not expectations, and deliberately not today's
#: counts.  Two measurements bracket them (2026-08-25): an
#: unauthenticated fetch of either page renders **25** rows in the shell
#: before lazy-load, while the authenticated boards carried **250** (SF)
#: and **425** (IDP).  A floor has to sit far above the public shell and
#: far below the live board so ordinary vendor churn never trips it —
#: these sit ~5x above the public shell and roughly half of the observed
#: board.
#:
#: Do NOT tighten these toward the live counts.  The vendor reshaped
#: both boards between 2026-07-30 and 2026-08-25 (the SF page was 978
#: rows then, 250 now), and a floor pinned to a snapshot converts an
#: ordinary vendor change into a manufactured outage.
_ROS_ROW_FLOORS: dict[str, int] = {
    ROS_SF_URL: 120,
    ROS_IDP_URL: 200,
}


class RosAuthError(RuntimeError):
    """The ROS page could not be proven to be the authenticated league view.

    Raised rather than returned so it cannot be mistaken for a per-page
    soft failure: an unproven session is a whole-run condition, and the
    caller must exit before any CSV is written so last-good is preserved.
    """


def prove_ros_page_is_league_scoped(
    *,
    url: str,
    html: str,
    rows: list[dict],
    floor: int | None = None,
) -> None:
    """Fail closed unless this page is demonstrably the league's own view.

    ``fetch_draftsharks.py`` proves its passes by showing that the
    WebAssembly worker rewrote values away from the static
    ``data-scoring-value-*`` public defaults.  That proof cannot be
    copied here: the ROS pages carry **zero** ``data-scoring-value``
    attributes (measured 2026-08-25), so there is no public default to
    diverge from.  Inventing a look-alike would be a proof of nothing.

    What IS available, and is used instead:

    1. **the authenticated league marker** — the league's name appears in
       the rendered shell only for a session with it selected.  Absent
       marker is ``AUTH_REQUIRED``, never "the page was quiet";
    2. **a row floor** — a public/expired session still renders a short
       default board, so a plausible-looking page with an implausible
       population is rejected too.

    Both are required.  Either alone is bypassable: a cached shell can
    carry the marker with no board behind it, and a full public board can
    carry no marker at all.

    Raises :class:`RosAuthError`; returns ``None`` on success.
    """
    if LEAGUE_NAME.casefold() not in (html or "").casefold():
        raise RosAuthError(
            f"auth_required: {url} rendered without the authenticated "
            f"league marker — the session cookies are absent, expired, or "
            f"scoped to no league.  Re-mint via scripts/fetch_draftsharks.py."
        )
    bar = _ROS_ROW_FLOORS.get(url, 0) if floor is None else floor
    n = len(rows or [])
    if n < bar:
        raise RosAuthError(
            f"implausible_population: {url} rendered {n} rows, below the "
            f"floor of {bar}.  A truncated or default board must not be "
            f"published as this league's rest-of-season view."
        )


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
    rows = await _extract_rows(page)
    # Proven AFTER the lazy-scroll settles: the row floor is a statement
    # about the finished board, and asserting it mid-scroll would reject
    # every healthy run.
    prove_ros_page_is_league_scoped(url=url, html=await page.content(), rows=rows)
    return rows


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

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print(
            "[ds-ros] playwright not installed.  Run `pip install playwright "
            "&& playwright install chromium`.",
            file=sys.stderr,
        )
        return 2

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        ctx = await browser.new_context(user_agent=_USER_AGENT)
        await ctx.add_cookies(cookies)
        page = await ctx.new_page()

        sf_rows: list[dict] = []
        sf_page_failed = False
        try:
            sf_rows = await _fetch_page(page, ROS_SF_URL)
            print(f"[ds-ros] superflex page yielded {len(sf_rows)} unique rows")
        except RosAuthError as exc:
            # A session that cannot be proven is a whole-run condition,
            # not a page hiccup: the IDP page is served by the same
            # cookies and would fail the same way.  Abort BEFORE any
            # write so both last-good CSVs survive, and exit non-zero so
            # ``run_fetcher`` leaves the freshness stamp where it was.
            await browser.close()
            print(f"[ds-ros] ERROR: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"[ds-ros] superflex fetch failed: {exc}")
            sf_page_failed = True
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
        except RosAuthError as exc:
            await browser.close()
            print(f"[ds-ros] ERROR: {exc}", file=sys.stderr)
            return 2
        except Exception as exc:
            idp_page_failed = True
            print(f"[ds-ros] idp fetch failed: {exc}; preserving last-good if present")

        await browser.close()

    if not sf_rows and not idp_only_rows:
        print("[ds-ros] both pages empty; aborting CSV write")
        return 1

    sf_csv = ROS_RAW_DIR / "draftSharksRosSf.csv"
    idp_csv = ROS_RAW_DIR / "draftSharksRosIdp.csv"

    # SF CSV gets every row from the SF page.  Same silent-degradation
    # rule the IDP branch below already had, which this side lacked: a
    # FAILED SF fetch must not overwrite last-good with a header-only
    # file.  Reachable now that the auth proof can reject a page — and
    # reachable before it, whenever the SF page failed while the IDP page
    # succeeded.
    sf_degraded = False
    if sf_page_failed and sf_csv.exists():
        print(
            f"[ds-ros] ERROR: SF page fetch failed — preserving last-good "
            f"{sf_csv.relative_to(REPO)} (NOT overwriting).",
            file=sys.stderr,
        )
        sf_degraded = True
        n_sf = -1
    else:
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

    if n_sf >= 0:
        print(f"[ds-ros] wrote {n_sf} rows → {sf_csv.relative_to(REPO)}")
    if n_idp >= 0:
        print(f"[ds-ros] wrote {n_idp} rows → {idp_csv.relative_to(REPO)}")
    return 1 if (idp_degraded or sf_degraded) else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    sys.exit(main())
