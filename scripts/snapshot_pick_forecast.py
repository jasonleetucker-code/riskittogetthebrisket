"""AL-P4: record a dated point-in-time pick-forecast / team-strength snapshot.

    python scripts/snapshot_pick_forecast.py record [--league KEY] [--dir DIR]
                                                    [--no-contract] [--dry-run]
    python scripts/snapshot_pick_forecast.py list [--dir DIR]

``record`` writes one line per active league per Sleeper NFL week (season,
season type and week from Sleeper's own ``/state/nfl``) to the append-only
monthly ``data/pick_forecast_snapshots/ledger-YYYY-MM.jsonl`` (gitignored,
box-local, private). FIRST WRITE WINS: a second run in the same NFL week is a
no-op, so the weekly timer may fire more often without harm and an operator
can run it on demand. CAPTURE ONLY — nothing is served, nothing reads it
(``src/ros/pick_forecast_snapshot.py``).

Roster quality and age come from the canonical roster-intelligence owner over
the canonical contract, built in memory from the freshest served payload; that
contract describes one league, so other leagues record those two fields as
``None`` with the reason. ``--no-contract`` skips the build (both fields then
record ``contract_build_skipped``).

Exit codes: 0 every league recorded (or already recorded this week); 1 Sleeper's
NFL state is unreadable (no week can be named, so nothing is guessed), no
league is configured, or any league failed to assemble/write.
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


def _load_contract() -> tuple[dict[str, Any] | None, str | None, dict[str, Any]]:
    """The canonical contract, built in memory from the freshest served payload."""
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
    provenance = {
        "payloadPath": rel,
        "payloadSha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "payloadScrapeTimestamp": raw.get("scrapeTimestamp"),
        "payloadAgeHours": None if age_hours is None else round(age_hours, 2),
    }
    try:
        contract = build_api_data_contract(raw)
    except Exception as exc:  # noqa: BLE001
        return None, f"contract_build_failed:{type(exc).__name__}:{exc}"[:300], provenance
    provenance["contractLeagueKey"] = snap.contract_league_key(contract)
    provenance["contractVersion"] = contract.get("version") or contract.get("contractVersion")
    return contract, None, provenance


def cmd_record(args: argparse.Namespace) -> int:
    from src.api.league_registry import active_leagues, get_league_by_key  # noqa: PLC0415
    from src.public_league.sleeper_client import fetch_nfl_state  # noqa: PLC0415

    try:
        base = snap.check_store_path(Path(args.dir))
    except snap.StorePathRefused as exc:
        log(f"refused: {exc}")
        return 1

    nfl_state = fetch_nfl_state()
    ident = snap.week_identity(nfl_state)
    if ident is None:
        log(f"Sleeper /state/nfl unreadable ({nfl_state!r}); refusing to guess a week")
        return 1
    season, season_type, week = ident

    if args.league:
        cfg = get_league_by_key(args.league)
        leagues = [cfg] if cfg is not None else []
    else:
        leagues = [c for c in active_leagues() if c and c.sleeper_league_id]
    if not leagues:
        log("no league configured -- nothing to record")
        return 1

    known = set() if args.dry_run else snap.recorded_keys(base)
    pending = [
        c for c in leagues if snap.snapshot_key(c.key, season, season_type, week) not in known
    ]
    for cfg in leagues:
        if cfg not in pending:
            log(f"{cfg.key}: {season} {season_type} week {week} already recorded")
    if not pending:
        return 0

    if args.no_contract:
        contract, contract_reason, provenance = None, "contract_build_skipped", {}
    else:
        contract, contract_reason, provenance = _load_contract()
        if contract is None:
            log(f"canonical contract unavailable ({contract_reason}); rosterQuality/age -> None")

    failures = 0
    for cfg in pending:
        try:
            inputs = snap.gather_inputs(
                cfg,
                nfl_state,
                contract=contract,
                contract_reason=contract_reason,
                provenance=provenance,
            )
            record = snap.assemble_snapshot(inputs)
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
        except (OSError, ValueError) as exc:
            failures += 1
            log(f"{cfg.key}: write failed: {exc}")
            continue
        log(
            f"{cfg.key}: {season} {season_type} week {week} "
            f"{'recorded' if written else 'already recorded'} "
            f"({len(record['teams'])} teams, {nulls} null fields with reasons)"
        )
    return 1 if failures else 0


def cmd_list(args: argparse.Namespace) -> int:
    try:
        rows = list(snap.iter_snapshots(Path(args.dir)))
    except snap.StorePathRefused as exc:
        log(f"refused: {exc}")
        return 1
    for r in rows:
        print(
            f"{r.get('leagueKey')}\t{r.get('season')}\t{r.get('seasonType')}\t"
            f"week {r.get('week')}\t{r.get('recordedAt')}\t"
            f"forecast={'yes' if r.get('forecast') else 'no'}"
        )
    log(f"{len(rows)} snapshot(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="record this NFL week's snapshot per league")
    rec.add_argument("--league", help="one league key (default: every active league)")
    rec.add_argument("--dir", default=str(snap.DEFAULT_DIR))
    rec.add_argument("--no-contract", action="store_true", help="skip the contract build")
    rec.add_argument("--dry-run", action="store_true", help="print records, write nothing")
    rec.set_defaults(func=cmd_record)
    lst = sub.add_parser("list", help="list recorded snapshots")
    lst.add_argument("--dir", default=str(snap.DEFAULT_DIR))
    lst.set_defaults(func=cmd_list)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
