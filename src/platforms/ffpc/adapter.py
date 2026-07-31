"""FFPC public-page adapter implementing the platform-neutral contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from src.platforms.assets import AssetResolver, load_manual_mappings
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedManagerSeason,
    NormalizedMembership,
    NormalizedMovement,
    NormalizedTransaction,
)
from src.platforms.ffpc.client import PublicFFPCClient
from src.platforms.ffpc.parser import FFPCParser



class FFPCAdapter:
    platform = "ffpc"

    def __init__(self, client: PublicFFPCClient, resolver: AssetResolver) -> None:
        self.client = client
        self.parser = FFPCParser(resolver)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
        *,
        players_directory: dict[str, dict[str, Any]] | None,
        repo_root: Path,
    ) -> "FFPCAdapter":
        manual_path = repo_root / str(
            config.get("assetMappingsFile") or "config/sharp/ffpc_asset_mappings.json"
        )
        resolver = AssetResolver.from_sleeper_directory(
            players_directory,
            manual_mappings=load_manual_mappings(manual_path),
        )
        client = PublicFFPCClient(
            cache_dir=repo_root / "data" / "intel" / "ffpc" / "raw",
            request_budget=int(config.get("requestBudgetPerRun") or 100),
            sleep_seconds=float(config.get("sleepSecondsBetweenCalls") or 1.5),
            cache_hours=float(config.get("cacheHours") or 12),
            timeout_seconds=float(config.get("timeoutSeconds") or 20),
            retry_limit=int(config.get("retryLimit") or 2),
            allowed_hosts=tuple(config.get("allowedHosts") or ("myffpc.com", "www.myffpc.com")),
            user_agent=str(config.get("userAgent") or "ChaseUpside-FFPC-Public-Reader/1.0"),
        )
        return cls(client, resolver)

    def fetch_source(
        self,
        source: dict[str, Any],
        *,
        force_refresh: bool = False,
        fixture_html: str | None = None,
    ) -> NormalizedBatch:
        league_id = str(source.get("sourceLeagueId") or "").strip()
        url = str(source.get("publicUrl") or "").strip()
        if not league_id:
            raise ValueError("FFPC sourceLeagueId is required")
        if fixture_html is None and not url:
            raise ValueError("FFPC publicUrl is required outside fixture mode")
        if fixture_html is None:
            fetched = self.client.fetch(url, force_refresh=force_refresh)
            html = fetched.content
            fetched_ms = fetched.fetched_ms
            from_cache = fetched.from_cache
        else:
            html = fixture_html
            fetched_ms = int(source.get("fixtureFetchedMs") or 0) or None
            from_cache = False
            url = url or f"fixture://ffpc/{league_id}"
        parsed = self.parser.parse(
            html,
            source_url=url,
            source_league_id=league_id,
            season=str(source.get("season") or "") or None,
            format_type=str(source.get("format") or "") or None,
            fetched_ms=fetched_ms,
            sharp_eligible=bool(source.get("sharpEligible", False)),
            verified_global_ids=source.get("verifiedGlobalUserIds") or (),
            season_complete=(
                bool(source.get("seasonComplete"))
                if "seasonComplete" in source
                else None
            ),
        )
        parsed.batch.counters["pagesFetched"] = int(
            fixture_html is None and not from_cache
        )
        parsed.batch.counters["pagesLoadedFromCache"] = int(
            fixture_html is None and from_cache
        )
        parsed.batch.counters["pagesParsed"] = 1 if parsed.page_types else 0
        parsed.batch.counters["parseFailures"] = (
            parsed.batch.counters.get("parseFailures", 0) + len(parsed.errors)
        )
        return parsed.batch

    # Contract methods remain intentionally narrow. A source entry may
    # contain several public URLs, but the first implementation parses
    # each configured page as one batch and lets ingestion deduplicate it.
    def _single(self, source: dict[str, Any]) -> NormalizedBatch:
        return self.fetch_source(source)

    def fetch_league_metadata(self, source: dict[str, Any]) -> NormalizedLeague:
        batch = self._single(source)
        if not batch.leagues:
            raise ValueError("FFPC page did not expose league metadata")
        return batch.leagues[0]

    def fetch_league_members(self, source: dict[str, Any]) -> Sequence[NormalizedManager]:
        return self._single(source).managers

    def fetch_standings(self, source: dict[str, Any]) -> Sequence[NormalizedManagerSeason]:
        return self._single(source).manager_seasons

    def fetch_rosters(self, source: dict[str, Any]) -> Sequence[NormalizedMembership]:
        return self._single(source).memberships

    def fetch_transactions(
        self, source: dict[str, Any]
    ) -> tuple[Sequence[NormalizedTransaction], Sequence[NormalizedMovement]]:
        batch = self._single(source)
        return batch.transactions, batch.movements

    def fetch_draft_results(self, source: dict[str, Any]) -> Sequence[dict[str, Any]]:
        # Read-only draft results are parsed for audit/mapping coverage;
        # they are not transaction movements and never become buy/sell
        # signals by themselves.
        return self._single(source).draft_results

    def fetch_manager_history(
        self, source_manager_id: str, sources: Sequence[dict[str, Any]]
    ) -> Sequence[NormalizedManagerSeason]:
        out = []
        for source in sources:
            for row in self.fetch_standings(source):
                if row.manager_key == f"ffpc:{source_manager_id}":
                    out.append(row)
        return out


def load_ffpc_config(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}
