#!/usr/bin/env python3
"""Crawl transactions from the sharp-eligible leagues.

Discovery finds MANAGERS, records finds their RESULTS — this finds
their TRADES, which is what /market/sharp-tracker's board is made of.

Until this existed, ``ledger.ingest_events`` had exactly one caller
(Insider Trading's snapshot migration), so the ledger held only the
user's own league-mates and a sharp board would have rendered empty.

    python scripts/crawl_sharp_transactions.py              # budgeted pass
    python scripts/crawl_sharp_transactions.py --budget 2000
    python scripts/crawl_sharp_transactions.py --league 12345   # one league
    python scripts/crawl_sharp_transactions.py --stats          # coverage only

Costs 1 call per league for rosters plus one per transaction week —
three weeks on a league's first pass (the backfill walks to week 0,
where Sleeper files preseason trades), one per run after that.
Idempotent: movements dedupe on the roster-slot key, so a re-run or an
interrupted pass re-ingests nothing.

Both sides of every trade are recorded; the board filters to the
QUALIFIED cohort at read time. See src/sharp/transactions.py for why
that ordering is deliberate.

LEAGUE FORMAT CAPTURE (second pass, same run)
After the transaction pass, a separately budgeted pass records each
trade-bearing / sharp-eligible league's point-in-time FORMAT (roster
slots, scoring card, settings) from ``GET /v1/league/{id}`` into the
append-only capture table the completed-trade ledger reads
(src/sharp/league_format_capture.py). Never-captured leagues first, then
the oldest check; a captured league is re-checked at most weekly and a
``complete`` league never. A failure here is reported, never fails the
transaction pass.

    python scripts/crawl_sharp_transactions.py --format-budget 0       # skip it
    python scripts/crawl_sharp_transactions.py --formats-only --format-budget 4000
    python scripts/crawl_sharp_transactions.py --format-stats

The same run then captures OUR registered leagues' per-season formats
(previous_league_id chain; src/trade/own_league_format_capture.py) so the
ledger classifies own-league trades in their own season's format. Skipped
with --format-budget 0 or --league, and skipped when the Sharp format pass
stopped on an HTTP 429 (same public IP -- one shared stop). It spends its OWN
small budget (--own-league-format-budget, default
own_league_format_capture.DEFAULT_RUN_BUDGET), NOT --format-budget: the Sharp
pass routinely spends all of that on its backlog, which would starve the
current-season re-fetch that confirms own-league trades (the bracket). A 429
inside the own-league pass stops the remaining own leagues too.

The pass stops at the first HTTP 429 (``stoppedReason: rate_limited``)
rather than reading it as a deleted league. Every Sharp crawl shares the
box's public IP, so run a large one-shot backfill (``--formats-only
--format-budget 4000``) only while NO other Sharp timer is running
(discovery 04:20, records 04:50, rosters 05:50, and this transaction
timer itself) -- check ``systemctl list-timers 'dynasty-sharp-*'`` first.

Exit codes: 0 success, 1 failure, 2 budget exhausted with leagues left.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import league_format_capture, transactions  # noqa: E402

log = logging.getLogger("crawl_sharp_transactions")


def _capture_own_league_formats(
    *,
    budget: int,
    sharp_stopped_reason: str | None = None,
    configs: list | None = None,
    refresh=None,
) -> dict:
    """Per-season format captures for OUR registered leagues (third pass).

    The completed-trade ledger classifies each own-league trade in its OWN
    season-league's format (src/trade/own_league_format_capture.py).  Run here
    rather than in its own timer so it shares this timer's slot on the box's
    public IP; it costs one request per league once the completed seasons are
    captured (they are frozen after one fetch).  Never fails the run.

    Shared 429 stop: skipped entirely when the Sharp format pass stopped
    ``rate_limited``, and a 429 inside it stops the remaining own leagues.
    ``budget`` is this pass's own request cap, shared across the leagues.
    """
    from src.trade import own_league_format_capture  # noqa: PLC0415

    if sharp_stopped_reason == "rate_limited":
        return {"skipped": "sharp_format_pass_rate_limited", "budget": budget, "leagues": []}
    if budget <= 0:
        return {"skipped": "own_league_format_budget_zero", "budget": budget, "leagues": []}
    refresh = refresh or own_league_format_capture.refresh_own_league_formats
    if configs is None:
        from src.api import league_registry  # noqa: PLC0415

        try:
            configs = list(league_registry.active_leagues())
        except Exception as exc:  # noqa: BLE001
            return {"error": f"registry_unreadable:{type(exc).__name__}: {exc}", "leagues": []}
    out: list[dict] = []
    used = 0
    stopped: str | None = None
    for cfg in configs:
        if stopped is not None:
            out.append({"leagueKey": cfg.key, "skipped": stopped})
            continue
        if used >= budget:
            stopped = "own_league_format_budget_exhausted"
            out.append({"leagueKey": cfg.key, "skipped": stopped})
            continue
        try:
            res = refresh(
                cfg.key,
                root_league_id=cfg.sleeper_league_id,
                sleep_s=0.12,
                max_fetches=budget - used,
            )
            used += int(res.leagues_fetched)
            out.append(res.to_dict())
            if res.stopped_reason == "rate_limited":
                stopped = "rate_limited"
        except Exception as exc:  # noqa: BLE001
            log.exception("own-league format capture failed for %s", cfg.key)
            out.append({"leagueKey": cfg.key, "error": f"{type(exc).__name__}: {exc}"})
    return {"budget": budget, "callsUsed": used, "stoppedReason": stopped, "leagues": out}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=None, help="Max Sleeper API calls.")
    parser.add_argument(
        "--league",
        action="append",
        dest="leagues",
        help="Crawl only this league id (repeatable). Default: every sharp-eligible league.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Report crawl coverage and exit without fetching anything.",
    )
    parser.add_argument(
        "--format-budget",
        type=int,
        default=league_format_capture.DEFAULT_BUDGET,
        help="Sleeper calls for the league-format capture pass (0 skips it).",
    )
    parser.add_argument(
        "--own-league-format-budget",
        type=int,
        default=None,
        help=(
            "Sleeper calls for the own-league per-season format pass (separate from "
            "--format-budget; default own_league_format_capture.DEFAULT_RUN_BUDGET)."
        ),
    )
    parser.add_argument(
        "--formats-only",
        action="store_true",
        help="Run only the league-format capture pass (backfill).",
    )
    parser.add_argument(
        "--format-stats",
        action="store_true",
        help="Report league-format capture coverage and exit without fetching.",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        if args.stats:
            print(json.dumps(transactions.crawl_coverage(), indent=2))
            return 0
        if args.format_stats:
            print(json.dumps(league_format_capture.capture_coverage(), indent=2))
            return 0

        payload: dict = {}
        tx_pending = False
        if not args.formats_only:
            kwargs = {}
            if args.budget is not None:
                kwargs["budget"] = args.budget
            result = transactions.crawl_transactions(league_ids=args.leagues, **kwargs)
            payload = result.to_dict()
            payload["coverage"] = transactions.crawl_coverage()
            tx_pending = bool(result.leagues_pending)

        format_pending = False
        sharp_stopped: str | None = None
        if args.format_budget > 0:
            try:
                fmt = league_format_capture.capture_league_formats(
                    league_ids=args.leagues, budget=args.format_budget
                )
                payload["leagueFormats"] = fmt.to_dict()
                payload["leagueFormatCoverage"] = league_format_capture.capture_coverage()
                format_pending = bool(fmt.leagues_pending)
                sharp_stopped = fmt.stopped_reason
            except Exception as exc:  # noqa: BLE001 — never fails the tx pass
                log.exception("sharp league-format capture pass failed")
                payload["leagueFormats"] = {"error": f"{type(exc).__name__}: {exc}"}
                if args.formats_only:
                    print(json.dumps(payload, indent=2))
                    return 1
            if not args.leagues:
                from src.trade import own_league_format_capture  # noqa: PLC0415

                own_budget = (
                    args.own_league_format_budget
                    if args.own_league_format_budget is not None
                    else own_league_format_capture.DEFAULT_RUN_BUDGET
                )
                payload["ownLeagueFormats"] = _capture_own_league_formats(
                    budget=own_budget, sharp_stopped_reason=sharp_stopped
                )
        print(json.dumps(payload, indent=2))
        # Partial is normal on a large graph — the next run continues
        # from the cursor, uncrawled leagues first.
        return 2 if (tx_pending or format_pending) else 0
    except Exception:  # noqa: BLE001
        log.exception("sharp transaction crawl failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
