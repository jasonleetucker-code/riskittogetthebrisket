"""Reproducible same-board byte/parse comparison; never field latency evidence."""

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-board-savings-percent", type=float, default=40)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use the input's factual league card, never a provider",
    )
    args = parser.parse_args()
    if not 0 <= args.minimum_board_savings_percent < 100:
        parser.error("--minimum-board-savings-percent must be in [0, 100)")
    source_bytes = args.input.read_bytes()
    raw = json.loads(source_bytes)
    from src.api import data_contract
    from src.serving.builder import build_generation
    from src.serving.serialization import validate_generation

    if args.offline:
        import socket

        def no_network(*args, **kwargs):
            raise RuntimeError("network disabled for offline payload measurement")

        socket.create_connection = no_network
        sleeper = raw.get("sleeper") or {}
        card = sleeper.get("scoringSettings") or {}
        data_contract._LEAGUE_CONTEXT_CACHE.update(
            {
                "context": {
                    "roster_count": len(sleeper.get("teams") or []) or 12,
                    "bonus_rec_te": float(card.get("bonus_rec_te") or 0),
                    "fetched_from_sleeper": False,
                },
                "fetched_at": time.time(),
            }
        )
    started = time.perf_counter()
    candidate = build_generation(
        raw, {"type": "measurement", "producedAt": raw.get("scrapeTimestamp")}
    )
    elapsed = time.perf_counter() - started
    validate_generation(candidate)
    report = {
        "inputSha256": hashlib.sha256(source_bytes).hexdigest(),
        "environment": "local offline recorded input"
        if args.offline
        else "local configured producer",
        "python": sys.version.split()[0],
        "boardGeneration": candidate.generation_id,
        "players": len(candidate.contract["playersArray"]),
        "buildSeconds": round(elapsed, 3),
        "canonicalProjectionParity": True,
        "views": {},
        "limitation": "Byte and Python parse measurements only; no browser or production latency claim.",
    }
    for name, view in candidate.views.items():
        samples = []
        for _ in range(7):
            start = time.perf_counter()
            json.loads(view.raw)
            samples.append((time.perf_counter() - start) * 1000)
        report["views"][name] = {
            "decodedBytes": len(view.raw),
            "gzipBytes": len(view.gzip),
            "pythonParseMedianMs": round(statistics.median(samples), 3),
        }
    baseline = report["views"]["array"]["gzipBytes"]
    for name in ("rankings", "trade", "catalog"):
        report["views"][name]["gzipReductionVsArrayPercent"] = round(
            100 * (1 - report["views"][name]["gzipBytes"] / baseline), 2
        )
    report["payloadBudget"] = {
        "minimumBoardSavingsPercent": args.minimum_board_savings_percent,
        "passed": all(
            report["views"][name]["gzipReductionVsArrayPercent"]
            >= args.minimum_board_savings_percent
            for name in ("rankings", "trade")
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["payloadBudget"]["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    # This utility never publishes an artifact, writes history, or starts jobs.
    os.environ.setdefault("RISKIT_FEATURE_LEDGER_RANK_CHANGE", "0")
    main()
