from __future__ import annotations

import csv
import difflib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Final

from src.utils import normalize_player_name, normalize_position_family

from .constants import (
    LOW_CONFIDENCE_THRESHOLD,
    POS_SOURCE_TO_CANONICAL,
    TEAM_CANONICAL_ALIASES,
    TEAM_GUIDE_TO_CANONICAL,
)

_NICKNAME_MAP: Final[dict[str, str]] = {
    "ken": "kenneth",
    "mike": "michael",
    "pat": "patrick",
    "dj": "d j",
}

_POSITION_COMPATIBILITY: Final[dict[str, set[str]]] = {
    # Clay IDP edge roles are frequently mapped as DL while canonical ecosystems may label EDGE as LB.
    "DL": {"DL", "LB"},
    "LB": {"LB", "DL"},
    "DB": {"DB"},
    "QB": {"QB"},
    "RB": {"RB"},
    "WR": {"WR"},
    "TE": {"TE"},
}


def normalize_team_code(team: str | None) -> str:
    raw = str(team or "").strip().upper()
    if not raw:
        return ""
    return TEAM_GUIDE_TO_CANONICAL.get(raw, TEAM_CANONICAL_ALIASES.get(raw, raw))


def normalize_position_code(pos: str | None) -> str:
    if not pos:
        return ""
    raw = str(pos).strip().upper()
    return POS_SOURCE_TO_CANONICAL.get(raw, normalize_position_family(raw))


def _safe_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _norm_aliases(norm_name: str) -> list[str]:
    tokens = [t for t in norm_name.split(" ") if t]
    if not tokens:
        return []

    aliases: set[str] = set()
    if len(tokens) >= 3 and len(tokens[1]) == 1:
        aliases.add(" ".join([tokens[0], *tokens[2:]]))

    first = tokens[0]
    if first in _NICKNAME_MAP:
        mapped = _NICKNAME_MAP[first].split(" ")
        aliases.add(" ".join([*mapped, *tokens[1:]]))
    return sorted(a for a in aliases if a)


@dataclass(frozen=True)
class CanonicalPlayer:
    canonical_player_id: str
    canonical_name: str
    normalized_name: str
    position_canonical: str
    team_canonical: str
    sleeper_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MatchResult:
    match_status: str
    match_confidence: float
    match_method: str
    canonical_player_id: str | None
    player_name_canonical: str | None
    candidate_ids: list[str]
    candidate_names: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def low_confidence(self) -> bool:
        return self.match_confidence < LOW_CONFIDENCE_THRESHOLD


class PlayerMatcher:
    def __init__(self, players: list[CanonicalPlayer]) -> None:
        self.players = players
        self._by_norm: dict[str, list[CanonicalPlayer]] = {}
        self._by_exact_lower: dict[str, list[CanonicalPlayer]] = {}
        self._by_id: dict[str, CanonicalPlayer] = {}
        for player in players:
            self._by_id[player.canonical_player_id] = player
            self._by_norm.setdefault(player.normalized_name, []).append(player)
            self._by_exact_lower.setdefault(player.canonical_name.casefold(), []).append(player)

    def _position_compatible(self, candidate: CanonicalPlayer, position_canonical: str) -> bool:
        if not position_canonical or not candidate.position_canonical:
            return True
        allowed = _POSITION_COMPATIBILITY.get(position_canonical, {position_canonical})
        return candidate.position_canonical in allowed

    def _team_compatible(self, candidate: CanonicalPlayer, team_canonical: str) -> bool:
        if not team_canonical or not candidate.team_canonical:
            return True
        return candidate.team_canonical == team_canonical

    def _filter_candidates(
        self,
        candidates: list[CanonicalPlayer],
        *,
        team_canonical: str,
        position_canonical: str,
    ) -> list[CanonicalPlayer]:
        team_pos = [
            c
            for c in candidates
            if self._position_compatible(c, position_canonical)
            and self._team_compatible(c, team_canonical)
        ]
        if team_pos:
            return team_pos
        pos_only = [c for c in candidates if self._position_compatible(c, position_canonical)]
        if pos_only:
            return pos_only
        # Trust-first guardrail: do not fall back to cross-position candidates when source position is known.
        if position_canonical:
            return []
        return candidates

    def _result_for_unique(
        self,
        candidate: CanonicalPlayer,
        *,
        status: str,
        confidence: float,
        method: str,
    ) -> MatchResult:
        return MatchResult(
            match_status=status,
            match_confidence=round(confidence, 4),
            match_method=method,
            canonical_player_id=candidate.canonical_player_id,
            player_name_canonical=candidate.canonical_name,
            candidate_ids=[candidate.canonical_player_id],
            candidate_names=[candidate.canonical_name],
        )

    def _result_for_ambiguous(self, candidates: list[CanonicalPlayer], method: str) -> MatchResult:
        return MatchResult(
            match_status="ambiguous_duplicate",
            match_confidence=0.0,
            match_method=method,
            canonical_player_id=None,
            player_name_canonical=None,
            candidate_ids=[c.canonical_player_id for c in candidates[:10]],
            candidate_names=[c.canonical_name for c in candidates[:10]],
        )

    def _result_unresolved(self, method: str) -> MatchResult:
        return MatchResult(
            match_status="unresolved",
            match_confidence=0.0,
            match_method=method,
            canonical_player_id=None,
            player_name_canonical=None,
            candidate_ids=[],
            candidate_names=[],
        )

    def match(
        self,
        *,
        player_name_source: str,
        team_canonical: str = "",
        position_canonical: str = "",
        manual_override: dict[str, str] | None = None,
    ) -> MatchResult:
        source_name = str(player_name_source or "").strip()
        if not source_name:
            return self._result_unresolved("empty_name")

        if manual_override:
            override_id = str(manual_override.get("canonical_player_id") or "").strip()
            if override_id:
                candidate = self._by_id.get(override_id)
                if candidate:
                    status = str(manual_override.get("match_status") or "fuzzy_match_reviewed").strip()
                    confidence = float(manual_override.get("match_confidence") or 0.92)
                    return self._result_for_unique(
                        candidate,
                        status=status,
                        confidence=confidence,
                        method="manual_override",
                    )

        source_casefold = source_name.casefold()
        team_norm = normalize_team_code(team_canonical)
        pos_norm = normalize_position_code(position_canonical)
        exact_candidates = self._by_exact_lower.get(source_casefold, [])
        if exact_candidates:
            filtered = self._filter_candidates(exact_candidates, team_canonical=team_norm, position_canonical=pos_norm)
            if len(filtered) == 1:
                return self._result_for_unique(
                    filtered[0],
                    status="exact_match",
                    confidence=1.0,
                    method="exact_name_casefold",
                )
            if len(filtered) > 1:
                return self._result_for_ambiguous(filtered, "exact_name_casefold_ambiguous")

        norm_name = normalize_player_name(source_name)
        if not norm_name:
            return self._result_unresolved("empty_normalized_name")

        normalized_candidates = self._by_norm.get(norm_name, [])
        if normalized_candidates:
            filtered = self._filter_candidates(normalized_candidates, team_canonical=team_norm, position_canonical=pos_norm)
            if len(filtered) == 1:
                status = "exact_match" if filtered[0].canonical_name.casefold() == source_casefold else "deterministic_match"
                confidence = 1.0 if status == "exact_match" else 0.97
                return self._result_for_unique(
                    filtered[0],
                    status=status,
                    confidence=confidence,
                    method="normalized_name_unique",
                )
            if len(filtered) > 1:
                return self._result_for_ambiguous(filtered, "normalized_name_ambiguous")

        for alias_norm in _norm_aliases(norm_name):
            alias_candidates = self._by_norm.get(alias_norm, [])
            if not alias_candidates:
                continue
            filtered = self._filter_candidates(alias_candidates, team_canonical=team_norm, position_canonical=pos_norm)
            if len(filtered) == 1:
                return self._result_for_unique(
                    filtered[0],
                    status="deterministic_match",
                    confidence=0.95,
                    method="alias_norm_unique",
                )
            if len(filtered) > 1:
                return self._result_for_ambiguous(filtered, "alias_norm_ambiguous")

        if pos_norm:
            search_pool = [p for p in self.players if self._position_compatible(p, pos_norm)]
        else:
            search_pool = self.players
        if not search_pool:
            return self._result_unresolved("empty_search_pool")

        scored: list[tuple[float, CanonicalPlayer]] = []
        for player in search_pool:
            score = _safe_similarity(norm_name, player.normalized_name)
            if score >= 0.90:
                scored.append((score, player))
        if not scored:
            return self._result_unresolved("no_fuzzy_candidates")

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_candidate = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else 0.0
        if best_score >= 0.94 and (best_score - second_score >= 0.02):
            return self._result_for_unique(
                best_candidate,
                status="fuzzy_match_reviewed",
                confidence=best_score,
                method="fuzzy_ratio_high",
            )
        if len(scored) > 1 and abs(best_score - second_score) < 0.02:
            tied = [cand for score, cand in scored if abs(score - best_score) < 0.02][:10]
            return self._result_for_ambiguous(tied, "fuzzy_ratio_tie")
        return self._result_unresolved("fuzzy_below_threshold")


def latest_dynasty_data_file(data_dir: Path) -> Path | None:
    files = sorted(data_dir.glob("dynasty_data_*.json"), reverse=True)
    return files[0] if files else None


def load_canonical_players(data_dir: Path, *, dynasty_data_path: Path | None = None) -> tuple[list[CanonicalPlayer], dict[str, Any]]:
    source_path = dynasty_data_path or latest_dynasty_data_file(data_dir)
    if source_path is None or not source_path.exists():
        return [], {"sourcePath": "", "playerCount": 0}

    payload = json.loads(source_path.read_text(encoding="utf-8"))
    players_map = payload.get("players", {})
    sleeper = payload.get("sleeper", {})
    sleeper_positions = sleeper.get("positions", {})
    sleeper_player_ids = sleeper.get("playerIds", {})

    out: list[CanonicalPlayer] = []
    for name, row in players_map.items():
        if not isinstance(row, dict):
            continue
        canonical_name = str(name or "").strip()
        if not canonical_name:
            continue
        norm_name = normalize_player_name(canonical_name)
        if not norm_name:
            continue

        sleeper_id = str(
            row.get("_sleeperId")
            or sleeper_player_ids.get(canonical_name)
            or ""
        ).strip()
        canonical_player_id = f"sleeper:{sleeper_id}" if sleeper_id else f"player::{norm_name}"
        pos_source = sleeper_positions.get(canonical_name) or row.get("position") or row.get("_position") or ""
        position_canonical = normalize_position_code(str(pos_source))
        team_source = row.get("team") or row.get("_team") or ""
        team_canonical = normalize_team_code(str(team_source))
        out.append(
            CanonicalPlayer(
                canonical_player_id=canonical_player_id,
                canonical_name=canonical_name,
                normalized_name=norm_name,
                position_canonical=position_canonical,
                team_canonical=team_canonical,
                sleeper_id=sleeper_id,
            )
        )

    return out, {"sourcePath": str(source_path), "playerCount": len(out)}


def load_manual_match_overrides(path: Path | None) -> dict[str, dict[str, str]]:
    if path is None or not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = normalize_player_name(row.get("player_name_source"))
            team = normalize_team_code(row.get("team_source"))
            pos = normalize_position_code(row.get("position_source"))
            if not name:
                continue
            key = override_key(name, team, pos)
            out[key] = {str(k): str(v or "") for k, v in row.items()}
    return out


def override_key(name_normalized: str, team_canonical: str, position_canonical: str) -> str:
    return f"{name_normalized}|{team_canonical}|{position_canonical}"


def manual_override_for_row(
    overrides: dict[str, dict[str, str]],
    *,
    player_name_source: str,
    team_source: str,
    position_source: str,
) -> dict[str, str] | None:
    if not overrides:
        return None
    name = normalize_player_name(player_name_source)
    team = normalize_team_code(team_source)
    pos = normalize_position_code(position_source)
    keys = [
        override_key(name, team, pos),
        override_key(name, "", pos),
        override_key(name, team, ""),
        override_key(name, "", ""),
    ]
    for key in keys:
        if key in overrides:
            return overrides[key]
    return None


def duplicate_canonical_name_report(players: list[CanonicalPlayer]) -> list[dict[str, Any]]:
    by_norm: dict[str, list[CanonicalPlayer]] = {}
    for player in players:
        by_norm.setdefault(player.normalized_name, []).append(player)

    report: list[dict[str, Any]] = []
    for norm_name, rows in by_norm.items():
        if len(rows) <= 1:
            continue
        report.append(
            {
                "normalized_name": norm_name,
                "candidate_count": len(rows),
                "candidates": [r.to_dict() for r in rows],
            }
        )
    report.sort(key=lambda x: x["normalized_name"])
    return report
