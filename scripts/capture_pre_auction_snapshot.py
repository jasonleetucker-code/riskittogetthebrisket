#!/usr/bin/env python3
"""Automatic pre-auction snapshot (daily timer; idempotent, first-valid-wins).

Wraps ``scripts/backtest_perfect_draft.py::build_snapshot`` with the gate in
``src/draft/pre_auction_capture.py``.  Sleeper draft state is read through the
existing ``src.public_league.sleeper_client``.  Output (gitignored, box-local,
like the other pre-event captures): ``data/draft_backtest/<year>-pre.json`` and
insurance copies ``<year>-early-<ISOweek>.json``; neither is ever overwritten.

Exit codes: 0 recorded, or already held (nothing to do); 1 error;
2 skipped (draft started, or no board/rookie pool to capture);
3 transient (Sleeper unreadable / league or year unresolved) -- retried.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.draft import pre_auction_capture as pac  # noqa: E402

DEFAULT_DIR = REPO / "data" / "draft_backtest"
EXIT_OK, EXIT_ERROR, EXIT_SKIPPED, EXIT_TRANSIENT = 0, 1, 2, 3


def _resolve(league_key: str | None, year: int | None) -> tuple[str | None, str | None, int | None]:
    from src.api import league_registry as reg
    from src.api.draft_class_evidence import league_draft_years_for

    cfg = reg.get_league_by_key(league_key) if league_key else reg.get_default_league()
    if cfg is None or not cfg.sleeper_league_id:
        return None, None, None
    if year is None:
        year = league_draft_years_for(cfg.sleeper_league_id).upcoming_draft_year
    return cfg.key, cfg.sleeper_league_id, int(year)


def run(
    *,
    out_dir: Path = DEFAULT_DIR,
    league_key: str | None = None,
    year: int | None = None,
    window_days: int = pac.DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
    resolve: Callable[..., Any] = _resolve,
    fetch_drafts: Callable[[str], tuple[str, Any]] | None = None,
    build: Callable[[str | None], tuple[dict[str, Any] | None, int]] | None = None,
) -> int:
    now = now or datetime.now(timezone.utc)
    try:
        key, sleeper_id, draft_year = resolve(league_key, year)
    except Exception as exc:  # noqa: BLE001
        print(f"TRANSIENT: cannot resolve league/draft year: {exc}", file=sys.stderr)
        return EXIT_TRANSIENT
    if not key or not sleeper_id or not draft_year:
        print("TRANSIENT: no Sleeper league / draft year resolvable.", file=sys.stderr)
        return EXIT_TRANSIENT

    # Cheap exit BEFORE any network or contract build.
    if pac.pre_path(out_dir, draft_year).exists():
        print(f"HELD: {pac.pre_path(out_dir, draft_year)} already recorded; not overwriting.")
        return EXIT_OK

    if fetch_drafts is None:
        from src.public_league import sleeper_client

        fetch_drafts = sleeper_client.fetch_drafts_classified
    try:
        kind, drafts = fetch_drafts(sleeper_id)
    except Exception as exc:  # noqa: BLE001
        kind, drafts = "error", str(exc)
    if kind != "ok" or not isinstance(drafts, list):
        print(f"TRANSIENT: Sleeper drafts unreadable ({kind}); refusing to guess.", file=sys.stderr)
        return EXIT_TRANSIENT

    decision = pac.decide(drafts, draft_year, now, window_days=window_days)
    if decision.action == "refuse":
        print(f"SKIPPED: {decision.reason}; the auction has started, nothing recorded.")
        return EXIT_SKIPPED
    path = (
        pac.pre_path(out_dir, draft_year)
        if decision.action == "record_pre"
        else pac.early_path(out_dir, draft_year, now)
    )
    if path.exists():
        print(f"HELD: {path} already recorded; not overwriting.")
        return EXIT_OK

    if build is None:
        from scripts.backtest_perfect_draft import build_snapshot as build
    payload, code = build(key)
    if payload is None:
        return code
    if not pac.write_once(path, pac.stamp(payload, decision, draft_year, now)):
        print(f"HELD: {path} appeared concurrently; not overwriting.")
        return EXIT_OK
    print(f"RECORDED {decision.action}: {path} ({decision.reason}).")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--league-key", default=None)
    ap.add_argument("--year", type=int, default=None, help="rookie draft class year")
    ap.add_argument("--window-days", type=int, default=pac.DEFAULT_WINDOW_DAYS)
    args = ap.parse_args(argv)
    return run(
        out_dir=args.out_dir,
        league_key=args.league_key,
        year=args.year,
        window_days=args.window_days,
    )


if __name__ == "__main__":
    sys.exit(main())
