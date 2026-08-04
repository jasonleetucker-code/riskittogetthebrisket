"""Curated dynasty-industry people, verified accounts, and model membership.

The existing Sharp Score remains the empirical performance pathway.  This
module adds a second, independently explainable pathway sourced from the
research workbook:

* ``curated_industry_sharp`` — included because the workbook establishes
  dynasty-industry expertise.
* ``verified_super_sharp`` — a curated person with at least one explicitly
  verified, lawfully observable fantasy identity or decision stream.
* ``algorithmically_qualified_sharp`` — the unchanged Sharp Score v2 result.

A person may satisfy either pathway or both.  Missing league data stays NULL;
no synthetic 50% win rate, title count, or neutral performance score is ever
created.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import sqlite3
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from src.intel import platform_ledger
from src.sharp import platform_records
from src.sharp import score as sharp_score

log = logging.getLogger(__name__)
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_PATH = REPO_ROOT / "config" / "sharp" / "curated_universe.json"
SCHEMA_VERSION = 1

VERIFIED_STATUSES = {"verified"}
PROBABLE_STATUSES = {"high_confidence_probable", "probable"}
OPEN_REVIEW_STATUSES = {"possible", "unresolved", "high_confidence_probable", "conflict"}
FANTASY_PLATFORMS = {"sleeper", "ffpc"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sharp_people (
  person_id                    TEXT PRIMARY KEY,
  canonical_name               TEXT NOT NULL,
  normalized_name              TEXT NOT NULL,
  public_display_name          TEXT,
  pseudonym                    TEXT,
  primary_public_handle        TEXT,
  current_affiliation          TEXT,
  primary_category             TEXT,
  dynasty_specialties_json     TEXT NOT NULL DEFAULT '[]',
  activity_status              TEXT,
  current_activity             INTEGER NOT NULL DEFAULT 1,
  workbook_confidence          TEXT,
  publicly_trackable_assessment TEXT,
  best_potential_use           TEXT,
  selection_bucket             TEXT,
  why_included                 TEXT,
  evidence_of_prominence       TEXT,
  evidence_of_skill            TEXT,
  competition_record           TEXT,
  primary_content_link         TEXT,
  known_public_identifiers     TEXT,
  curated_expertise_score      REAL,
  trackability_score           REAL,
  candidate_status             TEXT NOT NULL,
  source_workbook_sheet        TEXT,
  source_workbook_row          INTEGER,
  source_snapshot              TEXT,
  created_ms                   INTEGER NOT NULL,
  updated_ms                   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sharp_aliases (
  alias_id             TEXT PRIMARY KEY,
  person_id            TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  alias                TEXT NOT NULL,
  normalized_alias     TEXT NOT NULL,
  alias_type           TEXT NOT NULL,
  platform             TEXT,
  active               INTEGER NOT NULL DEFAULT 1,
  confidence           REAL,
  source               TEXT,
  created_ms           INTEGER NOT NULL,
  updated_ms           INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sharp_alias_unique
  ON sharp_aliases(person_id, normalized_alias, IFNULL(platform, ''));

CREATE TABLE IF NOT EXISTS sharp_platform_accounts (
  account_id               TEXT PRIMARY KEY,
  person_id                TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  platform                 TEXT NOT NULL,
  username                 TEXT,
  normalized_username      TEXT,
  platform_user_id         TEXT,
  manager_key              TEXT,
  display_name             TEXT,
  profile_url              TEXT,
  verification_status      TEXT NOT NULL,
  verification_confidence  REAL NOT NULL,
  verification_method      TEXT,
  evidence_url             TEXT,
  first_verified_ms        INTEGER,
  last_verified_ms         INTEGER,
  active_status            TEXT,
  last_checked_ms          INTEGER,
  metadata_json            TEXT NOT NULL DEFAULT '{}',
  created_ms               INTEGER NOT NULL,
  updated_ms               INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sharp_account_person_identity
  ON sharp_platform_accounts(
    person_id, platform, IFNULL(normalized_username, ''), IFNULL(platform_user_id, '')
  );

CREATE UNIQUE INDEX IF NOT EXISTS idx_sharp_account_platform_user
  ON sharp_platform_accounts(platform, platform_user_id)
  WHERE platform_user_id IS NOT NULL AND platform_user_id <> ''
    AND verification_status='verified';
CREATE INDEX IF NOT EXISTS idx_sharp_accounts_person
  ON sharp_platform_accounts(person_id, platform, verification_status);
CREATE INDEX IF NOT EXISTS idx_sharp_accounts_manager
  ON sharp_platform_accounts(manager_key);

CREATE TABLE IF NOT EXISTS sharp_identity_candidates (
  candidate_id                TEXT PRIMARY KEY,
  person_id                   TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  platform                    TEXT NOT NULL,
  candidate_username          TEXT,
  normalized_username         TEXT,
  candidate_platform_user_id  TEXT,
  candidate_display_name      TEXT,
  candidate_team_or_entry_name TEXT,
  verification_status         TEXT NOT NULL,
  confidence                  REAL NOT NULL,
  candidate_generation_method TEXT,
  supports_json               TEXT NOT NULL DEFAULT '[]',
  contradicts_json            TEXT NOT NULL DEFAULT '[]',
  evidence_url                TEXT,
  recommended_action          TEXT,
  manual_review_required      INTEGER NOT NULL DEFAULT 1,
  observed_manager_key        TEXT,
  last_checked_ms             INTEGER,
  metadata_json               TEXT NOT NULL DEFAULT '{}',
  created_ms                  INTEGER NOT NULL,
  updated_ms                  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sharp_candidates_review
  ON sharp_identity_candidates(verification_status, platform, confidence DESC);
CREATE INDEX IF NOT EXISTS idx_sharp_candidates_person
  ON sharp_identity_candidates(person_id, platform);

CREATE TABLE IF NOT EXISTS sharp_identity_evidence (
  evidence_id             TEXT PRIMARY KEY,
  person_id               TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  candidate_id            TEXT,
  evidence_type           TEXT NOT NULL,
  description             TEXT,
  source_url              TEXT,
  source_date             TEXT,
  supports_match          INTEGER,
  confidence_contribution REAL,
  reviewed_status         TEXT,
  source_workbook_sheet   TEXT,
  source_workbook_row     INTEGER,
  metadata_json           TEXT NOT NULL DEFAULT '{}',
  created_ms              INTEGER NOT NULL,
  updated_ms              INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sharp_evidence_person
  ON sharp_identity_evidence(person_id, evidence_type);

CREATE TABLE IF NOT EXISTS sharp_model_membership (
  person_id                         TEXT PRIMARY KEY REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  curated_industry_sharp            INTEGER NOT NULL DEFAULT 0,
  algorithmically_qualified_sharp   INTEGER NOT NULL DEFAULT 0,
  verified_super_sharp              INTEGER NOT NULL DEFAULT 0,
  ffpc_specialist                   INTEGER NOT NULL DEFAULT 0,
  idp_specialist                    INTEGER NOT NULL DEFAULT 0,
  devy_c2c_specialist               INTEGER NOT NULL DEFAULT 0,
  high_stakes_specialist            INTEGER NOT NULL DEFAULT 0,
  active                            INTEGER NOT NULL DEFAULT 1,
  membership_state                  TEXT NOT NULL,
  inclusion_reason                  TEXT,
  curated_weight                    REAL,
  empirical_weight                  REAL,
  trackability_weight               REAL,
  combined_influence                REAL,
  inclusion_date_ms                 INTEGER,
  last_evaluated_ms                 INTEGER,
  metadata_json                     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sharp_membership_flags
  ON sharp_model_membership(curated_industry_sharp, algorithmically_qualified_sharp,
                            verified_super_sharp, active);

CREATE TABLE IF NOT EXISTS sharp_performance_metrics (
  metric_id                    TEXT PRIMARY KEY,
  person_id                    TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  platform_account_id          TEXT REFERENCES sharp_platform_accounts(account_id) ON DELETE SET NULL,
  manager_key                  TEXT,
  league_type                  TEXT,
  seasons_observed             INTEGER,
  completed_leagues            INTEGER,
  active_leagues               INTEGER,
  regular_season_wins          INTEGER,
  regular_season_losses        INTEGER,
  regular_season_ties          INTEGER,
  winning_percentage           REAL,
  playoff_appearances          INTEGER,
  championships               INTEGER,
  runner_up_finishes           INTEGER,
  average_finish               REAL,
  portfolio_size               INTEGER,
  roster_value_metric          REAL,
  draft_metric                 REAL,
  trade_metric                 REAL,
  waiver_metric                REAL,
  data_completeness            REAL,
  sample_size_confidence       REAL,
  empirical_score              REAL,
  empirical_score_percentile   REAL,
  methodology_version          TEXT,
  last_calculated_ms           INTEGER NOT NULL,
  metadata_json                TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sharp_metrics_person
  ON sharp_performance_metrics(person_id, last_calculated_ms DESC);

CREATE TABLE IF NOT EXISTS sharp_review_decisions (
  decision_id       TEXT PRIMARY KEY,
  candidate_id      TEXT NOT NULL REFERENCES sharp_identity_candidates(candidate_id) ON DELETE CASCADE,
  person_id         TEXT NOT NULL REFERENCES sharp_people(person_id) ON DELETE CASCADE,
  decision          TEXT NOT NULL,
  reviewer          TEXT,
  reason            TEXT,
  decided_ms        INTEGER NOT NULL,
  metadata_json     TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sharp_import_runs (
  run_id                 TEXT PRIMARY KEY,
  snapshot_name          TEXT,
  snapshot_sha256        TEXT,
  started_ms             INTEGER NOT NULL,
  finished_ms            INTEGER,
  status                 TEXT NOT NULL,
  workbook_identities    INTEGER NOT NULL DEFAULT 0,
  curated_people         INTEGER NOT NULL DEFAULT 0,
  research_candidates    INTEGER NOT NULL DEFAULT 0,
  screened_out           INTEGER NOT NULL DEFAULT 0,
  aliases_upserted       INTEGER NOT NULL DEFAULT 0,
  accounts_upserted      INTEGER NOT NULL DEFAULT 0,
  evidence_upserted      INTEGER NOT NULL DEFAULT 0,
  candidates_upserted    INTEGER NOT NULL DEFAULT 0,
  duplicates_merged      INTEGER NOT NULL DEFAULT 0,
  errors_json            TEXT NOT NULL DEFAULT '[]',
  metadata_json          TEXT NOT NULL DEFAULT '{}'
);

CREATE VIEW IF NOT EXISTS sharp_activity_events AS
SELECT
  am.movement_key AS event_id,
  am.platform,
  am.league_key,
  tx.season,
  am.action AS event_type,
  mil.canonical_manager_id AS person_id,
  spa.account_id AS platform_account_id,
  am.ts AS timestamp_ms,
  am.canonical_asset_id,
  am.source_asset_id,
  am.transaction_key,
  am.movement_key AS normalized_event_fingerprint,
  am.ingested_ms AS first_observed_ms,
  am.ingested_ms AS last_observed_ms,
  am.metadata_json AS raw_source_payload
FROM asset_movements am
LEFT JOIN transactions tx ON tx.transaction_key=am.transaction_key
LEFT JOIN manager_identity_links mil ON mil.manager_key=am.manager_key
LEFT JOIN sharp_platform_accounts spa ON spa.manager_key=am.manager_key
WHERE am.movement_key IS NOT NULL;
"""


@dataclass(frozen=True)
class CuratedCohortMember:
    manager_key: str
    person_id: str
    platform: str
    qualification_method: str
    quality: float
    display_name: str | None = None
    network: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json(value: Any, default: Any) -> str:
    if value is None:
        value = default
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_identity(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = raw.casefold().replace("’", "'")
    return re.sub(r"[^a-z0-9]+", "", raw)


def stable_id(prefix: str, *parts: Any) -> str:
    joined = "\x1f".join(str(part or "") for part in parts)
    return f"{prefix}:{hashlib.sha256(joined.encode('utf-8')).hexdigest()[:24]}"


def ensure_schema(ledger_path: Path | None = None) -> sqlite3.Connection:
    conn = platform_ledger.ensure_platform_schema(ledger_path)
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        ("curated_sharp_schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()
    return conn


def load_snapshot(path: Path | str | None = None) -> dict[str, Any]:
    target = Path(path) if path else DEFAULT_SNAPSHOT_PATH
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("curated universe snapshot must be a JSON object")
    if not isinstance(raw.get("people"), list):
        raise ValueError("curated universe snapshot has no people list")
    return raw


def _candidate_status_priority(value: str | None) -> int:
    return {
        "curated_included": 5,
        "research_candidate": 4,
        "inactive_or_historical": 3,
        "screened_out": 2,
        "insufficient_identity_information": 1,
    }.get(str(value or ""), 0)


def _merge_person_rows(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge detailed/final, near-miss, and candidate-pool rows by person id.

    The final/detail row always wins over a watchlist or screened-out row.
    This is the import's duplicate-person guard and makes re-running a newer
    workbook with a promoted candidate idempotent.
    """

    by_id: dict[str, dict[str, Any]] = {}
    for source in (
        snapshot.get("candidate_pool") or [],
        snapshot.get("research_people") or [],
        snapshot.get("people") or [],
    ):
        for row in source:
            if not isinstance(row, dict):
                continue
            person_id = str(row.get("person_id") or "").strip()
            name = str(row.get("canonical_name") or "").strip()
            if not person_id or not name:
                continue
            prior = by_id.get(person_id)
            merged = dict(prior or {})
            for key, value in row.items():
                if value not in (None, "", [], {}):
                    merged[key] = value
            if prior and _candidate_status_priority(
                prior.get("candidate_status")
            ) > _candidate_status_priority(row.get("candidate_status")):
                merged["candidate_status"] = prior.get("candidate_status")
            by_id[person_id] = merged
    return list(by_id.values())


def import_snapshot(
    snapshot: dict[str, Any] | None = None,
    *,
    snapshot_path: Path | str | None = None,
    ledger_path: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    snapshot = snapshot or load_snapshot(snapshot_path)
    now = _now_ms()
    snapshot_bytes = json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode("utf-8")
    snapshot_sha = hashlib.sha256(snapshot_bytes).hexdigest()
    run_id = stable_id("sharp_import", snapshot_sha, now)
    stats = {
        "runId": run_id,
        "workbookIdentities": 0,
        "curatedPeople": 0,
        "researchCandidates": 0,
        "screenedOut": 0,
        "aliasesUpserted": 0,
        "accountsUpserted": 0,
        "evidenceUpserted": 0,
        "candidatesUpserted": 0,
        "duplicatesMerged": 0,
        "errors": [],
    }
    people = _merge_person_rows(snapshot)
    raw_count = sum(
        len(snapshot.get(key) or []) for key in ("people", "research_people", "candidate_pool")
    )
    stats["duplicatesMerged"] = max(0, raw_count - len(people))
    stats["workbookIdentities"] = len(snapshot.get("candidate_pool") or people)

    conn = ensure_schema(ledger_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO sharp_import_runs(
              run_id, snapshot_name, snapshot_sha256, started_ms, status,
              workbook_identities, metadata_json
            ) VALUES(?, ?, ?, ?, 'running', ?, ?)
            """,
            (
                run_id,
                str(snapshot.get("workbook_name") or "curated_universe.json"),
                snapshot_sha,
                now,
                stats["workbookIdentities"],
                _json({"researchSnapshot": snapshot.get("research_snapshot")}, {}),
            ),
        )

        for row in people:
            person_id = str(row["person_id"])
            status = str(row.get("candidate_status") or "research_candidate")
            if person_id in {p.get("person_id") for p in snapshot.get("people") or []}:
                status = "curated_included"
            if status == "curated_included":
                stats["curatedPeople"] += 1
            elif status == "screened_out":
                stats["screenedOut"] += 1
            else:
                stats["researchCandidates"] += 1
            conn.execute(
                """
                INSERT INTO sharp_people(
                  person_id, canonical_name, normalized_name, public_display_name,
                  pseudonym, primary_public_handle, current_affiliation,
                  primary_category, dynasty_specialties_json, activity_status,
                  current_activity, workbook_confidence,
                  publicly_trackable_assessment, best_potential_use,
                  selection_bucket, why_included, evidence_of_prominence,
                  evidence_of_skill, competition_record, primary_content_link,
                  known_public_identifiers, curated_expertise_score,
                  trackability_score, candidate_status, source_workbook_sheet,
                  source_workbook_row, source_snapshot, created_ms, updated_ms
                ) VALUES(
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(person_id) DO UPDATE SET
                  canonical_name=excluded.canonical_name,
                  normalized_name=excluded.normalized_name,
                  public_display_name=COALESCE(excluded.public_display_name, sharp_people.public_display_name),
                  pseudonym=COALESCE(excluded.pseudonym, sharp_people.pseudonym),
                  primary_public_handle=COALESCE(excluded.primary_public_handle, sharp_people.primary_public_handle),
                  current_affiliation=COALESCE(excluded.current_affiliation, sharp_people.current_affiliation),
                  primary_category=COALESCE(excluded.primary_category, sharp_people.primary_category),
                  dynasty_specialties_json=excluded.dynasty_specialties_json,
                  activity_status=COALESCE(excluded.activity_status, sharp_people.activity_status),
                  current_activity=excluded.current_activity,
                  workbook_confidence=COALESCE(excluded.workbook_confidence, sharp_people.workbook_confidence),
                  publicly_trackable_assessment=COALESCE(excluded.publicly_trackable_assessment, sharp_people.publicly_trackable_assessment),
                  best_potential_use=COALESCE(excluded.best_potential_use, sharp_people.best_potential_use),
                  selection_bucket=COALESCE(excluded.selection_bucket, sharp_people.selection_bucket),
                  why_included=COALESCE(excluded.why_included, sharp_people.why_included),
                  evidence_of_prominence=COALESCE(excluded.evidence_of_prominence, sharp_people.evidence_of_prominence),
                  evidence_of_skill=COALESCE(excluded.evidence_of_skill, sharp_people.evidence_of_skill),
                  competition_record=COALESCE(excluded.competition_record, sharp_people.competition_record),
                  primary_content_link=COALESCE(excluded.primary_content_link, sharp_people.primary_content_link),
                  known_public_identifiers=COALESCE(excluded.known_public_identifiers, sharp_people.known_public_identifiers),
                  curated_expertise_score=COALESCE(excluded.curated_expertise_score, sharp_people.curated_expertise_score),
                  trackability_score=COALESCE(excluded.trackability_score, sharp_people.trackability_score),
                  candidate_status=CASE
                    WHEN excluded.candidate_status='curated_included' THEN excluded.candidate_status
                    ELSE sharp_people.candidate_status END,
                  source_workbook_sheet=COALESCE(excluded.source_workbook_sheet, sharp_people.source_workbook_sheet),
                  source_workbook_row=COALESCE(excluded.source_workbook_row, sharp_people.source_workbook_row),
                  source_snapshot=excluded.source_snapshot,
                  updated_ms=excluded.updated_ms
                """,
                (
                    person_id,
                    row.get("canonical_name"),
                    normalize_identity(row.get("canonical_name")),
                    row.get("public_display_name") or row.get("canonical_name"),
                    row.get("pseudonym"),
                    row.get("primary_public_handle"),
                    row.get("current_affiliation"),
                    row.get("primary_category"),
                    _json(row.get("dynasty_specialties"), []),
                    row.get("activity_status"),
                    int(bool(row.get("current_activity", status != "inactive_or_historical"))),
                    row.get("workbook_confidence"),
                    row.get("publicly_trackable_assessment"),
                    row.get("best_potential_use"),
                    row.get("selection_bucket"),
                    row.get("why_included")
                    or row.get("screening_note")
                    or row.get("reason_omitted"),
                    row.get("evidence_of_prominence"),
                    row.get("evidence_of_skill") or row.get("primary_evidence_notes"),
                    row.get("competition_record"),
                    row.get("primary_content_link") or row.get("source_url"),
                    row.get("known_public_identifiers"),
                    row.get("curated_expertise_score"),
                    row.get("trackability_score"),
                    status,
                    row.get("source_workbook_sheet") or row.get("workbook_sheet"),
                    row.get("source_workbook_row") or row.get("workbook_row"),
                    str(snapshot.get("workbook_name") or "curated_universe.json"),
                    now,
                    now,
                ),
            )

        for row in snapshot.get("aliases") or []:
            person_id = str(row.get("person_id") or "")
            alias = str(row.get("alias") or "").strip()
            if not person_id or not alias:
                continue
            alias_id = stable_id(
                "sharp_alias", person_id, row.get("platform"), normalize_identity(alias)
            )
            conn.execute(
                """
                INSERT INTO sharp_aliases(
                  alias_id, person_id, alias, normalized_alias, alias_type,
                  platform, active, confidence, source, created_ms, updated_ms
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(alias_id) DO UPDATE SET
                  alias=excluded.alias,
                  active=excluded.active,
                  confidence=excluded.confidence,
                  source=excluded.source,
                  updated_ms=excluded.updated_ms
                """,
                (
                    alias_id,
                    person_id,
                    alias,
                    normalize_identity(alias),
                    row.get("alias_type") or "other",
                    row.get("platform"),
                    int(bool(row.get("active", True))),
                    row.get("confidence"),
                    row.get("source"),
                    now,
                    now,
                ),
            )
            stats["aliasesUpserted"] += 1

        for row in snapshot.get("platform_accounts") or []:
            person_id = str(row.get("person_id") or "")
            platform = str(row.get("platform") or "").lower()
            username = str(row.get("username") or "").strip() or None
            if not person_id or not platform:
                continue
            verification_method = str(row.get("verification_method") or "") or None
            # NOTE: a ``workbook_positive_identification`` branch used to sit
            # here, collapsing a person's fantasy account to one row keyed on
            # (person, platform) so a renamed username updated in place. It is
            # gone because it has no producer: the workbook cannot verify
            # account ownership, so it no longer emits fantasy accounts at all.
            # Verified fantasy accounts now arrive only from ``review_candidate``,
            # which keys on the platform's own stable user id -- a strictly
            # better answer to the same rename problem.
            account_id = str(
                row.get("account_id") or stable_id("sharp_account", person_id, platform, username)
            )
            verified_ms = now if row.get("verification_status") == "verified" else None
            manager_key = row.get("manager_key")
            if platform == "x" and verification_method == "workbook_public_handle" and username:
                conn.execute(
                    """
                    UPDATE sharp_platform_accounts
                       SET active_status='historical_handle', updated_ms=?
                     WHERE person_id=? AND platform='x'
                       AND verification_method='workbook_public_handle'
                       AND account_id<>? AND normalized_username<>?
                    """,
                    (now, person_id, account_id, normalize_identity(username)),
                )
            conn.execute(
                """
                INSERT INTO sharp_platform_accounts(
                  account_id, person_id, platform, username, normalized_username,
                  platform_user_id, manager_key, display_name, profile_url,
                  verification_status, verification_confidence,
                  verification_method, evidence_url, first_verified_ms,
                  last_verified_ms, active_status, last_checked_ms,
                  metadata_json, created_ms, updated_ms
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                  username=COALESCE(excluded.username, sharp_platform_accounts.username),
                  normalized_username=COALESCE(excluded.normalized_username, sharp_platform_accounts.normalized_username),
                  platform_user_id=COALESCE(excluded.platform_user_id, sharp_platform_accounts.platform_user_id),
                  manager_key=COALESCE(excluded.manager_key, sharp_platform_accounts.manager_key),
                  display_name=COALESCE(excluded.display_name, sharp_platform_accounts.display_name),
                  profile_url=COALESCE(excluded.profile_url, sharp_platform_accounts.profile_url),
                  verification_status=CASE
                    WHEN sharp_platform_accounts.verification_status='verified' THEN 'verified'
                    ELSE excluded.verification_status END,
                  verification_confidence=MAX(sharp_platform_accounts.verification_confidence, excluded.verification_confidence),
                  verification_method=COALESCE(excluded.verification_method, sharp_platform_accounts.verification_method),
                  evidence_url=COALESCE(excluded.evidence_url, sharp_platform_accounts.evidence_url),
                  first_verified_ms=COALESCE(sharp_platform_accounts.first_verified_ms, excluded.first_verified_ms),
                  last_verified_ms=COALESCE(excluded.last_verified_ms, sharp_platform_accounts.last_verified_ms),
                  active_status=COALESCE(excluded.active_status, sharp_platform_accounts.active_status),
                  last_checked_ms=COALESCE(excluded.last_checked_ms, sharp_platform_accounts.last_checked_ms),
                  metadata_json=excluded.metadata_json,
                  updated_ms=excluded.updated_ms
                """,
                (
                    account_id,
                    person_id,
                    platform,
                    username,
                    normalize_identity(username) if username else None,
                    row.get("platform_user_id"),
                    manager_key,
                    row.get("display_name"),
                    row.get("profile_url"),
                    row.get("verification_status") or "unresolved",
                    float(row.get("verification_confidence") or 0.0),
                    verification_method,
                    row.get("evidence_url"),
                    verified_ms,
                    verified_ms,
                    row.get("active_status"),
                    None,
                    _json(row.get("metadata"), {}),
                    now,
                    now,
                ),
            )
            stats["accountsUpserted"] += 1

        for index, row in enumerate(snapshot.get("identity_evidence") or []):
            person_id = str(row.get("person_id") or "")
            if not person_id:
                continue
            evidence_id = str(
                row.get("evidence_id")
                or stable_id(
                    "sharp_evidence",
                    person_id,
                    row.get("evidence_type"),
                    row.get("source_url"),
                    row.get("description"),
                    index,
                )
            )
            known = {
                "person_id",
                "candidate_account_id",
                "candidate_id",
                "evidence_type",
                "description",
                "source_url",
                "source_date",
                "supports_match",
                "confidence_contribution",
                "reviewed_status",
                "source_workbook_sheet",
                "source_workbook_row",
            }
            metadata = {key: value for key, value in row.items() if key not in known}
            conn.execute(
                """
                INSERT INTO sharp_identity_evidence(
                  evidence_id, person_id, candidate_id, evidence_type,
                  description, source_url, source_date, supports_match,
                  confidence_contribution, reviewed_status,
                  source_workbook_sheet, source_workbook_row, metadata_json,
                  created_ms, updated_ms
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                  description=excluded.description,
                  source_url=excluded.source_url,
                  source_date=excluded.source_date,
                  supports_match=excluded.supports_match,
                  confidence_contribution=excluded.confidence_contribution,
                  reviewed_status=excluded.reviewed_status,
                  metadata_json=excluded.metadata_json,
                  updated_ms=excluded.updated_ms
                """,
                (
                    evidence_id,
                    person_id,
                    row.get("candidate_id") or row.get("candidate_account_id"),
                    row.get("evidence_type") or "workbook_source",
                    row.get("description"),
                    row.get("source_url"),
                    row.get("source_date"),
                    None
                    if row.get("supports_match") is None
                    else int(bool(row.get("supports_match"))),
                    row.get("confidence_contribution"),
                    row.get("reviewed_status"),
                    row.get("source_workbook_sheet"),
                    row.get("source_workbook_row"),
                    _json(metadata, {}),
                    now,
                    now,
                ),
            )
            stats["evidenceUpserted"] += 1

        for row in snapshot.get("identity_candidates") or []:
            person_id = str(row.get("person_id") or "")
            platform = str(row.get("platform") or "").lower()
            if not person_id or not platform:
                continue
            username = str(row.get("candidate_username") or "").strip() or None
            candidate_id = str(
                row.get("candidate_id")
                or stable_id(
                    "sharp_candidate",
                    person_id,
                    platform,
                    username,
                    row.get("candidate_team_or_entry_name"),
                )
            )
            conn.execute(
                """
                INSERT INTO sharp_identity_candidates(
                  candidate_id, person_id, platform, candidate_username,
                  normalized_username, candidate_platform_user_id,
                  candidate_display_name, candidate_team_or_entry_name,
                  verification_status, confidence, candidate_generation_method,
                  supports_json, contradicts_json, evidence_url,
                  recommended_action, manual_review_required,
                  observed_manager_key, last_checked_ms, metadata_json,
                  created_ms, updated_ms
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                  candidate_platform_user_id=COALESCE(excluded.candidate_platform_user_id, sharp_identity_candidates.candidate_platform_user_id),
                  candidate_display_name=COALESCE(excluded.candidate_display_name, sharp_identity_candidates.candidate_display_name),
                  candidate_team_or_entry_name=COALESCE(excluded.candidate_team_or_entry_name, sharp_identity_candidates.candidate_team_or_entry_name),
                  verification_status=CASE
                    WHEN sharp_identity_candidates.verification_status IN ('verified','rejected_match')
                    THEN sharp_identity_candidates.verification_status
                    ELSE excluded.verification_status END,
                  confidence=MAX(sharp_identity_candidates.confidence, excluded.confidence),
                  supports_json=excluded.supports_json,
                  contradicts_json=excluded.contradicts_json,
                  evidence_url=COALESCE(excluded.evidence_url, sharp_identity_candidates.evidence_url),
                  recommended_action=excluded.recommended_action,
                  manual_review_required=CASE
                    WHEN sharp_identity_candidates.verification_status IN ('verified','rejected_match')
                    THEN 0 ELSE excluded.manual_review_required END,
                  observed_manager_key=COALESCE(excluded.observed_manager_key, sharp_identity_candidates.observed_manager_key),
                  metadata_json=excluded.metadata_json,
                  updated_ms=excluded.updated_ms
                """,
                (
                    candidate_id,
                    person_id,
                    platform,
                    username,
                    normalize_identity(username) if username else None,
                    row.get("candidate_platform_user_id"),
                    row.get("candidate_display_name"),
                    row.get("candidate_team_or_entry_name"),
                    row.get("verification_status") or "unresolved",
                    float(row.get("confidence") or 0.0),
                    row.get("candidate_generation_method"),
                    _json(row.get("supports"), []),
                    _json(row.get("contradicts"), []),
                    row.get("evidence_url"),
                    row.get("recommended_action"),
                    int(bool(row.get("manual_review_required", True))),
                    row.get("observed_manager_key"),
                    None,
                    _json(row.get("metadata"), {}),
                    now,
                    now,
                ),
            )
            stats["candidatesUpserted"] += 1

        detailed_memberships = {
            str(row.get("person_id")): row for row in snapshot.get("model_memberships") or []
        }
        for row in people:
            person_id = str(row["person_id"])
            detail = detailed_memberships.get(person_id, {})
            curated = int(
                row.get("candidate_status") == "curated_included"
                or person_id in detailed_memberships
            )
            state = detail.get("membership_state") or (
                "curated_only"
                if curated
                else str(row.get("candidate_status") or "research_candidate")
            )
            conn.execute(
                """
                INSERT INTO sharp_model_membership(
                  person_id, curated_industry_sharp,
                  algorithmically_qualified_sharp, verified_super_sharp,
                  ffpc_specialist, idp_specialist, devy_c2c_specialist,
                  high_stakes_specialist, active, membership_state,
                  inclusion_reason, curated_weight, empirical_weight,
                  trackability_weight, combined_influence,
                  inclusion_date_ms, last_evaluated_ms, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(person_id) DO UPDATE SET
                  curated_industry_sharp=MAX(sharp_model_membership.curated_industry_sharp, excluded.curated_industry_sharp),
                  ffpc_specialist=MAX(sharp_model_membership.ffpc_specialist, excluded.ffpc_specialist),
                  idp_specialist=MAX(sharp_model_membership.idp_specialist, excluded.idp_specialist),
                  devy_c2c_specialist=MAX(sharp_model_membership.devy_c2c_specialist, excluded.devy_c2c_specialist),
                  high_stakes_specialist=MAX(sharp_model_membership.high_stakes_specialist, excluded.high_stakes_specialist),
                  active=excluded.active,
                  membership_state=CASE
                    WHEN sharp_model_membership.algorithmically_qualified_sharp=1
                         AND excluded.curated_industry_sharp=1 THEN 'both_curated_and_performance'
                    WHEN sharp_model_membership.verified_super_sharp=1
                         AND excluded.curated_industry_sharp=1 THEN 'trackable_curated_sharp'
                    ELSE excluded.membership_state END,
                  inclusion_reason=COALESCE(excluded.inclusion_reason, sharp_model_membership.inclusion_reason),
                  curated_weight=COALESCE(excluded.curated_weight, sharp_model_membership.curated_weight),
                  trackability_weight=COALESCE(excluded.trackability_weight, sharp_model_membership.trackability_weight),
                  last_evaluated_ms=excluded.last_evaluated_ms,
                  metadata_json=excluded.metadata_json
                """,
                (
                    person_id,
                    curated,
                    0,
                    int(bool(detail.get("verified_super_sharp"))),
                    int(bool(detail.get("ffpc_specialist"))),
                    int(bool(detail.get("idp_specialist"))),
                    int(bool(detail.get("devy_c2c_specialist"))),
                    int(bool(detail.get("high_stakes_specialist"))),
                    int(
                        bool(
                            row.get(
                                "current_activity",
                                row.get("candidate_status") != "inactive_or_historical",
                            )
                        )
                    ),
                    state,
                    detail.get("inclusion_reason")
                    or row.get("why_included")
                    or row.get("screening_note"),
                    detail.get("curated_weight")
                    if detail.get("curated_weight") is not None
                    else (float(row.get("curated_expertise_score") or 0.0) / 100.0 or None),
                    None,
                    detail.get("trackability_weight")
                    if detail.get("trackability_weight") is not None
                    else (float(row.get("trackability_score") or 0.0) / 100.0 or None),
                    None,
                    now,
                    now,
                    _json({"source": "workbook"}, {}),
                ),
            )

        conn.execute(
            """
            UPDATE sharp_import_runs SET
              finished_ms=?, status='success', curated_people=?,
              research_candidates=?, screened_out=?, aliases_upserted=?,
              accounts_upserted=?, evidence_upserted=?, candidates_upserted=?,
              duplicates_merged=?, errors_json=?
            WHERE run_id=?
            """,
            (
                _now_ms(),
                stats["curatedPeople"],
                stats["researchCandidates"],
                stats["screenedOut"],
                stats["aliasesUpserted"],
                stats["accountsUpserted"],
                stats["evidenceUpserted"],
                stats["candidatesUpserted"],
                stats["duplicatesMerged"],
                _json(stats["errors"], []),
                run_id,
            ),
        )
        if dry_run:
            conn.rollback()
            stats["status"] = "dry_run"
        else:
            conn.commit()
            stats["status"] = "success"
    except Exception as exc:
        conn.rollback()
        stats["errors"].append(f"{type(exc).__name__}: {exc}")
        stats["status"] = "failed"
        raise
    finally:
        conn.close()
    return stats


def _http_json(url: str, *, timeout: float = 15.0, attempts: int = 3) -> tuple[int, Any]:
    last_error: Exception | None = None
    for attempt in range(attempts):
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ChaseUpside-Curated-Sharps/1.0 (+https://chaseupside.com)",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8", "replace")
                return int(response.status), json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, None
            if exc.code == 429 or 500 <= exc.code < 600:
                last_error = exc
            else:
                raise
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            last_error = exc
        if attempt + 1 < attempts:
            time.sleep(min(8.0, 0.75 * (2**attempt)))
    if last_error:
        raise last_error
    return 599, None


def _upsert_identity_link(
    conn: sqlite3.Connection,
    *,
    manager_key: str,
    person_id: str,
    method: str,
    confidence: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    now = _now_ms()
    existing = conn.execute(
        "SELECT canonical_manager_id, verified FROM manager_identity_links WHERE manager_key=?",
        (manager_key,),
    ).fetchone()
    if (
        existing
        and str(existing["canonical_manager_id"]) != person_id
        and int(existing["verified"] or 0)
    ):
        raise ValueError(
            f"platform account {manager_key} is already verified for {existing['canonical_manager_id']}"
        )
    conn.execute(
        """
        INSERT INTO manager_identity_links(
          manager_key, canonical_manager_id, link_method, link_confidence,
          verified, created_ms, metadata_json
        ) VALUES(?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(manager_key) DO UPDATE SET
          canonical_manager_id=excluded.canonical_manager_id,
          link_method=excluded.link_method,
          link_confidence=excluded.link_confidence,
          verified=1,
          metadata_json=excluded.metadata_json
        """,
        (manager_key, person_id, method, confidence, now, _json(metadata, {})),
    )
    conn.execute(
        "UPDATE platform_managers SET canonical_manager_id=? WHERE manager_key=?",
        (person_id, manager_key),
    )


def resolve_verified_sleeper_accounts(
    *,
    ledger_path: Path | None = None,
    fetch_json=_http_json,
    request_sleep: float = 0.35,
) -> dict[str, int]:
    """Resolve workbook-verified usernames to official Sleeper user ids.

    The workbook's positive username identification is treated as ownership
    evidence.  The public API call only resolves the stable platform id and
    current display data.  A 404 is recorded as stale/renamed rather than
    silently reassigned to a similarly named account.
    """

    conn = ensure_schema(ledger_path)
    stats = {"checked": 0, "resolved": 0, "notFound": 0, "errors": 0}
    try:
        rows = conn.execute(
            """
            SELECT * FROM sharp_platform_accounts
             WHERE platform='sleeper' AND verification_status='verified'
               AND username IS NOT NULL AND username<>''
               AND (platform_user_id IS NULL OR platform_user_id='')
             ORDER BY account_id
            """
        ).fetchall()
        for row in rows:
            stats["checked"] += 1
            username = str(row["username"])
            url = "https://api.sleeper.app/v1/user/" + urllib.parse.quote(username, safe="")
            try:
                status, payload = fetch_json(url)
            except Exception as exc:  # noqa: BLE001
                stats["errors"] += 1
                conn.execute(
                    "UPDATE sharp_platform_accounts SET last_checked_ms=?, metadata_json=? WHERE account_id=?",
                    (
                        _now_ms(),
                        _json({"lastResolveError": f"{type(exc).__name__}: {exc}"}, {}),
                        row["account_id"],
                    ),
                )
                conn.commit()
                continue
            now = _now_ms()
            if status == 404 or not isinstance(payload, dict) or not payload.get("user_id"):
                stats["notFound"] += 1
                conn.execute(
                    """
                    UPDATE sharp_platform_accounts
                       SET active_status='not_found_or_renamed', last_checked_ms=?,
                           metadata_json=?, updated_ms=?
                     WHERE account_id=?
                    """,
                    (
                        now,
                        _json({"resolutionStatus": "not_found"}, {}),
                        now,
                        row["account_id"],
                    ),
                )
                conn.commit()
                continue
            user_id = str(payload["user_id"])
            current_username = str(payload.get("username") or username)
            display_name = str(payload.get("display_name") or "").strip() or None
            manager_key = f"sleeper:{user_id}"
            conn.execute(
                """
                INSERT INTO platform_managers(
                  manager_key, platform, source_manager_id, username,
                  display_name, source_identity_type, identity_scope,
                  identity_confidence, canonical_manager_id, first_seen_ms,
                  last_seen_ms, metadata_json
                ) VALUES(?, 'sleeper', ?, ?, ?, 'global_verified', 'platform',
                         1.0, ?, ?, ?, ?)
                ON CONFLICT(manager_key) DO UPDATE SET
                  username=excluded.username,
                  display_name=COALESCE(excluded.display_name, platform_managers.display_name),
                  canonical_manager_id=excluded.canonical_manager_id,
                  last_seen_ms=excluded.last_seen_ms,
                  metadata_json=excluded.metadata_json
                """,
                (
                    manager_key,
                    user_id,
                    current_username,
                    display_name,
                    row["person_id"],
                    now,
                    now,
                    _json({"resolvedBy": "official_sleeper_user_endpoint"}, {}),
                ),
            )
            _upsert_identity_link(
                conn,
                manager_key=manager_key,
                person_id=str(row["person_id"]),
                method="workbook_verified_username+official_sleeper_id",
                confidence=1.0,
                metadata={"username": current_username},
            )
            conn.execute(
                """
                UPDATE sharp_platform_accounts SET
                  username=?, normalized_username=?, platform_user_id=?,
                  manager_key=?, display_name=?, profile_url=?,
                  active_status='active', last_verified_ms=?, last_checked_ms=?,
                  metadata_json=?, updated_ms=?
                WHERE account_id=?
                """,
                (
                    current_username,
                    normalize_identity(current_username),
                    user_id,
                    manager_key,
                    display_name,
                    f"https://sleeper.com/u/{current_username}",
                    now,
                    now,
                    _json({"officialApiResolved": True}, {}),
                    now,
                    row["account_id"],
                ),
            )
            conn.commit()
            stats["resolved"] += 1
            if request_sleep:
                time.sleep(request_sleep)
        refresh_memberships(ledger_path=ledger_path, connection=conn)
        conn.commit()
    finally:
        conn.close()
    return stats


def inspect_sleeper_candidates(
    *,
    ledger_path: Path | None = None,
    fetch_json=_http_json,
    request_sleep: float = 0.35,
    limit: int = 250,
    budget: int | None = None,
) -> dict[str, int]:
    """Check candidate usernames without asserting ownership.

    Existence plus name resemblance may raise a candidate to probable, but
    only an explicit review action or already authoritative workbook evidence
    can create a verified account link.
    """

    conn = ensure_schema(ledger_path)
    stats = {"checked": 0, "found": 0, "probable": 0, "notFound": 0, "conflicts": 0}
    try:
        rows = conn.execute(
            """
            SELECT c.*, p.canonical_name, p.public_display_name
              FROM sharp_identity_candidates c
              JOIN sharp_people p ON p.person_id=c.person_id
             WHERE c.platform='sleeper'
               AND c.verification_status NOT IN ('verified','rejected_match')
               AND c.candidate_username IS NOT NULL
             ORDER BY c.confidence DESC, c.candidate_id
             LIMIT ?
            """,
            (max(1, min(int(budget if budget is not None else limit), 1000)),),
        ).fetchall()
        for row in rows:
            stats["checked"] += 1
            username = str(row["candidate_username"])
            url = "https://api.sleeper.app/v1/user/" + urllib.parse.quote(username, safe="")
            status, payload = fetch_json(url)
            now = _now_ms()
            if status == 404 or not isinstance(payload, dict) or not payload.get("user_id"):
                stats["notFound"] += 1
                conn.execute(
                    """
                    UPDATE sharp_identity_candidates
                       SET verification_status='unresolved', confidence=MIN(confidence, 0.15),
                           last_checked_ms=?, metadata_json=?, updated_ms=?
                     WHERE candidate_id=?
                    """,
                    (
                        now,
                        _json({"officialApiStatus": "not_found"}, {}),
                        now,
                        row["candidate_id"],
                    ),
                )
                conn.commit()
                continue
            stats["found"] += 1
            user_id = str(payload["user_id"])
            display_name = str(payload.get("display_name") or "").strip() or None
            # Corroboration means the account carries the PERSON'S NAME.
            #
            # The queried username must not appear on both sides: we searched
            # for it, so Sleeper echoes it back verbatim in ``username``, and
            # including it made ``overlap`` structurally always true. On the
            # first live sweep that promoted all 42 existing accounts to
            # "high confidence probable" -- including ``hrr5010`` for Hasan
            # Rahim and ``amicsta`` for Anthony Amico, where nothing
            # corresponds at all. A tautology reported as evidence is exactly
            # the false certainty this model exists to avoid.
            #
            # What survives is a real test: the person's name against what the
            # account actually shows. ``jjzachariason`` matches "JJ
            # Zachariason" and is genuine evidence; ``carpentiernfl`` does not
            # match "Cody Carpentier" and correctly stays merely possible --
            # it is the X handle, which is how it was generated.
            candidate_norms = {
                normalize_identity(row["canonical_name"]),
                normalize_identity(row["public_display_name"]),
            } - {""}
            observed_norms = {
                normalize_identity(display_name),
                normalize_identity(payload.get("username")),
            } - {""}
            overlap = bool(candidate_norms & observed_norms)
            collisions = conn.execute(
                """
                SELECT DISTINCT person_id FROM sharp_identity_candidates
                 WHERE platform='sleeper' AND candidate_platform_user_id=?
                   AND person_id<>?
                UNION
                SELECT DISTINCT person_id FROM sharp_platform_accounts
                 WHERE platform='sleeper' AND platform_user_id=?
                   AND person_id<>?
                """,
                (user_id, row["person_id"], user_id, row["person_id"]),
            ).fetchall()
            if collisions:
                new_status = "conflict"
                new_confidence = min(float(row["confidence"] or 0.0), 0.35)
                stats["conflicts"] += 1
            elif overlap:
                new_status = "high_confidence_probable"
                new_confidence = max(float(row["confidence"] or 0.0), 0.72)
                stats["probable"] += 1
            else:
                new_status = "possible"
                new_confidence = max(float(row["confidence"] or 0.0), 0.35)
            conn.execute(
                """
                UPDATE sharp_identity_candidates SET
                  candidate_platform_user_id=?, candidate_display_name=?,
                  verification_status=?, confidence=?, last_checked_ms=?,
                  metadata_json=?, updated_ms=?
                WHERE candidate_id=?
                """,
                (
                    user_id,
                    display_name,
                    new_status,
                    new_confidence,
                    now,
                    _json(
                        {
                            "officialApiUsername": payload.get("username"),
                            "nameOverlap": overlap,
                            "avatar": payload.get("avatar"),
                        },
                        {},
                    ),
                    now,
                    row["candidate_id"],
                ),
            )
            conn.commit()
            if request_sleep:
                time.sleep(request_sleep)
    finally:
        conn.close()
    return stats


def match_ffpc_candidates(*, ledger_path: Path | None = None) -> dict[str, int]:
    """Compare workbook FFPC aliases to already ingested public managers.

    Exact normalized name matching is still only *probable*: FFPC display
    names and team/entry names can collide and may represent co-managed
    entries.  The review queue preserves the distinction.
    """

    conn = ensure_schema(ledger_path)
    stats = {"checked": 0, "matched": 0, "conflicts": 0}
    try:
        candidates = conn.execute(
            """
            SELECT c.*, p.canonical_name, p.public_display_name
              FROM sharp_identity_candidates c
              JOIN sharp_people p ON p.person_id=c.person_id
             WHERE c.platform='ffpc'
               AND c.verification_status NOT IN ('verified','rejected_match')
            """
        ).fetchall()
        managers = conn.execute(
            """
            SELECT manager_key, source_manager_id, display_name, username
              FROM platform_managers WHERE platform='ffpc'
            """
        ).fetchall()
        index: dict[str, list[sqlite3.Row]] = {}
        for manager in managers:
            for value in (
                manager["display_name"],
                manager["username"],
                manager["source_manager_id"],
            ):
                normalized = normalize_identity(value)
                if normalized:
                    index.setdefault(normalized, []).append(manager)
        for candidate in candidates:
            stats["checked"] += 1
            aliases = {
                normalize_identity(candidate["canonical_name"]),
                normalize_identity(candidate["public_display_name"]),
                normalize_identity(candidate["candidate_display_name"]),
                normalize_identity(candidate["candidate_team_or_entry_name"]),
            } - {""}
            matches: dict[str, sqlite3.Row] = {}
            for alias in aliases:
                for manager in index.get(alias, []):
                    matches[str(manager["manager_key"])] = manager
            now = _now_ms()
            if len(matches) == 1:
                manager = next(iter(matches.values()))
                conn.execute(
                    """
                    UPDATE sharp_identity_candidates SET
                      observed_manager_key=?, candidate_platform_user_id=?,
                      candidate_display_name=COALESCE(?, candidate_display_name),
                      verification_status='high_confidence_probable',
                      confidence=MAX(confidence, 0.78), last_checked_ms=?,
                      metadata_json=?, updated_ms=?
                    WHERE candidate_id=?
                    """,
                    (
                        manager["manager_key"],
                        manager["source_manager_id"],
                        manager["display_name"],
                        now,
                        _json({"matchMethod": "exact_normalized_public_name"}, {}),
                        now,
                        candidate["candidate_id"],
                    ),
                )
                stats["matched"] += 1
            elif len(matches) > 1:
                conn.execute(
                    """
                    UPDATE sharp_identity_candidates SET
                      verification_status='conflict', confidence=MIN(confidence, 0.4),
                      last_checked_ms=?, metadata_json=?, updated_ms=?
                    WHERE candidate_id=?
                    """,
                    (
                        now,
                        _json({"matchingManagerKeys": sorted(matches)}, {}),
                        now,
                        candidate["candidate_id"],
                    ),
                )
                stats["conflicts"] += 1
        conn.commit()
    finally:
        conn.close()
    return stats


def review_candidate(
    candidate_id: str,
    decision: str,
    *,
    reviewer: str = "admin",
    reason: str | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    decision = str(decision).strip().lower()
    if decision not in {"approve", "reject", "unresolved"}:
        raise ValueError("decision must be approve, reject, or unresolved")
    conn = ensure_schema(ledger_path)
    try:
        row = conn.execute(
            """
            SELECT c.*, p.public_display_name
              FROM sharp_identity_candidates c
              JOIN sharp_people p ON p.person_id=c.person_id
             WHERE c.candidate_id=?
            """,
            (candidate_id,),
        ).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        now = _now_ms()
        if decision == "approve":
            if not row["candidate_platform_user_id"] and not row["observed_manager_key"]:
                raise ValueError("candidate has no stable platform identity to approve")
            platform = str(row["platform"])
            platform_user_id = str(row["candidate_platform_user_id"] or "") or None
            manager_key = str(row["observed_manager_key"] or "") or (
                f"{platform}:{platform_user_id}" if platform_user_id else None
            )
            if manager_key:
                conflict = conn.execute(
                    """
                    SELECT canonical_manager_id FROM manager_identity_links
                     WHERE manager_key=? AND verified=1
                       AND canonical_manager_id<>?
                    """,
                    (manager_key, row["person_id"]),
                ).fetchone()
                if conflict:
                    raise ValueError(
                        f"{manager_key} is already verified for {conflict['canonical_manager_id']}"
                    )
            account_id = stable_id(
                "sharp_account",
                row["person_id"],
                platform,
                platform_user_id,
                row["candidate_username"],
            )
            conn.execute(
                """
                INSERT INTO sharp_platform_accounts(
                  account_id, person_id, platform, username, normalized_username,
                  platform_user_id, manager_key, display_name, verification_status,
                  verification_confidence, verification_method, evidence_url,
                  first_verified_ms, last_verified_ms, active_status,
                  last_checked_ms, metadata_json, created_ms, updated_ms
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 'verified', 1.0,
                         'explicit_admin_review', ?, ?, ?, 'active', ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                  verification_status='verified', verification_confidence=1.0,
                  verification_method='explicit_admin_review',
                  platform_user_id=COALESCE(excluded.platform_user_id, sharp_platform_accounts.platform_user_id),
                  manager_key=COALESCE(excluded.manager_key, sharp_platform_accounts.manager_key),
                  display_name=COALESCE(excluded.display_name, sharp_platform_accounts.display_name),
                  last_verified_ms=excluded.last_verified_ms,
                  last_checked_ms=excluded.last_checked_ms,
                  updated_ms=excluded.updated_ms
                """,
                (
                    account_id,
                    row["person_id"],
                    platform,
                    row["candidate_username"],
                    row["normalized_username"],
                    platform_user_id,
                    manager_key,
                    row["candidate_display_name"],
                    row["evidence_url"],
                    now,
                    now,
                    now,
                    _json({"approvedCandidateId": candidate_id}, {}),
                    now,
                    now,
                ),
            )
            if manager_key:
                _upsert_identity_link(
                    conn,
                    manager_key=manager_key,
                    person_id=str(row["person_id"]),
                    method="explicit_admin_review",
                    confidence=1.0,
                    metadata={"candidateId": candidate_id},
                )
            new_status = "verified"
        elif decision == "reject":
            new_status = "rejected_match"
        else:
            new_status = "unresolved"
        conn.execute(
            """
            UPDATE sharp_identity_candidates SET
              verification_status=?, manual_review_required=?, updated_ms=?
            WHERE candidate_id=?
            """,
            (new_status, int(decision == "unresolved"), now, candidate_id),
        )
        decision_id = stable_id("sharp_decision", candidate_id, decision, now)
        conn.execute(
            """
            INSERT INTO sharp_review_decisions(
              decision_id, candidate_id, person_id, decision, reviewer,
              reason, decided_ms, metadata_json
            ) VALUES(?, ?, ?, ?, ?, ?, ?, '{}')
            """,
            (decision_id, candidate_id, row["person_id"], decision, reviewer, reason, now),
        )
        refresh_memberships(ledger_path=ledger_path, connection=conn)
        conn.commit()
        return {"candidateId": candidate_id, "decision": decision, "status": new_status}
    finally:
        conn.close()


def _metric_id(person_id: str, manager_key: str) -> str:
    return stable_id("sharp_metric", person_id, manager_key, sharp_score.methodology_version())


def refresh_memberships(
    *,
    ledger_path: Path | None = None,
    connection: sqlite3.Connection | None = None,
) -> dict[str, int]:
    own_connection = connection is None
    conn = connection or ensure_schema(ledger_path)
    now = _now_ms()
    stats = {"people": 0, "performanceQualified": 0, "superSharps": 0, "both": 0}
    try:
        records, _evidence = platform_records.build_manager_records(ledger_path=ledger_path)
        record_by_key = {record.user_id: record for record in records}
        scored = sharp_score.score_managers(records)
        score_by_key = {item.user_id: item for item in scored}
        links = conn.execute(
            "SELECT manager_key, canonical_manager_id FROM manager_identity_links WHERE verified=1"
        ).fetchall()
        managers_by_person: dict[str, set[str]] = {}
        for link in links:
            managers_by_person.setdefault(str(link["canonical_manager_id"]), set()).add(
                str(link["manager_key"])
            )
        verified_accounts = conn.execute(
            """
            SELECT person_id, account_id, platform, manager_key
              FROM sharp_platform_accounts
             WHERE verification_status='verified'
            """
        ).fetchall()
        account_by_manager = {
            str(row["manager_key"]): row for row in verified_accounts if row["manager_key"]
        }
        fantasy_accounts_by_person: dict[str, list[sqlite3.Row]] = {}
        for row in verified_accounts:
            if str(row["platform"]) in FANTASY_PLATFORMS:
                fantasy_accounts_by_person.setdefault(str(row["person_id"]), []).append(row)
        people = conn.execute(
            """
            SELECT p.person_id, p.curated_expertise_score, p.trackability_score,
                   p.candidate_status, p.current_activity,
                   m.curated_industry_sharp
              FROM sharp_people p
              JOIN sharp_model_membership m ON m.person_id=p.person_id
            """
        ).fetchall()
        for person in people:
            stats["people"] += 1
            person_id = str(person["person_id"])
            linked_keys = managers_by_person.get(person_id, set())
            linked_scores = [score_by_key[key] for key in linked_keys if key in score_by_key]
            qualified_scores = [item for item in linked_scores if item.qualified]
            algorithmic = bool(qualified_scores)
            curated = bool(person["curated_industry_sharp"])
            super_sharp = bool(curated and fantasy_accounts_by_person.get(person_id))
            if algorithmic:
                stats["performanceQualified"] += 1
            if super_sharp:
                stats["superSharps"] += 1
            if curated and algorithmic:
                stats["both"] += 1
            empirical = max(
                (float(item.score or 0.0) / 100.0 for item in qualified_scores or linked_scores),
                default=None,
            )
            curated_weight = (
                float(person["curated_expertise_score"] or 0.0) / 100.0
                if person["curated_expertise_score"] is not None
                else None
            )
            trackability = (
                float(person["trackability_score"] or 0.0) / 100.0
                if person["trackability_score"] is not None
                else None
            )
            if empirical is None:
                combined = None
                if curated_weight is not None:
                    combined = 0.85 * curated_weight + 0.15 * float(trackability or 0.0)
            else:
                combined = (
                    0.60 * float(curated_weight or 0.0)
                    + 0.30 * empirical
                    + 0.10 * float(trackability or 0.0)
                )
            if curated and algorithmic:
                state = "both_curated_and_performance"
            elif super_sharp:
                state = "trackable_curated_sharp"
            elif curated:
                state = "curated_only"
            elif algorithmic:
                state = "performance_qualified_only"
            else:
                state = str(person["candidate_status"] or "candidate_under_review")
            conn.execute(
                """
                UPDATE sharp_model_membership SET
                  algorithmically_qualified_sharp=?, verified_super_sharp=?,
                  membership_state=?, empirical_weight=?,
                  combined_influence=?, active=?, last_evaluated_ms=?
                WHERE person_id=?
                """,
                (
                    int(algorithmic),
                    int(super_sharp),
                    state,
                    empirical,
                    combined,
                    int(bool(person["current_activity"])),
                    now,
                    person_id,
                ),
            )
            for manager_key in linked_keys:
                record = record_by_key.get(manager_key)
                score_item = score_by_key.get(manager_key)
                if record is None and score_item is None:
                    continue
                account = account_by_manager.get(manager_key)
                metric_id = _metric_id(person_id, manager_key)
                completeness = float(score_item.confidence if score_item else 0.0)
                conn.execute(
                    """
                    INSERT INTO sharp_performance_metrics(
                      metric_id, person_id, platform_account_id, manager_key,
                      league_type, seasons_observed, completed_leagues,
                      active_leagues, regular_season_wins,
                      regular_season_losses, regular_season_ties,
                      winning_percentage, playoff_appearances, championships,
                      portfolio_size, data_completeness,
                      sample_size_confidence, empirical_score,
                      empirical_score_percentile, methodology_version,
                      last_calculated_ms, metadata_json
                    ) VALUES(?, ?, ?, ?, 'dynasty', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(metric_id) DO UPDATE SET
                      platform_account_id=excluded.platform_account_id,
                      seasons_observed=excluded.seasons_observed,
                      completed_leagues=excluded.completed_leagues,
                      active_leagues=excluded.active_leagues,
                      regular_season_wins=excluded.regular_season_wins,
                      regular_season_losses=excluded.regular_season_losses,
                      regular_season_ties=excluded.regular_season_ties,
                      winning_percentage=excluded.winning_percentage,
                      playoff_appearances=excluded.playoff_appearances,
                      championships=excluded.championships,
                      portfolio_size=excluded.portfolio_size,
                      data_completeness=excluded.data_completeness,
                      sample_size_confidence=excluded.sample_size_confidence,
                      empirical_score=excluded.empirical_score,
                      empirical_score_percentile=excluded.empirical_score_percentile,
                      methodology_version=excluded.methodology_version,
                      last_calculated_ms=excluded.last_calculated_ms,
                      metadata_json=excluded.metadata_json
                    """,
                    (
                        metric_id,
                        person_id,
                        account["account_id"] if account else None,
                        manager_key,
                        record.completed_seasons if record else None,
                        record.dynasty_leagues if record else None,
                        max(0, (record.observed_leagues - record.completed_seasons))
                        if record
                        else None,
                        record.wins if record else None,
                        record.losses if record else None,
                        record.ties if record else None,
                        record.win_pct if record else None,
                        record.playoff_appearances if record else None,
                        record.championships if record else None,
                        record.observed_leagues if record else None,
                        completeness,
                        completeness,
                        score_item.score if score_item else None,
                        score_item.score_percentile if score_item else None,
                        score_item.methodology_version
                        if score_item
                        else sharp_score.methodology_version(),
                        now,
                        _json(
                            {
                                "qualified": bool(score_item.qualified) if score_item else False,
                                "ineligibleReasons": score_item.ineligible_reasons
                                if score_item
                                else [],
                            },
                            {},
                        ),
                    ),
                )
        if own_connection:
            conn.commit()
    finally:
        if own_connection:
            conn.close()
    return stats


def curated_cohort_members(
    *,
    mode: str = "all",
    ledger_path: Path | None = None,
) -> list[CuratedCohortMember]:
    """Verified platform identities eligible to contribute behavior signals.

    Untrackable curated people stay in the people/model APIs but cannot create
    behavioral votes until a public identity is verified.  One person with
    multiple accounts remains one canonical person via manager_identity_links.
    """

    allowed = {"all", "curated_industry", "super", "both"}
    if mode not in allowed:
        raise ValueError(f"unsupported curated cohort mode: {mode}")
    conn = ensure_schema(ledger_path)
    try:
        rows = conn.execute(
            """
            SELECT a.manager_key, a.person_id, a.platform, p.public_display_name,
                   p.current_affiliation, p.curated_expertise_score,
                   m.algorithmically_qualified_sharp, m.verified_super_sharp
              FROM sharp_platform_accounts a
              JOIN sharp_people p ON p.person_id=a.person_id
              JOIN sharp_model_membership m ON m.person_id=a.person_id
             WHERE a.verification_status='verified'
               AND a.manager_key IS NOT NULL AND a.manager_key<>''
               AND m.curated_industry_sharp=1 AND m.active=1
            """
        ).fetchall()
    finally:
        conn.close()
    out: list[CuratedCohortMember] = []
    for row in rows:
        both = bool(row["algorithmically_qualified_sharp"])
        super_sharp = bool(row["verified_super_sharp"])
        if mode == "super" and not super_sharp:
            continue
        if mode == "both" and not both:
            continue
        method = "both_curated_and_performance" if both else "curated_industry"
        out.append(
            CuratedCohortMember(
                manager_key=str(row["manager_key"]),
                person_id=str(row["person_id"]),
                platform=str(row["platform"]),
                qualification_method=method,
                quality=max(0.0, min(1.0, float(row["curated_expertise_score"] or 75.0) / 100.0)),
                display_name=str(row["public_display_name"] or "") or None,
                network=str(row["current_affiliation"] or "") or None,
            )
        )
    return out


def _decode_json(value: Any, default: Any) -> Any:
    try:
        return json.loads(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def people_payload(
    *,
    membership: str = "all",
    platform: str = "all",
    specialty: str = "all",
    identity: str = "all",
    search: str = "",
    limit: int = 500,
    offset: int = 0,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    allowed_membership = {
        "all",
        "curated",
        "performance",
        "both",
        "super",
        "research",
        "screened_out",
    }
    if membership not in allowed_membership:
        raise ValueError(f"unsupported membership filter: {membership}")
    if platform not in {"all", "sleeper", "ffpc", "x"}:
        raise ValueError(f"unsupported platform filter: {platform}")
    if specialty not in {"all", "idp", "devy", "high_stakes", "analyst"}:
        raise ValueError(f"unsupported specialty filter: {specialty}")
    if identity not in {"all", "verified", "probable", "unresolved", "untrackable"}:
        raise ValueError(f"unsupported identity filter: {identity}")
    conn = ensure_schema(ledger_path)
    try:
        people = conn.execute(
            """
            SELECT p.*, m.*
              FROM sharp_people p
              JOIN sharp_model_membership m ON m.person_id=p.person_id
             ORDER BY COALESCE(m.combined_influence, m.curated_weight, 0) DESC,
                      p.public_display_name COLLATE NOCASE
            """
        ).fetchall()
        accounts = conn.execute(
            "SELECT * FROM sharp_platform_accounts ORDER BY platform, verification_status, username"
        ).fetchall()
        metrics = conn.execute(
            """
            SELECT * FROM sharp_performance_metrics
             ORDER BY last_calculated_ms DESC
            """
        ).fetchall()
        candidates = conn.execute(
            """
            SELECT person_id, verification_status, COUNT(*) AS n,
                   MAX(confidence) AS max_confidence
              FROM sharp_identity_candidates
             GROUP BY person_id, verification_status
            """
        ).fetchall()
        evidence_counts = conn.execute(
            "SELECT person_id, COUNT(*) AS n FROM sharp_identity_evidence GROUP BY person_id"
        ).fetchall()
    finally:
        conn.close()
    accounts_by_person: dict[str, list[dict[str, Any]]] = {}
    for row in accounts:
        item = dict(row)
        item["metadata"] = _decode_json(item.pop("metadata_json", None), {})
        accounts_by_person.setdefault(str(row["person_id"]), []).append(item)
    metrics_by_person: dict[str, list[dict[str, Any]]] = {}
    for row in metrics:
        item = dict(row)
        item["metadata"] = _decode_json(item.pop("metadata_json", None), {})
        metrics_by_person.setdefault(str(row["person_id"]), []).append(item)
    candidates_by_person: dict[str, dict[str, Any]] = {}
    for row in candidates:
        summary = candidates_by_person.setdefault(str(row["person_id"]), {})
        summary[str(row["verification_status"])] = {
            "count": int(row["n"]),
            "maxConfidence": row["max_confidence"],
        }
    evidence_by_person = {str(row["person_id"]): int(row["n"]) for row in evidence_counts}

    search_norm = normalize_identity(search)
    output: list[dict[str, Any]] = []
    for row in people:
        item = dict(row)
        person_id = str(row["person_id"])
        person_accounts = accounts_by_person.get(person_id, [])
        verified_accounts = [a for a in person_accounts if a["verification_status"] == "verified"]
        if membership == "curated" and not row["curated_industry_sharp"]:
            continue
        if membership == "performance" and not row["algorithmically_qualified_sharp"]:
            continue
        if membership == "both" and not (
            row["curated_industry_sharp"] and row["algorithmically_qualified_sharp"]
        ):
            continue
        if membership == "super" and not row["verified_super_sharp"]:
            continue
        if membership == "research" and row["candidate_status"] not in {
            "research_candidate",
            "inactive_or_historical",
            "insufficient_identity_information",
        }:
            continue
        if membership == "screened_out" and row["candidate_status"] != "screened_out":
            continue
        if platform != "all" and not any(a["platform"] == platform for a in person_accounts):
            continue
        if specialty == "idp" and not row["idp_specialist"]:
            continue
        if specialty == "devy" and not row["devy_c2c_specialist"]:
            continue
        if specialty == "high_stakes" and not row["high_stakes_specialist"]:
            continue
        if specialty == "analyst" and row["primary_category"] == "High-stakes player":
            continue
        candidate_summary = candidates_by_person.get(person_id, {})
        if identity == "verified" and not verified_accounts:
            continue
        if identity == "probable" and not any(
            key in candidate_summary for key in PROBABLE_STATUSES
        ):
            continue
        if identity == "unresolved" and not any(
            key in candidate_summary for key in OPEN_REVIEW_STATUSES
        ):
            continue
        if identity == "untrackable" and verified_accounts:
            continue
        haystack = normalize_identity(
            " ".join(
                str(value or "")
                for value in (
                    row["canonical_name"],
                    row["public_display_name"],
                    row["pseudonym"],
                    row["primary_public_handle"],
                    row["current_affiliation"],
                )
            )
        )
        if search_norm and search_norm not in haystack:
            continue
        item["dynastySpecialties"] = _decode_json(item.pop("dynasty_specialties_json", None), [])
        item["membershipMetadata"] = _decode_json(item.pop("metadata_json", None), {})
        item["accounts"] = person_accounts
        item["verifiedPlatformIdentities"] = verified_accounts
        item["performanceMetrics"] = metrics_by_person.get(person_id, [])
        item["identityCandidateSummary"] = candidate_summary
        item["evidenceCount"] = evidence_by_person.get(person_id, 0)
        output.append(item)
    total = len(output)
    output = output[max(0, int(offset)) : max(0, int(offset)) + max(1, min(int(limit), 1000))]
    return {
        "status": "ok",
        "generatedAt": _now_ms(),
        "filters": {
            "membership": membership,
            "platform": platform,
            "specialty": specialty,
            "identity": identity,
            "search": search,
        },
        "total": total,
        "people": output,
        "summary": summary_payload(ledger_path=ledger_path),
    }


def person_payload(person_id: str, *, ledger_path: Path | None = None) -> dict[str, Any] | None:
    payload = people_payload(limit=1000, ledger_path=ledger_path)
    for person in payload["people"]:
        if person["person_id"] == person_id:
            conn = ensure_schema(ledger_path)
            try:
                evidence = [
                    dict(row)
                    for row in conn.execute(
                        """
                        SELECT evidence_type, description, source_url, source_date,
                               supports_match, confidence_contribution,
                               reviewed_status, source_workbook_sheet,
                               source_workbook_row, metadata_json
                          FROM sharp_identity_evidence WHERE person_id=?
                         ORDER BY source_workbook_sheet, source_workbook_row, evidence_id
                        """,
                        (person_id,),
                    ).fetchall()
                ]
                candidates = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM sharp_identity_candidates WHERE person_id=? ORDER BY confidence DESC",
                        (person_id,),
                    ).fetchall()
                ]
            finally:
                conn.close()
            for row in evidence:
                row["metadata"] = _decode_json(row.pop("metadata_json", None), {})
            for row in candidates:
                row["supports"] = _decode_json(row.pop("supports_json", None), [])
                row["contradicts"] = _decode_json(row.pop("contradicts_json", None), [])
                row["metadata"] = _decode_json(row.pop("metadata_json", None), {})
            person["evidence"] = evidence
            person["identityCandidates"] = candidates
            return person
    return None


def review_queue_payload(
    *,
    platform: str = "all",
    status: str = "open",
    limit: int = 500,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    conn = ensure_schema(ledger_path)
    try:
        clauses = []
        params: list[Any] = []
        if platform != "all":
            clauses.append("c.platform=?")
            params.append(platform)
        if status == "open":
            clauses.append(
                "c.verification_status IN ('possible','unresolved','high_confidence_probable','conflict')"
            )
        elif status != "all":
            clauses.append("c.verification_status=?")
            params.append(status)
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = conn.execute(
            f"""
            SELECT c.*, p.canonical_name, p.public_display_name,
                   p.primary_public_handle, p.current_affiliation
              FROM sharp_identity_candidates c
              JOIN sharp_people p ON p.person_id=c.person_id
              {where}
             ORDER BY CASE c.verification_status
                        WHEN 'conflict' THEN 0
                        WHEN 'high_confidence_probable' THEN 1
                        WHEN 'possible' THEN 2 ELSE 3 END,
                      c.confidence DESC, p.public_display_name
             LIMIT ?
            """,
            (*params, max(1, min(int(limit), 1000))),
        ).fetchall()
    finally:
        conn.close()
    output = []
    for row in rows:
        item = dict(row)
        item["supports"] = _decode_json(item.pop("supports_json", None), [])
        item["contradicts"] = _decode_json(item.pop("contradicts_json", None), [])
        item["metadata"] = _decode_json(item.pop("metadata_json", None), {})
        output.append(item)
    return {"status": "ok", "total": len(output), "candidates": output}


def summary_payload(*, ledger_path: Path | None = None) -> dict[str, Any]:
    conn = ensure_schema(ledger_path)
    try:
        statuses = {
            str(row["candidate_status"]): int(row["n"])
            for row in conn.execute(
                "SELECT candidate_status, COUNT(*) AS n FROM sharp_people GROUP BY candidate_status"
            ).fetchall()
        }
        membership = dict(
            conn.execute(
                """
                SELECT
                  COUNT(*) AS total_people,
                  SUM(curated_industry_sharp) AS curated_people,
                  SUM(algorithmically_qualified_sharp) AS performance_qualified_people,
                  SUM(verified_super_sharp) AS super_sharps,
                  SUM(CASE WHEN curated_industry_sharp=1 AND algorithmically_qualified_sharp=1 THEN 1 ELSE 0 END) AS both,
                  SUM(CASE WHEN curated_industry_sharp=1 AND verified_super_sharp=0 THEN 1 ELSE 0 END) AS untrackable_curated
                FROM sharp_model_membership
                """
            ).fetchone()
        )
        identity = {
            str(row["verification_status"]): int(row["n"])
            for row in conn.execute(
                """
                SELECT verification_status, COUNT(*) AS n
                  FROM sharp_platform_accounts GROUP BY verification_status
                """
            ).fetchall()
        }
        candidates = {
            str(row["verification_status"]): int(row["n"])
            for row in conn.execute(
                """
                SELECT verification_status, COUNT(*) AS n
                  FROM sharp_identity_candidates GROUP BY verification_status
                """
            ).fetchall()
        }
        platform_accounts = {
            str(row["platform"]): int(row["n"])
            for row in conn.execute(
                """
                SELECT platform, COUNT(*) AS n FROM sharp_platform_accounts
                 WHERE verification_status='verified' GROUP BY platform
                """
            ).fetchall()
        }
        latest_import = conn.execute(
            "SELECT * FROM sharp_import_runs ORDER BY started_ms DESC LIMIT 1"
        ).fetchone()
        activity = dict(
            conn.execute(
                """
                SELECT COUNT(*) AS activity_events,
                       COUNT(DISTINCT person_id) AS people_with_activity
                  FROM sharp_activity_events WHERE person_id IS NOT NULL
                """
            ).fetchone()
        )
    finally:
        conn.close()
    return {
        "candidateStatuses": statuses,
        "membership": membership,
        "verifiedAccountsByPlatform": platform_accounts,
        "accountVerificationStatuses": identity,
        "identityCandidateStatuses": candidates,
        "activity": activity,
        "latestImport": dict(latest_import) if latest_import else None,
    }


def reconciliation_report(*, ledger_path: Path | None = None) -> dict[str, Any]:
    summary = summary_payload(ledger_path=ledger_path)
    membership = summary["membership"]
    accounts = summary["verifiedAccountsByPlatform"]
    statuses = summary["candidateStatuses"]
    conn = ensure_schema(ledger_path)
    try:
        candidate_rows = conn.execute(
            """
            SELECT platform, verification_status, COUNT(*) AS n
              FROM sharp_identity_candidates
             GROUP BY platform, verification_status
            """
        ).fetchall()
        candidates_by_platform: dict[str, dict[str, int]] = {}
        for row in candidate_rows:
            candidates_by_platform.setdefault(str(row["platform"]), {})[
                str(row["verification_status"])
            ] = int(row["n"])
        ffpc_names = int(
            conn.execute(
                """
                SELECT COUNT(DISTINCT candidate_team_or_entry_name)
                  FROM sharp_identity_candidates
                 WHERE platform='ffpc'
                   AND candidate_team_or_entry_name IS NOT NULL
                   AND TRIM(candidate_team_or_entry_name)<>''
                """
            ).fetchone()[0]
            or 0
        )
        rejected = int(
            conn.execute(
                "SELECT COUNT(*) FROM sharp_identity_candidates WHERE verification_status='rejected_match'"
            ).fetchone()[0]
            or 0
        )
    finally:
        conn.close()
    sleeper_candidates = candidates_by_platform.get("sleeper", {})
    probable_sleeper = sum(
        sleeper_candidates.get(status, 0) for status in ("high_confidence_probable", "probable")
    )
    unresolved_sleeper = sum(
        sleeper_candidates.get(status, 0) for status in ("unresolved", "possible", "conflict")
    )
    return {
        "generatedAt": _now_ms(),
        "totalWorkbookIdentitiesReviewed": sum(statuses.values()),
        "totalImportedAsCuratedSharps": int(membership.get("curated_people") or 0),
        "totalImportedAsResearchCandidates": int(statuses.get("research_candidate") or 0)
        + int(statuses.get("inactive_or_historical") or 0)
        + int(statuses.get("insufficient_identity_information") or 0),
        "totalScreenedOutStored": int(statuses.get("screened_out") or 0),
        "totalPositivelyVerifiedOnSleeper": int(accounts.get("sleeper") or 0),
        "totalProbableSleeperMatches": probable_sleeper,
        "totalUnresolvedSleeperIdentities": unresolved_sleeper,
        "totalPositivelyVerifiedOnFFPC": int(accounts.get("ffpc") or 0),
        "totalFFPCTeamOrEntryNamesFound": ffpc_names,
        "totalSuperSharps": int(membership.get("super_sharps") or 0),
        "totalWithUsablePublicActivity": int(summary["activity"].get("people_with_activity") or 0),
        "totalRejectedIdentityMatches": rejected,
        "totalDuplicateIdentitiesMerged": int(
            (summary.get("latestImport") or {}).get("duplicates_merged") or 0
        ),
        "totalActivityEventsImported": int(summary["activity"].get("activity_events") or 0),
        "candidateStatusCounts": statuses,
        "identityCandidateStatusCounts": summary["identityCandidateStatuses"],
        "identityCandidatesByPlatform": candidates_by_platform,
    }


def _export_value(value: Any) -> Any:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _write_rows(output_dir: Path, stem: str, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{stem}.json"
    csv_path = output_dir / f"{stem}.csv"
    json_path.write_text(
        json.dumps(list(rows), ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    columns: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                columns.append(key)
    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        if columns:
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _export_value(row.get(key)) for key in columns})
    return {"count": len(rows), "json": str(json_path), "csv": str(csv_path)}


def export_reconciliation(
    output_dir: Path | str,
    *,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Write the requested machine-readable reconciliation artifacts.

    The files contain public workbook evidence and model metadata only. Raw
    platform payloads and internal authentication/session data are never
    exported.
    """

    target = Path(output_dir)
    conn = ensure_schema(ledger_path)
    try:
        imported_people = [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.*, m.curated_industry_sharp,
                       m.algorithmically_qualified_sharp, m.verified_super_sharp,
                       m.membership_state, m.combined_influence,
                       m.last_evaluated_ms
                  FROM sharp_people p
                  LEFT JOIN sharp_model_membership m ON m.person_id=p.person_id
                 ORDER BY p.public_display_name, p.person_id
                """
            ).fetchall()
        ]
        verified_identities = [
            dict(row)
            for row in conn.execute(
                """
                SELECT a.*, p.public_display_name AS person_name,
                       p.primary_public_handle, p.current_affiliation
                  FROM sharp_platform_accounts a
                  JOIN sharp_people p ON p.person_id=a.person_id
                 WHERE a.verification_status='verified'
                 ORDER BY a.platform, p.public_display_name, a.username
                """
            ).fetchall()
        ]
        candidate_rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT c.*, p.public_display_name AS person_name,
                       p.primary_public_handle, p.current_affiliation
                  FROM sharp_identity_candidates c
                  JOIN sharp_people p ON p.person_id=c.person_id
                 ORDER BY c.platform, c.verification_status,
                          c.confidence DESC, p.public_display_name
                """
            ).fetchall()
        ]
        probable_matches = [
            row
            for row in candidate_rows
            if row.get("verification_status") in {"probable", "high_confidence_probable"}
        ]
        unresolved_identities = [
            row
            for row in candidate_rows
            if row.get("verification_status") in {"unresolved", "possible", "conflict"}
        ]
        rejected_matches = [
            row for row in candidate_rows if row.get("verification_status") == "rejected_match"
        ]
        super_sharps = [
            dict(row)
            for row in conn.execute(
                """
                SELECT p.person_id, p.canonical_name, p.public_display_name,
                       p.primary_public_handle, p.current_affiliation,
                       p.primary_category, p.dynasty_specialties_json,
                       p.curated_expertise_score, p.trackability_score,
                       m.membership_state, m.combined_influence,
                       GROUP_CONCAT(DISTINCT a.platform) AS verified_platforms,
                       GROUP_CONCAT(DISTINCT a.username) AS verified_usernames
                  FROM sharp_people p
                  JOIN sharp_model_membership m ON m.person_id=p.person_id
                  LEFT JOIN sharp_platform_accounts a
                    ON a.person_id=p.person_id AND a.verification_status='verified'
                 WHERE m.verified_super_sharp=1
                 GROUP BY p.person_id
                 ORDER BY m.combined_influence DESC, p.public_display_name
                """
            ).fetchall()
        ]
        source_evidence = [
            dict(row)
            for row in conn.execute(
                """
                SELECT e.*, p.public_display_name AS person_name
                  FROM sharp_identity_evidence e
                  JOIN sharp_people p ON p.person_id=e.person_id
                 ORDER BY p.public_display_name, e.source_workbook_sheet,
                          e.source_workbook_row, e.evidence_id
                """
            ).fetchall()
        ]
    finally:
        conn.close()

    artifacts = {
        "imported_people": _write_rows(target, "imported_people", imported_people),
        "verified_identities": _write_rows(target, "verified_identities", verified_identities),
        "probable_matches": _write_rows(target, "probable_matches", probable_matches),
        "unresolved_identities": _write_rows(
            target, "unresolved_identities", unresolved_identities
        ),
        "rejected_matches": _write_rows(target, "rejected_matches", rejected_matches),
        "super_sharps": _write_rows(target, "super_sharps", super_sharps),
        "source_evidence": _write_rows(target, "source_evidence", source_evidence),
    }
    report = reconciliation_report(ledger_path=ledger_path)
    report_path = target / "reconciliation_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    artifacts["reconciliation_report"] = {"count": 1, "json": str(report_path)}
    return artifacts
