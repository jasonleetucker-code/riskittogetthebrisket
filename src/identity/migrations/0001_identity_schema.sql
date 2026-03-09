-- Phase 1 identity schema

CREATE TABLE IF NOT EXISTS players (
  player_id TEXT PRIMARY KEY,
  sleeper_id TEXT DEFAULT '',
  full_name TEXT NOT NULL,
  search_name TEXT NOT NULL,
  team TEXT DEFAULT '',
  position TEXT DEFAULT '',
  position_group TEXT DEFAULT '',
  rookie_class_year INTEGER,
  age REAL,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS player_aliases (
  alias_id TEXT PRIMARY KEY,
  player_id TEXT NOT NULL,
  source TEXT NOT NULL,
  external_asset_id TEXT DEFAULT '',
  external_name TEXT NOT NULL,
  name_normalized TEXT NOT NULL,
  team_raw TEXT DEFAULT '',
  position_raw TEXT DEFAULT '',
  match_confidence REAL NOT NULL,
  match_method TEXT NOT NULL,
  first_seen_snapshot_id TEXT NOT NULL,
  last_seen_snapshot_id TEXT NOT NULL,
  FOREIGN KEY(player_id) REFERENCES players(player_id)
);

CREATE TABLE IF NOT EXISTS picks (
  pick_id TEXT PRIMARY KEY,
  season INTEGER NOT NULL,
  round INTEGER NOT NULL,
  slot_known INTEGER NOT NULL DEFAULT 0,
  slot_number INTEGER,
  bucket TEXT DEFAULT '',
  league_id TEXT DEFAULT '',
  description TEXT DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pick_aliases (
  pick_alias_id TEXT PRIMARY KEY,
  pick_id TEXT NOT NULL,
  source TEXT NOT NULL,
  external_asset_id TEXT DEFAULT '',
  external_name TEXT NOT NULL,
  year_guess INTEGER,
  round_guess INTEGER,
  bucket_guess TEXT DEFAULT '',
  match_confidence REAL NOT NULL,
  match_method TEXT NOT NULL,
  FOREIGN KEY(pick_id) REFERENCES picks(pick_id)
);

CREATE INDEX IF NOT EXISTS idx_player_aliases_source_name
  ON player_aliases(source, name_normalized);

CREATE INDEX IF NOT EXISTS idx_player_aliases_external_id
  ON player_aliases(source, external_asset_id);

CREATE INDEX IF NOT EXISTS idx_pick_aliases_external_id
  ON pick_aliases(source, external_asset_id);

