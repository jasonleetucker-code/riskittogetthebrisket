"""Point-in-time league FORMAT captures for our OWN registered leagues, per season.

WHY THIS EXISTS
───────────────
The completed-trade ledger's own-league lane used to classify EVERY own-league
trade with TODAY's format: the registry entry plus the current scoring card
(``market_trade_format.format_from_registry``).  Sleeper chains a dynasty league
year to year under a NEW league id (``previous_league_id``), and each season's
league carries its own roster slots, team count and scoring card.  Measured on
the public chains (2026-10-01):

* ``dynasty_main`` 2025 had 10 teams (12 today), different roster slots and
  ``bonus_rec_te`` 0.35 (0 today) — 32 scoring keys differ, 57 for 2024;
* ``dynasty_new``'s ``bonus_rec_te`` 0.5 exists only from 2026, and its slots
  differed before 2025.

So a 2024 trade was being certified NATIVE_COMPARABLE against a format nobody
played in 2024.  Those own-league trades were the ONLY native population in the
ledger (183 trades, 48 IDP).

WHAT THIS OWNS
──────────────
"Which Sleeper league (id + season) did each season of an own registered league
run under, and what format did we observe it in, when."  Two tables in a small
box-local SQLite store (:func:`default_path`, beside the per-league scoring
snapshots in ``data/leagues/``, gitignored):

* ``own_league_season_chain`` — one row per ``(league_key, league_id)``: the
  season-league's own ``season`` and ``previous_league_id``.  A chain link is an
  immutable fact, so rows are ``INSERT OR IGNORE`` only;
* the capture tables of the Sharp league-format capture owner
  (``src/sharp/league_format_capture.py``), REUSED rather than re-invented:
  ``record_capture`` (append-only, dated, a row only when the payload differs
  from the capture in force), ``load_capture_index`` and ``capture_in_force``
  (the nearest-prior / post-trade / time-unknown rule) are called as-is.  Own
  leagues are just Sleeper leagues, so the stored payload and the format read
  back from it (``format_from_sleeper_league``) are identical to the Sharp lane.

Why a separate file instead of the intel ledger's capture table: the intel
ledger's retention pass (``prune_captures``) keeps a capture only while a trade
IN THE INTEL LEDGER needs it or the league is still being checked.  A completed
own-league season is captured once and never re-checked, and its trades live in
the acquisition store, not the intel ledger — so it would be pruned after the
movement horizon.  Own-league history is a handful of rows (a few leagues x a
few seasons) and is kept indefinitely.  (The reused check table keeps its
``sharp_`` name inside this file; it is the capture owner's schema, not a
claim that these are Sharp leagues.)

FETCH POLICY
────────────
:func:`refresh_own_league_formats` walks the chain from the registry's current
league with the public, unauthenticated Sleeper ``GET /v1/league/{id}``
(``sleeper_client.request_json_classified``: a 429 stops the walk and is never
read as a deleted league), bounded by :data:`MAX_CHAIN_HOPS` calls.  A
season-league whose last observed status is ``complete`` and which already has
a capture and a chain row is NOT re-fetched — its stored ``previous_league_id``
is followed instead — so steady state is ONE request per league per run (the
current season).  It runs as the third pass of the Sharp transaction-crawl
timer (``scripts/crawl_sharp_transactions.py``, after the Sharp format pass),
so it shares that timer's slot on the box's public IP and the current season
accumulates dated captures 4x/day; ``scripts/capture_own_league_formats.py``
runs it by hand.  Deliberately NOT in ``server.py``: nothing on the serving
path may import a format-capture owner (pinned by
``tests/sharp/test_league_format_capture.py``).

POINT-IN-TIME RULE (decided in ``market_trade_normalize._own_league_format``)
─────────────────────────────────────────────────────────────────────────────
A capture describes a trade exactly only when it was taken AT OR BEFORE the
trade.  A completed season's settings fetched now are the BEST AVAILABLE
evidence for that season (``season_league_settings``) — Sleeper settings are
frozen once a league completes — but they are not proof of the settings at
trade time, because a mid-season change is unknowable from a later fetch.  So
they are published as ``post_trade_capture`` evidence and the ledger's timing
cap holds them below NATIVE_COMPARABLE.  NATIVE remains for trades whose format
evidence is dated at or before the trade.

WHAT THIS DOES NOT DO
─────────────────────
It computes no format axis (``market_trade_format`` does, through the canonical
slot / scoring / TE owners), touches no value, and never runs inside a request.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from src.sharp import league_format_capture as lfc

log = logging.getLogger(__name__)

#: Capture provenance written into the reused capture table.
SOURCE_OWN_LEAGUE_CHAIN = "own_league_season_chain_league_endpoint"

#: Env override for the store path (tests, alternate deploys).
_PATH_ENV = "RISKIT_OWN_LEAGUE_FORMAT_DB"
_FILE_NAME = "own_league_format_captures.sqlite"

#: Upper bound on chain hops — and so on requests per league per run.  Same
#: bound ``league_comparison.season_scoring`` uses for the same walk.
MAX_CHAIN_HOPS = 12

_CHAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS own_league_season_chain (
  league_key          TEXT NOT NULL,
  league_id           TEXT NOT NULL,
  season              TEXT,
  previous_league_id  TEXT,
  first_seen_ms       INTEGER NOT NULL,
  PRIMARY KEY (league_key, league_id)
);
"""

#: Tables this module writes (the capture owner's three plus the chain).
WRITE_TABLES = (*lfc.WRITE_TABLES, "own_league_season_chain")


def default_path() -> Path:
    override = os.getenv(_PATH_ENV, "").strip()
    if override:
        return Path(override)
    from src.api import league_registry  # noqa: PLC0415

    return league_registry.scoring_snapshot_dir() / _FILE_NAME


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open (creating) the store and ensure its schema.  Writers only."""
    p = Path(path) if path is not None else default_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=30)
    conn.executescript(_CHAIN_SCHEMA)
    lfc.ensure_schema(conn)
    conn.commit()
    return conn


def _clean_id(value: Any) -> str | None:
    text = str(value or "").strip()
    # Sleeper terminates a chain with the STRING "0" (see src/sharp/records.py).
    return text if text and text != "0" else None


@dataclass
class OwnLeagueFormatRefresh:
    league_key: str
    root_league_id: str | None
    leagues_walked: int = 0
    leagues_fetched: int = 0
    captures_new: int = 0
    captures_unchanged: int = 0
    skipped_frozen: int = 0
    stopped_reason: str | None = None
    outcomes: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "leagueKey": self.league_key,
            "rootLeagueId": self.root_league_id,
            "leaguesWalked": self.leagues_walked,
            "leaguesFetched": self.leagues_fetched,
            "capturesNew": self.captures_new,
            "capturesUnchanged": self.captures_unchanged,
            "skippedFrozen": self.skipped_frozen,
            "stoppedReason": self.stopped_reason,
            "outcomes": dict(self.outcomes),
        }


def _default_http_get(url: str) -> Any:
    """Same classified fetcher the Sharp capture pass uses: payload, ``None``
    for a league that does not exist, ``lfc.FETCH_ERROR`` for a transport
    failure, ``lfc.RateLimited`` raised on a 429."""
    return lfc._default_http_get(url)


def refresh_own_league_formats(
    league_key: str,
    *,
    root_league_id: str | None = None,
    path: Path | None = None,
    http_get: Callable[[str], Any] | None = None,
    clock_ms: Callable[[], int] | None = None,
    max_hops: int = MAX_CHAIN_HOPS,
    sleep_s: float = 0.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> OwnLeagueFormatRefresh:
    """Walk one registry league's ``previous_league_id`` chain and record each
    season-league's format, dated, append-only.  Never raises on a fetch
    failure (the walk stops and says why); commits per league so the writer
    lock is never held across network I/O.

    ``root_league_id`` defaults to the registry's current Sleeper league id.
    """
    if root_league_id is None:
        from src.api import league_registry  # noqa: PLC0415

        cfg = league_registry.get_league_by_key(league_key)
        root_league_id = getattr(cfg, "sleeper_league_id", None) if cfg is not None else None
    result = OwnLeagueFormatRefresh(league_key=league_key, root_league_id=_clean_id(root_league_id))
    if result.root_league_id is None:
        result.stopped_reason = "no_root_league_id"
        return result
    fetch = http_get or _default_http_get
    tick = clock_ms or (lambda: int(time.time() * 1000))
    conn = connect(path)
    try:
        chain = {
            str(r[0]): (r[1], r[2])
            for r in conn.execute(
                "SELECT league_id, season, previous_league_id FROM own_league_season_chain "
                "WHERE league_key = ?",
                (league_key,),
            ).fetchall()
        }
        checks = {
            str(r[0]): (r[1] or "")
            for r in conn.execute(
                "SELECT league_id, last_status FROM sharp_league_format_checks"
            ).fetchall()
        }
        captured = {
            str(r[0])
            for r in conn.execute(
                "SELECT DISTINCT league_id FROM sharp_league_format_captures"
            ).fetchall()
        }
        seen: set[str] = set()
        current: str | None = result.root_league_id
        fetches = 0
        while current and current not in seen and result.leagues_walked < max_hops:
            seen.add(current)
            result.leagues_walked += 1
            frozen = (
                current in chain
                and current in captured
                and str(checks.get(current, "")).lower() == "complete"
            )
            if frozen:
                # A completed season's settings no longer move; follow the
                # stored link instead of spending a request.
                result.skipped_frozen += 1
                result.outcomes[current] = "frozen_complete"
                current = _clean_id(chain[current][1])
                continue
            if fetches and sleep_s:
                sleep_fn(sleep_s)
            try:
                league = fetch(f"{lfc.SLEEPER_BASE}/league/{current}")
            except lfc.RateLimited:
                result.stopped_reason = "rate_limited"
                result.outcomes[current] = "rate_limited"
                break
            fetches += 1
            result.leagues_fetched += 1
            if league is lfc.FETCH_ERROR or (league is not None and not isinstance(league, dict)):
                result.stopped_reason = "fetch_failed"
                result.outcomes[current] = "fetch_failed"
                break
            if league is None:
                result.stopped_reason = "league_not_found"
                result.outcomes[current] = "not_found"
                break
            if _clean_id(league.get("league_id")) not in (None, current):
                result.stopped_reason = "league_id_mismatch"
                result.outcomes[current] = "league_id_mismatch"
                break
            outcome = lfc.record_capture(
                conn,
                league,
                captured_ms=tick(),
                source=SOURCE_OWN_LEAGUE_CHAIN,
                league_id=current,
            )
            result.outcomes[current] = outcome
            if outcome == "new":
                result.captures_new += 1
            elif outcome == "unchanged":
                result.captures_unchanged += 1
            season = str(league.get("season") or "").strip() or None
            prev = _clean_id(league.get("previous_league_id") or league.get("previous_league"))
            conn.execute(
                "INSERT OR IGNORE INTO own_league_season_chain "
                "(league_key, league_id, season, previous_league_id, first_seen_ms) "
                "VALUES (?, ?, ?, ?, ?)",
                (league_key, current, season, prev, tick()),
            )
            conn.commit()
            current = prev
        conn.commit()
    finally:
        conn.close()
    log.info("own_league_format_capture: %s", result.to_dict())
    return result


# ── read side (the trade ledger, read-only) ──────────────────────────────


@dataclass(frozen=True)
class OwnLeagueFormatIndex:
    """Everything the ledger needs, read once per build."""

    #: ``{league_id: [capture, ...]}`` oldest-first (``lfc.load_capture_index``).
    captures: Mapping[str, list[dict[str, Any]]]
    #: ``{league_key: {season: league_id}}``.
    seasons: Mapping[str, Mapping[str, str]]
    state: str

    def league_for_season(self, league_key: str, season: Any) -> str | None:
        if season is None:
            return None
        return (self.seasons.get(league_key) or {}).get(str(season).strip())


EMPTY_INDEX = OwnLeagueFormatIndex(captures={}, seasons={}, state="not_loaded")


def load_index(path: Path | None = None) -> OwnLeagueFormatIndex:
    """Read the store through a ``mode=ro`` connection — never creating or
    migrating it.  A missing store is a STATE (every own-league trade then has
    no season-league format), never an error."""
    p = Path(path) if path is not None else default_path()
    if not p.exists():
        return OwnLeagueFormatIndex(
            captures={}, seasons={}, state="own_league_format_store_missing"
        )
    try:
        conn = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True)
        try:
            captures = lfc.load_capture_index(conn)
            try:
                rows = conn.execute(
                    "SELECT league_key, league_id, season FROM own_league_season_chain"
                ).fetchall()
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
                    raise
                rows = []
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        return OwnLeagueFormatIndex(
            captures={}, seasons={}, state=f"own_league_format_store_unreadable:{exc}"
        )
    seasons: dict[str, dict[str, str]] = {}
    for key, lid, season in rows:
        if key and lid and season:
            # One league per season in a well-formed chain; first writer wins
            # on a malformed one rather than silently swapping.
            seasons.setdefault(str(key), {}).setdefault(str(season), str(lid))
    return OwnLeagueFormatIndex(
        captures=captures,
        seasons=seasons,
        state="available" if captures else "no_captures",
    )
