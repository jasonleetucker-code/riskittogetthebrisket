#!/usr/bin/env python3
"""Collect Signals Fantasy's public dynasty boards into the private box store.

    python scripts/fetch_signals.py                       # both boards
    python scripts/fetch_signals.py --board dynasty
    python scripts/fetch_signals.py --min-interval-hours 6
    python scripts/fetch_signals.py --identity-report     # + join vs local board
    python scripts/fetch_signals.py --clear-stop          # after a 401/403 stop

Exit codes: 0 every requested board ok (published / unchanged / 304 /
skipped by interval) · 1 any board failed or is stopped · 2 any board
quarantined for schema drift (and none hard-failed).

All logic lives in ``src/sources/signals.py`` (the one Signals owner); this
is a thin CLI.  One GET per board per run, conditional once a good release
exists, 429-aware, and stopped — persistently — by 401/403.  Output goes to
``data/sources/signals/`` (gitignored; never force-added by any workflow).
Authorization: owner attestation 2026-10-01, public boards only, read-only.
No login, no paid surface.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources import signals as S  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STORE = REPO / "data" / "sources" / "signals"

_OK = {"published", "unchanged_content", "not_modified", "skipped_recent"}


def _identity_report(store: S.SignalsStore) -> dict:
    """Join the stored releases against a contract built from the newest
    local export — the same CONTRACT_CSV_JOIN_V1 path the endpoint uses."""
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    exports = sorted((REPO / "exports" / "latest").glob("dynasty_data_*.json"))
    if not exports:
        return {"status": "no_local_export"}
    raw = json.loads(exports[-1].read_text(encoding="utf-8"))
    contract = build_api_data_contract(raw)
    rows = contract.get("playersArray") or []
    observations = []
    for key in S.BOARDS:
        for obs in (store.latest(key) or {}).get("observations") or []:
            observations.append({**obs, "board": key})
    join = S.join_to_board(observations, rows)
    by_board: dict[str, dict[str, int]] = {}
    for key in S.BOARDS:
        by_board[key] = {
            "observations": sum(1 for o in observations if o["board"] == key),
            "resolved": sum(1 for m in join.matches.values() if m["board"] == key),
            "ambiguous": sum(1 for a in join.ambiguous if a["board"] == key),
            "unresolved": sum(1 for u in join.unresolved if u["board"] == key),
        }
    reasons: dict[str, int] = {}
    for e in join.ambiguous + join.unresolved:
        reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
    report = {
        "status": "ok",
        "export": exports[-1].name,
        "boardRows": len(rows),
        "byBoard": by_board,
        "reasons": reasons,
        "ambiguous": join.ambiguous,
        "unresolved": join.unresolved,
    }
    S.atomic_write_json(store.root / "identity_report.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--board", choices=["all", *S.BOARDS], default="all")
    ap.add_argument("--store-dir", type=Path, default=DEFAULT_STORE)
    ap.add_argument(
        "--min-interval-hours",
        type=float,
        default=None,
        help="skip a board attempted less than this many hours ago",
    )
    ap.add_argument("--clear-stop", action="store_true", help="clear a persisted 401/403 stop")
    ap.add_argument("--identity-report", action="store_true")
    args = ap.parse_args(argv)

    store = S.SignalsStore(args.store_dir)
    boards = list(S.BOARDS) if args.board == "all" else [args.board]
    if args.clear_stop:
        for key in boards:
            state = store.fetch_state(key)
            if state.pop("stoppedAt", None):
                state.pop("stopReason", None)
                store.save_fetch_state(key, state)
                print(f"[signals] {key}: stop cleared")

    outcomes = []
    for key in boards:
        out = S.collect_board(S.BOARDS[key], store, min_interval_hours=args.min_interval_hours)
        outcomes.append(out)
        print(f"[signals] {json.dumps(out, sort_keys=True)}")

    if args.identity_report:
        rep = _identity_report(store)
        summary = {
            k: rep[k] for k in ("status", "export", "boardRows", "byBoard", "reasons") if k in rep
        }
        print("[signals] identity " + json.dumps(summary, sort_keys=True))

    kinds = {o["outcome"] for o in outcomes}
    if kinds <= _OK:
        return 0
    if kinds - _OK == {"quarantined"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
