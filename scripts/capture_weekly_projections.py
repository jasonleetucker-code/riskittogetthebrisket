#!/usr/bin/env python3
"""Capture the FULL weekly projection pool, point-in-time (IDP streaming RET evidence).

For the current NFL week and the next ``--weeks-ahead`` weeks (and any
``--weeks`` named explicitly, e.g. fantasy-playoff weeks), fetch every weekly
projection source whose own feature flag is ON, and append its raw pool —
every position, free agents and placeholders included — to the gitignored
archive ``data/projections/weekly_archive/<season>/w<week>/<source>_<fetchedAt>.json.gz``
(:mod:`src.ros.weekly_projection_archive`), together with each league's
league-scored points keyed by scoring FINGERPRINT.

A projection captured after kickoff is not a pre-kickoff projection, so the
timer fires several times per week BEFORE games (Tue / Thu / Sat / Sun
morning, see ``deploy/systemd/dynasty-weekly-projection-capture.timer.template``).
An unchanged re-download is not written again (append-only, content-hashed).

Gate: ``weekly_projection_capture`` (registry default OFF; the production
service opts in with ``RISKIT_FEATURE_WEEKLY_PROJECTION_CAPTURE=1``).  Off →
exit 0 with ``feature_disabled`` and no network call.

Exit codes:
  0 — at least one source captured (written or unchanged) for the current
      week, or the gate is off;
  1 — no source produced usable data for the current week (every source
      unavailable / unpublished);
  2 — error (bad arguments, unreadable registry, unexpected exception).

Politeness: requests are sequential with at least ``--pause`` (default 1.5 s)
between them, and every source keeps its own User-Agent.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api.feature_flags import is_enabled  # noqa: E402
from src.ros import weekly_league_projections as wlp  # noqa: E402
from src.ros import weekly_projection_archive as archive  # noqa: E402

_STATE_URL = "https://api.sleeper.app/v1/state/nfl"
_USER_AGENT = "riskit-weekly-projections/1.0"


def _nfl_state() -> dict[str, Any]:
    req = urllib.request.Request(_STATE_URL, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310
        return json.loads(resp.read())


def _ms_to_iso(raw: Any) -> str | None:
    try:
        ms = float(raw)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def _raw_of(source_key: str, result: Any) -> tuple[Any, int, list[str | None]]:
    """``(raw payload to archive, row count, provider stamps)``."""
    if source_key == wlp.SLEEPER_SOURCE:
        rows = list(result.rows)
        stamps = [_ms_to_iso(r.get("updated_at") or r.get("last_modified")) for r in rows]
        return rows, len(rows), stamps
    payload = dict(result.payload or {})
    return payload, len(payload.get("players") or []), []


#: Fields that change on every render / re-stamp without new projections.
_VOLATILE_ROW_FIELDS = frozenset({"updated_at", "last_modified"})
_VOLATILE_ENVELOPE_FIELDS = frozenset({"generatedAt", "expiresAt"})


def _stable_content(source_key: str, raw: Any) -> Any:
    """What the archive's unchanged-check hashes (see record_capture)."""
    if source_key == wlp.SLEEPER_SOURCE:
        return [
            {k: v for k, v in r.items() if k not in _VOLATILE_ROW_FIELDS}
            if isinstance(r, dict)
            else r
            for r in raw
        ]
    return {k: v for k, v in raw.items() if k not in _VOLATILE_ENVELOPE_FIELDS}


def _has_content(source_key: str, result: Any) -> bool:
    if getattr(result, "status", None) != "ok":
        return False
    if source_key == wlp.SLEEPER_SOURCE:
        from src.ros.sleeper_weekly_projections import row_refusal_reason

        return any(
            row_refusal_reason(r, season=result.season, week=result.week) is None
            for r in result.rows
        )
    return bool((result.payload or {}).get("players"))


def _league_scored(
    league_keys: list[str],
    source_key: str,
    result: Any,
    season: int,
    week: int,
    identity_index: Any = None,
) -> dict[str, dict[str, Any]]:
    """``{scoring_fingerprint: {leagueKeys, points}}`` via the one owner."""
    out: dict[str, dict[str, Any]] = {}
    for league_key in league_keys:
        s = wlp.load_weekly_projections(
            league_key,
            season,
            week,
            fetch=lambda key, _s, _w: result if key == source_key else None,
            sources=(source_key,),
            schedule_rows=(),
            identity_index=identity_index,
            use_cache=False,
        )
        if s.scoring_fingerprint is None:
            continue
        entry = out.setdefault(s.scoring_fingerprint, {"leagueKeys": [], "points": {}})
        entry["leagueKeys"].append(league_key)
        if not entry["points"]:
            entry["points"] = {
                pid: p.weekly_points
                for pid, p in s.players.items()
                if p.state == wlp.STATE_PROJECTED
            }
    return out


def _model_of(source_key: str) -> str | None:
    from src.ros import projection_source_census as census

    entry = census.get_source(source_key) or {}
    return (entry.get("modelAncestry") or {}).get("model")


def _fetch(source_key: str, season: int, week: int) -> Any:
    return wlp._default_fetch(source_key, season, week)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--season", type=int, default=None)
    ap.add_argument("--week", type=int, default=None, help="current week (default: Sleeper state)")
    ap.add_argument("--weeks-ahead", type=int, default=3)
    ap.add_argument("--weeks", type=int, nargs="*", default=(), help="extra weeks, e.g. 15 16 17")
    ap.add_argument("--league-key", action="append", default=None)
    ap.add_argument("--base-dir", type=Path, default=None)
    ap.add_argument("--pause", type=float, default=1.5, help="seconds between requests (>= 1)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    # Literal flag name: the reachability audit reads literals only.
    if not is_enabled("weekly_projection_capture"):
        print("weekly_projection_capture: feature_disabled (no network call)")
        return 0
    if args.pause < 1.0:
        print("error: --pause must be >= 1 second", file=sys.stderr)
        return 2
    try:
        season, week = args.season, args.week
        if season is None or week is None:
            state = _nfl_state()
            season = season or int(state["season"])
            week = week or int(state["week"])
        if args.league_key:
            league_keys = list(args.league_key)
        else:
            from src.api import league_registry as reg

            league_keys = [cfg.key for cfg in reg.active_leagues()]
    except Exception as exc:  # noqa: BLE001
        print(f"error: cannot resolve season/week/leagues: {exc}", file=sys.stderr)
        return 2

    weeks = sorted({int(week) + i for i in range(max(0, args.weeks_ahead) + 1)} | set(args.weeks))
    weeks = [w for w in weeks if 1 <= w <= 18]
    current_ok = False
    networked = False
    try:
        for wk in weeks:
            identity_index = None
            for source_key in wlp.SOURCE_PRECEDENCE:
                if networked:
                    time.sleep(args.pause)
                result = _fetch(source_key, season, wk)
                status = getattr(result, "status", None)
                networked = status not in ("feature_disabled", None)
                if source_key == wlp.SLEEPER_SOURCE and status == "ok":
                    identity_index = wlp._default_identity_index(list(result.rows))
                if not _has_content(source_key, result):
                    print(
                        f"{source_key} w{wk}: {status} "
                        f"{getattr(result, 'reason', '') or 'not published'}"
                    )
                    continue
                raw, n, stamps = _raw_of(source_key, result)
                scored = _league_scored(league_keys, source_key, result, season, wk, identity_index)
                if args.dry_run:
                    print(f"{source_key} w{wk}: would capture {n} rows ({len(scored)} cards)")
                    current_ok = current_ok or wk == week
                    continue
                written = archive.record_capture(
                    source_key=source_key,
                    season=season,
                    week=wk,
                    fetched_at=result.observed_at,
                    rows=raw,
                    provider_updated_at=stamps,
                    source_url=getattr(result, "url", None),
                    model_company=_model_of(source_key),
                    league_scored=scored,
                    extra={"currentWeekAtCapture": week},
                    hash_content=_stable_content(source_key, raw),
                    base_dir=args.base_dir,
                )
                print(f"{source_key} w{wk}: {written.status} {n} rows -> {written.path}")
                current_ok = current_ok or wk == week
    except Exception as exc:  # noqa: BLE001
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    return 0 if current_ok else 1


if __name__ == "__main__":
    sys.exit(main())
