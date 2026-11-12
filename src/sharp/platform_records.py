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


def _row_reasons(row: Any, *, identity_type: Any) -> list[str]:
    """Exclusion reasons for one ``manager_seasons`` row.

    ``identity_type`` is passed separately (the manager-level identity
    resolved in the query, not the row's own column) so the caller can hand
    over the sqlite row as it came off the cursor, without copying it.
    """
    reasons: list[str] = []
    identity_type = str(identity_type or "")
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
    for result_field in _REQUIRED_RESULT_FIELDS:
        if row[result_field] is None:
            reasons.append(
                "missing_playoff_result"
                if result_field in ("made_playoffs", "is_champion")
                else f"missing_{result_field}"
            )
    try:
        stored = json.loads(row["exclusion_reasons_json"] or "[]")
    except (TypeError, ValueError):
        stored = []
    reasons.extend(str(value) for value in stored if str(value).strip())
    return list(dict.fromkeys(reasons))


@dataclass(slots=True)
class _SeasonTotals:
    """Running totals over one manager's eligible season rows.

    ``build_manager_records`` folds each eligible row into one of these as
    the cursor yields it, so memory scales with managers, not rows.
    """

    seasons: int = 0
    leagues: set[str] = field(default_factory=set)
    wins: int = 0
    losses: int = 0
    ties: int = 0
    playoff_appearances: int = 0
    championships: int = 0
    finish_percentiles: list[float] = field(default_factory=list)

    def add(self, row: Any) -> None:
        self.seasons += 1
        self.leagues.add(str(row["league_key"] or row["league_id"]))
        self.wins += int(row["wins"])
        self.losses += int(row["losses"])
        self.ties += int(row["ties"])
        self.playoff_appearances += int(row["made_playoffs"])
        self.championships += int(row["is_champion"])
        team_count = int(row["team_count"])
        if team_count > 1:
            self.finish_percentiles.append(
                (team_count - int(row["finish_rank"])) / float(team_count - 1)
            )


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

    The season rows are STREAMED off the cursor and folded into per-manager
    totals; none is kept. Production's ``manager_seasons`` holds about 1.14
    million rows, and the former ``fetchall()`` held every one of them (and
    every column value) at once: the WA-17 peak census of 2026-11-12 counted
    1,138,004 live ``sqlite3.Row`` objects in a burst of about 19 million
    Python objects. Output is unchanged: same records in the same order,
    same evidence (``tests/sharp/test_platform_records_streaming.py``).
    """
    evidence: dict[str, EvidenceStatus] = {}
    totals_by_manager: dict[str, _SeasonTotals] = {}
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    try:
        # The two small per-manager aggregates come first: the row loop
        # below needs ``last_seen`` for the FFPC recent-activity rule.
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
        cursor = conn.execute(
            """
            SELECT ms.*, COALESCE(pm.platform, ms.platform, 'sleeper') AS source_platform,
                   COALESCE(pm.source_identity_type, ms.source_identity_type,
                            'global_verified') AS resolved_identity_type
              FROM manager_seasons ms
              LEFT JOIN platform_managers pm ON pm.manager_key=ms.manager_key
            """
        )
        for row in cursor:
            key = str(row["manager_key"] or "")
            if not key:
                continue
            platform = str(row["source_platform"] or key.split(":", 1)[0])
            status = evidence.get(key)
            if status is None:
                status = evidence[key] = EvidenceStatus(key, platform)
            status.total_rows += 1
            # The resolved (manager-level) identity decides, not the row's own.
            reasons = _row_reasons(row, identity_type=row["resolved_identity_type"])
            if platform == "ffpc" and key not in last_seen:
                reasons.append("missing_recent_activity")
            if reasons:
                status.reasons.update(reasons)
                continue
            status.automated_eligible_rows += 1
            totals = totals_by_manager.get(key)
            if totals is None:
                totals = totals_by_manager[key] = _SeasonTotals()
            totals.add(row)
    finally:
        conn.close()

    now_ms = int(time.time() * 1000)
    records: list[sharp_score.ManagerRecord] = []
    for manager_key, totals in totals_by_manager.items():
        if totals.seasons < min_season_rows:
            continue
        last_ts = last_seen.get(manager_key)
        records.append(
            sharp_score.ManagerRecord(
                user_id=manager_key,
                completed_seasons=totals.seasons,
                observed_leagues=len(totals.leagues),
                dynasty_leagues=len(totals.leagues),
                completed_games=totals.wins + totals.losses + totals.ties,
                wins=totals.wins,
                losses=totals.losses,
                ties=totals.ties,
                playoff_appearances=totals.playoff_appearances,
                championships=totals.championships,
                finish_percentiles=totals.finish_percentiles,
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


def coverage(
    *,
    ledger_path: Path | None = None,
    records: list[sharp_score.ManagerRecord] | None = None,
    evidence: dict[str, EvidenceStatus] | None = None,
) -> dict[str, Any]:
    """Coverage summary over the manager-record population.

    ``records``/``evidence`` let a caller that already ran
    :func:`build_manager_records` this request pass the result straight
    through instead of paying for the same joins/aggregates twice — the
    cohort-status endpoint (``src/sharp/service.py::cohort_status``) is the
    motivating caller. Omit both (the default) to compute them here as
    before.
    """
    if records is None or evidence is None:
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
