#!/usr/bin/env python3
"""Build the canonical Market Trade Ledger + coverage/evaluation report.

    python scripts/market_trade_ledger.py                     # build + report
    python scripts/market_trade_ledger.py --no-board          # skip residuals
    python scripts/market_trade_ledger.py --export PATH.json  # residuals vs that raw export
    python scripts/market_trade_ledger.py --allow-stale-target-scoring

Reads (never writes) the raw archive, the intel ledger (read-only) and the
acquisition store; rebuilds ``data/market_trades/underlying_trades.sqlite``
wholesale and writes the report to ``data/market_trades/reports/``.  Nothing
here touches a canonical value.  Report contents are COUNTS — never another
league's trade contents.

Exit codes: 0 built · 1 error · 2 no observations in any lane.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.trade import market_trade_archive as archive  # noqa: E402
from src.trade import market_trade_report as report  # noqa: E402


def _latest_export(repo: Path) -> Path | None:
    files = sorted((repo / "exports" / "latest").glob("dynasty_data_*.json"))
    return files[-1] if files else None


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--target-league", default=report.DEFAULT_TARGET_LEAGUE)
    parser.add_argument("--allow-stale-target-scoring", action="store_true")
    parser.add_argument("--no-board", action="store_true")
    parser.add_argument("--export", type=Path, default=None)
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--print", action="store_true", help="print the full report JSON")
    parser.add_argument(
        "--player-directory",
        type=Path,
        default=None,
        help="Sleeper /players/nfl dump to resolve identities against (default: the app's cached copy)",
    )
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    ctx = None
    if args.player_directory is not None:
        from src.trade.market_trade_normalize import IdentityContext  # noqa: PLC0415

        ctx = IdentityContext.from_directory(
            json.loads(args.player_directory.read_text(encoding="utf-8")),
            source=f"file:{args.player_directory.name}",
        )
    try:
        result = report.build_ledger(
            target_league=args.target_league,
            allow_stale_target_scoring=args.allow_stale_target_scoring,
            ctx=ctx,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: ledger build failed: {exc}", file=sys.stderr)
        return 1

    contract = None
    board_date: date | None = None
    if not args.no_board:
        export = args.export or _latest_export(repo)
        if export is not None:
            from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

            raw = json.loads(export.read_text(encoding="utf-8"))
            contract = build_api_data_contract(raw)
            try:
                board_date = date.fromisoformat(str(raw.get("date")))
            except (TypeError, ValueError):
                board_date = None

    now = datetime.now(timezone.utc)
    payload = {
        "generatedAt": now.isoformat(),
        "coverage": report.coverage_report(result),
        "evaluation": report.evaluation_report(result, contract=contract, board_date=board_date),
    }
    if not args.no_persist:
        path = report.persist_canonical_ledger(
            result["grouping"].groups,
            built_at=now.isoformat(),
            extra_meta={"volume": result["grouping"].volume, "targetLeague": args.target_league},
        )
        payload["canonicalLedger"] = str(path)
        out_dir = Path(archive.DEFAULT_DIR) / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        # One file per UTC day (the daily timer builds once; a manual rebuild the
        # same day wins) plus latest.json — bounded growth, a daily history.
        rpath = out_dir / f"market_trade_ledger_{now.strftime('%Y-%m-%d')}.json"
        payload["reportPath"] = str(rpath)
        body = json.dumps(payload, indent=1, default=str).encode("utf-8")
        from src.sources.signals import atomic_write_bytes  # noqa: PLC0415

        atomic_write_bytes(rpath, body)
        atomic_write_bytes(out_dir / "latest.json", body)

    if args.print:
        print(json.dumps(payload, indent=1, default=str))
    else:
        cov = payload["coverage"]
        summary = {
            "rawSourceObservations": cov["rawSourceObservations"]["total"],
            "underlyingTrades": cov["underlyingTrades"],
            "dispositions": cov["dispositions"],
            "identity": {k: v.get("resolutionRate") for k, v in cov["identity"].items()},
            "topology": payload["evaluation"]["topology"]["byFitSuitability"],
            "reportPath": payload.get("reportPath"),
        }
        print(json.dumps(summary, indent=1, default=str))
    return 0 if result["observations"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
