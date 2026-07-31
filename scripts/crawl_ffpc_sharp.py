#!/usr/bin/env python3
"""Read configured FFPC public pages into the unified Sharp ledger."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.intel import platform_ledger  # noqa: E402
from src.platforms.base import (  # noqa: E402
    IDENTITY_GLOBAL_UNVERIFIED,
    NormalizedManager,
)
from src.platforms.ffpc.adapter import FFPCAdapter, load_ffpc_config  # noqa: E402
from src.sharp import market as sharp_market  # noqa: E402

log = logging.getLogger("crawl_ffpc_sharp")
REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "config" / "sharp" / "ffpc_sources.json"
PLAYERS_CACHE = REPO_ROOT / "data" / "intel" / "ffpc" / "sleeper_players.json"


def _players_directory(*, force: bool = False) -> dict[str, dict[str, Any]]:
    if PLAYERS_CACHE.exists() and not force:
        try:
            raw = json.loads(PLAYERS_CACHE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except (OSError, ValueError):
            pass
    from src.api import sleeper_overlay

    raw = sleeper_overlay._http_get_json("https://api.sleeper.app/v1/players/nfl")
    if not isinstance(raw, dict):
        raise RuntimeError("Sleeper player directory unavailable for canonical mapping")
    PLAYERS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    PLAYERS_CACHE.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")
    return raw


def _merge_counters(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value or 0)


def _sources(config: dict[str, Any], only: str | None) -> list[dict[str, Any]]:
    sources = [s for s in config.get("seedLeagues") or [] if isinstance(s, dict)]
    sources = [s for s in sources if bool(s.get("enabled", True))]
    if only:
        sources = [s for s in sources if str(s.get("sourceLeagueId")) == only]
    return sources


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-only", action="store_true")
    parser.add_argument("--source-league")
    parser.add_argument("--budget", type=int)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--players-fixture", type=Path)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    config = load_ffpc_config(args.config)
    if config.get("mode", "public_only") != "public_only":
        raise SystemExit("Only FFPC mode=public_only is supported")
    if bool((config.get("authenticatedApi") or {}).get("enabled")):
        raise SystemExit(
            "Authenticated/undocumented FFPC access is deliberately unsupported by this collector"
        )
    if not config.get("enabled") and not args.fixture:
        print(json.dumps({"status": "disabled", "config": str(args.config)}, indent=2))
        return 0
    if args.budget is not None:
        config["requestBudgetPerRun"] = args.budget

    started = int(time.time() * 1000)
    run_id = f"ffpc-{started}-{uuid.uuid4().hex[:8]}"
    counters: dict[str, int] = {}
    reports = []
    try:
        if args.players_fixture:
            loaded = json.loads(args.players_fixture.read_text(encoding="utf-8"))
            players = loaded if isinstance(loaded, dict) else {}
        elif args.fixture:
            # Fixture mode is fully offline by design. Unmapped fixture
            # assets remain reviewable unless a players fixture is given.
            players = {}
        else:
            players = _players_directory(force=args.force_refresh)
        adapter = FFPCAdapter.from_config(
            config, players_directory=players, repo_root=REPO_ROOT
        )
        if not args.dry_run:
            platform_ledger.ensure_platform_schema().close()
            platform_ledger.hydrate_sleeper_asset_catalog(players)

        if args.fixture:
            source = {
                "sourceLeagueId": args.source_league or "fixture",
                "publicUrl": "https://myffpc.com/fixture",
                "season": "2026",
                "format": "dynasty",
                "fixtureFetchedMs": started,
            }
            sources = [source]
            fixture_html = args.fixture.read_text(encoding="utf-8")
        else:
            sources = _sources(config, args.source_league)
            fixture_html = None
        if not sources:
            print(json.dumps({"status": "no_sources", "enabled": True}, indent=2))
            return 0

        for source in sources:
            page_sources = source.get("publicUrls") or [source.get("publicUrl")]
            for url in [str(value or "").strip() for value in page_sources if str(value or "").strip()]:
                page_source = {**source, "publicUrl": url}
                batch = adapter.fetch_source(
                    page_source,
                    force_refresh=args.force_refresh,
                    fixture_html=fixture_html,
                )
                _merge_counters(counters, batch.counters)
                if args.dry_run:
                    reports.append(
                        {
                            "sourceLeagueId": source.get("sourceLeagueId"),
                            "url": url,
                            "managers": len(batch.managers),
                            "transactions": len(batch.transactions),
                            "movements": len(batch.movements),
                            "managerSeasons": len(batch.manager_seasons),
                            "warnings": batch.warnings,
                        }
                    )
                else:
                    ingest = platform_ledger.ingest_batch(batch)
                    ingest_report = ingest.to_dict()
                    counters["movementsInserted"] = counters.get("movementsInserted", 0) + ingest.movements_inserted
                    counters["movementsSkipped"] = counters.get("movementsSkipped", 0) + ingest.movements_skipped
                    counters["transactionsDeduplicated"] = counters.get("transactionsDeduplicated", 0) + max(
                        0, ingest.transactions_seen - ingest.transactions_inserted
                    )
                    reports.append(
                        {
                            "sourceLeagueId": source.get("sourceLeagueId"),
                            "url": url,
                            "ingest": ingest_report,
                            "warnings": batch.warnings,
                        }
                    )

        # Curated identities are explicit configuration records. They do
        # not become Sharp-v2 qualifiers; market selection reads their
        # separate qualification method and configured weight.
        if not args.dry_run:
            conn = platform_ledger.ensure_platform_schema()
            try:
                for raw in config.get("curatedManagers") or []:
                    if not isinstance(raw, dict):
                        continue
                    key = str(raw.get("managerKey") or "").strip()
                    if not key.startswith("ffpc:"):
                        continue
                    source_id = key.split(":", 1)[1]
                    platform_ledger.upsert_manager(
                        NormalizedManager.build(
                            "ffpc",
                            source_id,
                            display_name=str(raw.get("publicDisplayName") or "") or None,
                            source_identity_type=str(
                                raw.get("sourceIdentityType") or IDENTITY_GLOBAL_UNVERIFIED
                            ),
                            identity_scope="platform",
                            identity_confidence=float(raw.get("identityConfidence") or 0.8),
                            metadata={
                                "qualificationMethod": "curated_high_stakes",
                                "sourceRationale": raw.get("sourceRationale"),
                                "sourceReferences": raw.get("sourceReferences") or [],
                                "verified": bool(raw.get("verified")),
                            },
                        ),
                        conn=conn,
                    )
                conn.commit()
            finally:
                conn.close()

        finished = int(time.time() * 1000)
        if not args.dry_run:
            automated, _ = sharp_market.cohort_members(
                qualification="automated",
                ffpc_config=config,
            )
            curated, _ = sharp_market.cohort_members(
                qualification="curated",
                ffpc_config=config,
            )
            counters["automatedFfpcQualifiers"] = sum(
                1 for member in automated if member.platform == "ffpc"
            )
            counters["curatedFfpcContributors"] = sum(
                1 for member in curated if member.platform == "ffpc"
            )
            platform_ledger.record_ingestion_run(
                run_id=run_id,
                platform="ffpc",
                source_ref=args.source_league,
                started_ms=started,
                finished_ms=finished,
                status="success",
                counters=counters,
                metadata={"reports": reports, "publicOnly": True},
            )
        payload = {
            "status": "dry_run" if args.dry_run else "success",
            "runId": run_id,
            "counters": counters,
            "reports": reports,
            "coverage": (
                {} if args.dry_run else platform_ledger.platform_coverage()
            ),
        }
        print(json.dumps(payload, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001
        log.exception("FFPC public ingestion failed")
        try:
            if args.dry_run:
                return 1
            platform_ledger.record_ingestion_run(
                run_id=run_id,
                platform="ffpc",
                source_ref=args.source_league,
                started_ms=started,
                finished_ms=int(time.time() * 1000),
                status="failed",
                counters=counters,
                error={"type": type(exc).__name__, "message": str(exc)},
                metadata={"publicOnly": True},
            )
        except Exception:  # noqa: BLE001
            log.exception("could not persist FFPC failure report")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
