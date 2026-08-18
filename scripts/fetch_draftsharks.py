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

HOW THE BOARD IS LOADED (corrected 2026-08-18 — the previous
description was obsolete and had cost 12 days of silent staleness).

This file used to state that ``/dynasty-rankings/te-premium-superflex``
"holds the full 874-row universe in a single DOM" with DL/LB/DB rows
merely hidden by ``display:none``.  That stopped being true.  The page
now server-renders ~25 rows and loads the rest over **htmx**
(``hx-get="/dynasty-rankings/load-table"``, ``hx-include="#sharedParams"``),
and ``#sharedParams`` carries a ``fantasyPosition`` filter that decides
which families are RENDERED AT ALL.  Extracting "all rows including
hidden ones" therefore returned offense only, `idp_count == 0` tripped
the zero-IDP guard on every 2-hourly run from 2026-08-05, and last-good
preservation correctly kept serving 12-day-old CSVs.

So we harvest the unfiltered board first and stop there when it already
carries both families.  Only when IDP is genuinely absent do we traverse
the page's OWN ``fantasyPosition`` control — same URL, same
league-scored session, same settled worker values — and union the passes
on DraftSharks' own ``data-key``.

That union is gated on a proof, not an assumption: an asset seen in two
passes must carry the SAME ``3D Value +`` as an exact ``Decimal``, over
at least ``_MIN_OVERLAP_FOR_EQUIVALENCE`` overlapping assets.  Too few
overlaps, any value conflict, or a vendor-id collision all FAIL CLOSED.

Still deliberately NOT scraped: the IDP-only URL
(``/dynasty-rankings/idp``) and the ROS boards.  Those are separately
rescaled — the same defender reads 44 on the combined board and 81 on
the IDP-only one — and merging scales would splice two currencies.

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
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "draftsharks_session.json"
ENV_PATH = REPO / ".env"
OUT_SF = REPO / "CSVs" / "site_raw" / "draftSharksSf.csv"
OUT_IDP = REPO / "CSVs" / "site_raw" / "draftSharksIdp.csv"

# Contract-aligned row-count floors (== _DEFAULT_SOURCE_ROW_FLOORS in
# src/api/data_contract.py).  Existing guards catch idp_count==0 and
# all-zero IDP values, but a structurally-short-but-nonzero scrape
# still overwrote last-good and then hard-failed the contract floor
# on a clean checkout.  Fail loud + preserve last-good if either
# family is below its floor.
_DS_SF_ROW_FLOOR: int = 190
_DS_IDP_ROW_FLOOR: int = 85

HOME_URL = "https://www.draftsharks.com/"
LOGIN_URL = "https://www.draftsharks.com/login"
RANKINGS_URL = "https://www.draftsharks.com/dynasty-rankings/te-premium-superflex"
LEAGUE_ID = "995704"  # "Risk It To Get The Brisket"
LEAGUE_NAME = "Risk It To Get The Brisket"

# Position-family classifier for the single combined DOM.  QB/RB/WR/TE
# go to the SF CSV; DL/LB/DB (plus all common aliases) go to the IDP
# CSV.  Rows with other or missing positions are dropped.
_OFFENSE_FAMILIES: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})
_IDP_FAMILIES: frozenset[str] = frozenset(
    {"DL", "LB", "DB", "DE", "DT", "EDGE", "NT", "ILB", "OLB", "MLB", "CB", "S", "SS", "FS"}
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


# ── Pure parsing seam ────────────────────────────────────────────────
#
# Extraction used to live entirely in a JS string evaluated against a
# live Playwright ``Page``, which meant nothing could be tested without
# a browser and the 2026-08 breakage sat undetected for 12 days.  The
# parser below is the ONE owner of "HTML -> rows"; navigation only
# fetches HTML and hands it here.  There is deliberately no second
# JS implementation — a duplicate that agrees today is still a second
# owner.
#
# THE VALUE TRAP, stated because it is easy to get backwards.  Every
# value cell carries static ``data-scoring-value-*`` attributes (one
# per site scoring format).  Those are DraftSharks' PUBLIC defaults.
# When our league is activated the WebAssembly worker rewrites the
# RENDERED text and leaves those attributes alone, so reading
# ``data-scoring-value-te-premium-superflex`` would silently harvest
# public values while every league-activation gate above reported
# success.  We read rendered ``.column-title`` text, and
# ``tests/scripts/test_fetch_draftsharks.py`` pins that we never read
# the attribute form.

_TEAM_CLASS_RE = re.compile(r"team-(?:abbr|logo)-([a-z]+)", re.I)


def classify_position(raw: str) -> str:
    """Canonical family for a DS position label.

    DS emits compound labels such as ``"EDGE/DL"``.  The previous
    exact-match against the family sets classified those as NEITHER, so
    they were dropped from both CSVs with no counter and no log line.
    Mirrors ``fetch_draftsharks_ros.py::_classify_position``.
    """
    token = str(raw or "").upper().strip()
    if not token:
        return ""
    for part in re.split(r"[/,|]", token):
        part = part.strip()
        if part in _OFFENSE_FAMILIES or part in _IDP_FAMILIES:
            return part
    return token.split("/")[0].strip()


def family_of(position: str) -> str | None:
    """``"offense"`` / ``"idp"`` / ``None`` for an unclassifiable row."""
    pos = classify_position(position)
    if pos in _OFFENSE_FAMILIES:
        return "offense"
    if pos in _IDP_FAMILIES:
        return "idp"
    return None


def normalize_value(raw: str) -> Decimal | None:
    """Rendered ``3D Value +`` text -> exact Decimal, or ``None``.

    Exact decimal, never float: the multipass equivalence gate compares
    the same asset seen through two position filters and must accept
    ``"53"`` == ``"53.0"`` while rejecting ``53`` vs ``52.99``.  Float
    parsing would blur that boundary in both directions.
    """
    text = re.sub(r"[,\s]", "", str(raw or ""))
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def _cell_text(row: Any, attr: str) -> str:
    el = row.find(attrs={"data-attribute": attr})
    if el is None:
        return ""
    inner = el.find(class_="column-title")
    return re.sub(r"\s+", " ", (inner or el).get_text()).strip()


def parse_rows(html: str) -> list[dict[str, Any]]:
    """Every ``<tbody data-player-row>`` in ``html`` as a record.

    ``vendorId`` is DS's own ``data-key`` — a stable per-player
    identifier that survives filtering and re-render.  It is the
    reconciliation key for multipass traversal; player NAME never is,
    because a same-name collision under last-write-wins silently
    corrupts a row's position and therefore its family.
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415 — keep import cost off module load

    soup = BeautifulSoup(html or "", "html.parser")
    out: list[dict[str, Any]] = []
    for tb in soup.find_all("tbody", attrs={"data-player-row": True}):
        name = str(tb.get("data-player-name") or "").strip()
        if not name:
            continue

        team = ""
        for el in tb.find_all(attrs={"class": True}):
            classes = el.get("class") or []
            match = _TEAM_CLASS_RE.search(" ".join(classes))
            if match:
                team = match.group(1).upper()
                break

        rank_el = tb.find(class_="rank-index")
        rank_raw = re.sub(r"\s+", " ", rank_el.get_text()).strip() if rank_el else ""
        try:
            ds_rank: int | None = int(rank_raw)
        except (TypeError, ValueError):
            ds_rank = None

        out.append(
            {
                "vendorId": str(tb.get("data-key") or "").strip() or None,
                "name": name,
                "team": team,
                "position": str(tb.get("data-fantasy-position") or "").upper().strip(),
                "dsRank": ds_rank,
                "adp": _cell_text(tb, "adp"),
                "bye": _cell_text(tb, "player.team.bye") or _cell_text(tb, "bye"),
                "age": _cell_text(tb, "player.age") or _cell_text(tb, "age"),
                "oneYr": _cell_text(tb, "fantasy_points"),
                "threeYr": _cell_text(tb, "threeYrPts"),
                "fiveYr": _cell_text(tb, "fiveYrPts"),
                "tenYr": _cell_text(tb, "tenYrPts"),
                "comment": _cell_text(tb, "comment"),
                "dsValue": _cell_text(tb, "dsValue"),
            }
        )
    return out


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
            if isinstance(c, dict) and "name" in c and c.get("name") in _AUTH_COOKIE_NAMES
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
        raise RuntimeError(f"DS login failed — no _identity cookie issued.  Page errors: {errors}")
    fresh_cookies = await context.cookies("https://www.draftsharks.com")
    _save_cookies(fresh_cookies)
    count = sum(1 for c in fresh_cookies if c.get("name") in _AUTH_COOKIE_NAMES)
    print(
        f"[DS] logged in; persisted {count} cookie(s) to {SESSION_PATH.name}",
        flush=True,
    )


# League-activation JS for the post-2026-06-23 DS UI.  The legacy
# ``<select id="use-my-league-dropdown">`` was replaced by an Alpine.js
# button dropdown (``.scoring-nav__league-dropdown``) whose menu items
# set ``selectedUserLeagueId`` and call ``handleUserLeagueChange()``.
# For a logged-in account the per-league items are rendered alongside
# the static "Use My League" / "Sync My League" entries, so we click
# the toggle, then click the item whose Alpine ``@click`` handler
# carries our league id — falling back to an EXACT normalized
# league-NAME match (never substring; see round-16 note below).
# Returns a status string; "no-item:..." reports COUNTS only (Codex
# review round 15): the menu inventory contains the account's OTHER
# synced leagues' names and ids, and the raise below streams into the
# public workflow log — so a markup change surfaces as a shape
# diagnostic, never as a verbatim league inventory.
_ACTIVATE_LEAGUE_JS = r"""([leagueId, leagueName]) => {
    const root = document.querySelector('.scoring-nav__league-dropdown');
    if (!root) return 'no-dropdown';
    const toggle = root.querySelector('.ds-dropdown__toggle');
    if (toggle) toggle.click();
    const items = Array.from(root.querySelectorAll('.ds-dropdown__menu-item'));
    const handler = (el) =>
        (el.getAttribute('@click') || el.getAttribute('x-on:click') || '');
    const norm = (s) => (s || '').trim().replace(/\s+/g, ' ');
    // Primary: exact league-ID match in the Alpine @click handler.
    // Fallback (markup drift only): EXACT normalized-label equality —
    // substring matching could click a different synced league whose
    // label merely contains ours, e.g. a cloned league with a suffix
    // (Codex review round 16).  The return value records which signal
    // identified the item so the caller can calibrate confirmation.
    let target = items.find((el) => handler(el).includes(`'${leagueId}'`));
    let mode = 'id';
    if (!target) {
        target = items.find((el) => norm(el.textContent) === norm(leagueName));
        mode = 'name';
    }
    if (!target) {
        const leagueLike = items.filter((el) =>
            handler(el).includes('selectedUserLeagueId')).length;
        return 'no-item:' + items.length + ' menu items ('
            + leagueLike + ' league-like), none matching target league';
    }
    target.click();
    return 'clicked-' + mode;
}"""

# Confirmation probe: the dropdown's toggle label renders
# ``x-text="selectedUserLeagueText"`` — Alpine rewrites it to the
# selected league's name once the selection has actually registered.
# A raw DOM ``.click()`` dispatched before Alpine bound its handlers
# is a no-op, so click dispatch alone must never count as success
# (Codex review on PR #530: an unconfirmed activation would let the
# scrape continue on PUBLIC scoring and overwrite the league-synced
# last-good CSVs).  Returns the current label text.
_LEAGUE_LABEL_JS = r"""() => {
    const el = document.querySelector(
        '.scoring-nav__league-dropdown .ds-dropdown__toggle-label');
    return el ? el.textContent.trim() : '';
}"""


async def _activate_league(page) -> None:
    """Select the synced league so the WASM worker applies league
    scoring.  Tries the legacy ``<select>`` first (cheap, and keeps
    the fetcher working if DS ever rolls the redesign back), then the
    Alpine dropdown that replaced it in the 2026-06-23 UI refresh.

    Success requires CONFIRMATION — the dropdown toggle label must
    switch to the league name — not merely a dispatched click.  An
    unconfirmed activation raises, which the workflow treats as
    non-fatal (keep last-good CSVs); that is strictly better than
    silently scraping public-scoring values into the league CSVs."""
    legacy = page.locator("#use-my-league-dropdown")
    if await legacy.count() > 0:
        try:
            await page.select_option("#use-my-league-dropdown", value=LEAGUE_ID, timeout=5_000)
            return
        except Exception as exc:
            raise RuntimeError(f"Failed to select league {LEAGUE_ID} (legacy select): {exc}")

    # Alpine binds its @click handlers after init; with only
    # ``domcontentloaded`` awaited the first attempts can race it, in
    # which case ``target.click()`` dispatches into a void.  Retry the
    # click-then-confirm cycle until the toggle label proves the
    # selection registered.
    status = "no-dropdown"
    label = ""
    norm_name = " ".join(LEAGUE_NAME.split())
    for _ in range(8):
        status = await page.evaluate(_ACTIVATE_LEAGUE_JS, [LEAGUE_ID, LEAGUE_NAME])
        if status.startswith("clicked"):
            # Poll for the label flip (~3s) before trusting the click.
            # Identity must rest on at least one EXACT signal (Codex
            # review round 16): when the item was found by exact
            # league-ID handler match, substring label containment is
            # enough to prove the click registered; when it was found
            # by the name fallback, the label must match the league
            # name EXACTLY (normalized) — substring confirmation could
            # bless a different synced league whose label contains
            # ours.
            for _ in range(6):
                await page.wait_for_timeout(500)
                label = await page.evaluate(_LEAGUE_LABEL_JS)
                norm_label = " ".join(label.split())
                confirmed = (
                    norm_label == norm_name if status == "clicked-name" else norm_name in norm_label
                )
                if confirmed:
                    print(
                        f"[DS] league activated via Alpine dropdown "
                        f"(label confirmed, match={status[8:]})",
                        flush=True,
                    )
                    return
        else:
            await page.wait_for_timeout(1_000)
    # Diagnostic dead-ends.  ``no-dropdown`` = the league widget moved
    # again; ``no-item:...`` = the dropdown exists but our league isn't
    # in it (counts only — see _ACTIVATE_LEAGUE_JS comment); ``clicked``
    # with an unconfirmed label = the click dispatched but the selection
    # never registered.  The toggle label is described, not quoted: on
    # failure it can carry ANOTHER synced league's name, which must not
    # stream into the workflow log (Codex review round 15).
    label_desc = "empty" if not label else f"{len(label)} chars, target league name absent"
    raise RuntimeError(
        f"Failed to select league {LEAGUE_ID}: legacy #use-my-league-dropdown "
        f"absent; Alpine dropdown activation returned {status!r} with toggle "
        f"label {label_desc}"
    )


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

    # Snapshot the PUBLIC-scoring dsValues of the first few rendered
    # rows BEFORE activating the league, then require at least one of
    # them to change afterward.  The WASM worker reshuffles values
    # board-wide when league scoring applies, so any delta proves the
    # transition happened — without pinning the gate to one player's
    # mutable market value (the previous "Mahomes >= 78" pin broke if
    # DS repriced, renamed, or dropped that one player; Codex review
    # on PR #530).
    async def _probe_values() -> dict:
        return await page.evaluate(r"""() => {
            const rows = Array.from(document.querySelectorAll('tbody[data-player-row]')).slice(0, 8);
            const out = {};
            for (const tb of rows) {
                const name = tb.getAttribute('data-player-name') || '';
                const el = tb.querySelector('[data-attribute="dsValue"]');
                const v = el ? parseFloat(el.textContent.trim()) : NaN;
                if (name && Number.isFinite(v)) out[name] = v;
            }
            return out;
        }""")

    # Poll for a NON-EMPTY baseline before doing anything else (Codex
    # review round 12): the first probe fires right after
    # ``domcontentloaded``, and if the table hasn't hydrated yet a
    # one-shot ``{}`` baseline would make the transition gate below
    # structurally unpassable (``if baseline and ...`` can never see a
    # delta from nothing) — turning every slow page load into a
    # permanent false-raise.  Rows render within a few seconds; if
    # none appear in 20s the page structure changed → raise loudly.
    baseline: dict = {}
    for _ in range(10):
        baseline = await _probe_values()
        if baseline:
            break
        await page.wait_for_timeout(2_000)
    if not baseline:
        raise RuntimeError(
            "No ranked rows rendered within 20s of page load — cannot "
            "establish a public-scoring baseline (page structure may have "
            "changed).  Refusing to extract."
        )

    # Already-active detection (Codex review on PR #530): a cached
    # authenticated session can load the page with the league ALREADY
    # selected (DS remembers per-account state server-side).  Selecting
    # the same league again changes nothing, so the transition gate
    # below would false-raise every run and preserve increasingly
    # stale CSVs.  When either UI generation already shows our league
    # selected, we first DESELECT back to the public board (see below)
    # so the normal activation path gets a real transition to observe.
    already_active = await page.evaluate(
        r"""([leagueId, leagueName]) => {
        const legacy = document.querySelector('#use-my-league-dropdown');
        if (legacy && String(legacy.value) === String(leagueId)) return true;
        const label = document.querySelector(
            '.scoring-nav__league-dropdown .ds-dropdown__toggle-label');
        return !!(label && label.textContent.includes(leagueName));
    }""",
        [LEAGUE_ID, LEAGUE_NAME],
    )
    if already_active:
        # Codex review (rounds 11+13): with the league pre-selected we
        # have NO observable proof the visible values are league-scored
        # — a stalled worker leaves public values that look perfectly
        # "settled".  Stability cannot prove scoring identity.  So we
        # CREATE the provable transition instead: deselect back to the
        # public board (observing that change), then run the normal
        # activation path with its full baseline→delta gate.  Every
        # extraction now rests on an observed public→league value
        # transition, whatever state the page loaded in.
        print(
            f"[DS] league {LEAGUE_ID} pre-selected — deselecting to establish "
            f"a provable public baseline",
            flush=True,
        )
        deselected = await page.evaluate(r"""() => {
            const legacy = document.querySelector('#use-my-league-dropdown');
            if (legacy) {
                const blank = Array.from(legacy.options || []).find(o => !o.value);
                if (!blank) return 'no-blank-option';
                legacy.value = '';
                legacy.dispatchEvent(new Event('change', { bubbles: true }));
                return 'clicked';
            }
            const root = document.querySelector('.scoring-nav__league-dropdown');
            if (!root) return 'no-dropdown';
            const toggle = root.querySelector('.ds-dropdown__toggle');
            if (toggle) toggle.click();
            const items = Array.from(root.querySelectorAll('.ds-dropdown__menu-item'));
            const handler = (el) =>
                (el.getAttribute('@click') || el.getAttribute('x-on:click') || '');
            const blank = items.find((el) => handler(el).includes("selectedUserLeagueId = ''"));
            if (!blank) return 'no-blank-item';
            blank.click();
            return 'clicked';
        }""")
        if deselected != "clicked":
            raise RuntimeError(
                f"League {LEAGUE_ID} pre-selected but deselect control not "
                f"found ({deselected!r}) — cannot establish a provable "
                f"baseline; refusing to extract over last-good CSVs."
            )
        # Wait for the deselect to take: the worker must show LIFE
        # (some observed value change — the deselect landing, a stale
        # in-flight league update landing, or both) and the output
        # must then SETTLE (Codex round 14): right after page load the
        # initial LEAGUE update may still be in flight, so the FIRST
        # movement observed here can be that stale league update — a
        # first-movement-wins gate would store league values as the
        # supposed public baseline.  Only a settled post-deselect
        # snapshot (3 identical consecutive probes, ~4s stable) may
        # serve as the activation baseline: settling proves the
        # worker's update queue drained past the deselect we clicked.
        pre_deselect = baseline
        moved = False
        settled: dict = {}
        prev: dict = {}
        streak = 0
        for _ in range(30):
            await page.wait_for_timeout(2_000)
            cur = await _probe_values()
            if not cur:
                prev = {}
                streak = 0
                continue
            if not moved:
                if any(
                    name in cur and abs(cur[name] - v) > 0.05 for name, v in pre_deselect.items()
                ):
                    moved = True
                elif prev and cur != prev:
                    moved = True
            streak = streak + 1 if (prev and cur == prev) else 0
            prev = cur
            if moved and streak >= 2:
                settled = cur
                break
        if not settled:
            raise RuntimeError(
                f"Deselecting league {LEAGUE_ID} never produced settled "
                f"post-deselect values within 60s (movement observed: {moved}) "
                f"— worker unresponsive or still churning; refusing to extract."
            )
        baseline = settled
        # Fall through to the normal activation path below with the
        # settled public baseline.

    print(f"[DS] activating league {LEAGUE_ID} …", flush=True)
    await _activate_league(page)

    # HARD GATE (Codex reviews on PR #530, rounds 11+14): league
    # scoring must be OBSERVED to apply — the probed values must move
    # off the public baseline AND the moved output must SETTLE (3
    # identical consecutive probes) before extraction.  First-movement
    # is not enough: a stale queued update (e.g. the deselect from the
    # pre-selected branch above landing late) could transiently
    # satisfy an any-delta gate while the table still carries PUBLIC
    # scoring.  Requiring the SETTLED snapshot to differ from the
    # settled public baseline means a late stale update parks the loop
    # (values == baseline → keep waiting for the real league update)
    # instead of passing the gate.  If nothing qualifying settles, the
    # worker stalled → raise (the workflow treats a fetch failure as
    # non-fatal keep-last-good; the staleness watchdog surfaces
    # repeats).  Known limitation (unchanged): a league whose scoring
    # produces IDENTICAL values for every probed player would
    # false-raise — but then public equals league output anyway, so
    # keeping last-good loses nothing.
    applied = False
    current: dict = {}
    prev = {}
    streak = 0
    for _ in range(30):
        await page.wait_for_timeout(2_000)
        current = await _probe_values()
        if not current:
            prev = {}
            streak = 0
            continue
        streak = streak + 1 if (prev and current == prev) else 0
        prev = current
        differs = baseline and any(
            name in current and abs(current[name] - base_v) > 0.05
            for name, base_v in baseline.items()
        )
        if differs and streak >= 2:
            applied = True
            break
    if not applied:
        raise RuntimeError(
            f"League scoring never applied — probed dsValues never settled "
            f"off the public baseline within 60s despite confirmed league "
            f"selection.  Refusing to extract: the table would carry PUBLIC "
            f"scoring and overwrite the league-synced last-good CSVs.  "
            f"baseline={baseline!r} current={current!r}"
        )

    return await _harvest_full_universe(page)


# Every ``fantasyPosition`` option the dynasty page itself offers, in
# DOM order.  ``''`` is "All Positions".  These are the page's OWN
# controls on the SAME league-scored session — not the separately
# rescaled ``/dynasty-rankings/idp`` board, which stays forbidden.
#
# The aggregate ``IDP`` pass is included deliberately.  Without it the
# only overlaps are offense-side (a QB appears in both the unfiltered
# board and the QB pass), which proves filtering does not rescale
# OFFENSE and leaves the IDP families resting on an inference.  With it,
# every defender appears in both ``IDP`` and its own ``DL``/``LB``/``DB``
# pass, so filter-invariance is demonstrated inside both families
# instead of argued across them.
_POSITION_PASSES: tuple[str, ...] = ("", "QB", "RB", "WR", "TE", "IDP", "DL", "LB", "DB")

# Below this many overlapping assets we refuse to declare the passes
# share one currency.  One coincidental match is not a proof.
_MIN_OVERLAP_FOR_EQUIVALENCE: int = 25
# ...and it must not all sit in one family (see overlapByFamily).
_MIN_OVERLAP_PER_FAMILY: int = 10


async def _harvest_full_universe(page) -> list[dict]:
    """Collect the whole board, proving one valuation currency.

    The default view no longer contains the IDP universe: DraftSharks
    now loads the table over htmx (``/dynasty-rankings/load-table``,
    parameterised by ``#sharedParams``) and the ``fantasyPosition``
    filter decides which families are RENDERED AT ALL, rather than
    hiding them with ``display:none`` as the 2026 parser assumed.

    So we take the unfiltered pass first and stop there if it already
    carries both families — that is the cheap, no-merge path.  Only if
    IDP is genuinely absent do we traverse the page's own position
    filters, and then the union is gated on an exact-decimal
    equivalence proof over the assets that appear in more than one
    pass.  No overlap means no proof, and no proof means no union.
    """
    first = await _extract_rows(page)
    if any(family_of(r.get("position", "")) == "idp" for r in first):
        print("[DS] single pass carries both families — no merge needed", flush=True)
        return first

    print(
        "[DS] no IDP rows in the unfiltered board — traversing the page's own "
        "fantasyPosition filters on this same league-scored session",
        flush=True,
    )
    passes: dict[str, list[dict]] = {"all": first}
    for value in _POSITION_PASSES[1:]:
        try:
            await _select_position_filter(page, value)
        except RuntimeError as exc:
            print(f"[DS] position pass {value!r} unavailable: {exc}", flush=True)
            continue
        rows = await _extract_rows(page)
        passes[value] = rows
        print(f"[DS] pass {value or 'ALL'}: {len(rows)} rows", flush=True)

    merged, report = reconcile_passes(passes)
    print(f"[DS] reconciliation: {json.dumps(report, default=str)}", flush=True)

    if report["identityCollisions"]:
        raise RuntimeError(
            f"vendorId collision across passes ({len(report['identityCollisions'])} ids) — "
            "the same DraftSharks key arrived under two different player names.  "
            "Refusing to merge: last-write-wins here would silently swap a row's "
            "position and therefore its family."
        )
    if report["valueConflictCount"]:
        raise RuntimeError(
            f"3D Value + disagrees across position filters for "
            f"{report['valueConflictCount']} asset(s), e.g. {report['valueConflicts'][:3]}.  "
            "The filters are therefore NOT views on one valuation currency, and "
            "merging them would splice two scales.  Refusing."
        )
    if report["overlappingAssets"] < _MIN_OVERLAP_FOR_EQUIVALENCE:
        raise RuntimeError(
            f"only {report['overlappingAssets']} asset(s) appear in more than one pass "
            f"(need >= {_MIN_OVERLAP_FOR_EQUIVALENCE}) — there is not enough overlap to "
            "PROVE the passes share one currency.  Absence of contradiction is not proof; "
            "refusing to merge."
        )
    thin = [
        fam
        for fam in ("offense", "idp")
        if report["overlapByFamily"].get(fam, 0) < _MIN_OVERLAP_PER_FAMILY
    ]
    if thin:
        raise RuntimeError(
            f"insufficient overlap inside {thin} (need >= {_MIN_OVERLAP_PER_FAMILY} each; "
            f"got {report['overlapByFamily']}) — a healthy TOTAL that is entirely one family "
            "would leave the other family's currency unproven.  Refusing to merge."
        )
    print(
        f"[DS] currency equivalence proven across {report['overlappingAssets']} "
        f"overlapping assets {report['overlapByFamily']}, 0 conflicts",
        flush=True,
    )
    return merged


async def collect_dom_diagnostic(page) -> dict:
    """Counts and selector shapes for the CURRENT authenticated DOM.

    Deliberately emits NO player names, NO league identifiers, NO
    account details and NO raw HTML — only the structural facts needed
    to decide how the parser must change.  Same posture as
    ``_activate_league``, which already refuses to log the league label.
    """
    return await page.evaluate(
        """() => {
            const n = (sel) => document.querySelectorAll(sel).length;
            const rows = Array.from(document.querySelectorAll('tbody[data-player-row]'));
            const posCounts = {};
            let hidden = 0;
            const attrNames = new Set();
            for (const tb of rows) {
                const p = (tb.getAttribute('data-fantasy-position') || '').toUpperCase() || '<empty>';
                posCounts[p] = (posCounts[p] || 0) + 1;
                const st = window.getComputedStyle(tb);
                if (st && st.display === 'none') hidden += 1;
                for (const a of tb.attributes) attrNames.add(a.name);
            }
            const first = rows[0] || null;
            const cellAttrs = first
                ? Array.from(first.querySelectorAll('[data-attribute]'))
                      .map((el) => el.getAttribute('data-attribute'))
                : [];
            return {
                rowContainers: n('tbody[data-player-row]'),
                playerNameAttrs: n('[data-player-name]'),
                dsValueCells: n('[data-attribute="dsValue"]'),
                columnTitleNodes: n('.column-title'),
                rankIndexNodes: n('.rank-index'),
                hiddenRowContainers: hidden,
                positionCounts: posCounts,
                rowAttributeNames: Array.from(attrNames).sort(),
                cellDataAttributes: cellAttrs,
                stableIdCandidates: {
                    dataKey: rows.filter((t) => t.getAttribute('data-key')).length,
                    dataPlayerId: rows.filter((t) => t.getAttribute('data-player-id')).length,
                    dataTeamId: rows.filter((t) => t.getAttribute('data-team-id')).length,
                },
                positionFilterOptions: Array.from(
                    document.querySelectorAll('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button')
                ).map((el) => {
                    const h = el.getAttribute('@click') || el.getAttribute('x-on:click') || '';
                    const m = h.match(/handleFantasyPositionChange\\((?:"|')([^"']*)(?:"|')\\)/);
                    return m ? m[1] : null;
                }).filter((v) => v !== null),
                sharedParamNames: Array.from(
                    document.querySelectorAll('#sharedParams input[name]')
                ).map((el) => el.getAttribute('name')),
                htmxTableEndpointPresent: !!document.querySelector('[hx-get*="load-table"]'),
            };
        }"""
    )


# Identifying strings that must never survive into a committed fixture.
# The league name is the one the activation chain already refuses to
# log; the rest are the account-scoped values this scraper handles.
_FIXTURE_FORBIDDEN: tuple[str, ...] = (LEAGUE_NAME, LEAGUE_ID)


def sanitize_html_fixture(html: str) -> str:
    """A committable fixture: real STRUCTURE, synthetic IDENTITIES.

    Keeps exactly what the parser reads — the ``tbody[data-player-row]``
    hierarchy, the ``data-*`` attributes, the ``[data-attribute]`` cells
    and their ``.column-title`` descent, the team class form and the
    ``.rank-index`` node — and replaces every real identity with a
    deterministic synthetic one, so the fixture reproduces the current
    parser behaviour without carrying production data.

    Deterministic (index-derived, not random) so re-running produces a
    byte-identical fixture and a diff means the SHAPE changed.
    """
    from bs4 import BeautifulSoup  # noqa: PLC0415

    soup = BeautifulSoup(html or "", "html.parser")
    out_rows = []
    for i, tb in enumerate(soup.find_all("tbody", attrs={"data-player-row": True}), 1):
        pos = str(tb.get("data-fantasy-position") or "").upper().strip()
        value = _cell_text(tb, "dsValue")
        rank_el = tb.find(class_="rank-index")
        rank = re.sub(r"\s+", " ", rank_el.get_text()).strip() if rank_el else str(i)
        cells = []
        for attr in ("adp", "bye", "age", "fantasy_points", "threeYrPts", "fiveYrPts", "tenYrPts"):
            cells.append(f'<td data-attribute="{attr}"><span class="column-title">{i}</span></td>')
        cells.append(
            f'<td data-attribute="comment"><span class="column-title">note {i}</span></td>'
        )
        cells.append(f'<td data-attribute="dsValue"><span class="column-title">{value}</span></td>')
        out_rows.append(
            f'<tbody data-player-row data-key="{900000 + i}" '
            f'data-fantasy-position="{pos}" data-player-name="Synthetic Player {i:04d}" '
            f'data-team-id="{(i % 32) + 1}" data-is-rookie="false">'
            f"<tr>"
            f'<td><div class="column-title rank-index"><span>{rank}</span></div></td>'
            f'<td><span class="team-abbr-fa"></span></td>' + "".join(cells) + "</tr></tbody>"
        )
    doc = (
        "<!-- SANITIZED FIXTURE — synthetic identities, real structure.\n"
        "     Generated by scripts/fetch_draftsharks.py --sanitized-fixture.\n"
        "     Contains no real player, league or account data. -->\n"
        '<table id="rankingsTableContainer">\n' + "\n".join(out_rows) + "\n</table>\n"
    )
    for needle in _FIXTURE_FORBIDDEN:
        if needle and needle in doc:  # pragma: no cover — defence in depth
            raise RuntimeError(f"sanitizer leaked an identifying string: {needle!r}")
    return doc


async def _extract_rows(page) -> list[dict]:
    """Scroll the full table into the DOM, settle, and extract every
    row.  Shared by the normal activation path and the already-active
    short-circuit in ``_scrape_one``."""
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

    rows = parse_rows(await page.content())
    print(f"[DS] extracted rows: {len(rows)}", flush=True)
    return rows


async def _select_position_filter(page, value: str) -> None:
    """Drive the dynasty page's own ``fantasyPosition`` filter.

    The board is loaded by htmx (``hx-get="/dynasty-rankings/load-table"``,
    ``hx-include="#sharedParams"``); ``fantasyPosition`` is one of the
    params in that block.  We click the page's own control rather than
    calling the endpoint directly so the league-scored session, the
    settled worker values and every gate above stay exactly as proven.
    """
    label = value or "All Positions"
    clicked = await page.evaluate(
        """(wanted) => {
            const norm = (s) => (s || '').replace(/\\s+/g, ' ').trim();
            const items = Array.from(
                document.querySelectorAll('[role="listbox"] [role="option"], [role="listbox"] li, [role="listbox"] button')
            );
            for (const el of items) {
                const handler = el.getAttribute('@click') || el.getAttribute('x-on:click') || '';
                if (handler.includes(`handleFantasyPositionChange("${wanted}")`)
                    || handler.includes(`handleFantasyPositionChange('${wanted}')`)) {
                    el.click();
                    return true;
                }
            }
            return false;
        }""",
        value,
    )
    if not clicked:
        raise RuntimeError(f"position filter option not found: {label}")
    # htmx swaps #rankingsTableContainer; give the swap and the Alpine
    # re-render room before the scroll loop counts rows.
    await page.wait_for_timeout(1_500)


def reconcile_passes(passes: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    """Union multipass rows on DS's own ``vendorId``, proving one currency.

    Three rules, each of which exists because its absence is a known
    corruption mode in this repository:

    * **Never key on player name.**  Two different players sharing a
      normalized name under last-write-wins silently inherits the other
      one's position, and therefore the other one's FAMILY — the same
      class of defect the C-Series lineup work found.  ``vendorId`` is
      DS's ``data-key`` and survives filtering and re-render.
    * **A collision fails closed.**  If one ``vendorId`` arrives with two
      different names, we refuse rather than pick one.
    * **Equivalence is exact.**  An asset seen in two passes must carry
      the SAME value as an exact ``Decimal``, so ``"53"`` and ``"53.0"``
      agree while ``53`` and ``52.99`` do not.  That is what proves the
      filter changes only which rows RENDER and not the currency they
      are priced in.

    Returns ``(rows, report)``.  ``report`` carries the overlap evidence
    the caller needs to decide whether equivalence was actually PROVEN
    rather than merely un-contradicted.
    """
    merged: dict[str, dict] = {}
    seen_in: dict[str, list[str]] = {}
    identity_collisions: list[str] = []
    value_conflicts: list[dict] = []
    missing_id = 0

    for pass_name, rows in passes.items():
        for row in rows:
            vid = row.get("vendorId")
            if not vid:
                missing_id += 1
                continue
            prior = merged.get(vid)
            if prior is None:
                merged[vid] = dict(row)
                seen_in[vid] = [pass_name]
                continue
            seen_in[vid].append(pass_name)
            if str(prior.get("name") or "") != str(row.get("name") or ""):
                identity_collisions.append(vid)
                continue
            a = normalize_value(prior.get("dsValue"))
            b = normalize_value(row.get("dsValue"))
            if a is None or b is None or a != b:
                value_conflicts.append(
                    {
                        "vendorId": vid,
                        "passes": seen_in[vid][-2:],
                        "values": [prior.get("dsValue"), row.get("dsValue")],
                    }
                )

    overlaps = {vid: names for vid, names in seen_in.items() if len(names) > 1}
    # Report overlap PER FAMILY.  A healthy total that is entirely
    # offense would leave the IDP families' currency unproven while the
    # aggregate number looked reassuring.
    overlap_by_family: dict[str, int] = {}
    for vid in overlaps:
        fam = family_of(merged[vid].get("position", "")) or "unclassified"
        overlap_by_family[fam] = overlap_by_family.get(fam, 0) + 1
    report = {
        "passes": {name: len(rows) for name, rows in passes.items()},
        "uniqueAssets": len(merged),
        "rowsWithoutVendorId": missing_id,
        "overlappingAssets": len(overlaps),
        "overlapByFamily": overlap_by_family,
        "identityCollisions": sorted(set(identity_collisions)),
        "valueConflicts": value_conflicts[:20],
        "valueConflictCount": len(value_conflicts),
    }
    return list(merged.values()), report


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


async def _scrape(
    *,
    headless: bool,
    dom_diagnostic: Path | None = None,
    sanitized_fixture: Path | None = None,
) -> list[dict]:
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
            rows = await _scrape_with_autologin(context, page)
            # Both artefacts are captured from the SETTLED, league-scored
            # board — the same DOM the rows came from — so the diagnostic
            # describes what we actually parsed rather than a fresh load.
            if dom_diagnostic is not None:
                diag = await collect_dom_diagnostic(page)
                dom_diagnostic.parent.mkdir(parents=True, exist_ok=True)
                dom_diagnostic.write_text(json.dumps(diag, indent=2) + "\n", encoding="utf-8")
                print(f"[DS] wrote DOM diagnostic -> {dom_diagnostic}", flush=True)
            if sanitized_fixture is not None:
                fixture = sanitize_html_fixture(await page.content())
                sanitized_fixture.parent.mkdir(parents=True, exist_ok=True)
                sanitized_fixture.write_text(fixture, encoding="utf-8")
                print(f"[DS] wrote sanitized fixture -> {sanitized_fixture}", flush=True)
            return rows
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
    want = "offense" if include_families is _OFFENSE_FAMILIES else "idp"
    selected = [r for r in rows if family_of(r.get("position", "")) == want]

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
            w.writerow(
                [
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
                ]
            )
    return len(selected)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't write the CSV.",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Launch the browser visibly (useful for debugging).",
    )
    parser.add_argument(
        "--dest-sf",
        type=Path,
        default=OUT_SF,
        help=f"Offense CSV path (default: {OUT_SF.relative_to(REPO)}).",
    )
    parser.add_argument(
        "--dest-idp",
        type=Path,
        default=OUT_IDP,
        help=f"IDP CSV path (default: {OUT_IDP.relative_to(REPO)}).",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        help=(
            "Parse a saved HTML file instead of driving a browser.  Exercises "
            "the parser and every guard deterministically, with no network."
        ),
    )
    parser.add_argument(
        "--dom-diagnostic",
        type=Path,
        help=(
            "After the league-scored board settles, write a COUNTS-AND-SHAPES "
            "JSON describing the current DOM.  No player names, no league "
            "identifiers, no raw HTML."
        ),
    )
    parser.add_argument(
        "--sanitized-fixture",
        type=Path,
        help=(
            "Write a synthetic HTML fixture that preserves parser-relevant "
            "structure with deterministic fake identities substituted for "
            "every real one.  Safe to commit."
        ),
    )
    args = parser.parse_args(argv)

    _load_env_dotfile(ENV_PATH)

    if args.from_file:
        rows = parse_rows(args.from_file.read_text(encoding="utf-8", errors="replace"))
        print(f"[DS] parsed {len(rows)} rows from {args.from_file}", flush=True)
    else:
        rows = asyncio.run(
            _scrape(
                headless=not args.headful,
                dom_diagnostic=args.dom_diagnostic,
                sanitized_fixture=args.sanitized_fixture,
            )
        )

    if not rows:
        print("[DS] ERROR: no rows extracted", file=sys.stderr)
        return 1

    # Family split sanity-check.  We deliberately scrape only the
    # offense-combined page because its DOM carries the full
    # cross-universe universe (QB + IDP on the same dsValue scale),
    # so a missing IDP count here means the worker didn't settle
    # or the position attribute normalization changed.
    families = [family_of(r.get("position", "")) for r in rows]
    off_count = sum(1 for f in families if f == "offense")
    idp_count = sum(1 for f in families if f == "idp")
    unclassified = [r.get("position", "") for r, f in zip(rows, families, strict=True) if f is None]
    print(f"[DS] family split: offense={off_count} idp={idp_count}")
    if unclassified:
        # Previously these vanished from both CSVs with no counter and
        # no log line, so a position-label change looked identical to a
        # smaller board.  Report them; K/DEF are expected here.
        seen = sorted({p or "<empty>" for p in unclassified})
        print(f"[DS] unclassified rows: {len(unclassified)} across labels {seen}")
    per_position: dict[str, int] = {}
    for row in rows:
        key = classify_position(row.get("position", "")) or "<empty>"
        per_position[key] = per_position.get(key, 0) + 1
    print(f"[DS] position counts: {dict(sorted(per_position.items()))}")
    if idp_count == 0:
        print(
            "[DS] ERROR: no IDP rows — league-synced scrape probably "
            "didn't complete (worker hung or cookies missing league context).",
            file=sys.stderr,
        )
        return 1

    # Value-sanity guard: even when ``idp_count > 0`` the DS WASM
    # worker can finish a partial pass that emits IDP rows with
    # ``dsValue`` rendered as 0 across the whole pool.  We saw this on
    # the 2026-04-28T18:13Z scrape — Carson Schwesinger (IDP rank 1)
    # arrived at value=0 alongside every other IDP row, which then
    # fed straight into the live blend and tripped
    # ``test_ds_csvs_have_negative_rows`` on the next PR validation.
    # Refuse to overwrite the existing CSVs in that case so the prior
    # good scrape stays in place until the page recovers.  Threshold
    # is "max IDP value > 0": one positive IDP row is enough to prove
    # the worker finished its pass.
    idp_max_value = max(
        (_value_of(r) for r in rows if family_of(r.get("position", "")) == "idp"),
        default=0.0,
    )
    if idp_max_value <= 0:
        print(
            f"[DS] ERROR: every IDP row has dsValue<=0 (max={idp_max_value}) — "
            "WASM worker did not produce IDP values.  Refusing to "
            "overwrite the prior good CSV; re-run later or check the "
            "DraftSharks page in --headful mode.",
            file=sys.stderr,
        )
        return 1

    # Contract-aligned floor BEFORE writing: a partial scrape (WASM
    # worker hung, lazy-load shortfall) that still emits some positive
    # IDP values must not overwrite last-good with a structurally-
    # short board that then hard-fails the contract floor on a clean
    # checkout.  Fail loud, preserve last-good.
    if off_count < _DS_SF_ROW_FLOOR or idp_count < _DS_IDP_ROW_FLOOR:
        print(
            f"[DS] ERROR: degraded scrape — offense={off_count} "
            f"(floor {_DS_SF_ROW_FLOOR}) idp={idp_count} (floor "
            f"{_DS_IDP_ROW_FLOOR}).  Preserving last-good CSVs; not "
            f"overwriting.",
            file=sys.stderr,
        )
        return 2

    if args.dry_run:
        print("[DS] dry-run — skipping CSV write")
        print("Top 10 offense:")
        off_sorted = sorted(
            (r for r in rows if family_of(r.get("position", "")) == "offense"),
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
            (r for r in rows if family_of(r.get("position", "")) == "idp"),
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

    off_written = _write_csv(args.dest_sf, rows, include_families=_OFFENSE_FAMILIES)
    print(f"[DS] wrote {args.dest_sf} ({off_written} rows)")
    idp_written = _write_csv(args.dest_idp, rows, include_families=_IDP_FAMILIES)
    print(f"[DS] wrote {args.dest_idp} ({idp_written} rows)")
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
