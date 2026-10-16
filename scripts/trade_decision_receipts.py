"""Record AL-P5 DECISION receipts for served Best Offers runs.

``POST /api/trade/best-offers`` appends one line per served run to the
box-local, append-only run log (``src/trade/best_offers.py::record_run``,
``data/trade/best_offers/runs-YYYY-MM.jsonl``). This script READS that log
(never writes it) and appends one DECISION receipt per run to the box-local
learning store ``data/learning/receipts.sqlite`` through
``src/model_registry/producer_receipts.py`` section 5.

Recording after the fact keeps the serving path and its response untouched,
which is AL-P5's acceptance ("producer outputs byte-identical"). Point in time
still holds: each receipt's cutoff is the run line's own ``recordedAt``, taken
at serve time.

Idempotent: a receipt's identity is the run's own ``runId`` and its body is a
pure function of the stored line, so a re-run stores only duplicates.

Writes only when ``RISKIT_RECEIPTS_ENABLED=1`` (fail closed): the box's deploy
sets it; any other invocation builds and reports.

Exit codes:
  0  receipts built (and, when enabled, stored: written / duplicates only).
     Refused lines are listed in the summary (``refused``) but do not change
     the exit code: the log is append-only, so a line that can never form a
     valid receipt would otherwise fail every future deploy and train
     operators to ignore the warning.
  1  the store reported a conflict / rejection or could not be written --
     the failure an operator can act on
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from src.model_registry import producer_receipts as pr  # noqa: E402
from src.model_registry.learning_receipt import ReceiptError  # noqa: E402

EXIT_OK = 0
EXIT_PARTIAL = 1


def build_receipts(log_dir: Path) -> tuple[list[Any], list[dict[str, str]], int]:
    """``(receipts, refused, lines read)`` over every run-log line."""
    receipts: list[Any] = []
    refused: list[dict[str, str]] = []
    lines = 0
    if not log_dir.is_dir():
        return receipts, refused, lines
    from src.trade.best_offers import iter_run_log_lines  # noqa: PLC0415

    # The run log is read by its own owner (the writer), not by the learning
    # layer: src/model_registry may not import src/trade (learning boundary).
    for file_name, line in iter_run_log_lines(log_dir):
        lines += 1
        if line is None:
            refused.append({"item": file_name, "reason": "line is not a JSON object"})
            continue
        try:
            receipts.extend(pr.best_offers_decision_receipts(line, file_name=file_name))
        except (ReceiptError, ValueError) as exc:
            refused.append({"item": f"{file_name}#{line.get('runId')}", "reason": str(exc)})
    return receipts, refused, lines


def main(argv: list[str] | None = None) -> int:
    from src.trade.best_offers import BEST_OFFERS_RUN_LOG_DIR  # noqa: PLC0415

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--log-dir",
        type=Path,
        default=BEST_OFFERS_RUN_LOG_DIR,
        help="Best Offers run-log directory (default data/trade/best_offers)",
    )
    ap.add_argument(
        "--store",
        type=Path,
        default=None,
        help="learning-receipt store (default data/learning/receipts.sqlite)",
    )
    ap.add_argument("--dry-run", action="store_true", help="build and validate; write nothing")
    args = ap.parse_args(argv)

    receipts, refused, lines = build_receipts(args.log_dir)
    summary: dict[str, Any] = {
        "producer": pr.BEST_OFFERS_PRODUCER,
        "runLogPresent": args.log_dir.is_dir(),
        "linesRead": lines,
        "receipts": len(receipts),
        "refused": refused,
    }
    summary["refusedCount"] = len(refused)

    if args.dry_run or not pr.receipts_enabled():
        summary["written"] = None
        summary["notWrittenBecause"] = (
            "--dry-run"
            if args.dry_run
            else f"{pr.RECEIPTS_ENABLED_ENV} is not 1 (only the box's deploy writes receipts)"
        )
        print(json.dumps(summary, sort_keys=True))
        return EXIT_OK

    from src.model_registry.receipt_store import append_receipts  # noqa: PLC0415

    try:
        result = append_receipts(receipts, path=args.store)
    except (ReceiptError, OSError, sqlite3.Error) as exc:
        print(
            f"WARNING: trade decision receipts NOT written: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    summary.update(
        written=result["written"],
        duplicates=result["duplicates"],
        contentConflicts=result["contentConflicts"],
        rejected=result["rejected"],
    )
    print(json.dumps(summary, sort_keys=True))
    if result["contentConflicts"] or result["rejected"]:
        print(
            "WARNING: trade decision receipts recorded with conflicts / rejections",
            file=sys.stderr,
        )
        return EXIT_PARTIAL
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
