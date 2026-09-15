#!/usr/bin/env python3
"""Run the shared VPS source cycle in a standalone process; never import server."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from src.serving.artifacts import (  # noqa: E402 — direct script execution needs repo root
    ArtifactStore,
    MissingArtifact,
    PublishLockTimeout,
    _mkdir,
    _publish_lock,
)
from src.serving.producer import (  # noqa: E402
    ProducerConfig,
    run_source_cycle,
    source_parity_contract,
)
from src.serving.producer_status import ProducerJournal  # noqa: E402

log = logging.getLogger(__name__)


def _accepted_raw(store: ArtifactStore, bootstrap_path: Path | None) -> dict:
    from src.serving.serialization import ASSET, KEY, load_generation

    try:
        return load_generation(store.read_current(ASSET, KEY)).raw
    except MissingArtifact:
        if bootstrap_path is None:
            raise ValueError(
                "No accepted serving generation. Bootstrap requires --accepted-raw PATH chosen from the accepted legacy input."
            ) from None
        raw = json.loads(bootstrap_path.read_bytes())
        if not isinstance(raw, dict) or not raw.get("players"):
            raise ValueError(
                "--accepted-raw must contain the accepted nonempty raw players payload"
            )
        return raw


def backfill_history(config: ProducerConfig) -> int:
    """Optional maintenance, sharing the source lease and original history owner."""
    from src.api import source_history

    _mkdir(config.serving_root)
    with _publish_lock(config.serving_root / "producer.lock", 0):
        history_path = source_history.HISTORY_PATH
        if history_path.exists() and history_path.stat().st_size:
            return 0
        exports = sorted(config.data_dir.glob("dynasty_data_*.json"))
        return source_history.backfill_from_exports(exports) if exports else 0


async def _run(config: ProducerConfig, bootstrap_path: Path | None) -> int:
    from src.serving.builder import build_generation, record_accepted_generation
    from src.serving.serialization import publish_generation
    from src.serving.input_manifest import capture_canonical_inputs

    store = ArtifactStore(config.artifact_root)
    journal = ProducerJournal(store, establish_ownership=True)

    async def publish(raw, source):
        manifest = capture_canonical_inputs(raw, repo_dir=config.repo_dir)
        journal.input_manifest = manifest.as_dict()
        # This manifest explicitly names unresolved dependencies. Never use its
        # fingerprint to skip canonical builds until those inputs are captured.
        candidate = build_generation(raw, source, is_fresh_scrape=True)
        artifact = publish_generation(
            candidate,
            store=store,
            input_generations={
                **manifest.input_generations,
                "sourceCycle": journal.source_parity_hash,
            },
        )
        journal.accepted_generation = artifact.generation_id
        record_accepted_generation(candidate)
        try:
            from src.serving.league_views import refresh_league_serving

            report = refresh_league_serving(store=store)
            published = len(report.get("published") or [])
            failed = len(report.get("failed") or [])
            journal.league_report = {
                "outcome": "busy"
                if report.get("outcome") == "busy"
                else "partial"
                if published and failed
                else "failed"
                if failed
                else "success",
                "published": published,
                "failed": failed,
            }
        except Exception:  # noqa: BLE001 — preserve the accepted canonical generation
            journal.league_report = {"outcome": "failed"}
            journal.event("league_refresh_failed", level="warning")
            log.exception("League serving refresh failed after canonical publication")

    result = await run_source_cycle(
        config,
        lambda: _accepted_raw(store, bootstrap_path),
        publish=publish,
        progress=journal.progress,
        event=journal.event,
        completed=journal.completed,
    )
    print(
        json.dumps(
            {
                "outcome": result.outcome,
                "durationSeconds": round(result.duration, 3),
                "playerCount": result.player_count,
                "siteCount": result.site_count,
                "acceptedGeneration": journal.accepted_generation or None,
            }
        )
    )
    return {"success": 0, "busy": 3}.get(result.outcome, 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Print ownership plan; no writes or providers"
    )
    parser.add_argument(
        "--accepted-raw",
        type=Path,
        help="Explicit accepted legacy raw input for first-generation bootstrap only",
    )
    parser.add_argument(
        "--backfill-history",
        action="store_true",
        help="Only backfill the existing history if empty; no scrape",
    )
    parser.add_argument(
        "--artifact-root", type=Path, help="Private serving directory (default RISKIT_SERVING_DIR)"
    )
    parser.add_argument("--timeout-seconds", type=float, default=7200)
    parser.add_argument(
        "--lease-wait-seconds",
        type=float,
        default=0,
        help="Standalone service admission wait; default immediate busy exit",
    )
    args = parser.parse_args(argv)
    if not 0 < args.timeout_seconds <= 86400:
        parser.error("--timeout-seconds must be in (0, 86400]")
    if not 0 <= args.lease_wait_seconds <= 9000:
        parser.error("--lease-wait-seconds must be in [0, 9000]")
    config = ProducerConfig(
        repo_dir=REPO_DIR,
        data_dir=REPO_DIR / "data",
        artifact_root=args.artifact_root,
        timeout_seconds=args.timeout_seconds,
        lease_wait_seconds=args.lease_wait_seconds,
        disk_min_mb=int(os.getenv("DISK_SPACE_MIN_MB", "500")),
        publication_requires_disk=True,
    )
    if args.dry_run:
        print(
            json.dumps(
                {
                    "mode": "history-maintenance" if args.backfill_history else "source-cycle",
                    "sourceParity": source_parity_contract(),
                    "artifactRoot": str(config.serving_root),
                },
                indent=2,
            )
        )
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        if args.backfill_history:
            print(json.dumps({"outcome": "success", "snapshotsWritten": backfill_history(config)}))
            return 0
        return asyncio.run(_run(config, args.accepted_raw))
    except PublishLockTimeout:
        print(json.dumps({"outcome": "busy"}))
        return 3
    except Exception as exc:  # noqa: BLE001 — CLI should return a failed unit status
        log.error("Source producer failed: %s", type(exc).__name__)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
