# Unified Sharp Tracker: Sleeper + FFPC

## Scope

Sharp Tracker has one downstream market-signal pipeline. Sleeper and FFPC are independent upstream adapters; neither owns a separate score, endpoint, page, or table.

```text
Sleeper crawler/adaptor ─┐
                         ├─ platform-neutral identities and evidence
FFPC public-page adapter ┘          │
                                    ▼
                         normalized SQLite ledger
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
             Sharp Score v2 cohort         curated FFPC cohort
                     └──────────────┬──────────────┘
                                    ▼
                     raw canonical asset movements
                                    ▼
                       one unified market table
```

The existing Sleeper crawl remains the production acquisition path. `src/platforms/sleeper.py` is a thin compatibility adapter around its persisted state; it does not replace or fork the working crawler.

## Platform-scoped identities

Every source identity is namespaced before it enters a cross-platform query:

```text
manager_key     = <platform>:<source-manager-id>
league_key      = <platform>:<source-league-id>
transaction_key = <platform>:<source-transaction-id>
movement_key    = <platform>:<deterministic-movement-id>
```

Examples:

```text
sleeper:123456789
ffpc:site-user-4567
ffpc:league:789:team:123
```

The migration keeps the original Sleeper primary keys intact so every existing Sleeper query and count remains stable. The new scoped columns are additive. FFPC rows use their scoped key in the legacy primary-key columns, preventing a bare FFPC identifier from colliding with the same bare Sleeper identifier.

A Sleeper identity and FFPC identity are never linked by username, display name, team name, or fuzzy matching. `platform_managers.canonical_manager_id` is populated only by an explicit verified identity record. Until that happens, the two keys remain distinct. Combined unique-manager counts use `canonical_manager_id` when present and the platform-scoped key otherwise.

### FFPC identity hierarchy

1. Verified FFPC global/SiteUser identifier: `global_verified`
2. Stable but not independently verified global identifier: `global_unverified`
3. League-scoped team/entry identifier: `league_scoped_team`
4. League-scoped deterministic name hash: `name_only`

A league-scoped or name-only identity cannot satisfy automated multi-league Sharp qualification.

## Additive database migration

`src/intel/platform_ledger.py` extends the existing ledger with:

- platform/scoped-key columns on `transactions`, `asset_movements`, and `manager_seasons`
- `platform_managers`
- `manager_identity_links` (explicit, verified cross-platform links only)
- `platform_leagues`
- `platform_memberships`
- `canonical_assets`
- `asset_aliases`
- `unmapped_assets`
- `ingestion_runs`

The migration:

1. Opens the existing SQLite ledger.
2. Creates a SQLite online backup, including committed WAL data.
3. Adds columns and tables inside one transaction. An implicit first-use migration also creates a fixed-name WAL-safe `*.pre-platform-v2-auto.bak` before changing schema.
4. Backfills every existing row as `platform='sleeper'`.
5. Creates synchronization triggers for future legacy Sleeper writes.
6. verifies row-count preservation, scoped keys, and orphan counts.
7. records schema version `2` in `meta`.
8. safely returns the same report when rerun.

Run it with:

```bash
python scripts/migrate_intel_platform_v2.py
```

Use `--no-backup` only in disposable test environments.

## FFPC access model

The first implementation is deliberately **public-only, read-only, and disabled by default**.

The HTTP client supports only `GET` against exact configured HTTPS URLs on an allowlist. It has no methods for authentication, cookies, session replay, contest entry, lineup changes, drafts, FAAB submission, trades, payments, account changes, or identifier enumeration.

Each request supports:

- raw body and response-metadata caching
- retrieval timestamp and source URL
- ETag and Last-Modified conditional requests
- timeout and bounded retries
- exponential backoff
- a descriptive user agent
- an inter-request delay
- a hard per-run request budget
- redirect validation against the same host allowlist

No credentials, session IDs, or cookies belong in committed configuration. The `authenticatedApi.enabled` flag must remain false; the collector exits rather than using it.

### Terms and access limitation

FFPC has not published a supported public data API for this use. Public page accessibility and page structure can change, and public visibility does not itself grant permission for automated collection. Obtain FFPC approval before enabling production collection. The adapter is structured to minimize load and risk, not to assert that scraping is contractually permitted.

## Configuration

Configuration is stored in `config/sharp/ffpc_sources.json`.

```json
{
  "enabled": false,
  "mode": "public_only",
  "requestBudgetPerRun": 100,
  "sleepSecondsBetweenCalls": 1.5,
  "cacheHours": 12,
  "seedLeagues": [
    {
      "sourceLeagueId": "public-league-id",
      "publicUrls": [
        "https://www.myffpc.com/<public-standings-url>",
        "https://www.myffpc.com/<public-transactions-url>"
      ],
      "season": "2026",
      "format": "dynasty",
      "enabled": true,
      "sharpEligible": false,
      "seasonComplete": false,
      "verifiedGlobalUserIds": []
    }
  ],
  "curatedManagers": [],
  "allowCuratedInCombinedSignals": false,
  "authenticatedApi": {"enabled": false}
}
```

`sharpEligible`, `seasonComplete`, and `verifiedGlobalUserIds` are explicit operator attestations. They must not be enabled merely because a page looks like a dynasty standings page. Automated FFPC evidence enters Sharp Score v2 only when all required evidence is present and these assertions are supportable.

To disable FFPC without affecting Sleeper, set `enabled` to false and disable the optional FFPC timer. The unified endpoint continues to query and display Sleeper data.

## FFPC parser behavior

The parser uses semantic table headers, text labels, data attributes, and URL parameters. CSS class names are not required. Saved sanitized fixtures cover standings, rosters, historical seasons, draft boards, trades, picks, waivers/FAAB, changed column order, missing optional fields, duplicate representations, and invalid pages.

### Supported public-page fields

When visibly and reliably present, the adapter can normalize:

- league identifier, name, season, format assertion, and team count
- team/entry identifier, manager display name, roster membership, and visible roster assets retained in audit metadata
- standings: wins, losses, ties, points for/against, rank, playoff flag, championship and runner-up flags, completion flag
- trade rows: timestamp, week, participating teams, player/pick, action, counterparty, source transaction identifier
- waiver/free-agent rows and visible FAAB bid
- draft-board selections for mapping/audit coverage
- draft picks with season, round, and original owner when exposed

### Fields not assumed

The adapter leaves a value unknown when the page does not prove it. In particular, it does not infer:

- global manager identity from a name
- a completed season from the calendar
- ties as zero when the ties column is absent
- playoff/championship results from regular-season rank
- dynasty eligibility from a generic contest name
- a historical league chain when no public link exists
- original pick ownership when the page does not show it
- private roster, transaction, or account data

Unknown evidence stays inspectable with exclusion reasons such as `league_scoped_identity`, `missing_completed_season`, `missing_ties`, `missing_final_standing`, `missing_playoff_result`, `unknown_or_ineligible_league_format`, and `insufficient_multi_league_identity`.

## Canonical assets

Sleeper player IDs remain the canonical player IDs because existing Sharp and frontend data already use them. FFPC source IDs/names are stored as aliases.

The automatic match ladder is intentionally strict:

1. manual verified alias or authoritative external ID
2. exact normalized full name + NFL team + position
3. exact normalized full name + position
4. globally unique exact normalized full name, with suffixes such as Jr., Sr., II, and III preserved

There is no fuzzy fallback, and a missing suffix does not auto-match a suffixed player. Ambiguous or unmatched assets are written to `unmapped_assets` and excluded from canonical market totals until resolved.

Manual aliases are stored in `config/sharp/ffpc_asset_mappings.json`:

```json
{
  "ffpc:<source-asset-id>": "<canonical-sleeper-player-id>"
}
```

Inspect the queue with:

```bash
python - <<'PY'
from src.intel import platform_ledger
import json
print(json.dumps(platform_ledger.unmapped_assets(platform="ffpc"), indent=2))
PY
```

Draft picks use:

```text
pick:<season>:<round>
pick:<season>:<round>:<original-owner-or-slot>
```

When original ownership is visible, distinct picks are never collapsed into one generic round asset.

## Transaction normalization and deduplication

The ledger preserves three separate units:

- one source transaction
- one asset movement/manager observation
- one canonical asset aggregate produced later

Trades contribute to Sharp buy/sell signals. Waivers and free-agent activity remain in the ledger but are excluded by the trade-only market query. A waiver claim is never a trade buy, and a drop is never a trade sell.

An authoritative FFPC transaction ID is used when present. Otherwise, a deterministic trade fingerprint is built from:

- platform and league
- season and timestamp
- transaction type
- sorted participating team identifiers
- sorted canonical/source assets
- visible FAAB information

Display order is not included. Rows without an ID are grouped by timestamp plus an explicit unordered participant pair before fingerprinting, so duplicate team-side renderings converge on one transaction without accidentally merging two simultaneous trades made by the same manager against different partners. Each movement key is then derived from transaction key, manager key, action, canonical/source asset, and a pick/asset discriminator. Reprocessing the same page inserts zero new movements.

## Automated versus curated qualification

There is one Sharp Score formula: `sharp-v2` in `src/sharp/score.py` and `config/sharp/scoring_v2.json`. Platform support does not alter any weight, gate, confidence threshold, or percentile rule.

### Automated qualification

A platform-neutral `ManagerRecord` is built only from season rows that have:

- a verified global manager identity
- a confirmed qualifying dynasty league
- a complete season
- trustworthy wins, losses, and ties
- final rank and team count
- playoff and championship results
- recent trade activity sufficient to evaluate the existing activity/recency gates (FFPC rows without observed activity remain `missing_recent_activity`)

The manager must then pass the unchanged Sharp Score v2 gates. FFPC evidence that does not meet these conditions is not scored as zero; it is excluded with reasons.

### Curated FFPC high-stakes cohort

A curated record is a separate qualification method, `curated_high_stakes`. It requires an explicit manager key, public name, rationale/references, added date, verified flag, contribution permission, and configured quality weight.

Curated observations enter the default combined table only when both are true:

- the manager record has `verified: true` and `allowedToContribute: true`
- `allowCuratedInCombinedSignals` is true

The default is false. Curated managers are never labeled as Sharp Score v2 qualifiers.

## Unified market mathematics

`GET /api/sharp/market` selects allowed manager keys and queries raw normalized movements independently for every requested time window. It does not add precomputed source summaries.

For one canonical asset:

```text
buys   = count(raw trade movements where action = add)
sells  = count(raw trade movements where action = drop)
net    = buys - sells
volume = buys + sells
```

Unique managers use an explicit canonical manager identity when one exists; otherwise platform-scoped keys are distinct. Unique leagues always use platform-scoped league keys.

Source summaries are derived from the same raw movement set. Therefore:

```text
combined buys   = Sleeper buys   + FFPC buys
combined sells  = Sleeper sells  + FFPC sells
combined volume = Sleeper volume + FFPC volume
```

Unique-manager totals are set cardinalities, not sums of per-source counts.

Manager quality is the observation-weighted mean of the actual managers contributing movements to that asset in the selected window:

```text
asset_manager_quality = sum(manager_quality for each movement) / movement_count
```

Automated quality is `Sharp Score / 100`. Curated quality is the configured curated weight. Existing `signal_strength`, `confidence_tier`, breadth, and velocity functions are then applied unchanged.

Time windows remain overlapping independent views. A movement 15 days old appears once in the 30-day query and once in the 90-day query; those views are never added together.

## API

### `GET /api/sharp/cohort`

Existing route and fields remain available. Platform coverage and curated counts are additive.

### `GET /api/sharp/market`

Parameters:

```text
window=48h|7d|14d|30d|90d|all
sort=strength|net|volume|velocity|buys|sells
assetType=player|pick|all
platform=all|sleeper|ffpc
qualification=all|automated|curated
limit=1..500
```

The response contains one row per canonical asset, combined windows, source breakdowns, source labels, signal strength, confidence, velocity, manager quality, coverage, stale/degraded state, and unmapped-asset count.

### `GET /api/sharp/market/audit`

Parameters: `assetId`, `window`, and `qualification`.

Each returned movement includes platform, league, transaction, timestamp, manager, direction, canonical/source asset, qualification method, source reference/URL, and ingestion timestamp.

## Frontend behavior

`/market/sharp-tracker` remains the single route. Its single table displays one canonical row with columns for signal, buys, sells, net, volume, managers, leagues, velocity, confidence, sources, and last activity. Expanding a row shows exact Sleeper and FFPC reconciliations.

The source filter sends `platform=sleeper|ffpc` to the normalized endpoint. It does not hide rows from a combined response. One source can be disabled, stale, or failed while the other remains usable.

## Running collection

Offline fixture demonstration:

```bash
python scripts/crawl_ffpc_sharp.py \
  --fixture tests/platforms/ffpc/fixtures/transactions.html \
  --players-fixture tests/platforms/ffpc/fixtures/players.json \
  --source-league fixture \
  --dry-run
```

Configured public collection:

```bash
python scripts/crawl_ffpc_sharp.py --public-only --dry-run --verbose
python scripts/crawl_ffpc_sharp.py --public-only
python scripts/crawl_ffpc_sharp.py --public-only --source-league <id> --budget 25
```

Install the isolated optional timer only after FFPC is enabled and approved:

```bash
APP_DIR=/home/dynasty/trade-calculator \
VENV_DIR=/home/dynasty/.venvs/trade-calculator \
SERVICE_NAME=dynasty \
bash deploy/install-ffpc-sharp-service.sh
```

The FFPC job runs separately from Sleeper jobs. It never runs during a user request, and its failure does not stop Sleeper ingestion or the unified read path.
