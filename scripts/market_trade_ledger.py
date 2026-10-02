#!/usr/bin/env python3
"""Build the canonical Market Trade Ledger + coverage/evaluation report.

    python scripts/market_trade_ledger.py                     # build + report
    python scripts/market_trade_ledger.py --no-board          # skip residuals
    python scripts/market_trade_ledger.py --export PATH.json  # residuals vs that raw export
    python scripts/market_trade_ledger.py --allow-stale-target-scoring
    python scripts/market_trade_ledger.py --census [--out DIR]  # AL-2a census only

Reads (never writes) the raw archive, the intel ledger (read-only) and the
acquisition store; rebuilds ``data/market_trades/underlying_trades.sqlite``
wholesale and writes the report to ``data/market_trades/reports/``.  Nothing
here touches a canonical value.  Report contents are COUNTS — never another
league's trade contents.

``--census`` is READ-ONLY: it builds the ledger in memory, writes the AL-2a
target-format evidence census (aggregate, small-cell suppressed) as
``target_format_census_<UTC date>.json`` + ``.md`` into ``--out`` (default
``data/market_trades/reports/census/``, gitignored), and neither rebuilds the
canonical ledger nor writes the coverage report.  ``--archive-path``,
``--intel-ledger-path``, ``--acquisition-path`` and ``--lanes`` point any mode
at other stores (synthetic fixtures locally; the box defaults otherwise).

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


def write_census(result: dict, out_dir: Path, *, now: datetime) -> tuple[Path, Path]:
    """Write the publishable AL-2a census (JSON + markdown) into ``out_dir``."""
    from src.sources.signals import atomic_write_bytes  # noqa: PLC0415

    census = report.build_target_format_census(result)
    census["generatedAt"] = now.isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"target_format_census_{now.strftime('%Y-%m-%d')}"
    jpath, mpath = out_dir / f"{stem}.json", out_dir / f"{stem}.md"
    atomic_write_bytes(jpath, json.dumps(census, indent=1, default=str).encode("utf-8"))
    atomic_write_bytes(mpath, report.census_markdown(census).encode("utf-8"))
    return jpath, mpath


def main(argv: list[str] | None = None) -> int:
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
    parser.add_argument(
        "--census",
        action="store_true",
        help="write only the AL-2a target-format census (read-only; no ledger rebuild)",
    )
    parser.add_argument("--out", type=Path, default=None, help="census output directory")
    parser.add_argument("--archive-path", type=Path, default=None)
    parser.add_argument("--intel-ledger-path", type=Path, default=None)
    parser.add_argument("--acquisition-path", type=Path, default=None)
    parser.add_argument(
        "--lanes",
        default=None,
        help="comma-separated source lanes (default: all three)",
    )
    args = parser.parse_args(argv)

    repo = Path(__file__).resolve().parents[1]
    ctx = None
    if args.player_directory is not None:
        from src.trade.market_trade_normalize import IdentityContext  # noqa: PLC0415

        ctx = IdentityContext.from_directory(
            json.loads(args.player_directory.read_text(encoding="utf-8")),
            source=f"file:{args.player_directory.name}",
        )
    lanes = [s.strip() for s in args.lanes.split(",") if s.strip()] if args.lanes else None
    try:
        result = report.build_ledger(
            target_league=args.target_league,
            allow_stale_target_scoring=args.allow_stale_target_scoring,
            ctx=ctx,
            archive_path=args.archive_path,
            intel_ledger_path=args.intel_ledger_path,
            acquisition_path=args.acquisition_path,
            lanes=lanes,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"error: ledger build failed: {exc}", file=sys.stderr)
        return 1

    if args.census:
        out_dir = args.out or (Path(archive.DEFAULT_DIR) / "reports" / "census")
        try:
            jpath, mpath = write_census(result, out_dir, now=datetime.now(timezone.utc))
        except Exception as exc:  # noqa: BLE001
            print(f"error: census failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps({"census": str(jpath), "markdown": str(mpath)}, indent=1))
        return 0 if result["observations"] else 2

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
