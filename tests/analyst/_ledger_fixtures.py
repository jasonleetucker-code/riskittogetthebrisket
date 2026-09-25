"""Shared builders for the analyst ledger tests.  No network, no live data."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.analyst.claim import (
    AnalystClaim,
    AssetSide,
    Condition,
    GameType,
    Provenance,
    SourceRef,
    TakeType,
)
from src.analyst.stance import SourceLabel, Stance, stance_for_label
from src.analyst.store import ContentRecord, LedgerEntry, TimePrecision

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
PLAYER = "player:4984"
OTHER_PLAYER = "player:6794"
PICK = "mpick:2027:r1"


def at(days: float = 0, hours: float = 0) -> datetime:
    return T0 + timedelta(days=days, hours=hours)


def content(
    content_id: str = "ep-1",
    *,
    analysts: tuple[str, ...] = ("alice",),
    platform: str = "podcast",
    show_id: str = "show-a",
    published: datetime | None = None,
    precision: TimePrecision = TimePrecision.INSTANT,
    observed: datetime | None = None,
    origin: str = "test:fixture",
    url: str = "",
) -> ContentRecord:
    return ContentRecord(
        platform=platform,
        content_id=content_id,
        analyst_ids=analysts,
        published_at=published or at(0),
        origin=origin,
        show_id=show_id,
        url=url or f"https://example.test/{content_id}",
        published_precision=precision,
        observed_at=observed,
    )


def entry(
    *,
    analyst: str = "alice",
    content_id: str = "ep-1",
    platform: str = "podcast",
    asset_key: str = PLAYER,
    label: SourceLabel = SourceLabel.BUY,
    said: datetime | None = None,
    precision: TimePrecision = TimePrecision.INSTANT,
    game_type: GameType = GameType.DYNASTY,
    asset_side: AssetSide = AssetSide.OFFENSE,
    thesis_id: str = "",
    supersedes: str = "",
    discovered: datetime | None = None,
    origin: str = "test:fixture",
    parser_version: str = "v1",
) -> LedgerEntry:
    stance = stance_for_label(label)
    conditions = (Condition("only if cheap"),) if stance is Stance.CONDITIONAL_SELL else ()
    claim = AnalystClaim(
        source=SourceRef(analyst_id=analyst, content_id=content_id, platform=platform),
        asset_key=asset_key,
        stance=stance,
        source_label=label,
        take_type=TakeType.BUY_SELL_VALUE,
        said_at=said or at(0),
        provenance=Provenance.TRANSCRIPT_PARAPHRASE,
        game_type=game_type,
        asset_side=asset_side,
        conditions=conditions,
        thesis_id=thesis_id,
        supersedes=supersedes,
        discovered_at=discovered,
    )
    return LedgerEntry(
        claim=claim, origin=origin, parser_version=parser_version, said_at_precision=precision
    )
