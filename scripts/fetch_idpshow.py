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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources.acquisition_state import (  # noqa: E402
    AUTH_REQUIRED,
    HEALTHY,
    PARSE_FAILED,
    SCHEMA_CHANGED,
    UNAVAILABLE,
    AcquisitionOutcome,
)

REPO = Path(__file__).resolve().parents[1]
SESSION_PATH = REPO / "idpshow_session.json"
ARTICLE_URL = "https://www.theidpshow.com/p/idp-dynasty-rankings"
OUT_PATH = REPO / "CSVs" / "site_raw" / "idpShow.csv"

#: Companion to data/scrape_state/idpShow_last_success (written by
#: deploy/idpshow_fetch_and_push.sh only on a truly successful run).  This
#: file is written by THIS script, on every real (non-dry-run) invocation of
#: the PLAIN board, success or failure, so a failed run's FAILURE CLASS
#: survives -- not just the fact that the freshness stamp didn't advance.
#: Never contains a cookie name or value: AcquisitionOutcome's fields are
#: outcome metadata only (state/reason/detail/rowCount), and nothing here
#: reads the cookie jar's contents into a message.
STATUS_PATH = REPO / "data" / "scrape_state" / "idpShow_last_status.json"
SOURCE_KEY = "idpShow"

#: The board that actually VOTES (see COMBINED_ARTICLE_URL below) gets its
#: OWN status file, not a shared one.  deploy/idpshow_fetch_and_push.sh runs
#: this script TWICE per cycle -- plain, then --combined -- as two separate
#: process invocations; a single shared status file would let the second
#: run's outcome silently overwrite the first's, which is exactly the
#: collapse this instrumentation exists to prevent.  Mirrors the existing
#: idpShow_last_success / idpShowCombined_last_success freshness-stamp split
#: the deploy script already uses.
COMBINED_STATUS_PATH = REPO / "data" / "scrape_state" / "idpShowCombined_last_status.json"
COMBINED_SOURCE_KEY = "idpShowCombined"

#: The repo-wide 0/1/2 exit-code convention (src/sources/acquisition_state.py
#: ::state_from_exit_code) stays the external contract so
#: deploy/idpshow_fetch_and_push.sh's `if ! ...; then` check is unaffected --
#: this instrumentation is additive, not a taxonomy change.  SCHEMA_CHANGED
#: keeps exit 2; every other non-HEALTHY state keeps exit 1, with the real
#: distinction now recorded in the board-appropriate status file instead of
#: collapsed away.
_EXIT_CODE_BY_STATE = {HEALTHY: 0, SCHEMA_CHANGED: 2}


def _persist_outcome(outcome: AcquisitionOutcome, status_path: Path) -> int:
    """Print the outcome as JSON (no secret values -- see the status-path
    comments above) and persist it to ``status_path``.  Returns the exit
    code for ``main`` to propagate, unifying every return point in one
    place so a caller can't add a new failure branch without also
    classifying it.  ``status_path`` is threaded through rather than a
    module-level constant because ONE process run acquires exactly ONE
    board (plain XOR combined) and must only ever touch that board's own
    status file -- never the other board's."""
    payload = outcome.to_dict()
    print(json.dumps(payload, indent=2))
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return _EXIT_CODE_BY_STATE.get(outcome.state, 1)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rel(path: Path) -> str:
    """Display-only: relative to REPO when possible, absolute otherwise (a
    test double may point these paths outside REPO)."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


# The SAME publisher also runs a COMBINED offense+IDP dynasty board.  It is a
# different QUANTITY from the IDP-only board above — a cross-market ordering
# that ranks Bijan Robinson against Patrick Queen — not a re-cut of it.
#
# Acquired and preserved; it votes NOTHING.  Two reasons, both load-bearing:
#
#   * It is the same PROVIDER, so admitting both as independent votes would
#     manufacture agreement out of one opinion — the KTC Off/TE+/TE++/TE+++
#     defect family CLAUDE.md names explicitly.
#   * Measured 2026-08-20, the swap is not a free upgrade: the combined board
#     carries 250 players (170 offense / 80 IDP) against the IDP board's 350,
#     and only 79 of our current IDP players appear on it.  Switching wholesale
#     would strip an IDP Show vote from 278 defenders to gain 170 offense rows.
#
# Which board should VOTE is an owner decision with a measured cost, not a URL
# swap.  This fetcher's job is to make the evidence available either way.
COMBINED_ARTICLE_URL = (
    "https://www.theidpshow.com/p/combined-idp-offense-dynasty-rankings-fantasy-football"
)
COMBINED_OUT_PATH = REPO / "CSVs" / "site_raw" / "idpShowCombined.csv"

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
        out.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain") or ".theidpshow.com",
                "path": c.get("path") or "/",
            }
        )
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
                c["name"],
                c["value"],
                domain=str(c.get("domain") or "").lstrip("."),
                path=c.get("path") or "/",
            )
        except Exception:
            continue
    return session


def _fetch_article_html(session, url: str = ARTICLE_URL) -> str:
    r = session.get(url, timeout=45)
    if r.status_code != 200:
        raise RuntimeError(f"GET {url} failed: HTTP {r.status_code}")
    return r.text


def _extract_chart_id(html: str) -> str | None:
    """Locate the Datawrapper iframe and return the base chart ID.

    The iframe ``src`` looks like
    ``https://datawrapper.dwcdn.net/Kwh7Y/5/`` — we pull the chart
    ID only (``Kwh7Y``) and rely on :func:`_resolve_latest_version`
    to walk the JS-redirect chain and find the current version.
    Substack articles often keep the iframe's embed URL at whatever
    version was live when the post was first published (here v5)
    while the author republishes new versions behind that redirect.
    """
    m = re.search(
        r"datawrapper\.dwcdn\.net/([A-Za-z0-9]+)/(\d+)/",
        html,
    )
    if not m:
        return None
    return m.group(1)


def _extract_all_chart_ids(html: str) -> list[str]:
    """Every distinct Datawrapper chart embedded in the article, in order.

    :func:`_extract_chart_id` returns the FIRST iframe, which is right for
    the IDP-only post (one chart) and WRONG for the combined post, which
    embeds two: a top-250 excerpt and the full 700+ board.  Taking the
    first silently ingests the excerpt — measured 2026-08-20, that cost
    277 of the 350 IDP players their cross-market placement.
    """
    seen: list[str] = []
    for m in re.finditer(r"datawrapper\.dwcdn\.net/([A-Za-z0-9]+)/", html):
        cid = m.group(1)
        if cid not in seen:
            seen.append(cid)
    return seen


def _pick_widest_chart(session, chart_ids: list[str]) -> tuple[str, str, str] | None:
    """Choose the chart with the MOST data rows, and say why.

    Selection is on measured row count rather than on document order or a
    hardcoded id, for two reasons: the author can reorder the embeds, and a
    hardcoded id silently breaks the day the chart is republished under a
    new one.  Ties and empty responses lose - a truncated fetch must never
    win by default, which is the same fail-closed posture as the 0-rows
    guard in :func:`main`.
    """
    best: tuple[str, str, str] | None = None
    best_rows = 0
    for cid in chart_ids:
        version = _resolve_latest_version(session, cid)
        if not version:
            continue
        try:
            csv_text = _fetch_dataset_csv(session, cid, version)
        except RuntimeError:
            continue
        rows = max(0, len(csv_text.splitlines()) - 1)
        print(f"[idpshow]   candidate {cid} v{version}: {rows} rows")
        if rows > best_rows:
            best, best_rows = (cid, version, csv_text), rows
    return best


def _resolve_latest_version(session, chart_id: str) -> str | None:
    """Follow Datawrapper's JS/meta-refresh redirects to find the
    current published version of a chart.

    The iframe endpoint at
    ``https://datawrapper.dwcdn.net/{chart_id}/{ver}/`` returns
    either:
      * a 200 with a small JS/meta redirect to the "next" version
        (e.g. v5 → v133 → v165 → v186 → v190), OR
      * a 200 with the rendered chart HTML (terminal; no redirect).

    We walk the chain up to 20 hops (protects against pathological
    loops) and return the final version number.  Fallback: return
    the starting version unchanged if the first hop already
    terminates.
    """
    current = "1"
    for _ in range(20):
        url = f"https://datawrapper.dwcdn.net/{chart_id}/{current}/"
        r = session.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            allow_redirects=False,
        )
        if r.status_code != 200:
            return None
        # If the response is a large rendered HTML page we've hit the
        # terminal version; the redirect shell is a tiny (<300 byte)
        # HTML with one script + meta tag.
        if len(r.text) > 1000:
            return current
        m = re.search(
            rf"datawrapper\.dwcdn\.net/{re.escape(chart_id)}/(\d+)/",
            r.text,
        )
        if not m:
            # No redirect and not rendered HTML either — unusual,
            # but treat as terminal to avoid infinite loops.
            return current
        next_ver = m.group(1)
        if next_ver == current:
            return current
        current = next_ver
    # Hit the hop limit without finding a terminal — likely a loop.
    return current


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


def _fetch_dataset_csv(session, chart_id: str, version: str) -> str:
    url = f"https://datawrapper.dwcdn.net/{chart_id}/{version}/dataset.csv"
    r = session.get(
        url,
        headers={"Referer": "https://www.theidpshow.com/"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"GET {url} failed: HTTP {r.status_code}")
    return r.text


def _parse_dataset(csv_text: str) -> list[dict]:
    """Parse the Datawrapper CSV; keep name / normalised position /
    rank and drop every other column (combine metrics, college
    notes, etc. are out of scope for a ranking source).

    The IDP Show republishes the chart periodically and has renamed
    its columns at least once:

      * old schema: ``PLAYER``, ``POS`` (bare code, e.g. ``ED``),
        ``OVR`` (overall rank)
      * new schema (2026-05): ``PLAYER``, ``POSITION RANK``
        (position code with the positional rank glued on, e.g.
        ``ED1`` / ``S69`` / ``DT46``), ``OVERALL`` (overall rank)

    We accept either schema so a future revert / re-rename doesn't
    silently re-break the feed (the 0-rows guard in :func:`main`
    would still catch a *third* unknown schema).
    """
    # The IDP-only chart is comma-separated; the COMBINED board is
    # tab-separated with `Rank / Name / Position / Team / Change`.  Sniff on
    # the header rather than on the flag, so a future format flip on either
    # board is handled by the same code path instead of by a second parser.
    first = csv_text.splitlines()[0] if csv_text.splitlines() else ""
    delimiter = "\t" if first.count("\t") > first.count(",") else ","
    reader = csv.DictReader(csv_text.splitlines(), delimiter=delimiter)
    rows_out: list[dict] = []
    for row in reader:
        # "Name"/"Position"/"Rank" are the COMBINED board's headers.
        name = str(row.get("PLAYER") or row.get("Name") or "").strip()
        if not name:
            continue
        # Position: old ``POS`` is a bare code; new ``POSITION RANK``
        # is the code with the positional rank concatenated
        # (``ED1``).  Strip everything from the first digit on.
        pos_src = (
            str(row.get("POS") or row.get("POSITION RANK") or row.get("Position") or "")
            .strip()
            .upper()
        )
        m = re.match(r"[A-Z]+", pos_src)
        pos_raw = m.group(0) if m else pos_src
        pos_norm = _POS_NORM.get(pos_raw, pos_raw)
        # Overall rank: old ``OVR`` → new ``OVERALL``.
        ovr_raw = (
            str(row.get("OVR") or row.get("OVERALL") or row.get("Rank") or "").strip().lstrip("0")
        )
        try:
            rank = int(ovr_raw) if ovr_raw else None
        except (TypeError, ValueError):
            continue
        if rank is None or rank <= 0:
            continue
        rows_out.append(
            {
                "name": name,
                "position": pos_norm,
                "rank": rank,
            }
        )
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


def main(argv: list[str] | None = None) -> int:
    """Entry point.  ``argv`` MUST be accepted, not just for symmetry.

    ``server.py``'s in-scrape refresh calls ``main([])`` — the same shape
    it uses for the other three fetchers, all of which already take
    ``argv``.  This one did not, so every scrape raised
    ``TypeError: main() takes 0 positional arguments but 1 was given``,
    which ``server.py:2323`` caught and logged as a WARNING
    (``idpshow_fetch_exception``).  The in-scrape IDP Show refresh was
    therefore dead in production while looking merely noisy; observed
    live 2026-07-30.

    Note that simply dropping the argument would NOT have fixed it:
    ``parse_args(None)`` reads ``sys.argv[1:]``, which under uvicorn is
    the *server's* argv, so argparse would exit on unrecognised flags.
    Threading ``argv`` through is the fix, and it matches
    ``fetch_dynasty_nerds`` / ``fetch_fantasypros_offense`` /
    ``fetch_fantasypros_idp``.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape but don't write the CSV.",
    )
    parser.add_argument(
        "--combined",
        action="store_true",
        help=(
            "Fetch the publisher's COMBINED offense+IDP dynasty board into "
            "idpShowCombined.csv instead of the IDP-only board.  This is "
            "the provider family's SOLE voting source as of 2026-08-20 — "
            "see the ``idpShowCombined`` entry in "
            "``src/api/data_contract.py::_RANKING_SOURCES``.  The plain "
            "(no-flag) board is still fetched for diagnostics but is "
            "unregistered and cannot vote.  See COMBINED_ARTICLE_URL for "
            "why this board, not that one."
        ),
    )
    args = parser.parse_args(argv)
    article_url = COMBINED_ARTICLE_URL if args.combined else ARTICLE_URL
    out_path = COMBINED_OUT_PATH if args.combined else OUT_PATH
    # ONE process run acquires exactly ONE board.  Resolved once, up front,
    # so every return point below -- including the two failure branches
    # shared by both boards (missing session / paywalled) -- stamps the
    # board that was ACTUALLY being fetched this invocation, never the
    # other one.
    source_key = COMBINED_SOURCE_KEY if args.combined else SOURCE_KEY
    status_path = COMBINED_STATUS_PATH if args.combined else STATUS_PATH

    if not SESSION_PATH.exists():
        print(
            f"[idpshow] ERROR: {_rel(SESSION_PATH)} missing.  "
            f"Paste browser cookies into that file (see the script's "
            f"module docstring for the refresh flow).",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=AUTH_REQUIRED,
                reason="session_file_missing",
                detail=f"{_rel(SESSION_PATH)} not present",
                observed_at=_now(),
            ),
            status_path,
        )

    session = _build_session()

    try:
        html = _fetch_article_html(session, article_url)
    except RuntimeError as exc:
        print(f"[idpshow] article fetch failed: {exc}", file=sys.stderr)
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=UNAVAILABLE,
                reason="article_fetch_failed",
                detail=str(exc),
                observed_at=_now(),
            ),
            status_path,
        )

    if _looks_paywalled(html):
        print(
            "[idpshow] session appears expired — article still paywalled.  "
            "Refresh cookies in idpshow_session.json.",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=AUTH_REQUIRED,
                reason="session_expired_paywalled",
                detail="article still shows the paywall sentinel with cookies attached",
                observed_at=_now(),
            ),
            status_path,
        )

    if args.combined:
        # The combined post embeds a top-250 excerpt AND the full 700+
        # board.  Pick by measured width, never by document order.
        candidates = _extract_all_chart_ids(html)
        print(f"[idpshow] combined post embeds {len(candidates)} chart(s): {candidates}")
        picked = _pick_widest_chart(session, candidates)
        if not picked:
            print(
                "[idpshow] ERROR: no Datawrapper chart in the combined post "
                "returned a usable dataset.",
                file=sys.stderr,
            )
            return _persist_outcome(
                AcquisitionOutcome(
                    source_key=source_key,
                    state=PARSE_FAILED,
                    reason="no_combined_chart_found",
                    detail=f"{len(candidates)} candidate chart(s), none produced a usable dataset",
                    observed_at=_now(),
                ),
                status_path,
            )
        chart_id, version, csv_text = picked
        print(f"[idpshow] chart_id={chart_id} version={version} (widest of {len(candidates)})")
        rows = _parse_dataset(csv_text)
        print(f"[idpshow] parsed {len(rows)} rows")
        if not rows:
            print("[idpshow] ERROR: 0 rows parsed — refusing to overwrite.", file=sys.stderr)
            return _persist_outcome(
                AcquisitionOutcome(
                    source_key=source_key,
                    state=PARSE_FAILED,
                    reason="no_rows_extracted",
                    detail=f"chart {chart_id} v{version} parsed to 0 rows",
                    observed_at=_now(),
                ),
                status_path,
            )
        # Hard floor aligned with the downstream contract guard
        # ``_DEFAULT_SOURCE_ROW_FLOORS["idpShowCombined"]`` (450).  This
        # board is now a VOTING source, so the failure mode the plain
        # board's floor exists to prevent applies here too — most
        # sharply, picking the article's 250-row excerpt chart again
        # instead of the ~665-700 row full board (the exact defect PR
        # #1008 fixed by measuring chart width instead of trusting
        # document order).  Fail loudly and preserve last-good rather
        # than silently shipping a truncated board.  Skipped under
        # --dry-run so the sample below still prints for diagnosis.
        _IDPSHOW_COMBINED_ROW_FLOOR = 450
        if not args.dry_run and len(rows) < _IDPSHOW_COMBINED_ROW_FLOOR:
            print(
                f"[idpshow] ERROR: only {len(rows)} rows — expected ≥"
                f"{_IDPSHOW_COMBINED_ROW_FLOOR} (contract floor "
                f"_DEFAULT_SOURCE_ROW_FLOORS['idpShowCombined']).  "
                f"Partial/degraded scrape (or the excerpt chart won the "
                f"width comparison again); preserving last-good CSV, not "
                f"overwriting.",
                file=sys.stderr,
            )
            return _persist_outcome(
                AcquisitionOutcome(
                    source_key=source_key,
                    state=SCHEMA_CHANGED,
                    reason="row_count_below_floor",
                    detail=(
                        f"{len(rows)} rows parsed, floor is "
                        f"{_IDPSHOW_COMBINED_ROW_FLOOR} (chart {chart_id} v{version})"
                    ),
                    observed_at=_now(),
                ),
                status_path,
            )
        if args.dry_run:
            print("[idpshow] dry run — not writing")
            # Deliberately not persisted: a dry-run writes no CSV, so
            # recording HEALTHY here would claim an acquisition that
            # didn't happen.
            return 0
        count = _write_csv(out_path, rows)
        print(f"[idpshow] wrote {count} rows → {_rel(out_path)}")
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=HEALTHY,
                row_count=count,
                observed_at=_now(),
            ),
            status_path,
        )

    chart_id = _extract_chart_id(html)
    if not chart_id:
        print(
            "[idpshow] ERROR: Datawrapper iframe not found in article.  "
            "The author may have removed the chart or switched platforms.",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=PARSE_FAILED,
                reason="chart_id_not_found",
                detail="no datawrapper.dwcdn.net iframe reference in article HTML",
                observed_at=_now(),
            ),
            status_path,
        )
    version = _resolve_latest_version(session, chart_id)
    if not version:
        print(
            f"[idpshow] ERROR: could not resolve latest Datawrapper "
            f"version for chart {chart_id} — redirect chain broke.",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=UNAVAILABLE,
                reason="version_resolution_http_error",
                detail=f"chart {chart_id}: redirect chain returned a non-200 hop",
                observed_at=_now(),
            ),
            status_path,
        )
    print(f"[idpshow] chart_id={chart_id} version={version}")

    try:
        csv_text = _fetch_dataset_csv(session, chart_id, version)
    except RuntimeError as exc:
        print(f"[idpshow] dataset fetch failed: {exc}", file=sys.stderr)
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=UNAVAILABLE,
                reason="dataset_fetch_failed",
                detail=str(exc),
                observed_at=_now(),
            ),
            status_path,
        )

    rows = _parse_dataset(csv_text)
    print(f"[idpshow] parsed {len(rows)} rows")

    # Guard: if parsing produced zero rows the CSV format almost certainly
    # changed (column rename, empty response, etc.).  Overwriting the
    # existing CSV with an empty file destroys the last-good data and
    # causes the data-quality gate to fail on every subsequent CI run.
    # Exit 1 so the VPS timer marks the run as failed; the existing CSV
    # is left intact and will continue to serve until a human investigates
    # the column change and updates _parse_dataset accordingly.
    if len(rows) == 0:
        # Print the raw CSV header line so the runner log makes the issue
        # immediately obvious without needing a separate manual fetch.
        first_line = csv_text.splitlines()[0] if csv_text.strip() else "(empty response)"
        print(
            f"[idpshow] ERROR: 0 rows parsed — CSV header was: {first_line!r}\n"
            f"  Check whether PLAYER / POS / OVR column names changed.",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=PARSE_FAILED,
                reason="no_rows_extracted",
                detail=f"csv header: {first_line!r}",
                observed_at=_now(),
            ),
            status_path,
        )

    # Hard floor aligned with the downstream contract guard
    # ``_DEFAULT_SOURCE_ROW_FLOORS["idpShow"]`` (150).  Previously a
    # WARN at <100 that still wrote the CSV — a partial scrape (e.g. a
    # republished/truncated Datawrapper chart) overwrote the last-good
    # board and silently shipped a CSV that then hard-failed the
    # contract-coverage test on a clean checkout.  Fail loudly and
    # preserve last-good instead.  Skipped under --dry-run so the
    # sample below still prints for diagnosis.
    _IDPSHOW_ROW_FLOOR = 150
    if not args.dry_run and len(rows) < _IDPSHOW_ROW_FLOOR:
        print(
            f"[idpshow] ERROR: only {len(rows)} rows — expected ≥"
            f"{_IDPSHOW_ROW_FLOOR} (contract floor "
            f"_DEFAULT_SOURCE_ROW_FLOORS['idpShow']).  Partial/degraded "
            f"scrape; preserving last-good CSV, not overwriting.",
            file=sys.stderr,
        )
        return _persist_outcome(
            AcquisitionOutcome(
                source_key=source_key,
                state=SCHEMA_CHANGED,
                reason="row_count_below_floor",
                detail=f"{len(rows)} rows parsed, floor is {_IDPSHOW_ROW_FLOOR}",
                observed_at=_now(),
            ),
            status_path,
        )

    if args.dry_run:
        print("[idpshow] dry-run — top 5:")
        for r in rows[:5]:
            print(f"  #{r['rank']:<4} {r['position']:<4} {r['name']}")
        # Deliberately not persisted: a dry-run writes no CSV, so recording
        # HEALTHY here would claim an acquisition that didn't happen.
        return 0

    count = _write_csv(out_path, rows)
    print(f"[idpshow] wrote {count} rows → {_rel(out_path)}")
    return _persist_outcome(
        AcquisitionOutcome(
            source_key=source_key,
            state=HEALTHY,
            row_count=count,
            observed_at=_now(),
        ),
        status_path,
    )


if __name__ == "__main__":
    raise SystemExit(main())
