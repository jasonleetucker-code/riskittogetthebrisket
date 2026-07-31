"""Strict source-to-canonical asset mapping for unified Sharp signals.

Sleeper player ids remain the canonical player ids because the existing
ledger and frontend already use them.  FFPC names/ids are aliases.  The
resolver intentionally has no fuzzy fallback: an ambiguous or weak name
match is queued for review instead of contaminating a combined player row.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

def normalize_asset_name(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch)).lower()
    # Suffixes are intentionally preserved. Removing Jr./Sr./III can
    # collapse two real players into one identity; suffix variants belong
    # in the manual review/mapping layer instead.
    tokens = re.findall(r"[a-z0-9]+", raw)
    return " ".join(tokens)


def canonical_pick_id(
    season: str | int,
    round_number: str | int,
    original_owner_or_slot: str | int | None = None,
) -> str:
    base = f"pick:{str(season).strip()}:{int(round_number)}"
    owner = str(original_owner_or_slot or "").strip()
    return f"{base}:{owner}" if owner else base


@dataclass(frozen=True)
class AssetCandidate:
    canonical_asset_id: str
    display_name: str
    normalized_name: str
    nfl_team: str | None = None
    position: str | None = None
    external_ids: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class AssetResolution:
    canonical_asset_id: str | None
    match_method: str
    confidence: float
    normalized_name: str
    candidates: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return bool(self.canonical_asset_id)


class AssetResolver:
    """Resolve FFPC source assets onto the existing Sleeper-keyed catalog."""

    def __init__(
        self,
        candidates: Iterable[AssetCandidate],
        *,
        manual_mappings: dict[str, str] | None = None,
    ) -> None:
        self._manual = {str(k): str(v) for k, v in (manual_mappings or {}).items()}
        self._by_id: dict[tuple[str, str], AssetCandidate] = {}
        self._by_name: dict[str, list[AssetCandidate]] = {}
        for item in candidates:
            self._by_name.setdefault(item.normalized_name, []).append(item)
            self._by_id[("sleeper", item.canonical_asset_id)] = item
            for platform, value in item.external_ids.items():
                if value:
                    self._by_id[(str(platform).lower(), str(value))] = item

    @classmethod
    def from_sleeper_directory(
        cls,
        players: dict[str, dict[str, Any]] | None,
        *,
        manual_mappings: dict[str, str] | None = None,
    ) -> "AssetResolver":
        candidates: list[AssetCandidate] = []
        for sleeper_id, raw in (players or {}).items():
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("full_name") or raw.get("search_full_name") or "").strip()
            normalized = normalize_asset_name(name)
            if not normalized:
                continue
            external = {}
            for key, platform in (
                ("gsis_id", "gsis"),
                ("espn_id", "espn"),
                ("yahoo_id", "yahoo"),
                ("fantasy_data_id", "fantasydata"),
            ):
                value = str(raw.get(key) or "").strip()
                if value:
                    external[platform] = value
            candidates.append(
                AssetCandidate(
                    canonical_asset_id=str(sleeper_id),
                    display_name=name,
                    normalized_name=normalized,
                    nfl_team=str(raw.get("team") or "").strip().upper() or None,
                    position=str(raw.get("position") or "").strip().upper() or None,
                    external_ids=external,
                )
            )
        return cls(candidates, manual_mappings=manual_mappings)

    def resolve(
        self,
        *,
        platform: str,
        source_asset_id: str | None,
        name: str | None,
        nfl_team: str | None = None,
        position: str | None = None,
        asset_type: str = "player",
        pick_season: str | int | None = None,
        pick_round: str | int | None = None,
        pick_original_owner: str | int | None = None,
    ) -> AssetResolution:
        platform = str(platform or "").strip().lower()
        source_id = str(source_asset_id or "").strip()
        if asset_type == "pick":
            if pick_season and pick_round:
                return AssetResolution(
                    canonical_asset_id=canonical_pick_id(
                        pick_season, pick_round, pick_original_owner
                    ),
                    match_method="canonical_pick",
                    confidence=1.0,
                    normalized_name=normalize_asset_name(name),
                )
            return AssetResolution(
                canonical_asset_id=None,
                match_method="unresolved",
                confidence=0.0,
                normalized_name=normalize_asset_name(name),
                reason="missing_pick_season_or_round",
            )

        manual_key = f"{platform}:{source_id}" if source_id else ""
        if manual_key and manual_key in self._manual:
            return AssetResolution(
                canonical_asset_id=self._manual[manual_key],
                match_method="manual_mapping",
                confidence=1.0,
                normalized_name=normalize_asset_name(name),
            )

        if source_id:
            candidate = self._by_id.get((platform, source_id))
            if candidate:
                return AssetResolution(
                    canonical_asset_id=candidate.canonical_asset_id,
                    match_method="authoritative_external_id",
                    confidence=1.0,
                    normalized_name=candidate.normalized_name,
                )

        normalized = normalize_asset_name(name)
        if not normalized:
            return AssetResolution(
                canonical_asset_id=None,
                match_method="unresolved",
                confidence=0.0,
                normalized_name="",
                reason="missing_player_name",
            )
        matches = list(self._by_name.get(normalized) or [])
        team = str(nfl_team or "").strip().upper()
        pos = str(position or "").strip().upper()

        if team and pos:
            exact = [c for c in matches if c.nfl_team == team and c.position == pos]
            if len(exact) == 1:
                return AssetResolution(
                    exact[0].canonical_asset_id,
                    "exact_name_team_position",
                    0.98,
                    normalized,
                )
            if len(exact) > 1:
                return self._ambiguous(normalized, exact, "ambiguous_name_team_position")

        if pos:
            exact = [c for c in matches if c.position == pos]
            if len(exact) == 1:
                return AssetResolution(
                    exact[0].canonical_asset_id,
                    "exact_name_position",
                    0.93,
                    normalized,
                )
            if len(exact) > 1:
                return self._ambiguous(normalized, exact, "ambiguous_name_position")

        # Exact name alone is accepted only when it is globally unique.
        if len(matches) == 1:
            return AssetResolution(
                matches[0].canonical_asset_id,
                "unique_exact_name",
                0.90,
                normalized,
            )
        if matches:
            return self._ambiguous(normalized, matches, "ambiguous_exact_name")
        return AssetResolution(
            canonical_asset_id=None,
            match_method="unresolved",
            confidence=0.0,
            normalized_name=normalized,
            reason="no_exact_match",
        )

    @staticmethod
    def _ambiguous(
        normalized: str,
        matches: list[AssetCandidate],
        reason: str,
    ) -> AssetResolution:
        return AssetResolution(
            canonical_asset_id=None,
            match_method="ambiguous",
            confidence=0.0,
            normalized_name=normalized,
            candidates=tuple(sorted(c.canonical_asset_id for c in matches)),
            reason=reason,
        )


def load_manual_mappings(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw.items()
        if str(key).strip() and str(value).strip()
    }
