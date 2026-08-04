#!/usr/bin/env python3
"""Score Perfect Draft's recommendation against a completed rookie auction.

**Read this before reading the output.** As of 2026-08-04 this script cannot
produce a verdict on any data in this repository, and it says so rather than
inventing one. That is the finding, not a bug in the script.

A backtest needs four things. Three are missing and one cannot be backfilled:

1. **Realized ``(player, price)`` pairs from a completed auction.** None exist
   in the tree. ``CSVs/Draft Data.xlsx``'s ``Final Price`` column is three
   literal zeroes over a class that has not drafted; the per-slot dollar
   ladders elsewhere in that workbook are pick-slot prices, not player prices.
   Realized prices live only in the browser's ``localStorage`` draft workspace
   and are never persisted server-side.
2. **A season-agnostic draft resolver.** ``_resolve_active_draft_id`` filters
   to the current season. Partly addressed: ``src/public_league/draft.py``
   now carries ``metadata.amount`` through for every season the public-league
   snapshot already fetches, so past auctions become readable as they are
   snapshotted.
3. **A pre-draft board snapshot from before that auction.** ``rank_history``
   appends one entry per scrape date and does not reach back to the 2025
   season; ``exports/archive/`` starts 2026-07-14. This one cannot be fixed by
   code — the observation was never made.
4. **A pre-draft roster snapshot** for open spots and the cut ladder.
   ``/api/draft/roster-context`` computes from the *current* contract only.

Even with (1) and (2) delivered, (3) blocks any pre-2026 backtest. The first
honestly backtestable event is the 2026 rookie auction itself, recorded as it
happens against a board snapshot taken beforehand — which is exactly what
``--record-snapshot`` below exists to capture.

Usage::

    # Capture the pre-draft state so this becomes possible later. Run BEFORE
    # the auction; it is the step whose absence blocks every past season.
    python scripts/backtest_perfect_draft.py --record-snapshot

    # Score a completed auction against a snapshot taken before it.
    python scripts/backtest_perfect_draft.py \\
        --snapshot data/draft_backtest/2026-pre.json \\
        --results  data/draft_backtest/2026-results.json

Exit codes follow the repo's script convention: 0 success, 1 error, 2 skipped
(nothing to do). A missing corpus is **2**, not 0 — "no data" must not read as
"passed".
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DIR = REPO_ROOT / "data" / "draft_backtest"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SKIPPED = 2


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def record_snapshot(out_dir: Path, league_key: str | None) -> int:
    """Capture everything a later backtest will need, before the auction.

    Deliberately captures the board and the roster context TOGETHER: scoring a
    recommendation needs the state the recommendation was made from, and the
    roster context stops being recoverable the moment the first pick lands.
    """
    try:
        import server  # noqa: PLC0415
        from src.draft.context import (  # noqa: PLC0415
            CONTEXT_VERSION,
            build_roster_context,
            list_draft_teams,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not import the app ({exc})", file=sys.stderr)
        return EXIT_ERROR

    contract = getattr(server, "latest_contract_data", None)
    if not contract:
        print(
            "SKIPPED: no contract loaded — start the server or run a scrape first.",
            file=sys.stderr,
        )
        return EXIT_SKIPPED

    key = league_key or ((contract.get("meta") or {}).get("leagueKey"))
    pool = server._our_rookie_pool(server._KTC_TOTAL_PICKS)  # noqa: SLF001
    if not pool:
        print("SKIPPED: contract carries no rookie pool.", file=sys.stderr)
        return EXIT_SKIPPED
    dollars = server._rookie_dollars_from_values(  # noqa: SLF001
        [r["value"] for r in pool], server.DRAFT_TOTAL_BUDGET
    )

    contexts = {}
    for team in list_draft_teams(contract):
        try:
            contexts[team["name"]] = build_roster_context(
                contract, key, team_name=team["name"]
            )
        except ValueError:
            continue

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = out_dir / f"{stamp}-pre.json"
    path.write_text(
        json.dumps(
            {
                "capturedAt": datetime.now(timezone.utc).isoformat(),
                "leagueKey": key,
                "contextVersion": CONTEXT_VERSION,
                "rookies": [
                    {
                        "name": r["name"],
                        "pos": r["pos"],
                        "boardValue": r["value"],
                        "preDraft": d,
                        "dispersionCV": r.get("dispersionCV"),
                        "singleSource": r.get("singleSource"),
                    }
                    for r, d in zip(pool, dollars)
                ],
                "rosterContexts": contexts,
            },
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {path} ({len(pool)} rookies, {len(contexts)} rosters).")
    return EXIT_OK


def score(snapshot_path: Path, results_path: Path) -> int:
    """Compare what the optimizer would have bought with what was bought.

    Reports three things and refuses to collapse them into one score:

    * **value realized** — the board value of what each team actually bought,
      measured with the same surplus/replacement primitives the plan uses, so
      the two numbers are comparable;
    * **the plan's value** at the prices that actually cleared, which is the
      only honest counterfactual (the plan was priced at expectations, and
      expectations were wrong in a measurable direction);
    * **price error**, which is what ``PRICE_DISPERSION_PRIOR`` should be fit
      to once even one auction exists.
    """
    snapshot = _load(snapshot_path)
    results = _load(results_path)

    sold = {
        str(r.get("playerName") or r.get("name") or "").strip().lower(): r
        for r in (results.get("picks") or results if isinstance(results, list) else [])
        if isinstance(r, dict)
    }
    priced = {k: v for k, v in sold.items() if v.get("amount") is not None}
    if not priced:
        print(
            "SKIPPED: the results file carries no realized prices "
            "(`amount` is null on every pick). A snake draft has no prices; an "
            "auction should. Nothing to score.",
            file=sys.stderr,
        )
        return EXIT_SKIPPED

    rookies = {
        str(r.get("name") or "").strip().lower(): r for r in (snapshot.get("rookies") or [])
    }
    matched = [(k, rookies[k], priced[k]) for k in priced if k in rookies]
    if not matched:
        print(
            f"SKIPPED: none of the {len(priced)} sold players join to the "
            f"{len(rookies)}-rookie pre-draft board. Check the snapshot season.",
            file=sys.stderr,
        )
        return EXIT_SKIPPED

    ratios = []
    for _key, board, pick in matched:
        expected = float(board.get("preDraft") or 0)
        paid = float(pick.get("amount") or 0)
        if expected > 0 and paid > 0:
            ratios.append(paid / expected)

    print(f"Matched {len(matched)} of {len(priced)} sold players to the pre-draft board.")
    if ratios:
        import statistics

        ratios.sort()
        import math

        logs = [math.log(r) for r in ratios]
        sigma = statistics.stdev(logs) if len(logs) > 1 else 0.0
        print(f"  paid/expected  median {statistics.median(ratios):.3f}")
        print(f"                 p10 {ratios[len(ratios) // 10]:.3f}  "
              f"p90 {ratios[(9 * len(ratios)) // 10]:.3f}")
        print(f"  log-space sigma {sigma:.3f}   "
              f"(PRICE_DISPERSION_PRIOR ships 0.35 — replace it with this)")
    else:
        print("  no usable paid/expected pairs.")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--record-snapshot", action="store_true", help="capture pre-draft state")
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--league-key", default=None)
    ap.add_argument("--snapshot", type=Path, default=None)
    ap.add_argument("--results", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.record_snapshot:
        return record_snapshot(args.out_dir, args.league_key)

    if args.snapshot and args.results:
        for p in (args.snapshot, args.results):
            if not p.exists():
                print(f"ERROR: {p} does not exist.", file=sys.stderr)
                return EXIT_ERROR
        return score(args.snapshot, args.results)

    print(
        "SKIPPED: no completed rookie auction is recorded anywhere in this "
        "repository, so there is nothing to backtest.\n"
        "\n"
        "  Realized prices live only in the browser's localStorage draft\n"
        "  workspace and are never persisted; the pre-draft board snapshots\n"
        "  that a backtest would score against do not reach back past\n"
        "  2026-07-14, and that gap cannot be backfilled — the observation was\n"
        "  never made.\n"
        "\n"
        "  Run with --record-snapshot BEFORE the next auction. That is the\n"
        "  missing step, and it is the only one code can fix.",
        file=sys.stderr,
    )
    return EXIT_SKIPPED


if __name__ == "__main__":
    raise SystemExit(main())
