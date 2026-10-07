"""Scheduled refresh + freshness for automated slates (DFS-AUTO-04/07/08/12).

The scheduler (``dynasty-dfs-auto-refresh`` timer → ``scripts/refresh_dfs_auto_slates.py``)
wakes every 10 minutes; THIS module decides whether anything is due, from how
close the nearest unlocked slate is to lock:

* more than 24 h to lock → every 2 h
* 3–24 h → every 30 min
* under 3 h → every 10 min
* locked → not refreshed (salaries are frozen; late-swap reads what was held)

Every successful build is stored under the ``system:auto`` namespace as an
ordinary immutable slate snapshot and recorded in the point-in-time ledger.  An
unchanged build (same content hash) creates nothing new — it only advances the
"last checked" clock.  A failed source never erases the last good slate; the
slate keeps its data and says ``SOURCE_ERROR`` with the reason.

Freshness states, per slate (``freshness()``):

* ``CURRENT`` — checked within its cadence;
* ``AGING`` — within twice its cadence;
* ``STALE`` — older than that;
* ``DEGRADED`` — current, but a projection family or identity input was
  unavailable on the last build (the slate says which);
* ``SOURCE_ERROR`` — the last refresh attempt for its platform failed;
* ``UNAVAILABLE`` — nothing has ever been built (a list-level state).

Sports: NFL (``refresh_nfl`` — weekly, windows derived from the nflverse
schedule) and NBA / NHL (``refresh_daily`` — the dated slate Daily Fantasy Fuel
lists, timed by the ESPN scoreboard; DFS-AUTO-19).  One table, one cadence, one
freshness vocabulary for all of them; the ``week`` column holds the NFL week, or
the slate's Eastern date as ``YYYYMMDD`` for a daily sport (``periodKey``).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from src.dfs import pit, store
from src.dfs.auto import SYSTEM_OWNER, daily, nfl
from src.dfs.auto.common import body_hash
from src.dfs.auto.scoring_cards import CARDS

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dfs_auto_slates (
    auto_key TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    sport TEXT NOT NULL,
    season INTEGER NOT NULL,
    week INTEGER NOT NULL,
    slate_key TEXT NOT NULL,
    label TEXT NOT NULL,
    lock_at TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    built_at TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    degraded TEXT,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dfs_auto_runs (
    platform TEXT NOT NULL,
    sport TEXT NOT NULL,
    at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS dfs_auto_runs_at ON dfs_auto_runs(platform, sport, at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(store._db_path(), timeout=10)
    conn.executescript(_SCHEMA)
    return conn


def _now() -> datetime:
    """The clock (one seam, so tests never depend on the wall clock)."""
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(timezone.utc)


def cadence(lock_at: datetime, now: datetime) -> timedelta | None:
    """How often a slate locking at ``lock_at`` is refreshed; None once locked."""
    to_lock = lock_at - now
    if to_lock <= timedelta(0):
        return None
    if to_lock > timedelta(hours=24):
        return timedelta(hours=2)
    if to_lock > timedelta(hours=3):
        return timedelta(minutes=30)
    return timedelta(minutes=10)


#: Sports with an automatic path.
AUTO_SPORTS = ("nfl",) + daily.SPORTS
#: After an attempt that found nothing to build (offseason, an off day, a page
#: listing no slate yet) the next attempt waits this long; after a failure or an
#: ordinary success the timer's own 10-minute tick governs.
UNAVAILABLE_BACKOFF = timedelta(hours=1)
RETRY_BACKOFF = timedelta(minutes=10)


def derivation_note(sport: str) -> str:
    return nfl.DERIVATION_NOTE if sport == "nfl" else daily.derivation_note(sport)


def season_for(now: datetime) -> int:
    """The NFL season a date belongs to (Jan–Feb are the previous season's playoffs)."""
    return now.year if now.month >= 3 else now.year - 1


# ── freshness ────────────────────────────────────────────────────────────


def _last_run(conn: sqlite3.Connection, platform: str, sport: str) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT at, outcome, detail FROM dfs_auto_runs WHERE platform=? AND sport=? ORDER BY at DESC LIMIT 1",
        (platform, sport),
    ).fetchone()
    return (
        {"at": r[0], "outcome": r[1], "detail": json.loads(r[2]) if r[2] else None} if r else None
    )


def freshness(
    row: Mapping[str, Any], last_run: Mapping[str, Any] | None, now: datetime
) -> dict[str, Any]:
    lock = _parse(row["lock_at"])
    checked = _parse(row["checked_at"])
    age = now - checked
    cad = cadence(lock, now)
    locked = cad is None
    state = "CURRENT"
    if last_run and last_run["outcome"] == "source_error" and _parse(last_run["at"]) > checked:
        state = "SOURCE_ERROR"
    elif not locked and age > 2 * cad:
        state = "STALE"
    elif row.get("degraded"):
        state = "DEGRADED"
    elif not locked and age > cad:
        state = "AGING"
    return {
        "state": state,
        "locked": locked,
        "checkedAt": row["checked_at"],
        "builtAt": row["built_at"],
        "ageMinutes": round(age.total_seconds() / 60, 1),
        "cadenceMinutes": None if cad is None else int(cad.total_seconds() // 60),
        "degraded": json.loads(row["degraded"]) if row.get("degraded") else [],
        "lastRun": dict(last_run) if last_run else None,
    }


def list_slates(
    sport: str = "nfl", platform: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    now = now or _now()
    horizon = _iso(now - timedelta(hours=12))
    with _lock, _connect() as conn:
        q = "SELECT auto_key, platform, sport, season, week, slate_key, label, lock_at, snapshot_id, content_hash, built_at, checked_at, degraded, summary FROM dfs_auto_slates WHERE sport=? AND lock_at >= ?"
        args: list[Any] = [sport, horizon]
        if platform:
            q += " AND platform=?"
            args.append(platform)
        rows = conn.execute(q + " ORDER BY lock_at, platform, slate_key", args).fetchall()
        runs = {p: _last_run(conn, p, sport) for p in nfl.PLATFORMS}
    is_daily = sport in daily.SPORTS
    cols = (
        "auto_key", "platform", "sport", "season", "week", "slate_key", "label", "lock_at",
        "snapshot_id", "content_hash", "built_at", "checked_at", "degraded", "summary",
    )  # fmt: skip
    slates = []
    for r in rows:
        d = dict(zip(cols, r))
        slates.append(
            {
                "autoSlateId": d["auto_key"],
                "platform": d["platform"],
                "sport": d["sport"],
                "season": d["season"],
                "week": None if is_daily else d["week"],
                "slateDate": _period_date(d["week"]) if is_daily else None,
                "slateKey": d["slate_key"],
                "label": d["label"],
                "lockAt": d["lock_at"],
                "contentHash": d["content_hash"],
                "summary": json.loads(d["summary"]),
                "freshness": freshness(d, runs.get(d["platform"]), now),
            }
        )
    out = {
        "sport": sport,
        "state": "AVAILABLE" if slates else "UNAVAILABLE",
        "slates": slates,
        "lastRuns": {p: r for p, r in runs.items() if r},
        "derivationNote": derivation_note(sport),
        "asOf": _iso(now),
    }
    if not slates:
        reason = _nothing_built_reason(sport, runs)
        if reason:
            out["reason"] = reason
    return out


def _nothing_built_reason(sport: str, runs: Mapping[str, Any]) -> str | None:
    """Why a sport has no slate, in words, from the last runs (None = no run yet)."""
    outcomes = {(r or {}).get("outcome") for r in runs.values() if r}
    if not outcomes:
        return None
    label = sport.upper()
    if outcomes == {"unavailable"}:
        return (
            f"No {label} slate is listed right now (an off day, the offseason or preseason). "
            "Checked again hourly; the platform file still works under Advanced."
        )
    if "source_error" in outcomes:
        return (
            f"The last {label} refresh could not reach a source; it retries within 10 minutes. "
            "The platform file still works under Advanced."
        )
    return None


def _period_date(period: Any) -> str | None:
    s = str(period or "")
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def get_row(auto_key: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT snapshot_id, platform, sport, lock_at FROM dfs_auto_slates WHERE auto_key=?",
            (auto_key,),
        ).fetchone()
    return {"snapshotId": r[0], "platform": r[1], "sport": r[2], "lockAt": r[3]} if r else None


def is_due(sport: str = "nfl", now: datetime | None = None) -> bool:
    """True when no slate is stored yet, or any unlocked slate has outlived its cadence."""
    now = now or _now()
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT lock_at, checked_at FROM dfs_auto_slates WHERE sport=? AND lock_at > ?",
            (sport, _iso(now)),
        ).fetchall()
        last = [r for r in (_last_run(conn, p, sport) for p in nfl.PLATFORMS) if r]
    failed = [r for r in last if r["outcome"] != "ok"]
    if not rows:
        if not last:
            return True
        newest = max(last, key=lambda r: r["at"])
        return now - _parse(newest["at"]) >= _backoff(newest["outcome"])
    for lock_at, checked_at in rows:
        cad = cadence(_parse(lock_at), now)
        if cad is not None and now - _parse(checked_at) >= cad:
            return True
    # A failed platform retries at the shortest cadence rather than waiting 2 h.
    return any(now - _parse(r["at"]) >= _backoff(r["outcome"]) for r in failed)


def _backoff(outcome: str) -> timedelta:
    return UNAVAILABLE_BACKOFF if outcome == "unavailable" else RETRY_BACKOFF


# ── the refresh ──────────────────────────────────────────────────────────


def _record_run(platform: str, sport: str, at: str, outcome: str, detail: Any) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO dfs_auto_runs VALUES (?,?,?,?,?)",
            (platform, sport, at, outcome, json.dumps(detail, default=str)[:4000]),
        )


def _store_slate(platform: str, body: dict[str, Any], degraded: list[str], now: datetime) -> str:
    """Upsert one derived slate.  Returns ``created`` | ``unchanged``."""
    auto = body["auto"]
    sport = auto["sport"]
    key = auto["autoKey"]
    h = body_hash(body)
    athletes = body["athletes"]
    summary = {
        "games": len(auto["games"]),
        "players": len(athletes),
        "projected": sum(1 for a in athletes if a.get("projection") is not None),
        "sources": body["slate"]["provenance"]["sources"],
    }
    at = _iso(now)
    with _lock, _connect() as conn:
        prev = conn.execute(
            "SELECT content_hash FROM dfs_auto_slates WHERE auto_key=?", (key,)
        ).fetchone()
        if prev and prev[0] == h:
            conn.execute(
                "UPDATE dfs_auto_slates SET checked_at=?, degraded=?, summary=? WHERE auto_key=?",
                (at, json.dumps(degraded) if degraded else None, json.dumps(summary), key),
            )
            return "unchanged"
    meta = store.put_snapshot(SYSTEM_OWNER, body["ruleset"], h, body)
    pit.capture_snapshot(
        SYSTEM_OWNER,
        {
            "id": meta["id"],
            "ruleset": body["ruleset"],
            "contentHash": h,
            "createdAt": meta["createdAt"],
            "body": body,
        },
    )
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO dfs_auto_slates VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                key, platform, sport, auto["season"], auto["periodKey"], auto["slateKey"], body["label"],
                auto["lockAt"], meta["id"], h, at, at,
                json.dumps(degraded) if degraded else None, json.dumps(summary),
            ),
        )  # fmt: skip
    return "created"


def _sleeper_points(
    rows: list[Mapping[str, Any]] | None, platform: str, season: int, week: int, observed_at: str
) -> tuple[dict[str, dict[str, Any]] | None, dict[str, Any]]:
    if rows is None:
        return None, {"state": "unavailable"}
    from src.ros.sleeper_weekly_projections import build_weekly_observations

    batch = build_weekly_observations(
        rows,
        season=season,
        week=week,
        observed_at=observed_at,
        scoring_settings=CARDS[(platform, "nfl")],
    )
    points = {
        o.sleeper_player_id: {
            "points": round(o.league_scored_points, 2),
            "team": o.team,
            "uncovered": list(o.uncovered_scoring_keys),
        }
        for o in batch.observations
    }
    return points, {
        "state": "ok",
        "observedAt": observed_at,
        "accepted": len(points),
        "refused": dict(batch.refused),
        "scoringFingerprint": batch.scoring_fingerprint,
        "scoringCard": "unverified — see scoring_cards.VERIFICATION",
    }


Fetcher = Callable[..., Any]


def refresh_nfl(
    *,
    now: datetime | None = None,
    get_schedule: Fetcher,
    get_dff: Fetcher,
    get_sleeper_rows: Fetcher,
    get_directory: Fetcher,
    force: bool = False,
) -> dict[str, Any]:
    """One refresh pass.  Fetchers are injected (``scripts/refresh_dfs_auto_slates.py``
    wires the real ones; tests wire fixtures)."""
    now = now or _now()
    at = _iso(now)
    if not force and not is_due("nfl", now):
        return {"outcome": "not_due", "at": at}
    season = season_for(now)
    try:
        games = nfl.games_from_schedule(get_schedule(season), season)
    except Exception as exc:  # noqa: BLE001 - a failed source is a recorded state
        for p in nfl.PLATFORMS:
            _record_run(
                p, "nfl", at, "source_error", {"stage": "schedule", "error": str(exc)[:300]}
            )
        return {"outcome": "source_error", "stage": "schedule", "at": at}
    week = nfl.current_week(games, now)
    if week is None:
        for p in nfl.PLATFORMS:
            _record_run(
                p, "nfl", at, "unavailable", {"stage": "schedule", "reason": "no_upcoming_games"}
            )
        return {"outcome": "unavailable", "reason": "no_upcoming_games", "at": at}
    week_games = [g for g in games if g.week == week]
    slates = nfl.derive_slates(week_games)

    degraded: list[str] = []
    directory = None
    try:
        directory = get_directory()
    except Exception:  # noqa: BLE001
        directory = None
    index = None
    if directory:
        from src.identity.resolution import build_sleeper_index

        index = build_sleeper_index(directory)
    else:
        degraded.append("identity_directory_unavailable")
    try:
        sleeper = get_sleeper_rows(season, week)  # (rows, observed_at) or None
    except Exception:  # noqa: BLE001
        sleeper = None
    if sleeper is None:
        degraded.append("projection_family_unavailable:sleeper_rotowire")

    result: dict[str, Any] = {
        "outcome": "ok",
        "at": at,
        "season": season,
        "week": week,
        "platforms": {},
    }
    for platform in nfl.PLATFORMS:
        try:
            page = get_dff(platform)
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", type(exc).__name__)
            _record_run(
                platform, "nfl", at, "source_error", {"stage": "salaries", "error": str(code)}
            )
            result["platforms"][platform] = {"outcome": "source_error", "error": str(code)}
            result["outcome"] = "partial"
            continue
        points, sleeper_meta = _sleeper_points(
            sleeper[0] if sleeper else None, platform, season, week, sleeper[1] if sleeper else at
        )
        pool, report = nfl.build_pool(
            platform, page["rows"], week_games, sleeper_points=points,
            directory=directory, directory_index=index,
        )  # fmt: skip
        if not pool:
            _record_run(
                platform,
                "nfl",
                at,
                "source_error",
                {"stage": "salaries", "error": "SOURCE_EMPTY", "report": report.to_dict()},
            )
            result["platforms"][platform] = {"outcome": "source_error", "error": "SOURCE_EMPTY"}
            result["outcome"] = "partial"
            continue
        sources = {
            "builtAt": at,
            "salaries": {
                "source": "dailyfantasyfuel",
                "url": page.get("url"),
                "fetchedAt": page.get("fetchedAt"),
                "publishedAt": page.get("updatedAt"),
                "sha256": page.get("sha256"),
            },
            "schedule": {"source": "nflverse", "season": season, "week": week},
            "projections": {
                "dailyfantasyfuel": {"state": "ok", "publishedAt": page.get("updatedAt")},
                "sleeper_rotowire": sleeper_meta,
            },
            "identity": {"source": "sleeper_directory", "state": "ok" if index else "unavailable"},
            "status": {"source": "sleeper_directory+dailyfantasyfuel"},
        }
        outcomes = {}
        for sd in slates:
            body = nfl.slate_body(platform, sd, pool, report, sources)
            if body is not None:
                outcomes[sd.key] = _store_slate(platform, body, degraded, now)
        _record_run(platform, "nfl", at, "ok", {"slates": outcomes, "degraded": degraded})
        result["platforms"][platform] = {
            "outcome": "ok",
            "slates": outcomes,
            "pool": report.to_dict(),
        }
    return result


# ── NBA / NHL (DFS-AUTO-19) ──────────────────────────────────────────────


def _schedule_for(
    sport: str, days: list[str], cache: dict[str, Any], get_schedule: Fetcher
) -> tuple[list[Any], list[dict[str, Any]], list[str]]:
    """Games for the listed days (one fetch per day per pass), their provenance,
    and any per-day failure codes."""
    games: list[Any] = []
    meta: list[dict[str, Any]] = []
    errors: list[str] = []
    for day in days:
        if day not in cache:
            try:
                cache[day] = get_schedule(sport, day)
            except Exception as exc:  # noqa: BLE001 - a failed source is a recorded state
                cache[day] = exc
        got = cache[day]
        if isinstance(got, Exception):
            errors.append(str(getattr(got, "code", type(got).__name__)))
            continue
        games.extend(got.get("games") or [])
        meta.append(
            {
                "source": "espn_scoreboard",
                "date": day,
                "url": got.get("url"),
                "fetchedAt": got.get("fetchedAt"),
                "sha256": got.get("sha256"),
                "games": len(got.get("games") or []),
                "dropped": (got.get("dropped") or [])[:20],
            }
        )
    return games, meta, errors


def _daily_sources(
    at: str, page: Mapping[str, Any], sched_meta: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "builtAt": at,
        "salaries": {
            "source": "dailyfantasyfuel",
            "url": page.get("url"),
            "fetchedAt": page.get("fetchedAt"),
            "publishedAt": page.get("updatedAt"),
            "sha256": page.get("sha256"),
        },
        "schedule": sched_meta,
        "projections": {"dailyfantasyfuel": {"state": "ok", "publishedAt": page.get("updatedAt")}},
        "identity": {"source": "provider_scoped", "state": "not_available_for_sport"},
        "status": {"source": "dailyfantasyfuel"},
    }


def refresh_daily(
    sport: str,
    *,
    now: datetime | None = None,
    get_dff: Fetcher,
    get_schedule: Fetcher,
    force: bool = False,
) -> dict[str, Any]:
    """One refresh pass for a daily sport.  ``get_dff(sport, platform)`` returns a
    parsed DFF page (``live.get_daily_dff``); ``get_schedule(sport, day)`` returns
    ``{"games": [ScheduledGame], ...}`` (``live.get_daily_schedule``)."""
    if sport not in daily.SPORTS:
        raise ValueError(f"not a daily automatic sport: {sport!r}")
    now = now or _now()
    at = _iso(now)
    if not force and not is_due(sport, now):
        return {"outcome": "not_due", "sport": sport, "at": at}
    result: dict[str, Any] = {"outcome": "ok", "sport": sport, "at": at, "platforms": {}}
    cache: dict[str, Any] = {}
    seen: list[str] = []

    def done(platform: str, outcome: str, detail: dict[str, Any]) -> None:
        _record_run(platform, sport, at, outcome, detail)
        result["platforms"][platform] = {"outcome": outcome, **detail}
        seen.append(outcome)

    for platform in daily.PLATFORMS:
        try:
            page = get_dff(sport, platform)
        except Exception as exc:  # noqa: BLE001
            code = str(getattr(exc, "code", type(exc).__name__))
            done(platform, "source_error", {"stage": "salaries", "error": code})
            continue
        rows = page.get("rows") or []
        if not rows:
            done(platform, "unavailable", {"stage": "salaries", "reason": "no_slate_listed"})
            continue
        days = daily.slate_dates(rows)
        if not days:
            done(platform, "source_error", {"stage": "salaries", "error": "no_start_dates"})
            continue
        games, sched_meta, sched_errors = _schedule_for(sport, days, cache, get_schedule)
        if sched_errors and not games:
            err = ",".join(sorted(set(sched_errors)))
            done(platform, "source_error", {"stage": "schedule", "error": err})
            continue
        pool, report = daily.build_pool(sport, platform, rows, games)
        if not pool:
            # Every listed row was refused (e.g. a preseason page: those games are
            # not on the regular-season schedule) — nothing to build, not a crash.
            detail = {"stage": "pool", "reason": "no_listed_game_on_schedule"}
            done(platform, "unavailable", {**detail, "report": report.to_dict()})
            continue
        sources = _daily_sources(at, page, sched_meta)
        degraded = ["schedule_partial"] if sched_errors else []
        built: dict[str, str] = {}
        for day, slate_games in daily.slates(pool, games):
            that_day = sum(1 for g in games if g.date_et == day)
            body = daily.slate_body(
                sport, platform, day, slate_games, pool, report, sources, that_day
            )
            if body is not None:
                built[body["auto"]["autoKey"]] = _store_slate(platform, body, degraded, now)
        if not built:
            detail = {"stage": "slates", "reason": "fewer_than_two_games"}
            done(platform, "unavailable", {**detail, "report": report.to_dict()})
            continue
        done(platform, "ok", {"slates": built, "pool": report.to_dict()})
    if "source_error" in seen:
        result["outcome"] = "partial" if "ok" in seen else "source_error"
    elif "ok" not in seen:
        result["outcome"] = "unavailable"
    return result
