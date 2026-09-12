# Performance architecture — owner pause report

Checkpoint: **2026-09-12, approximately 11:36 UTC / 07:36 EDT**. Execution is paused at the owner's request. All three working agents confirmed that they have no running test or benchmark. No automatic continuation, deployment or activation is scheduled by this report.

**The architecture is substantially implemented, but the performance modernization is not accepted or finished.** The last official disposition remains **historical Phase 3A PASS; Phase 3B FAILED / INTERRUPTED**. Subsequent fixes have passed affected backend validation, but the modified candidate has not completed fresh official short/full acceptance. Production readiness, mobile speed and site-wide completion remain unproved.

The chronological authority is [PERFORMANCE_CAMPAIGN.md](PERFORMANCE_CAMPAIGN.md); the current assignment snapshot is [Steward revision 93](evidence/performance-swarm-2026-09-12.json). Earlier failed measurements remain preserved rather than overwritten.

**Candidate and integration boundary**

- Working tree: `C:/Users/jason/.codex/visualizations/2026/09/10/01a08cd0-89d8-7191-be6e-d3d7859d6986/chase-performance`.
- Branch: `codex/performance-serving`; HEAD: `564ef3f28dc90904e0e1542adc53f2b4eb59c7ee`. Substantial implementation is uncommitted; HEAD alone does not identify the measured code.
- Last reconciled main: `86d20e6cae3f75b6c5d58a084882f4115e3e6e19`. Last fetched main recorded in this execution: `e94d9977f85fa5b216f823cc5fc6bf809459edca`.
- Relevant upstream source/shared-frontend movement still needs protected integration reconciliation. The latest six-commit movement examined contains 76 source/data/Hill paths; no executable, test, workflow or dependency changes affect the frozen backend replay. Hill champion remains v2. Unrelated fixed-input evidence is retained, not treated as evidence of deployed freshness.
- No push, commit, merge, PR, deployment, installed unit, timer activation or production/frontend flag change was performed by this continuation.

**Architecture actually implemented**

```text
Existing source/feed owners
  -> background ingestion and existing canonical valuation/scoring engines
  -> canonical, league and news preparation
  -> producer semantic/projection validation
  -> immutable artifacts; opt-in Ed25519 certification for attested products
  -> atomic accepted pointer and authenticated observation
  -> background verification and lightweight adoption
  -> coherent canonical/league memory capture
  -> thin authenticated prepared APIs, bytes and ETags
  -> Next.js route consumers and browser rendering
```

This reuses the existing application, private filesystem store and producer owners. It does not introduce Redis, PostgreSQL, Kafka, another Uvicorn worker, a distributed queue or a new valuation engine.

| Boundary | Implemented state | Important limit |
| --- | --- | --- |
| Canonical computation | Existing valuation/scoring owners prepare coherent generations outside ordinary prepared reads | Canonical input manifest remains incomplete; canonical no-op/skip is disabled |
| Source/league/news ownership | Separate producers, leases, queued refresh markers, bootstrap receipt and strict ownership proof | Local leases do not prove cross-host GitHub ownership or installed production cutover |
| Immutable publication | Byte integrity, atomic pointer replacement, rejection and last-known-good recovery | New candidate dependency-admission correction needs fresh sustained acceptance |
| Attestation | Producer validates semantics before signing inventory/identity/policy; web verifies external public pin and signed observations | Opt-in; strict path remains default. Production private-key separation and exhaustive policy closure are not proved; news is not automatically an attested canonical asset |
| Adoption | Reduced duplicate graphs, prepared bytes and required indexes; compatible canonical/league pair captured together | Adoption still has real allocation/CPU cost; it is not allocation-free |
| Prepared APIs | Rankings/trade/catalog and pinned detail capture accepted memory, preserve ETags and authenticated boundaries | Overrides retain existing canonical calculation/cache; untouched routes are not all thin prepared reads |
| Retention | 48-hour target, at least three accepted generations per partition, rollback/proof/transitive dependency protection, capacity rejection | Local test/replay evidence does not establish actual Linux disk/permission behavior |
| Frontend | Rankings/trade prepared mode, intent catalog, full pinned popup/audit details, telemetry and diagnostics | Default-off; slowed-mobile useful-state acceptance failed; later frontend fixes need fresh integrated suite/build/bundles/browser validation |

The store budget defaults to the smaller of 4 GiB or 10% of filesystem capacity, with the existing free-space floor. Pressure may shorten unprotected rollback history and must report that fact. Protected-plus-proposed exhaustion rejects publication while preserving the accepted pointer.

**What the measurements establish**

| Comparison | Observed result | What it does not establish |
| --- | --- | --- |
| Healthy 1,093-player replay payload | Reconciled array 790,946 gzip bytes; rankings/trade 405,727 each: **48.70% smaller**. Catalog 138,977 bytes: **82.43% smaller** | Browser useful-state or production wire latency |
| Strict versus attested canonical adoption, diagnostic medians | 1,292.976 -> 340.019 ms wall time | Official endpoint acceptance; enclosing CPU spans overlap |
| Strict versus attested league adoption, diagnostic medians | 676.252 -> 240.281 ms wall time | Zero adoption cost or production Linux behavior |
| Expiry work, diagnostic p95 | 821.159 -> 0.048 ms | Field freshness/provider reliability |
| Endpoint capture, diagnostic p95 | Approximately 0.0028 ms | Complete HTTP/network/browser latency |
| Prior matched rankings refresh p95 | 61.0708 -> 16.1133 ms after producer-owned certification/adoption changes | A passing hour, equal host scheduling or browser speed |
| Prior quiet web RSS | 547,446,784 -> 435,159,040 bytes in matched short evidence | A permanent plateau; combined producer/process-tree peak increased to about 1.804 GB |

Phase 2 attribution was accepted as **D — connection/loopback**, scoped to the local receive/transport tail. It does not prove a particular packet, ACK, Nagle or kernel mechanism and does not authorize a product workaround. Observer sensitivity and the separate generation-transition tail remain material limitations.

The owner-approved **local-only** policy is unchanged:

```text
refresh p95 < 75 ms
AND (relative degradation <= 20%
     OR (absolute increase <= 15 ms AND refresh p95 <= 25 ms))
```

This is explicitly selected as `local-prepared-hybrid-v1`; the previous policy remains the CLI default. It does not change production SLOs, mobile targets or other route budgets. Each required route/status series must pass independently. Missing observations fail; p99 is insufficient below 1,000 samples.

**Official acceptance: passing short, failed full, new acceptance absent**

The historical fresh short run completed 300 seconds of exercise, 60-second baseline, 30-second refresh and 125.079 seconds of verified quiet after drain. It passed every gate: 49,292 coherent responses, zero errors, adoption and fault checks, 100% complete sampling and 1.109-second maximum acquisition-start gap. Aggregate RSS rose 482,064,384 -> 548,564,992 bytes, a **narrow** 66,500,608-byte increase against a 67,108,864-byte allowance. Handles returned 652 -> 657; 39 observed children all exited; peak process-tree RSS was 1,830,502,400 bytes.

The following full attempt was **not an accepted hour**:

- 324,316 responses had no HTTP/coherence errors, but four unchanged source workers exited unexpectedly.
- Rankings conditional changed-generation 200 p95 was **52.8267 ms**, from eight observations, versus a 16.4296-ms body baseline. Both hybrid secondary branches failed; ordinary series and the pooled result passing cannot hide that failure.
- Observed HTTP stopped around 3,000 seconds. The cap-derived 3,600-second report field did not prove continuous exercise.
- A 2,658.719-second terminal acquisition gap and power sleep/hibernate evidence interrupted the run; complete coverage was 52.9896% of elapsed observation time.
- Verified quiet was zero. Final quiet RSS/handle recovery was **missing**, not evidence of either recovery or a demonstrated leak.
- All 291 observed children eventually exited and disk remained under the 512-MiB lab budget. Those bounded successes do not make the run pass.

Since that attempt, worker diagnostics/admission/deferred follow-up and interruption accounting were corrected and tested. The four historical exceptions remain unknown because their stderr was discarded. Independent held-lease reproductions support the demonstrated fixture admission mechanism; they do not reconstruct those historical exceptions.

The later 180-second diagnostic plumbing smoke recorded 26,141 coherent responses, no HTTP/worker errors, five deferred follow-ups and no surviving observed children. It used diagnostics and only 15 seconds required quiet. Its original report failed, including an adoption-report selector bug subsequently corrected. **It is not official acceptance and was not rewritten into a pass.**

The prescribed three 900-second natural-transition runs, stale-ETag/body controls, fresh official 300-second short and fresh 3,600-second full have **not started**. Last power observation before pause was AC offline, 73% battery, remaining runtime unknown at 09:10:58 UTC. A later multi-hour tool wall gap occurred without a benchmark running; its cause was not attributed. Reliable uninterrupted power must be rechecked before release.

**Corrections retained during the current swarm**

| Files / live owner | Correction and evidence | Checkpoint |
| --- | --- | --- |
| `src/serving/artifacts.py` | Reject missing/ambiguous required dependencies before pruning or pointer change; narrowly recover own corrupt predecessor without allowing it to satisfy dependencies or pruning uncertain history | Independently reviewed; final integrated backend green |
| `src/serving/attestation.py` | Added directly executed `src/bdvm/actuals.py` scoring-season dependency to policy fingerprint after same-size/same-mtime mutation reproduction | 44 tests independently passed; not a claim of exhaustive dependency closure |
| `scripts/soak_prepared_serving.py`, `scripts/soak_observation.py`, `scripts/serving_lab_spans.py` | Bounded structured worker output, admission-versus-post-admission failure distinction, deferred follow-up/adoption, actual observed duration and quiet accounting, transition correlation | Lab tests green; required long experiments pending |
| `frontend/app/api/read-models/[...path]/route.js` | Preserve backend `X-Data-Generation` header in dev/E2E bridge | Reviewed; 24 author / 37 separate review tests. Production nginx bypasses this bridge |
| `frontend/components/useTerminal.js` | Prevent stale scope/auth results, shared-flight subscriber cancellation errors and request-key collisions | 23 tests independently passed; no timing gain claimed |
| `frontend/lib/dynasty-data.js` | Preserve explicit null confidence rather than converting it to zero across legacy/full/prepared materialization | 136-test selection independently passed; ranking values unchanged |
| `frontend/components/useWaiverAnalysis.js`, `useBestAvailableIdp.js` | Preserve unknown FAAB versus zero; bind enrichment to request scope and reject explicit contradictory league labels/array bodies | 104 tests independently passed; no actual production misroute claimed |
| `frontend/app/league/LeagueClient.jsx` | Preserve in-flight section results across rapid tab returns and bind errors to their section | 28 tests independently passed; public section architecture unchanged |
| `frontend/components/ds/DataTable.jsx` | Reattach resize observer after empty/refilled table and clear obsolete frozen geometry | Author 39 tests pass; independent 39 tests pass, **final review judgment/hash seal unfinished at pause** |
| `frontend/components/terminal/TeamCommandHeader.jsx`, route baseline selectors | Home usefulness requires settled meaningful aggregates rather than matching loading placeholders | 15 tests independently passed; not a new approved home speed budget |
| Frontend lab collector, shell/data hook, rankings/trade marks and browser diagnostic script | Bounded opt-in stage/loss/consumer marks; duplicate module marks caught and corrected | Focused independent review passed; no new slowed-mobile acceptance |
| Two `deploy/systemd/*fetch.timer.template` files and ownership runbook | Correct custom service-prefix dependencies and clarify legacy/default-off/rotation prerequisites | 19 tests independently passed; no installation performed |

Latest backend integration: **570 passed, 19 skipped, one existing warning, five passing subtests, 415.45 seconds**. Separate final lab selection: **494 passed, 23.42 seconds**. Ruff 0.6.9 format/lint, coercion, planning and whitespace gates passed at that backend checkpoint. Counts overlap and must not be added. Earlier failed selections remain recorded.

Historical frontend evidence was **2,519 tests / 175 files**, production build, **14/14 bundle gates**, nine browser smoke cases and private parity. **The new shared frontend changes invalidate a blanket claim that this is the final candidate's integrated frontend validation.** A fresh full suite, production build, unchanged bundles and applicable browser semantic checks are still required. Focused passing tests do not substitute.

**Frontend performance and remaining routes**

Slowed mobile remains failed. All 16 prior alternating rankings samples missed the ten-second observation cutoff; that cutoff is not the acceptance budget. Targets remain warm <=1s, normal p95 <=2s, cold <=3s and useful-or-unavailable <=5s. The hidden-cell experiment was rejected and reverted. No replacement rendering optimization has been accepted as a speed improvement.

React rendering, DOM creation/layout, hydration/fetch admission, parse and materialization remain measured or partially attributed cost areas. Rankings already has virtualization; describing virtualization as entirely absent would be false. The current table correction fixes lifecycle correctness, not the unproved mobile performance owner. Field INP/CLS and authenticated deployed useful-state evidence remain unavailable.

| Route family | Current knowledge | Work still missing |
| --- | --- | --- |
| Rankings/trade | Prepared payload/API and full semantic parity exist; mobile fails | Fresh frontend integration and production-backed useful-state acceptance |
| Home | Global-board/team/terminal/history/news dependencies traced; terminal identity and home predicate corrected | Real cold/warm/mobile measurements, approved budget and justified migration |
| Draft | Shared contract/capital work traced; live sync admission overlap is a source-level question | Reproduction if warranted, measurement and approved budget |
| Waivers | Dependencies traced; scope/null enrichment corrections tested | Performance measurements and approved route acceptance |
| Rosters | Global rows/picks plus request-time league roster intelligence assembly traced | Measured owner attribution; no frontend replacement of canonical strength |
| BDVM | Active-tab gating and bounded values cache/single-flight verified; roster/trade scans retain request-time work | API/client timing and budget; cannot change global-top-result semantics merely to reduce work |
| Public `/league` and entity pages | Existing public SSR/section/lazy/cache architecture retained; rapid-tab defect fixed; seven entity templates censused | Measurements and auth/intent reproduction for franchise comparison exception |
| Private player detail | Full-board dependency, lazy detail sections, history and realized stats traced | Same-player league-switch reproduction; request-time provider dependency and migration assessment |
| Game Day, comparison/history/news/Sharp/finder families | Earlier architecture findings exist; dedicated current route assignments remain incomplete/queued | Complete inventory, measurements, owner-approved absent budgets, then gated migration |

Two newly identified issues are **not fixed**:

1. `PlayerPopup.jsx::_loadRealized` caches by player ID for 30 minutes, omits selected league from the request and does not rerun on league change, although the backend scores using factual requested-league settings. Assignment 061 traced the mismatch but had not run a reproduction or edited code when paused.
2. Public franchise `RosterComparePanel.jsx` calls private data/user hooks before its collapsed return. The public AppShell gate does not suppress those direct child hooks. Assignment 063 has not run the auth/intent regression or changed code. This is not a claim that backend authentication leaked private responses.

**Production and security readiness**

Actual candidate production identity, installed source/league/news/GitHub ownership, combined RAM/CPU/cgroup headroom, Linux FDs, child recovery, filesystem capacity and credential permissions remain unverified. The last local SSH attempt was rejected during authentication. Read-only GitHub evidence is available, but a successful deployment of another main SHA is not deployment evidence for this candidate. Existing diagnostic workflow queue/privacy restrictions were respected rather than bypassed.

A concrete internal prerequisite remains: artifact directories/files use explicit 0700/0600 creation, readers need a read/write lock, and queue markers currently need root-level atomic writes. Merely switching the web service to a different UID or changing UMask would break access or grant excessive write authority. A permission-aware store/queue design, implementation and actual Linux cross-UID validation are still needed before claiming web cannot sign. A missing private-key environment variable in a same-user Windows child is not credential isolation.

The required rollout remains legacy deployment -> healthy baseline -> authorized shadow/bootstrap -> verified artifacts/parity/resources/trust -> disable embedded recurring source owner before standalone recurrence -> prepared backend -> frontend only after its gate. None of these production actions is implied by local green tests.

**Assignment accounting at pause**

Exactly **100 immutable assignments** remain in the board. Revision 93 has **0 active, 16 approved, 43 ready for review, 9 blocked and 32 queued**. No assignment is currently marked integrated or complete in the whole-assignment state machine. Approved bounded work is not equivalent to completed rollout/acceptance assignments.

There are 64 numbered attempt-packet families on disk, plus assignments 006 and 016 with other recorded evidence formats. Assignments 061 and 063 have partial read-only execution captured in the owner-pause receipt. Thus **68 IDs have entered work, 32 have not**; this is not a claim of 68 accepted or fully completed assignments. Rejected attempts, null-receipt correction and unfinished reviews remain visible. Final 095–100 completion audit has not executed.

**Resume order — no execution while paused**

1. Finish the pending table review; reproduce and resolve the identified player-league and public-intent issues without speculative performance changes.
2. Freeze the candidate and run fresh affected frontend suite/build/bundles/browser checks. Preserve backend evidence when its dependencies remain unchanged.
3. Verify reliable power, no competing jobs, replay/signing/runtime and start/end hashes. Run the prescribed transition diagnostics and discriminating controls; keep historical sparse failures.
4. Run fresh official short. Only an all-gates pass permits the fresh full hour plus drain and 125 continuous quiet seconds outside exercise.
5. If local full acceptance passes, complete Linux/production prerequisites and obtain the separately required rollout authority. Continue remaining assignments only after the owner resumes work.
6. Production backend readiness permits rankings/trade acceptance; its success permits measured route migrations under approved budgets, then site-wide/field acceptance.

| Layer | Ready? | Evidence | Blocker |
| --- | --- | --- | --- |
| Merge candidate | No overall readiness claim | Affected backend and focused frontend corrections/reviews | Relevant main reconciliation; fresh integrated frontend and short/full acceptance; unfinished review/issues |
| Shadow mode | Not rollout ready | Local immutable artifacts, parity, leases, retention and recovery | Full local acceptance; Linux headroom/ownership/permission proof and rollout authority |
| Source workers | Partial local readiness | Reproduced admission behavior, deferred follow-up, cleanup and corrected diagnostics | Fresh sustained validation; actual production single-owner/feed coverage and credentials |
| Prepared backend | Implemented, not currently accepted | Thin coherent captures, attestation and 570-test integrated result | Transition controls, fresh short/full and deployed authenticated validation |
| Prepared rankings/trade frontend | No; keep disabled | Payload reduction, prior semantic parity and new focused corrections | Slowed-mobile failure, fresh full frontend validation and production backend gate |
| Broader page migration | Not accepted or complete | Several route censuses and targeted correctness fixes | Remaining measurements/assignments, approved budgets, migration gates and field verification |

**PERFORMANCE MODERNIZATION INCOMPLETE — REMAINING BLOCKERS: unfinished correctness review and frontend dependency issues; fresh integrated frontend validation; transition-latency attribution and uninterrupted short/full acceptance; permission-aware producer/web separation and Linux/production evidence/authorization; mobile useful-state acceptance; remaining-route budgets/migration; site-wide and field verification. Work is explicitly paused by the owner.**

Agent-OS-Receipt: af1d50a577c96fd9eed9f934a902a9469f8b69bc
