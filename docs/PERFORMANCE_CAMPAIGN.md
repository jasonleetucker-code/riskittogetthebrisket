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

## RSS / refresh-latency closure continuation — 2026-09-11

Owner-authorized continuation on `codex/performance-serving`, starting from
`07eed7d58e2c90262103f2aaf2252883f7d230e6`. The prior failed acceptance report is
preserved above. This closure is evaluated below; current readiness remains
**B — NOT READY**. Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc.

Scope is exactly web RSS, refresh latency and sampling/quiet recovery. Preserve
proven generation coherence, source/league acceptance, retention and local suite
evidence unless an affected change requires revalidation. Mobile frontend,
broader page migration and new infrastructure are excluded. No push, PR merge,
deployment, timer installation or production flag activation follows from this
continuation.

Execution order: (1) real-artifact isolated generation lifetime and allocation
experiment, with explicit GC diagnostic only; (2) timestamped refresh/request
spans separating CPU/GIL, event-loop, lock, disk, GC and host scheduling costs;
(3) sampler timing and worker/reload drain repair; (4) only demonstrated product
fixes; (5) focused tests; (6) affected integrated backend selection; (7) a passing
five-minute functional/resource run; (8) only then full acceptance. Do not start
another hour while the short-run RSS, latency or sampling gate is failing.

Acceptance thresholds remain unchanged: at least 3,600 seconds of serving
exercise, followed by at least 120 seconds of verified worker-free and
reload-drained quiet recovery; zero unexpected HTTP/coherence errors, all changed
generations adopted; p95 below 75ms per required route/status series and refresh
degradation at most 20%; coverage at least 99% and maximum sampling gap at most
2 seconds; all observed workers cleaned up, existing RSS/handle recovery and
retention/disk budgets satisfied. A demonstrated allocator plateau can inform
a separate owner decision, but cannot be relabeled a passing RSS recovery gate.

The active saved checkout completed its required fast-forward pull. New main
`86d20e6cae3f75b6c5d58a084882f4115e3e6e19` adds four documentation paths through
five commits (including the merge): `AI_INSTRUCTIONS.md`,
`docs/OWNER_REQUESTED_TODO.md`, `docs/OWNER_TODO_RECOVERY_AUDIT_2026-09-10.md` and
`docs/PLANNING_DOCUMENT_STATUS.md`. Classification: benign documentation/process
movement; no product, input-generation or architecture conflict. Reconciliation
was clean. The newly added durable-intake rule was read and this closure scope
was recorded in the owner-intake ledger. No open PR was returned by the live
ownership check. Fixed-input performance evidence is retained.

Engineering applicability: allocation/request/sampler tracing and generation
lifetime invariants **APPLY_NOW**; replay/typed contracts/retention and protected
rollout are **ALREADY_COVERED**; frontend migration and infrastructure are
**DEFERRED_BY_AUTHORITY**. No new valuation or configuration owner is introduced.

### Closure attribution and retained change

Reconciled candidate before this closure change:
`c9308683888de260e4142f4140bc8f7376d8afc0`. The source/main SHAs and classifications
above remain the fixed reconciliation boundary; no new frontend work was done.

**RSS classification: C — CPython allocator high-water behavior is the dominant
observed mechanism.** The sustained production ceiling remains unverified.
The authoritative baseline control streamed its observations and retained only
two weak references, eliminating diagnostic-history growth as the explanation.
Across 30 real-artifact, one-league load/adopt cycles, canonical objects stayed
at one, league bundles at one, payloads at 16, and serialized buffers at 32
(approximately 102.487 MB). Superseded canonical weak references were zero;
runtime/reader roots and legacy aliases pointed to the accepted generation;
the inspected response/override/draft caches remained empty. GC tracked objects
were 412,883 initially and 412,884 finally. Diagnostic collection reclaimed zero.

Small-block live allocation grew only 5,648 bytes while CPython arena capacity
grew by 236 MiB, reaching 512 arenas of 1 MiB each. RSS rose from 463,826,944 to
735,023,104 bytes. Arenas stayed at 512 only for the last three observations
(about 41 seconds); RSS still rose 17.18 MiB over cycles 21–30. This is evidence
of late flattening, not a permanent 735 MB process limit. The separate 12-cycle
tracemalloc experiment settled from 352,715,993 to 352,799,260 live bytes. Its
RSS was inflated by tracer metadata/snapshots and is explicitly excluded from
product RSS acceptance. No affirmative evidence of native leakage was found;
the difference between resident pages and arena capacity is not itself such
evidence. CPython allocator documentation:[memory management](https://docs.python.org/3.12/c-api/memory.html).

The isolated runner is `scripts/diagnose_serving_lifetime.py`. Producers are
separate processes using real ArtifactStore publications; the measured consumer
uses AtomicRuntime, the server publication adapter and LeagueServingReader.
No providers, browser, HTTP load or multi-league partial-failure concurrency
are represented. These limitations remain attached to the classification.
Private raw reports remain under `data/private_serving/lab/lifetime-*`;
bounded public-safe observations are in
`docs/evidence/performance-rss-attribution-2026-09-11.json`.

| Before | Hypothesis | Change | After | Verdict |
| --- | --- | --- | --- | --- |
| Loader separately decodes eight view graphs, then recomputes canonical projections for validation and discards them; 12-cycle retained RSS 625.75 MiB | Reusing the already-required projection graph avoids duplicated live collections and temporary encoding allocations | `src/serving/serialization.py::load_generation` decodes full once, retains the pure projections, and validates exact persisted raw/gzip/ETag/generation/envelope values; `_validate_generation` reuses one encoding only when the compared projection is the same object. Public validation still independently recomputes projections | Same fixture/cycle count: 506.25 MiB retained RSS, 119.50 MiB less; GC tracked objects 325,907; one canonical/bundle and unchanged serialized buffers. Small-block allocation settles near 203.016 MB. Diagnostic median refresh load/adopt, cycles 1–12 (initial load excluded), 6.041 → 4.051 seconds, not HTTP acceptance | Retained memory improvement; existing RSS recovery gate still applies. Matched HTTP acceptance is reported separately below |
| League expiry accounted for 17.46 seconds of inclusive web work in the diagnostic trace | Applying expiry before producer encoding could avoid re-encoding eight views in web | Proposal reviewed, not implemented | Independent review found that unchanged-input reobservation excludes the observation timestamp and could repeatedly renew roster-stripped bytes without restoring fresh context | Rejected before implementation. Preserve current expiry and recovery behavior |

The product change does not alter values, row order, source inputs, scoring,
legacy defaults, ownership or request publication. The existing producer
already shares nested full/runtime/array objects. Consumers retain the same
read-only ownership rule; overlays and expiry copy their outer dictionaries.
Seven parametrized persisted-view tampering cases ensure that self-consistent
wrong JSON/gzip/ETag combinations cannot bypass canonical parity checks.

### Refresh attribution and validation ownership

The opt-in `scripts/serving_lab_spans.py` extends the existing soak, with
wall/process/thread CPU clocks, thread identity, generation digest, request
sequence and nested phase spans. It records no arguments, exception messages,
payload values, private identities or file paths. HTTP observations join to
spans by request sequence; driver `monotonic` and child `perf_counter` origins
are not assumed identical. Nested inclusive timings must never be summed.

The 180-second diagnostic recorded these baseline serving-active spans:

| Stage | Count | Inclusive wall / thread CPU | Interpretation |
| --- | ---: | --- | --- |
| Canonical load | 6 | 16.939 / 14.703 seconds | CPU-heavy decode and semantic validation on reload threads |
| Canonical validation | 6 | 12.016 / 10.359 seconds | Includes recomputed projections, JSON encodings, gzip, ETags and envelope checks |
| League refresh | 65 | 51.004 / 37.313 seconds | Includes loads, validation, stale-context re-encoding and store work |
| League validation | 11 | 12.127 / 11.688 seconds | Canonical/league parity remains expensive |
| League expiry | 75 | 17.457 / 12.094 seconds | 88 payload preparations; most polls are cheap, transitions are expensive |
| Endpoint capture | 16,280 | maximum 0.100 ms wall | Captured-memory lookup; no artifact read or store lock |
| Canonical atomic swap | 6 | maximum 0.030 ms wall | Reference publication is negligible |

All observed meaningful canonical/league loading and validation spans were
off the event-loop thread. This rules out direct synchronous reload I/O on the
request loop in this fixture. It does not make Python threads CPU-isolated:
217 of 221 HTTP observations at least 75 ms overlapped measured reload/league/GC
work by request sequence. Maximum recorded loop delay was 464.3 ms; GC reached
473.3 ms. CPU/GIL contention and stop-the-world collection are strongly supported
contributors, not an exact apportioned causal percentage. Store-lock waits
reached 1.574 seconds on background paths; disk copying and publication can
delay those paths, but requests do not acquire that lock. Host scheduling and
I/O contributions cannot be fully separated by these inclusive spans.

Diagnostic limitations are explicit: 44 events were dropped from the bounded
queue, and the original 10 ms pulse was below Windows asyncio clock resolution.
It spun under request activity and added observer overhead. The pulse is now
50 ms. This run is attribution only and its latency/RSS values are never used
as acceptance results. See
`docs/evidence/performance-refresh-attribution-2026-09-11.json`.

The fixed replay's source age is beyond the roster freshness ceiling. Its
expiry cost represents the stale-context path; it is not a forecast of a
fresh provider observation. The fixture and thresholds remain unchanged.

The prior **153.6143 ms trade conditional changed-generation 200**, one sample
at 2,870.265 seconds, remains in the completed-hour evidence. Nearby samples
show ten processes and approximately 24–30% host CPU, between overlapping
source/league worker completions. There was no CPU/span trace then. Exact cause
is **unknown**, consistent with reload contention; it is neither discarded nor
classified as proven scheduler noise. The new diagnostic demonstrates slow
reload-overlapping requests generally, not reproduction of that exact event.

Producer and reader validation overlap: publication validates the in-memory
candidate, the store validator loads/validates the serialized candidate representation, and
web adoption repeats semantic validation after store checksums. Existing hashes
prove internal byte integrity; they do not independently certify that a view
contains the correct canonical/scoring projection. A cheaper attested boundary
would have to bind a trusted validation owner, algorithm/model/scoring identity
and every representation, with mutation/recovery tests. No validation check was
removed and no unsigned assertion was promoted into such a proof in this pass.

### Measurement ownership repair

`scripts/soak_observation.py` supplies timing/state bookkeeping to the existing
`scripts/soak_prepared_serving.py`; it is not another serving or storage owner.
The sampler records expected/actual starts, lateness, missed ticks, observation,
process-tree, psutil member, disk, serialization/write/flush/progress wall and
thread CPU durations, plus web/driver/host CPU. Its schedule stays on the
absolute grid and does not add another full sleep after an overrun. Missing
ticks are never fabricated. Complete-resource coverage and full-precision
acquisition gaps, including boundaries, drive the unchanged 99% / 2s gates.
No speculative process-tree or disk-inventory optimization was added.

Exercise now lasts the configured duration before admission closes. The driver
then drains admitted workers and visible/remembered child identities, verifies
accepted canonical and league pointer versions and no queued/active reload,
and starts the continuous quiet clock. New work, pointer/activity changes,
unknown resources or observation gaps reset it. All newly observed rows are
checked, not merely the last row. Only samples wholly within verified quiet
contribute to final RSS/handle recovery. A bounded drain/reset timeout fails
closed. Start/end hashes freeze the harness, helper and measured product path.

The old 2.765/2.719-second gaps cannot retrospectively identify a psutil call or
scheduler stall because their stage clocks were absent. The old overrun sleep
policy demonstrably amplified delays; the new observations distinguish trigger
costs from that scheduling defect. Short-run measurements below determine
whether the problem recurs. The old 98.984-second tail is preserved as failed,
not retroactively repaired.

### Closure validation and platform limits

Completed validation in this continuation:

| Selection | Observed result | Scope/limits |
| --- | --- | --- |
| `tests/serving/test_serving_pipeline.py` and `tests/serving/test_lab_spans.py` | 46 passed, 13.81 seconds | Focused canonical byte parity, corruption rejection, bound captures and diagnostic privacy; overlaps the integrated selection |
| `tests/serving/test_soak_report.py` and `tests/serving/test_soak_observation.py` | 55 passed, 0.29 seconds | Absolute ticks, delayed observations, full-precision boundaries, child identity/discovery, pending reloads, late-worker extension, quiet reset, incomplete observations and code freeze |
| Affected integrated backend selection | 477 passed, 19 skipped, 1 warning; 5 passing subtests; 155.25 seconds | Serving suite excluding the two separately reported soak files; canonical data/age, scoring, auth/cache/privacy, overrides, startup, prepared news and staged ownership. Skips include unavailable public snapshots and platform/tool-dependent cases; they are not passes |
| Required Ruff 0.6.9 format/lint and whitespace gate | Green, 1,473 Python files checked | No new formatting/lint failures |
| Decision-coercion gate | Green for changed files | No new coercions or stale allowances in affected files; unrelated main debt is reported by the existing ratchet |
| Independent architecture/correctness review | Green for the retained change and repaired measurement protocol | Rejected unsafe expiry proposal; required precision, child-discovery and quiet-continuity corrections before measurement |

These counts are separate observations and are not summed. The integrated
command was:

```text
python -m pytest tests/serving tests/api/test_data_contract.py tests/api/test_data_contract_age.py tests/api/test_data_age_is_board_age.py tests/api/test_scoring_compatibility.py tests/api/test_private_auth.py tests/api/test_cache_control_privacy.py tests/api/test_overrides_response_cache.py tests/api/test_public_league_privacy_boundary.py tests/api/test_startup_nonblocking.py tests/api/test_startup_validation.py tests/news/test_prepared.py tests/deploy/test_staged_source_ownership.py --ignore=tests/serving/test_soak_report.py --ignore=tests/serving/test_soak_observation.py -q
```

Prior frontend tests/build/bundle/parity evidence is preserved; this pass changes
neither frontend code nor canonical wire bytes. No new mobile or deployed-field
measurement is claimed. Source, league and news ownership remain separately
gated by the previously recorded installed-unit/feed evidence. Canonical skip
remains disabled; no new infrastructure, timer or production flag was added.

The local measurement host has 33,821,810,688 bytes of RAM and 22 logical CPUs.
That is Windows lab capacity. Production VPS capacity/headroom, Linux allocator
behavior, simultaneous co-resident service peaks and installed cgroup/FD state
are still unavailable after the previously documented SSH authentication failure.
Numerical systemd `MemoryHigh` and `MemoryMax` therefore remain **unknown**, not
copied from the web service or inferred from this laptop. A process-tree sampled
peak is also distinct from the sum of individual live processes' historical OS
peaks; both are retained in the short-run evidence where available.

**Separate owner decision, not applied:** retain the existing RSS recovery gate
(the current rule), or explicitly replace it with bounded live allocation plus
a hard process-memory gate. The alternative would first need a sustained Linux
plateau, actual VPS headroom, combined web/worker peaks and explicit limits with
operating reserve. The local allocator evidence does not authorize that change.

### Matched short-run acceptance and final decision

Both runs used the same 1,093-player contract/raw-input hashes, frozen harness,
300 seconds of serving exercise, 60-second warm baseline, 30-second refresh
schedule, 512 MiB serving-store budget and at least 120 seconds of separately
verified quiet recovery. Detailed web spans were disabled. Other tests/builds
and measurement jobs were stopped. The baseline ran first using the reconciled
HEAD decoder, then the candidate ran with the retained change. Startup/end
hashes prove the only measured product/helper difference was
`src/serving/serialization.py`. The baseline wrapper restored the candidate
automatically before the candidate run. No production state was involved.

| Observation | Baseline | Candidate |
| --- | ---: | ---: |
| Serving exercise | 300.000 s | 300.000 s |
| Total read observation, including drain/quiet | 440.953 s | 433.766 s |
| Verified worker/reload-free quiet | 120.968 s | 120.969 s |
| Quiet interval | 319.985–440.953 s | 312.797–433.766 s |
| Quiet resets | 0 | 0 |
| Coherent successful HTTP responses | 54,588 | 52,284 |
| Unexpected HTTP/coherence errors | 0 | 0 |
| HTTP generations / changed publications adopted | 7 / all 6 | 7 / all 6 |
| Source cycles / overlapping league cycles | 9 / 8 | 9 / 8 |
| Controlled failure/recovery scenarios | all 6 passed | all 6 passed |
| Warm web RSS | 477,655,040 B | 397,111,296 B |
| Quiet web RSS | 639,983,616 B | 553,066,496 B |
| Web RSS increase | 154.81 MiB | 148.73 MiB |
| Aggregate warm → quiet RSS | 550,109,184 → 728,989,696 B | 473,016,320 → 634,523,648 B |
| Maximum sampled simultaneous process-tree RSS | 1,733,300,224 B | 1,390,006,272 B |
| Largest sum of live processes' historical OS peak RSS | 2,681,122,816 B | 2,145,853,440 B |
| Warm/quiet process count; peak count | 4 / 4; 10 | 4 / 4; 10 |
| Aggregate warm → quiet Windows handles | 602 → 608 | 625 → 631 |
| Web warm → quiet Windows handles | 378 → 383 | 378 → 383 |
| Observed children / surviving / unknown | 55 / 0 / 0 | 55 / 0 / 0 |
| Complete one-second observations | 441 | 434 |
| Complete-resource coverage / missed ticks | 100% / 0 | 100% / 0 |
| Maximum acquisition gap, including boundaries | 1.172 s | 1.016 s |
| Maximum sampled store bytes | 527,528,425 B | 527,528,425 B |
| Final store bytes / retained / protected generations | 526,914,542 B / 10 / 6 | 526,914,542 B / 10 / 6 |

Tracemalloc and object enumeration were intentionally disabled during acceptance;
the isolated live-allocation/reference observations above are separate evidence,
not invented acceptance measurements. Acquisition gaps exclude cleanup after
the measurement ends. The old generic `maxSampleGapSeconds` field includes a
cleanup sample and is not the sampling gate; `maxObservationSampleGapSeconds`
uses complete-precision acquisition starts and observation boundaries.

All observed route/status p95 values were below 75 ms. Every required refresh
series still failed the unchanged relative 20% limit:

| Route/status | Baseline warm → refresh p95 | Baseline degradation | Candidate warm → refresh p95 | Candidate degradation |
| --- | ---: | ---: | ---: | ---: |
| Rankings 200 | 15.217 → 54.451 ms | +257.82% | 3.649 → 61.262 ms | +1,578.97% |
| Rankings 304 | 1.698 → 3.495 ms | +105.86% | 1.737 → 3.470 ms | +99.80% |
| Trade 200 | 1.998 → 4.567 ms | +128.60% | 1.945 → 6.686 ms | +243.83% |
| Trade 304 | 1.578 → 3.405 ms | +115.73% | 1.547 → 3.357 ms | +116.96% |

The retained change demonstrates a repeatable memory reduction: 119.50 MiB at
cycle 12 in the isolated control, and 82.89 MiB less quiet web RSS in the
matched HTTP run. It does **not** demonstrate an HTTP latency improvement.
Median observed host CPU was 9.9% for baseline and 21.15% for candidate; the
single sequential pair cannot attribute every latency difference to the decoder.
The candidate fails the relative latency gate regardless. No speed acceptance
is inferred from the isolated load/adopt median or from aggregate route timing.

Sampler stage clocks did not reproduce the former >2s gaps. Maximum complete
iteration time was 272.170 ms before and 113.267 ms after; the largest stage
was disk inventory (254.240 / 94.563 ms). Process-tree maxima were 27.704 / 29.897
ms, separate web-tree enumeration 32.544 / 25.002 ms, and all-member psutil work
below 0.9 ms. Maximum scheduled lateness was 172 / 31 ms, with zero missed ticks.
These observations do not identify the uninstrumented historical gap trigger,
and do not justify replacing the process/disk observer or relaxing its limit.
They verify the repaired sampler and actual quiet protocol in both short runs.

Raw private reports, samples, requests, sampler clocks and quiet checks remain
under `data/private_serving/lab/closure-{baseline,candidate}-01-report*`.
Safe aggregate results and raw-evidence hashes are recorded in
`docs/evidence/performance-closure-short-runs-2026-09-11.json`.

**Final full soak: not run in this continuation.** The owner's execution rule
forbids another hour while the five-minute RSS or refresh-latency gate fails.
The earlier 3,600.984-second run and its 365,376 coherent responses remain
historical evidence; they are not a passing hour for this decoder change.

Current failed conditions and exact corrective actions:

| Condition | Owner and evidence | Corrective action |
| --- | --- | --- |
| RSS recovery fails | `serialization.py::load_generation`, `league_views.py` representations and CPython allocation lifetime; candidate web +148.73 MiB despite stable isolated live roots | Keep the current gate. Reduce further demonstrated transient/live representation costs without losing parity, or obtain an explicit owner decision on a replacement gate only after sustained Linux allocation/headroom evidence. Do not add periodic GC or infer a hard bound from the short plateau |
| Refresh degradation fails | Background canonical/league decoding, semantic validation and stale-context encoding; all four candidate series exceed +20% | Profile the remaining league/validation work against a safe producer-attestation boundary. Preserve factual scoring, byte/projection validation and fresh-observation recovery; a checksum-only bypass or the rejected roster-stripping proposal is insufficient. Repeat matched short acceptance after a demonstrated fix |
| Current-candidate full-hour evidence absent | Short-run gating rule; sampler/quiet checks now pass locally | After RSS and latency short gates pass, run at least 3,600 seconds of exercise plus drained continuous quiet; retain exact per-series and resource checks |
| Production resource/ownership evidence absent | Installed source/league/news units, extra GitHub feed coverage, Linux handles/FDs and VPS capacity inaccessible | Obtain working authorized read-only host access, inspect installed ownership and combined host resources, and validate Linux recovery before claiming systemd/FD readiness or selecting numerical worker limits |

The preserved frontend/mobile and broader-migration dispositions remain separate
from backend/shadow readiness. No merge to main, push, PR, deployment, timer
activation or production flag change occurred. The closure implementation,
experiments, review and gated decision are complete; rollout acceptance is not.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No | Main reconciled; affected tests and independent review pass; retained memory improvement | RSS recovery and relative refresh latency fail |
| Shadow mode | No | Local ownership/retention/fault behavior preserved; short-run sampling and quiet pass | Bounded-resource acceptance incomplete; installed host evidence unavailable |
| Source workers | Partial locally | Nine source and eight overlapping league cycles; all observed children exit in each matched run | Installed source/league/news ownership, Linux FD recovery and host capacity unverified |
| Prepared backend | No | 52,284 coherent candidate reads, zero errors, all six changed publications adopted | RSS and relative latency fail; new full hour and deployed authenticated evidence absent |
| Prepared rankings/trade frontend | No; keep disabled | Prior suite/build/bundle/semantic evidence retained | Separate slowed-mobile gate remains unmet; excluded from this pass |
| Broader page migration | Out of scope | No page migration or infrastructure introduced | Not authorized in this continuation |

**Exactly one current outcome: B — NOT READY.**
