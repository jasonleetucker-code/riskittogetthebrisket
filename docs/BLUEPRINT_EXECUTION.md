# Risk It To Get The Brisket — Canonical Dynasty Engine Blueprint

> **⚠ STALE — March 2026 snapshot.**  This doc described the
> ``CANONICAL_DATA_MODE`` offline-canonical-build path that was
> retired in 2026.  The live ``/api/data`` contract is now the
> single source of truth (see `CLAUDE.md` → "Canonical Data Mode"
> section).  Kept for historical context — do NOT use as a current
> implementation reference.  For current architecture, read
> `CLAUDE.md` and `docs/ARCHITECTURE.md`.

_Last updated: 2026-03-09_

## 1. Mission Statement
Build a **private dynasty + IDP valuation platform** that:
- Ingests multiple external rankings/value sources (KTC, DLF, Dynasty Nerds, etc.).
- Resolves every asset (players, picks) to a single internal ID.
- Normalizes each source into a shared 0–9999 canonical scale.
- Applies **scoring adjustments** (TEP, pick year discount).
- Powers a decision layer (trade calculator, rankings, roster/league dashboard).

This is a five-system stack:
1. **Source ingestion system** — adapters + raw snapshots.
2. **Identity mapping system** — master player/pick IDs.
3. **Canonical value engine** — per-universe normalization + blending.
4. **League context engine** — scoring, pick logic (scarcity and replacement removed).
5. **Decision UI / API** — calculator, rankings, roster intelligence.

Everything downstream depends on getting those layers right and versioned.

---

## 2. Product Definition
### What v1 **is**
- Import & normalize signals from chosen sources.
- Offensive + IDP assets share the same canonical economy.
- League-scoped trade calculator with roster impact + balancing suggestions.
- Rankings/roster/team-value dashboards fed by canonical values.

### What v1 **is not**
- No public SaaS, anonymous users, crowd voting, or content network.
- No giant cross-league trade DB yet.
- No podcast/news layer.

MVP = Source ingest → Canonical values → Calibration → Trade calc → Rankings/Roster UI.

---

## 3. Architecture Layers
### 3.1 Raw Source Layer
- **Tables**: `raw_source_snapshots`, `raw_source_assets` (players + picks).
- Store _exact_ payloads per source pull (name, source ID, rank, value, metadata).
- Never mutate raw rows. Reruns should be possible without re-scraping.

### 3.2 Identity Resolution
- **Master tables**: `players`, `player_aliases`, `picks`, `pick_aliases`.
- Map Sleeper/KTC/DLF IDs, names, suffixes, positions, teams, rookie flags, IDP roles.
- No value blending until asset IDs are resolved.

### 3.3 Canonical Normalization
- Separate universes: Offense Vet, Offense Rookie, IDP Vet, IDP Rookie, Picks.
- For each source snapshot:
  1. Rank assets.
  2. Convert to percentile.
  3. Apply curve (e.g., `score = round(9999 * percentile^0.65)` for MVP).
  4. Blend across sources with weights per universe.
- Store in `canonical_snapshots`, `canonical_asset_values` (versioned).

### 3.4 League Context Engine
- **League tables**: `leagues`, `league_settings`, `league_rosters`, `roster_assets`.
- Inputs: team count, lineup reqs, bench/taxi, superflex, TE premium, IDP structure, scoring per event, pick format.
- Outputs: package compression rules, pick discounts. (Replacement baselines and scarcity multipliers have been removed from the system.)

### 3.5 Decision Layer
- Services: trade calc API, rankings API, roster/team view API.
- Surfaces: calculator, rankings table, team/league dashboards, player detail, settings.
- Display base values, calibrated values, trade liquidity values.

---

## 4. Core Models & Tables
| Area | Tables / Files |
| --- | --- |
| Raw ingest | `raw_source_snapshots`, `raw_source_asset_values` |
| Identity | `players`, `player_aliases`, `picks`, `pick_aliases` |
| Canonical | `canonical_snapshots`, `canonical_asset_values`, `value_history` |
| League | `leagues`, `league_settings`, `league_rosters`, `roster_assets` |
| Trade history | `trade_evaluations`, `package_adjustments` |
| Config | `source_configs`, `league_profiles`, `pick_curves` |

Every canonical run is versioned. Trend charts must reference snapshot IDs.

---

## 5. Normalization & Blending Rules
1. **Percentile transform** per source/universe.
2. **Curve** (power/logistic) to widen elite tier, compress bottom.
3. **Blend** sources with weights that reflect coverage + stability.
4. **League adjustments**: apply TEP, pick year discount, rookie optimism dial, contender vs rebuilder dial. (Scarcity multipliers and position factors / LAM removed.)
5. **Trade liquidity**: add package compression (premium for fewer/better assets) + pick time discount.

---

## 6. League Context & Pick Engine
- Pick model: tiered curve by slot (1.01 elite, 1.04–1.06 strong, etc.), adjustable class strength + future discount.
- Support early/mid/late buckets when slot unknown.
- _Note: Replacement baselines and scarcity multipliers were previously planned here but have been removed from the system._

---

## 7. Trade Engine Contract
For each proposed deal:
1. Raw totals per side (base + calibrated values).
2. Package adjustment / consolidation premium.
3. Lineup impact (who becomes starter/bench, positional needs).
4. Fairness band verdict + balancing suggestion (“add late 2nd or DB2-tier”).
5. Optional mode: Market mirror vs My board.

---

## 8. UI Surfaces (MVP)
1. **Calculator** – add assets, live verdict, suggested balancers.
2. **Rankings** – sortable master board (overall/offense/IDP/rookies/picks/my roster) with trend + source contribution.
3. **Team/League view** – team values, strengths/weaknesses, roster profiles.
4. **Player detail** – current value, trend history, tier, source breakdown.
5. **Settings** – league scoring, source weights, pick discounts, rookie optimism, contender/rebuilder mode.

---

## 9. Jenkins Responsibilities
- Schedule source pulls and roster imports.
- Validate: unmatched players, duplicate mappings, value outliers, rank jumps.
- Rebuild canonical snapshots & publish artifacts.
- Generate ops reports (risers/fallers, source failures, value drift, roster delta).
- Maintain audit logs (snapshot IDs, weights, adjustments).

### Jenkins File Targets
1. `jenkins/source_pull` – run adapters, dump raw snapshots.
2. `jenkins/canonical_build` – run normalization/blending per snapshot.
3. `jenkins/league_refresh` – apply league settings, rebuild adjusted values.
4. `jenkins/reporting` – output daily trend/ops report (Markdown/JSON).

---

## 10. Execution Backlog (Jenkins + Kodex)
### Phase 0 – Repo spine
- [x] Document current legacy stack (scrapers, server.py, frontend).
- [x] Carve out `/src` structure for new modules (`src/adapters`, `src/identity`, `src/canonical`, `src/league`, `src/api`).
- [x] Add `.env.example` + config loaders.

### Phase 1 – Source adapters & raw store
- [x] Define adapter contract (inputs, normalization hints, metadata).
- [x] Implement initial adapters (DLF CSV import, KTC scrape stub, placeholder manual CSV loader) into `raw_source_*` tables/files.
- [x] Raw snapshot storage + CLI/cron entrypoint.
- [ ] Unmatched-player report.

### Phase 2 – Identity mapping
- [x] Master `players` table + alias ingestion.
- [x] CLI to reconcile new names and flag manual review.
- [ ] Unit tests for suffix/punctuation/team changes.

### Phase 3 – Canonical pipeline
- [x] Define universes + weight config.
- [x] Percentile + curve transforms (power curve for MVP).
- [x] Source blending + snapshot versioning.
- [ ] Store canonical assets + value history.

### Phase 4 – League context
- [ ] League settings schema + YAML/JSON import.
- [x] ~~Starter demand + replacement math~~ — removed (scarcity/replacement eliminated from pipeline).
- [x] ~~Scarcity multipliers~~ — removed from system. Rookie optimism dial remains TBD.
- [ ] Pick curve + time discount module.

### Phase 5 – Trade API + calculator
- [ ] Package adjustment logic.
- [ ] Lineup impact service (per team roster profile).
- [ ] REST endpoint + initial CLI.
- [x] Frontend calculator view (hook into Next app).

### Phase 6 – Rankings + roster dashboards
- [x] Rankings endpoint + table component.
- [ ] Roster/team view (values, surpluses, needs).
- [ ] Player detail page with trend chart + source contributions.

### Phase 7 – Advanced tooling
- [ ] Trade finder / target list.
- [ ] Contender vs rebuilder toggle adjustments.
- [ ] Historical value charts + regression alerts.

---

## 11. Open Decisions (Founder inputs required)
- Source list + initial weights (per universe).
- League scoring + lineup profile (official data entry).
- Package tax multiplier scale.
- Rookie optimism setting (baseline bump or neutral?).
- Contender vs rebuilder heuristics.
- Market mirror vs My board default mode.
- Pick discount schedule (year offsets).

---

## 12. Immediate Next Actions
1. **Repo inventory** – tag legacy modules vs to-be-rebuilt components.
2. **Source adapter spec** – codify required fields + metadata contract.
3. **Identity schema** – create tables + matching utilities.
4. **Initial data drop** – import existing CSVs (dlf_idp, etc.) into raw layer for testing pipeline.
5. **Jenkinsfile update** — stub new stages for source pull + canonical build.

Once these are in place, Kodex can start implementing adapters + canonical pipeline while I finalize league context + trade engine specs.

---

## Runtime Reality Check (Live as of 2026-03-09)
- Production frontend authority is explicitly controlled by backend env `FRONTEND_RUNTIME`.
- Default runtime is `static` for deterministic production behavior.
- Next runtime remains available (`next` / `auto`) but is no longer a silent implicit fallback.

## Current Official `/api/data` Contract
- Contract version: `2026-03-09.v1`
- Required live fields:
  - `contractVersion`
  - `generatedAt`
  - `players` (legacy map for Static runtime compatibility)
  - `playersArray` (normalized stable array)
  - `sites`
  - `maxValues`
- Contract health is validated:
  - at runtime (status exposure)
  - in CI (`scripts/validate_api_contract.py`)

## Migration Honesty
- `Dynasty Scraper.py` + `server.py` remain the live runtime backbone.
- `src/` scaffold modules are partially implemented and not yet authoritative for end-to-end production valuation runtime.
- Next frontend exists and is usable for dev, but Static runtime remains the primary production path in this phase.

