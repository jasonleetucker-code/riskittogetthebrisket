"""AL-3b — projection scorecard under exact league scoring (report-only).

Scores the projections Calculator held BEFORE kickoff against realized
league-scored points with ``src/model_registry/projection_scorecard.py``:

* **WEEKLY** — each NFL week's pregame Sleeper weekly projections:
  ``data/game_day/live/_nfl/<season>/week_<n>/pregame_projections.json.gz``
  (read with ``game_day_live._read_pregame_archive``), or, for a recent week whose
  raw log is not yet archived, the SAME payload built in memory by
  ``game_day_live.build_pregame_projection_archive`` (nothing is written there).
  Realized: Sleeper's weekly stat dump, read once per content change through
  ``league_comparison.sleeper_stats.fetch_week_stats_response`` (only with
  ``--fetch-realized``) and kept under ``data/learning/scorecards/realized/`` so a
  re-run replays the same bytes.
* **SEASON** — every immutable BDVM snapshot under ``data/bdvm/projections/<season>/``
  against ``bdvm.actuals`` weekly points (nflverse; cache-only unless
  ``--fetch-realized``), kept the same way.

Writes a deterministic PRIVATE summary to
``data/learning/scorecards/projection_scorecard_<leagueKey>.json`` and, only when
``RISKIT_RECEIPTS_ENABLED=1``, EVALUATION receipts to ``data/learning/receipts.sqlite``.
Changes no projection, no served value and no source weight; promotes nothing.

Usage::

    python scripts/projection_scorecard.py --league dynasty_main [--season 2026]
        [--fetch-realized] [--dry-run]

Exit codes: 0 scored (read the summary: it may be empty / insufficient);
1 receipts could not be stored; 2 unknown league or no usable scoring card.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._scorecard_common import SCORECARD_DIR, code_revision, emit, write_json  # noqa: E402
from src.api import league_registry  # noqa: E402
from src.model_registry import projection_scorecard as ps  # noqa: E402

CODE_PATHS = ("src/model_registry/projection_scorecard.py", "scripts/projection_scorecard.py")
REALIZED_DIR = SCORECARD_DIR / "realized"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _stored(directory: Path) -> list[dict[str, Any]]:
    out = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else ():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("readAt") and "content" in data:
            out.append({**data, "_path": _rel(path)})
    return out


def _keep_if_changed(
    directory: Path,
    content: Any,
    *,
    dry_run: bool,
    identity: Any = None,
    read_at: datetime | None = None,
) -> dict[str, Any]:
    """The stored copy with the same identity, or a new one stamped ``read_at``.

    ``identity`` defaults to the content. A re-read with the same identity keeps
    its ORIGINAL ``readAt``, so the scorecard's inputs (and receipts) stay
    byte-identical across runs; an identity that includes the evidence STATE (e.g.
    not-yet-final -> final) makes a state change a new record with a new read time."""
    digest = _sha(content if identity is None else identity)
    for item in _stored(directory):
        if item.get("sha256") == digest:
            return item
    read_at = read_at or _now()
    record = {"readAt": read_at.isoformat(), "sha256": digest, "content": content}
    if not dry_run:
        path = directory / f"{read_at.strftime('%Y%m%dT%H%M%SZ')}_{digest[:12]}.json"
        write_json(path, record)
        record["_path"] = _rel(path)
    else:
        record["_path"] = "(dry-run, not stored)"
    return record


def _host_state() -> tuple[dict[str, Any] | None, datetime]:
    """Sleeper's own week state and when it was read (``None`` on failure)."""
    from src.public_league.sleeper_client import fetch_nfl_state

    at = _now()
    state = fetch_nfl_state()
    return (dict(state) if isinstance(state, dict) else None), at


# ── WEEKLY ───────────────────────────────────────────────────────────────────


def weekly_archives(season: int) -> tuple[list[ps.WeeklyArchive], list[str]]:
    from src.ros import game_day_live as gdl

    root = gdl.LIVE_ROOT / gdl.NFL_KEY / str(season)
    out: list[ps.WeeklyArchive] = []
    notes: list[str] = []
    if not root.is_dir():
        return out, [f"no NFL Game Day directory for {season} at {root}"]
    for week_dir in sorted(root.glob("week_*"), key=lambda p: int(p.name.split("_")[1])):
        week = int(week_dir.name.split("_")[1])
        path = gdl.pregame_archive_path(season, week)
        if path.exists():
            payload = gdl._read_pregame_archive(path)
            if payload is None:
                notes.append(f"week {week}: archive unreadable")
                continue
            out.append(
                ps.WeeklyArchive(
                    season, week, payload, f"{gdl.NFL_KEY}/{season}/{week_dir.name}/{path.name}"
                )
            )
            continue
        try:
            payload = gdl.build_pregame_projection_archive(
                season, week, schedule_rows=gdl._archive_schedule_rows(season), now=time.time()
            )
        except gdl.PregameArchiveUnavailable as exc:
            notes.append(f"week {week}: raw log present, archive not buildable ({exc})")
            continue
        if payload is None:
            notes.append(f"week {week}: no stored weekly projection fetch")
            continue
        out.append(
            ps.WeeklyArchive(
                season,
                week,
                payload,
                f"{gdl.NFL_KEY}/{season}/{week_dir.name}/observations (unarchived)",
            )
        )
    return out, notes


def _week_record(item: dict[str, Any], season: int, week: int) -> ps.RealizedWeek | None:
    content = item.get("content") or {}
    if not isinstance(content, dict) or not isinstance(content.get("stats"), dict):
        return None
    observed = content.get("hostStateObservedAt")
    return ps.RealizedWeek(
        season=season,
        week=week,
        fetched_at=datetime.fromisoformat(item["readAt"]),
        stats=content["stats"],
        source_key=item["_path"],
        host_state=content.get("hostState"),
        host_state_observed_at=datetime.fromisoformat(observed) if observed else None,
    )


def realized_weeks(
    season: int,
    last_kickoff: dict[int, datetime | None],
    *,
    fetch: bool,
    dry_run: bool,
) -> tuple[list[ps.RealizedWeek], list[str]]:
    """Stored realized dumps per week; with ``fetch``, read the host week state and
    then the dump, and keep it when its stats OR its evidence state changed."""
    out: list[ps.RealizedWeek] = []
    notes: list[str] = []
    for week in sorted(last_kickoff):
        directory = REALIZED_DIR / "sleeper_weekly_stats" / str(season) / f"week_{week}"
        if fetch:
            from src.league_comparison.sleeper_stats import fetch_week_stats_response

            state, state_at = _host_state()
            response = fetch_week_stats_response(season, week)
            read_at = _now()
            if response.error is None and isinstance(response.payload, dict) and response.payload:
                content = {
                    "stats": response.payload,
                    "hostState": state,
                    "hostStateObservedAt": state_at.isoformat() if state is not None else None,
                }
                trial = _week_record(
                    {"readAt": read_at.isoformat(), "content": content, "_path": "trial"},
                    season,
                    week,
                )
                label = ps.realized_week_state(trial, last_kickoff[week])
                _keep_if_changed(
                    directory,
                    content,
                    dry_run=dry_run,
                    identity={"stats": _sha(response.payload), "evidenceState": label},
                    read_at=read_at,
                )
            else:
                notes.append(f"week {week}: realized fetch failed ({response.error})")
        for item in _stored(directory):
            record = _week_record(item, season, week)
            if record is None:
                notes.append(f"week {week}: unreadable realized record {item.get('_path')}")
                continue
            out.append(record)
    return out, notes


def _last_kickoffs(archives: list[ps.WeeklyArchive]) -> dict[int, datetime | None]:
    out: dict[int, datetime | None] = {}
    for arch in archives:
        kicks = [
            datetime.fromisoformat(str(e.get("kickoffAt")))
            for e in (arch.payload.get("players") or {}).values()
            if isinstance(e, dict) and e.get("kickoffAt")
        ]
        out[arch.week] = max(kicks) if kicks else None
    return out


# ── SEASON ───────────────────────────────────────────────────────────────────


def season_snapshots(season: int) -> list[ps.SeasonSnapshot]:
    from src.bdvm.projections import SNAPSHOT_DIR, load_snapshot

    root = SNAPSHOT_DIR / str(season)
    out = []
    for path in sorted(root.glob("projections_*.json")) if root.is_dir() else ():
        as_of, records = load_snapshot(path)
        out.append(ps.SeasonSnapshot(as_of, records, _rel(path)))
    return out


def week_first_kickoffs(season: int) -> dict[int, datetime]:
    from src.api import matchup_intel as mi
    from src.ros import game_day_live as gdl

    rows = gdl._archive_schedule_rows(season)
    out: dict[int, datetime] = {}
    for week in range(1, 19):
        kicks = mi.kickoffs_for_week(rows, None, season=season, week=week, now=time.time())
        if kicks:
            out[week] = datetime.fromtimestamp(min(kicks.values()), tz=timezone.utc)
    return out


def realized_season(
    season: int, scoring: dict[str, Any], league_key: str, *, fetch: bool, dry_run: bool
) -> tuple[ps.RealizedSeason | None, list[str]]:
    """The latest stored season realized read; with ``fetch``, re-read the
    nflverse weekly rows through ``bdvm.actuals`` together with the host week
    state that proves which weeks are FINISHED, and keep it when either changed."""
    directory = REALIZED_DIR / "nflverse_weekly_points" / str(season) / league_key
    notes: list[str] = []
    if fetch:
        from src.bdvm.actuals import fetch_current_season_actuals
        from src.utils.name_clean import normalize_player_name

        state, state_at = _host_state()
        try:
            _current, points = fetch_current_season_actuals(
                scoring, name_normalizer=normalize_player_name, season=season
            )
        except Exception as exc:  # noqa: BLE001 -- a fetch failure is reported, never zero
            points = None
            notes.append(f"season realized unavailable: {type(exc).__name__}: {exc}")
        if points:
            final = sorted(w for w in range(1, 19) if ps.host_week_final(state, season, w))
            _keep_if_changed(
                directory,
                {
                    "points": {k: [list(x) for x in v] for k, v in sorted(points.items())},
                    "finalWeeks": final,
                    "hostState": state,
                    "hostStateObservedAt": state_at.isoformat(),
                },
                dry_run=dry_run,
            )
    stored = sorted(_stored(directory), key=lambda i: i["readAt"])
    if not stored:
        return None, [*notes, "season realized: nothing stored (--fetch-realized reads it)"]
    item = stored[-1]
    content = item["content"]
    kicks = week_first_kickoffs(season)
    if not kicks:
        return None, [*notes, "season realized: no cached schedule, week kickoffs unknown"]
    return (
        ps.RealizedSeason(
            season=season,
            known_at=datetime.fromisoformat(item["readAt"]),
            points={k: [tuple(x) for x in v] for k, v in content["points"].items()},
            week_first_kickoff=kicks,
            source_key=item["_path"],
            final_weeks=frozenset(int(w) for w in content.get("finalWeeks") or ()),
        ),
        notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--league", required=True)
    parser.add_argument("--season", type=int)
    parser.add_argument("--fetch-realized", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="print; write nothing")
    args = parser.parse_args(argv)

    from src.bdvm.actuals import current_nfl_season
    from src.league_comparison.sleeper_scoring import scoring_fingerprint

    cfg = league_registry.get_league_by_key(args.league)
    if cfg is None:
        print(f"unknown league {args.league!r}")
        return 2
    scoring = league_registry.scoring_settings_for_league(cfg)
    if not scoring:
        print(f"{cfg.key}: no stored scoring card; run scripts/fetch_league_scoring.py")
        return 2
    fingerprint = scoring_fingerprint(scoring)
    season = args.season or current_nfl_season()
    if season is None:
        print("no current NFL season (off-season); pass --season")
        return 2

    archives, notes = weekly_archives(season)
    realized, more = realized_weeks(
        season, _last_kickoffs(archives), fetch=args.fetch_realized, dry_run=args.dry_run
    )
    notes += more
    snapshots = season_snapshots(season)
    season_realized = None
    if snapshots:
        season_realized, more = realized_season(
            season, dict(scoring), cfg.key, fetch=args.fetch_realized, dry_run=args.dry_run
        )
        notes += more
    else:
        notes.append(f"no BDVM snapshots under data/bdvm/projections/{season}")

    result = ps.evaluate(
        league_key=cfg.key,
        scoring=dict(scoring),
        scoring_fingerprint=fingerprint,
        weekly_archives=archives,
        realized_weeks=realized,
        season_snapshots=snapshots,
        realized_season=season_realized,
    )
    summary = {
        **result.summary,
        "inputs": {
            "season": season,
            "scoringEvidenceState": league_registry.scoring_evidence_state(cfg),
            "weeklyArchives": [a.source_key for a in archives],
            "realizedWeeks": sorted({r.source_key for r in realized}),
            "seasonSnapshots": [s.source_key for s in snapshots],
            "notes": notes,
        },
    }
    ok = sum(1 for c in summary["cohorts"] if c["status"] == "ok")
    print(
        f"projection scorecard {cfg.key} {season}: archives={len(archives)} "
        f"realizedWeeks={len(realized)} snapshots={len(snapshots)} pairs={len(result.pairs)} "
        f"cohorts={len(summary['cohorts'])} sufficient={ok}"
    )
    for note in notes:
        print(f"  note: {note}")
    if args.dry_run:
        print(json.dumps(summary, sort_keys=True, indent=1)[:4000])
        return 0
    out = write_json(SCORECARD_DIR / f"projection_scorecard_{cfg.key}.json", summary)
    print(f"summary -> {out}")
    code_sha = code_revision(CODE_PATHS)
    stored = emit(
        lambda: ps.receipts(result, code_sha=code_sha, scoring_fingerprint=fingerprint),
        label=f"projection_scorecard:{cfg.key}",
    )
    return 0 if stored.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
