# Performance modernization campaign

Owner-authorized 2026-09-10 after the source-grounded audit. Baseline main:
`8202c0c29b3bd2c8b970a9ad16c53732ae8e7c2a`. Rankings and trade migrate first.
Branch: `codex/performance-serving`. Local implementation candidate; no PR,
merge to main, deployed flag, installed unit or production acceptance is claimed.

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

## Contract and status

The Phase 1 record below is retained as historical evidence. The Phase 2
continuation at the end supersedes its retention and acceptance status; fixed
input payload comparisons remain valid and are not relabeled as new timings.

Preserve canonical values, rank/order/filter/export parity, factual scoring
identity, league separation, source coverage, missing versus zero, stale versus
current, and public/private boundaries. A read model is a serving projection,
never another valuation owner. Prepared default reads retrieve accepted bytes;
explicit user overrides still use the existing canonical calculation/cache.

**PHASE 2 DECISION: B — NOT READY.** The shared serving boundary and
first route migrations are implemented and locally exercised. This is not a
claim that every page or the full performance program is complete. The slowed
mobile useful-state target failed; the completed hour-long local run failed
resource, latency and sampling acceptance. Production activation remains
unverified. The canonical builder deliberately does not skip work on an
incomplete input manifest.

See [architecture and ranked findings](PERFORMANCE_ARCHITECTURE.md),
[source ownership and rollout](ops/source-producer-ownership.md),
[input dependency boundaries](ops/serving-input-manifests.md), and the
[Phase 1 changed-file manifest](evidence/performance-change-manifest.txt) and
[Phase 2 changed-file manifest](evidence/performance-phase2-change-manifest.txt).

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

- **Final reconciled backend selection: 533 passed, 5 skipped**, 72.08 seconds.
  This includes serving artifacts/runtime/producer/manifest/status, all news,
  affected BDVM/gameplan/simulation caches, telemetry, source guards, array,
  league routing, overrides, league adjustment, private auth and startup.
  It supersedes the earlier resolved failures below; counts overlap.
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
  production flag-on build passed and **14/14** bundle gates passed on that earlier build. The browser
  evidence records final focused/full reruns and nine desktop/mobile cases.
- Required Python formatter and repository lint: **GREEN**, Ruff **0.6.9**,
  **1,462** files checked. Final checks and integration reconciliation are
  recorded below.
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

Phase 1 infrastructure assessment: additions are private disk artifacts and standalone systemd
processes on the existing host; no new paid service is required. This shifts
CPU/network work rather than proving lower total resource use. Disk retention
for immutable generations was not integrated at that checkpoint, so production sizing/retention
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


## Current-main reconciliation

- Validated implementation before reconciliation: `6424cf5af`, based on
  `8202c0c29b3bd2c8b970a9ad16c53732ae8e7c2a`.
- Fetched main: `2c3b74cf8`. Intervening commits: `7e1289470` (GitHub Actions
  Sharp smoke), `aacd980ff` (IDP Show Fetch production evidence), `b5fedaad6`
  (GitHub Actions freshness), `53b87921a` (GitHub Actions source refresh),
  `2c3b74cf8` (GitHub Actions Hill refit evidence).
- Classification: **RELEVANT_BASE_MOVE**. There are 72 changed data/evidence
  paths, including source CSVs, raw exports, cached Sleeper/ROS inputs and the
  Hill model registry. The Hill champion remains version 2; the new entries
  are challenger/rejected evidence, but these are still builder/manifest inputs.
  The change is not called benign merely because automation authored it.
- Reconciled locally without conflict as `65a3c3aa9539bd3aafea6acaa4f48c53348a8cdd`.
  No product source, dependency, workflow or tests changed upstream. Serving,
  news/cache/API checks and the fixed-input payload gate are rerun against the
  composed tree. Synthetic frontend facts remain synthetic and independent of
  those changed source CSVs.
- Final frontend runtime: official Node 20.20.2, downloaded from nodejs.org and
  verified SHA256 `dc3700fdd57a63eedb8fd7e3c7baaa32e6a740a1b904167ff4204bc68ed8bf77`.
  The integrated Node 20 suite passed **174 files / 2,513 tests** in 114.05 seconds.
  Earlier browser timing evidence remains explicitly Node 24; it is not relabeled.
- The first telemetry-wired Node 20 build compiled, but its bundle gate failed
  for `/more` (11.0 KB over a 10 KB limit). A new root client entry caused the
  styled-jsx runtime to enter that page's chunk. The reporter now mounts once
  inside the existing `AppShellWrapper` client boundary, preserving document
  metrics while avoiding that extra root entry. Budgets remain unchanged.


## Final integrated evidence

- Final Node 20 flag-on build with telemetry in the existing shell: **PASS**;
  **14/14 unchanged bundle budgets PASS**. `/more` is 2.9 KB, rankings 60.9 KB,
  trade 65.5 KB. Build warnings concern the existing middleware convention,
  themeColor placement, Next Edge-runtime diagnostics and absent local public
  backend; no compiler failure occurred.
- Final affected shell/privacy tests after the mount adjustment: **46 passed**.
- Final Node 20 / Chrome 152 browser smoke: **9/9 cases PASS**, zero page errors
  and zero forbidden global-contract reads. **27/27 telemetry POSTs succeeded**,
  with the six allowed fields, finite nonnegative values, fixed route templates
  and no Referer. TTFB/FCP/LCP were observed; INP/CLS were not observed. This
  smoke adds correctness evidence, not a new performance comparison. See
  [the supplemental artifact](evidence/performance-browser-node20-2026-09-10.json).
- Reconciled source-data payload replay: array **790,946** gzip bytes versus
  rankings/trade **405,727** each, **48.70% reduction**, 40% gate **PASS**;
  catalog **138,977** bytes, **82.43% reduction**. All 1,093 canonical rows
  validate. Both the original and [reconciled report](evidence/performance-payloads-reconciled-2026-09-10.json)
  remain available; no change in Python wall time is claimed as a speed gain.
- The healthy newer checkout exposed legacy tests installing only individual
  globals after startup had published a coherent generation. Handler suites
  now explicitly opt into isolated startup and install their own legacy
  representation; the independent real startup/recovery/lifecycle tests retain
  production behavior. Added unauthenticated checks for all new read-model
  routes and admin performance diagnostics. No assertions were weakened.
- The legacy override path again accepts absent source metadata, as the old
  builder boundary did; missing metadata stays absent instead of raising while
  copying it. Removed exactly one stale coercion-baseline allowance for the
  old news rank helper; no new allowance or budget increase was added.
- Independent review found no remaining substantive defect in generation
  publication/parity, factual league binding, queued refresh admission,
  ownership renewal, last-good restart behavior, status recovery, legacy opt-out
  or bounded Windows pointer retries. This does not certify the unresolved
  production and slowed-mobile acceptance items.


Final handoff: **IMPLEMENTED CANDIDATE / ROLLOUT GATED** on
`codex/performance-serving`; no PR, push, merge to main or deployment performed.
The final backend selection, Node 20 suite/build/bundles, browser smoke,
formatter, decision-coercion ratchet and whitespace checks pass locally.
The campaign work claim remains open for the explicit rollout acceptance gaps.
UNRESOLVED: mobile useful-state target; deployed source ownership/cutover and
field performance; sustained resource/retention evidence; complete canonical
input manifest. Next action remains protected integration and deployed shadow
validation, followed by mobile remediation before flag activation.

## Phase 2 continuation — 2026-09-11 UTC

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

### 1. Reconciliation

Started from clean `5445a62dc886774e3972814d5bb44adfad89ccaf` on
`codex/performance-serving`. The active saved main checkout completed
`git pull --ff-only origin main`; the candidate fetched main. Both confirmed
`2c3b74cf89ea507c3d74855ccb09551cba671f38`, already incorporated by Phase 1.
There were **zero intervening commits and zero changed paths** at execution
start, so no irrelevant, benign evidence/data, relevant input-generation,
product-code or architecture changes required a new classification/reconciliation.
The earlier relevant-input reconciliation above remains recorded. Fixed-input
payload comparisons are retained; no source-data movement is silently labeled
benign because automation authored it.

The pre-soak fetch subsequently found `9a24f7f67c803c2524cc5292f0385092bb88a06b`
(`chore(idpshow): automated refresh 2026-09-11T00:32:13Z`). Its entire diff is
observation timestamps in `data/scrape_state/idpShow_last_status.json`,
`idpShow_last_success`, `idpShowCombined_last_status.json` and
`idpShowCombined_last_success`; values, rows and source code did not change.
Classification: **relevant input-generation movement / RELEVANT_BASE_MOVE**,
because `input_manifest.capture_canonical_inputs` captures that tree and
`data_contract._build_source_timestamps` consumes successful-observation stamps.
It reconciled cleanly as `211725c5d38bab7153af1236d3468d4dff3e52f3`. Affected
manifest/source-freshness checks: **57 passed**, 5.39s. Fixed private replay,
frontend/build and unrelated backend evidence are retained without repetition.

### 2–4. Mobile attribution, changes and before/after verdict

The existing browser lab now supports opt-in module/hydration, auth/settings,
fetch admission/join/cache, headers/body completion, JSON parse, materialization,
state publication, React Profiler and table-width marks. Both build-time and
browser opt-in are required; the bounded enum/numeric collector stays local and
contains no identities, URLs, rows, settings or private content. Ordinary builds
retain `response.json()` and no Profiler wrapper. Chrome trace/resource/navigation
measurements remain distinct from overlapping React measurements.

Supported Node 20.20.2 production builds used the unchanged useful-state
predicate, 4× CPU, 150 ms latency and 1.6 Mbps download. The existing synthetic
120-player board and private healthy 1,093-player replay ran cold and warm
separately. Initial contaminated diagnostics were discarded; final alternating
A/B/B/A acceptance ran without other builds/tests and with diagnostics off.
The private acceptance transport used SHA-verified producer gzip bytes; an
earlier diagnostic recompression is labeled separately.

**Observed attribution is partial, not a complete CPU accounting.** Private
rankings maximum React render durations were 2.573s cold / 1.413s warm. First
table width reads at 18.851s / 12.049s are navigation timestamps, **not commit
durations**; the width callback itself took about 6ms / 1ms. Commit timestamp to
Profiler callback spanned about 1.77s, including DOM/effects/scheduling, without
isolating each cost. The diagnostic observation windows recorded substantial
script, layout and style time, but those cumulative totals cannot be summed
into time-to-useful or added to overlapping React durations. Private JSON parse
was 252–384ms and materialization 62–217ms across routes. Module-to-fetch and
post-parse-to-table gaps remain partly unassigned. Settings reads were small
relative to the missing seconds. The next owning paths are initial rankings
table/row-ref layout work and shell hydration/fetch admission; a precise
per-commit DOM/layout split remains missing.

| Before | Hypothesis | Change | After | Verdict |
| --- | --- | --- | --- | --- |
| Slowed rankings misses the existing useful-state deadline; large script/render/layout cost | Avoid building CSS-hidden mobile cell children to reduce initial DOM work while preserving measured table geometry | Bounded hidden-cell experiment retained cells/columns, complete row universe, popup/export behavior and resize restoration | All **16** uninstrumented alternating rankings samples (8 synthetic, 8 private; both builds, cold/warm) missed the unchanged 10s observation cutoff. No repeatable useful-state benefit. Geometry and semantic parity passed | **REJECTED and fully reverted**. Only an inactive patch is archived. No performance fix or speedup is claimed |

The 10s observation cutoff is not an acceptance budget: warm ≤1s, normal p95
≤2s, cold ≤3s and the absolute 5s useful/unavailable deadline remain unchanged.
Null observations and misses remain failures. There is no second speculative
candidate. Detailed measurements, missing observations, correctness hashes and
limitations are in [Phase 2 browser evidence](../tests/e2e/performance-lab/phase2-evidence.json).

### 5. Validation and independent review

- Integrated affected backend selection: **635 passed, 6 skipped, 1 failed** in
  272.69s. The failure was Windows `WinError 2` launching `bash` in the deploy
  sourcing contract because Git Bash was absent from PATH. Rerunning that exact
  test with Git Bash on PATH: **1 passed**, 1.22s. The original selection is not
  described as an uninterrupted green run. Serving legacy/shadow/prepared,
  reload/corruption/recovery, ownership, retention, news, affected caches,
  overrides, scoring/league routing, telemetry, private auth and startup were
  included. No full roughly 11k backend-suite pass is claimed.
- Final focused shadow publication/status/initial soak-report selection:
  **39 passed**, 14.87s. These counts overlap the integrated selection.
- Retention author's selection: **63 passed, 6 filesystem capability skips**;
  required news dependency follow-up: **2 passed / 35 deselected**. These are
  supporting, overlapping runs, not additional unique coverage.
- Final retained frontend: **175 files / 2,519 tests passed**, 143.87s;
  Node 20 production build and **14/14 unchanged bundle budgets passed**.
  Final browser smoke **9/9**, zero page errors, **27/27** successful privacy-valid
  telemetry POSTs. Observed TTFB/FCP/LCP; missing INP/CLS stay missing.
- Private replay semantic checks: **4/4** (both builds × desktop/mobile).
  Complete Show-all CSV of 943 eligible rows and 69-row QB filter were
  hash-identical; sorting/filtering, source controls, full popup/audit and
  resize geometry passed. The initial fixture-only league identity/CSV
  assumption failures are recorded in the browser evidence, not erased.
- Required Ruff 0.6.9 format/lint gate passed; decision-coercion ratchet passed
  with 663 present / 657 accepted debt and eight unrelated-file differences.
  No new allowance or budget increase was introduced.
- Independent read-only review through `adb769b64` found no actionable issue in
  the shadow lease fix, source proof path, integrated retention dependencies,
  cached diagnostics or default-off frontend instrumentation. That bounded
  review does not certify unmeasured API transition/resource behavior.
- Earlier actual-HTTP soak harness: **15 tests passed**, 0.25s. Independent review
  required and verified per-route/status/phase latency gates, sampling gates and
  changed-generation HTTP adoption. The final integrated gate checked **1,468**
  Python files, with no formatting changes. That historical measured code was
  `45d5d407f354da198e9eb75b34d6fd40fdb17d7c`; harness SHA256
  `1fdddf5766cc4af740a1cac9bd9e8927a6bfbb9e86d0566775ad3dc4596c81d4`.

### 6–7. Resources and retention

The existing `ArtifactStore` now coordinates publication, disk reads and pruning
with consistent lock order. Publication-history age, 48-hour target, minimum
three accepted generations per partition, rollback pins, ownership proofs and
transitive league/news canonical dependencies are implemented. Default budget
is min(4 GiB, 10% filesystem capacity), retaining the free-space floor. Pressure
reports a shortened rollback window; protected-plus-proposed exhaustion rejects
publication without deleting or changing the accepted pointer. Corrupt/uncertain
references fail pruning closed. Unowned archives/databases/evidence/caches are
excluded. Dry-run/apply CLI and bounded cached admin diagnostics share this
owner. Controlled timestamp tests exercise 48-hour eligibility without waiting
two days; unknown legacy acceptance times remain protected.

The initial 180-second helper smoke passed its functional fault checks, but
excluded HTTP/auth/league dispatch, overlapped unrelated jobs and had only
97.26% sampling coverage with a 3.047s gap. It is **not** the required hour soak,
an API latency result or acceptance evidence. The final harness must exercise
actual loopback authenticated rankings/trade routes with a separate web child
and parent resource sampler, preserving normal independent canonical/league
reloads. Local fixture sessions/providers cannot substitute for deployed auth
or real source collection.

Three short HTTP harness attempts are not acceptance evidence. A Windows
event-loop socketpair/guard setup failure and unread stderr pipe were corrected.
The last 180.5s smoke produced 9,320 coherent 200/304 responses and no HTTP
errors, but its recovery adapter returned `False` instead of `None`, preventing
the runtime restart and changed-generation adoption. That harness bug is fixed
and regression-tested; its RSS/adoption failure is not assigned to product code.
The full run starts with a new private store and the fixed exported contract
SHA256 `7c36b88688011bb7a8a26edb31182a57b76107ab2e29c6ca3422e8472f114361`.

### 8. Canonical manifest

**PARTIAL; skip disabled.** The four gaps are traced in
[the existing manifest document](ops/serving-input-manifests.md): factual league
context/cache owner, clock/observation boundaries, transactional history
selection and effective cached configuration. Each has a mutation boundary,
proposed identity and required completeness test. `complete: false` remains;
unchanged canonical observations rebuild. Documentation-only disposition is
intentional here, not proof that implicit inputs are complete.

### 9. Ownership and staged rollout boundaries

Legacy remains the default. The standalone bootstrap persists a strict proof
under the source lease before release; healthy recurring cycles retain that
proof instead of pinning another canonical generation. Shadow startup/cache
recovery cannot publish outside the fresh source cycle lease. The source,
league and news owners remain separate; queued refreshes and provider failure
behavior are preserved. A local lease is not cross-host GitHub ownership.

The [ownership runbook](ops/source-producer-ownership.md) preserves the sequence:
legacy deployment → telemetry/resources → shadow preparation → worker/artifact/
parity verification → prepared backend → frontend opt-in after mobile acceptance.
Recurring standalone source ownership must wait until embedded ownership is
disabled; one bounded serialized bootstrap is permitted before that transition.
GitHub's additional feed coverage remains enabled. Opt-in source/league timer
templates are no longer mistaken for mandatory installed timers by the deploy
presence probe; no installation or timer activation occurred.

The successful main deployment workflow at `53b87921a` is not a deployment of
this candidate. Read-only SSH using existing configuration failed authentication
before remote measurements. Installed units, host capacity, actual scraper
children, Linux FDs/systemd limits and authenticated deployed desktop/mobile
waterfalls are inaccessible. WSL is uninstalled and Docker unavailable locally.
Windows handles must not be relabeled Linux FDs. No worker memory ceiling was
copied from the web service; host measurement is required first. No push, PR,
merge to main, deployment, timer activation or production flag change occurred.

### Historical interrupted-run checkpoint

The required 60-minute local soak did not complete and failed its gates. It is
preserved at `docs/evidence/performance-soak-interrupted-2026-09-11.json`, not
recast as a passing resource result: 1,462 samples covered only 8.84% of the
16,544.7-second driver lifetime, with a 313.813-second observed gap and no final
quiet RSS/handle sample. It also had an earlier 2.422-second sample gap before
the long interruption. The run recorded 3,469 prepared HTTP 503 responses,
including 1,734 rankings and 1,735 trade errors, plus a connection abort and a
timeout. It observed 102,035 coherent successful responses, all successful
changed generations through HTTP, all six fault scenarios, no surviving one of
123 observed child processes, and disk below the 536,870,912-byte lab budget;
those bounded facts do not complete the soak.

Successful rankings 200s during refresh had p95 **106.25ms** versus **16.46ms**
baseline (+545.5%), failing both the <75ms serving-read gate and <=20%
degradation gate. Trade refresh 200 p95 was 28.41ms (+18.93%) but both routes'
304 refresh series failed the relative gate. Quiet rankings p95 was 180.32ms
from only 90 samples, not a sustained final quiet measurement. Raw observations
lack request/error timestamps, so exact pre/post interruption attribution is
unavailable; the failures are retained rather than attributed to suspension.

A provider-free focused reproduction found the concrete 503 owner. Real
prepared rankings and trade endpoint functions return coherent 200/304 for
canonical A, both return 503 immediately after canonical B becomes visible while
`LeagueServingReader` still holds A, and return coherent B 200/304 after its
refresh. Scoring identity for B passed. The reproduction made no store
publication or external provider call. An initial unvalidated eager-staging
patch was subsequently rejected in review: replacing the league tuple before
the canonical pointer merely reverses the mismatch, and releasing its lock
before the pointer swap still permits an intervening poll. The continuation
replaces that experiment with coherent request captures and independent review.
The earlier tool rejection concerned a temporary sleep-prevention probe and
reported account usage exhaustion; it was not a test result. Project Python
execution and the scoped sleep request were successfully revalidated after the
user resumed the work. No persistent Windows power setting is changed.

Exact corrective action before a new decision: run the focused serving tests and
formatter in a functioning environment; run the focused transition reproduction
against the patched code; then run a new uninterrupted 3,600-second soak with a
600-second baseline, >=99% one-second sampling coverage, <=2-second gaps, zero
unexpected HTTP failures, per-route/status p95 <75ms, refresh degradation <=20%,
generation adoption, final quiet resource recovery and all retention faults
passing. Repeat Linux installed-unit/FD/resource and deployed authenticated
desktop/mobile evidence before claiming production readiness.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No at checkpoint | Reconciled main and local suite evidence | Coherent transition fix and uninterrupted soak still pending at that time |
| Shadow mode | No at checkpoint | Lease/publish guard and retention paths reviewed locally | No bounded uninterrupted resource proof |
| Source workers | No at checkpoint | Ownership proof/lease path and controlled faults covered locally | Installed Linux units, host capacity and source coverage not observed |
| Prepared backend | No at checkpoint | Exact canonical/league reader mismatch reproduced | Coherent capture implementation and acceptance pending at that time |
| Prepared rankings/trade frontend | No at checkpoint | Parity/build/bundle smoke pass; hidden-cell experiment rejected | Slowed mobile useful-state gate still fails |
| Broader page migration | Out of scope | Explicitly outside this continuation | Not authorized or implemented |

### Completion continuation: frozen candidate and corrected transition

Current main subsequently advanced from `9a24f7f67` to `6054b4a65` through
14 commits touching 91 distinct paths. Per-commit SHAs, paths and classifications
are preserved in [reconciliation evidence](evidence/performance-phase2-reconciliation-2026-09-11.json).
Two documentation/operations evidence commits are benign; twelve source-data,
observation or challenger-registry commits are relevant input-generation moves.
No upstream product code changed. The Hill champion remains generation 2.
Reconciliation commit `c1412fcf01b347f7c2814a1273a7325bcac5a1d1` preserved both
adjacent work-claim rows in its sole documentation conflict. Affected freshness,
manifest and then-current harness checks passed (74 tests, overlapping later
runs). Fixed-input browser and payload comparisons remain valid.

| Before | Hypothesis | Change | After | Verdict |
| --- | --- | --- | --- | --- |
| Independent canonical B publication and league A polling produce prepared HTTP 503s despite each generation being valid | Requests must capture the board and league bytes as one coherent pair | `LeagueServingReader.capture` binds one immutable board/bundle pair per active league. Each compatible league adopts independently; a missing/rejected new bundle retains the accepted pair. Expiry is applied off-request before fallible reloads. Prepared data, rankings, trade, catalog and player-detail handlers use captured references; startup primes the reader off-request | Integrated affected backend: 656 passed, 6 skipped, one warning in 151.98s. A 300.5s functional smoke produced 33,213 coherent 200/304 responses, zero HTTP errors, and adopted all changed generations | Correctness fix retained at `7647747b3c317c32f30842cdb495590abadfe9bd`; independent architecture/correctness review green. The short smoke is not resource or speed acceptance |

The corrected reader does not encode eight fallback views on every poll while
waiting for a newer league artifact. It keeps at most one accepted pair per
active league plus in-flight references, with shared canonical objects across
leagues. Unchanged logical generations can rebind refreshed observations without
re-encoding. Secondary-league failure cannot prevent healthy primary adoption.
Scoring/configuration mutation, unavailable/expired context, corruption,
recovery, legacy compatibility and object release have focused regression tests.

The short functional smoke overlapped backend tests. Its aggregate RSS rose
from 550,133,760 to 751,706,112 bytes and relative refresh latency gates failed;
neither result is hidden or promoted to acceptance. All six fault scenarios,
one-second sampling, protected retention, disk budget and child cleanup passed.
The new hour run separates web and observer resources for attribution while
retaining the original aggregate RSS/handle gates. Missing process observations
remain null. League polling is included in refresh latency classification.
Windows automatic sleep is inhibited only for the scoped run; persistent power
settings are unchanged.

Final harness revision `30946825d` passed 18 report/sampling/identity tests,
the required Ruff formatter/lint and decision-coercion gate. Independent review
found no remaining actionable defect in the measured capture or sampler paths.
The uninterrupted run uses a new private store, the same 1,093-player contract,
3,600 seconds of reads, a 600-second baseline, 30-second refresh admission and
a configured 125-second cutoff for new admissions. The actual worker-free
observation span is qualified below. No other campaign build or test job ran
alongside it; host CPU observations remain available separately.

### 6–7. Completed hour: observed results and retained failures

The frozen `30946825d9c1b967dd7d7dd7e90bf5107896527e` run recorded
**3,600.984 seconds of reads**, followed by cleanup (3,603.281 seconds total).
It completed its scheduled hour but **did not pass the full-soak gate**:
`passed=false`, `full60MinuteSoak=false`. The
[privacy-safe completed-run evidence](evidence/performance-soak-completed-2026-09-11.json)
contains all gates, route/status counts, p95s, fault times, five-minute resource
windows, sampling gaps and hashes of the private one-second/HTTP observations.
The raw replay and observations remain private. This result supersedes the
interrupted-run checkpoint for the current candidate without erasing it.

- **Correctness and recovery PASS locally:** 365,376 successful coherent
  responses, zero HTTP errors, zero mixed-generation/audit failures and no
  deadlock or unexpected worker failure. All 60 changed source publications
  were adopted through HTTP; 29 unchanged cycles and 89 overlapping league
  cycles completed. There were 61 observed logical generations including the
  starting board. The six controlled rejection/corruption/restart/capacity/
  termination/queued-request recovery scenarios passed.
- **Cleanup/handles PASS on Windows:** all 541 observed child identities exited,
  with zero remaining, reparented or unknown children. Aggregate idle handles
  were 615 → 625; web handles 376 → 382. Peak process count was 10, warmed idle
  count 4. These are Windows handles, not Linux FDs. Unobserved short-lived
  descendants and real provider/browser children are not proven by this replay.
- **RSS FAIL:** idle aggregate median 559,329,280 → 856,670,208 bytes,
  **+283.57 MiB / +53.16%**, exceeding the unchanged 64 MiB permitted increase
  for this baseline. Web RSS alone was 480,505,856 → 759,975,936 bytes
  (**+266.52 MiB**); driver RSS 78,823,424 → 96,673,792. Peak aggregate RSS was
  1,810,624,512 bytes. Five-minute idle medians show elevated web memory through
  the sustained run, not only live-worker peaks. The owning process is proven;
  retained objects versus allocator high-water behavior is **not yet isolated**.
- **Latency FAIL:** the pooled refresh p95 of 19.93ms hides substantial relative
  regressions and a failed rare response series; it cannot certify the route
  gates. Exact comparisons are below. A conditional request may correctly return
  200 when its generation changes; that response still counts against acceptance.
- **Sampling PARTIAL / maximum-gap FAIL:** 3,598 observations before cleanup,
  99.917% coverage (≥99% passes), but gaps of 2.765s at 2,908.078 → 2,910.843s
  and 2.719s at 2,954.937 → 2,957.656s exceed the 2s ceiling. Missing ticks were
  not fabricated. Host CPU measurements are retained; no causal attribution to
  host load or a particular application operation is claimed from them alone.
- **Quiet recovery evidence PARTIAL:** 125 seconds was the configured cutoff
  for new refresh admission. Existing workers continued until the final busy
  sample at 3,500.781s. The 100 final idle samples span 3,501.750 → 3,600.734s,
  only **98.984 seconds**; 99.953s from the last busy sample is an upper bound,
  not a verified quiet duration. The
  idle medians above are available, but this is not a demonstrated 120-second
  worker-free recovery interval. A rerun must drain workers and pending reloads before starting that
  interval, extending measurement as needed. This additional limitation is
  explicit in the evidence; it does not change the frozen harness's output.
- **Retention/disk PASS within local scope:** maximum measured owned disk was
  527,529,138 bytes and final disk 526,914,639 bytes, below the 536,870,912-byte
  lab budget. Usage stabilized near that ceiling despite repeated publications.
  Final dry-run inventory: 10 generations, 6 protected, zero unknown acceptance
  times, no blocked pruning. Controlled 48-hour, minimum-three, rollback/proof/
  transitive-dependency and concurrent reader tests provide the protection
  evidence; the hour's fixed fixture does not independently replay every news
  product. The 1-byte capacity fault rejected publication and retained the
  accepted pointer. The final dry-run reports no newly shortened window because
  it plans no deletion; pressure-shortening behavior is covered by the explicit
  retention tests and must not be inferred from that final dry-run field.

| HTTP series | Baseline p95 ms | Refresh p95 ms | Verdict |
| --- | ---: | ---: | --- |
| Rankings unconditional 200 | 5.3225 | 61.7126 | Absolute <75ms passes; ≤20% degradation fails |
| Trade unconditional 200 | 3.1355 | 22.9210 | Absolute passes; relative fails |
| Rankings conditional 304 | 2.7399 | 5.2434 | Absolute passes; relative fails |
| Trade conditional 304 | 2.5492 | 5.0398 | Absolute passes; relative fails |
| Rankings conditional changed-generation 200 | 5.3225 (baseline 200) | 6.2146 | Both pass; five refresh observations |
| Trade conditional changed-generation 200 | 3.1355 (baseline 200) | 153.6143 | Both fail; **one observation** at 2,870.265s, too sparse for a stable percentile estimate and still a recorded deadline failure |

The host reports 33,821,810,688 bytes of memory and 22 logical CPUs. Resource
samples include CPU seconds for observed live processes and host utilization;
they are not complete lifetime CPU accounting for every short-lived child.
No Linux worker resource limit is assigned from these Windows measurements.

### 5, 8–10. Final validation, decision and exact corrective actions

The final fetch confirmed unchanged main
`6054b4a650a0272c23a579cabbec06e41d95c6ff`, already reconciled at `c1412fcf`.
The measured implementation is `30946825d`; subsequent edits are evidence and
documentation only. The Phase 2 manifest lists implementation/evidence paths;
upstream input-data paths are separately enumerated in reconciliation evidence.

Final affected backend selection: **656 passed, 6 skipped, 1 warning** in
151.98s, including serving modes, scoring, overrides, private/public boundaries,
reload/corruption/recovery, news, affected caches, startup and deploy contracts.
Final sampler/report tests: **18 passed**, 0.19s. These overlap; they are not
summed. Required Ruff 0.6.9 formatting/lint and decision-coercion gates passed.
The unchanged frontend evidence remains **2,519 tests / 175 files**, production
build, **14/14** bundle budgets, **9/9** browser smoke, **27/27** privacy-valid
telemetry posts and **4/4** private semantic checks. No broader interrupted
backend run is relabeled a pass. Independent read-only architecture/correctness
review is green for the retained coherent captures, retention and ownership;
it does not override the failed measured gates.

**Exactly one current outcome: B — NOT READY.** The authorized local Phase 2
implementation and evaluation are recorded. The candidate cannot be promoted
to READY FOR PR / SHADOW ROLLOUT on this evidence. Legacy behavior and prepared
frontend default-off remain unchanged; no merge to main, push, PR, deployment,
timer activation or production flag change was performed.

| Failed or missing condition | Owner / missing evidence | Exact corrective action |
| --- | --- | --- |
| Sustained web RSS increase | `src/serving/runtime.py::AtomicRuntime.reload_if_changed`, `src/serving/serialization.py::load_generation` / `validate_generation`, `src/serving/league_views.py::LeagueServingReader._refresh`; allocation/retention attribution is missing | Profile changed and unchanged loads in an isolated diagnostic replay, trace retained generation references and allocation high-water behavior, fix the demonstrated owner without dropping validation, then rerun the unchanged hour and RSS gate |
| Refresh latency and rare 200 deadline failure | Same in-web reload/validation path, prepared endpoint dispatch and event-loop scheduling; wall-clock correlation is observed, CPU/GIL/lock attribution is incomplete | Correlate timestamped reload/league phases with CPU and lock traces, compare isolated baseline/candidate runs, retain only a repeatable parity-preserving fix, then rerun every route/status latency gate |
| Two sampling gaps and insufficient worker-free tail | `scripts/soak_prepared_serving.py::resource_observations` and main admission/quiet scheduling | Diagnose sampler scheduling/host contention; drain workers and pending reloads before starting the ≥120s quiet clock, regression-test that timing, and repeat the full measurement with ≥99% coverage and ≤2s gaps; do not fill absent samples |
| Slowed-mobile useful-state deadlines | Existing browser lab and rankings table/layout plus shell hydration/fetch admission; module-to-fetch and post-parse-to-table costs remain partly unassigned | Continue opt-in CPU/React/layout attribution on both existing fixtures; use unchanged alternating uninstrumented cold/warm acceptance. Keep prepared frontend disabled until all declared deadlines pass |
| Installed source/league/news ownership, host resources and authenticated deployed behavior | Deployment/source runbook; existing SSH authentication failed before read-only inspection; no accessible Linux runtime | Obtain working authorized read-only host access; inspect actual units, GitHub feed ownership, combined host capacity and Linux child/FD recovery. Only under separate rollout authorization execute the staged shadow sequence and authenticated candidate auth/304/scoring/stale/rejection/restart and desktop/mobile measurements |

Canonical manifest remains **PARTIAL, skip disabled**. The four documented
owners/mutation boundaries/proposed identities satisfy this phase's permitted
documentation-only disposition, not completeness or no-op activation. Broader
page migration and new infrastructure remain outside scope. A failed mobile
gate alone would not block a safe backend/shadow candidate; here the independent
resource and latency failures also block that readiness.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No | Current main reconciled; affected backend/frontend/build gates and bounded independent review pass | Required bounded-resource/latency acceptance fails; sampling/quiet evidence incomplete |
| Shadow mode | No | Default-off behavior, serialized ownership proof, retention and controlled faults verified locally | Sustained web RSS and refresh latency fail; installed host evidence unavailable |
| Source workers | Partial locally; no rollout readiness | Lease/proof/queued-request tests; 89 source cycles and all observed children cleaned up | Real source/feed coverage, installed source/league/news ownership, Linux FD/systemd and host capacity unverified |
| Prepared backend | No | 365,376 coherent authenticated-fixture 200/304 reads, zero errors, all changed generations adopted | RSS/latency gates fail; deployed authenticated scoring/stale/recovery evidence missing |
| Prepared rankings/trade frontend | No — keep disabled | Full suite/build/budgets and desktop/mobile semantic parity pass | All 16 slowed rankings acceptance samples missed the observation cutoff; useful-state deadlines fail |
| Broader page migration | Out of scope | No additional pages or infrastructure introduced | Not authorized in this continuation |
