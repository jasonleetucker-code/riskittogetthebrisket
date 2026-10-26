"""AL-P4: record a dated point-in-time pick-forecast / team-strength snapshot.

    python scripts/snapshot_pick_forecast.py record [--league KEY] [--dir DIR]
                                                    [--no-contract] [--dry-run]
    python scripts/snapshot_pick_forecast.py list [--dir DIR] [--all]

``record`` assembles one record per active league for the current capture
window (``nfl-week:<N>`` from Sleeper's own ``/state/nfl`` in season, the UTC
ISO week otherwise) and appends it to the append-only monthly
``data/pick_forecast_snapshots/ledger-YYYY-MM.jsonl`` (box-local, private,
ignored by version control) -- but only when its TIER beats what the window
already holds (settled > unsettled, then complete > partial > degraded). A
better record is a new line naming what it ``supersedes``; nothing is
overwritten, and a re-run at an equal or lower tier is a no-op. So the Tuesday
slot plus the Wednesday/Thursday catch-ups, systemd's ``Restart=on-failure``,
and an operator re-run are all safe; a Monday run before Monday Night Football
records ``captureSettled: false`` and cannot hold the window against the
settled Tuesday capture. CAPTURE ONLY -- nothing is served, nothing reads it
(``src/ros/pick_forecast_snapshot.py``).

A CORE field (teams + standings, pick ownership, forecast) null because a read
failed (Sleeper timeout, ``/traded_picks`` failure, a snapshot that fails the
current-season integrity check) is REFUSED, not written, and the run exits 3 so
systemd retries.

Roster quality and age come from the canonical roster-intelligence owner over
the canonical contract, built in memory from the freshest served payload -- and
only when that payload is inside the scrape-cadence staleness budget
(``league_registry.SCORING_SNAPSHOT_MAX_AGE_HOURS``, the rule the sparse-evidence
shadow uses); past it both fields record ``contract_stale``. The contract
describes one league, so other leagues record those two fields as ``None`` with
the reason. ``--no-contract`` skips the build (``contract_build_skipped``).

Exit codes: 0 every league recorded, or already held at an equal or better tier;
1 a hard failure (no league configured, a league failed to assemble or write);
3 transient -- Sleeper's NFL state unreadable (no window is guessed) or a core
field missing for a transient reason. systemd treats both 1 and 3 as failure and
retries; 3 is the expected, self-clearing one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.ros import pick_forecast_snapshot as snap  # noqa: E402


def log(msg: str) -> None:
    print(f"[pick-forecast-snapshot] {msg}", flush=True)


EXIT_OK = 0
EXIT_FAILED = 1
EXIT_TRANSIENT = 3


def _stale_budget_hours() -> float:
    """The repo's scrape-cadence staleness rule, owned by ``league_registry`` --
    the same budget the sparse-evidence shadow refuses stale boards by."""
    from src.api.league_registry import SCORING_SNAPSHOT_MAX_AGE_HOURS  # noqa: PLC0415

    return float(SCORING_SNAPSHOT_MAX_AGE_HOURS)


def _load_contract() -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """The canonical contract, built in memory from the freshest served payload.

    Refused -- ``(None, reason, provenance)`` -- when that payload is older than
    the staleness budget or states no scrape time: roster quality and age from a
    stale board would be recorded as if they were this week's.
    """
    from src.api import sparse_evidence_shadow  # noqa: PLC0415
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    found = sparse_evidence_shadow.newest_live_payload(REPO)
    if found is None:
        return None, "no_served_payload_on_disk", {}
    path, raw, age_hours = found
    try:
        rel = str(path.resolve().relative_to(REPO))
    except ValueError:
        rel = str(path)
    budget = _stale_budget_hours()
    provenance = {
        "payloadPath": rel,
        "payloadSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "payloadScrapeTimestamp": raw.get("scrapeTimestamp"),
        "payloadAgeHours": None if age_hours is None else round(age_hours, 2),
        "staleBudgetHours": budget,
    }
    if age_hours is None:
        return None, "contract_age_unknown", provenance
    if age_hours > budget:
        return None, "contract_stale", provenance
    try:
        contract = build_api_data_contract(raw)
    except Exception as exc:  # noqa: BLE001
        return None, f"contract_build_failed:{type(exc).__name__}:{exc}"[:300], provenance
    provenance["contractLeagueKey"] = snap.contract_league_key(contract)
    provenance["contractVersion"] = contract.get("version") or contract.get("contractVersion")
    return contract, None, provenance


def cmd_record(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone  # noqa: PLC0415

    from src.api.league_registry import active_leagues, get_league_by_key  # noqa: PLC0415
    from src.public_league.sleeper_client import fetch_nfl_state  # noqa: PLC0415

    try:
        base = snap.check_store_path(Path(args.dir))
    except snap.StorePathRefused as exc:
        log(f"refused: {exc}")
        return EXIT_FAILED

    nfl_state = fetch_nfl_state()
    ident = snap.week_identity(nfl_state)
    if ident is None:
        log(f"Sleeper /state/nfl unreadable ({nfl_state!r}); refusing to guess a week")
        return EXIT_TRANSIENT
    season, season_type, week = ident
    # One clock for the whole run, so every league files under the same window.
    recorded_at = datetime.now(timezone.utc).isoformat()
    window = snap.capture_window(nfl_state, recorded_at)

    if args.league:
        cfg = get_league_by_key(args.league)
        leagues = [cfg] if cfg is not None else []
    else:
        leagues = [c for c in active_leagues() if c and c.sleeper_league_id]
    if not leagues:
        log("no league configured -- nothing to record")
        return EXIT_FAILED

    known = set() if args.dry_run else snap.recorded_keys(base)
    pending = []
    for cfg in leagues:
        best = snap.best_recorded(base, cfg.key, season, season_type, window, known=known)
        if best is not None and best[0] == snap.TOP_TIER:
            log(f"{cfg.key}: {season} {season_type} {window} already recorded ({best[0]})")
        else:
            pending.append(cfg)
    if not pending:
        return EXIT_OK

    if args.no_contract:
        contract, contract_reason, provenance = None, "contract_build_skipped", {}
    else:
        contract, contract_reason, provenance = _load_contract()
        if contract is None:
            log(f"canonical contract unavailable ({contract_reason}); rosterQuality/age -> None")

    failures = transient = 0
    for cfg in pending:
        try:
            inputs = snap.gather_inputs(
                cfg,
                nfl_state,
                contract=contract,
                contract_reason=contract_reason,
                provenance=provenance,
            )
            record = snap.assemble_snapshot(inputs, recorded_at=recorded_at)
        except Exception as exc:  # noqa: BLE001
            failures += 1
            log(f"{cfg.key}: assembly failed: {type(exc).__name__}: {exc}")
            continue
        nulls = sum(len(t["missing"]) for t in record["teams"]) + len(record["missing"])
        if args.dry_run:
            print(json.dumps(record, indent=2, sort_keys=True, default=str))
            continue
        try:
            written = snap.record_snapshot(record, base)
        except snap.TransientCaptureRefused as exc:
            transient += 1
            log(f"{cfg.key}: NOT recorded, retry expected -- {exc}")
            continue
        except (OSError, ValueError) as exc:
            failures += 1
            log(f"{cfg.key}: write failed: {exc}")
            continue
        log(
            f"{cfg.key}: {season} {season_type} {window} (week {week}) "
            f"{'recorded' if written else 'already held at an equal or better tier'} "
            f"tier={record['tier']} ({len(record['teams'])} teams, "
            f"{nulls} null fields with reasons, lastFinalWeek={record['lastFinalWeek']})"
        )
    if failures:
        return EXIT_FAILED
    return EXIT_TRANSIENT if transient else EXIT_OK


def cmd_list(args: argparse.Namespace) -> int:
    try:
        rows = (
            list(snap.iter_snapshots(Path(args.dir)))
            if args.all
            else snap.current_snapshots(Path(args.dir))
        )
    except snap.StorePathRefused as exc:
        log(f"refused: {exc}")
        return EXIT_FAILED
    for r in rows:
        print(
            f"{r.get('leagueKey')}\t{r.get('season')}\t{r.get('seasonType')}\t"
            f"{r.get('captureWindow')}\t{r.get('recordedAt')}\t{r.get('tier')}\t"
            f"lastFinalWeek={r.get('lastFinalWeek')}\t"
            f"forecast={'yes' if r.get('forecast') else 'no'}\t"
            f"supersedes={'yes' if r.get('supersedes') else 'no'}"
        )
    log(f"{len(rows)} snapshot(s){' (full history)' if args.all else ' (current per window)'}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record this capture window's snapshot per league")
    rec.add_argument("--league", help="one league key (default: every active league)")
    rec.add_argument("--dir", default=str(snap.DEFAULT_DIR))
    rec.add_argument("--no-contract", action="store_true", help="skip the contract build")
    rec.add_argument("--dry-run", action="store_true", help="print records, write nothing")
    rec.set_defaults(func=cmd_record)
    lst = sub.add_parser("list", help="list the current snapshot per window")
    lst.add_argument("--dir", default=str(snap.DEFAULT_DIR))
    lst.add_argument("--all", action="store_true", help="every record, superseded ones too")
    lst.set_defaults(func=cmd_list)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
