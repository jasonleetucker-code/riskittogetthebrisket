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

Foundation #1488 merged as `1de2bd5d922df13414eed5d2bae6ca62145ec152` after exact-head checks and independent review. Read-only Linux diagnostics #1489 merged as `e6a6afd1f0cebe0b83185e733af8214a6a281045`. Their running production identity is not yet verified; automatic deployment is still in progress. Subsequent source/cache/browser units remain separate PRs and issue #1338 stays open.

Main then incorporated the other owner's League MVP gate (#1487) and a superseded-deploy receipt. [Reconciliation evidence](evidence/reconciliation-2026-09-26.json) classifies the combined movement as relevant. The sole merge conflict was adjacent performance work-claim rows from our own operations/API branches; both current owners are retained. Upstream MVP product and authority changes are preserved. The composed API/MVP/release-classification selection passes30tests and planning integrity passes; API implementation hashes are unchanged. Exact new-head CI remains required. Upstream intentional Markdown line-break whitespace is retained rather than reformatted.

The confidence candidate incorporates that reconciled parent while preserving both
owner directives. Fresh combined frontend validation passes189files/2,803tests
(41.52s); Node20 production build and all14unchanged bundle budgets pass.
Independent merge review confirms confidence source/tests are unchanged and both
ledger sections survive. These are integration checks, not browser performance
acceptance. Required new-head CI and deployed verification remain outstanding.
