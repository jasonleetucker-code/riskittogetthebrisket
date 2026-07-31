"""Platform-neutral manager-season evidence for Sharp Score v2."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.intel import platform_ledger
from src.platforms.base import IDENTITY_GLOBAL_VERIFIED
from src.sharp import score as sharp_score

_REQUIRED_RESULT_FIELDS = (
    "wins",
    "losses",
    "ties",
    "finish_rank",
    "team_count",
    "made_playoffs",
    "is_champion",
)


@dataclass
class EvidenceStatus:
    manager_key: str
    platform: str
    automated_eligible_rows: int = 0
    total_rows: int = 0
    reasons: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, Any]:
        return {
            "managerKey": self.manager_key,
            "platform": self.platform,
            "automatedEligibleSeasonRows": self.automated_eligible_rows,
            "totalSeasonRows": self.total_rows,
            "reasons": sorted(self.reasons),
        }


def _row_reasons(row: Any) -> list[str]:
    reasons: list[str] = []
    identity_type = str(row["source_identity_type"] or "")
    if identity_type != IDENTITY_GLOBAL_VERIFIED:
        reasons.append(
            "league_scoped_identity"
            if identity_type in ("league_scoped_team", "name_only")
            else "insufficient_multi_league_identity"
        )
    if not row["is_complete"]:
        reasons.append("missing_completed_season")
    if not row["sharp_eligible"]:
        reasons.append("unknown_or_ineligible_league_format")
    for field in _REQUIRED_RESULT_FIELDS:
        if row[field] is None:
            reasons.append(
                "missing_playoff_result"
                if field in ("made_playoffs", "is_champion")
                else f"missing_{field}"
            )
    try:
        stored = json.loads(row["exclusion_reasons_json"] or "[]")
    except (TypeError, ValueError):
        stored = []
    reasons.extend(str(value) for value in stored if str(value).strip())
    return list(dict.fromkeys(reasons))


def build_manager_records(
    *,
    ledger_path: Path | None = None,
    min_season_rows: int = 1,
) -> tuple[list[sharp_score.ManagerRecord], dict[str, EvidenceStatus]]:
    """Build one Sharp ``ManagerRecord`` population across all platforms.

    Only complete, verified, sharp-eligible league-seasons with all
    required result fields enter automated Sharp Score v2. Unknown values
    stay unknown and are recorded as exclusion reasons; they are never
    converted to zero.
    """
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        rows = conn.execute(
            """
            SELECT ms.*, COALESCE(pm.platform, ms.platform, 'sleeper') AS source_platform,
                   COALESCE(pm.source_identity_type, ms.source_identity_type,
                            'global_verified') AS resolved_identity_type
              FROM manager_seasons ms
              LEFT JOIN platform_managers pm ON pm.manager_key=ms.manager_key
            """
        ).fetchall()
        activity = {
            str(r["manager_key"]): int(r["n"] or 0)
            for r in conn.execute(
                """
                SELECT manager_key, COUNT(DISTINCT transaction_key) AS n
                  FROM asset_movements
                 WHERE tx_type='trade' AND manager_key IS NOT NULL
                 GROUP BY manager_key
                """
            ).fetchall()
        }
        last_seen = {
            str(r["manager_key"]): int(r["ts"])
            for r in conn.execute(
                """
                SELECT manager_key, MAX(ts) AS ts
                  FROM asset_movements
                 WHERE manager_key IS NOT NULL
                 GROUP BY manager_key
                """
            ).fetchall()
            if r["ts"] is not None
        }
    finally:
        conn.close()

    evidence: dict[str, EvidenceStatus] = {}
    eligible_by_manager: dict[str, list[Any]] = {}
    for row in rows:
        key = str(row["manager_key"] or "")
        if not key:
            continue
        platform = str(row["source_platform"] or key.split(":", 1)[0])
        status = evidence.setdefault(key, EvidenceStatus(key, platform))
        status.total_rows += 1
        # Alias the resolved identity into the row reason evaluation.
        data = dict(row)
        data["source_identity_type"] = row["resolved_identity_type"]
        reasons = _row_reasons(data)
        if platform == "ffpc" and key not in last_seen:
            reasons.append("missing_recent_activity")
        reasons = list(dict.fromkeys(reasons))
        if reasons:
            status.reasons.update(reasons)
            continue
        status.automated_eligible_rows += 1
        eligible_by_manager.setdefault(key, []).append(row)

    now_ms = int(time.time() * 1000)
    records: list[sharp_score.ManagerRecord] = []
    for manager_key, seasons in eligible_by_manager.items():
        if len(seasons) < min_season_rows:
            continue
        leagues = {str(s["league_key"] or s["league_id"]) for s in seasons}
        wins = sum(int(s["wins"]) for s in seasons)
        losses = sum(int(s["losses"]) for s in seasons)
        ties = sum(int(s["ties"]) for s in seasons)
        finishes = [
            (int(s["team_count"]) - int(s["finish_rank"])) / float(int(s["team_count"]) - 1)
            for s in seasons
            if int(s["team_count"]) > 1
        ]
        last_ts = last_seen.get(manager_key)
        records.append(
            sharp_score.ManagerRecord(
                user_id=manager_key,
                completed_seasons=len(seasons),
                observed_leagues=len(leagues),
                dynasty_leagues=len(leagues),
                completed_games=wins + losses + ties,
                wins=wins,
                losses=losses,
                ties=ties,
                playoff_appearances=sum(int(s["made_playoffs"]) for s in seasons),
                championships=sum(int(s["is_champion"]) for s in seasons),
                finish_percentiles=finishes,
                trades_completed=activity.get(manager_key, 0),
                days_since_last_activity=(
                    int((now_ms - last_ts) / 86_400_000) if last_ts else None
                ),
            )
        )
    return records, evidence


def _reason_counts(evidence: dict[str, EvidenceStatus]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in evidence.values():
        for reason in status.reasons:
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def manager_evidence(
    manager_key: str | None = None,
    *,
    ledger_path: Path | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    """Inspect evidence/exclusion reasons without bloating cohort status."""
    _records, evidence = build_manager_records(ledger_path=ledger_path)
    if manager_key:
        status = evidence.get(str(manager_key))
        return [status.to_dict()] if status else []
    return [
        status.to_dict()
        for status in sorted(
            evidence.values(),
            key=lambda item: item.manager_key,
        )[: max(1, min(1000, int(limit)))]
    ]


def coverage(*, ledger_path: Path | None = None) -> dict[str, Any]:
    records, evidence = build_manager_records(ledger_path=ledger_path)
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS season_rows,
                   SUM(CASE WHEN is_complete=1 THEN 1 ELSE 0 END)
                     AS completed_rows,
                   COUNT(DISTINCT manager_key) AS managers,
                   COUNT(DISTINCT league_key) AS leagues,
                   MIN(season) AS earliest_season,
                   MAX(season) AS latest_season
              FROM manager_seasons
            """
        ).fetchone()
    finally:
        conn.close()

    by_platform: dict[str, dict[str, int]] = {}
    for status in evidence.values():
        entry = by_platform.setdefault(
            status.platform,
            {
                "managersWithEvidence": 0,
                "automatedEvidenceManagers": 0,
                "seasonRows": 0,
            },
        )
        entry["managersWithEvidence"] += 1
        entry["seasonRows"] += status.total_rows
        if status.automated_eligible_rows:
            entry["automatedEvidenceManagers"] += 1
    return {
        # Preserve the pre-platform records coverage contract.
        "seasonRows": int(row["season_rows"] or 0),
        "completedSeasonRows": int(row["completed_rows"] or 0),
        "managersWithRecords": int(row["managers"] or 0),
        "leaguesWithRecords": int(row["leagues"] or 0),
        "earliestSeason": row["earliest_season"],
        "latestSeason": row["latest_season"],
        # Additional platform-neutral evidence detail.
        "scoreableRecords": len(records),
        "platforms": by_platform,
        "exclusionReasonCounts": _reason_counts(evidence),
        # Keep the cohort response bounded as discovery grows into the
        # thousands. Full per-manager evidence remains queryable through
        # ``manager_evidence`` and the ledger.
        "evidenceExamples": [
            status.to_dict()
            for status in sorted(
                evidence.values(),
                key=lambda item: item.manager_key,
            )[:25]
        ],
    }
