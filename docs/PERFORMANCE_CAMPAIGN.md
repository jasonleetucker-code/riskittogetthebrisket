# Performance modernization campaign

**Owner final-release authority — 2026-09-12 (supersedes pause).** Resume the existing100-assignment campaign. The owner explicitly authorizes reviewable commits, push, PRs, protected green merges and staged rollout after prerequisite gates. Preserve local hybrid and all correctness/resource/browser gates. Measured new route budgets may be adopted with two independent reviews when no existing requirement or product expectation is weakened. Full terminal requirement is accepted production behavior and required work merged to main. No protection bypass or secret exposure. The pause report is historical; current execution follows the approved Final Performance Release Completion plan.


Owner-authorized 2026-09-10 after the source-grounded audit. Baseline main:
`8202c0c29b3bd2c8b970a9ad16c53732ae8e7c2a`. Rankings and trade migrate first.
Branch: `codex/performance-serving`. Local implementation candidate; no PR,
merge to main, deployed flag, installed unit or production acceptance is claimed.

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

## Contract and status

**Owner pause — 2026-09-12, approximately 11:36 UTC.** Implementation and
measurements are paused; all three working agents have stopped. The consolidated
[architecture and acceptance checkpoint](PERFORMANCE_PAUSE_REPORT_2026-09-12.md)
records the latest retained fixes, 570-test integrated backend result, pending
frontend integration, unfinished reviews and exact phase blockers. Steward
revision 93 has zero active assignments. Historical Phase 3A PASS / Phase 3B
FAILED-INTERRUPTED remains; no fresh official short/full has run on the subsequent
corrections. Resume requires a new owner request; no rollout authority changed.

**Current execution: 100-assignment gated completion, 2026-09-12 UTC.** The owner
authorized the exact numbered queue and independent work-ahead preparation.
The live board is the existing local Steward store's `performance-swarm` record;
its [sanitized snapshot](evidence/performance-swarm-2026-09-12.json) contains all
100 missions, dependencies, file leases, receipts and dispositions. Commander 000
uses three worker slots and retains sole board/document ownership. Initial lanes
006, 012 and 016 investigate worker exits, transition latency and interruption
accounting. A queued or executed assignment is not a passed acceptance gate.
Historical Phase 3A PASS and Phase 3B FAILED/INTERRUPTED remain the starting facts.
No new short/full run or production acceptance is yet claimed. The latest owner
directive permits independent production preparation, frontend investigation,
route measurements and regression preparation; activation gates remain intact.
Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc.

This is a chronological evidence ledger. The latest disposition is in
**Phase 3 local backend acceptance** below: policy implementation complete,
fresh short PASS, full attempt FAILED / INTERRUPTED; Phase 4 remains blocked.
Earlier Phase 1/2 verdicts remain historical. Fixed-input comparisons are retained
within their dependency scope and are not relabeled as new measurements.

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

## Validation / reload isolation closure — 2026-09-11 (implemented and evaluated)

Owner directive continues the existing campaign from clean candidate
`564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`. Fresh baseline precedes all product
changes. No acceptance threshold, frontend, scoring, weights, source policy,
production flag or deployment unit is changed. No hour soak is authorized yet.

Fetched main: `f864564e2fc3b3145f576a1d8a3ec2a9eefca238`. Since reconciled
`86d20e`, the only intervening commit updates four `data/scrape_state/`
IDP Show status/success observation files. Source observations are relevant to
production freshness; they do not affect the fixed replay's input bytes or any
serving implementation dependency. Preserve fixed-input comparisons. No merge
performed under the owner's no-merge directive. The saved working copy is on
another owner's `codex/awards-mobile-redesign`; it was not pulled or modified.

### Validation ownership before changes

| Live owner | Checks | Repeated downstream |
| --- | --- | --- |
| producer construction / builder | SCHEMA/SHAPE, CANONICAL SEMANTICS, SCORING IDENTITY, SOURCE/INPUT IDENTITY: population/source checks, full contract validator, factual scoring stamp, canonical projections | Web does not rerun the entire contract validator |
| ArtifactStore publication/read | BYTE INTEGRITY, SCHEMA/SHAPE, GENERATION IDENTITY: safe names, exact file hashes/sizes, physical identity, atomic pointer | Read verifies/copies under the existing store lock |
| canonical serialized validator | BYTE INTEGRITY, GENERATION IDENTITY, PROJECTION PARITY, SCHEMA/SHAPE: full SHA, ETag, gzip/raw equality, projection JSON equality, envelope | Producer publication and canonical web adoption recompute projections and JSON |
| canonical web adoption | Above serialized checks, canonical identity and pointer race/LKG checks | Recreates graphs needed only to certify bytes |
| league construction/validation | LEAGUE/CANONICAL COMPATIBILITY, SCORING IDENTITY, GENERATION IDENTITY, PROJECTION PARITY, SCHEMA/SHAPE: factual card, context ownership, complete ready roster, canonical invariants | Repeated before publication, serialized publication, web adoption |
| league serialized load and expiry | BYTE INTEGRITY, GENERATION IDENTITY, FRESHNESS: all eight envelopes/ETags/gzip; source timestamp restamp and stale/unknown context encoding | Web reencodes eight views on restamp/expiry |
| coordinator | SOURCE/INPUT IDENTITY, FRESHNESS: complete equal inputs, verified code/input identity, renewed observation | Full validation before unchanged reobservation |

Canonical input completeness remains unknown for factual league context, clock,
transactional history and cached configuration. Certification must not promote
these manifests to complete; canonical skip remains disabled.

### Trust and consumer decisions before acceptance

Opt-in Ed25519 producer certification binds exact non-certificate file inventory,
immutable metadata, policy fingerprint and unsigned content identity. The existing
atomic pointer carries a separately signed observation bound to partition,
physical generation, manifest digest and timestamps. Public verification pin is
external to the store; private signing credential belongs only to the producer.
An artifact-only writer cannot legitimize changed JSON/gzip/ETags/projections by
rehashing unsigned metadata. The issuer must first run strict semantic/parity
validation on exactly the bytes it signs. A compromised trusted validator can
sign incorrect results; signatures do not eliminate that trust assumption.
Existing common-user deployment templates do not establish private-key isolation.
This is an explicit unverified production activation prerequisite.

Prepared byte endpoints require bytes, ETag and payload-view metadata; player
lookup additionally requires a shared canonical row index and selected catalog
metadata. Full contract/raw inputs and five legacy views remain for untouched
domain handlers and aliases. Only rankings/trade/catalog duplicate graphs are
removed in opt-in canonical adoption. League final ready/stale/unknown bytes
must retain the original ready context for authenticated fresh reobservation.

Fresh baseline `isolation-baseline-01-report.json`: 432.625 seconds total,
300-second exercise, 120.063 seconds verified quiet. Correct responses and
absolute latency passed; RSS and relative refresh latency failed. Aggregate RSS
475,049,984 -> 634,757,120 bytes; web 398,073,856 -> 547,446,784 bytes.
Resource coverage 99.6487%, maximum sample gap 1.578 seconds, zero remaining
observed children. This is a failing baseline, not acceptance evidence.

Main triage detail: `f864564e2` is **BENIGN_AUTOMATION_MOVE for the reused fixed-input serving gates**.
Author/workflow provenance: repository IDP Show Fetch (prod), automated refresh
2026-09-11T14:32:27Z. Inspected every changed leaf: only `observedAt` and the
corresponding success epoch advance; acquired/usable flags and row counts stay
identical. No code, fixture, policy, configuration or dependency consumed by
these gates changes. Changed paths are exactly
`data/scrape_state/idpShowCombined_last_status.json`,
`data/scrape_state/idpShowCombined_last_success`,
`data/scrape_state/idpShow_last_status.json`, and
`data/scrape_state/idpShow_last_success`. This does not claim deployed freshness
validation or waive final integration checks. Candidate base remains the previously
reconciled `86d20e`; starting validated head is `564ef3f28`.

Final implementation validation (before acceptance):

| Check | Observed result |
| --- | --- |
| Final affected integrated backend selection | 547 passed, 19 skipped, 1 warning, 5 passing subtests; 174.06 seconds |
| Harness timing, quiet protocol, report gates and diagnostic privacy | 57 passed; 0.30 seconds; reported separately, not added to overlapping suites |
| Repository formatter/lint | 1,477 Python files format-clean; Ruff 0.6.9 lint green |
| Decision coercion gate | No new coercions or stale allowances in touched files; unrelated main debt remains outside scope |
| Independent architecture/correctness review | Green after startup-policy, dependency-closure, strict expiry/configuration fallback and authorized pointer-recovery fixes |
| Full recorded-board functional smoke | Two coherent canonical generations loaded, one live canonical root and zero superseded weakrefs; not acceptance timing |

The first integrated attempt completed with six failures in new tampering-test
setup (reserved metadata fields), 541 passes and 19 skips; it is **not a pass**.
The fixtures were corrected and the entire selection rerun as above. The first
functional smoke was also rejected when a formatter changed pinned policy files
mid-run; its policy-drift refusal is not a passing smoke. A fresh frozen-code
smoke succeeded. No interrupted/failed run is substituted for the final results.

Enabled league reobservation skips lineup/value construction but emits a new
physical artifact because final response timestamps are part of immutable bytes.
It preserves logical canonical parent/input identity and intact roster context;
it is not a physical no-op. Canonical identical publication keeps immutable
content and acceptance age, renewing only its authenticated observation pointer.

New code-policy drift is rejected on verification/publication until restart.
Keys are read from external configuration at verification time; coordinated key
rotation requires new certification and explicit reader restart/revalidation if
already captured LKG memory must be withdrawn immediately. Requests intentionally
do not perform per-request key or disk checks. The local lab only removes the
private-key configuration from the web child; it does not establish cross-account
filesystem isolation. Production signer/web credential isolation is unverified.

### Matched short candidate — unchanged gates

The attested candidate completed 300 seconds of serving exercise, 448.063
seconds total, with 120.907 seconds verified quiet. All 66,476 responses were
coherent; all six changed publications were observed; zero HTTP/errors and zero
remaining observed children. Sampling: 99.9090% complete-resource coverage,
1.047-second maximum reported sample gap, zero missed ticks. All absolute
per-series p95 values were below 75ms. **Relative latency fails; overall FAIL.**

| Series | Warm p95 ms | Refresh p95 ms | Absolute delta ms | Relative delta | Refresh p99 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Rankings 200 | 3.0505 | 16.1133 | +13.0628 | +428.22% | 21.2596 |
| Rankings 304 | 1.6786 | 2.4917 | +0.8131 | +48.44% | 3.3632 |
| Trade 200 | 1.7073 | 2.9721 | +1.2648 | +74.08% | 12.7526 |
| Trade 304 | 1.4424 | 2.3464 | +0.9040 | +62.67% | 3.0030 |

Each ordinary series has 2,628 warm and at least 8,614 refresh observations.
The conditional changed-generation rankings-200 series has only one refresh
sample (1.8236ms); it stays recorded and subject to the existing gate, but is
insufficient for a robust tail estimate. All six generations were independently
observed across responses. Sparse conditional samples are not dropped or called
repeatable performance evidence.

Aggregate RSS: 471,822,336 -> 535,769,088 bytes, +63,946,752 bytes, passing the
unchanged 64MiB allowance narrowly. Web RSS: 384,528,384 -> 435,159,040 bytes.
Previous matched baseline web final was 547,446,784 bytes. Peak sampled process
tree RSS increased from 1,430,814,720 baseline to 1,804,288,000 candidate: moving
validation/expiry construction upstream has a producer/combined peak cost and
is not an across-the-board resource reduction. Worker limits remain unassigned.
Handles 652 -> 657; idle processes return to four, maximum ten. Final disk
511,312,217 bytes remains below 536,870,912; nine retained generations include
six protected generations. Source/league drain took until 326.5s before quiet,
reflecting the cost of final producer representations. No orphaned children.

**Before -> hypothesis -> change -> after -> verdict:** baseline rankings
refresh p95 61.0708ms and failed RSS recovery -> repeated web semantic work and
decoded page/league graphs cause allocation and scheduling pressure -> certified
producer-owned semantics, byte-only page/league adoption and final expiry
representations -> rankings p95 16.1133ms, lower quiet web RSS and short RSS gate
pass -> retain: lifetime and trace diagnostics confirm reduced web work; relative latency still fails.
This single sequential pair does not prove identical host scheduling or field
latency. No full hour is run on this failing short result.

### Allocation ownership and process decision

Untraced isolated lifetime (12 replacement cycles, 316.003 seconds): RSS
366,587,904 -> 424,824,832 bytes; peak observed post-cycle RSS 426,536,960.
CPython arena high-water is 173 from cycle 1 onward; current arenas 103 -> 150,
peaking at 152. Live small-object blocks 106,459,184 -> 106,494,960 bytes
(+35,776). Current arenas are not flat: this supports bounded observed live
ownership and allocator churn, **not a proven long-term RSS plateau**.
One canonical root, one league bundle, 32 byte/payload carriers, 64 serialized
buffers remain; serialized bytes 204,975,194 -> 204,976,163. Superseded canonical
weakrefs remain zero. Earlier shared-decoder cycle 12 RSS 530,841,600 was higher
by 106,016,768 bytes. Graph-count/arena and HTTP quiet observations both support
retaining the reduction, without claiming interchangeable diagnostic protocols.

Six traced cycles show live bytes 279,118,725 -> 281,306,611. Largest positive
delta is 1,922,544 bytes in pathlib parsing, followed by tracemalloc snapshot
comparison allocations; JSON decoder delta is 7,631 bytes. Tracer bookkeeping
alone rises 69,598,320 -> 103,291,984 bytes and perturbs process RSS heavily.
Do not compare traced RSS with the uninstrumented acceptance gate. No product GC
policy changed; diagnostic explicit collection occurs at cycle 0 only for these
runs. Canonical phase creates about 1.104 million net blocks while old canonical
memory remains held by the coherent league capture; league replacement releases
that old graph. Traced transient peak above phase start is about 82.34MB canonical
and 167.28MB league. Those are phase peaks, not summed allocation traffic.

Additional helper-process infrastructure is **not justified by this evidence**.
Producer construction, semantic proof and encoding are already isolated. Passing
required canonical/legacy dict graphs back from another process recreates their
web allocation and eventual refcount/GC retirement. Preserve capture-once APIs.
Any further isolation proposal must demonstrate that its transfer/adoption avoids
that work; an IPC wrapper around the same decoding is not an evidenced fix.

An independent reconstruction of saved request spans confirms a separate latency
question. Using a 16.125ms boundary guard (Windows monotonic 15.625ms resolution
plus 0.5ms saved rounding), every ordinary series has 4,857 wholly verified quiet
samples. Quiet p95/p99 milliseconds: rankings 200 12.7207/17.8728,
rankings 304 1.9558/2.7782, trade 200 2.2439/12.4193, trade 304 1.9124/2.7419.
Rankings remains slow without active workers/reloads. Actual QPC start/end times
were not saved, so interval membership is reconstructed from finish minus elapsed;
it is not a packet trace and does not override the original acceptance result.
Installed client/server code enables TCP_NODELAY; no TCP delayed-ACK cause was
proved. The existing sequential loop sends rankings 200 first after its 10ms
pacing wait, making order/wakeup/body-transfer attribution a follow-up experiment,
not an established product defect. No request order or acceptance protocol changed.


### Completed reload and event-loop attribution

The existing diagnostic harness ran strict and attested adoption separately with
120-second exercises, 30-second baselines/refresh intervals and verified
120-second quiet recovery. These instrumented runs are attribution only. The
strict collector dropped **1,260 spans**; candidate dropped zero. Strict results
below describe retained observations, not a complete matched tail distribution.
Successful league loads are separated from rejected-parent attempts.

| Observed operation | Strict baseline | Attested candidate |
| --- | ---: | ---: |
| Successful canonical adoption median wall / thread CPU ms (5 each) | 1,292.976 / 1,203.125 | 340.019 / 343.750 |
| Successful league adoption median wall / thread CPU ms (7 / 5) | 676.252 / 640.625 | 240.281 / 218.750 |
| Expiry poll p95 / maximum wall ms | 821.159 / 2,061.816 | 0.048 / 0.066 |
| Event-loop delay p99 / maximum ms | 100.170 / 521.766 | 14.106 / 169.320 |
| GC pause p99 / maximum ms | 1.553 / 335.416 | 0.407 / 144.221 |
| Endpoint capture p95 ms | 0.0028 | 0.0028 |
| Canonical swap maximum ms | 0.0168 | 0.0149 |

Strict canonical semantic/parity validation median was 700.034ms and projection
construction 434.923ms. Neither operation appeared in the complete candidate web
trace; payload preparation fell from 56 observed calls to zero. These phases can
overlap enclosing adoption spans and must not be summed. CPU clock quantization
can place reported thread CPU slightly above wall time. Event-loop stalls above
20ms fell from 150 retained observations (140 overlapping background spans) to
29 (12 overlapping); overlap supports contention attribution, not an exclusive
GIL causal proof. GC event counts are not comparable rates because HTTP volumes
and trace completeness differ.

The producer now proves schema, canonical/projection semantics, scoring and
input bindings on serialized bytes before signing. The opt-in web reader proves
exact byte inventory, signature, pinned validation policy, physical generation,
observation authenticity and live canonical/factual/configuration compatibility;
it creates only required domain graphs/indexes and captures final byte references.
The strict path remains the default. Requests retain the capture-once path without
artifact publication locks, artifact reads or projection rebuilding.
No global/manual product GC policy or extra process infrastructure was introduced.

### Final disposition and remaining evidence

**Complete:** narrow implementation, corruption/parity/freshness tests, affected
integrated validation, independent review, matched short comparison, isolated
lifetime/allocation diagnostics and reload traces. The improvement is retained:
web memory and adoption work both decrease, while combined producer peak memory
increases. **Failed:** the unchanged relative-latency gate on all four ordinary
series. The short RSS gate passes narrowly; a long-term plateau is not proved.

Owner-policy questions remain separate. The three smaller increases are only
0.81–1.26ms with refresh p95 below 3ms, so an owner could reconsider that SLO in
a later decision. No exception is applied here. Rankings increases by 13.06ms
and still has 12.72ms quiet p95; this is an unresolved engineering attribution
question, not solely an SLO-policy blocker. These local HTTP timings indicate
possible added response latency, not measured browser useful-state or field UX.

Exact next corrective action: extend diagnostic marks in the existing
`scripts/soak_prepared_serving.py` / `scripts/serving_lab_spans.py` path to separate
first-slot pacing/wakeup, response body transmission and client receipt; use
order variation only as a diagnostic experiment. Identify the responsible owner
before another product change, then repeat the unchanged uninstrumented short
acceptance. Do not add an IPC decoder or alter acceptance ordering/thresholds.
Only a passing readiness decision permits the final hour.

Linux descriptor recovery, installed source/league/news ownership, cross-host
GitHub feed coverage, actual deployment capacity/worker limits, signer/web
credential isolation and authenticated deployed desktop/mobile measurements
remain inaccessible/unverified. Local Windows handles and fixed replay are not
substitutes. Earlier frontend/mobile and historical soak results remain recorded
above; this continuation neither reruns nor promotes them. Canonical input gaps
remain documented and canonical skip stays disabled.

Changed live paths: producer publication/certification and observation recovery
(`src/serving/attestation.py`, `artifacts.py`, `__init__.py`); prepared lifespan and
byte adapters (`server.py`, `runtime.py`, `serialization.py`); league production,
adoption, expiry and reobservation (`league_views.py`, `coordinator.py`). The
explicit crypto dependency is in `requirements.txt`. Existing soak observation,
span and lifetime scripts plus attestation/league/web-adoption/observation tests
supply evidence. Intake/claim records and this campaign carry the disposition.
The numeric summary and source/report hashes are in
`docs/evidence/performance-isolation-2026-09-11.json`; private replay payloads,
credentials and raw traces remain outside version control. No push, merge,
deployment, timer activation or production flag/default change occurred.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No overall readiness claim | Affected tests, lint/coercion and independent review green; main movement classified | Relative latency fails; final resource acceptance absent |
| Shadow mode | Partial local evidence | Coherent reads, protected artifacts and short RSS/sampling gates pass | Final full soak and installed ownership/resource evidence missing |
| Source workers | Partial local evidence | All changes observed; no remaining children; bounded disk | Combined peak 1.804 GB; Linux capacity, ownership and key isolation unverified |
| Prepared backend | No | Auth/isolation/corruption/recovery tests green; 66,476 coherent local responses | Four relative gates fail; full soak and deployed proof absent |
| Prepared rankings/trade frontend | No; disabled | Prior evidence retained; no frontend change | Prior mobile acceptance unmet; deployed measurements unavailable |
| Broader page migration | Outside scope | No migration performed | Requires separate authorization and validation |

**B — NOT READY FOR FINAL FULL SOAK**

## Master completion campaign — owner implementation directive, 2026-09-11

Current candidate is the uncommitted continuation of `564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`.
The approved plan expands the campaign without waiving any intermediate gate.
Root owns the existing driver; an independent implementation unit owns the span
collector; another tests driver plumbing; a separate reviewer can reject evidence.
No new application API, architecture owner or production instrumentation is added.

| Phase | Entry / success requirement | Current state / next permitted work |
| --- | --- | --- |
| 2: Final latency attribution | Repeated timelines plus discriminating controls; category A–G; preserve historical policy/results | COMPLETE AND OWNER ACCEPTED: scoped category D / decision C. Local policy disposition recorded in Phase 3 below |
| 3A: Local short | Accepted Phase 2 and explicit local policy decision; all existing correctness/resources/latency/sampling/quiet gates | PASS: fresh 300s exercise + drain +125.079s quiet under local-prepared-hybrid-v1; all gates pass |
| 3B–C: Full local acceptance | 3A passes; >=3,600s exercise (ten-minute baseline), drain, 125s verified quiet; every existing gate | FAILED / INTERRUPTED: four worker exits, conditional rankings 200 latency failure, terminal sampling gap and no quiet recovery. Local failure attribution is next; Phase 4 blocked |
| 4: Linux/production | Local backend acceptance; actual authorized host access and separate applicable rollout authority | BLOCKED. Read actual resources/ownership/credential separation, then legacy -> shadow -> prepared backend with rollback |
| 5: Rankings/trade browser | PRODUCTION BACKEND READY | BLOCKED. Same useful-state predicate; warm<=1s, normal p95<=2s, cold<=3s, useful/unavailable<=5s; parity/build/bundles and staged frontend activation |
| 6: Remaining important routes | RANKINGS / TRADE SPEED COMPLETE | BLOCKED. Measure route dependencies/cost, prioritize user impact, preserve fast routes; owner approves proposed absent budgets before acceptance |
| 7: Site-wide acceptance | All declared important-route migrations accepted or explicit justified dispositions | BLOCKED. Field/lab/overlap evidence and structural regression guards; unknowns remain blockers |

Phase 2 uses the same private 1,093-player contract/raw bytes and existing signed
artifact architecture. Opt-in QPC driver and external ASGI timings distinguish
arrival, handler/capture, response creation, send and client buffer availability.
Clock exchanges report offset uncertainty; no timestamp is called packet arrival.
Balanced all-24-permutation ordering and original ordering are crossed with
event-wait/continuous/sleep pacing, 60s per cell, three seeded repetitions after
>=120s drained quiet. Separate refresh, ASGI, collector/read-split and conditional
connection controls remain diagnostic only. Missing/censored/dropped observations
are recorded. p99 needs >=1,000 samples. Product corrections require demonstrated
owners and independent review, then affected integrated tests and unchanged
official short acceptance. No SLO parameters/waivers are selected here.

Main fetched to `f7ad36f8096586fe19d98c34ff82ddce91539681`.
The six intervening commits after `f864564e2` are: `2ded57320` IDP observation;
`fdd214c7b` source-freshness/identity status; `c8bdd575a` source CSV/snapshot/export
refresh; `a6de48ed8` Hill refit evidence (champion remains version 2, old versions
unchanged, no applied/promoted new model); `8249aa930` Awards/shared frontend/docs;
`f7ad36f80` Sharp failed-deploy receipt, not production success.
Overall **RELEVANT_BASE_MOVE for integration**: source/UI/shared documents require
bounded reconciliation before shipping. No server/src/scripts/workflow/dependency
or fixed private replay change affects the reused local backend timing evidence.
No merge is performed and live source freshness is not claimed from fixed replay.
Detailed changed paths are preserved in the final latency evidence summary.

Phase 4 retains one unrestricted source owner during shadow; bounded bootstrap
persists strict proof under its lease, then embedded recurring ownership is
disabled before standalone recurrence. Source/league/news/GitHub coverage and
actual Linux FDs, combined headroom and signing-key separation are separate
requirements. Earlier no-push/no-merge/no-deploy authorization boundary persists.
Phase 5 does not retry the rejected hidden-cell change without new evidence.
Phase 6 covers home/dashboard, draft, waivers, rosters, Game Day, player detail,
league comparison, BDVM and expensive finder/comparison surfaces. Structural
guards apply only when appropriate to measured migration dependencies.
Final completeness requires backend, both first routes, important remaining
pages, production resources/field UX and durable regression protection all pass.

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

## Phase 2 final latency attribution — Windows execution, 2026-09-11

**Historical checkpoint:** its policy-blocked status and unchanged-SLO discussion
describe the end of Phase 2. The subsequent owner decision in the Phase 3 section
supersedes that blocker for local acceptance only; measurements are unchanged.

This section supersedes the earlier active Phase 2 entry, without promoting the
historical failed acceptance run. Numeric distributions and provenance are in
[the latency evidence](evidence/performance-latency-2026-09-11.json). The private
1,093-player replay, signed-generation architecture and canonical answers are
unchanged. No product correction was retained in this continuation.

**Primary attribution: D — Connection/loopback.** This is a measured location
classification for the local transport/socket-receive tail, not a proven packet,
ACK, Nagle or kernel mechanism.

**C — LATENCY ATTRIBUTED TO LAB/HARNESS/PLATFORM; OWNER ACCEPTANCE-POLICY DECISION REQUIRED**

Phase 2 implementation, required experiments and independent review are complete.
Phase 3 remains blocked: the currently authorized relative-latency gate still
fails and no owner exception or replacement policy has been approved.

### Measurement boundaries and implementation

The existing driver now records QPC pacing, request/write/header/body timestamps,
connection sequence/establishment, runtime client TCP_NODELAY, actual status,
request kind/slot/phase, gzip length and received bytes. An external lab ASGI
wrapper correlates arrival, endpoint capture/ETag/response construction, response
start and each body send through final completion. Bounded asynchronous writers
report losses; failures retain available timestamps. Experimental options are
refused unless diagnostics are enabled. Ordinary request order, event pacing,
thresholds and serving defaults remain unchanged.

ASGI arrival follows protocol parsing. ASGI send return is a handoff, not network
delivery. A buffered first-byte read is not packet arrival. Whole-body controls
have no first-byte observation; 304 has no body. Socket recv_into controls record
the original buffer sizes, wall/thread CPU clocks and byte counts without content.
Their wall time includes native waiting and thread rescheduling. Client
TCP_NODELAY was observed as 1. The final transport observer directly observed
server TCP_NODELAY as 0; no socket option or OS/network setting was changed.

Driver/server clocks report QueryPerformanceCounter (100ns declared resolution),
GetTickCount64 (15.625ms) and GetThreadTimes. Observed thread CPU values are often
quantized to 15.625ms; zero CPU percentiles do not mean no work. Twelve timestamp
exchanges bound clock offset. Quiet controls include start/end exchanges; refresh
controls only have start exchanges, so drift is unobserved there. Same-process
durations carry the principal attribution. Cross-process midpoint distributions
retain uncertainty and negative values; they are not exact stage durations.
The paired-tail supplement uses a conservative start/end offset envelope where
available. Percentiles of different stages are never added or subtracted.

### Required comparisons and preserved failures

The six order/pacing cells ran 60s each, three seeded shuffled repetitions, after
121.021s observed quiet. Balanced blocks cycle all 24 permutations; completed
blocks have six occurrences of each request type in every slot. There were 708
complete and nine incomplete balanced blocks in the factorial. All incomplete
blocks remain in the evidence. Separate server-collector-off, balanced-off,
split-read, new-connection, original-refresh and balanced-refresh controls ran.
The same initialized ASGI stack consumed and audited complete responses in three
4,096-response batches with the server collector on, and separately off.

Collector-off means server collection off; lightweight driver timing/writing
remains. It measures that observer's contribution, not total instrumentation
overhead. Split reads changed trade timing materially; they are not interchangeable
acceptance samples. Raw app-return control time includes task scheduling, whereas
HTTP timing ends at full body receipt; the evidence also compares corresponding
ASGI boundaries. All new diagnostic p99 tables explicitly suppress p99 below
1,000 observations. Historical acceptance p99 fields are preserved verbatim;
sparse series, including the single conditional-200 observation, are insufficient
for a meaningful p99 and are labelled separately in the evidence.
Rare ASGI maxima around 129–167ms remain recorded.

The original refresh diagnostic had 29,736 audited responses, 120.031s verified
quiet and no errors. Its trade-200 relative check failed. Balanced refresh had
29,424 responses and 120.078s verified quiet; its diagnostic latency checks passed.
Both reports remain overall false because uninstrumentedAcceptance is false.
Resource sampling was complete, maximum gaps below two seconds, all observed
children returned, and protected generations/disk checks passed. These short
instrumented observations do not replace resource acceptance or the full soak.
Phase-labelled postRefreshIdle is selected after response completion and is not
necessarily wholly verified quiet; the actual quiet-recovery interval is separate.

Conditional changed-generation 200s are kept separate from true 304s: original
refresh recorded one trade response (33.6753ms); balanced refresh recorded trade
3.3933ms and rankings 37.5935ms. These are sparse observations, not reliable p99s.

The earlier basic smoke and the compressed-control UnicodeDecodeError are
retained as development observations, not acceptance. Control metadata gzip
decoding was repaired and tested. Subsequent plumbing smokes passed but used
short quiet/cell durations and establish no performance gate.

### Comparisons that reject speculative changes

| Before / hypothesis | Diagnostic change | After | Verdict |
| --- | --- | --- | --- |
| Rankings is uniquely expensive | Balanced order, equal wire bodies and handler spans | Rankings/trade 200 bodies differ by one byte; handler p95 stays sub-millisecond; balanced-off p95 aligns by slot | Rankings-specific compute/size explanation rejected |
| Only the first paced slot pays | All six order/pacing cells, all 24 permutations | Body tails also occur in later slots and continuous requests | Strict first-slot-only explanation rejected |
| Server trace collection creates the whole delay | Server collector off, three repetitions | Rankings p95 remains about 16.17ms | Observer contribution exists; not the complete explanation |
| Body-read splitting fixes the delay | read(1), then remainder | Rankings p95 16.40ms; first byte <0.735ms after headers, remaining body p95 11.95ms | No product correction; observer treatment affects trade |
| Fresh connections remove keepalive penalty | New connection per request | 200 p95 about 31ms including establishment; body tails persist | Rejected remedy; no socket/OS tuning |
| Transport alone explains the recurring p95 tail | Exact captured headers/chunks through frozen ASGI responder | 200 p95 about 2.6ms versus app 16.23/22.25ms | Application timing affects tail frequency; this control alone was insufficient for final attribution |

In the balanced server-collector-off control, rankings/trade 200 p95 by zero-based
slot was 16.3062/16.3209, 27.8109/27.8079, 24.2452/23.9129 and 20.3996/20.2329ms.
In the matched socket-recorded app control, actual receive calls account for most
of the elapsed time: rankings/trade body-receive p95 12.2830/17.7117ms. With frozen
responses this is 0.8181/0.8246ms, although p99 tails remain. The frozen control
bypasses ongoing app/auth/freshness execution and proves captured-byte parity only.


### Final transport discrimination and observer sensitivity

Removing only the lab reload-observation middleware retained all production
middleware and the same response header. Rankings/trade 200 p95 remained
16.3925/25.4035ms over three 60s repetitions. The lab middleware alone is therefore
not the demonstrated owner.

The final opt-in observer wraps the existing Windows Proactor transport write,
native send and existing completion callback. It adds no completion callback,
task or scheduling operation. It records original byte counts, buffer sizes,
send-future state and native completion delivery using a bounded FIFO of captured
request IDs; callback correlation does not depend on the current context.
Completion means entry to the existing `_loop_writing` callback. It does not mean
physical kernel completion or peer receipt. Write/submit/complete totals must
match and all pending watched bytes must drain.

A final app/frozen pair used identical inputs, observer, original order, event
pacing, reused connections and whole-body reads. Each ran three 60s cells after
120.169s / 120.778s verified quiet. Source code remained frozen and no tests,
builds or other measurement ran concurrently. App/frozen recorded
18,630 / 21,254 measured responses. **Every measured response** has unique request
ID, matching submit/return/delivery sequence sets and exact equality of written,
submitted, completed and client-received wire bytes. There are zero missing
ASGI/transport stages, dropped traces, read failures or remaining children.
Frozen endpoint spans are absent by design because the handler is bypassed.
Global counters additionally include warmup/seed traffic and are not added to
the measured counts.

| Final control / route-status / slot | n | Client p50 / p95 / p99 ms | ASGI through final send p95 ms | First write through last native delivery p95 ms |
| --- | ---: | ---: | ---: | ---: |
| App rankings 200 / 0 | 4,659 | 4.6503 / 16.4128 / 31.9188 | 6.7757 | 2.1904 |
| App rankings 304 / 1 | 4,657 | 3.2299 / 5.5571 / 6.2815 | 5.2852 | 0.9996 |
| App trade 200 / 2 | 4,657 | 4.2279 / 23.2743 / 26.7386 | 6.4769 | 2.2446 |
| App trade 304 / 3 | 4,657 | 3.2576 / 5.7172 / 6.7653 | 5.2703 | 0.9371 |
| Frozen rankings 200 / 0 | 5,315 | 2.2157 / 16.2415 / 16.9499 | 2.5087 | 1.8301 |
| Frozen rankings 304 / 1 | 5,313 | 1.3629 / 1.9244 / 2.5441 | 1.0612 | 1.0890 |
| Frozen trade 200 / 2 | 5,313 | 2.1986 / 13.9505 / 27.6521 | 2.2925 | 1.7519 |
| Frozen trade 304 / 3 | 5,313 | 1.3209 / 1.7934 / 2.5947 | 1.0363 | 0.9436 |

For the observed slowest five percent of each 200 series, a positive interval
remains after native completion delivery even at the conservative clock bound:
app rankings **232/234**, app trade **233/234**, frozen rankings **266/267**,
frozen trade **267/267**. Median lower bounds are respectively
**22.1139, 18.3525, 12.0884 and 22.4401ms**. These are paired per-request
calculations, not differences between percentiles. Tail p99 is insufficient
because each tail has fewer than 1,000 samples. The app/frozen recorded clock
offset envelopes are [-1.9656, 2.8142] / [-1.9894, 3.2149]ms (server minus driver).
All watched native send futures were already complete when submission returned.
Neither this nor the callback establishes when data became readable to the peer.

The recurrence is visible in separate repetitions: app rankings p95
15.8528/16.3155/31.3004ms, frozen rankings
16.4183/16.1489/15.9686ms. Trade varies more:
app 23.4034/22.8453/23.6699ms; frozen 26.5797/13.4377/4.7917ms.
Per-cell distributions, incomplete blocks, byte counts and all stage p50/p95/p99
are retained in the JSON; the pooled table does not replace them.

**Before → hypothesis → change → after → verdict:** the earlier frozen control
had 200 p95 near 2.58ms and left an application/transport interaction unresolved.
The hypothesis was that the recurring body tail could persist after native
handoff with application work absent. Adding byte-conserving native transport
observations reproduced that tail in the frozen responder and located almost
every slow 200 after native completion delivery. The verdict is **D**, scoped to
local transport/socket-receive behavior. The observer increased frozen p95 to
16.24/13.95ms; this sensitivity is evidence of timing interaction, not intrinsic
uninstrumented platform latency. It prevents claiming that application scheduling
never influences the tail. No product correction or OS tuning follows.

The ASGI control bypasses TCP and its backpressure: with server collection off,
rankings/trade 200 p95 was 3.7243/3.7551ms; with collection on, it was
4.9077/4.8746ms. Paired server boundaries are also reported because complete ASGI
app return and HTTP body receipt are different endpoints. Together with balanced
slots, near-identical response bytes and the frozen/native control, this rejects
rankings-specific handler work and a strict first-slot explanation. Exact-byte
fast responses do not support intrinsic payload volume as the demonstrated
primary owner. No separately measured product scheduling defect justifies F.
Kernel readiness versus thread resumption, packet/ACK behavior and production
applicability remain unknown within the local D classification.

### Preserved official acceptance and SLO analysis

The last **uninstrumented** official short protocol remains original ordering,
`stop.wait(0.01)`, 300s exercise, 60s baseline, 30s refresh and at least 120s
drained quiet. It is not rerun because this continuation retained no product fix.
All ten recorded product dependencies still hash-identically to that candidate;
new diagnostic timings cannot promote its failed result.

| Official route / actual status | Baseline p95 ms | Refresh p95 ms | Absolute increase ms | Relative increase | Current gate |
| --- | ---: | ---: | ---: | ---: | --- |
| Rankings 200 | 3.0505 | 16.1133 | 13.0628 | 428.22% | Absolute pass; relative fail |
| Rankings 304 | 1.6786 | 2.4917 | 0.8131 | 48.44% | Absolute pass; relative fail |
| Trade 200 | 1.7073 | 2.9721 | 1.2648 | 74.08% | Absolute pass; relative fail |
| Trade 304 | 1.4424 | 2.3464 | 0.9040 | 62.67% | Absolute pass; relative fail |

The prior 66,476 coherent responses, zero errors, adopted generations,
corruption/recovery checks, RSS recovery (+63,946,752 bytes), 99.909% sampling,
1.047s maximum gap and 120.907s quiet remain historical observations. The narrow
RSS pass is not a long-run bound. Phase-labelled idle statistics and the older
reconstructed quiet slice retain their existing timestamp limitations.

The current policy requires **absolute p95 <75ms AND refresh degradation <=20%**
for each required route/status series. It is still binding. With a 1–3ms baseline,
small scheduling shifts produce large percentages. A hypothetical future hybrid
could consider absolute latency, relative degradation and absolute millisecond
delta. Depending on its logical combination, it could avoid rejecting small
absolute changes or could conceal repeated regressions, growing cumulative route
cost and one degraded series. Absolute headroom alone can mask a large relative
regression; a relative rule alone is sensitive to tiny denominators. The
**13.0628ms rankings increase is separate from the 0.8131–1.2648ms smaller-series
increases**. No parameters, formula, exception or policy change is selected or
implemented here.

An owner acceptance-policy disposition is now genuinely required before Phase 3
can be judged: the evidence identifies a local lab/platform tail, while the
authorized Windows relative gate still fails. Until an explicit decision is
recorded in the existing intake/authorization records, the gate remains failed.
No hour run is authorized by this attribution.

### Validation, reconciliation and deliverable ledger

This latency continuation changes exactly these tracked paths:
`scripts/soak_prepared_serving.py`, `scripts/serving_lab_spans.py`,
`tests/serving/test_lab_spans.py`, `tests/serving/test_latency_diagnostics.py`,
`docs/PERFORMANCE_CAMPAIGN.md`, `docs/evidence/performance-latency-2026-09-11.json`,
`docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md` and `docs/WORK_CLAIMS.md`.
Other existing uncommitted product changes belong to the preceding candidate
work and remain preserved. Private offline analysis and raw observations stay
under the ignored existing lab directory.

Current final validation: **155 tests passed in 8.68s** across
`test_lab_spans.py`, `test_latency_diagnostics.py`,
`test_soak_observation.py` and `test_soak_report.py`. They cover clock/correlation
ordering, final body sends, 304/no body, reconnect/timeouts, seeded ETags, balanced
slots, bounded losses, privacy, experiment-option rejection, disabled defaults,
frozen responses and exact transport delegation/conservation. Ruff 0.6.9
repository formatter/lint passed for 1,478 Python files. Decision-coercion checks
passed in touched files (eight unrelated main differences retained); planning
integrity passed. Independent implementation/correctness and final attribution
review approved after the recorded fixes and offline ID/sequence assertions.

The earlier integrated result is **547 passed, 19 skipped, one warning and five
passing subtests in 174.06s**; counts overlap and are not summed. Existing frontend
**2,519 tests / 175 files**, production build, **14/14** bundle budgets,
**9/9** browser smoke and **27/27** privacy observations remain prior evidence,
not new runs. Slowed mobile still fails. No frontend or value/ranking product
logic changed in this continuation.

Final fetched main is `e5b0ac127fcbb6d078eeda0f15378c0b3821a169`;
candidate remains uncommitted on `564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`.
Last reconciled main is `86d20e6cae3f75b6c5d58a084882f4115e3e6e19`.
The earlier source/shared-frontend movement remains **RELEVANT_BASE_MOVE for
integration**, with no changed fixed-input backend dependency. Later commits
`25bb6d0fd`, `495fe42df`, `e5b0ac127` change a deploy receipt or four IDP
observation timestamps; they are **BENIGN_AUTOMATION_MOVE** for these comparisons.
The Sharp receipt's 401/unverifiable smoke is not production evidence. Exact
commit SHAs and changed paths are in the artifact. No main reconciliation merge,
push, deployment, timer or flag change was performed.

| Existing deliverable area | Current disposition / evidence |
| --- | --- |
| Architecture and live request path | Existing certified generation → lightweight adoption → captured prepared bytes preserved; only the lab adds opt-in wrappers |
| Baselines, inputs and payloads | Same 1,093-player replay/raw hashes; per-run source hashes and all response-byte distributions recorded |
| Frontend/browser comparison | Prior suite/build/parity preserved; mobile failure retained; Phase 5 not entered |
| Resource and retention evidence | Earlier corrected short RSS and retention evidence preserved; diagnostic refresh cleanup clean; final hour absent |
| Backend correctness | Prior integrated pass preserved with ten unchanged product hashes; current diagnostic/accounting tests green |
| Ownership and rollout | Existing staged procedure retained; actual Linux ownership, FD recovery, headroom and signing-key separation unverified |
| Canonical dependency gaps | Existing factual league context, clock boundaries, transactional history and cached configuration dispositions retained; canonical skip disabled |
| Instrumentation/privacy | Bounded local timeline/native observations, explicit missing/lost stages, sanitized aggregate artifact; replay/keys/raw traces remain private |
| Independent review and decision | Scoped D attribution / Phase 2 C approved; official relative failure unwaived |
| Next permitted action and authorization | Owner acceptance-policy disposition; Phase 3–7 entry gates remain in force |

No authenticated deployed-candidate measurement or Linux host inspection was
collected in this Phase 2 continuation. Actual RAM/headroom, service limits,
Linux FDs, current source/league/news/GitHub publishers, credential permissions,
real authenticated 200/304 behavior and field UX remain unverified; local Windows
handles and synthetic authentication do not substitute. The remaining-page
inventory, budget approval and migration are gated future work, not completed
architecture exceptions.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No overall readiness claim | Current affected tests/review green; main movement classified; product evidence retained | Relevant integration reconciliation and acceptance-policy/local gates pending |
| Shadow mode | Not rollout ready | Local parity, retention and failure/recovery evidence retained | Final local acceptance and actual Linux/production validation absent |
| Source workers | Locally implemented; production unverified | Producer separation, leases/proofs and bounded cleanup preserved | Installed cross-owner cutover, combined headroom, Linux FDs and signing authority separation unverified |
| Prepared backend | Not accepted for rollout | Thin captured reads; scoped local latency attribution complete; correctness retained | Current relative SLO fails; owner disposition and final acceptance required |
| Prepared rankings/trade frontend | No; keep disabled | Existing semantic/build/bundle evidence | Slowed-mobile useful-state failure; production backend gate unmet |
| Broader page migration | Not started under this gate | Reusable serving architecture available | Phase 5 completion, measured inventory and owner-approved missing budgets required |

**PERFORMANCE MODERNIZATION INCOMPLETE — REMAINING BLOCKERS: owner acceptance-policy
decision and passing local gates; final full soak; Linux/production ownership,
resources, credential separation and authorized rollout; mobile useful-state
acceptance; remaining-route budgets/migration; field and site-wide verification.**

## Phase 3 local backend acceptance — owner decision, 2026-09-11

**Status: Phase 3A PASS; Phase 3B FAILED / INTERRUPTED. Phase 4 blocked.** Phase 2
category D and outcome C are accepted; no speculative rankings/backend correction
follows. The local acceptance-policy blocker is resolved by explicit owner decision.

Start reconciliation fetched main `d243a1f7f1edfe85048f8fd10831adb41e54fb79`.
After the Phase 2 checkpoint, `802752c6f` changes source freshness/identity/KTC
state (including captures/divergence, not only timestamps); `2a18436e3` changes
43 CSV/workbook/source/ROS/Sleeper/export paths; `d243a1f7f` changes Hill evidence.
The served Hill champion remains v2, its complete record and all 28 prior versions
are identical, and new v29/v30 are challenger/rejected, neither applied nor promoted.
All three are **RELEVANT_BASE_MOVE for integration** because canonical source/config
hashes consume these paths. No serving code, test, workflow or dependency changed.
The saved private replay and all ten product fingerprints are unchanged, so these
fixed-input comparisons remain valid. No reconciliation merge is performed.

For the current local prepared-backend campaign only, select
`--latency-policy local-prepared-hybrid-v1` and require:

```text
refresh p95 < 75 ms
AND
(relative refresh degradation <= 20%
 OR (absolute refresh p95 increase <= 15 ms AND refresh p95 <= 25 ms))
```

This supersedes only the former percentage-only secondary local requirement.
It is an acceptance-policy correction following measured lab/platform attribution,
not a waiver of a known application defect. Existing baseline/refresh definitions,
observations, percentile calculation, request mix/order/pacing, conditional-200
comparisons and absolute baseline/quiet gates remain. Missing observations fail.
The previous policy remains the CLI default for other invocations; historical
reports are preserved verbatim and are not substitutes for the newly requested runs.

Phase 3A uses the same private 1,093-player replay/input hashes and signed-artifact
setup: diagnostics disabled, 300s exercise, 60s baseline, 30s refresh, complete
worker/reload drain and 125 continuous verified quiet seconds. Require every
existing correctness/generation/corruption/recovery, RSS, handles/process cleanup,
retention/disk gate, >=99% complete sampling and <=2s acquisition gaps. The RSS
allowance remains max(10% of warmed baseline, 64 MiB). Stop builds, tests and
unrelated measurements; freeze code before measurement.

Only if every short gate passes, Phase 3B proceeds automatically with a fresh
3600s serving exercise including a 600s baseline, 30s refresh, complete drain and
125 continuous verified quiet seconds outside the exercise. Same semantics,
inputs, resources and hybrid rule; no historical hour substitutes. Failure blocks
advancement and must identify its owning path and corrective action.

A passing full run yields **LOCAL BACKEND ACCEPTANCE PASS**, then Phase 4 may
inspect actual Linux/production resources and ownership read-only under available
authority. This does not change production SLOs, frontend/mobile useful-state,
Core Web Vitals, field/RUM or unrelated endpoint/route budgets. No merge, deployment,
production-unit installation, timer/flag change or prepared frontend activation
is authorized here. Existing Phase 4–7 gates and required owner approval for new
Phase 6 route budgets remain in force.

### Phase 3A observed acceptance

Policy implementation and tests are complete: 230 affected lab/policy/resource
tests passed in 7.39s, required Ruff 0.6.9 formatter/lint (1478 files), coercion and
planning checks passed. Independent policy/correctness review approved after the
invalid-observation reporting fix. Tests are completed before acceptance, not run
concurrently. Only the lab evaluator/reporting and its tests change executable code.

Fresh `phase3-short-01` **PASS**, report SHA256
`f20eb1e2dc282123265463bc3355e7eee14100e444cb685de41e69e9d594b28c`:
300s serving exercise /60s baseline /30s refresh, diagnostics disabled, unchanged
original order/pacing. 49,292 audited responses, zero errors/coherence failures,
all changed generations adopted, and all corruption/recovery/retention gates pass.
125.079s continuous verified quiet follows drain, with no quiet resets.

| Route / actual status | Baseline p95 ms | Refresh p95 ms | Hybrid verdict |
| --- | ---: | ---: | --- |
| Rankings 200 | 17.0136 | 16.4121 | Pass; relative and absolute branches |
| Rankings 304 | 5.2002 | 4.8661 | Pass; relative and absolute branches |
| Trade 200 | 25.5469 | 22.3134 | Pass; relative and absolute branches |
| Trade 304 | 5.2143 | 4.7123 | Pass; relative and absolute branches |
| Trade conditional changed-generation 200 | 25.5469 (normal body baseline) | 28.8685 | Pass via relative branch (+13.002%); absolute branch fails |

All prior relative-rule checks also happen to pass in this fresh run; the policy
change is not credited as a measured latency optimization. Sparse transition
observations retain their counts and insufficient-p99 labels.

Aggregate RSS 482,064,384 →548,564,992 bytes (+66,500,608; allowance67,108,864),
a narrow pass. Web RSS 387,258,368 →437,342,208; driver RSS
94,806,016 →111,157,248. Peak process-tree RSS1,830,502,400 bytes, maximum10
processes. Handles652→657;39 observed children, zero remaining/reparented/unknown.
Disk511,311,784 bytes stays below the536,870,912-byte lab budget.

450 complete observation samples plus one post-cleanup sample; complete coverage
100%, maximum **acquisition-start gap1.109s**. The legacy displayed completion-time
gap is2.078s (a disk-observation stage took1.024s); it is retained separately and
does not replace the established full-precision acquisition-start gate. Code and
input/source fingerprints match the frozen start and end. Main re-fetched before
full acceptance remains `d243a1f7f1edfe85048f8fd10831adb41e54fb79`.

This pass authorizes the fresh full run. It is not local full acceptance or
production readiness; the narrow short RSS recovery must still survive the hour.

### Phase 3B observed failure and incomplete exercise

After the independently verified short pass, `phase3-full-01` ran with a new
private store, the identical frozen code/replay/signing setup, diagnostics off,
original request order/pacing, requested 3600s exercise /600s baseline /30s refresh
and 125s quiet after drain. Its report SHA256 is
`6bc4e260451b94ad6f4a3181c0cd4c312eba49712657d0fead3d9313892885d2`.
**FAIL / INTERRUPTED**; this is not a completed or accepted hour soak.

The sanitized [Phase 3 evidence](evidence/performance-local-acceptance-2026-09-11.json)
contains separate reports, every policy branch and gate, per-series p95/p99/counts,
CPU/resource distributions, worker events, independent raw-record checks and
SHA256s of the private reports/request/sample/sampler/quiet/latency files.
Private replay, signing keys and raw evidence remain in the existing private lab
directory. Only this phase's evaluator/reporting and report tests change executable
code; no application API, product behavior or production configuration changed.

324,316 recorded responses had zero HTTP or response-audit errors. All published
changed generations were observed; corruption/recovery and pressure scenarios
were exercised. However, four unchanged source workers exited 1 at 1054.453,
1458.610, 2432.906 and 2904.672 seconds (sequences 9, 18, 36, 45). Of 46 completed
ordinary source cycles, 31 changed and 11 unchanged succeeded, four unchanged
failed; all 47 completed independent league cycles succeeded. The required
zero-unexpected-failure gate fails independently of the later host interruption.

| Full attempt route / actual status | Baseline p95 ms | Refresh p95 ms | Delta ms / percent | Relative branch | Absolute branch | Verdict / refresh n |
| --- | ---: | ---: | --- | --- | --- | --- |
| Rankings 200 | 16.4296 | 16.5830 | +0.1534 / +0.934% | Pass | Pass | Pass /64,381 |
| Rankings 304 | 4.5536 | 4.7967 | +0.2431 / +5.339% | Pass | Pass | Pass /64,371 |
| Trade 200 | 20.9147 | 22.5871 | +1.6724 / +7.996% | Pass | Pass | Pass /64,380 |
| Trade 304 | 4.2731 | 4.5662 | +0.2931 / +6.859% | Pass | Pass | Pass /64,377 |
| Trade conditional changed-generation 200 | 20.9147 (body baseline) | 3.3985 | -17.5162 / -83.751% | Pass | Pass | Pass /3; p99 insufficient |
| Rankings conditional changed-generation 200 | 16.4296 (body baseline) | **52.8267** | **+36.3971 / +221.534%** | **Fail** | **Fail** | **FAIL /8; p99 insufficient** |

Every observed p95 remains below the unchanged 75ms absolute ceiling; this does
not override the failed secondary branches. The pooled hybrid passes (6.1279 to
9.8294ms, +3.7015ms /+60.404%), while the per-series gate fails. Old relative
pooled/per-series failures are retained as informational fields, not extra vetoes.
The eight rankings transition observations occurred between 1227.438 and 2959.750s,
before the terminal gap; maximum53.3520ms. Keep their failure despite sparse p99.
The three trade transitions have maximum28.0586ms; the unchanged percentile
function produces p95=3.3985ms. No interpolation or sparse-series waiver is added.

| Run / route | Baseline p95 / p99 ms | Refresh p95 / p99 ms | Post-refresh p95 / p99 ms |
| --- | --- | --- | --- |
| Short rankings 200 | 17.0136 /43.3416 | 16.4121 /32.4541 | 16.2862 /31.2052 |
| Short rankings 304 | 5.2002 /5.7328 | 4.8661 /5.7488 | 3.6100 /4.7787 |
| Short trade 200 | 25.5469 /28.3404 | 22.3134 /26.8930 | 11.8853 /27.0704 |
| Short trade 304 | 5.2143 /5.9883 | 4.7123 /5.7451 | 3.2989 /4.3948 |
| Full attempt rankings 200 | 16.4296 /52.2279 | 16.5830 /54.0888 | 42.8630 /insufficient (n71); no verified quiet |
| Full attempt rankings 304 | 4.5536 /5.5047 | 4.7967 /6.8008 | 4.7652 /insufficient (n73); no verified quiet |
| Full attempt trade 200 | 20.9147 /26.7774 | 22.5871 /26.9876 | 8.5594 /insufficient (n73); no verified quiet |
| Full attempt trade 304 | 4.2731 /5.2784 | 4.5662 /5.9177 | 3.7382 /insufficient (n73); no verified quiet |

These post-refresh HTTP phases use the existing classification. They are not
identical to the verified resource-quiet window; the short run verifies 125.079s
quiet separately, while the full attempt verifies none. Every unqualified p99
above has at least 1000 observations. Conditional-200 p99s are insufficient in
both runs; the artifact retains all original values and counts with that label.

| Resource / observation | Short pass | Failed full attempt |
| --- | --- | --- |
| Complete resource observations | 450/450;100% coverage | 2998/3000;**52.9896%** of elapsed observation period |
| Maximum acquisition-start gap | 1.109s | **2658.719s** terminal gap;1.172s maximum internal pre-gap start gap |
| Verified quiet after drain | 125.079s | **0s**, `quiet_drain_timeout` |
| Aggregate baseline -> quiet RSS bytes | 482,064,384 ->548,564,992; allowance67,108,864 | 486,948,864 ->unavailable |
| Web baseline -> quiet RSS bytes | 387,258,368 ->437,342,208 | 389,402,624 ->unavailable |
| Peak observed web / process-tree RSS bytes | 587,784,192 /1,830,502,400 | 664,694,784 /1,864,503,296 |
| Windows handles baseline -> quiet; peak | 652 ->657;1331 | 645 ->unavailable;1330 |
| Processes idle / maximum / after cleanup | 4 /10 /1 | 4 /10 /1 |
| Observed children / remaining / unknown | 39 /0 /0 | 291 /0 /0 |
| Host CPU median / p95, all recorded observations | 29.4% /38.8% | 20.3% /30.3%; missing interval unmeasured |
| Observed process-tree CPU seconds per sample median / p95 | 1.3359 /2.4375 | 1.5625 /2.5781; completed-child CPU may be missed |
| Final disk bytes / budget | 511,311,784 /536,870,912 | 511,312,467 /536,870,912 |
| Retained / protected generations at final dry-run | 9 /6 | 9 /7; oldest2026-09-11T22:49:18.596380Z |

The full attempt's peak disk observation is511,313,252 bytes, within budget;
final retention is unblocked with no shortened rollback window. A prior capacity
failure receipt matches the deliberately exercised rejection scenario. Windows
handle counts are not Linux FDs. All observed descendants were cleaned up, but
no final quiet RSS or handle median exists. Their fail-closed gates indicate
**missing recovery evidence**, not demonstrated sustained memory growth/leakage.

Raw HTTP ends at3000.016s; the last resource acquisition starts2999.000s and
ends2999.719s. Report elapsed read-observation time5657.719s includes the terminal
gap; `servingExerciseSeconds=3600` is a cap-derived field, not proof of continuous
serving. `full60MinuteSoak=false`. Two pre-gap resource observations, at1458s and
1911s, were incomplete with three unknown process observations each; web samples
were complete. These are preserved independently of the terminal interruption.
The largest sampler flush wall span is2657.985s and disk span12.766s.

Read-only Windows power logs record battery-triggered sleep at22:54:44Z and
resume-from-hibernate at23:39:05Z, among the retained transitions. The tool host
also reset during this interval; the original process was reattached and its
exit1 report collected, without duplicate execution. This supports a host
interruption during the observation gap; the precise contribution of each power
transition to the blocked flush is not separately timed. The lab already used
its temporary system-awake request. No saved power or network settings changed.

### Failure owners and next permitted action

| Failed condition | Owning path / evidence limit | Exact corrective action |
| --- | --- | --- |
| Four unchanged worker exits | `scripts/soak_prepared_serving.py` source `worker()` -> `league_worker()`; child completion discards piped stderr from `communicate()` | Capture bounded private stage/exception evidence and reproduce one unchanged/concurrent-league overlap in a fresh replay store. The 20s fixture lease wait is a hypothesis, not a recorded exception. If confirmed, align the fixture's follow-up busy outcome with the existing production owner and preserve queued-work/adoption/quiet assertions |
| Rankings conditional changed-generation 200 hybrid failure | Existing conditional HTTP series; actual handler/transport owner unmeasured in this uninstrumented run | Use the existing opt-in driver/span lab for generation-transition responses during overlap and a discriminating control. Keep baseline/order/pacing/percentile/thresholds fixed; no speculative rankings correction or sparse-series waiver |
| Sampling coverage/gap and unverified drain/quiet/RSS/handles | `resource_observations()`, `QuietRecovery`, Windows execution host; battery sleep/hibernate events and terminal observation gap | After attributing/correcting demonstrated failures and affected validation, freeze code on a reliably powered uninterrupted host; rerun fresh short, then full only after every short gate passes. Never count suspended time as observed exercise |

Production league refresh treats a contended lease as a `busy` follow-up; the lab's
nested league worker instead has a hard20s wait that can propagate failure. Each
failed source exit precedes its paired successful league exit by0–2s, supporting
that hypothesis. Nonweb stderr used a pipe and was read then discarded; it was
not sent to `DEVNULL` (that applies to the web child). The historical exception
cannot be reconstructed from the final accepted pointer. No unproven fix is made.

Independent review confirms the short pass, all eight transition observations,
the four pre-gap worker failures, code/input fingerprints, child cleanup and the
incomplete-hour disposition. Required pre-run tests remain230 passed; the report
file's95 tests are included in that count. No concurrent builds/tests ran during
acceptance. Final planning-integrity, whitespace, artifact/report consistency,
raw-artifact hash and privacy checks pass after the evidence update;
product/frontend results remain prior evidence.

Final fetched main is `4033052cf9bc48b3c8ec5ff160205d995165ef6f`.
Its four IDP status/success path changes only advance observation timestamps;
success/acquisition/row counts and payload remain unchanged. This is
**BENIGN_AUTOMATION_MOVE for fixed-input comparison**. Earlier relevant source
movement still requires integration reconciliation. Candidate HEAD remains
`564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`, last reconciled main remains
`86d20e6cae3f75b6c5d58a084882f4115e3e6e19`; exact SHAs/paths and frozen code/input
hashes are in the artifact. No merge, push, deployment or production inspection
was performed. Full acceptance did not pass; Phase 4–7 remain gated.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No overall readiness claim | Policy/reporting implemented;230 affected tests, formatter/lint/coercion and review green | Relevant main reconciliation and failed full local acceptance |
| Shadow mode | Not rollout ready | Existing local parity/retention/corruption evidence preserved | Local full acceptance and Linux/installed ownership/headroom proof |
| Source workers | Partial local evidence | Changed cycles adopted;291 observed children cleaned up | Four unchanged-worker failures; causes unproven; production ownership/FD/key isolation unverified |
| Prepared backend | Not locally accepted | Fresh short passes hybrid;324,316 full-attempt responses have no HTTP/audit errors | Conditional rankings latency, worker failures, incomplete hour and absent recovery |
| Prepared rankings/trade frontend | No; disabled | Prior semantic/build/bundle evidence retained | Slowed-mobile useful-state failure; production backend gate unmet |
| Broader page migration | Not started under this gate | Existing reusable architecture | Phase 5 completion, measured inventory and owner-approved missing budgets |

**PERFORMANCE MODERNIZATION INCOMPLETE — REMAINING BLOCKERS: failed full local
acceptance (source-worker exits, conditional rankings latency, interrupted sampling
and unverified quiet recovery); Linux/production validation and authorized rollout;
mobile useful-state acceptance; remaining-route budgets/migration; field and
site-wide verification.**

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc

## 100-assignment execution — 2026-09-12 UTC

The owner approved execution of exactly 100 numbered assignments using Commander
000 and three reusable worker slots. The authoritative `performance-swarm` record
uses the existing local Steward store, revision checks and immutable evidence.
The [sanitized snapshot](evidence/performance-swarm-2026-09-12.json) distinguishes
dispatch, execution, review and acceptance. All 100 missions are preserved;
unexecuted assignments remain queued. Root alone updates shared campaign records.

The candidate remains uncommitted on `564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`.
The start fetch reached `7631e233a937faaf7c795c3430e6b5cf40e35bda`. Assignment
004 independently inspected the four commits after `4033052cf`: observation,
source/KTC/export and model-registry inputs make them relevant for integration.
IDP Show changes only timestamps; DraftSharks IDP changes eleven age cells;
KTC values change. Hill champion 2 and all thirty prior version records remain
identical. No serving implementation path changes. All ten recorded application
fingerprints and both private replay hashes match the previous full attempt.
No merge, pull over another owner's checkout, push or deployment was performed.

### Worker failure attribution and bounded capture

The existing soak driver now captures one bounded, structured completion record
per ordinary child through its existing output channel. Records distinguish
canonical publication from league follow-up and retain exception class/numeric
OS error without exception messages or arbitrary stderr. Missing, malformed or
duplicate records fail the ordinary-worker checks. Collection is capped at 8 KiB
per record and 1,024 records per run; reader cleanup and loss counts are explicit.
Assignment 018's focused validation passed **67 tests in 0.76s**. This is protocol
and cleanup evidence, not an acceptance run.

Two independent executions used fresh private stores, the same 1,093-player
replay and frozen driver `e65cd62e217db5e8c38606e7f0b751438e82e02a34dc568359bb9b40819543a5`.
They invoked the existing lab functions without starting providers or HTTP load.

| Observation | Assignment 007 | Independent assignment 008 |
| --- | --- | --- |
| Total controlled invocation | 70.719s | 65.563s |
| Uncontended unchanged worker | Success | Success |
| Held league lease | 22.359s | 22.109s |
| Contended source outcome | Canonical accepted, then `league_admission` / `PublishLockTimeout`, exit 1 | Same; pointer advanced while source child was still alive |
| After lease release | League preparation, queued-marker consumption and strict canonical binding pass | Same, with source-lease reacquisition and exact three-record checks |
| Observed children / remaining / unknown | 9 / 0 / 0 | 9 / 0 / 0 |
| Code and input hashes | Unchanged | Unchanged |
| Scoped sleep prevention | Acquired and released | Acquired and released |

Assignment 007 passed eleven checks; 008 passed seventeen. Their immutable packet
hashes are `0b972e743640b598da37674341227c3b734c86fc153840996287a32ddcb27054`
and `47d5810d090836b2c3ec22c1210656be7f0d09867588c655f82af08a2f3a27f7`.
This proves the controlled admission-timeout mechanism. It cannot recover the
four historical exceptions, which remain unknown. Neither execution proves
HTTP latency, sustained resources or final quiet acceptance.

The permitted correction is limited to failed outer league admission, with a
bounded queued follow-up that prepares the latest accepted canonical generation.
Canonical errors, errors after admission and unknown exceptions must still fail.
A successful companion worker is not proof that a newer canonical generation
has been prepared. Implementation and independent review are in progress.

The production audit separately found that `refresh_league_serving` caught
`PublishLockTimeout` across both admission and admitted work. Real held request
and store locks reproduced incorrect `busy` results. Assignment 020's minimal
correction preserves errors after admission; its focused pipeline/follow-up
selection passed **13 tests / 54 deselected**. Independent assignments 090 and
091 each approved the exact four-line correction and ran six focused checks
separately. These overlapping checks are not added together. Affected integrated
validation remains required before measurement release.

### Measurement and gates

Assignment 016 adds explicit requested duration, elapsed lifetime, recorded
resource/HTTP boundaries and verified quiet duration. It does not infer a
continuous hour from a capped elapsed field. Its focused observation selection
passed **64 tests**. Assignment 014 adds default-off adoption/selected-byte
correlation and bounded loss accounting; its span selection passed **49 tests**.
These selections overlap existing evidence and are not summed. Driver integration
and independent measurement review remain in progress.

The current policy is still `local-prepared-hybrid-v1`; its legacy default,
75ms ceiling, 20% relative branch, 15ms/25ms absolute branch and all resource,
sampling, coherence and quiet gates are unchanged. No new short or full acceptance
has started in this continuation. Conditional rankings latency remains unresolved.
The next measurements are the specified natural-transition and body-equivalent
controls, followed by fresh short acceptance and a full run only if every short
gate passes. Phase 4 activation, prepared frontend and later migration acceptance
remain gated; independent preparation may proceed.

The first complete driver review snapshot was
`fb49ef562383fd7ada24d3fd8351220e354c102b96b90698616165648d2c89a1`.
Its focused report/diagnostic selection passed 175 tests. The preceding selection
recorded 240 passes and two supervisor fixture failures; it is not a pass.
Additional busy/deferred-work regressions and review corrections are underway.
Direct inspection identified missing current-generation 304 and exact compressed
body comparisons in the new stale-ETag control. Independent review also found
that a cleanup timeout could escape before remaining cleanup and failed-report
serialization. These are open lab defects, not measured application latency
owners. Discarded worker-output accounting must be explicit. The existing
`full60MinuteSoak` field qualifies the observation window; all required checks
and `passed` must also pass before full acceptance can be claimed.

The read-only host preparation observed AC power, available memory/disk and a
successful scoped awake request. Assignment 003 classified the current 21
previously unclassified processes as Codex-packaged support runtimes using
executable paths and ancestry privately. This does not reconstruct historical
process identities or guarantee zero interference. No process or persistent
power setting was changed. Assignment 098 must recheck the host and reserve it
after tests, builds and code changes stop; preparation is not release.

### Resumed execution checkpoint — 2026-09-12 07:14 UTC

The owner renewed the same completion instruction. Agent-OS-Receipt:
`af1d50a577c96fd9eed9f934a902a9469f8b69bc`. The candidate and historical
evidence are preserved. New main is `e94d9977f85fa5b216f823cc5fc6bf809459edca`;
assignment 004 classified six intervening commits as relevant source/data
movement for integration, with no changed executable, frontend, test, workflow
or dependency paths. Both fixed private replay hashes remain unchanged. No
reconciliation merge or modification of another owner's checkout occurred.

The preceding execution completed the reviewed worker receipt/deferred-follow-up,
collector-close and duration-accounting corrections. The final lab selection on
driver `bb8a6b8e` passed **425 tests in 10.47s**. Affected integrated backend
validation recorded **545 passed, 5 failed, 19 skipped**, with five passing
subtests and one warning. The five failures occurred in existing source scanners
reading UTF-8 files with Windows cp1252 before their assertions. An exact
five-test rerun with process-local `PYTHONUTF8=1` passed in 0.89s. These are
separate results, not an uninterrupted green suite or additive coverage.

The 180-second plumbing invocation ran from 02:48:28 to 02:52:20 UTC on the
same 1,093-player replay with diagnostics enabled and only 15 seconds of required
quiet. Its original report SHA256 is
`dad1d01607892ffa7df0232a8b1f43937229e6bc84f42eec58f94c20f97c56ad`.
It recorded **26,141 coherent responses**, zero HTTP/worker errors, five
successful deferred league follow-ups and 52 observed children with none
remaining or unknown. Actual verified quiet was 15.062s, complete sampling 100%,
and maximum acquisition gap 1.016s. Aggregate RSS was 488,247,296 to 545,812,480
bytes; Windows handles 672 to 688; peak process-tree RSS 1,670,377,472 bytes;
final store 511,311,793 bytes under the 536,870,912-byte lab budget. These
diagnostic observations are **not** official resource or latency acceptance.

Independent offline audit verified all measured request IDs, status/body-byte
and captured-generation joins through final ASGI send. Driver/server collectors
wrote 26,141/445,596 events with zero losses and verified closure. Opening and
closing clock exchanges were present. The 27 failed off-request league-load
brackets remain reason-unassigned; no request error or lost stage was observed.
Native transport and a separate first-byte read were deliberately absent.

The original smoke remains **failed**: besides diagnostics disabling acceptance,
its adoption evaluator incorrectly included four new `worker_outcome` receipts
without publication identities. All four actual changed `refresh` publications
were independently observed through HTTP. Assignment 010 now restricts the
evaluator to actual publication events; assignment 021's **102 report tests
passed in 1.17s**, preserving missing/unseen-generation failure and independent
worker-failure vetoes. Assignment 090 independently approved the source/raw
evidence discriminator. The old report is not rewritten or promoted.

Assignment 026 then reproduced a separate material dependency-admission defect:
missing required parents could replace an accepted pointer when pruning failed
closed but capacity still allowed publication. The actual prepared-news
publisher reproduced it after controlled pruning removed its captured canonical
parent. Unrelated corrupt-history repair still succeeded without deletion.
Assignment 020 is correcting candidate dependency validation within the existing
store, before pruning or pointer replacement; regression and independent review
remain required. No speculative latency product change follows from this defect.

The prescribed three 900-second transition diagnostics, stale-ETag controls and
fresh official short/full runs have **not yet run**. The authoritative 100-row
board retains unexecuted missions as queued and distinguishes preparation from
acceptance. No production rollout, prepared frontend activation or campaign
completion is claimed.

Checkpoint recorded at 2026-09-12 07:53:00 UTC.
### Swarm retained corrections and validation checkpoint

The resumed 100-assignment campaign has retained two bounded corrections, each
with independent review. ArtifactStore now verifies a proposed publication's
required dependency closure before any pruning or pointer replacement. A healthy
publication may repair only its own corrupt pointer after immutable dependencies
verify; uncertain old pointer state still forbids all pruning. The first version
broke healthy news recovery (22 prepared-news passes / one failure); that result
is preserved. The corrected store independently passed 100 retention/artifact/news
tests with six filesystem capability skips. Its source SHA256 is
`32751ccb2670ac3467496989ed2bb4200a9f002727f2a758ec476a63ca84d91e`.

The signing policy now includes the directly executed scoring-season helper
`src/bdvm/actuals.py`. An isolated same-size, same-mtime semantic mutation proved
that the prior policy did not notice this dependency. The corrected policy and
its restart/recertification cases passed 44 tests independently; this proves the
specific omission is closed, not complete executable/runtime dependency coverage
or production signer separation. Policy source SHA256 is
`49f10c17f62a4f974ad40a29680f05716989f85572f1bdc7e75e045d5af34f8f`.

Final lab regression selection: **494 passed in 22.49 seconds**. Required Ruff
0.6.9 checks report 1,479 format-clean Python files and clean lint; whitespace,
decision-coercion and planning-integrity checks pass. Counts overlap earlier
selections and are not summed. The fresh broader backend selection is still
running with failures; these focused results do not replace that integrated gate.
No prescribed 900-second transition experiment, fresh official short acceptance,
or full soak has started at this checkpoint. The candidate remains unaccepted.

The immutable mission store also records a correction to a null-content import
for assignment 034 attempt 2. That erroneous receipt is not execution evidence;
the subsequently sealed actual packet has its own distinct receipt. Dispatch,
execution, preparation, review and acceptance remain separate facts.

### Swarm integrated validation and measurement hold — 2026-09-12 08:24 UTC

The final dependency-admission correction also preserves healthy replacement of
an otherwise corrupt predecessor in the same partition. Its immutable manifest
must still establish identity; uncertain predecessor bytes are quarantined in
the retention inventory, cannot satisfy a dependency, count against capacity,
and prevent pruning. Missing or ambiguous required parents remain rejected.
The earlier integrated failures and the first recovery regression remain
historical evidence. Final ArtifactStore SHA256:
`76b6e1047b89e43b5edb09e7802dd908fa817b0861eb3fbb90f9c66e137d6a26`.
Independent review and 17 targeted recovery/dependency tests passed. The author
selection separately passed 112 tests with one skip; these counts overlap.

The final affected integrated backend selection completed: **570 passed,
19 skipped, one existing warning and five passing subtests, 415.45 seconds**.
All 40 captured source/test fingerprints matched before and after. Its private
log SHA256 is `104fa40a17b625638a0efa4f3b44d58e1d61459278cb562353e8cacced9d4f4c`.
Fixtures now publish their required real canonical parent before testing league
adoption; transition, recovery, scoring and corruption assertions remain. The
preceding 533-pass/30-failure selection is preserved, not relabeled green.
Final separate lab selection: **494 passed, 23.42 seconds**. Ruff formatting
(1,479 files), lint, whitespace, coercion and planning checks passed. None of
these overlapping counts is summed into unique coverage.

The Next dev/E2E read-model bridge now forwards the actual backend
`X-Data-Generation` header while retaining its prior allowlist entry. Six new
regressions failed before the one-header change; 24 author tests and a separate
37-test independent bridge/mode/readiness selection passed. Production nginx
routes API requests directly to FastAPI; this is not a measured production
latency improvement or frontend activation. Browser/build/bundle acceptance
remains gated.

The reviewed 900-second invocation freezes 90 backend, policy, configuration
and dependency files plus the unchanged private replay. No prescribed natural
transition, stale-ETag, fresh official short or full run has started. Fresh host
inspection at 08:24 UTC reports **AC offline, 80% battery and unknown remaining
runtime**. The scoped awake request succeeds but does not prevent the historical
battery-triggered hibernation mechanism. Long measurement release is withheld
until reliable power is observed. No persistent power settings were changed.
This is a host prerequisite, not a passing latency or recovery result.

Offline production preparation also identifies an internal implementation
prerequisite: explicit 0700/0600 artifact creation and root-level atomic request
markers do not support a separated verifier UID merely by changing service
users or UMask. The reviewed design must preserve reader lock access and narrow
queue writes without granting artifact-root replacement authority. A fresh
rotation store also has a different producer lease, so old ownership must be
stopped and drained before its bootstrap. No permission, service, credential,
rotation or production change has been applied. Actual Linux access and rollout
remain separate gates. Mission board revision 70 retains exactly 100 assignments
and distinguishes queued work, completed preparation, independent review and
blocked acceptance.
