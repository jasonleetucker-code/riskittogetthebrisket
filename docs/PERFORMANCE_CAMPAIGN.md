# Performance modernization campaign

Owner-authorized 2026-09-10 after the source-grounded audit. Baseline main:
`8202c0c29b3bd2c8b970a9ad16c53732ae8e7c2a`. Rankings and trade migrate first.
Branch: `codex/performance-serving`. Local implementation candidate; no PR,
merge, deployed flag, installed unit or production acceptance is claimed.

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

## Contract and status

Preserve canonical values, rank/order/filter/export parity, factual scoring
identity, league separation, source coverage, missing versus zero, stale versus
current, and public/private boundaries. A read model is a serving projection,
never another valuation owner. Prepared default reads retrieve accepted bytes;
explicit user overrides still use the existing canonical calculation/cache.

**STATUS: IMPLEMENTED CANDIDATE / ROLLOUT GATED.** The shared serving boundary and
first route migrations are implemented and locally exercised. This is not a
claim that every page or the full performance program is complete. The slowed
mobile useful-state target failed; production activation and sustained load
remain unverified. The canonical builder deliberately does not skip work on an
incomplete input manifest.

See [architecture and ranked findings](PERFORMANCE_ARCHITECTURE.md),
[source ownership and rollout](ops/source-producer-ownership.md),
[input dependency boundaries](ops/serving-input-manifests.md), and the
[exact changed-file manifest](evidence/performance-change-manifest.txt).

## Combined implementation and acceptance

| Phase / objective | Implementation and common paths | Local acceptance / state |
|---|---|---|
| 0: Observe the real critical path | `src/api/telemetry.py`, `server.py`, Next telemetry bridge, `WebVitalsReporter`, route baseline harness and replay lab | COMPLETE instrumentation and reproducible local mechanisms; PARTIAL field evidence. Bounded 512-series metrics, validated trace/request IDs, bytes, cache/provider/work spans, deployment/generation identities; privacy and streaming tests pass |
| 1: Remove repeated work | Legacy overlay preparation moved inside serialization-cache miss; draft duplicate contract reads removed; Game Day retains last good state; generation/scoring-aware BDVM caches and gameplan/simulation single-flight | COMPLETE selected defects. Repeated overlay hits/304 do not stamp lineups; same-timestamp context changes invalidate; same-input concurrent cache misses build once; failures retry rather than poison caches |
| 2: Separate collection from serving | Existing scraper cycle extracted to `src/serving/producer.py`; CLI, source/league leases and bounded refresh markers; source receipt/proof, accepted-generation publisher and background readers; prepared news producer | COMPLETE local paths, PARTIAL cutover. Rejected candidates retain last good data; reader reloads without web restart; queued admin refresh invokes no provider; lease/status/source policy tests pass. Installed ownership and production resource limits remain unverified |
| 3: Prepare coherent answers | `builder.py`, `serialization.py`, `runtime.py`, `projections.py`, `league_views.py`; all legacy views plus rankings/trade/catalog; indexed selected-player detail | COMPLETE selected products. All eight projections validate against one canonical generation; cross-league factual scoring checks, stale roster refusal, old-reader/new-publication coherence and generation-pinned details pass |
| 4: Migrate the frontend/API boundary | Shared read-model bridge; `useDynastyData` mode; rankings/trade/AppShell; first-intent catalog; full detail on popup/source audit; bounded generation recovery | COMPLETE first route pair and catalog/detail code; PARTIAL rollout/performance acceptance. Desktop/mobile filters, source audit, popup, trade selection and exact CSV parity pass in the synthetic browser lab; no global contract fetch on migrated defaults. Slowed mobile route target FAIL |
| 5: Reuse unchanged dependency products | Asset registry, conservative canonical manifest, scoped league manifest/coordinator invoked by the actual refresh owner | PARTIAL by design. Identical complete league facts reobserve the same generation with zero new lineup builds; changed roster/config invalidates. Canonical manifest remains `complete: false` for unresolved implicit inputs, so canonical no-op is disabled |
| 6: Conditional infrastructure | Existing FastAPI/Next/systemd and private immutable files retained | DEFERRED. No measured requirement establishes Redis, PostgreSQL, a commercial orchestrator, another Uvicorn worker or a distributed queue as the necessary next fix |

## Before / change / after / result

Each comparison keeps the answer and input fixed. A fixture measurement is not
production latency, and Python parse timing is not browser parse timing.

| Hypothesis / before | Change | After / verdict |
|---|---|---|
| Rankings/trade should cut gzipped bytes at least 40% versus the array contract | Shared board projection; retain row/filter/export fields, defer full provenance to pinned details | Recorded healthy 1,093-player input: array 792,857 bytes vs rankings/trade 406,170 bytes each, **48.77% reduction: PASS**. Canonical projection parity PASS. Catalog 138,998 bytes, 82.47% smaller |
| Repeat legacy overlay requests should not redo an unchanged lineup solve, including 304 | Delay stamping until generation/context-keyed encode miss | Pre-audit isolated handler probe: two requests, two solves. Regression: repeated hit/304 uses one solve; changed context invokes the next solve: **PASS** |
| Concurrent equal cache misses should share one calculation and allow failed work to retry | Bounded, complete cache identities and single-flight in existing BDVM/gameplan/simulation owners | Before: incomplete dependency/league identities and duplicated work found by adversarial probes. After: all affected input-change, league-isolation, one-builder and retry regressions pass: **PASS structural**, no claimed production latency gain |
| New source generation must become visible without a restart or a partially replaced contract | Validate all bytes/indexes off-request, atomically publish/select one generation | Actual lifespan test observes generation replacement without restart; rejected/corrupt candidates preserve accepted data and in-flight captured reference: **PASS** |
| Prepared ordinary reads must make zero external-provider or canonical-build calls | Worker-prepared canonical/league/news products and pure memory reads | Actual prepared handler tests reject provider/lineup/build invocation; queued refresh returns 202 without a background web task: **PASS** |
| Unchanged league facts should perform zero repeated lineup builds | Complete scoped input manifest and `prepare_or_reobserve` in real refresh caller | First refresh solves once; unchanged refresh reobserves same generation/files; changed roster solves again: **PASS**. Canonical skip remains explicitly disabled |
| Smaller boards should improve normal route-to-useful time without changing behavior | Same flag-on build consumes full-shaped vs projected 120-player fixture | Three cold/three warm runs: desktop rankings p95 825/520 -> 643/418 ms, trade 606/265 -> 351/192; mobile rankings 866/434 -> 601/368, trade 615/252 -> 362/191. **PASS in this bounded lab**, not statistical field p95 |
| Rankings/trade should meet existing useful-state budgets under slowed mobile conditions | Same real Next/browser path, 4x CPU, 150 ms latency, 1.6 Mbps download | **FAIL**. Multi-second useful-state latency and rankings ten-second misses remain. Preserve the strict markers/budgets. Full details, later diagnostic comparisons and limitations are in the browser lab evidence |

The payload report is [machine-readable](evidence/performance-payloads-2026-09-10.json).
It uses `exports/archive/dynasty_export_20260910_164414.zip`, raw SHA256
`9133cbee209b6e8b220f38f780871a033d94a8ea7e0f5d167cb0605378439d32`.
The original latest checkout export was partial/missing a required source; it
was correctly rejected rather than used as a healthy baseline. Replay is offline,
seeds factual league context and disables ledger rank-change notes for the lab.
It does not publish source receipts, history or private artifacts to Git.

[Browser lab instructions](../tests/e2e/performance-lab/README.md) and
[evidence](../tests/e2e/performance-lab/evidence.json) document the synthetic
120-player population, full-shaped/prepared comparison, installed Chrome,
production Next build, actual proxy routes, visible useful-state predicates,
resource sizes and failures. The Next lab bridge decodes upstream gzip; its
browser bytes must not be represented as production nginx wire bytes. Unreported
Web Vitals remain null. No final field LCP/INP/CLS claim is made.

## Validation record

- Integrated serving/lifecycle/API/news selection: **522 passed, 6 skipped,
  5 subtests passed** before the final queue/status and legacy opt-out fixes.
- Subsequent integrated selection: **371 passed, 5 skipped, one failure** from
  a transient Windows `current.json` sharing error. The bounded pointer-read
  retry fixes that issue; affected artifacts/pipeline/startup/array/league
  selection subsequently **94 passed, 5 skipped**. Platform skips are retained.
- Static frontend/reachability checks: **79 passed** after correcting the
  test scanner's Windows relative-path separator and caching its pure AST scan.
  No feature gate or product status was relaxed. FAAB/failure attribution:
  **43 passed**.
- Agent cache suite: **508 passed** plus UTF-8 rerun of the Windows encoding
  failure. News and source/manifest/ownership selections also passed; these
  overlap the integrated counts and must not be summed as unique coverage.
- Frontend before final row-measurement fix: **174 files / 2,512 tests passed**,
  production flag-on build passed and **14/14** bundle gates passed. The browser
  evidence records final focused/full reruns and nine desktop/mobile cases.
- Required Python formatter and repository lint: **GREEN**, Ruff **0.6.9**,
  **1,462** files checked. Final checks and integration reconciliation are
  recorded below when run.
- A broad backend run was interrupted after exposing the Windows static-scanner
  defect. It was not a completed full-suite pass. No claim is made that all
  roughly 11,000 collected backend tests ran for this campaign.

Coverage includes canonical field parity, factual scoring/league isolation,
missing/stale states, hot reload, corrupted publication, source guards, source
ownership renewal, queue admission, error recovery, single-flight and cache
invalidation. Synthetic tests cannot establish provider availability or actual
Linux scheduling.

## Rollout, freshness, cost and rollback

`RISKIT_SERVING_MODE=legacy` remains the default. It keeps the existing five
views and does not build the three new projections or start league readers.
`shadow` prepares/publishes the new products while retaining legacy ownership.
`prepared` requires intact verified source ownership and an accepted canonical
artifact; it loads readers and omits embedded source scheduling/backfill.
`NEXT_PUBLIC_PREPARED_READ_MODELS=1` is a separate build-time frontend opt-in.

1. Deploy code with flags unchanged, then validate sampled privacy-safe
   telemetry and current authenticated baselines on the deployed artifact.
2. Use shadow/offline parity to validate actual full/default/overridden boards,
   complete source coverage, active factual scoring cards and league identities.
3. Follow the source ownership runbook: install and verify the source, league
   and news workers/path units; establish a healthy receipt and durable proof.
   Keep the separate GitHub feed/deploy owner intact. Measure RSS/FD/disk use.
4. Enable prepared backend reads, verify reload/refresh overlap, auth, 304,
   stale/unavailable behavior and manual source/league queue consumption.
5. Enable the frontend build flag only after browser parity and the declared
   rollout performance gates pass for real authenticated desktop/mobile flows.
   The failed slowed-mobile target remains an acceptance item, not an exemption.

Freshness is carried separately from value identity: actual source timestamps
are never changed to web load time. Stale valid canonical answers remain usable;
expired league rosters become explicitly unavailable. News retains valid items
through provider errors with truthful attempt/success/status metadata. Failed
publication or reload keeps last good data and exposes the error. Worker leases
and bounded private status/queue files avoid duplicate local owners.

Infrastructure additions are private disk artifacts and standalone systemd
processes on the existing host; no new paid service is required. This shifts
CPU/network work rather than proving lower total resource use. Disk retention
for immutable generations is not integrated yet, so production sizing/retention
and a sustained refresh-load test remain required. Do not increase web workers
until process-local caches and resource budgets are measured.

For frontend rollback, rebuild without its opt-in flag. For backend rollback,
stop standalone source timer/path/service ownership, return to legacy mode and
restart, preserving accepted artifacts. Check freshness and alert wiring. Never
promote a rejected raw export or intentionally run two unrestricted publishers.

## Remaining acceptance and next action

UNRESOLVED: slowed-mobile useful-state budget; real authenticated production
waterfalls/field Web Vitals; installed producer/source-parity evidence and
cutover; sustained RSS/FD/disk bounds and artifact retention; complete canonical
input manifest. Nonmigrated dashboard/draft/waiver/roster and explicit heavy
comparison/finder computations remain follow-on work ranked in the architecture
report, not silently declared provider-free.

Next dependency-ready action: validate this candidate through normal protected
integration, then collect deployed shadow/source/resource evidence and resolve
mobile rendering cost before activating the read-model frontend flag. No
production credentials, schedules, values, launch denominator or public data
were changed by the local implementation.

## Target experience

Continuous standalone ingestion should normalize sources through the existing
canonical engines, then publish validated immutable ranking and league products
with explicit input generations, scoring identity and freshness. A small
background reader atomically loads those products into the existing FastAPI
process; authenticated APIs serve indexed, precompressed answers through thin
Next bridges. Rankings and trade load only their working data, and fetch full
player detail on intent. Dependency-aware jobs share unchanged work, while
unusual expensive requests receive bounded job execution and honest progress.
This makes the usual interaction a lookup and render while the site's ongoing
computation stays behind the serving boundary.
