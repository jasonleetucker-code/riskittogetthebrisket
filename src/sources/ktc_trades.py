"""KeepTradeCut Trade Database — the source adapter (C4-MTL-02, KTC lane).

Authorization: owner decision 2026-09-30 (#1555), recorded in
``docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md`` header and §19.2 — the
owner holds KTC's permission to collect all KTC data.  That grant does not
waive request hygiene: this adapter reads ONE public page per run, never
follows a redirect, honours Retry-After, and a 401/403/challenge PERSISTS a
stop that later runs obey until an operator clears it.

WHAT THE SURFACE ACTUALLY IS — measured 2026-10-01
──────────────────────────────────────────────────
``GET https://keeptradecut.com/dynasty/trade-database`` (robots.txt allows
it) returns HTML with the data INLINE, the same pattern as the waiver
database ``scripts/fetch_crowd_faab.py`` already reads:

* ``var trades = [...]`` — the most recent 200 completed trades, every
  format mixed (1QB and SF, TEP 0-3, 8-16 and 96 teams).  Each row:
  ``id`` (int, KTC-native), ``date`` (``YYYY-MM-DDT00:00:00`` — DAY
  granularity only), ``teamOne`` / ``teamTwo`` (``playerIds`` list of KTC
  ids or literal pick labels, ``place``, ``isVftFavored``), ``settings``
  (``id`` = the HOST league id, ``dynastyPlatformType`` 1/2, ``teams``,
  ``qBs``, ``ppr``, ``tep``, ``is2TE``, ``passTDPoints``,
  ``leagueStartingLineup``, ``rostersPerPlayer``, ``leagueUrl``,
  ``leagueYear``) and ``isUsedInVft`` (whether KTC's own trade-derived
  value — KTC Trades — consumed the row).
* ``var allPlayerSearchValues = [...]`` — the id -> name/position index
  (``src.sources.ktc_identity`` is its one owner).
* ``tradeInsights`` / ``lastProcessedTimes`` — aggregates; not archived.

The site's own "all trades" XHR (``POST /dynasty/trade-database/trades``)
answered **403** to a plain request on 2026-10-01.  Per the stop rule we did
not retry it with cookies, tokens or a spoofed referer; this adapter does not
call it.  History depth is therefore the 200-row rolling window — a single
fetch is a snapshot, so the archive ACCUMULATES (``market_trade_archive``).

WHAT THIS MODULE DOES NOT DO
────────────────────────────
It resolves no identity beyond recording the vendor's own index, groups
nothing and values nothing.  It is evidence capture.  Raw trades never move a
canonical value (spec §3, §18).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from src.sources.signals import (
    BodyTooLarge,
    HttpGet,
    _redirect_is_access_wall,
    _retry_after_seconds,
    atomic_write_bytes,
    atomic_write_json,
    urllib_get,
)
from src.sources.ktc_identity import search_index_rows
from src.trade import market_trade_archive as archive

SOURCE_FAMILY = "ktc_trade_database"
TRADE_DB_URL = "https://keeptradecut.com/dynasty/trade-database"
PARSER_VERSION = "ktc-trade-db-inline-v1"
USER_AGENT = "Mozilla/5.0 (compatible; riskittogetthebrisket/1.0; trade-ledger)"
HTTP_TIMEOUT_SECONDS = 60
TRANSIENT_BACKOFF_SECONDS = (5.0, 20.0)
MAX_RETRY_AFTER_SECONDS = 300

#: KTC's dynasty trade database is a DYNASTY surface by URL and page title;
#: the per-row ``dynastyPlatformType`` names the HOST platform, not the game
#: type.  So dynasty status is a SOURCE-LEVEL claim, stamped as such — the
#: same posture ``faab_comparability.DYNASTY_PROVENANCE_SOURCE_LEVEL`` takes
#: for the sibling waiver database.
DYNASTY_PROVENANCE = "source_level_claim:ktc_dynasty_trade_database"

#: Host platform codes as MEASURED from ``settings.leagueUrl`` on the live
#: feed (2026-10-01): every type-2 row links sleeper.app, every type-1 row
#: links myfantasyleague.com.  The URL is still checked per row; an unknown
#: code with no recognisable URL is ``unknown``, never a guess.
_PLATFORM_BY_HOST = (
    ("sleeper.app", "sleeper"),
    ("myfantasyleague.com", "mfl"),
    ("fleaflicker.com", "fleaflicker"),
    ("fantrax.com", "fantrax"),
    ("espn.com", "espn"),
)

_TRADES_RE = re.compile(r"var\s+trades\s*=\s*(\[.*?\]);", re.DOTALL)

#: Strings that mark an anti-bot interstitial rather than the page.  Seeing
#: one is an ACCESS stop, not a parse failure: retrying would be an attempt
#: to get past it.
_CHALLENGE_MARKERS = (
    "cf-challenge",
    "challenge-platform",
    "captcha",
    "just a moment...",
    "attention required!",
)

#: A parse that yields far fewer rows than the window size is suspicious but
#: not fatal; ZERO rows from a page that otherwise loaded is a schema-drift
#: quarantine.
EXPECTED_WINDOW = 200

#: Consecutive quarantined (schema-drift) fetches after which collection
#: STOPS rather than writing another raw page to the quarantine every run.
#: One drifted page is evidence worth keeping; the same drift re-fetched every
#: 30 minutes is a disk leak on a near-full box.  The stop persists like an
#: access stop and is cleared the same way (``--clear-stop``).
MAX_CONSECUTIVE_QUARANTINES = 3
STOP_REASON_SCHEMA_DRIFT = "schema_drift_repeated"


# ── Parsing ───────────────────────────────────────────────────────────────


@dataclass
class ParsedTradePage:
    trades: list[dict[str, Any]] = field(default_factory=list)
    identity_rows: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _json_array(match: re.Match[str] | None) -> list[Any] | None:
    if match is None:
        return None
    try:
        value = json.loads(match.group(1))
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) else None


def _valid_trade_row(row: Any) -> str | None:
    """Return a rejection reason, or ``None`` when the row is usable evidence."""
    if not isinstance(row, dict):
        return "not_an_object"
    if row.get("id") is None or str(row.get("id")).strip() == "":
        return "missing_id"
    for side in ("teamOne", "teamTwo"):
        block = row.get(side)
        if not isinstance(block, dict) or not isinstance(block.get("playerIds"), list):
            return f"missing_{side}_playerIds"
    if not isinstance(row.get("settings"), dict):
        return "missing_settings"
    return None


def parse_trade_page(html: str) -> ParsedTradePage:
    """Extract trade rows and the identity index from one page.

    Rows are kept VERBATIM (they are archived as the source said them);
    only structurally unusable rows are dropped, and every drop is counted.
    """
    page = ParsedTradePage()
    trades = _json_array(_TRADES_RE.search(html or ""))
    if trades is None:
        page.errors.append("trades_array_missing_or_unparseable")
        return page
    rejected: dict[str, int] = {}
    for row in trades:
        reason = _valid_trade_row(row)
        if reason is not None:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        page.trades.append(row)
    if rejected:
        page.warnings.append(
            "rows_rejected:" + ",".join(f"{k}={v}" for k, v in sorted(rejected.items()))
        )
    if trades and not page.trades:
        page.errors.append("every_trade_row_rejected")
    if not trades:
        page.errors.append("trades_array_empty")

    # Identity rows come from the ONE owner of KTC id -> identity.
    page.identity_rows, _ = search_index_rows(html or "")
    if not page.identity_rows:
        # Not fatal for ARCHIVING (the trade rows are still true), but every
        # numeric reference will be unresolvable until a later fetch supplies
        # an index — named, never silently absorbed.
        page.warnings.append("identity_index_missing")
    if page.trades and len(page.trades) < EXPECTED_WINDOW // 4:
        page.warnings.append(f"window_unusually_small:{len(page.trades)}")
    return page


def looks_like_challenge(body_text: str) -> bool:
    lowered = (body_text or "")[:20000].lower()
    return any(marker in lowered for marker in _CHALLENGE_MARKERS)


def host_platform(settings: Mapping[str, Any] | None) -> str:
    """``sleeper`` / ``mfl`` / ... from the row's own league URL, else ``unknown``."""
    url = str((settings or {}).get("leagueUrl") or "").lower()
    for host, name in _PLATFORM_BY_HOST:
        if host in url:
            return name
    return "unknown"


def observed_date(row: Mapping[str, Any]) -> str | None:
    """The vendor's trade DATE (``YYYY-MM-DD``), or ``None`` if unreadable."""
    raw = str(row.get("date") or "").strip()
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", raw)
    return m.group(1) if m else None


# ── Store state (box-local, beside the archive) ──────────────────────────


def state_path(root: Path | None = None) -> Path:
    base = Path(root) if root is not None else Path(archive.DEFAULT_DIR)
    return base / "ktc_fetch_state.json"


def load_state(root: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: Mapping[str, Any], root: Path | None = None) -> None:
    atomic_write_json(state_path(root), dict(state))


def _quarantine(root: Path | None, raw_sha: str, body: bytes, record: Mapping[str, Any]) -> None:
    import gzip  # noqa: PLC0415

    base = (Path(root) if root is not None else Path(archive.DEFAULT_DIR)) / "quarantine" / "ktc"
    target = base / f"{raw_sha}.html.gz"
    if not target.exists():
        atomic_write_bytes(target, gzip.compress(body, mtime=0))
    atomic_write_json(base / f"{raw_sha}.json", dict(record))


# ── Collection ────────────────────────────────────────────────────────────


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(text: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None


def collect(
    *,
    root: Path | None = None,
    archive_path: Path | None = None,
    http: HttpGet = urllib_get,
    now: Callable[[], datetime] = utc_now,
    sleep: Callable[[float], None] = time.sleep,
    min_interval_minutes: float | None = None,
    force: bool = False,
    url: str = TRADE_DB_URL,
) -> dict[str, Any]:
    """Fetch the page once and archive what it says.  Never raises for HTTP or
    parse failures — they are outcomes:

    ``archived`` · ``not_modified`` · ``quarantined`` · ``skipped_recent`` ·
    ``auth_stopped`` · ``stopped`` · ``rate_limited`` · ``fetch_failed``
    """
    state = load_state(root)
    started = now()
    outcome: dict[str, Any] = {"sourceFamily": SOURCE_FAMILY, "url": url}

    # ``force`` bypasses ONLY the min interval.  A persisted stop (401/403,
    # access-wall redirect, challenge page, repeated schema drift) is an
    # operator decision; only ``clear_stop`` (``--clear-stop``) lifts it.
    if state.get("stoppedAt"):
        outcome.update(
            outcome="stopped",
            reason=f"collection stopped at {state['stoppedAt']} ({state.get('stopReason')}); "
            "clear with --clear-stop after resolving access",
        )
        return outcome
    last = _parse_iso(state.get("lastAttemptAt"))
    if (
        min_interval_minutes
        and not force
        and last is not None
        and (started - last).total_seconds() < min_interval_minutes * 60
    ):
        outcome.update(outcome="skipped_recent", lastAttemptAt=state.get("lastAttemptAt"))
        return outcome

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html", "Accept-Encoding": "gzip"}
    # Conditional GET only once something has been archived — a validator
    # without the content it validates would 304 us into having nothing.
    if state.get("lastArchivedAt"):
        if state.get("etag"):
            headers["If-None-Match"] = state["etag"]
        if state.get("lastModified"):
            headers["If-Modified-Since"] = state["lastModified"]

    status: int | None = None
    resp_headers: dict[str, str] = {}
    body = b""
    transient = 0
    rate = 0
    err: str | None = None
    while True:
        try:
            status, resp_headers, body = http(url, headers, HTTP_TIMEOUT_SECONDS)
            err = None
        except BodyTooLarge as exc:
            outcome.update(outcome="fetch_failed", reason=f"oversize: {exc}")
            break
        except OSError as exc:
            status, resp_headers, body = None, {}, b""
            err = f"transport: {exc}"
        if status == 429:
            wait = _retry_after_seconds(resp_headers.get("retry-after"), now())
            if wait is None:
                wait = TRANSIENT_BACKOFF_SECONDS[min(rate, len(TRANSIENT_BACKOFF_SECONDS) - 1)]
            if rate >= 2 or wait > MAX_RETRY_AFTER_SECONDS:
                outcome.update(outcome="rate_limited", retryAfterSeconds=wait)
                break
            rate += 1
            sleep(wait)
            continue
        if status is None or status >= 500:
            if transient < len(TRANSIENT_BACKOFF_SECONDS):
                sleep(TRANSIENT_BACKOFF_SECONDS[transient])
                transient += 1
                continue
            outcome.update(outcome="fetch_failed", reason=err or f"HTTP {status}")
            break
        break

    at = now()
    fetched_at = _iso(at)
    fetch_id = f"ktc:{fetched_at}"
    state["lastAttemptAt"] = fetched_at
    state["parserVersion"] = PARSER_VERSION

    if outcome.get("outcome") in ("rate_limited", "fetch_failed"):
        pass
    elif status in (401, 403):
        state["stoppedAt"] = fetched_at
        state["stopReason"] = f"HTTP {status}"
        outcome.update(outcome="auth_stopped", httpStatus=status)
    elif status is not None and 300 <= status < 400 and status != 304:
        if _redirect_is_access_wall(url, resp_headers.get("location")):
            state["stoppedAt"] = fetched_at
            state["stopReason"] = f"HTTP {status} redirect to an access wall or another origin"
            outcome.update(outcome="auth_stopped", httpStatus=status)
        else:
            outcome.update(outcome="fetch_failed", reason=f"HTTP {status} redirect not followed")
    elif status == 304:
        outcome.update(outcome="not_modified")
    elif status != 200:
        outcome.update(outcome="fetch_failed", reason=f"HTTP {status}")
    else:
        text = body.decode("utf-8", errors="replace")
        raw_sha = hashlib.sha256(body).hexdigest()
        page = parse_trade_page(text)
        if page.errors and looks_like_challenge(text):
            state["stoppedAt"] = fetched_at
            state["stopReason"] = "anti-bot challenge page"
            outcome.update(outcome="auth_stopped", httpStatus=status, reason="challenge_page")
        elif page.errors:
            _quarantine(
                root,
                raw_sha,
                body,
                {
                    "quarantinedAt": fetched_at,
                    "rawSha256": raw_sha,
                    "parserVersion": PARSER_VERSION,
                    "errors": page.errors,
                    "warnings": page.warnings,
                },
            )
            outcome.update(outcome="quarantined", errors=page.errors, rawSha256=raw_sha)
            prior_q = state.get("consecutiveQuarantines")
            n_q = (prior_q if isinstance(prior_q, int) else 0) + 1
            state["consecutiveQuarantines"] = n_q
            outcome["consecutiveQuarantines"] = n_q
            if n_q >= MAX_CONSECUTIVE_QUARANTINES:
                state["stoppedAt"] = fetched_at
                state["stopReason"] = STOP_REASON_SCHEMA_DRIFT
                outcome["stopped"] = True
                outcome["reason"] = (
                    f"{n_q} consecutive quarantined fetches; collection stopped "
                    f"({STOP_REASON_SCHEMA_DRIFT}) until the parser is fixed and "
                    "--clear-stop is run"
                )
        else:
            observations = [
                archive.RawObservation(
                    source_native_id=str(row["id"]),
                    payload=row,
                    observed_date=observed_date(row),
                )
                for row in page.trades
            ]
            dates = sorted(d for d in (o.observed_date for o in observations) if d)
            ids = sorted(
                int(o.source_native_id) for o in observations if o.source_native_id.isdigit()
            )
            write = archive.record_fetch(
                archive.FetchRecord(
                    fetch_id=fetch_id,
                    source_family=SOURCE_FAMILY,
                    fetched_at=fetched_at,
                    outcome="archived",
                    url=url,
                    http_status=status,
                    raw_sha256=raw_sha,
                    parser_version=PARSER_VERSION,
                    detail={
                        "warnings": page.warnings,
                        "identityRows": len(page.identity_rows),
                        "windowMinDate": dates[0] if dates else None,
                        "windowMaxDate": dates[-1] if dates else None,
                        "windowMinId": ids[0] if ids else None,
                        "windowMaxId": ids[-1] if ids else None,
                    },
                ),
                observations,
                identity_entries=page.identity_rows,
                path=archive_path,
            )
            state["etag"] = resp_headers.get("etag")
            state["lastModified"] = resp_headers.get("last-modified")
            state["lastArchivedAt"] = fetched_at
            outcome.update(
                outcome="archived",
                httpStatus=status,
                rawSha256=raw_sha,
                warnings=page.warnings,
                windowMinDate=dates[0] if dates else None,
                windowMaxDate=dates[-1] if dates else None,
                **write.to_dict(),
            )
            if write.turnover_suspected:
                outcome["warning"] = (
                    "no overlap with previously archived rows — the 200-row window turned "
                    "over completely between runs and trades were probably missed; tighten "
                    "the timer cadence"
                )

    state["lastOutcome"] = outcome.get("outcome")
    if outcome.get("outcome") in ("archived", "not_modified"):
        state["consecutiveFailures"] = 0
        state["consecutiveQuarantines"] = 0
    else:
        prior = state.get("consecutiveFailures")
        state["consecutiveFailures"] = (prior if isinstance(prior, int) else 0) + 1
    save_state(state, root)
    return outcome


def clear_stop(root: Path | None = None) -> bool:
    state = load_state(root)
    if not state.get("stoppedAt"):
        return False
    state.pop("stoppedAt", None)
    state.pop("stopReason", None)
    state.pop("consecutiveQuarantines", None)
    save_state(state, root)
    return True
