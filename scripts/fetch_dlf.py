#!/usr/bin/env python3
"""Fetch DynastyLeagueFootball (DLF) rankings for the four boards
we consume: ``dlfSf``, ``dlfIdp``, ``dlfRookieSf``, ``dlfRookieIdp`` —
plus ``dlfValuesSfTep``, DLF's native offensive Trade Analyzer Values
(``name,pos,team,value``, values exactly as published; pick values go to
``dlfValuesSfTepPicks.csv`` for audit).

DLF sits behind Cloudflare and WordPress member authentication.
Vanilla ``requests`` and Playwright both get blocked at Cloudflare's
JS challenge — the automated-browser fingerprint trips CF's bot
detection.  We use ``curl_cffi`` with ``impersonate='chrome131'`` so
the TLS fingerprint matches a real Chrome browser, which sails past
the CF challenge with a normal HTTP round-trip.

Flow
----

1. ``GET  /wp-login.php``  — seed baseline cookies.
2. ``POST /wp-login.php``  — submit ``DLF_USERNAME`` + ``DLF_PASSWORD``
   from ``.env`` (``log`` + ``pwd`` WP form fields).  Success yields
   the ``wordpress_logged_in_*`` + ``wordpress_sec_*`` cookies.
3. ``GET  /{rankings-url}`` for each of the four boards — DLF now
   serves the full table instead of the 10-row preview.
4. Parse the ``<table class="dlf-rankings-*">`` HTML with BeautifulSoup;
   the header row exposes ``Rank``, ``Avg``, ``Pos``, ``Name``,
   ``Team``, ``Age``, per-expert columns, ``Value``, ``Follow``.
5. For each player row, prefer ``Avg`` (expert-consensus average rank,
   fractional) over ``Rank`` (nominal integer) — averages preserve
   near-tie fidelity and match the ``_RANK_ALIASES`` preference in
   ``src/api/data_contract.py``.
6. Write a ``name,rank`` CSV at the path registered in
   ``_SOURCE_CSV_PATHS`` for each board.

Output — four CSVs, each ``name,rank`` shape consumed by the
scraper-bridge adapter:

    CSVs/site_raw/dlfSf.csv
    CSVs/site_raw/dlfIdp.csv
    CSVs/site_raw/dlfRookieSf.csv
    CSVs/site_raw/dlfRookieIdp.csv

Run
---

    python3 scripts/fetch_dlf.py
    python3 scripts/fetch_dlf.py --dry-run     # scrape but don't write
    python3 scripts/fetch_dlf.py --only dlfRookieSf   # single board

Authentication
--------------

Reads ``DLF_USERNAME`` + ``DLF_PASSWORD`` from ``.env`` at the repo
root (gitignored).  GitHub Actions uses the same env var names via
repository secrets — see ``.github/workflows/scheduled-refresh.yml``.

A cached session (``dlf_session.json``, gitignored) caches the login
cookies between runs so we only re-authenticate when WordPress
invalidates the session (typically after ~14 days).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "dlf_session.json"
ENV_PATH = REPO / ".env"

LOGIN_URL = "https://dynastyleaguefootball.com/wp-login.php"
HOME_URL = "https://dynastyleaguefootball.com/"

# Four boards, each with its stable output path and scrape URL.  The
# URLs were confirmed by the user on 2026-04-21.  If DLF ever
# restructures the URL scheme, update these and the registry paths
# in ``src/api/data_contract.py::_SOURCE_CSV_PATHS`` in lockstep.
BOARDS: dict[str, dict[str, str]] = {
    "dlfSf": {
        "url": "https://dynastyleaguefootball.com/dynasty-superflex-rankings/",
        "out": "CSVs/site_raw/dlfSf.csv",
        "label": "Dynasty Superflex",
        # DLF publishes (or published) an atomic Value beside the expert
        # rank.  It is preserved when present, for literal DLF trade second
        # opinions — but it is NOT what the model votes on (rank is), so its
        # absence is reported and never blocks the rank board (2026-09-24:
        # requiring it froze DLF SF from 09-09 while its rank was healthy).
        "expect_native_value": True,
        # Aligned with the downstream contract floor
        # ``_DEFAULT_SOURCE_ROW_FLOORS["dlfSf"]`` (240) so a partial
        # scrape fails here and preserves last-good rather than
        # shipping a CSV that later hard-fails the contract test.
        "min_rows": 240,
    },
    "dlfIdp": {
        "url": "https://dynastyleaguefootball.com/rankings/dynasty-idp-rankings/",
        "out": "CSVs/site_raw/dlfIdp.csv",
        "label": "Dynasty IDP",
        # Aligned with ``_DEFAULT_SOURCE_ROW_FLOORS["dlfIdp"]`` (150).
        "min_rows": 150,
    },
    "dlfRookieSf": {
        "url": "https://dynastyleaguefootball.com/dynasty-rookie-superflex-rankings/",
        "out": "CSVs/site_raw/dlfRookieSf.csv",
        "label": "Rookie Superflex",
        "min_rows": 40,
    },
    "dlfRookieIdp": {
        "url": "https://dynastyleaguefootball.com/dynasty-rookie-idp-rankings/",
        "out": "CSVs/site_raw/dlfRookieIdp.csv",
        "label": "Rookie IDP",
        "min_rows": 20,  # smallest board; pre-NFL-draft class ~29 rows
    },
    # DLF's native offensive VALUE moved off the rankings boards to the Trade
    # Analyzer Values page (owner directive 2026-09-24).  Probed on the
    # production host 2026-09-24 (DLF Fetch Diagnostics run 36038278764):
    # title "Dynasty Trade Analyzer Values – 2QB/Superflex with TE Premium",
    # three ``Asset | Value`` tables of 138 + 138 + 136 rows, assets as
    # ``Name [POS, TEAM]`` or ``YYYY R.SS (overall)`` for picks, values
    # published to four decimals (984.7047 at the top).  Offense only — DLF
    # IDP stays rank-based.  Its OWN board, fetch state and health: a failure
    # here never touches the rank boards, and vice versa.
    "dlfValuesSfTep": {
        "url": "https://dynastyleaguefootball.com/trade-analyzer-values/?l=sf_te_prem",
        "out": "CSVs/site_raw/dlfValuesSfTep.csv",
        "picks_out": "CSVs/site_raw/dlfValuesSfTepPicks.csv",
        "label": "Trade Analyzer Values (SF, TE premium)",
        "kind": "values",
        # ~80% of the players on the probed board (412 assets incl. picks);
        # re-derived from the first real capture.
        "min_rows": 300,
    },
}


def _load_env_dotfile(path: Path) -> None:
    """Parse ``.env`` and populate ``os.environ`` with any keys not
    already set.  Inline replacement for ``python-dotenv``."""
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


def _load_session_cookies() -> list[dict]:
    """Return cookie dicts from the cached session file, or [] when
    missing / malformed."""
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
                "domain": c.get("domain") or ".dynastyleaguefootball.com",
                "path": c.get("path") or "/",
            }
        )
    return out


def _save_session_cookies(session) -> None:
    """Persist the session's cookie jar so the next run can skip the
    login POST.  WP session cookies are typically valid ~14 days."""
    cookies_out: list[dict] = []
    for c in session.cookies.jar:
        try:
            cookies_out.append(
                {
                    "name": c.name,
                    "value": c.value,
                    "domain": c.domain or ".dynastyleaguefootball.com",
                    "path": c.path or "/",
                }
            )
        except Exception:
            continue
    payload = {
        "_comment_": (
            "DLF session cookies auto-refreshed by scripts/fetch_dlf.py "
            "using DLF_USERNAME / DLF_PASSWORD.  Gitignored; safe to "
            "delete to force a fresh login."
        ),
        "cookies": cookies_out,
    }
    SESSION_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    try:
        SESSION_PATH.chmod(0o600)
    except Exception:
        pass


def _build_session():
    """Construct a ``curl_cffi.requests.Session`` configured to
    impersonate Chrome 131 (matches DLF's Cloudflare JS challenge
    fingerprint check)."""
    try:
        from curl_cffi import requests as cr
    except ImportError:
        raise SystemExit(
            "curl_cffi is required for DLF scraping (bypasses the "
            "Cloudflare JS challenge that blocks vanilla requests / "
            "Playwright).  Install with `pip install curl_cffi`."
        )
    session = cr.Session(impersonate="chrome131")
    # Seed with cached cookies if present.
    for c in _load_session_cookies():
        try:
            session.cookies.set(
                c["name"],
                c["value"],
                domain=c.get("domain"),
                path=c.get("path") or "/",
            )
        except Exception:
            continue
    return session


def _is_logged_in(session) -> bool:
    """Cheap auth probe: does the cookie jar carry a WP login
    cookie?  WP sets ``wordpress_logged_in_*`` and ``wordpress_sec_*``
    on successful authentication."""
    for c in session.cookies.jar:
        name = getattr(c, "name", "")
        if name.startswith("wordpress_logged_in_"):
            return True
    return False


def _login(session) -> None:
    """POST WP login credentials; raises on failure."""
    username = os.environ.get("DLF_USERNAME", "").strip()
    password = os.environ.get("DLF_PASSWORD", "").strip()
    if not username or not password:
        raise SystemExit(
            "DLF_USERNAME / DLF_PASSWORD not set in .env.  Add to the "
            "repo's .env file (gitignored) or set as GitHub Secrets for CI."
        )
    # 1) Seed baseline cookies from the login page (WP's testcookie
    #    handshake requires a GET before POST).
    r1 = session.get(LOGIN_URL, timeout=30)
    if r1.status_code != 200:
        raise RuntimeError(f"DLF login GET failed: HTTP {r1.status_code}")
    # 2) Submit credentials.  WP's login form POSTs ``log`` / ``pwd``
    #    / ``wp-submit`` with a ``redirect_to`` on success.
    r2 = session.post(
        LOGIN_URL,
        data={
            "log": username,
            "pwd": password,
            "wp-submit": "Log In",
            "redirect_to": HOME_URL,
            "testcookie": "1",
        },
        headers={
            "Referer": LOGIN_URL,
            "Origin": "https://dynastyleaguefootball.com",
        },
        timeout=30,
        allow_redirects=True,
    )
    if r2.status_code not in (200, 302):
        raise RuntimeError(f"DLF login POST failed: HTTP {r2.status_code}")
    if not _is_logged_in(session):
        # WP returns 200 with the login form on invalid credentials.
        # Surface the page's error message for diagnostics.
        snippet = r2.text[:600].replace("\n", " ")
        raise RuntimeError(
            "DLF login rejected — no wordpress_logged_in_* cookie issued.  "
            f"Page snippet: {snippet}"
        )
    _save_session_cookies(session)


def _ensure_logged_in(session) -> None:
    """Cheap-first auth: trust cached cookies, verify via probe, log
    in only when needed.  Probing is done by hitting the home page
    and checking for a ``Log Out`` link — an authenticated member
    page always renders that link in the top nav."""
    if not _is_logged_in(session):
        _login(session)
        return
    # Verify the cached cookies still work by hitting the home page
    # and sniffing for the logged-in sentinel.
    r = session.get(HOME_URL, timeout=30)
    if r.status_code != 200 or "wp-login.php?action=logout" not in r.text:
        print("[DLF] cached session rejected — re-authenticating …", flush=True)
        _login(session)


def _fetch_rankings_html(session, url: str) -> str:
    """GET a DLF rankings URL; raises if the response looks like the
    non-member preview (which typically clips to 10 rows + upsell)."""
    r = session.get(url, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"DLF rankings GET {url} failed: HTTP {r.status_code}")
    return r.text


# Paywall sentinels — phrases DLF only shows to unauthenticated
# visitors on the rankings pages.  If any match, the full board is
# NOT in the response and we need to re-authenticate.  We match on
# the "DLF Premium" upsell block specifically (shown above the
# truncated 10-row preview), not on generic subscription links
# that also appear in the page footer.
_PAYWALL_SENTINELS = (
    "This content is for",  # WP-MemberPress upsell wrapper
    "Please login to access this page",
    "Your account is not yet active",
)


def _looks_like_preview(html: str) -> bool:
    """Heuristic: the non-member preview truncates the DOM to the
    top 10 rows + an upsell banner.  Signal presence of any of the
    known preview phrases AND a short (<200KB) body."""
    if len(html) < 200_000:
        for sig in _PAYWALL_SENTINELS:
            if sig.lower() in html.lower():
                return True
    return False


def _parse_rankings(html: str) -> list[dict]:
    """Extract rows from a DLF rankings HTML page.

    DLF renders rankings as a WPDataTable with headers
    ``Rank, Avg, Pos, Name, Team, Age, <expert1>, …, Value, Follow``.
    We pick up every row whose ``Name`` cell is populated and preserve both
    expert rank and the native ``Value`` column.  Rank remains the DLF blend
    signal; Value is a separate vendor-native asset quantity for literal DLF
    trade second opinions.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit(
            "beautifulsoup4 required for HTML parsing.  "
            "Install with `pip install beautifulsoup4`."
        )
    soup = BeautifulSoup(html, "html.parser")
    # Walk every <table>; pick the first one with a Name + (Avg|Rank)
    # header pair and enough body rows.  DLF's page also emits small
    # sidebar tables (related articles, ads) we need to skip past.
    for table in soup.find_all("table"):
        thead = table.find("thead")
        if thead is None:
            # Fallback: some DLF tables put headers in the first tr.
            first_tr = table.find("tr")
            if not first_tr:
                continue
            header_cells = first_tr.find_all(["th", "td"])
        else:
            header_cells = thead.find_all(["th", "td"])
        if not header_cells:
            continue
        # Use the cell's full text (including <br>-joined expert
        # name + "Last Updated: ..." annotations) — we only care
        # about the prefix.
        headers = [(c.get_text(" ", strip=True) or "").strip().lower() for c in header_cells]

        def _find(*targets: str) -> int:
            for i, h in enumerate(headers):
                first_tok = h.split()[0] if h else ""
                if h in targets or first_tok in targets:
                    return i
            return -1

        name_idx = _find("name", "player")
        avg_idx = _find("avg", "average")
        rank_idx = _find("rank", "#")
        pos_idx = _find("pos", "position")
        team_idx = _find("team")
        value_idx = _find("value")
        if name_idx == -1 or (avg_idx == -1 and rank_idx == -1):
            continue
        # Walk body rows.
        body = table.find("tbody") or table
        rows_out: list[dict] = []
        for tr in body.find_all("tr"):
            cells = tr.find_all("td")
            if not cells:
                continue

            def _cell(i: int) -> str:
                if i < 0 or i >= len(cells):
                    return ""
                return cells[i].get_text(" ", strip=True).strip()

            name = _cell(name_idx)
            if not name:
                continue
            avg = _cell(avg_idx)
            rank = _cell(rank_idx)
            pos = _cell(pos_idx)
            team = _cell(team_idx)
            value = _cell(value_idx)
            rows_out.append(
                {
                    "name": name,
                    "avg": avg,
                    "rank": rank,
                    "pos": pos,
                    "team": team,
                    "value": value,
                }
            )
        if len(rows_out) >= 10:
            return rows_out
    return []


def _rank_of(row: dict) -> float | None:
    """Prefer the Avg column (expert-consensus average, fractional)
    over the Rank column (nominal integer).  Returns ``None`` when
    neither parses as a positive number so the caller can drop the
    row cleanly."""
    for key in ("avg", "rank"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return None


def _native_value_of(row: dict) -> float | None:
    """Return DLF's positive native Value, or None when unavailable."""
    raw = str(row.get("value") or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


_TRADE_VALUE_PLAYER_RE = re.compile(
    r"^(?P<name>.+?)\s*\[(?P<pos>[A-Z]{1,4}),\s*(?P<team>[A-Z]{2,4})\]$"
)
_TRADE_VALUE_PICK_RE = re.compile(
    r"^(?P<year>\d{4})\s+(?P<round>\d{1,2})\.(?P<slot>\d{1,2})(?:\s*\((?P<overall>\d+)\))?$"
)
#: Icon ligature text the page renders beside every asset (Material "swap
#: arrows" button) — markup, not part of the asset's name.
_ASSET_ICON_SUFFIXES: tuple[str, ...] = ("swap_horiz",)


def _published_value(raw: str) -> str | None:
    """DLF's value exactly as published (commas removed, every decimal kept),
    or ``None`` — blank, malformed and non-positive are MISSING, never 0."""
    text = str(raw or "").strip().replace(",", "")
    try:
        number = float(text)
    except (TypeError, ValueError):
        return None
    return text if number > 0 else None


def _parse_trade_values(html: str) -> list[dict]:
    """Rows of every ``Asset | Value`` table on the Trade Analyzer Values page.

    Each row is ``{"kind": "player"|"pick"|"unparsed", "asset", "value", ...}``
    where ``value`` is the published text (or ``None`` when missing).  Players
    carry ``name`` / ``pos`` / ``team``; picks ``year`` / ``round`` / ``slot``
    / ``overall``.  An asset matching neither shape is kept as ``unparsed`` so
    a page change is counted, not silently dropped.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit("beautifulsoup4 required for HTML parsing.")
    out: list[dict] = []
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        thead = table.find("thead")
        head = (thead or table.find("tr") or table).find_all(["th", "td"])
        headers = [c.get_text(" ", strip=True).strip().lower() for c in head]
        if "asset" not in headers or "value" not in headers:
            continue
        a_idx, v_idx = headers.index("asset"), headers.index("value")
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) <= max(a_idx, v_idx):
                continue
            asset = cells[a_idx].get_text(" ", strip=True)
            for suffix in _ASSET_ICON_SUFFIXES:
                if asset.endswith(suffix):
                    asset = asset[: -len(suffix)].strip()
            if not asset:
                continue
            row: dict = {
                "asset": asset,
                "value": _published_value(cells[v_idx].get_text(" ", strip=True)),
            }
            if m := _TRADE_VALUE_PLAYER_RE.match(asset):
                row.update(kind="player", name=m["name"].strip(), pos=m["pos"], team=m["team"])
            elif m := _TRADE_VALUE_PICK_RE.match(asset):
                row.update(
                    kind="pick",
                    year=int(m["year"]),
                    round=int(m["round"]),
                    slot=int(m["slot"]),
                    overall=int(m["overall"]) if m["overall"] else None,
                )
            else:
                row["kind"] = "unparsed"
            out.append(row)
    return out


def _values_board_verdict(cfg: dict, rows: list[dict]) -> tuple[bool, str]:
    """Write guard for a ``kind: values`` board: enough PLAYERS with a valid
    published value.  Picks and unparsed assets never count toward the floor."""
    min_rows = int(cfg.get("min_rows") or 30)
    valued = sum(1 for r in rows if r.get("kind") == "player" and r.get("value"))
    if valued < min_rows:
        return False, (
            f"only {valued} players with a valid published Value — expected ≥{min_rows}; "
            "partial/degraded scrape or page change"
        )
    return True, "ok"


def _write_values_csv(path: Path, rows: list[dict]) -> int:
    """``name,pos,team,value`` — each value exactly as DLF published it.
    Players without a valid value are omitted (missing, not zero)."""
    written, seen = [], set()
    for r in rows:
        if r.get("kind") != "player" or not r.get("value"):
            continue
        key = (r["name"], r["pos"])
        if key in seen:
            continue
        seen.add(key)
        written.append((r["name"], r["pos"], r["team"], r["value"]))
    written.sort(key=lambda t: -float(t[3]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "pos", "team", "value"])
        w.writerows(written)
    return len(written)


def _write_value_picks_csv(path: Path, rows: list[dict]) -> int:
    """Pick assets, kept for the pick audit — never a model input here."""
    picks = [r for r in rows if r.get("kind") == "pick" and r.get("value")]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["asset", "year", "round", "slot", "overall", "value"])
        for r in picks:
            w.writerow(
                [r["asset"], r["year"], r["round"], r["slot"], r["overall"] or "", r["value"]]
            )
    return len(picks)


def _values_summary(rows: list[dict]) -> list[str]:
    """Evidence lines for ``--dry-run`` (and the on-box diagnostic)."""
    from collections import Counter

    kinds = Counter(r["kind"] for r in rows)
    players = [r for r in rows if r["kind"] == "player"]
    valued = [float(r["value"]) for r in players if r["value"]]
    lines = [
        f"assets={len(rows)} kinds={dict(kinds)} players_valued={len(valued)} "
        f"missing_value={sum(1 for r in players if not r['value'])}",
        f"positions={dict(Counter(r['pos'] for r in players))}",
    ]
    if valued:
        s = sorted(valued, reverse=True)
        q = {p: s[min(len(s) - 1, int(p * len(s)))] for p in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9)}
        lines.append(
            f"value max={s[0]} min={s[-1]} p10={q[0.1]} p25={q[0.25]} p50={q[0.5]} "
            f"p75={q[0.75]} p90={q[0.9]} decimals={any('.' in r['value'] for r in players if r['value'])}"
        )
    picks = [r for r in rows if r["kind"] == "pick"]
    if picks:
        by_year = Counter(r["year"] for r in picks)
        lines.append(f"picks by year={dict(sorted(by_year.items()))}")
        lines.append("pick sample=" + str([(r["asset"], r["value"]) for r in picks[:12]]))
    unparsed = [r["asset"] for r in rows if r["kind"] == "unparsed"]
    if unparsed:
        lines.append(f"unparsed ({len(unparsed)})={unparsed[:12]}")
    return lines


def _board_verdict(cfg: dict, rows: list[dict]) -> tuple[bool, str]:
    """Would a real run write this board?  ``(ok, reason)``.

    The ONE place the per-board write guards live, shared by the real run and
    ``--dry-run`` so a diagnostic reports exactly the decision production makes.
    """
    min_rows = int(cfg.get("min_rows") or 30)
    if len(rows) < min_rows:
        return False, (
            f"parsed only {len(rows)} rows — expected ≥{min_rows} (aligned with "
            "the downstream contract floor); partial/degraded scrape"
        )
    return True, "ok"


def _native_value_note(cfg: dict, rows: list[dict]) -> str | None:
    """A warning when a board that should carry DLF's native Value does not.

    SEPARATE from :func:`_board_verdict` on purpose (owner directive
    2026-09-24): rank is the model signal and Value is an optional
    vendor-literal column, so a missing Value is reported — and written as an
    empty column, never synthesized from rank — while the rank board updates.
    """
    if not cfg.get("expect_native_value"):
        return None
    native_count = sum(1 for row in rows if _native_value_of(row) is not None)
    if native_count >= int(cfg.get("min_rows") or 30):
        return None
    return (
        f"native Value coverage {native_count}/{len(rows)} — DLF's Value column is "
        "unavailable on this board; writing rank with an empty value column"
    )


def _candidate_table_headers(html: str) -> list[list[str]]:
    """Header cells of every table with at least 10 body rows (diagnostics).

    Header text on DLF's tables is public column labels and expert names; each
    cell is clipped so a long annotation cannot flood the log.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    out: list[list[str]] = []
    for table in BeautifulSoup(html, "html.parser").find_all("table"):
        body = table.find("tbody") or table
        if len([tr for tr in body.find_all("tr") if tr.find_all("td")]) < 10:
            continue
        thead = table.find("thead")
        cells = (thead or table.find("tr") or table).find_all(["th", "td"])
        out.append([c.get_text(" ", strip=True)[:40] for c in cells][:40])
    return out


#: Page-structure markers the probe counts.  Plain substrings, printed as
#: counts only — never the surrounding text, which can carry nonces.
_PROBE_MARKERS: tuple[str, ...] = (
    "wpDataTable",
    "wpdatatables",
    "wdt_",
    "admin-ajax.php",
    "wp-json",
    "ajaxurl",
    'type="application/json"',
    "JSON.parse(",
    "DataTable(",
    "tablepress",
    "__NEXT_DATA__",
    "trade-analyzer",
    "tradeAnalyzer",
    "trade_analyzer",
)
_PROBE_HOST = "dynastyleaguefootball.com"


def _probe_page(html: str) -> list[str]:
    """Structural diagnostics for one DLF page — lines to print.

    Read-only evidence for designing a parser: table shapes, the first rows of
    each table, and which embedded-data mechanisms the page uses.  Prints
    structure and public row text only: no script bodies, no attribute values
    that could be nonces, and never anything from the session.
    """
    import re

    lines = [f"html_bytes={len(html)} preview={_looks_like_preview(html)}"]
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return lines + ["bs4 unavailable — structure not parsed"]
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    lines.append(f"title={(title.get_text(' ', strip=True) if title else '')[:100]!r}")

    for marker in _PROBE_MARKERS:
        n = html.count(marker)
        if n:
            lines.append(f"marker {marker!r} x{n}")

    tables = soup.find_all("table")
    lines.append(f"tables={len(tables)}")
    for ti, table in enumerate(tables):
        body = table.find("tbody") or table
        body_rows = [tr for tr in body.find_all("tr") if tr.find_all("td")]
        attrs = sorted(k for k in table.attrs if k in ("id", "class") or k.startswith("data-"))
        classes = " ".join(table.get("class") or [])[:80]
        lines.append(
            f"table[{ti}] body_rows={len(body_rows)} id={str(table.get('id') or '')[:40]!r} "
            f"class={classes!r} attr_names={attrs[:12]}"
        )
        if len(body_rows) < 3:
            continue
        thead = table.find("thead")
        head = (thead or table.find("tr") or table).find_all(["th", "td"])
        lines.append(f"  headers={[c.get_text(' ', strip=True)[:30] for c in head][:20]}")
        for ri, tr in enumerate(body_rows[:8], 1):
            cells = [c.get_text(" ", strip=True)[:30] for c in tr.find_all("td")][:14]
            lines.append(f"  row{ri}={cells}")

    for si, script in enumerate(soup.find_all("script")):
        stype = str(script.get("type") or "")
        text = script.string or script.get_text() or ""
        if "json" in stype.lower():
            keys: list[str] = []
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    keys = sorted(parsed)[:15]
                elif isinstance(parsed, list):
                    keys = [f"<list len={len(parsed)}>"]
            except (TypeError, ValueError):
                keys = ["<unparseable>"]
            lines.append(
                f"json_script[{si}] type={stype!r} id={str(script.get('id') or '')[:40]!r} "
                f"bytes={len(text)} top_keys={keys}"
            )
            continue
        # Large inline JS literals are the usual carrier of a client-rendered
        # table.  Name and size only.
        for m in re.finditer(r"(?:var|let|const)\s+([A-Za-z_$][\w$]*)\s*=\s*([\[{])", text):
            if len(text) - m.start() >= 5000:
                lines.append(
                    f"js_literal script[{si}] name={m.group(1)!r} opens={m.group(2)!r} "
                    f"script_bytes={len(text)}"
                )
        actions = sorted(set(re.findall(r"""action['"]?\s*[:=]\s*['"]([\w-]{3,60})['"]""", text)))
        if actions:
            lines.append(f"ajax_actions script[{si}]={actions[:10]}")
    return lines


def _probe(session, url: str) -> int:
    """Fetch one DLF URL with the member session and print diagnostics only."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme != "https" or (
        parsed.hostname != _PROBE_HOST and not str(parsed.hostname).endswith("." + _PROBE_HOST)
    ):
        print(f"[DLF] probe refused: only https://{_PROBE_HOST} URLs", file=sys.stderr)
        return 2
    try:
        html = _fetch_rankings_html(session, url)
        if _looks_like_preview(html):
            print("[DLF] probe: non-member preview — re-authenticating …", flush=True)
            _login(session)
            html = _fetch_rankings_html(session, url)
    except (RuntimeError, SystemExit) as exc:
        print(f"[DLF] probe fetch failed: {exc}", file=sys.stderr)
        return 1
    print(f"[DLF] probe {url}")
    for line in _probe_page(html):
        print(f"  {line}")
    return 0


def _format_number(value: float) -> int | str:
    """CSV-friendly number that keeps meaningful decimal precision."""
    if value == int(value):
        return int(value)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _write_csv(path: Path, rows: list[dict]) -> int:
    """Write DLF expert rank and native value as separate columns.

    Rank remains the canonical blend signal. Value is preserved for
    vendor-literal trade second opinions and never becomes a second DLF vote.
    """
    written: list[tuple[str, float, float | None]] = []
    seen_names: set[str] = set()
    for r in rows:
        name = (r.get("name") or "").strip()
        if not name:
            continue
        rank_val = _rank_of(r)
        if rank_val is None:
            continue
        # Dedup within the same board — DLF occasionally emits a
        # trailing "view full rankings" row that echoes the last
        # player; skip that kind of accidental duplicate.
        if name in seen_names:
            continue
        written.append((name, rank_val, _native_value_of(r)))
        seen_names.add(name)
    written.sort(key=lambda t: t[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank", "value"])
        for name, rank_val, native_value in written:
            w.writerow(
                [
                    name,
                    int(rank_val) if rank_val == int(rank_val) else f"{rank_val:.2f}",
                    "" if native_value is None else _format_number(native_value),
                ]
            )
    return len(written)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't write any CSVs.",
    )
    parser.add_argument(
        "--only",
        metavar="BOARD_KEY",
        action="append",
        default=None,
        help=f"Scrape only this board (repeatable).  Choices: {', '.join(BOARDS)}",
    )
    parser.add_argument(
        "--written-manifest",
        metavar="PATH",
        default=None,
        help=(
            "Write a JSON list of the board keys this run actually wrote.  Lets "
            "the prod push commit the boards that succeeded even when another "
            "board refused to overwrite its last-good CSV (exit 2)."
        ),
    )
    parser.add_argument(
        "--probe",
        metavar="URL",
        default=None,
        help=(
            "Read-only: log in, fetch one DLF URL and print its page structure "
            "(tables, first rows, embedded-data markers).  Writes nothing."
        ),
    )
    args = parser.parse_args()

    _load_env_dotfile(ENV_PATH)
    if args.probe:
        session = _build_session()
        try:
            _ensure_logged_in(session)
        except (SystemExit, RuntimeError) as exc:
            print(f"[DLF] login failed: {exc}", file=sys.stderr)
            return 1
        return _probe(session, args.probe)
    written_keys: list[str] = []

    def _write_manifest() -> None:
        if args.written_manifest:
            Path(args.written_manifest).write_text(
                json.dumps(written_keys) + "\n", encoding="utf-8"
            )

    _write_manifest()

    boards = args.only if args.only else list(BOARDS.keys())
    for key in boards:
        if key not in BOARDS:
            print(f"[DLF] ERROR: unknown board '{key}'", file=sys.stderr)
            return 2

    session = _build_session()
    try:
        _ensure_logged_in(session)
    except (SystemExit, RuntimeError) as exc:
        print(f"[DLF] login failed: {exc}", file=sys.stderr)
        return 1

    exit_code = 0
    for key in boards:
        cfg = BOARDS[key]
        url = cfg["url"]
        label = cfg["label"]
        min_rows = int(cfg.get("min_rows") or 30)
        out_path = REPO / cfg["out"]
        try:
            html = _fetch_rankings_html(session, url)
        except RuntimeError as exc:
            print(f"[DLF] {key} fetch failed: {exc}", file=sys.stderr)
            exit_code = max(exit_code, 1)
            continue
        if _looks_like_preview(html):
            # The cached session may have expired mid-run; try once more.
            print(f"[DLF] {key}: got non-member preview — re-authenticating …", flush=True)
            try:
                _login(session)
                html = _fetch_rankings_html(session, url)
            except RuntimeError as exc:
                print(f"[DLF] {key}: re-auth failed: {exc}", file=sys.stderr)
                exit_code = max(exit_code, 1)
                continue
            if _looks_like_preview(html):
                print(
                    f"[DLF] {key}: still preview after re-auth — " f"membership may have lapsed.",
                    file=sys.stderr,
                )
                exit_code = max(exit_code, 1)
                continue
        if cfg.get("kind") == "values":
            vrows = _parse_trade_values(html)
            print(f"[DLF] {key} ({label}): parsed {len(vrows)} assets")
            ok, reason = _values_board_verdict(cfg, vrows)
            if args.dry_run:
                print(f"  html_bytes={len(html)} preview={_looks_like_preview(html)}")
                for line in _values_summary(vrows):
                    print(f"  {line}")
                print(f"  verdict={'WRITE' if ok else 'REFUSE'} reason={reason}")
                continue
            if not ok:
                print(
                    f"[DLF] {key}: {reason}.  Preserving last-good CSV, NOT "
                    f"overwriting {out_path.relative_to(REPO)}.",
                    file=sys.stderr,
                )
                exit_code = max(exit_code, 2)
                continue
            count = _write_values_csv(out_path, vrows)
            picks = _write_value_picks_csv(REPO / cfg["picks_out"], vrows)
            print(
                f"[DLF] wrote {count} player values → {out_path.relative_to(REPO)} "
                f"(+{picks} pick values for audit)",
                flush=True,
            )
            written_keys.append(key)
            _write_manifest()
            continue
        rows = _parse_rankings(html)
        print(f"[DLF] {key} ({label}): parsed {len(rows)} rows")
        if not rows:
            print(f"[DLF] WARN: no rows extracted for {key}", file=sys.stderr)
            exit_code = max(exit_code, 1)
            continue
        ok, reason = _board_verdict(cfg, rows)
        if args.dry_run:
            # Evidence only: what the real run WOULD decide, from the same
            # verdict function, plus the table headers the parser saw.  Used by
            # the on-box DLF diagnostic (deploy/diagnostics/dlf_fetch_inventory.sh).
            rank_count = sum(1 for row in rows if _rank_of(row) is not None)
            native_count = sum(1 for row in rows if _native_value_of(row) is not None)
            print(f"  html_bytes={len(html)} preview={_looks_like_preview(html)}")
            for headers in _candidate_table_headers(html):
                print(f"  table_headers={headers}")
            print(
                f"  rows={len(rows)} rank_parsable={rank_count} "
                f"native_value={native_count} min_rows={min_rows} "
                f"expect_native_value={bool(cfg.get('expect_native_value'))}"
            )
            print(f"  verdict={'WRITE' if ok else 'REFUSE'} reason={reason}")
            note = _native_value_note(cfg, rows)
            if note:
                print(f"  native_value=UNAVAILABLE {note}")
            for i, r in enumerate(rows[:5], 1):
                print(
                    f"  {i:>3}. name={r.get('name')!r} "
                    f"avg={r.get('avg')!r} rank={r.get('rank')!r} "
                    f"value={r.get('value')!r} pos={r.get('pos')!r}"
                )
            continue
        # Check the floor BEFORE writing.  The old code wrote the CSV
        # first and only WARNed when short — so a partial/degraded
        # scrape overwrote the last-good board and (because the floor
        # was below the downstream contract floor) silently shipped a
        # CSV that later hard-failed the contract-coverage test on a
        # clean checkout.  Now: fail loudly, preserve last-good, never
        # overwrite with a structurally-degraded board.
        if not ok:
            print(
                f"[DLF] {key}: {reason}.  Preserving last-good CSV, NOT "
                f"overwriting {out_path.relative_to(REPO)}.",
                file=sys.stderr,
            )
            exit_code = max(exit_code, 2)
            continue
        note = _native_value_note(cfg, rows)
        if note:
            print(f"[DLF] WARNING {key}: {note}", file=sys.stderr, flush=True)
        count = _write_csv(out_path, rows)
        print(
            f"[DLF] wrote {count} rows → {out_path.relative_to(REPO)}",
            flush=True,
        )
        written_keys.append(key)
        _write_manifest()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
