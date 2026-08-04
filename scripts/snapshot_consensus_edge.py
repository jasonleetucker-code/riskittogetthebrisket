#!/usr/bin/env python3
"""Persist today's Consensus Edge board, and label matured outcomes.

Runs on the box that serves the board, because it reads the live
contract from disk and writes into gitignored ``data/``.

Two jobs in one invocation, deliberately:

1. **Snapshot** — record what the board says today, with the model and
   parameter versions that produced it. Without this the feature can
   never answer "what did we say about X on D", and no call can ever be
   scored after the fact.
2. **Label** — fill in forward returns for snapshots whose horizon has
   now elapsed. Kept separate from the write so an outcome can never be
   recorded before it happened.

Idempotent: re-running on the same date replaces that date's rows for
the same model+params and leaves every other row alone.

Exit codes (repo convention — see scripts/refresh_playerctx.py):
    0  - snapshot written (or --dry-run parsed cleanly)
    1  - soft failure (no contract, no board, write error)
    2  - schema regression: the board came back structurally wrong
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.consensus_edge import inputs as inputs_mod, service, snapshot  # noqa: E402


def log(msg: str) -> None:
    print(f"[ce-snapshot] {msg}", flush=True)


def _load_contract() -> dict | None:
    """The live contract, built the way the server builds it.

    The files on disk are the RAW scraper payload; ``dataFreshness`` is
    added by ``build_api_data_contract``. Snapshotting the raw payload
    directly would silently record ``hoursStale: null`` on every row —
    the same "an input never arrived" defect this whole audit is about,
    reintroduced in the job that exists to record the evidence.
    """
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    for directory in (REPO / "exports" / "latest", REPO / "data"):
        # NEWEST first. The filenames carry a date, so a plain ascending
        # sort with `return` on the first success took the OLDEST payload
        # in the directory — snapshotting a board from whenever the
        # earliest file happened to be written, under today's date.
        # `panel.py:161` already gets this right with `[-1]`; this is the
        # same fix, stated rather than implied.
        for candidate in sorted(directory.glob("dynasty_data_*.json"), reverse=True):
            try:
                raw = json.loads(candidate.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            return build_api_data_contract(raw)
    return None


def _label(args: argparse.Namespace, board: dict) -> dict[int, dict]:
    """Fill forward returns for snapshots whose horizon has now elapsed.

    This module's docstring has always advertised "Two jobs… 2. Label",
    and until now ``main`` did the first one only: ``label_outcomes`` had
    **zero callers anywhere**. The timer had been accumulating snapshots
    that nothing would ever score, which makes the store an archive
    rather than a measurement.

    Prices come from the store itself (see
    ``snapshot.prices_by_date``) — no git panel, no network, and origin
    and horizon prices written by the same code path.
    """
    horizons = [h.strip() for h in (args.label_horizons or "").split(",") if h.strip()]
    if not horizons:
        return {}
    prices = snapshot.prices_by_date(args.db)
    if len(prices) < 2:
        log(f"labelling skipped: only {len(prices)} dated price map(s) in the store")
        return {}
    out: dict[int, dict] = {}
    for raw in horizons:
        try:
            horizon = int(raw)
        except ValueError:
            log(f"ignoring unparseable horizon {raw!r}")
            continue
        try:
            out[horizon] = snapshot.label_outcomes(
                horizon_days=horizon, prices_by_date=prices, path=args.db
            )
        except ValueError as exc:
            # An unsupported horizon is a caller error, not a run
            # failure: the snapshot is already written and is the part
            # that cannot be recovered later.
            log(f"horizon {horizon}: {exc}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--as-of",
        type=str,
        default=None,
        help=(
            "YYYY-MM-DD (default: today UTC). Stamping a PAST date writes "
            "TODAY's board under that date, which is a fabricated history "
            "entry, so it requires --backfill."
        ),
    )
    ap.add_argument(
        "--backfill",
        action="store_true",
        help="permit --as-of in the past; without it a past date is refused",
    )
    ap.add_argument(
        "--label-horizons",
        type=str,
        default="7,14,30",
        help="comma-separated horizons to label after writing; empty string to skip",
    )
    ap.add_argument("--dry-run", action="store_true", help="build and report, do not write")
    ap.add_argument("--db", type=Path, default=None, help="override the snapshot database path")
    args = ap.parse_args(argv)

    contract = _load_contract()
    if not contract:
        print("[ce-snapshot] no contract on disk; nothing to snapshot", file=sys.stderr)
        return 1

    started = datetime.now(timezone.utc)
    # Shares input resolution with the API. Building this board from
    # fewer inputs than the served one would accrue a history of
    # something no user ever saw, which answers none of the questions
    # the history exists for — and the discrepancy would be invisible,
    # since a board missing a component is a legitimate state.
    board = service.build_board(
        contract,
        hours_stale=service.resolve_hours_stale(contract),
        **inputs_mod.resolve(contract),
    )
    board["contractScrapedAt"] = contract.get("scrapeTimestamp")

    if board.get("status") != "ok":
        print(f"[ce-snapshot] board status {board.get('status')!r}", file=sys.stderr)
        return 1

    players = board.get("players") or []
    scored = [r for r in players if r.get("score") is not None]
    if not players:
        print("[ce-snapshot] board returned zero rows — refusing to write", file=sys.stderr)
        return 2

    availability = board.get("componentAvailability") or {}
    live = [k for k, v in availability.items() if v.get("available")]
    log(
        f"board: {len(players)} rows, {len(scored)} scored, "
        f"components live: {', '.join(live) or 'none'}"
    )
    log(
        f"model {board.get('modelVersion')} params {board.get('paramSetId')} "
        f"hoursStale {(board.get('inputs') or {}).get('hoursStale')}"
    )

    if args.dry_run:
        log("dry run — not writing")
        return 0

    # UTC, matching ``snapshot.write_board``'s own default and the
    # ``as_of`` on every other date in the store. ``date.today()`` is
    # LOCAL, so on a box west of Greenwich a run after 17:00 wrote
    # yesterday's date onto today's board — a one-day-off history that
    # nothing would ever flag.
    today = datetime.now(timezone.utc).date()
    if args.as_of:
        try:
            requested = date.fromisoformat(args.as_of)
        except ValueError:
            print(f"[ce-snapshot] --as-of {args.as_of!r} is not YYYY-MM-DD", file=sys.stderr)
            return 1
        if requested < today and not args.backfill:
            # This writes TODAY's board under a PAST date. That is not a
            # reconstruction — the board is built from today's contract —
            # so it manufactures a history entry that never happened, and
            # every later study reads it as a real one. Deliberate use
            # (e.g. re-stamping a run that straddled midnight) has to say
            # so.
            print(
                f"[ce-snapshot] refusing to write today's board under the past date "
                f"{requested}; pass --backfill if that is genuinely what you want",
                file=sys.stderr,
            )
            return 1
        as_of = requested.isoformat()
    else:
        as_of = today.isoformat()

    try:
        result = snapshot.write_board(board, as_of=as_of, path=args.db)
    except Exception as exc:  # noqa: BLE001 — CLI boundary
        print(f"[ce-snapshot] write failed: {exc}", file=sys.stderr)
        return 1

    labelled = _label(args, board)

    cov = snapshot.coverage(args.db)
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    log(f"wrote {result['written']} rows for {result['asOf']} in {elapsed:.1f}s")
    for horizon, outcome in sorted(labelled.items()):
        log(
            f"labelled h{horizon}: {outcome.get('updated')} of "
            f"{outcome.get('considered')} unlabelled rows"
        )
    log(
        f"store now: {cov.get('rows')} rows across {cov.get('distinctDates')} dates "
        f"({cov.get('firstDate')} -> {cov.get('lastDate')}), "
        f"{cov.get('rowsWithCohortExcess')} with a cohort-excess outcome"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
