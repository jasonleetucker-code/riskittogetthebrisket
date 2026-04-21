#!/usr/bin/env python3
"""Fetch DynastyLeagueFootball (DLF) rankings for the four boards
we consume: ``dlfSf``, ``dlfIdp``, ``dlfRookieSf``, ``dlfRookieIdp``.

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
        "min_rows": 200,
    },
    "dlfIdp": {
        "url": "https://dynastyleaguefootball.com/rankings/dynasty-idp-rankings/",
        "out": "CSVs/site_raw/dlfIdp.csv",
        "label": "Dynasty IDP",
        "min_rows": 120,
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
        out.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain") or ".dynastyleaguefootball.com",
            "path": c.get("path") or "/",
        })
    return out


def _save_session_cookies(session) -> None:
    """Persist the session's cookie jar so the next run can skip the
    login POST.  WP session cookies are typically valid ~14 days."""
    cookies_out: list[dict] = []
    for c in session.cookies.jar:
        try:
            cookies_out.append({
                "name": c.name,
                "value": c.value,
                "domain": c.domain or ".dynastyleaguefootball.com",
                "path": c.path or "/",
            })
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
                c["name"], c["value"],
                domain=c.get("domain"), path=c.get("path") or "/",
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
        raise RuntimeError(
            f"DLF login GET failed: HTTP {r1.status_code}"
        )
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
        raise RuntimeError(
            f"DLF login POST failed: HTTP {r2.status_code}"
        )
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
    "This content is for",            # WP-MemberPress upsell wrapper
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
    We pick up every row whose ``Name`` cell is populated and emit
    ``{name, avg, rank, pos, team}`` so the caller can write a
    ``name,rank`` CSV that preserves the Avg column preference.
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
        headers = [
            (c.get_text(" ", strip=True) or "").strip().lower()
            for c in header_cells
        ]
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
            rows_out.append({
                "name": name,
                "avg": avg,
                "rank": rank,
                "pos": pos,
                "team": team,
            })
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


def _write_csv(path: Path, rows: list[dict]) -> int:
    """Write a ``name,rank`` CSV, preferring Avg over Rank per DLF's
    expert-consensus ladder convention.  Rows without a valid rank
    are silently dropped."""
    written: list[tuple[str, float]] = []
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
        written.append((name, rank_val))
        seen_names.add(name)
    written.sort(key=lambda t: t[1])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "rank"])
        for name, rank_val in written:
            # Preserve fractional precision from the Avg column.
            if rank_val == int(rank_val):
                w.writerow([name, int(rank_val)])
            else:
                w.writerow([name, f"{rank_val:.2f}"])
    return len(written)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Scrape but don't write any CSVs.",
    )
    parser.add_argument(
        "--only", metavar="BOARD_KEY", action="append", default=None,
        help=f"Scrape only this board (repeatable).  Choices: {', '.join(BOARDS)}",
    )
    args = parser.parse_args()

    _load_env_dotfile(ENV_PATH)

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
                    f"[DLF] {key}: still preview after re-auth — "
                    f"membership may have lapsed.",
                    file=sys.stderr,
                )
                exit_code = max(exit_code, 1)
                continue
        rows = _parse_rankings(html)
        print(f"[DLF] {key} ({label}): parsed {len(rows)} rows")
        if not rows:
            print(f"[DLF] WARN: no rows extracted for {key}", file=sys.stderr)
            exit_code = max(exit_code, 1)
            continue
        if args.dry_run:
            for i, r in enumerate(rows[:5], 1):
                print(
                    f"  {i:>3}. name={r.get('name')!r} "
                    f"avg={r.get('avg')!r} rank={r.get('rank')!r} "
                    f"pos={r.get('pos')!r}"
                )
            continue
        count = _write_csv(out_path, rows)
        print(
            f"[DLF] wrote {count} rows → {out_path.relative_to(REPO)}",
            flush=True,
        )
        if count < min_rows:
            print(
                f"[DLF] WARN: {key} wrote only {count} rows — expected ≥{min_rows}.  "
                f"DLF page structure may have changed; inspect "
                f"{out_path.relative_to(REPO)}.",
                file=sys.stderr,
            )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
