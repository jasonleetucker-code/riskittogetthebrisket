"""Additive platform-neutral extension of :mod:`src.intel.ledger`.

The original ledger is deliberately left backward compatible: existing
Sleeper primary keys and query functions remain valid.  This module adds
platform-scoped identity columns/tables, backfills every legacy row as
``platform='sleeper'``, and exposes the generalized read/write API used by
the unified Sleeper + FFPC Sharp Tracker.

No production data is rebuilt.  The migration is additive, transactional
and idempotent.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

from src.intel import ledger
from src.platforms.base import (
    NormalizedBatch,
    NormalizedLeague,
    NormalizedManager,
    NormalizedManagerSeason,
    NormalizedMembership,
    NormalizedMovement,
    NormalizedTransaction,
)

log = logging.getLogger(__name__)

PLATFORM_SCHEMA_VERSION = 2
MIGRATION_META_KEY = "platform_schema_version"

_ADDITIVE_COLUMNS: dict[str, dict[str, str]] = {
    "transactions": {
        "platform": "TEXT",
        "transaction_key": "TEXT",
        "source_transaction_id": "TEXT",
        "league_key": "TEXT",
        "metadata_json": "TEXT",
    },
    "asset_movements": {
        "platform": "TEXT",
        "movement_key": "TEXT",
        "transaction_key": "TEXT",
        "league_key": "TEXT",
        "canonical_asset_id": "TEXT",
        "source_asset_id": "TEXT",
        "manager_key": "TEXT",
        "counterparty_manager_key": "TEXT",
        "timestamp_ms": "INTEGER",
        "metadata_json": "TEXT",
    },
    "manager_seasons": {
        "platform": "TEXT",
        "league_key": "TEXT",
        "manager_key": "TEXT",
        "source_identity_type": "TEXT",
        "evidence_status": "TEXT",
        "exclusion_reasons_json": "TEXT",
        "metadata_json": "TEXT",
    },
    # Supports recovery from an interrupted/early platform-v2 rollout.
    # Fresh legacy ledgers do not have this table yet, so _add_columns
    # skips absent tables and _PLATFORM_SCHEMA creates it in full.
    "ingestion_runs": {
        "automated_ffpc_qualifiers": "INTEGER NOT NULL DEFAULT 0",
        "curated_ffpc_contributors": "INTEGER NOT NULL DEFAULT 0",
    },
}

_PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_managers (
  manager_key          TEXT PRIMARY KEY,
  platform             TEXT NOT NULL,
  source_manager_id    TEXT NOT NULL,
  username             TEXT,
  display_name         TEXT,
  source_identity_type TEXT NOT NULL,
  identity_scope       TEXT,
  identity_confidence  REAL,
  canonical_manager_id TEXT,
  first_seen_ms        INTEGER,
  last_seen_ms         INTEGER,
  metadata_json        TEXT,
  UNIQUE(platform, source_manager_id)
);

CREATE TABLE IF NOT EXISTS manager_identity_links (
  manager_key          TEXT PRIMARY KEY,
  canonical_manager_id TEXT NOT NULL,
  link_method          TEXT NOT NULL,
  link_confidence      REAL NOT NULL,
  verified             INTEGER NOT NULL,
  created_ms           INTEGER NOT NULL,
  metadata_json        TEXT
);

CREATE TABLE IF NOT EXISTS platform_leagues (
  league_key                 TEXT PRIMARY KEY,
  platform                   TEXT NOT NULL,
  source_league_id           TEXT NOT NULL,
  season                     TEXT,
  previous_source_league_id  TEXT,
  name                       TEXT,
  total_rosters              INTEGER,
  format_type                TEXT,
  is_dynasty                 INTEGER,
  sharp_eligible             INTEGER,
  first_seen_ms              INTEGER,
  last_crawled_ms            INTEGER,
  metadata_json              TEXT,
  UNIQUE(platform, source_league_id)
);

CREATE TABLE IF NOT EXISTS platform_memberships (
  platform       TEXT NOT NULL,
  league_key     TEXT NOT NULL,
  manager_key    TEXT NOT NULL,
  source_team_id TEXT,
  roster_id      TEXT,
  team_name      TEXT,
  last_seen_ms   INTEGER,
  metadata_json  TEXT,
  PRIMARY KEY (league_key, manager_key)
);

CREATE TABLE IF NOT EXISTS canonical_assets (
  canonical_asset_id TEXT PRIMARY KEY,
  display_name       TEXT,
  normalized_name    TEXT,
  asset_type         TEXT NOT NULL,
  nfl_team           TEXT,
  position           TEXT,
  metadata_json      TEXT,
  first_seen_ms      INTEGER,
  last_seen_ms       INTEGER
);

CREATE TABLE IF NOT EXISTS asset_aliases (
  platform           TEXT NOT NULL,
  source_asset_id    TEXT NOT NULL,
  canonical_asset_id TEXT,
  source_name        TEXT,
  normalized_name    TEXT,
  nfl_team           TEXT,
  position           TEXT,
  match_method       TEXT,
  match_confidence   REAL,
  manually_verified  INTEGER,
  metadata_json      TEXT,
  first_seen_ms      INTEGER,
  last_seen_ms       INTEGER,
  PRIMARY KEY (platform, source_asset_id)
);

CREATE TABLE IF NOT EXISTS unmapped_assets (
  platform        TEXT NOT NULL,
  source_asset_id TEXT NOT NULL,
  source_name     TEXT,
  normalized_name TEXT,
  nfl_team        TEXT,
  position        TEXT,
  reason          TEXT,
  candidates_json TEXT,
  first_seen_ms   INTEGER,
  last_seen_ms    INTEGER,
  occurrences     INTEGER NOT NULL DEFAULT 1,
  metadata_json   TEXT,
  PRIMARY KEY (platform, source_asset_id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  run_id          TEXT PRIMARY KEY,
  platform        TEXT NOT NULL,
  source_ref      TEXT,
  started_ms      INTEGER NOT NULL,
  finished_ms     INTEGER,
  status          TEXT NOT NULL,
  pages_fetched   INTEGER NOT NULL DEFAULT 0,
  pages_parsed    INTEGER NOT NULL DEFAULT 0,
  parse_failures  INTEGER NOT NULL DEFAULT 0,
  transactions_discovered INTEGER NOT NULL DEFAULT 0,
  transactions_deduplicated INTEGER NOT NULL DEFAULT 0,
  movements_inserted INTEGER NOT NULL DEFAULT 0,
  movements_skipped INTEGER NOT NULL DEFAULT 0,
  unmapped_players INTEGER NOT NULL DEFAULT 0,
  ambiguous_manager_identities INTEGER NOT NULL DEFAULT 0,
  automated_ffpc_qualifiers INTEGER NOT NULL DEFAULT 0,
  curated_ffpc_contributors INTEGER NOT NULL DEFAULT 0,
  error_json       TEXT,
  metadata_json    TEXT
);

CREATE INDEX IF NOT EXISTS idx_pm_platform ON platform_managers(platform);
CREATE INDEX IF NOT EXISTS idx_pm_canonical ON platform_managers(canonical_manager_id);
CREATE INDEX IF NOT EXISTS idx_mil_canonical
  ON manager_identity_links(canonical_manager_id);
CREATE INDEX IF NOT EXISTS idx_pl_platform ON platform_leagues(platform);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON asset_aliases(canonical_asset_id);
CREATE INDEX IF NOT EXISTS idx_am_platform_ts ON asset_movements(platform, ts);
CREATE INDEX IF NOT EXISTS idx_am_canonical_ts ON asset_movements(canonical_asset_id, ts);
CREATE INDEX IF NOT EXISTS idx_am_manager_key_ts ON asset_movements(manager_key, ts);
CREATE INDEX IF NOT EXISTS idx_am_league_key_ts ON asset_movements(league_key, ts);
CREATE INDEX IF NOT EXISTS idx_am_platform_source
  ON asset_movements(platform, source_asset_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tx_transaction_key
  ON transactions(transaction_key) WHERE transaction_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_am_movement_key
  ON asset_movements(movement_key) WHERE movement_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ms_manager_key
  ON manager_seasons(manager_key);
CREATE INDEX IF NOT EXISTS idx_ms_platform
  ON manager_seasons(platform, season);
"""

_TRIGGER_SCHEMA = """
CREATE TRIGGER IF NOT EXISTS trg_transactions_sleeper_platform
AFTER INSERT ON transactions
WHEN NEW.platform IS NULL
BEGIN
  UPDATE transactions
     SET platform='sleeper',
         source_transaction_id=NEW.tx_id,
         transaction_key='sleeper:' || NEW.tx_id,
         league_key='sleeper:' || NEW.league_id
   WHERE tx_id=NEW.tx_id;
  INSERT OR IGNORE INTO platform_leagues
    (league_key, platform, source_league_id, first_seen_ms,
     last_crawled_ms, metadata_json)
  VALUES ('sleeper:' || NEW.league_id, 'sleeper', NEW.league_id,
          NEW.ingested_ms, NEW.ingested_ms, '{}');
END;

CREATE TRIGGER IF NOT EXISTS trg_movements_sleeper_platform
AFTER INSERT ON asset_movements
WHEN NEW.platform IS NULL
BEGIN
  UPDATE asset_movements
     SET platform='sleeper',
         movement_key='sleeper:' || NEW.movement_id,
         transaction_key='sleeper:' || NEW.tx_id,
         league_key='sleeper:' || NEW.league_id,
         canonical_asset_id=NEW.asset_id,
         source_asset_id=NEW.asset_id,
         manager_key='sleeper:' || NEW.user_id,
         counterparty_manager_key=CASE
           WHEN NEW.counterparty_user_id IS NULL OR NEW.counterparty_user_id=''
           THEN NULL ELSE 'sleeper:' || NEW.counterparty_user_id END,
         timestamp_ms=NEW.ts
   WHERE movement_id=NEW.movement_id;
END;

CREATE TRIGGER IF NOT EXISTS trg_manager_seasons_sleeper_platform
AFTER INSERT ON manager_seasons
WHEN NEW.platform IS NULL
BEGIN
  UPDATE manager_seasons
     SET platform='sleeper',
         league_key='sleeper:' || NEW.league_id,
         manager_key='sleeper:' || NEW.user_id,
         source_identity_type='global_verified',
         evidence_status=CASE
           WHEN NEW.is_complete=1 AND NEW.sharp_eligible=1
           THEN 'automated_evidence' ELSE 'insufficient_history' END
   WHERE league_id=NEW.league_id AND season=NEW.season AND user_id=NEW.user_id;
  INSERT OR IGNORE INTO platform_managers
    (manager_key, platform, source_manager_id, source_identity_type,
     identity_scope, identity_confidence, first_seen_ms, last_seen_ms, metadata_json)
  VALUES ('sleeper:' || NEW.user_id, 'sleeper', NEW.user_id,
          'global_verified', 'platform', 1.0, NEW.crawled_ms, NEW.crawled_ms, '{}');
  INSERT OR IGNORE INTO platform_leagues
    (league_key, platform, source_league_id, season, first_seen_ms,
     last_crawled_ms, metadata_json)
  VALUES ('sleeper:' || NEW.league_id, 'sleeper', NEW.league_id, NEW.season,
          NEW.crawled_ms, NEW.crawled_ms, '{}');
END;

CREATE TRIGGER IF NOT EXISTS trg_sleeper_users_platform_insert
AFTER INSERT ON sleeper_users
BEGIN
  INSERT INTO platform_managers
    (manager_key, platform, source_manager_id, username, display_name,
     source_identity_type, identity_scope, identity_confidence,
     first_seen_ms, last_seen_ms, metadata_json)
  VALUES ('sleeper:' || NEW.user_id, 'sleeper', NEW.user_id,
          NEW.current_username, NEW.display_name, 'global_verified',
          'platform', 1.0, NEW.first_seen_ms, NEW.last_seen_ms, '{}')
  ON CONFLICT(manager_key) DO UPDATE SET
    username=COALESCE(excluded.username, platform_managers.username),
    display_name=COALESCE(excluded.display_name, platform_managers.display_name),
    last_seen_ms=MAX(COALESCE(platform_managers.last_seen_ms, 0),
                     COALESCE(excluded.last_seen_ms, 0));
END;

CREATE TRIGGER IF NOT EXISTS trg_sleeper_users_platform_update
AFTER UPDATE ON sleeper_users
BEGIN
  INSERT INTO platform_managers
    (manager_key, platform, source_manager_id, username, display_name,
     source_identity_type, identity_scope, identity_confidence,
     first_seen_ms, last_seen_ms, metadata_json)
  VALUES ('sleeper:' || NEW.user_id, 'sleeper', NEW.user_id,
          NEW.current_username, NEW.display_name, 'global_verified',
          'platform', 1.0, NEW.first_seen_ms, NEW.last_seen_ms, '{}')
  ON CONFLICT(manager_key) DO UPDATE SET
    username=COALESCE(excluded.username, platform_managers.username),
    display_name=COALESCE(excluded.display_name, platform_managers.display_name),
    last_seen_ms=MAX(COALESCE(platform_managers.last_seen_ms, 0),
                     COALESCE(excluded.last_seen_ms, 0));
END;

CREATE TRIGGER IF NOT EXISTS trg_league_memberships_platform_insert
AFTER INSERT ON league_memberships
BEGIN
  INSERT INTO platform_memberships
    (platform, league_key, manager_key, roster_id, last_seen_ms, metadata_json)
  VALUES ('sleeper', 'sleeper:' || NEW.league_id,
          'sleeper:' || NEW.user_id, NEW.roster_id, NEW.last_seen_ms, '{}')
  ON CONFLICT(league_key, manager_key) DO UPDATE SET
    roster_id=COALESCE(excluded.roster_id, platform_memberships.roster_id),
    last_seen_ms=MAX(COALESCE(platform_memberships.last_seen_ms, 0),
                     COALESCE(excluded.last_seen_ms, 0));
END;

CREATE TRIGGER IF NOT EXISTS trg_league_memberships_platform_update
AFTER UPDATE ON league_memberships
BEGIN
  INSERT INTO platform_memberships
    (platform, league_key, manager_key, roster_id, last_seen_ms, metadata_json)
  VALUES ('sleeper', 'sleeper:' || NEW.league_id,
          'sleeper:' || NEW.user_id, NEW.roster_id, NEW.last_seen_ms, '{}')
  ON CONFLICT(league_key, manager_key) DO UPDATE SET
    roster_id=COALESCE(excluded.roster_id, platform_memberships.roster_id),
    last_seen_ms=MAX(COALESCE(platform_memberships.last_seen_ms, 0),
                     COALESCE(excluded.last_seen_ms, 0));
END;

CREATE TRIGGER IF NOT EXISTS trg_leagues_platform_insert
AFTER INSERT ON leagues
BEGIN
  INSERT INTO platform_leagues
    (league_key, platform, source_league_id, season,
     previous_source_league_id, name, total_rosters, format_type,
     is_dynasty, sharp_eligible, first_seen_ms, last_crawled_ms, metadata_json)
  VALUES ('sleeper:' || NEW.league_id, 'sleeper', NEW.league_id,
          NEW.season, NEW.previous_league_id, NEW.name, NEW.total_rosters,
          'sleeper',
          CASE WHEN json_valid(COALESCE(NEW.settings_json, '{}'))
               THEN CAST(json_extract(NEW.settings_json, '$.signalEligible') AS INTEGER)
               ELSE NULL END,
          CASE WHEN json_valid(COALESCE(NEW.settings_json, '{}'))
               THEN COALESCE(CAST(json_extract(NEW.settings_json, '$.sharpEligible')
                                  AS INTEGER), 0)
               ELSE 0 END,
          NEW.first_seen_ms, NEW.last_crawled_ms,
          COALESCE(NEW.settings_json, '{}'))
  ON CONFLICT(league_key) DO UPDATE SET
    season=COALESCE(excluded.season, platform_leagues.season),
    previous_source_league_id=COALESCE(
      excluded.previous_source_league_id,
      platform_leagues.previous_source_league_id
    ),
    name=COALESCE(excluded.name, platform_leagues.name),
    total_rosters=COALESCE(
      excluded.total_rosters,
      platform_leagues.total_rosters
    ),
    is_dynasty=COALESCE(excluded.is_dynasty, platform_leagues.is_dynasty),
    sharp_eligible=excluded.sharp_eligible,
    last_crawled_ms=MAX(
      COALESCE(platform_leagues.last_crawled_ms, 0),
      COALESCE(excluded.last_crawled_ms, 0)
    ),
    metadata_json=excluded.metadata_json;
END;

CREATE TRIGGER IF NOT EXISTS trg_leagues_platform_update
AFTER UPDATE ON leagues
BEGIN
  INSERT INTO platform_leagues
    (league_key, platform, source_league_id, season,
     previous_source_league_id, name, total_rosters, format_type,
     is_dynasty, sharp_eligible, first_seen_ms, last_crawled_ms, metadata_json)
  VALUES ('sleeper:' || NEW.league_id, 'sleeper', NEW.league_id,
          NEW.season, NEW.previous_league_id, NEW.name, NEW.total_rosters,
          'sleeper',
          CASE WHEN json_valid(COALESCE(NEW.settings_json, '{}'))
               THEN CAST(json_extract(NEW.settings_json, '$.signalEligible') AS INTEGER)
               ELSE NULL END,
          CASE WHEN json_valid(COALESCE(NEW.settings_json, '{}'))
               THEN COALESCE(CAST(json_extract(NEW.settings_json, '$.sharpEligible')
                                  AS INTEGER), 0)
               ELSE 0 END,
          NEW.first_seen_ms, NEW.last_crawled_ms,
          COALESCE(NEW.settings_json, '{}'))
  ON CONFLICT(league_key) DO UPDATE SET
    season=COALESCE(excluded.season, platform_leagues.season),
    previous_source_league_id=COALESCE(
      excluded.previous_source_league_id,
      platform_leagues.previous_source_league_id
    ),
    name=COALESCE(excluded.name, platform_leagues.name),
    total_rosters=COALESCE(
      excluded.total_rosters,
      platform_leagues.total_rosters
    ),
    is_dynasty=COALESCE(excluded.is_dynasty, platform_leagues.is_dynasty),
    sharp_eligible=excluded.sharp_eligible,
    last_crawled_ms=MAX(
      COALESCE(platform_leagues.last_crawled_ms, 0),
      COALESCE(excluded.last_crawled_ms, 0)
    ),
    metadata_json=excluded.metadata_json;
END;
"""


@dataclass(frozen=True)
class PlatformIngestResult:
    transactions_seen: int = 0
    transactions_inserted: int = 0
    movements_seen: int = 0
    movements_inserted: int = 0
    managers_upserted: int = 0
    leagues_upserted: int = 0
    memberships_upserted: int = 0
    manager_seasons_upserted: int = 0
    unmapped_movements: int = 0

    @property
    def movements_skipped(self) -> int:
        return max(0, self.movements_seen - self.movements_inserted)

    def to_dict(self) -> dict[str, int]:
        return {
            **asdict(self),
            "movements_skipped": self.movements_skipped,
        }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_columns(conn: sqlite3.Connection) -> None:
    existing_tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for table, columns in _ADDITIVE_COLUMNS.items():
        if table not in existing_tables:
            continue
        existing = _columns(conn, table)
        for name, type_sql in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {type_sql}")


def _backfill_sleeper(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE transactions
           SET platform=COALESCE(platform, 'sleeper'),
               source_transaction_id=COALESCE(source_transaction_id, tx_id),
               transaction_key=COALESCE(transaction_key, 'sleeper:' || tx_id),
               league_key=COALESCE(league_key, 'sleeper:' || league_id)
        """
    )
    conn.execute(
        """
        UPDATE asset_movements
           SET platform=COALESCE(platform, 'sleeper'),
               movement_key=COALESCE(movement_key, 'sleeper:' || movement_id),
               transaction_key=COALESCE(transaction_key, 'sleeper:' || tx_id),
               league_key=COALESCE(league_key, 'sleeper:' || league_id),
               canonical_asset_id=COALESCE(canonical_asset_id, asset_id),
               source_asset_id=COALESCE(source_asset_id, asset_id),
               manager_key=COALESCE(manager_key, 'sleeper:' || user_id),
               counterparty_manager_key=COALESCE(
                 counterparty_manager_key,
                 CASE WHEN counterparty_user_id IS NULL OR counterparty_user_id=''
                      THEN NULL ELSE 'sleeper:' || counterparty_user_id END
               ),
               timestamp_ms=COALESCE(timestamp_ms, ts)
        """
    )
    conn.execute(
        """
        UPDATE manager_seasons
           SET platform=COALESCE(platform, 'sleeper'),
               league_key=COALESCE(league_key, 'sleeper:' || league_id),
               manager_key=COALESCE(manager_key, 'sleeper:' || user_id),
               source_identity_type=COALESCE(source_identity_type, 'global_verified'),
               evidence_status=COALESCE(
                 evidence_status,
                 CASE WHEN is_complete=1 AND sharp_eligible=1
                      THEN 'automated_evidence' ELSE 'insufficient_history' END
               )
        """
    )


def _sync_legacy_entities(conn: sqlite3.Connection) -> None:
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO platform_managers
          (manager_key, platform, source_manager_id, username, display_name,
           source_identity_type, identity_scope, identity_confidence,
           first_seen_ms, last_seen_ms, metadata_json)
        SELECT 'sleeper:' || user_id, 'sleeper', user_id, current_username,
               display_name, 'global_verified', 'platform', 1.0,
               COALESCE(first_seen_ms, ?), COALESCE(last_seen_ms, ?), '{}'
          FROM sleeper_users
         WHERE 1=1
        ON CONFLICT(manager_key) DO UPDATE SET
          username=COALESCE(excluded.username, platform_managers.username),
          display_name=COALESCE(excluded.display_name, platform_managers.display_name),
          last_seen_ms=MAX(platform_managers.last_seen_ms, excluded.last_seen_ms)
        """,
        (now, now),
    )
    # Managers can exist in movement/season rows before sleeper_users is hydrated.
    conn.execute(
        """
        INSERT OR IGNORE INTO platform_managers
          (manager_key, platform, source_manager_id, source_identity_type,
           identity_scope, identity_confidence, first_seen_ms, last_seen_ms, metadata_json)
        SELECT DISTINCT 'sleeper:' || user_id, 'sleeper', user_id,
               'global_verified', 'platform', 1.0, ?, ?, '{}'
          FROM asset_movements
         WHERE user_id IS NOT NULL AND user_id <> ''
           AND COALESCE(platform, 'sleeper')='sleeper'
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO platform_managers
          (manager_key, platform, source_manager_id, source_identity_type,
           identity_scope, identity_confidence, first_seen_ms, last_seen_ms, metadata_json)
        SELECT DISTINCT 'sleeper:' || user_id, 'sleeper', user_id,
               'global_verified', 'platform', 1.0, ?, ?, '{}'
          FROM manager_seasons
         WHERE user_id IS NOT NULL AND user_id <> ''
           AND COALESCE(platform, 'sleeper')='sleeper'
        """,
        (now, now),
    )
    _sync_legacy_leagues(conn)
    conn.execute(
        """
        INSERT OR IGNORE INTO platform_leagues
          (league_key, platform, source_league_id, season, first_seen_ms,
           last_crawled_ms, metadata_json)
        SELECT 'sleeper:' || league_id, 'sleeper', league_id, season,
               MIN(created_ms), MAX(ingested_ms), '{}'
          FROM transactions
         WHERE league_id IS NOT NULL AND league_id <> ''
           AND COALESCE(platform, 'sleeper')='sleeper'
         GROUP BY league_id, season
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO platform_leagues
          (league_key, platform, source_league_id, season, first_seen_ms,
           last_crawled_ms, metadata_json)
        SELECT 'sleeper:' || league_id, 'sleeper', league_id, season,
               MIN(crawled_ms), MAX(crawled_ms), '{}'
          FROM manager_seasons
         WHERE league_id IS NOT NULL AND league_id <> ''
           AND COALESCE(platform, 'sleeper')='sleeper'
         GROUP BY league_id, season
        """
    )
    conn.execute(
        """
        INSERT INTO platform_memberships
          (platform, league_key, manager_key, roster_id, last_seen_ms, metadata_json)
        SELECT 'sleeper', 'sleeper:' || league_id, 'sleeper:' || user_id,
               roster_id, COALESCE(last_seen_ms, ?), '{}'
          FROM league_memberships
         WHERE 1=1
        ON CONFLICT(league_key, manager_key) DO UPDATE SET
          roster_id=COALESCE(excluded.roster_id, platform_memberships.roster_id),
          last_seen_ms=MAX(platform_memberships.last_seen_ms, excluded.last_seen_ms)
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO canonical_assets
          (canonical_asset_id, asset_type, first_seen_ms, last_seen_ms, metadata_json)
        SELECT DISTINCT asset_id, asset_type, ?, ?, '{}'
          FROM asset_movements
         WHERE asset_id IS NOT NULL AND asset_id <> ''
           AND COALESCE(platform, 'sleeper')='sleeper'
        """,
        (now, now),
    )
    conn.execute(
        """
        INSERT INTO asset_aliases
          (platform, source_asset_id, canonical_asset_id, source_name,
           normalized_name, match_method, match_confidence, manually_verified,
           metadata_json, first_seen_ms, last_seen_ms)
        SELECT 'sleeper', asset_id, asset_id, NULL, NULL,
               'authoritative_source_id', 1.0, 1, '{}', ?, ?
          FROM (SELECT DISTINCT asset_id FROM asset_movements
                 WHERE asset_id IS NOT NULL AND asset_id <> ''
                   AND COALESCE(platform, 'sleeper')='sleeper')
         WHERE 1=1
        ON CONFLICT(platform, source_asset_id) DO UPDATE SET
          canonical_asset_id=excluded.canonical_asset_id,
          match_method='authoritative_source_id',
          match_confidence=1.0,
          manually_verified=1,
          last_seen_ms=excluded.last_seen_ms
        """,
        (now, now),
    )


def _execute_script(conn: sqlite3.Connection, script: str) -> None:
    """Execute a semicolon-delimited SQLite script without implicit commits."""
    statement = ""
    for line in script.splitlines():
        statement += line + "\n"
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            statement = ""
            if sql:
                conn.execute(sql)
    if statement.strip():
        raise sqlite3.DatabaseError("incomplete platform schema statement")


def _sync_legacy_leagues(conn: sqlite3.Connection) -> None:
    now = _now_ms()
    rows = conn.execute(
        "SELECT league_id, season, previous_league_id, name, total_rosters, "
        "settings_json, first_seen_ms, last_crawled_ms FROM leagues"
    ).fetchall()
    for row in rows:
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, ValueError):
            settings = {}
        signal_eligible = settings.get("signalEligible")
        sharp_eligible = bool(settings.get("sharpEligible"))
        conn.execute(
            """
            INSERT INTO platform_leagues
              (league_key, platform, source_league_id, season, previous_source_league_id,
               name, total_rosters, format_type, is_dynasty, sharp_eligible,
               first_seen_ms, last_crawled_ms, metadata_json)
            VALUES (?, 'sleeper', ?, ?, ?, ?, ?, 'sleeper', ?, ?, ?, ?, ?)
            ON CONFLICT(league_key) DO UPDATE SET
              season=COALESCE(excluded.season, platform_leagues.season),
              name=COALESCE(excluded.name, platform_leagues.name),
              total_rosters=COALESCE(excluded.total_rosters, platform_leagues.total_rosters),
              is_dynasty=COALESCE(excluded.is_dynasty, platform_leagues.is_dynasty),
              sharp_eligible=excluded.sharp_eligible,
              last_crawled_ms=MAX(COALESCE(platform_leagues.last_crawled_ms, 0),
                                  COALESCE(excluded.last_crawled_ms, 0)),
              metadata_json=excluded.metadata_json
            """,
            (
                f"sleeper:{row['league_id']}",
                str(row["league_id"]),
                row["season"],
                row["previous_league_id"],
                row["name"],
                row["total_rosters"],
                None if signal_eligible is None else int(bool(signal_eligible)),
                int(sharp_eligible),
                row["first_seen_ms"] or now,
                row["last_crawled_ms"] or now,
                _json(settings),
            ),
        )


#: Indexes that must exist on EVERY platform ledger, including ones
#: already stamped at the current ``PLATFORM_SCHEMA_VERSION``.
#:
#: ``_platform_schema_ready`` checks columns, one table and the triggers —
#: never indexes — so a purely additive index added to ``_PLATFORM_SCHEMA``
#: reaches new ledgers and NO deployed one.  Bumping the schema version to
#: deliver it would re-run the whole platform migration (and its backup) on
#: every deployed ledger to add an index, which is the trade
#: ``src/sharp/roster_store.py`` already declined for its four additive
#: tables.  This pass is the same posture: additive DDL, applied on its own,
#: outside the version gate.
_REQUIRED_PLATFORM_INDEXES: tuple[str, ...] = (
    # V1-59.  ``register_asset_alias`` repairs previously-unmapped rows with
    # ``UPDATE asset_movements ... WHERE platform=? AND source_asset_id=?``.
    # With only ``idx_am_platform_ts`` available, SQLite planned that as
    # ``SEARCH ... USING INDEX idx_am_platform_ts (platform=?)`` — i.e. the
    # whole platform partition scanned, per call.
    #
    # ``hydrate_sleeper_asset_catalog`` makes one such call per player in
    # Sleeper's directory, so the catalog pass cost O(players x movements)
    # and grew every time the ledger ingested anything.  Measured on a
    # synthetic ledger: 1,500 players over 60,000 movements took 22.70 s
    # without this index and 0.15 s with it (151x), and the cost doubled
    # exactly with movement count (20k/40k/80k/160k -> 1.48/3.01/5.99/12.08 s),
    # which is the signature of a scan rather than a lookup.
    #
    # That runtime is the whole incident: the catalog pass is ONE
    # transaction, so a hydration that takes half an hour holds the ledger's
    # write lock for half an hour, and every other writer — including the
    # next service instance and ``record_ingestion_run`` — waits out its
    # ``busy_timeout`` and raises ``database is locked``.
    "CREATE INDEX IF NOT EXISTS idx_am_platform_source "
    "ON asset_movements(platform, source_asset_id)",
)


def ensure_platform_indexes(conn: sqlite3.Connection) -> None:
    """Create any missing required index.  Idempotent, and free when satisfied.

    Safe to call on every connection: measured, ``CREATE INDEX IF NOT
    EXISTS`` for an index that already exists takes **no write lock** and
    returns in ~0 ms even while another connection holds one, so this
    cannot become a new contention source in steady state.  Only the
    one-time creation needs the lock.

    A failure to create is deliberately NOT swallowed.  An index that
    silently failed to appear leaves the O(players x movements) scan in
    place with no signal — which is the condition this exists to end.
    """
    for statement in _REQUIRED_PLATFORM_INDEXES:
        conn.execute(statement)


def _platform_schema_ready(conn: sqlite3.Connection) -> bool:
    try:
        version = conn.execute(
            "SELECT value FROM meta WHERE key=?", (MIGRATION_META_KEY,)
        ).fetchone()
        if not version or int(version[0]) != PLATFORM_SCHEMA_VERSION:
            return False
        required_columns = {
            "transactions": {"platform", "transaction_key", "league_key"},
            "asset_movements": {
                "platform",
                "movement_key",
                "canonical_asset_id",
                "manager_key",
            },
            "manager_seasons": {"platform", "league_key", "manager_key"},
            "ingestion_runs": {
                "automated_ffpc_qualifiers",
                "curated_ffpc_contributors",
            },
        }
        if any(
            not columns.issubset(_columns(conn, table))
            for table, columns in required_columns.items()
        ):
            return False
        identity_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' " "AND name='manager_identity_links'"
        ).fetchone()
        if not identity_table:
            return False
        required_triggers = {
            "trg_transactions_sleeper_platform",
            "trg_movements_sleeper_platform",
            "trg_manager_seasons_sleeper_platform",
            "trg_sleeper_users_platform_insert",
            "trg_league_memberships_platform_insert",
            "trg_leagues_platform_insert",
            "trg_leagues_platform_update",
        }
        present = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            ).fetchall()
        }
        return required_triggers.issubset(present)
    except (sqlite3.DatabaseError, TypeError, ValueError):
        return False


def _database_path(conn: sqlite3.Connection) -> Path | None:
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except sqlite3.DatabaseError:
        return None
    for row in rows:
        if str(row[1]) == "main" and str(row[2] or "").strip():
            return Path(str(row[2]))
    return None


def _create_automatic_backup(conn: sqlite3.Connection) -> Path | None:
    """Create one WAL-safe pre-v2 backup for implicit migration paths."""
    target = _database_path(conn)
    if target is None or not target.exists() or target.stat().st_size == 0:
        return None
    backup_path = target.with_name(f"{target.name}.pre-platform-v2-auto.bak")
    if backup_path.exists():
        return backup_path
    destination = sqlite3.connect(str(backup_path), timeout=10.0)
    try:
        conn.backup(destination)
    finally:
        destination.close()
    return backup_path


def _legacy_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in ("transactions", "asset_movements", "manager_seasons")
    }


def _verify_migration_invariants(
    conn: sqlite3.Connection,
    before: dict[str, int],
) -> None:
    after = _legacy_row_counts(conn)
    if before != after:
        raise RuntimeError(
            f"platform migration changed legacy row counts: before={before} after={after}"
        )
    missing = int(
        conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM transactions
                WHERE platform IS NULL OR transaction_key IS NULL
                   OR league_key IS NULL)
              +
              (SELECT COUNT(*) FROM asset_movements
                WHERE platform IS NULL OR movement_key IS NULL
                   OR transaction_key IS NULL OR league_key IS NULL
                   OR manager_key IS NULL)
              +
              (SELECT COUNT(*) FROM manager_seasons
                WHERE platform IS NULL OR league_key IS NULL
                   OR manager_key IS NULL)
            """
        ).fetchone()[0]
    )
    if missing:
        raise RuntimeError(f"platform migration left {missing} unscoped legacy rows")
    transaction_orphans = int(
        conn.execute(
            """
            SELECT COUNT(*)
              FROM asset_movements m
              LEFT JOIN transactions t
                ON t.transaction_key=m.transaction_key
             WHERE t.transaction_key IS NULL
            """
        ).fetchone()[0]
    )
    if transaction_orphans:
        raise RuntimeError(
            "platform migration found " f"{transaction_orphans} movement/transaction orphan(s)"
        )


def ensure_platform_schema(
    path: Path | None = None,
    *,
    conn: sqlite3.Connection | None = None,
) -> sqlite3.Connection:
    """Apply the additive platform migration and return an open connection.

    When ``conn`` is supplied, ownership stays with the caller.  Otherwise
    the returned connection must be closed by the caller.
    """
    own = conn is None
    connection = conn or ledger.connect(path)
    if _platform_schema_ready(connection):
        # Additive indexes live outside the version gate — see
        # ``_REQUIRED_PLATFORM_INDEXES``.  A ledger can be fully migrated
        # and still be missing one, which is exactly the V1-59 state.
        #
        # Skipped mid-transaction for the same reason the automatic backup
        # below is: this may be a caller's connection, and committing here
        # would end a transaction we do not own.  Every path that can
        # actually create the index (the collectors, which open their own
        # connection) reaches it on a fresh one.
        if not connection.in_transaction:
            ensure_platform_indexes(connection)
            connection.commit()
        return connection
    before = _legacy_row_counts(connection)
    # The explicit migration command creates a timestamped backup. This
    # fixed-name backup protects implicit first-use migrations as well, so
    # an API request or collector can never upgrade production silently
    # without a recoverable pre-v2 copy.
    if not connection.in_transaction:
        _create_automatic_backup(connection)
    try:
        if not connection.in_transaction:
            connection.execute("BEGIN IMMEDIATE")
        _add_columns(connection)
        _execute_script(connection, _PLATFORM_SCHEMA)
        _backfill_sleeper(connection)
        _sync_legacy_entities(connection)
        _execute_script(connection, _TRIGGER_SCHEMA)
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (MIGRATION_META_KEY, str(PLATFORM_SCHEMA_VERSION)),
        )
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            ("platform_schema_migrated_ms", str(_now_ms())),
        )
        _verify_migration_invariants(connection, before)
        connection.commit()
    except Exception:
        connection.rollback()
        if own:
            connection.close()
        raise
    return connection


def migration_report(path: Path | None = None) -> dict[str, Any]:
    conn = ensure_platform_schema(path)
    try:
        counts = {}
        for table in (
            "transactions",
            "asset_movements",
            "manager_seasons",
            "platform_managers",
            "manager_identity_links",
            "platform_leagues",
            "platform_memberships",
            "asset_aliases",
        ):
            counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        missing = {
            "transactions": int(
                conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE platform IS NULL OR transaction_key IS NULL"
                ).fetchone()[0]
            ),
            "movements": int(
                conn.execute(
                    "SELECT COUNT(*) FROM asset_movements "
                    "WHERE platform IS NULL OR movement_key IS NULL OR manager_key IS NULL"
                ).fetchone()[0]
            ),
            "managerSeasons": int(
                conn.execute(
                    "SELECT COUNT(*) FROM manager_seasons "
                    "WHERE platform IS NULL OR manager_key IS NULL OR league_key IS NULL"
                ).fetchone()[0]
            ),
        }
        orphans = {
            "movementTransactions": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM asset_movements m
                     LEFT JOIN transactions t
                       ON t.transaction_key=m.transaction_key
                    WHERE t.transaction_key IS NULL
                    """
                ).fetchone()[0]
            ),
            "movementManagers": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM asset_movements m
                     LEFT JOIN platform_managers pm
                       ON pm.manager_key=m.manager_key
                    WHERE m.manager_key IS NOT NULL
                      AND pm.manager_key IS NULL
                    """
                ).fetchone()[0]
            ),
            "movementLeagues": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM asset_movements m
                     LEFT JOIN platform_leagues pl
                       ON pl.league_key=m.league_key
                    WHERE m.league_key IS NOT NULL
                      AND pl.league_key IS NULL
                    """
                ).fetchone()[0]
            ),
            "seasonManagers": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM manager_seasons ms
                     LEFT JOIN platform_managers pm
                       ON pm.manager_key=ms.manager_key
                    WHERE ms.manager_key IS NOT NULL
                      AND pm.manager_key IS NULL
                    """
                ).fetchone()[0]
            ),
            "seasonLeagues": int(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM manager_seasons ms
                     LEFT JOIN platform_leagues pl
                       ON pl.league_key=ms.league_key
                    WHERE ms.league_key IS NOT NULL
                      AND pl.league_key IS NULL
                    """
                ).fetchone()[0]
            ),
        }
        version = conn.execute(
            "SELECT value FROM meta WHERE key=?", (MIGRATION_META_KEY,)
        ).fetchone()
        db_path = _database_path(conn)
        automatic_backup = (
            db_path.with_name(f"{db_path.name}.pre-platform-v2-auto.bak")
            if db_path is not None
            else None
        )
        return {
            "schemaVersion": int(version[0]) if version else None,
            "automaticBackupPath": (
                str(automatic_backup)
                if automatic_backup is not None and automatic_backup.exists()
                else None
            ),
            "counts": counts,
            "missingPlatformKeys": missing,
            "orphans": orphans,
            "ok": not any(missing.values()) and not any(orphans.values()),
        }
    finally:
        conn.close()


def backup_and_migrate(path: Path | None = None, *, backup: bool = True) -> dict[str, Any]:
    target = Path(path) if path else ledger.default_path()
    backup_path: Path | None = None
    before = {}
    if target.exists():
        raw = sqlite3.connect(str(target))
        try:
            for table in ("transactions", "asset_movements", "manager_seasons"):
                try:
                    before[table] = int(raw.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                except sqlite3.DatabaseError:
                    before[table] = 0
        finally:
            raw.close()
        if backup:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            backup_path = target.with_name(f"{target.name}.pre-platform-v2-{stamp}.bak")
            # Use SQLite's online backup API rather than copying the main
            # file: the production ledger runs in WAL mode, so a raw file
            # copy can omit committed rows still resident in ``-wal``.
            source = sqlite3.connect(str(target), timeout=10.0)
            destination = sqlite3.connect(str(backup_path), timeout=10.0)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
    report = migration_report(target)
    after = {k: report["counts"].get(k, 0) for k in before}
    preserved = all(before[k] == after.get(k) for k in before)
    return {
        "path": str(target),
        "backupPath": str(backup_path) if backup_path else None,
        "before": before,
        "after": after,
        "rowCountsPreserved": preserved,
        **report,
    }


def _legacy_ids(platform: str, source_id: str, scoped: str) -> str:
    return source_id if platform == "sleeper" else scoped


def link_manager_identity(
    *,
    manager_key: str,
    canonical_manager_id: str,
    link_method: str,
    confidence: float,
    verified: bool,
    metadata: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> None:
    """Create an explicit cross-platform identity link.

    Name/display similarity is never accepted here. Callers must supply a
    verified external assertion or a manually reviewed link record.
    """
    manager_key = str(manager_key or "").strip()
    canonical_manager_id = str(canonical_manager_id or "").strip()
    link_method = str(link_method or "").strip()
    if not manager_key or not canonical_manager_id or not link_method:
        raise ValueError("manager_key, canonical_manager_id and link_method are required")
    confidence = max(0.0, min(1.0, float(confidence)))
    if not verified:
        raise ValueError("cross-platform manager links must be explicitly verified")
    exists = conn.execute(
        "SELECT 1 FROM platform_managers WHERE manager_key=?",
        (manager_key,),
    ).fetchone()
    if not exists:
        raise ValueError(f"unknown platform manager: {manager_key}")
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO manager_identity_links
          (manager_key, canonical_manager_id, link_method, link_confidence,
           verified, created_ms, metadata_json)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(manager_key) DO UPDATE SET
          canonical_manager_id=excluded.canonical_manager_id,
          link_method=excluded.link_method,
          link_confidence=excluded.link_confidence,
          verified=1,
          created_ms=excluded.created_ms,
          metadata_json=excluded.metadata_json
        """,
        (
            manager_key,
            canonical_manager_id,
            link_method,
            confidence,
            now,
            _json(metadata),
        ),
    )
    conn.execute(
        "UPDATE platform_managers SET canonical_manager_id=? WHERE manager_key=?",
        (canonical_manager_id, manager_key),
    )


def upsert_manager(manager: NormalizedManager, *, conn: sqlite3.Connection) -> None:
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO platform_managers
          (manager_key, platform, source_manager_id, username, display_name,
           source_identity_type, identity_scope, identity_confidence,
           canonical_manager_id, first_seen_ms, last_seen_ms, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(manager_key) DO UPDATE SET
          username=COALESCE(excluded.username, platform_managers.username),
          display_name=COALESCE(excluded.display_name, platform_managers.display_name),
          source_identity_type=excluded.source_identity_type,
          identity_scope=excluded.identity_scope,
          identity_confidence=excluded.identity_confidence,
          canonical_manager_id=COALESCE(excluded.canonical_manager_id,
                                        platform_managers.canonical_manager_id),
          last_seen_ms=excluded.last_seen_ms,
          metadata_json=excluded.metadata_json
        """,
        (
            manager.manager_key,
            manager.platform,
            manager.source_manager_id,
            manager.username,
            manager.display_name,
            manager.source_identity_type,
            manager.identity_scope,
            float(manager.identity_confidence),
            manager.canonical_manager_id,
            now,
            now,
            _json(manager.metadata),
        ),
    )


def upsert_league(item: NormalizedLeague, *, conn: sqlite3.Connection) -> None:
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO platform_leagues
          (league_key, platform, source_league_id, season, previous_source_league_id,
           name, total_rosters, format_type, is_dynasty, sharp_eligible,
           first_seen_ms, last_crawled_ms, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(league_key) DO UPDATE SET
          season=COALESCE(excluded.season, platform_leagues.season),
          previous_source_league_id=COALESCE(
            excluded.previous_source_league_id,
            platform_leagues.previous_source_league_id
          ),
          name=COALESCE(excluded.name, platform_leagues.name),
          total_rosters=COALESCE(excluded.total_rosters, platform_leagues.total_rosters),
          format_type=COALESCE(excluded.format_type, platform_leagues.format_type),
          is_dynasty=COALESCE(excluded.is_dynasty, platform_leagues.is_dynasty),
          sharp_eligible=excluded.sharp_eligible,
          last_crawled_ms=excluded.last_crawled_ms,
          metadata_json=excluded.metadata_json
        """,
        (
            item.league_key,
            item.platform,
            item.source_league_id,
            item.season,
            item.previous_source_league_id,
            item.name,
            item.total_rosters,
            item.format_type,
            None if item.is_dynasty is None else int(item.is_dynasty),
            int(item.sharp_eligible),
            now,
            now,
            _json(item.metadata),
        ),
    )


def upsert_membership(item: NormalizedMembership, *, conn: sqlite3.Connection) -> None:
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO platform_memberships
          (platform, league_key, manager_key, source_team_id, roster_id,
           team_name, last_seen_ms, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(league_key, manager_key) DO UPDATE SET
          source_team_id=COALESCE(excluded.source_team_id,
                                  platform_memberships.source_team_id),
          roster_id=COALESCE(excluded.roster_id, platform_memberships.roster_id),
          team_name=COALESCE(excluded.team_name, platform_memberships.team_name),
          last_seen_ms=excluded.last_seen_ms,
          metadata_json=excluded.metadata_json
        """,
        (
            item.platform,
            item.league_key,
            item.manager_key,
            item.source_team_id,
            item.roster_id,
            item.team_name,
            now,
            _json(item.metadata),
        ),
    )


def register_asset_alias(
    *,
    platform: str,
    source_asset_id: str,
    canonical_asset_id: str | None,
    source_name: str | None = None,
    normalized_name: str | None = None,
    nfl_team: str | None = None,
    position: str | None = None,
    asset_type: str = "player",
    match_method: str = "manual",
    match_confidence: float = 1.0,
    manually_verified: bool = False,
    metadata: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> None:
    now = _now_ms()
    if canonical_asset_id:
        conn.execute(
            """
            INSERT INTO canonical_assets
              (canonical_asset_id, display_name, normalized_name, asset_type,
               nfl_team, position, metadata_json, first_seen_ms, last_seen_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(canonical_asset_id) DO UPDATE SET
              display_name=COALESCE(excluded.display_name, canonical_assets.display_name),
              normalized_name=COALESCE(excluded.normalized_name,
                                       canonical_assets.normalized_name),
              nfl_team=COALESCE(excluded.nfl_team, canonical_assets.nfl_team),
              position=COALESCE(excluded.position, canonical_assets.position),
              last_seen_ms=excluded.last_seen_ms
            """,
            (
                canonical_asset_id,
                source_name,
                normalized_name,
                asset_type,
                nfl_team,
                position,
                _json(metadata),
                now,
                now,
            ),
        )
    conn.execute(
        """
        INSERT INTO asset_aliases
          (platform, source_asset_id, canonical_asset_id, source_name,
           normalized_name, nfl_team, position, match_method, match_confidence,
           manually_verified, metadata_json, first_seen_ms, last_seen_ms)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, source_asset_id) DO UPDATE SET
          canonical_asset_id=COALESCE(excluded.canonical_asset_id,
                                      asset_aliases.canonical_asset_id),
          source_name=COALESCE(excluded.source_name, asset_aliases.source_name),
          normalized_name=COALESCE(excluded.normalized_name, asset_aliases.normalized_name),
          nfl_team=COALESCE(excluded.nfl_team, asset_aliases.nfl_team),
          position=COALESCE(excluded.position, asset_aliases.position),
          match_method=excluded.match_method,
          match_confidence=excluded.match_confidence,
          manually_verified=MAX(asset_aliases.manually_verified,
                                excluded.manually_verified),
          metadata_json=excluded.metadata_json,
          last_seen_ms=excluded.last_seen_ms
        """,
        (
            platform,
            source_asset_id,
            canonical_asset_id,
            source_name,
            normalized_name,
            nfl_team,
            position,
            match_method,
            float(match_confidence),
            int(manually_verified),
            _json(metadata),
            now,
            now,
        ),
    )
    if canonical_asset_id:
        # A source asset may have been ingested before a safe mapping was
        # available. Resolving the alias should repair those existing raw
        # rows rather than requiring their deterministic movement ids to
        # change or silently leaving them outside combined totals.
        if manually_verified:
            conn.execute(
                """
                UPDATE asset_movements
                   SET canonical_asset_id=?, asset_id=?
                 WHERE platform=? AND source_asset_id=?
                """,
                (
                    canonical_asset_id,
                    canonical_asset_id,
                    platform,
                    source_asset_id,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE asset_movements
                   SET canonical_asset_id=?, asset_id=?
                 WHERE platform=? AND source_asset_id=?
                   AND canonical_asset_id IS NULL
                """,
                (
                    canonical_asset_id,
                    canonical_asset_id,
                    platform,
                    source_asset_id,
                ),
            )
        conn.execute(
            "DELETE FROM unmapped_assets WHERE platform=? AND source_asset_id=?",
            (platform, source_asset_id),
        )


def record_unmapped_asset(
    *,
    platform: str,
    source_asset_id: str,
    source_name: str | None,
    normalized_name: str | None,
    nfl_team: str | None,
    position: str | None,
    reason: str,
    candidates: Sequence[str] = (),
    metadata: dict[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> None:
    now = _now_ms()
    conn.execute(
        """
        INSERT INTO unmapped_assets
          (platform, source_asset_id, source_name, normalized_name, nfl_team,
           position, reason, candidates_json, first_seen_ms, last_seen_ms,
           occurrences, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        ON CONFLICT(platform, source_asset_id) DO UPDATE SET
          source_name=COALESCE(excluded.source_name, unmapped_assets.source_name),
          normalized_name=COALESCE(excluded.normalized_name,
                                   unmapped_assets.normalized_name),
          nfl_team=COALESCE(excluded.nfl_team, unmapped_assets.nfl_team),
          position=COALESCE(excluded.position, unmapped_assets.position),
          reason=excluded.reason,
          candidates_json=excluded.candidates_json,
          last_seen_ms=excluded.last_seen_ms,
          occurrences=unmapped_assets.occurrences + 1,
          metadata_json=excluded.metadata_json
        """,
        (
            platform,
            source_asset_id,
            source_name,
            normalized_name,
            nfl_team,
            position,
            reason,
            _json(list(candidates)),
            now,
            now,
            _json(metadata),
        ),
    )


def _insert_transaction(item: NormalizedTransaction, conn: sqlite3.Connection) -> bool:
    now = _now_ms()
    legacy_tx_id = _legacy_ids(item.platform, item.source_transaction_id, item.transaction_key)
    source_league_id = (
        item.league_key.split(":", 1)[1] if ":" in item.league_key else item.league_key
    )
    legacy_league_id = _legacy_ids(item.platform, source_league_id, item.league_key)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO transactions
          (tx_id, league_id, season, week, tx_type, status, created_ms,
           ingested_ms, platform, transaction_key, source_transaction_id,
           league_key, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            legacy_tx_id,
            legacy_league_id,
            item.season,
            item.week,
            item.transaction_type,
            item.status,
            item.created_ms,
            now,
            item.platform,
            item.transaction_key,
            item.source_transaction_id,
            item.league_key,
            _json({**item.metadata, "sourceUrl": item.source_url}),
        ),
    )
    return bool(cur.rowcount and cur.rowcount > 0)


def _insert_movement(item: NormalizedMovement, conn: sqlite3.Connection) -> bool:
    now = _now_ms()
    source_tx_id = (
        item.transaction_key.split(":", 1)[1]
        if ":" in item.transaction_key
        else item.transaction_key
    )
    legacy_tx_id = _legacy_ids(item.platform, source_tx_id, item.transaction_key)
    source_league_id = (
        item.league_key.split(":", 1)[1] if ":" in item.league_key else item.league_key
    )
    legacy_league_id = _legacy_ids(item.platform, source_league_id, item.league_key)
    source_manager_id = (
        item.manager_key.split(":", 1)[1] if ":" in item.manager_key else item.manager_key
    )
    legacy_user_id = _legacy_ids(item.platform, source_manager_id, item.manager_key)
    legacy_counterparty = None
    if item.counterparty_manager_key:
        cp_source = item.counterparty_manager_key.split(":", 1)[-1]
        legacy_counterparty = _legacy_ids(item.platform, cp_source, item.counterparty_manager_key)
    legacy_movement_id = _legacy_ids(item.platform, item.source_movement_id, item.movement_key)
    fallback_asset = item.canonical_asset_id or f"unmapped:{item.platform}:{item.source_asset_id}"
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO asset_movements
          (movement_id, tx_id, league_id, tx_type, asset_id, asset_type,
           action, user_id, roster_id, counterparty_user_id, ts, week,
           faab_bid, ingested_ms, platform, movement_key, transaction_key,
           league_key, canonical_asset_id, source_asset_id, manager_key,
           counterparty_manager_key, timestamp_ms, metadata_json)
        SELECT ?, ?, ?, t.tx_type, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
               ?, ?, ?, ?, ?, ?
          FROM transactions t
         WHERE t.tx_id=?
        """,
        (
            legacy_movement_id,
            legacy_tx_id,
            legacy_league_id,
            fallback_asset,
            item.asset_type,
            item.action,
            legacy_user_id,
            item.roster_id,
            legacy_counterparty,
            item.timestamp_ms,
            item.week,
            item.faab_bid,
            now,
            item.platform,
            item.movement_key,
            item.transaction_key,
            item.league_key,
            item.canonical_asset_id,
            item.source_asset_id,
            item.manager_key,
            item.counterparty_manager_key,
            item.timestamp_ms,
            _json(
                {
                    **item.metadata,
                    "sourceUrl": item.source_url,
                    "sourceName": item.source_name,
                }
            ),
            legacy_tx_id,
        ),
    )
    return bool(cur.rowcount and cur.rowcount > 0)


def upsert_manager_season(item: NormalizedManagerSeason, *, conn: sqlite3.Connection) -> None:
    source_league_id = item.league_key.split(":", 1)[-1]
    legacy_league_id = _legacy_ids(item.platform, source_league_id, item.league_key)
    source_manager_id = item.manager_key.split(":", 1)[-1]
    legacy_user_id = _legacy_ids(item.platform, source_manager_id, item.manager_key)
    conn.execute(
        """
        INSERT INTO manager_seasons
          (league_id, season, user_id, roster_id, wins, losses, ties,
           points_for, points_against, made_playoffs, is_champion,
           is_runner_up, finish_rank, team_count, is_complete,
           sharp_eligible, crawled_ms, platform, league_key, manager_key,
           source_identity_type, evidence_status, exclusion_reasons_json,
           metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?)
        ON CONFLICT(league_id, season, user_id) DO UPDATE SET
          roster_id=excluded.roster_id,
          wins=excluded.wins, losses=excluded.losses, ties=excluded.ties,
          points_for=excluded.points_for, points_against=excluded.points_against,
          made_playoffs=excluded.made_playoffs,
          is_champion=excluded.is_champion,
          is_runner_up=excluded.is_runner_up,
          finish_rank=excluded.finish_rank,
          team_count=excluded.team_count,
          is_complete=excluded.is_complete,
          sharp_eligible=excluded.sharp_eligible,
          crawled_ms=excluded.crawled_ms,
          platform=excluded.platform,
          league_key=excluded.league_key,
          manager_key=excluded.manager_key,
          source_identity_type=excluded.source_identity_type,
          evidence_status=excluded.evidence_status,
          exclusion_reasons_json=excluded.exclusion_reasons_json,
          metadata_json=excluded.metadata_json
        """,
        (
            legacy_league_id,
            item.season,
            legacy_user_id,
            item.roster_id,
            item.wins,
            item.losses,
            item.ties,
            item.points_for,
            item.points_against,
            None if item.made_playoffs is None else int(item.made_playoffs),
            None if item.is_champion is None else int(item.is_champion),
            None if item.is_runner_up is None else int(item.is_runner_up),
            item.finish_rank,
            item.team_count,
            int(item.is_complete),
            int(item.sharp_eligible),
            _now_ms(),
            item.platform,
            item.league_key,
            item.manager_key,
            item.source_identity_type,
            item.evidence_status,
            _json(list(item.exclusion_reasons)),
            _json(item.metadata),
        ),
    )


def ingest_batch(
    batch: NormalizedBatch,
    *,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> PlatformIngestResult:
    own = conn is None
    connection = ensure_platform_schema(path, conn=conn)
    tx_inserted = 0
    mv_inserted = 0
    unmapped = 0
    try:
        for item in batch.managers:
            upsert_manager(item, conn=connection)
        for item in batch.leagues:
            upsert_league(item, conn=connection)
        for item in batch.memberships:
            upsert_membership(item, conn=connection)
        for item in batch.transactions:
            tx_inserted += int(_insert_transaction(item, connection))
        for item in batch.movements:
            mv_inserted += int(_insert_movement(item, connection))
            if item.canonical_asset_id:
                register_asset_alias(
                    platform=item.platform,
                    source_asset_id=item.source_asset_id,
                    canonical_asset_id=item.canonical_asset_id,
                    source_name=item.source_name,
                    normalized_name=(item.metadata or {}).get("normalizedName"),
                    nfl_team=(item.metadata or {}).get("nflTeam"),
                    position=(item.metadata or {}).get("position"),
                    asset_type=item.asset_type,
                    match_method=(item.metadata or {}).get("matchMethod", "adapter"),
                    match_confidence=float((item.metadata or {}).get("matchConfidence", 1.0)),
                    manually_verified=bool((item.metadata or {}).get("manuallyVerified", False)),
                    metadata=item.metadata,
                    conn=connection,
                )
            else:
                unmapped += 1
                record_unmapped_asset(
                    platform=item.platform,
                    source_asset_id=item.source_asset_id,
                    source_name=item.source_name,
                    normalized_name=(item.metadata or {}).get("normalizedName"),
                    nfl_team=(item.metadata or {}).get("nflTeam"),
                    position=(item.metadata or {}).get("position"),
                    reason=(item.metadata or {}).get("mappingReason", "unmapped"),
                    candidates=(item.metadata or {}).get("mappingCandidates", ()),
                    metadata=item.metadata,
                    conn=connection,
                )
        for item in batch.manager_seasons:
            upsert_manager_season(item, conn=connection)
        connection.commit()
        return PlatformIngestResult(
            transactions_seen=len(batch.transactions),
            transactions_inserted=tx_inserted,
            movements_seen=len(batch.movements),
            movements_inserted=mv_inserted,
            managers_upserted=len(batch.managers),
            leagues_upserted=len(batch.leagues),
            memberships_upserted=len(batch.memberships),
            manager_seasons_upserted=len(batch.manager_seasons),
            unmapped_movements=unmapped,
        )
    except Exception:
        connection.rollback()
        raise
    finally:
        if own:
            connection.close()


def query_movements(
    *,
    manager_keys: Sequence[str],
    since_ms: int | None,
    until_ms: int | None,
    platforms: Sequence[str] | None = None,
    asset_type: str | None = None,
    canonical_only: bool = True,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """``conn`` lets a caller that already holds a connection to this same
    ledger (e.g. ``roster_percentage.build_board()``, which already opens
    one for ``roster_store``) reuse it instead of paying for another
    ``ensure_platform_schema`` round trip. Ownership stays with the
    caller when supplied — mirrors ``ensure_platform_schema``'s own
    ``own = conn is None`` pattern.
    """
    if not manager_keys:
        return []
    own = conn is None
    connection = conn if conn is not None else ensure_platform_schema(path)
    clauses = [
        f"m.manager_key IN ({','.join('?' for _ in manager_keys)})",
        "m.tx_type='trade'",
    ]
    params: list[Any] = list(manager_keys)
    if since_ms is not None:
        clauses.append("m.ts >= ?")
        params.append(int(since_ms))
    if until_ms is not None:
        clauses.append("m.ts <= ?")
        params.append(int(until_ms))
    if platforms:
        clauses.append(f"m.platform IN ({','.join('?' for _ in platforms)})")
        params.extend(platforms)
    if asset_type and asset_type != "all":
        clauses.append("m.asset_type=?")
        params.append(asset_type)
    if canonical_only:
        clauses.append("m.canonical_asset_id IS NOT NULL")
    sql = f"""
        SELECT m.platform, m.movement_key, m.transaction_key, m.league_key,
               m.canonical_asset_id, m.source_asset_id, m.asset_type,
               m.action, m.manager_key, m.counterparty_manager_key,
               m.ts AS timestamp_ms, m.week, m.faab_bid, m.ingested_ms,
               m.metadata_json,
               COALESCE(pm.canonical_manager_id, m.manager_key)
                 AS canonical_manager_key,
               ca.display_name, ca.nfl_team, ca.position
          FROM asset_movements m
          LEFT JOIN platform_managers pm ON pm.manager_key=m.manager_key
          LEFT JOIN canonical_assets ca
                 ON ca.canonical_asset_id=m.canonical_asset_id
         WHERE {' AND '.join(clauses)}
         ORDER BY m.ts DESC, m.movement_key
    """
    try:
        rows = connection.execute(sql, params).fetchall()
        return [
            {
                "platform": r["platform"],
                "movementKey": r["movement_key"],
                "transactionKey": r["transaction_key"],
                "leagueKey": r["league_key"],
                "canonicalAssetId": r["canonical_asset_id"],
                "sourceAssetId": r["source_asset_id"],
                "assetType": r["asset_type"],
                "action": r["action"],
                "managerKey": r["manager_key"],
                "canonicalManagerKey": r["canonical_manager_key"],
                "counterpartyManagerKey": r["counterparty_manager_key"],
                "timestampMs": int(r["timestamp_ms"]),
                "week": r["week"],
                "faabBid": r["faab_bid"],
                "ingestedMs": int(r["ingested_ms"]),
                "metadata": json.loads(r["metadata_json"] or "{}"),
                "displayName": r["display_name"],
                "nflTeam": r["nfl_team"],
                "position": r["position"],
            }
            for r in rows
        ]
    finally:
        if own:
            connection.close()


def audit_asset(
    canonical_asset_id: str,
    *,
    manager_keys: Sequence[str],
    since_ms: int | None = None,
    until_ms: int | None = None,
    path: Path | None = None,
    limit: int = 250,
) -> list[dict[str, Any]]:
    rows = query_movements(
        manager_keys=manager_keys,
        since_ms=since_ms,
        until_ms=until_ms,
        path=path,
    )
    out = []
    for row in rows:
        if row["canonicalAssetId"] != canonical_asset_id:
            continue
        metadata = row.get("metadata") or {}
        out.append(
            {
                "platform": row["platform"],
                "league": row["leagueKey"],
                "transaction": row["transactionKey"],
                "timestamp": row["timestampMs"],
                "manager": row["managerKey"],
                "direction": row["action"],
                "asset": row["canonicalAssetId"],
                "sourceAssetId": row["sourceAssetId"],
                "sourceUrl": metadata.get("sourceUrl"),
                "sourceReference": metadata.get("sourceReference"),
                "ingestedTimestamp": row["ingestedMs"],
            }
        )
        if len(out) >= limit:
            break
    return out


def platform_coverage(path: Path | None = None) -> dict[str, dict[str, Any]]:
    conn = ensure_platform_schema(path)
    try:
        out: dict[str, dict[str, Any]] = {}
        for platform in ("sleeper", "ffpc"):
            managers = int(
                conn.execute(
                    "SELECT COUNT(*) FROM platform_managers WHERE platform=?", (platform,)
                ).fetchone()[0]
            )
            leagues = int(
                conn.execute(
                    "SELECT COUNT(*) FROM platform_leagues WHERE platform=?", (platform,)
                ).fetchone()[0]
            )
            transaction_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM transactions WHERE platform=?",
                    (platform,),
                ).fetchone()[0]
            )
            row = conn.execute(
                """
                SELECT COUNT(*) AS movements,
                       MAX(ts) AS latest,
                       MAX(ingested_ms) AS ingested
                  FROM asset_movements
                 WHERE platform=?
                """,
                (platform,),
            ).fetchone()
            run = conn.execute(
                "SELECT status, started_ms, finished_ms, pages_fetched, pages_parsed, "
                "parse_failures, unmapped_players, automated_ffpc_qualifiers, "
                "curated_ffpc_contributors FROM ingestion_runs "
                "WHERE platform=? ORDER BY started_ms DESC LIMIT 1",
                (platform,),
            ).fetchone()
            out[platform] = {
                "managers": managers,
                "leagues": leagues,
                "transactions": transaction_count,
                "movements": int(row["movements"] or 0),
                "lastActivityAt": int(row["latest"]) if row["latest"] else None,
                "lastUpdatedAt": int(row["ingested"]) if row["ingested"] else None,
                "latestIngestion": dict(run) if run else None,
            }
        return out
    finally:
        conn.close()


def unmapped_assets(path: Path | None = None, *, platform: str = "ffpc") -> list[dict[str, Any]]:
    conn = ensure_platform_schema(path)
    try:
        rows = conn.execute(
            """
            SELECT * FROM unmapped_assets
             WHERE platform=?
             ORDER BY occurrences DESC, last_seen_ms DESC
            """,
            (platform,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def hydrate_sleeper_asset_catalog(
    players: dict[str, dict[str, Any]] | None,
    *,
    path: Path | None = None,
    conn: sqlite3.Connection | None = None,
) -> int:
    """Populate canonical display metadata from Sleeper's player directory."""
    own = conn is None
    connection = ensure_platform_schema(path, conn=conn)
    count = 0
    try:
        for source_id, raw in (players or {}).items():
            if not isinstance(raw, dict):
                continue
            name = str(raw.get("full_name") or raw.get("search_full_name") or "").strip()
            if not name:
                continue
            from src.platforms.assets import normalize_asset_name

            register_asset_alias(
                platform="sleeper",
                source_asset_id=str(source_id),
                canonical_asset_id=str(source_id),
                source_name=name,
                normalized_name=normalize_asset_name(name),
                nfl_team=str(raw.get("team") or "").strip().upper() or None,
                position=str(raw.get("position") or "").strip().upper() or None,
                asset_type="player",
                match_method="authoritative_source_id",
                match_confidence=1.0,
                manually_verified=True,
                metadata={"catalogSource": "sleeper_players"},
                conn=connection,
            )
            count += 1
        connection.commit()
        return count
    except Exception:
        connection.rollback()
        raise
    finally:
        if own:
            connection.close()


def record_ingestion_run(
    *,
    run_id: str,
    platform: str,
    source_ref: str | None,
    started_ms: int,
    finished_ms: int | None,
    status: str,
    counters: dict[str, int] | None = None,
    error: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    path: Path | None = None,
    busy_timeout_ms: int | None = None,
) -> None:
    """Upsert one row into ``ingestion_runs``.

    ``busy_timeout_ms`` bounds how long this call waits for the ledger's
    write lock, overriding the connection default (30 s).

    It exists for the FAILURE-recording path, and V1-59 is why.  This
    function opens its OWN connection, so when the primary work died on
    write-lock contention the recorder queued behind the very lock that
    caused the failure, waited the full 30 s, and then raised — measured
    at 30.09 s in the controlled reproduction.  On a unit already at its
    ``TimeoutStartSec`` that wait is often long enough to be SIGKILLed
    mid-wait, so the run was never marked ``failed`` at all and
    ``platform_coverage`` went on reporting the previous SUCCESS as the
    latest ingestion.

    A shorter budget does not make the write more likely to succeed; it
    makes the attempt survivable, so the caller reaches its own reporting.
    The lock is still never ignored — contention raises, and callers must
    not swallow it.
    """
    values = counters or {}
    conn = ensure_platform_schema(path)
    if busy_timeout_ms is not None:
        conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)}")
    try:
        conn.execute(
            """
            INSERT INTO ingestion_runs
              (run_id, platform, source_ref, started_ms, finished_ms, status,
               pages_fetched, pages_parsed, parse_failures,
               transactions_discovered, transactions_deduplicated,
               movements_inserted, movements_skipped, unmapped_players,
               ambiguous_manager_identities, automated_ffpc_qualifiers,
               curated_ffpc_contributors, error_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
              finished_ms=excluded.finished_ms, status=excluded.status,
              pages_fetched=excluded.pages_fetched,
              pages_parsed=excluded.pages_parsed,
              parse_failures=excluded.parse_failures,
              transactions_discovered=excluded.transactions_discovered,
              transactions_deduplicated=excluded.transactions_deduplicated,
              movements_inserted=excluded.movements_inserted,
              movements_skipped=excluded.movements_skipped,
              unmapped_players=excluded.unmapped_players,
              ambiguous_manager_identities=excluded.ambiguous_manager_identities,
              automated_ffpc_qualifiers=excluded.automated_ffpc_qualifiers,
              curated_ffpc_contributors=excluded.curated_ffpc_contributors,
              error_json=excluded.error_json,
              metadata_json=excluded.metadata_json
            """,
            (
                run_id,
                platform,
                source_ref,
                int(started_ms),
                int(finished_ms) if finished_ms is not None else None,
                status,
                int(values.get("pagesFetched", 0)),
                int(values.get("pagesParsed", 0)),
                int(values.get("parseFailures", 0)),
                int(values.get("transactionsDiscovered", 0)),
                int(values.get("transactionsDeduplicated", 0)),
                int(values.get("movementsInserted", 0)),
                int(values.get("movementsSkipped", 0))
                + int(values.get("movementsSkippedAsDuplicates", 0)),
                int(values.get("unmappedPlayers", 0)),
                int(values.get("ambiguousManagerIdentities", 0)),
                int(values.get("automatedFfpcQualifiers", 0)),
                int(values.get("curatedFfpcContributors", 0)),
                _json(error),
                _json(metadata),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def latest_ingestion_run(platform: str, *, path: Path | None = None) -> dict[str, Any] | None:
    conn = ensure_platform_schema(path)
    try:
        row = conn.execute(
            "SELECT * FROM ingestion_runs WHERE platform=? " "ORDER BY started_ms DESC LIMIT 1",
            (platform,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
