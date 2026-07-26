# Player Context Data Layer (`src/playerctx/`)

Contracts, snap share, and depth-chart standing for every player in
the Sleeper pool — the scouting-report-grade context the redesigned
player profiles will consume.  This layer is **data + tooling only**:
nothing in `server.py`, `data_contract.py`, or `frontend/` reads it
yet.  Consumption wiring lands with the player-profile redesign (R2).

## Datasets

All sources are nflverse's public GitHub release assets (no auth, no
API keys).  URLs verified live 2026-07-25.

| Dataset | URL | Size | Join key |
|---|---|---|---|
| Contracts (OTC-sourced) | `https://github.com/nflverse/nflverse-data/releases/download/contracts/historical_contracts.csv.gz` | ~1.2 MB (~32k rows) | name + position (no gsis) |
| Snap counts (PFR-sourced) | `https://github.com/nflverse/nflverse-data/releases/download/snap_counts/snap_counts_{season}.csv` | ~2.4 MB / season (~27k rows) | name + team + position (no gsis) |
| Depth charts | `https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_{season}.csv` | 35–55 MB / season | `gsis_id` / `espn_id` (exact) |
| Sleeper players directory | `https://api.sleeper.app/v1/players/nfl` | ~5 MB JSON | join anchor |

Seasonal files are tried newest-calendar-year-first with a fallback to
the prior season **only on a genuine upstream 404** — snap counts for
year N don't exist until the N season kicks off, while the depth-chart
file for the upcoming season is refreshed daily through the offseason.
A transient failure (timeout / 5xx / connection error) on the current
season stops the walk instead of quietly publishing last year's file:
with no local copy the refresh fails (exit 1) and the last-good
snapshot stays untouched; with a local copy of that season the stale
copy is used.  A 404 on a file we already hold locally (asset removed
or temporarily unavailable upstream) also degrades to the cached copy
rather than regressing to the prior season — only a 404 with no local
copy walks on.

### Verified schemas

Contracts (`historical_contracts.csv.gz`):

    player,position,team,is_active,year_signed,years,value,apy,
    guaranteed,apy_cap_pct,inflated_value,...,otc_id,...,draft_team,
    season_history

`team` is the franchise **nickname** ("Packers"); dollars are raw
integers; `is_active` is TRUE/FALSE.

Snap counts (`snap_counts_{season}.csv`):

    game_id,pfr_game_id,season,game_type,week,player,pfr_player_id,
    position,team,opponent,offense_snaps,offense_pct,defense_snaps,
    defense_pct,st_snaps,st_pct

One row per player-game; `*_pct` are 0–1 fractions.

Depth charts (`depth_charts_{season}.csv`):

    dt,team,player_name,espn_id,gsis_id,pos_grp_id,pos_grp,pos_id,
    pos_name,pos_abb,pos_slot,pos_rank

The file appends a full dated snapshot (`dt`) per upstream scrape run;
we keep only the **newest snapshot per team**.  `pos_grp` is one of
an offensive formation ("3WR 1TE"), "Base 3-4 D" / "Base 4-3 D", or
"Special Teams".

## Pipeline

`scripts/refresh_playerctx.py` → `service.refresh_playerctx()`:

1. **fetch** (`fetch.py`) — downloads to `data/playerctx/` (covered by
   the repo-wide `data/` gitignore).  Honest UA, 15 s/180 s timeouts,
   mtime freshness window (default 6 h, ≥20 h for the Sleeper dump per
   Sleeper's rate guidance), then conditional GET via the stored
   ETag/Last-Modified sidecar (`<file>.meta.json`); 304 just bumps the
   mtime.  Network failure with a stale local copy degrades to the
   copy instead of failing.
2. **normalize** (`normalize.py`) — parse + aggregate:
   * contracts: `is_active` rows only, one per player (latest
     `year_signed`), nickname → abbreviation.
   * snaps: newest season in the file, per-player mean snap % (0–100),
     last-3-games mean, `trend` = recent − season (postseason ordered
     after REG), `side` = whichever unit has the MOST snaps across
     offense / defense / special teams (tie precedence
     defense > offense > st) — so a kicker with one trick-play
     offensive snap still classifies `st` with his real ST share.  Aggregation identity is `pfr_player_id`;
     ID-less rows fall back to normalized name + position family
     *without* team so a traded player's stints stay one season line,
     and an ID-less group whose rows play the same week twice (two
     distinct humans on one key) is dropped rather than merged.
   * depth: newest `dt` per team, fantasy slots only (OL and
     non-kicker specialists dropped), slot abbreviations collapsed to
     `POSITION_ALIASES` families, `rank` = 1-based standing among the
     team's players at that base position (slot starters first, then
     backups).
3. **join** — depth rows join by exact gsis/espn ID; contracts and
   snaps go through the unified-mapper name ladder
   (name+team+pos → name+pos → unique name, prebuilt as O(1) indexes).
   Each deterministic rung accepts only a **unique** candidate: when
   two active pool players share a normalized name + position family
   and the source team is absent or stale (contracts carry the signing
   team), the row is never attached to "whichever was indexed first".
   The team rung is consulted only when the source actually supplies a
   team — a teamless row must not pseudo-match a free agent's
   empty-team index entry.
   Manual overrides (`config/identity/id_overrides.json`, same file
   and loader as the unified mapper) are reverse-indexed by normalized
   full_name / gsis_id / espn_id → sleeper_id and consulted after the
   deterministic rungs miss but before the fuzzy fallback — an
   operator-pinned mapping settles ambiguity and beats a fuzzy guess.
   Unknown names (zero candidates) fall through to
   `src.identity.unified_mapper.resolve_player` for its fuzzy layer;
   ambiguous names never do (its candidate walk is first-match-wins) —
   without an override they are dropped (drop-don't-guess).  Team is
   decisive in the fuzzy tail: when the source names a team, fuzzy
   runs against that team's sub-pool only, so a team-matching
   candidate wins even at a lower score and a row never crosses teams
   on a fuzzy guess; teamless rows fuzzy against the full pool.  Rows
   that still don't map to the Sleeper pool are dropped and counted.
4. **floors** — schema drift (missing columns) or parsed-row counts
   under the floors (`contracts` 1000, snap aggregates 700, depth rows
   1200, joined players 400) raise `SchemaRegressionError` → exit 2.
   Retention vs the last-good snapshot is checked twice: the union
   (>25 % player-count collapse) AND each source's matched count
   individually, so one source regressing semantically (e.g. contracts
   matching nothing after a naming change) can't hide behind a healthy
   total.  Either breach → exit 2 with the last-good snapshot left
   untouched.  Soft failures (network, empty parse) → exit 1.
5. **store** (`store.py`) — atomic tmp-then-replace write of
   `data/playerctx/snapshot.json`.

## Snapshot contract (`playerctx.v1`)

```jsonc
{
  "schemaVersion": "playerctx.v1",
  "generatedAt": "2026-07-26T01:04:00+00:00",
  "counts": {
    "contracts":   {"parsed": 2907, "matched": 2281},
    "snapCounts":  {"parsed": 2189, "matched": 1772},
    "depthCharts": {"parsed": 2343, "matched": 2317},
    "noGsisFallback": 786,
    "players": 3856
  },
  "sources": { "contracts": {"url": "..."}, "snapCounts": {"url": "...", "season": 2025}, ... },
  "sleeperIndex": { "<sleeper_id>": "<record key>", ... },
  "players": {
    "00-0033280": {
      "gsisId": "00-0033280",
      "sleeperId": "4034",
      "name": "Christian McCaffrey",   // Sleeper pool is canonical
      "team": "SF",
      "position": "RB",                 // POSITION_ALIASES family
      "contract": {                     // optional block
        "apy": 16015853, "total": 64063412, "guaranteed": 36346412,
        "years": 4, "yearSigned": 2020, "endYear": 2023, "team": "CAR"
      },
      "snaps": {                        // optional block
        "season": 2025, "games": 19, "side": "offense",  // "offense" | "defense" | "st"
        "pct": 81.7, "recentPct": 75.3, "trend": -6.4
      },
      "depth": {                        // optional block
        "position": "RB", "rank": 1, "depthPosition": "RB", "team": "SF"
      }
    }
  }
}
```

Consumer rules for the profile UI (R2):

* **Look up by Sleeper ID through `sleeperIndex`** — record keys are
  `gsis_id` when known, else `"sleeper:<sleeper_id>"` (Sleeper's gsis
  coverage is sparse; ~⅓ of joined players key on the fallback).
  Never assume every key is a gsis id.
* Every context block (`contract` / `snaps` / `depth`) is optional —
  render what exists, hide what doesn't.  ~700 players carry all
  three.
* `load_playerctx()` returns `None` when no valid snapshot exists —
  "no context" is a normal state, not an error.
* Contract caveats (upstream OTC semantics, surfaced in the
  `parse_contracts` docstring): `contract.team` is the **signing**
  franchise (traded contracts keep their origin team); `endYear` is
  `yearSigned + years − 1` and can undershoot real expiry for
  in-contract extensions; the asset can lag recent signings by weeks.

## Refresh cadence

**Weekly is enough.**  Contracts move on OTC's cadence (rebuilds every
few weeks in the offseason), snap counts only change in-season, and
depth charts are refreshed daily upstream but only matter at weekly
granularity for dynasty context.  A run takes ~3 minutes (dominated by
the fuzzy-match tail and the ~35 MB depth-chart download; unchanged
files are skipped via ETag).  No GitHub Actions workflow is added in
this PR — schedule `python3 scripts/refresh_playerctx.py` alongside
the existing weekly jobs when the UI starts consuming the snapshot.

`data/` is gitignored, so the snapshot is **not** a committed
artifact: production materializes it by running the refresh script,
same as the other `data/` pipeline outputs.

## Observed baseline (2026-07-26 run)

* contracts: 2,907 active parsed → 2,281 matched to the pool
* snap counts (2025 season): 2,189 player aggregates → 1,772 matched
* depth charts (2026 file): 2,343 fantasy-slot rows → 2,317 matched
* joined players: 3,856 (715 with all three blocks)
* snapshot: ~1.1 MB compact JSON
