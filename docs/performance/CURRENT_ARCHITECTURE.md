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
