"""Platform-neutral records for Sharp Tracker ingestion.

Adapters translate source-specific APIs/HTML into these validated records.
The ledger never imports or understands a platform's wire format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

PLATFORM_SLEEPER = "sleeper"
PLATFORM_FFPC = "ffpc"
SUPPORTED_PLATFORMS = (PLATFORM_SLEEPER, PLATFORM_FFPC)

IDENTITY_GLOBAL_VERIFIED = "global_verified"
IDENTITY_GLOBAL_UNVERIFIED = "global_unverified"
IDENTITY_LEAGUE_SCOPED_TEAM = "league_scoped_team"
IDENTITY_NAME_ONLY = "name_only"

QUAL_AUTOMATED = "automated_qualified"
QUAL_CURATED = "curated_high_stakes"
QUAL_PROVISIONAL = "provisional"
QUAL_INSUFFICIENT = "insufficient_history"

# Descriptive aliases exported by the package surface.  Keep the short
# names above for backward compatibility with the first adapter draft.
QUALIFICATION_AUTOMATED = QUAL_AUTOMATED
QUALIFICATION_CURATED = QUAL_CURATED
QUALIFICATION_PROVISIONAL = QUAL_PROVISIONAL
QUALIFICATION_INSUFFICIENT = QUAL_INSUFFICIENT


def scoped_key(platform: str, source_id: str) -> str:
    platform = str(platform or "").strip().lower()
    source_id = str(source_id or "").strip()
    if platform not in SUPPORTED_PLATFORMS:
        raise ValueError(f"unsupported platform: {platform!r}")
    if not source_id:
        raise ValueError("source id cannot be empty")
    return f"{platform}:{source_id}"


@dataclass(frozen=True)
class NormalizedManager:
    platform: str
    source_manager_id: str
    manager_key: str
    username: str | None = None
    display_name: str | None = None
    source_identity_type: str = IDENTITY_GLOBAL_UNVERIFIED
    identity_scope: str = "platform"
    identity_confidence: float = 0.5
    canonical_manager_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        platform: str,
        source_manager_id: str,
        **kwargs: Any,
    ) -> "NormalizedManager":
        return cls(
            platform=platform,
            source_manager_id=str(source_manager_id),
            manager_key=scoped_key(platform, str(source_manager_id)),
            **kwargs,
        )


@dataclass(frozen=True)
class NormalizedLeague:
    platform: str
    source_league_id: str
    league_key: str
    season: str | None = None
    previous_source_league_id: str | None = None
    name: str | None = None
    total_rosters: int | None = None
    format_type: str | None = None
    is_dynasty: bool | None = None
    sharp_eligible: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        platform: str,
        source_league_id: str,
        **kwargs: Any,
    ) -> "NormalizedLeague":
        return cls(
            platform=platform,
            source_league_id=str(source_league_id),
            league_key=scoped_key(platform, str(source_league_id)),
            **kwargs,
        )


@dataclass(frozen=True)
class NormalizedMembership:
    platform: str
    league_key: str
    manager_key: str
    source_team_id: str | None = None
    roster_id: str | None = None
    team_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedTransaction:
    platform: str
    source_transaction_id: str
    transaction_key: str
    league_key: str
    season: str | None
    week: int | None
    transaction_type: str
    status: str
    created_ms: int
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        platform: str,
        source_transaction_id: str,
        *,
        league_key: str,
        season: str | None,
        week: int | None,
        transaction_type: str,
        status: str,
        created_ms: int,
        **kwargs: Any,
    ) -> "NormalizedTransaction":
        return cls(
            platform=platform,
            source_transaction_id=str(source_transaction_id),
            transaction_key=scoped_key(platform, str(source_transaction_id)),
            league_key=league_key,
            season=season,
            week=week,
            transaction_type=transaction_type,
            status=status,
            created_ms=int(created_ms),
            **kwargs,
        )


@dataclass(frozen=True)
class NormalizedMovement:
    platform: str
    source_movement_id: str
    movement_key: str
    transaction_key: str
    league_key: str
    canonical_asset_id: str | None
    source_asset_id: str
    source_name: str | None
    asset_type: str
    action: str
    manager_key: str
    roster_id: str | None
    counterparty_manager_key: str | None
    timestamp_ms: int
    week: int | None = None
    faab_bid: int | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        platform: str,
        source_movement_id: str,
        **kwargs: Any,
    ) -> "NormalizedMovement":
        return cls(
            platform=platform,
            source_movement_id=str(source_movement_id),
            movement_key=scoped_key(platform, str(source_movement_id)),
            **kwargs,
        )


@dataclass(frozen=True)
class NormalizedManagerSeason:
    platform: str
    league_key: str
    season: str
    manager_key: str
    roster_id: str | None = None
    wins: int | None = None
    losses: int | None = None
    ties: int | None = None
    points_for: float | None = None
    points_against: float | None = None
    made_playoffs: bool | None = None
    is_champion: bool | None = None
    is_runner_up: bool | None = None
    finish_rank: int | None = None
    team_count: int | None = None
    is_complete: bool = False
    sharp_eligible: bool = False
    source_identity_type: str = IDENTITY_GLOBAL_UNVERIFIED
    evidence_status: str = QUAL_INSUFFICIENT
    exclusion_reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedBatch:
    platform: str
    managers: list[NormalizedManager] = field(default_factory=list)
    leagues: list[NormalizedLeague] = field(default_factory=list)
    memberships: list[NormalizedMembership] = field(default_factory=list)
    transactions: list[NormalizedTransaction] = field(default_factory=list)
    movements: list[NormalizedMovement] = field(default_factory=list)
    manager_seasons: list[NormalizedManagerSeason] = field(default_factory=list)
    draft_results: list[dict[str, Any]] = field(default_factory=list)
    counters: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class PlatformAdapter(Protocol):
    platform: str

    def fetch_league_metadata(self, source: dict[str, Any]) -> NormalizedLeague: ...

    def fetch_league_members(self, source: dict[str, Any]) -> Sequence[NormalizedManager]: ...

    def fetch_standings(self, source: dict[str, Any]) -> Sequence[NormalizedManagerSeason]: ...

    def fetch_rosters(self, source: dict[str, Any]) -> Sequence[NormalizedMembership]: ...

    def fetch_transactions(
        self, source: dict[str, Any]
    ) -> tuple[Sequence[NormalizedTransaction], Sequence[NormalizedMovement]]: ...

    def fetch_draft_results(self, source: dict[str, Any]) -> Sequence[dict[str, Any]]: ...

    def fetch_manager_history(
        self, source_manager_id: str, sources: Sequence[dict[str, Any]]
    ) -> Sequence[NormalizedManagerSeason]: ...
