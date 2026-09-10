# Performance architecture: code truth and remaining work

Reviewed 2026-09-10 against campaign implementation and baseline main `8202c0c29b3bd2c8b970a9ad16c53732ae8e7c2a`.
This describes executable paths, including opt-in changes; it does **not** establish deployment, installed timers, production throughput or field latency.
**COMPLETE** means the bounded mechanism is implemented/tested; **PARTIAL** means coverage or activation remains; **MISSING** means the named mechanism is absent; **UNVERIFIED** marks runtime evidence not collected.
Implementation sequencing and acceptance live in `docs/PERFORMANCE_CAMPAIGN.md`; this inventory does not replace product authorization in `docs/EXECUTION_PLAN.md`.

## 1. Current architecture and deployment boundary

- Frontend: Next.js **16.3.4**, React **19.2.8**, App Router (`frontend/package.json`, `frontend/app/`). Interactive routes are client-heavy; AppShell gates private hydration and preserves public-route separation (`frontend/components/AppShell.jsx`).
- Existing frontend mechanisms are real: route chunks/dynamic imports, shared request promises, 30-second representation cache, ETag revalidation, memoized materialization and bundle checks. A new cache library or blanket Server Component rewrite is not justified merely by their availability.
- Configured HTTP topology is nginx → Python for `/api/*`, Next for pages (`deploy/nginx/chaseupside.com.conf`). Next proxy routes also support development/Next-fronted hosting; they are not automatically an extra production API hop.
- `deploy/systemd/dynasty.service.template` starts `python server.py`; `server.py` calls Uvicorn without an explicit worker count. The template sets `MemoryHigh=2560M`, `MemoryMax=3G`, `LimitNOFILE=8192:524288`. Installed settings and actual process count are **UNVERIFIED**.
- Backend rollout modes are `RISKIT_SERVING_MODE=legacy|shadow|prepared` (default legacy). Prepared startup requires a fresh successful standalone source-parity receipt and an accepted artifact; failure refuses startup rather than silently spawning an embedded producer.
- Frontend prepared projections require build-time `NEXT_PUBLIC_PREPARED_READ_MODELS=1` (`frontend/lib/read-model-policy.js`). Code migration and production activation are separate assertions.

```text
SOURCE → INGEST/NORMALIZE → COMPUTE → STORE → SERVE → FRONTEND
vendors → shared scraper cycle → canonical data_contract → private immutable generations
                                                   ↓         + prepared JSON/gzip/ETags
Sleeper facts → league overlay/scoring snapshots → league views → background pointer readers
                                                                  ↓
                         authenticated request → one captured generation → prepared bytes
```

The stable boundary is `src/serving/builder.py` → `src/serving/serialization.py` → `src/serving/artifacts.py` → `src/serving/runtime.py`.
`build_generation` uses the existing canonical engine; projections never become another valuation owner.
`record_accepted_generation` writes rank/source/temporal history only after successful fresh publication; startup and reload do not fabricate history.
`AtomicRuntime` validates a complete candidate before swapping one in-memory reference. Readers retain accepted data after corrupt, missing or rejected updates.
Prepared page handlers (`server.py::_get_prepared_read_model`) select a captured board and same-board league bundle, then return existing bytes/304. They do not load source files, call providers, recompute rankings or gzip the universe.
Selected-player detail uses an upstream player index and serializes one row; its generation check prevents joining a new detail row to an old board.

## 2. Data products and actual owners

| Product / workload | SOURCE → INGEST → COMPUTE → STORE → SERVE | Placement / state |
|---|---|---|
| Canonical board | `Dynasty Scraper.py::run` → `src/serving/producer.py::run_source_cycle` → `src/api/data_contract.py::build_api_data_contract` → `src/serving/serialization.py` → `server.py` | Mixed I/O/browser/CPU batch. **COMPLETE** shared extraction; standalone isolation is opt-in |
| Source parity | Core `SITES` policy + six KTC/IDP CSV mirrors + Dynasty Nerds, FP offense, FP IDP, conditional IDP Show → canonical acceptance guards | `scripts/run_source_producer.py`; missing anchors, half-source collapse and 75% player-retention guards retained |
| League serving | Sleeper → `src/api/league_registry.py::refresh_scoring_snapshot` + `src/api/sleeper_overlay.py::fetch_sleeper_overlay` → `src/serving/league_views.py` → per-league private artifact → `LeagueServingReader` | Scheduled mixed work; same factual scoring shares the accepted board, roster/context stays league-specific |
| News | Configured providers → `src/news/service.py` → `src/news/prepared.py` → private news artifact → `PreparedNewsReader` | Prepared mode removes provider sweeps from requests; partial/outage state and prior valid provider content remain explicit |
| BDVM inputs/projections | nflverse/local sources → `scripts/refresh_bdvm_inputs.py`, `scripts/refresh_bdvm_projections.py` → context/projection artifacts → `src/api/bdvm_api.py` | Existing standalone refresh is retained. Request auxiliary loads are `cache_only=True`; stale/missing inputs are reported |
| BDVM values/trades | Accepted contract + projection/context/actuals artifacts → `get_bdvm_values` → roster analysis → `scan_double_positive_trades` | Values are memoized; roster/trade scan remains on demand. Input prewarming is not a precomputed trade index |
| Gameplan | Current contract + league snapshot files → `src/api/gameplan.py` league bundle → bounded team/partner payloads | Generation-keyed shared computation; not a standalone producer for every answer |
| Game Day | Existing schedule/live/ROS owners → `src/ros/game_day_week.py`, `src/ros/game_day_sim.py` → `data/game_day/sims` + prediction archive → game-day APIs | Mixed live reads/local simulation; simulation coalescing and atomic cache writes added, broader product unchanged |
| Public league | Sleeper → `src/public_league/snapshot.py` → `src/public_league/snapshot_store.py` → public league API/sections | Existing separate snapshot/public identity boundary; not replaced with the private player contract |
| League comparison | Two factual Sleeper cards → `src/league_comparison/service.py::build_comparison` → historical NFL scoring → seven-day disk result | **PARTIAL**: scoring fetch precedes result-cache lookup; cold/forced work can still reach providers and historical processing |
| Historical evidence | Accepted boards → `src/api/rank_history.py`, `src/api/source_history.py`, `src/history/record.py` → JSONL/SQLite | Existing stores remain authoritative. Optional source-history backfill moved to explicit CLI maintenance |

The source service/timer/path templates under `deploy/systemd/dynasty-source-producer.*.template` share a process lease with the legacy wrapper.
The timer preserves completion-plus-two-hours cadence. A manual web refresh writes bounded `source-refresh.request` metadata; the path unit starts the same worker, which claims it under the lease. The web handler does not fork workers.
`dynasty-league-serving.*.template` supplies ten-minute refresh plus a separate manual-refresh path unit; `scripts/refresh_prepared_news.py` supplies explicit news production. None of these files proves an installed timer.
Existing BDVM service warms inputs then builds projections; its checked-in timer is Tuesday 06:10 UTC with jitter. Dedicated player-context, DLF/IDP, depth-chart, injury, game-day and model jobs retain their existing owners.
`.github/workflows/scheduled-refresh.yml` remains a separate `42 */2 * * *` source/deploy owner, with additional Dynasty Daddy, FantasyCalc, OTCFFB, Fantasy Navigator, PFK, Flock/rookies, DraftSharks/ROS, Fitzmaurice and Yahoo feeds. A VPS replacement must not disable this larger feed set.
Local process leases do not serialize a GitHub machine or deployment. `docs/ops/source-producer-ownership.md` contains source parity, bootstrap and rollback details.
The receipt proves the selected VPS source handoff; it does not prove fresh observations from every registered feed. GitHub-owned supplementary inputs remain part of the canonical dependency inventory.
The checked-in Jenkinsfile has no scheduled trigger; older Jenkins cadence claims in `docs/ops/schedules-and-cadence.md` are **STALE**, not production evidence.

## 3. User request paths and required fields

All private paths retain authentication, factual scoring checks, league isolation and private HTTP caching. The matrix describes code paths, not measured production latency.

| Page / interaction | Actual frontend → endpoint → work | Needed data / classification |
|---|---|---|
| `/` | `frontend/app/page.jsx` + AppShell/dashboard consumers → existing startup/private data and independent panels | Dashboard summaries/context; **MOVE UPSTREAM** reusable panel aggregates; remaining universal-contract dependency is **PARTIAL** |
| `/rankings` | page + `useDynastyData({readModel:"rankings"})` → `/api/read-models/rankings` when enabled → prepared league bundle | Canonical row values, order, filters, tiers, source diagnostics/export fields; **KEEP IN REQUEST** lookup/304 and browser filtering |
| `/trade` | page + `useDynastyData({readModel:"trade"})` → `/api/read-models/trade/context`; engine-specific actions remain separate | Canonical assets, picks, roster/settings and evaluation inputs; **KEEP** bounded selection/math, **WORKER** only proven heavy searches |
| Explicit ranking settings | `useDynastyData` override flow → `/api/rankings/overrides` → canonical engine/delta, keyed response cache | User-specific source weights/TEP/league adjustment; **CACHE/MEMOIZE** by full inputs; still on demand, not silently defaulted |
| `/draft` | `useApp()` → existing contract plus draft-specific APIs/polling | Pick board, assets, owners, current picks; **CACHE/MEMOIZE** factual draft IDs/picks; live polling is a distinct freshness requirement |
| `/waivers`, `/rosters` | `useApp()` → existing global data plus roster/waiver intelligence APIs | Roster membership, eligibility, scoring, opportunity/decision facts; **MOVE UPSTREAM** shared league/team derivatives after field audit |
| `/bdvm` | BDVM endpoints → local input artifacts + value LRU → roster/trade calculation | Projection provenance, value cards and roster analysis; **CACHE/MEMOIZE** cold values; no provider fallback hidden in auxiliary reads |
| `/league` | `frontend/app/league/page.jsx` → public league snapshot/section APIs | Public league summaries/history, not private universal player data; this separation is **ALREADY SOLVED** |
| Player popup/detail | `frontend/components/PlayerPopup.jsx` + `frontend/components/usePreparedPlayerDetail.js` → generation-bound `/api/read-models/players/{id}`; separate history endpoints | Selected complete canonical row/provenance; **KEEP** indexed lookup, **CACHE/MEMOIZE** repeated historical reads |
| Global search on BDVM/Game Day/comparison | AppShell intent catalog → `/api/read-models/players/catalog` only after authenticated intent when enabled | Search identity/minimal rows; **REMOVE** unconditional private universe hydration on these routes |
| `/league-comparison` | page fetch → `build_comparison` → factual cards, disk cache, historical stats/scoring | Comparative methodology/result; **MOVE UPSTREAM** baseline products, **WORKER** explicit forced rebuild |
| `/game-day` / matchup | Game Day components/APIs → current snapshots and league/week simulation cache | Current week/live state, roster matchup and simulation; **CACHE/MEMOIZE** exact inputs; maintain honest stale/unavailable states |

The new Next catch-all `frontend/app/api/read-models/[...path]/route.js` streams upstream responses; production nginx may bypass it.
Default scoring must not be confused with explicit overrides. Missing values are not zero, a stale roster is not current, and a smaller projection must preserve desktop/mobile sorting, filtering, export and detail semantics.

## 4. Material cache inventory

“SF” means single-flight; process-local SF does not coordinate separate workers. No TTL below authorizes silently serving a different scoring or league identity.

| Owner / cached value | Key, generation and TTL | Bounds / SF / invalidation / failure |
|---|---|---|
| `src/serving/artifacts.py`, `src/serving/runtime.py`: canonical prepared views | Asset/key + content/manifest generation; pointer token changes on observation; background reload, not request TTL | One accepted runtime pointer; OS publication lock, atomic selection, checksum/schema validation, LKG on failure. Disk generation retention is **MISSING** as an integrated policy |
| `src/serving/league_views.py`: rankings/trade/catalog bundles | Logical board + league + factual scoring/overlay/config/code inputs; reader polls ~2s, roster age ceiling 30m | One current bundle per compatible active league; coordinator process lease; changed-board bundles cannot cross over. Stale context becomes unavailable rather than current |
| `src/news/prepared.py`: accepted news | Artifact generation; attempt/success timestamps; stale after service freshness window | One reader snapshot; serialized reload; old valid content retained after bad update. Projection filters are bounded local work; no request providers |
| `server.py`: legacy overlay JSON/gzip/ETag | Stable `(kind, league, view)` slot; board ETag + overlay version inside slot | Max 32; per-key async encode lock, lazy lineup preparation only on miss. New version replaces old slot; failed encode is not cached |
| `server.py`: ranking override response | Full normalized settings + board/league/context generation and response view | Max 16; per-key async lock; fresh board clears entries; explicit custom calculation still pays first miss |
| `frontend/lib/dynasty-data.js`: fetched/materialized base | League + representation; 30s; browser revalidation; logout/league epoch invalidation | Base map max 8; active promises deduplicate fetches. Final override memo is one slot keyed by body/league/representation/base; failed merge is not success-cached |
| `src/api/sleeper_overlay.py`: full/teams overlay | Sleeper league ID; full fresh 15m, stale ceiling 30m; teams 5m | Full overlay SF/background stale refresh; dictionaries lack numeric league cap. Teams-only failure falls back to cached teams; TTL-only entries need factual identity discipline |
| Same owner: live draft IDs/picks | League ID → draft ID 60s; draft ID → full pick list 2s, client cursor sliced afterward | Separate caches avoid poisoning roster freshness; per-draft locking on picks; failed fetch does not replace good picks |
| `src/api/bdvm_api.py`: final values | Contract identity/generatedAt, league, params, surplus mode, exact scoring/roster config, projection/context/schedule/actuals/event generations | LRU 4; SF; failed actuals are not pinned into a degraded value result. Other missing evidence is explicitly reported |
| Same owner: auxiliary maps | Context file generation; season/schedule file generation; actuals season/day/exact card + weekly/PBP artifact identities | Each LRU 16; SF. Missing→present and replacement invalidate; TTL-expired local evidence may be served as stale. Reads remain cache-only |
| `src/api/gameplan.py`: league bundle/team answers | League + source stamp (contract/snapshot versions); team/partner added downstream | One bundle per league, team LRU 64; bundle SF; new stamp replaces bundle/clears team slots. Scoring/reception-fit dictionaries still have separate process-cache lifecycle |
| `src/ros/game_day_sim.py`: simulation JSON | League/season/week + detailed simulation-input fingerprint; 2h safety TTL | One disk file per partition, not a global disk cap; process SF; unique atomic temp files prevent concurrent corruption. Invalid/stale cache triggers recompute; failures do not publish partial output |
| `src/league_comparison/service.py`: comparison | League IDs/card hashes, seasons, config/methodology version; 7 days | Disk cache; no equivalent whole-build SF proven. Card resolution happens before hit lookup; cold/refresh work remains expensive |
| Existing source/config/history caches | `src/api/data_contract.py`, `src/api/league_registry.py`, `src/api/rank_history.py`, `src/nfl_data/cache.py` | Mixed mtime/process/TTL owners; not all share generation semantics. These are explicit canonical no-op blockers, not evidence that the whole system has coherent SWR |

The added BDVM keys preserve canonical scoring semantics; file identities are sampled once before asset loops. Successful concurrent misses build once; exceptions release SF state for retry.
Existing request threads reduce event-loop blocking but do not prove isolation from Python GIL, CPU, RSS or file-descriptor contention. Batch worker resource controls and load evidence are still necessary.

## 5. Solved mechanisms, gaps and consolidated priorities

**Already solved:** prepared full/runtime/array/startup/compact bytes, ETags/gzip, source rejection guards, BDVM refresh ownership/cache-only reads, public/private league separation, browser deduplication and route splitting. Preserve these owners.
**Implemented in this campaign:** coherent private publication/reload, source lease/receipt/manual queue, rankings/trade/catalog projections, selected-player lookup, cache correctness/SF repairs, prepared news and bounded telemetry.
**Partial:** frontend/backend rollout, nonmigrated page families, heavyweight explicit computations and full cache lifecycle consolidation. A helper alone does not close a route migration.
**Canonical dependency skipping remains false:** the recorded manifest covers raw content, 25 registered source entries, config/models, code, scoring snapshots, current history and runtime settings, but live/cached league context, clocks, mutable history and cached config remain unresolved (`docs/ops/serving-input-manifests.md`).
`src/serving/league_views.py::refresh_league_serving` calls the scoped coordinator: it skips preparation only after matching a **complete** manifest to a validated accepted artifact. Observation-only changes update pointer freshness without a new value calculation/history point; reload restores both league and overlay observation timestamps.
**Not established as a current bottleneck:** database vendor, number of frontend libraries, absence of Redis/GraphQL or absence of a commercial orchestrator. Historical improvements are not current field SLOs.

Ratings are engineering estimates, not measured speed multipliers. Columns: **G** gain, **E** effort, **C** infrastructure cost, **R** architectural risk, **M** maintenance burden, **F** confidence; each 1–10, with higher G/F favorable and higher E/C/R/M costly.

| # / recommendation and falsifiable acceptance | Problem type / category | G | E | C | R | M | F |
|---|---|---:|---:|---:|---:|---:|---:|
| 1. Close same-context browser/API/refresh baselines and telemetry rollout: every result records useful-state, bytes, work counts and deployment/data identity | Measurement/maintainability — **MUST DO** | 8 | 3 | 1 | 2 | 2 | 10 |
| 2. Activate the validated standalone producer/prepared reader boundary after source parity: ordinary migrated requests make zero provider/build calls, including refresh overlap | Cold/CPU/provider — **MUST DO** | 9 | 5 | 2 | 5 | 3 | 9 |
| 3. Complete rankings/trade/catalog/detail parity and gated frontend rollout: no global-contract fetch on migrated default routes; measured wire reduction target ≥40% without field loss | Payload/frontend — **MUST DO** | 9 | 5 | 1 | 4 | 3 | 8 |
| 4. Materialize recurring league comparison baselines; explicit rebuild becomes observable background work: warm read performs no provider or historical scoring | Cold/I/O/provider — **SHOULD DO** | 8 | 5 | 2 | 4 | 3 | 8 |
| 5. Exercise complete league input reuse through the actual refresh caller: repeated unchanged facts invoke zero lineup/projection builds; changed roster/card/code invalidates exactly affected bundles | CPU/repeated work — **SHOULD DO** | 6 | 3 | 1 | 3 | 2 | 9 |
| 6. Migrate remaining dashboard/draft/waiver/roster consumers through the same projection spine only after field/byte evidence: reduce each measured payload and preserve cross-page semantics | Payload/maintainability — **SHOULD DO** | 7 | 7 | 1 | 5 | 4 | 7 |
| 7. Measure BDVM cold value and roster/trade scan separately; precompute recurring league answers/candidate indexes only where first-miss CPU exceeds useful-state budget | Cold/CPU — **SHOULD DO** | 7 | 6 | 2 | 5 | 4 | 7 |
| 8. Keep tiny custom evaluation interactive; move proven heavy override/finder jobs to bounded process execution with request identity, queued/progress/failed states | CPU/on-demand — **SITUATIONAL** | 7 | 7 | 3 | 6 | 5 | 6 |
| 9. Finish cache/resource lifecycle controls: bounded league maps, artifact retention/LKG protection, worker RSS/FD/concurrency budgets; demonstrate a sustained refresh load without growth | Memory/I/O/reliability — **SHOULD DO** | 6 | 5 | 2 | 4 | 3 | 8 |
| 10. Close canonical manifest unknowns by passing factual context and explicit clock/history snapshots through existing owners before enabling skip; identical complete inputs must build zero times | Batch CPU/architecture — **SHOULD DO** | 6 | 8 | 2 | 7 | 4 | 7 |

If only **five** changes are funded, execute 1–5 together around the existing serving spine; they cover visibility, process isolation, the first route pair and two expensive shared computations.
With **ten**, add 6–10 in measured priority order. Do not split each page/cache into a separate architecture or redo the already fixed transport/valuation mechanisms.
Near-best-in-class remains the same shape: ingestion and prepared computation run continuously; coherent indexed answers wait behind a thin authenticated serving layer; explicit unusual work gets bounded jobs and honest progress.

| Advanced choice / evidence required | Category | G | E | C | R | M | F |
|---|---|---:|---:|---:|---:|---:|---:|
| Shared Redis/queue only when multiple serving processes need shared admission/cache state or measured repeated misses exceed local coordination | **SITUATIONAL** | 6 | 6 | 4 | 5 | 5 | 6 |
| PostgreSQL only for measured SQLite writer contention, cross-host transactions or operational requirements; retain cheap immutable read artifacts | **SITUATIONAL** | 5 | 8 | 5 | 7 | 6 | 5 |
| Parquet + DuckDB for measured large historical scans before heavier OLAP; API still serves prepared results | **SITUATIONAL** | 7 | 6 | 2 | 4 | 3 | 7 |
| SSE for genuinely useful job/live updates when polling cost/latency is measured; not a replacement for precomputed answers | **NICE TO HAVE** | 3 | 4 | 2 | 3 | 3 | 6 |
| Dagster/Prefect/Airflow only after simple dependency metadata cannot manage retries/backfills/ownership reliably | **SITUATIONAL** | 4 | 8 | 5 | 6 | 7 | 5 |
| Kubernetes/Kafka/microservice decomposition or extra Uvicorn workers as an unmeasured first fix | **DO NOT DO** | 2 | 9 | 8 | 8 | 9 | 9 |

## 6. Evidence and acceptance boundary

Use `docs/GLOBAL_PERFORMANCE_STANDARD.md`: warm useful state ≤1s, normal p95 ≤2s, supported cold ≤3s, honest useful/unavailable state by 5s; immediate interaction acknowledgement and preserved loaded-state continuity.
Research LCP/INP/CLS and API millisecond targets remain hypotheses until the current environment is measured. Do not rewrite older p95 or missing pre-feature baselines as this campaign's before result.
`frontend/scripts/measure-route-baselines.mjs`, `scripts/measure_prepared_payloads.py`, bundle checks and bounded `src/api/telemetry.py`/`frontend/components/WebVitalsReporter.jsx` provide the measurement path; telemetry series are capped at 512 and exclude private content.
Structural acceptance includes zero providers/builds on prepared requests, one builder under concurrent misses, stable generation on reobservation, LKG after invalid publication, factual scoring mismatch refusal and exact canonical row/detail parity.
Relevant regressions: `tests/serving/test_serving_pipeline.py`, `tests/serving/test_artifacts.py`, `tests/serving/test_runtime.py`, `tests/serving/test_producer.py`, `tests/serving/test_source_requests.py`, `tests/serving/test_input_manifest.py`, `tests/serving/test_coordinator.py`; `tests/bdvm/test_cache_generations.py`, `tests/api/test_gameplan_singleflight.py`, `tests/game_day/test_game_day_sim_cache.py`.
Local fixture tests verify mechanisms, not installed Linux units, authenticated production waterfalls, sustained RSS/FD ceilings or field p75/p95. Parent campaign evidence must record BEFORE → CHANGE → AFTER → PASS/FAIL under the same inputs/environment.
Consolidate with `docs/performance-optimization.md` and `docs/BACKLOG_REPLAN_2026-09-10.md`: retain fixed compact/overlay transport, canonical engines, completed public-page isolation and shared primitives; do not revive retired valuation paths, duplicate source owners or unrelated unmerged systems.

Legacy mode skips new board projections and league readers until explicitly opted in. The first source cutover requires a fresh matching receipt; later restarts use a durable validated ownership proof and can serve stale valid canonical data. See the campaign report for current local results and failed rollout targets.
