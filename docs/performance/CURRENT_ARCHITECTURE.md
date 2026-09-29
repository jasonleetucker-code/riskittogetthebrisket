# Calculator performance architecture — #1338

Current owner authorization: September 26, 2026, `../EXECUTION_PLAN.md` §0.
Controlling budgets and acceptance: `../GLOBAL_PERFORMANCE_STANDARD.md`.
This is the evidence ledger for the existing issue, not a second product roadmap.

## Baseline and boundaries

- Fresh worktree `codex/performance-1338-current` begins at main
  `ed890b1009e9e7a5ec31b6b815ba56ec783d228d`.
- #1346 is closed without merge. `archive/pr-1346` and its private observations
  remain historical; no serving, attestation, telemetry or soak system is imported.
- #1470 harvested independent correctness fixes. Current code and current
  measurements determine remaining work, including Gameplan single-flight.
- Open #1487 owns MVP eligibility and public awards/UI files. Its planning edits
  require bounded integration reconciliation; this lane does not edit its product
  files. The saved checkout is another owner's dirty UI branch and is untouched.
- Startup collected 12,723 tests; this is collection, not a test pass. Current
  export reports 1,109 players and a four-hour-old source observation; health,
  payload and browser measurements are still required before performance claims.
- Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Active units

Owner closure steering, 2026-09-26: complete the reviewed release train, prioritize
the failed production Rankings/Trade useful-state measurements, remeasure material
fixes, then close material failures in the remaining route denominator. Existing
attribution tools are sufficient for the next measurement. The unfinished DLF
structural diagnostic is preserved locally and deferred; it is not a prerequisite
without demonstrated production-correctness impact on this acceptance. No additional
diagnostic platform is authorized merely to broaden the audit. The final production
and adversarial acceptance remains required.

| Unit | Owner / paths | Current state / evidence needed |
| --- | --- | --- |
| Current route denominator and browser paths | `scripts/performance_route_inventory.py` | Reviewed executable static census: 46 page files, 48 BFF files and 94 server route decorators. Dynamic edges remain unknown; these are not distinct accepted URLs or runtime coverage |
| Backend GET/POST path census | Backend census | Live handler/cache/provider/compute owners traced for data, Gameplan, BDVM, Finder and simulation; observed costs still required |
| Gameplan duplicate cold builds | Root; `src/api/gameplan.py`, focused API tests | Reproduced six identical cold solves and four identical team derivations; reviewed correction shares each complete-key build. Changed facts, invalidation, concurrent replacement and failed-attempt retry covered |
| Linux and production measurement readiness | Operations census; evidence only | Inspect current workflows/identity; no donor failure is presumed current |
| Integration and evidence | Root; this ledger, intake, execution, claims | Small reviewed PRs; no production acceptance yet |

Engineering applicability: tracing/useful-state evidence, reproducible inputs,
complete cache identities and concurrency regression tests APPLY_NOW. Existing
canonical engines, single-flight primitive and protected release machinery are
ALREADY_COVERED and must be reused. New valuation methods and unrelated redesign
are outside authority. Signing and distributed infrastructure require evidence.

## Acceptance disposition

### Rankings/Trade compact candidate — closure priority, 2026-09-26

The production baseline failed Rankings cold and all four warm document-navigation
series. Its 8–14 MB decoded total includes multiple resources and cached bodies;
it does not prove duplicated API requests. Live-path inspection confirms the current
fetch single-flight and row WeakMap already share routine requests/materialization.
The first bounded correction therefore reuses the existing compact board for desktop
`/rankings` and `/trade`; new fetches on other desktop routes request array. A
persistent shell can retain an already-loaded semantically equal compact board
across SPA navigation, as with the existing mobile path. No forced refetch is added.
Mobile already uses compact. No additional API, calculation owner or prepared-serving
system is added.

On the same 1,037-row archived input, array is 8,757,503 raw / 792,636 gzip bytes;
corrected compact is 6,057,221 raw / 598,415 gzip bytes: **30.83% raw and 24.50%
gzip reduction**. This is an offline payload comparison, not a production timing
gain or the historical 1,109-player replay. The 1,013 eligible materialized rows,
22,286 source display/export cells and ordered popup details match. Review found
one tied-source ordering difference before the correction: retaining the canonical
source inventory costs 144 raw / 46 gzip bytes and restores exact popup ordering.
No missing values, source weights, canonical ranks or calculations change.

Affected backend validation passes 76 tests and five subtests with one existing
deprecation warning. Two default-concurrency full frontend attempts remain failed
(one then three Trade test timeout/cascade failures). That file passes alone; the
same full suite with four workers passes **189 files / 2,814 tests** with all test
assertions and five-second timeouts unchanged. Node 20 production build passes all
14 unchanged bundle budgets. These results do not substitute for deployment,
browser semantic checks and useful-state remeasurement, which remain required.

The remaining compact body is primarily player rows, including 1.58 MB raw source
audit detail used on disclosure intent. This identifies a possible next material
owner, not permission to discard it or a measured timing benefit. Remeasure the
first correction before choosing additional work. Adjacent DLF diagnostic expansion
is deferred; its uncommitted experiment and historical findings are preserved.

**INCOMPLETE.** No current route family is accepted by this ledger yet. Timing,
payload, Linux resources, field metrics and production useful state remain unknown
until observed. Unit tests and local probes cannot substitute for those gates.

## Expanded search and final adversarial hunt

Owner mandate recorded September 26: this route/task list is the investigation
floor. New opportunities enter the existing #1338 ledger with measured user delay,
frequency, affected routes/users, severity and implementation leverage; unmeasured
hypotheses stay hypotheses. Each retained performance improvement needs a demonstrated
owner, semantic proof, before/after evidence and independent review. Correctness
repairs discovered during census remain clearly distinguished from speed claims.

The final hunt is **NOT STARTED**; known failures and baseline measurements are still
open. After those close, an independent reviewer must challenge the entire current
request, compute/storage, background, browser and deployment path for overlooked
material costs. Completion requires accepted worthwhile fixes or evidence-backed
residual-cost dispositions, actual production verification and regression guards.
Checklist completion alone cannot satisfy this gate.

## First foundation change: Gameplan and executable census

The live endpoint resolves the factual league/profile and team before dispatching
`get_team_gameplan` to its existing thread pool. Its league and team caches
previously released their locks before construction, allowing every concurrent
cold request to repeat the same expensive work. The current-main reproduction
records six league builds and four team builds for equal concurrent requests.
The correction uses the existing `SingleFlight` owner for both scopes.

The league key now binds the normalized loaded roster rows, slots, player
metadata/ages, site values, playoff odds, notes, captured roster capacity,
league/profile, version and observation identity. Team/partner identity remains
in the team key. Captured capacity is also used in package construction. An
invalidation epoch prevents work admitted before invalidation from refilling
either cache or attracting new callers. Publication compares the cache entry
captured before the build, so a late completion cannot overwrite a different
accepted entry. This is conservative cache publication, not a new canonical
generation owner. Failed work leaves the in-flight registry and can retry;
unrelated keys build independently. Existing team LRU bounds remain.

Independent review first rejected a team invalidation race. That failure and
the later changed-input overlap regression were repaired before approval.
Final focused review: 14 tests passed against the recorded source/test hashes.
These exercise real small-fixture calculations but do not measure production
latency. Input loading and its possible team-strength provider fallback still
precede this cache; their cost is not declared solved.

The inventory can be regenerated with:

```text
python scripts/performance_route_inventory.py --output route-inventory.json
```

It traverses current frontend imports/layouts and recognizes local API method
references and server decorators. Every dynamic/unresolved edge remains marked
unknown. It excludes query values and payloads. Static import reachability does
not prove a fetch occurs on navigation. Eight regression tests and an independent
review cover grouped/parallel routes, cycles, bounds, comment-safe discovery and
query privacy. The first review's three rejected cases remain in the evidence.

Node 20.20.2 production build passes all 14 unchanged page bundle budgets. This
build is current-main frontend evidence, not browser useful-state acceptance.
The existing baseline runner still needs verified data-ready predicates and
fail-closed handling of session admission failures before its results can
support the global standard. Local E2E mode does not disable source scheduling.

### Validation and integration checkpoint

Final Gameplan endpoint/configuration/concurrency and inventory selection:
**56 passed, one existing deprecation warning**, 127.85 seconds. The broader
roster-intelligence run remains recorded as **7 failed, 694 passed, 22 skipped**;
all seven failures were reproduced against unchanged current-main AST guards.
They compared Windows separators to declared POSIX paths. Three `.as_posix()`
boundaries and a portable temporary output file repair that check without
changing duplicate-owner rules. Both affected files then passed **26 tests**,
including deliberate undeclared-owner cases. Counts overlap and are not summed.

Scoped Ruff 0.6.9 checks pass; earlier full repository format/lint checked 1,555
files. The current [foundation receipt](evidence/foundation-2026-09-26.json)
retains fingerprints, failed attempts, independent reviews and missing metrics.
Main advanced to `2e49e4ea5` through two automated commits changing only five
source observation/success timestamps. Every changed leaf was inspected:
**BENIGN_AUTOMATION_MOVE for the fixed-input Gameplan and inventory checks**;
no serving code, runtime, fixture or configured ranking input changed. This is
not a deployed freshness claim and does not suppress later relevant reconciliation.

## Data overlay preparation: current-main reproduction and correction

Three unchanged real-handler requests (200/200/304) invoked the canonical
lineup preparation three times even though the existing encoded response cache
served identical bytes. Separate RED cases changed registry starters or flex
eligibility while observation stamps stayed unchanged: the encoded cache served
the old lineup; clearing only that cache produced the correct replacement.

The correction moves the existing solve into the existing single-flight encode
miss. No alternate solver or valuation owner is introduced. It captures the
requested league's registry roster settings once, binds them and the full
canonical ETag to the response version, and uses those same settings for both
slot resolution and flex eligibility. Missing canonical identity disables this
cache. The canonical row reference is captured before awaiting the overlay.
Requested-league metadata is installed before fallback slot resolution.

Independent review and nine targeted tests cover real concurrent HTTP requests,
unchanged304s, same-stamp rule mutation, settings mutation after capture, a
canonical refresh during the awaited overlay, cross-league roster/scoring,
missing canonical identity, and unavailable slots. The integrated data/scoring/
privacy/override/compact/roster-owner selection passes120tests, with one skip,
one existing warning and five passing subtests. Counts overlap.

[Evidence and exact fingerprints](evidence/data-overlay-2026-09-26.json) retain
all three RED regressions and review findings. Build-count elimination is proven;
no measured route-latency gain or full production acceptance is asserted. The
existing publisher's immutable canonical bytes and overlay observation identity
remain assumptions of this cache; no canonical no-op or new source owner is added.

## Materializer missing-confidence correction

Current array and legacy materializers converted explicit null/blank confidence
to numeric zero. Both now guard the selected value before numeric conversion,
preserving real zero and existing nullish alias precedence. Ten parity cases retain
canonical ranks, values and source ranks. Rankings confidence-bucket sorting,
filtering and CSV do not use this numeric field and remain unchanged. This is a
correctness repair found during performance boundary research, not a speed claim.

Independent review approved the captured source/test hashes. Fresh Node20 frontend
validation:188files/2,799tests pass; production build and all14unchanged bundle
budgets pass. [Evidence](evidence/confidence-null-2026-09-26.json) preserves the
initial three failing cases and exact reports. Production semantics/browser
acceptance remain a separate required gate.

## Integration and production checkpoint

### Composed release candidate — September 26, 22:36 UTC

The remaining reviewed heads (#1490, #1492, #1493, #1495, #1497 and #1498)
are composed with the compact-board correction into one integration candidate.
Their original commits and independent reviews are retained. This avoids repeated
work-claim conflicts and does not promote pending or failed individual CI to a pass.
The exact composed head still requires CI, browser journeys and integration review.
No deferred DLF structural experiment is included.

Composition checks pass **83 Python tests (three platform skips)** and **33 browser
runner tests**; planning integrity passes. Frontend product, package/lock and compact
projection blobs are unchanged from the recorded 189-file/2,814-test build, so that
local evidence remains applicable; fresh exact-head CI is still required. Counts
overlap earlier runs and are not summed. Main `c7adc72b2` is included; subsequent
`976109461` changes only four IDP observation/status timestamps, with identical
success/row counts. It is benign for these fixed-input comparisons, not proof of
production freshness or authorization to overwrite its new observations.

Foundation deployment run `36272986437` completed successfully. A later automatic
deployment and authenticated verification are queued/running; no new deployed
useful-state pass is claimed. The original production failures remain acceptance
failures until the actual corrected deployment is measured.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

Foundation #1488 merged as `1de2bd5d922df13414eed5d2bae6ca62145ec152` after exact-head checks and independent review. Read-only Linux diagnostics #1489 merged as `e6a6afd1f0cebe0b83185e733af8214a6a281045`. Their running production identity is not yet verified; automatic deployment is still in progress. Subsequent source/cache/browser units remain separate PRs and issue #1338 stays open.

Main then incorporated the other owner's League MVP gate (#1487) and a superseded-deploy receipt. [Reconciliation evidence](evidence/reconciliation-2026-09-26.json) classifies the combined movement as relevant. The sole merge conflict was adjacent performance work-claim rows from our own operations/API branches; both current owners are retained. Upstream MVP product and authority changes are preserved. The composed API/MVP/release-classification selection passes30tests and planning integrity passes; API implementation hashes are unchanged. Exact new-head CI remains required. Upstream intentional Markdown line-break whitespace is retained rather than reformatted.

The confidence candidate incorporates that reconciled parent while preserving both
owner directives. Fresh combined frontend validation passes189files/2,803tests
(41.52s); Node20 production build and all14unchanged bundle budgets pass.
Independent merge review confirms confidence source/tests are unchanged and both
ledger sections survive. These are integration checks, not browser performance
acceptance. Required new-head CI and deployed verification remain outstanding.

## Merged release checkpoint — September 26, 23:38 UTC

PR #1499 merged the reviewed performance train as
`0b92d66fc6875c5487e60fc1d2a41308026b8f2c`. All constituent PRs are merged.
[Merged-release evidence](evidence/merged-release-2026-09-26.json) records the identities and limitations.
Exact-head required validation passed: 12,590 backend tests (43 skipped),
189 frontend files / 2,814 tests, Node20 production build and all14 unchanged
bundle gates. Browser journeys passed255 with63 explicit exclusions/skips;
these are functional checks, not production useful-state acceptance.

The live-data advisory lane retains17 failures. Independent same-input,
same-clock reproduction on pre-release main and candidate gives identical
rank/value/confidence results:36 high-confidence rows of740 and the same
10 low-confidence anchor players. Sixteen source-observation stamps crossed
the existing six-hour freshness boundary between runs. This is not a candidate
confidence regression or proof of production freshness. Assertions remain intact.

The actual merged tree differs from CI's tested synthetic merge only in an
automated Sharp smoke receipt. The final leaf classification was completed
immediately after merge, not before it. Later main `1b17eaea0` changes only that
same receipt to an unauthenticated/unmeasured state. Both are benign for the
fixed-input performance code checks; neither is production health evidence.

Deployment36278976584 is still validating the merged identity. Last verified
production identity is `7eae987b2f98eefc48758a207f4f85e666997e9a`; the compact
Rankings/Trade change is not yet claimed deployed or accepted. Remeasure the
actual deployment using the existing core baseline before further optimization.

Production browser verification36278712412 attempt1 retained93 passes,26 skips
and one real mobile public League Trades failure: the activity request remained
pending for over30 seconds and the visible panel still said Loading section.
The existing client helper has no fetch/body/retry deadline. A bounded recovery
correction is being prepared; upstream latency ownership remains unproved.
Campaign #1338 stays open.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

### Public League bounded recovery correction

The existing section helper now accepts one absolute intent deadline spanning
fetch, body and transient retries. LeagueClient includes SSR time on the first
document and assigns fresh budgets to later SPA/tab intents. Cached sections
and inactive pending section reuse remain intact. Real unmount and timeout
abort the request; late results cannot overwrite state. Other public helper
consumers retain their existing behavior.

Independent review rejected the first timer-only version: JSON could finish
after the deadline before the timer callback ran. A reproduced regression now
requires a final monotonic-clock check before publication. The corrected candidate
passes57 focused tests independently, the full189-file/2,826-test frontend suite,
Node20 build and all14 unchanged bundle budgets. Planning and whitespace checks
pass. [Failure, review and validation evidence](evidence/public-league-deadline-2026-09-26.json)
preserve both rejected and corrected attempts.

This fixes unbounded failure behavior, not the unproven upstream latency owner.
Hydration, scheduling or component loading can still exceed five seconds; an
unavailable outcome is never numerical useful-state success. Exact-head CI and
actual deployed acceptance remain required.

## Production continuation — September27

The compact release deployed successfully at0b92d66fc; the later data-only
ccfd7a49 deployment passed30smokes and remains the observed application source
for baseline36323800978. No loaded-memory commit introspection is available.
PR1500 merged the independently reviewed public League deadline correction as
836f9f628; deployment and actual correction acceptance remain pending. Its
189-file/2826-test exact-head frontend CI and14bundle gates passed. Overnight
main changed110 aggregate data/receipt paths with no frontend implementation
overlap. The structural source-data revalidation passed1126players/zero errors
**after merge**, not before; that timing is retained explicitly.

The new diagnostic core baseline fails acceptance. Of40 intended observations,
36 reached useful state; two failed authentication preflight contexts leave
four missing cold/warm observations. Desktop Rankings cold/warm p95 is
6194.3/2054.8ms; desktop Trade2163.6/1136.9; mobile Rankings2619.6/1002.3.
Mobile Trade's observed2120.6/1015.9 excludes the four missing observations
and cannot certify that series. No timings or thresholds were substituted.

Each observed main compact response is853369encoded/7189870decoded bytes.
Rankings additionally receives approximately3.195MB decoded auxiliary API data.
Cold data admission occurs1068–1133ms after navigation, followed by
427–709ms body/JSON/scheduling spans. The first desktop Rankings request
spends3767ms awaiting headers. Inclusive stages are not summed across requests
or called pure CPU/network time. This run has diagnostics enabled, a scheduled
Sharp population job active, changed live inputs and only five attempts per
series. It does not establish a causal before/after speed gain or an idle-host
comparison. The uninstrumented control remains required.

The existing runner now retains a fixed auth-preflight outcome and numeric
HTTP status on failed attempts, without credentials, response bodies, retries
or admission-policy changes. The previous boolean discarded the distinction
between rejection, expiry and transport/format failure.22Node tests and six
workflow tests pass; independent review adds six malformed/cleanup checks.
Historical four missing observations remain unresolved; no rate-limit cause
is asserted from their count.

### Rankings/Trade-only critical path — September27 owner refinement

No remaining-route campaign work advances before this route pair's production
gate. The next measurement attributes the approximately3.20MB auxiliary transfer
using the existing endpoint categories; no additional observer is introduced.
An existing-endpoint BDVM projection is being prepared as an unretained candidate:
the Rankings consumer reads only identity, gap, signal, tooltip and proxy fields.
Every player and consumed value must remain identical, including missing/zero,
name fallback, sorting and export order. Full BDVM responses remain the default.
The candidate cannot be called a performance fix before exact production endpoint
attribution and measurement. Main compact response/source-audit semantics remain
untouched; the existing detail endpoints do not supply an equivalent pinned audit.

Deployment36323914004 completed successfully. Remote checkout was836f9f628 at
14:42:35Z, health answered200 at14:46:45Z and30/30smokes passed at14:47:08Z.
Its hard backend gate passed12610tests with25skips,327deselections and440subtests;
the separate advisory lane retains17failures/285passes/40skips. This establishes
deployment, not Rankings/Trade useful-state acceptance or a passing public activity
journey. A source-data deployment36325833642 now holds the shared release lock.
Baseline36325468791 was canceled in the pending slot before measurement; zero
observations were produced. The replacement baseline36327352667 uses the reviewed
runner atc23b3a8e1 and records its source identity separately from deployed code.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

### September 27 — BDVM transfer owner confirmed; #1501 merged

Production report36327352667 identifies BDVM as3,155,119 decoded/688,535 encoded
bytes and news as47,045/7,065. Three completed mobile Rankings cold BDVM responses
overlap initial usefulness; some other responses remain pending at the snapshot.
This demonstrates a material transfer owner, not a causal latency reduction.
The minimal board projection preserves all Rankings-consumed fields, complete
player order, gap sorting, exact CSV and tooltip semantics. Full/default BDVM and
its calculation/cache owner are unchanged; cold compute savings are not claimed.

PR1501 merged as7e4a12d991682cc3c435286a54a1b9ae7583e32c at15:50:36Z after
independent hash-sealed correctness/release review and all exact-head checks passed.
CI hard backend:12601passed/43skipped/327deselected/440subtests; advisory live-data
5failed/287passed/40skipped retained. E2E255passed/63existing skips. Fresh local
Node20 suite190files/2831tests, build and14unchanged bundle budgets passed.
Deployment36331036284 is running; deployment and useful-state gains remain pending.

Diagnostics-off control36330458643 has36useful observations and4missing entries
from two HTTP429preflights. Desktop Rankings cold/warm samplep95=3705.9/2029.7ms;
mobile Rankings2668.2/1450.9ms; desktop Trade2159.6/1043.5ms; mobile Trade
2135.3/1016.3ms with only3successful contexts. The diagnostic run additionally
retains two transport-failure contexts whose exact cause is unknown. Neither run
passes complete acceptance. Five-attempt summaries are not field percentiles;
changing live data/cache/host conditions prevent numeric observer-overhead claims.

The existing runner receives an opt-in between-context cooldown to prevent its
own concentrated public endpoint requests from exhausting the existing per-IP
limiter. Default0 is preserved; opted-in60s occurs before every fresh context,
outside both navigation clocks, with no retries or discarded failed attempts.
The protocol reports it and the conservative session-lifetime bound includes it;
core collection uses the existing3-hour guest-duration input. Production rate
limits remain unchanged. This is a measurement-protocol adjustment, not a product
speed improvement or a waiver. Old fast-sequence failures remain evidence; any
comparison across cooldown protocols carries that limitation.

Next remains actual #1501 deployment, Rankings/Trade production remeasurement,
and only the largest demonstrated remaining owner. Other routes stay gated.
The paced workflow retains its existing45-minute job timeout. The122-minute
conservative credential bound is not a promise that a worst-case run can finish
within that cap; any timeout/interruption remains incomplete evidence.

### September 27 — production byte reduction verified; useful state still gated

#1501 deployment36331036284 succeeded: remote checkout
`7e4a12d991682cc3c435286a54a1b9ae7583e32c`, health200 at16:43:46Z and30/30
smokes at16:44:05Z. The main BDVM supporting response is now234,337 decoded bytes
and33,038 cold encoded bytes, down from3,155,119 and688,535 respectively
(92.57% decoded and95.20% encoded reduction). News accounts for47,045 decoded
bytes in the attributed earlier supporting traffic. Pending bodies remain missing;
cached encoded sizes are not wire-transfer measurements. The main data response
still contains approximately7.20MB decoded. The projection retains full/default
BDVM behavior and does not reduce its full engine computation or cache allocation.

The paced diagnostic run36331359050 recorded40/40 useful observations and all
cold sample p95s below3s, warm below2s. Its diagnostics-disabled control
36335065855 also recorded40/40, but failed the current milestone:

| Route/profile | Cold p95 ms | Warm document p95 ms |
| --- | ---: | ---: |
| Rankings desktop | 3379.4 | 2057.3 |
| Rankings mobile | 3822.2 | 2036.7 |
| Trade desktop | 4361.8 | 2557.4 |
| Trade mobile | 3329.5 | 1075.9 |

These are five observations per cell, unthrottled, with60s between fresh contexts;
warm means a second document navigation. All observed useful times are below5s,
but this does not pass the cold3s or strict global warm1s gates. The earlier
conditional progression recommendation is not accepted after this control.
Field, slowed-mobile, normal SPA and prefetched acceptance remain unmeasured.
See [sanitized production comparison](evidence/rankings-bdvm-production-2026-09-27.json).

The control shows a shared early navigation/load delay across routes without
corresponding payload/DOM growth; its precise owner remains unresolved. Separately,
an actual-runner Chromium control proved up to496ms of readiness polling lag.
The current bounded correction changes only the existing helper's observation
wait, preserves readiness predicates and deadlines, and versions the protocol.
No historical timing is discounted or promoted. Fresh production remeasurement
must follow independent review. Old-protocol run36337520148 was canceled while
queued, with no observations. No remaining-route work is released yet.

Main movement `ea5259f98` adds an independent read-only Game Day diagnostic
workflow/script; inspection found no Rankings/Trade, runner, runtime or serving
dependency change. It does not invalidate this unit's fixed code checks. This
campaign neither invokes that workflow nor claims its production results.
The composed tree was fast-forwarded without touching the dirty candidate. Its
three new workflow steps were missing required release-gate classifications;
independent review proved the existing presence test would fail. Three explicit
`blocking` entries repair that integration prerequisite without changing the
workflow, its permissions or operations. This is relevant to CI metadata only.

### September 28 — Claude takeover: fresh post-#1503 baseline, first-useful-state owners, #1510

Main movement since #1503 (`8a32eed68`): two correctness/product commits (#1504 Game Day
collector host-read repair; #1509 BALLDONTLIE shadow adapter, default OFF) confined to the
Game Day collector, live-state adapters, one flag and their tests — no Rankings/Trade,
`/api/data`, runner or serving dependency — plus 42 automated data refreshes. Neither
invalidates this unit's measurements.

**Fresh baseline, current main, corrected observer** — run 36479010660 (verification source
`12835ae3a`; `visible-locator-fixed-poll-v1`; diagnostics off; 60 s context pacing;
40/40 useful, 0 missing; a post-deploy Sharp bootstrap job was running on the host):

| Series | Cold p50 / p95 ms | Warm p50 / p95 ms |
| --- | ---: | ---: |
| Rankings desktop | 2879 / 4741 | 1249 / 1849 |
| Rankings mobile | 2574 / 3079 | 709 / 876 |
| Trade desktop | 2399 / 2518 | 690 / 1283 |
| Trade mobile | 2396 / 2427 | 445 / 581 |

Five observations per cell; not field percentiles. Fails cold <=3 s (Rankings desktop,
marginally mobile) and warm <=1 s (Rankings desktop, Trade desktop).

**Owner attribution** (paced diagnostic run 36331359050 re-read per attempt, plus local
production-build profiling): the board request starts ~960-1,080 ms into a cold load (after
every chunk downloads and React hydrates) although the HTML arrives at ~290 ms; body transfer
is ~450-550 ms cold; `JSON.parse` of the 7.2 MB compact board is ~18 ms and `buildRows`
2-7 ms locally (~90 ms combined on the runner) — the payload's parse/materialize cost is NOT
the owner. After the data arrives, desktop Rankings spends ~500-600 ms (runner, warm) building
and laying out the 200-row first commit: a local A/B at 2x CPU measured warm 1127 ms at 200
initial rows vs 669/645 ms at 60/40 rows. Rows are lean (~30 nodes, 10 cells); the cost is auto
table layout, which the column-width freeze needs — 40-row and 200-row frozen widths differ by
up to 36 px, so rendering fewer rows first would shift columns after paint.

**#1510 (merge `5273395b7`)**: (1) the board request starts during HTML parse on /rankings and
/trade (`lib/early-contract.js`, adopted at most once by the fetch layer, arrival-stamped
freshness, in-flight adoption at any age); (2) windowed row geometry is read in the frame drain
instead of inside React's commit (the armed first-board read, which shares the freeze's forced
layout, is kept). Local A/B under 100 ms emulated latency: cold median 3538 -> 3020 ms desktop
1x, 4446 -> 3744 desktop 4x, 4526 -> 3888 mobile 4x; warm 2189 -> 1994 ms at 4x. Independent
review approved; three should-fixes applied.

**Evidenced candidates not yet changed** (each with its own measurement):
* Public `/api/public/league/overview` rebuilds on every request (no memo): production TTFB
  2.0-7.9 s vs 0.37 s health; local 0.38-0.65 s per request.
* Every CSV-only data refresh (10-12/day) runs a forced `npm ci` + `next build` (~2 min CPU)
  on the production host, restarts both services and rebuilds the temporal ledger (~2 min).
* Backend event-loop starvation under concurrent CPU-bound work (GIL), measured locally with a
  loop-lag watchdog; the deploy-validation timing test
  `test_event_loop_stays_responsive_during_each_fetch_main` flaked on it (run 36487258010).
* `/api/news` was ruled OUT: its per-request digest costs 0.2-0.6 ms.

**#1510 production remeasurement** — run 36495127028 (deployed `5273395b7`, same observer,
pacing and route set, 40/40 useful):

| Series | Cold p50 / p95 ms | Warm p50 / p95 ms |
| --- | ---: | ---: |
| Rankings desktop | 2598 / 2796 | 959 / 2032 |
| Rankings mobile | 2218 / 2377 | 911 / 2008 |
| Trade desktop | 2088 / 2269 | 551 / 935 |
| Trade mobile | 1953 / 2058 | 569 / 1812 |

Every cold cell now meets <=3 s. What still fails is a single ~1.8-2.0 s warm outlier per
cell against p50s of 0.55-0.96 s: bimodal, not a slow distribution.

### September 29 — encoded overlay response: stale-while-revalidate

**Owner of the warm outliers.** Rankings and Trade read `/api/dynasty-data?view=compact`,
which splices the live Sleeper roster overlay onto the precomputed board and memoizes the
encoded bytes per (league, view) slot under version
`(overlayFetchedAt, payloadETag, canonicalETag, rosterRulesDigest)`. The overlay owner
refreshes every 15 min, so every refresh made the NEXT request re-run the lineup solve, the
multi-MB `json.dumps` (C encoder, GIL held throughout) and gzip on the request path. Locally
`/api/data` measured p50 10 ms against p90 896 ms and max 4.7 s over the same interval —
the same bimodal shape as production.

**Change** (`server.py::_serialize_overlaid_response`, `_kick_overlay_reencode`;
`sleeper_overlay.overlay_observation_servable`): when ONLY the overlay observation differs
and the cached generation's observation is inside the overlay owner's own 30-min
stale-serve ceiling (`_STALE_SERVE_MAX_SEC`), the previous encoded generation is served with
`Cache-Control: private, no-cache` and `X-Overlay-Encode: stale-while-revalidate`, and ONE
background task re-encodes under the same per-key lock. A new board, new canonical rows,
new roster rules, or an observation past the window still encodes on the request exactly as
before; missing/unparseable/zone-less/future stamps fail closed. The background result is
stored only while the slot still holds the generation it was started to replace, so it can
never overwrite a newer one. Nothing is served that the overlay owner itself would not
serve; the body carries its own `overlayFetchedAt`.

**Known limit, stated rather than hidden.** The background encode still holds the GIL for
the length of `json.dumps`, so requests arriving during that window can stall; the change
removes the encode from the triggering request, not from the process. Production
remeasurement decides whether the outliers are gone; a chunked or out-of-process encode is
the next candidate if they are not. Independent review: request-changes, four findings
(test clock, older-generation overwrite, cache lifetime of superseded bytes, cancelled-task
bookkeeping), all applied and sabotage-verified.

### September 29 — the scraper's run phase moved off the event loop

**Measured defect.** Production probes of `/api/health` (healthy round trip ~0.4 s) timed
out with no response at **20 s** (21:46:47 UTC) and **40 s** (22:52:49, three minutes after a
restart) on 2026-09-28. Scrape telemetry places the cause: `Dynasty Scraper.py::run` is
`async def`, but between its `health_report` and `build_payload` phases it runs ~3,000 lines
(3649-6712) of synchronous merge/normalization with no `await` — **~68 s** in the telemetry
of 2026-09-24 (`health_report` 11:12:56 -> `build_payload` 11:14:05). `run_scraper` awaited it
on the server's single event-loop thread, so every request went unserved for that span, on
every scheduled scrape (~2 h) and every restart. Same defect class as the import phase fixed
2026-09-16 (`_import_scraper_module`, 144 s), one phase later.

**Change** (`server.py::_run_scraper_off_loop`): `scraper.run()` executes on its own event
loop in a dedicated `scraper-run` thread (not the shared default executor). Progress payloads
are marshalled back with `call_soon_threadsafe` (FIFO, applied before the worker's completion
is delivered), so `scrape_status` stays single-threaded and ordered. The run timeout is
applied inside the worker loop as before. Cancelling the scrape -- any number of times, as
shutdown does (lifespan, then the server runner) -- cancels the scraper task in its loop and
does not return until the worker has unwound, so `scrape_run_lock` and the Chromium reaper in
`_finalize_scrape_run` never act under a live scrape. Independent review found the first
version returned early on a second cancel (reproduced); fixed and pinned by a double-cancel
test.

**What it does not remove.** The synchronous span still competes for the GIL, so requests
during a scrape can be slower, and any single long C-level call inside it holds the GIL for
its own duration. Full process isolation is the next step
if production remeasurement shows residual stalls. New concurrency this introduces, checked:
the one request-time reader of scraper output files
(`_latest_cached_contract_from_disk`, cold start only) already skips unreadable files to the
next-older export; all other readers run at startup or after the scrape returns.

### September 29 — #1512 production remeasurement; the overlay ETag owner

**#1512 remeasured** (deployed `204a16848`): baseline 36524497676 (plain) and diagnostic
36527088254, same observer, pacing and route set. Mobile improved (Trade warm 524-629 ms, p95
629; Rankings warm p95 2008 -> 1164 in the plain run, 776 in the diagnostic run). Desktop
Rankings still missed: warm attempts [2357, 900, 1004, 2279, 1100] (plain) and
[884, 1644, 992, 853, 827] (diagnostic); desktop Trade one 1364 ms warm outlier. The page itself
loads in ~300-400 ms in every attempt, fast or slow: the extra time is after the load event.

**Attribution.** In the diagnostic outlier (1644 ms) the board request took 488 ms to headers
(normally 130-200) and 613 ms for body + parse (normally 90-150): a FULL re-download on a warm
load that normally revalidates to a zero-body 304. The response's ETag had changed. Every
15-min overlay refresh restamps `overlayFetchedAt` and the trade-window edge
(`tradeWindowStart` / `tradeWindowCutoffMs`, "now minus 365 days") even when no roster, trade or
setting changed, and the encoded response was versioned by fetch time, so each refresh minted
new bytes and every client re-downloaded the whole board to learn nothing. The outlier rate
fits: ~2-3 per ~25-min baseline, about one per overlay refresh. The client reads none of those
three fields; `cache: "no-cache"` stays (it is the logout-replay guard, documented at the call
site).

**Change** (`server.py::_overlay_content_identity`): the encoded response is versioned by the
overlay's CONTENT (everything except the three per-fetch stamps), memoized per observation
(2.7 ms once per refresh per league on a real 317 KB overlay; a hit is ~3 us). Unchanged content
keeps its bytes and ETag -> warm loads revalidate to a 304. The served `overlayFetchedAt` is then
the observation at the slot's last encode (a board publish, roster-rule change, eviction or
restart re-encodes), which understates freshness and never overstates it. The scoring-profile
label stamped into `meta` joined the version, since fetch time no longer refreshes it implicitly
(independent review, approve with should-fixes applied). The
#1512 stale-serve bound now measures from the content's LAST confirmation
(`_OVERLAY_FP_LAST_SEEN`), not its first sighting.

**Still open for desktop Rankings warm**: with the data in hand at ~450-520 ms, useful state
lands at ~830-1000 ms -- the 200-row first render (~400-500 ms) keeps desktop Rankings warm at
the 1 s budget edge even without outliers.

