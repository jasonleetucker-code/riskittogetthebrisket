#!/usr/bin/env python3
"""Refresh prepared news using existing providers and the local canonical board.

Production uses --watch: ESPN's target rotation and Sleeper's 24-hour directory
cache must survive between refreshes. No server import or request handler runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.news.context import espn_targets, player_meta, player_names  # noqa: E402
from src.news.prepared import load_news, refresh_prepared_news  # noqa: E402
from src.news.service import (  # noqa: E402
    DEFAULT_CACHE_TTL_S,
    FAILURE_CACHE_TTL_S,
    build_default_service,
)
from src.serving.artifacts import ArtifactStore  # noqa: E402

log = logging.getLogger("prepared-news-producer")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-dir", type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=DEFAULT_CACHE_TTL_S)
    args = parser.parse_args(argv)
    if args.interval <= 0:
        parser.error("--interval must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    store = ArtifactStore(args.serving_dir)
    targets: dict = {"items": []}
    service = build_default_service(
        provider_config={"espn_player": {"targets_supplier": lambda: targets["items"]}}
    )
    stopped = threading.Event()
    if args.watch:
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_args: stopped.set())
    while not stopped.is_set():
        started = time.perf_counter()
        success = False
        try:
            canonical = store.read_current("canonical-serving", "default")
            contract = json.loads(canonical.files["views/full.json"])
            if not isinstance(contract, dict) or not contract.get("playersArray"):
                raise ValueError("canonical player universe unavailable")
            targets["items"] = espn_targets(contract)
            published = refresh_prepared_news(
                store,
                service,
                player_names=player_names(contract),
                player_meta=player_meta(contract),
                input_generation=canonical.generation_id,
            )
            result = load_news(published)
            success = any(run.ok for run in result.provider_runs)
            log.info(
                "news refresh accepted generation=%s duration_ms=%.1f items=%d healthy_providers=%d retained=%s",
                published.generation_id,
                (time.perf_counter() - started) * 1000,
                len(result.items),
                sum(run.ok for run in result.provider_runs),
                result.retained,
            )
        except Exception as exc:
            # Detailed provider errors are already recorded by the aggregator;
            # filesystem/configuration exceptions need no private paths in logs.
            log.error(
                "news refresh rejected error=%s duration_ms=%.1f",
                type(exc).__name__,
                (time.perf_counter() - started) * 1000,
            )
        if not args.watch:
            return 0 if success else 1
        stopped.wait(args.interval if success else min(args.interval, FAILURE_CACHE_TTL_S))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
