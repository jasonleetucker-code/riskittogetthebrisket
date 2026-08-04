# FFPC unified Sharp implementation map

## Audit result

The pre-change system had correct shared trade-counting primitives but source-specific identity assumptions:

- `src/intel/ledger.py` stored bare Sleeper `user_id`, `league_id`, `tx_id`, and `movement_id`.
- `src/sharp/records.py` assembled records from Sleeper season rows.
- `src/sharp/service.py` exposed cohort status but no market table endpoint.
- `src/intel/signals.py` already contained the authoritative independent-window, confidence, breadth, velocity, and signal-strength formulas.
- `/market/sharp-tracker` displayed cohort coverage only.

The implementation preserves `src/intel/signals.py` and `src/sharp/score.py` as the single mathematical authorities and adds platform-neutral layers around them.

## Created

- `src/platforms/base.py` — normalized adapter contract and typed records
- `src/platforms/assets.py` — strict canonical asset mapping
- `src/platforms/sleeper.py` — thin existing-Sleeper compatibility adapter
- `src/platforms/ffpc/client.py` — bounded public read-only client
- `src/platforms/ffpc/identity.py` — scoped FFPC identity hierarchy
- `src/platforms/ffpc/parser.py` — semantic public-page parser
- `src/platforms/ffpc/adapter.py` — normalized FFPC adapter
- `src/intel/platform_ledger.py` — additive platform schema, verified identity links, migration, ingestion, alias repair, audit queries
- `src/sharp/platform_records.py` — platform-neutral season evidence
- `src/sharp/market.py` — unified raw-movement market aggregation
- `scripts/migrate_intel_platform_v2.py` — backup/migration/report command
- `scripts/crawl_ffpc_sharp.py` — read-only FFPC collector
- `frontend/app/api/sharp/market/route.js` — Next backend proxy
- `deploy/ffpc-systemd/*` and `deploy/install-ffpc-sharp-service.sh` — optional isolated scheduler
- `config/sharp/ffpc_sources.json` and `ffpc_asset_mappings.json`
- fixture, migration, parser, identity, cohort, unified-signal, scheduler, CLI demonstration, API-surface, and frontend tests

## Modified

- `src/sharp/service.py` — platform-neutral cohort and `/api/sharp/market`/audit registration
- `frontend/app/market/sharp-tracker/page.jsx` — one unified table and source/qualification controls
- `docs/intel/SHARP_SCORE.md` — platform-neutral evidence clarification; methodology unchanged

## Located identity dependencies

The repository-wide search covered all usages requested in the implementation brief: `user_id`, `ownerId`, `league_id`, `tx_id`, `movement_id`, `sleeper_users`, `manager_seasons`, `asset_movements`, `Sharp Tracker`, `/api/sharp`, `build_asset_signals`, and `ManagerRecord`.

The migration is additive because existing Insider Trading, crawler, public-league, and audit consumers still read legacy columns. Scoped columns are used by the unified Sharp path; legacy fields remain stable for existing Sleeper consumers.
