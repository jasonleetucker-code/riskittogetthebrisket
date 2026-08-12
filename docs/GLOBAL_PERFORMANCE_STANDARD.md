# Global Interactive Performance Standard

**Status:** OWNER-APPROVED GLOBAL PRODUCT / ARCHITECTURE / ACCEPTANCE STANDARD  
**Owner direction captured:** 2026-08-12  
**Scope:** every existing and future interactive Brisket feature, page, ranking surface, search, filter, drill-down, dashboard, trade tool, league tool, intelligence surface, and user-facing API path.

---

## 1. Owner mandate

Speed is a first-class product requirement, not post-launch polish.

A feature that is analytically sophisticated but takes so long to populate that a user avoids it is a failed feature. Correctness, methodology, provenance, security, and speed are all parts of product correctness.

> **Brisket should feel immediate. Five seconds is the absolute useful-state failure ceiling, not the target.**

This applies to the entire site, not only Sharp Tracker.

No future feature is complete merely because its tests pass and its answer is correct. It must also meet the applicable user-facing performance budget on production-shaped data.

---

## 2. Performance hierarchy

### 2.1 Interaction acknowledgement

Every tap/click/filter/navigation should acknowledge immediately.

- local visual acknowledgement target: **<100 ms**;
- do not leave a user wondering whether a tap registered;
- optimistic/local UI may be used where safe, but must not fabricate data or execution success.

### 2.2 First useful state

The primary metric is **time to useful state**, not merely server function time.

Targets:

- warm/cached first useful data: **<=1 second**;
- normal production p95 first useful data: **<=2 seconds** where the architecture reasonably permits;
- cold/uncached supported path: **<=3 seconds** where reasonable;
- **absolute interactive useful-state deadline: <=5 seconds**.

A page that routinely takes 4-5 seconds is still considered too slow even if it technically stays below the ceiling.

### 2.3 Already-loaded interactions

For information already available in the browser or a prepared local index:

- sort/filter/tab changes should normally feel instantaneous;
- target **<250 ms** for local transforms/render updates;
- do not make a new network request merely because implementation convenience makes it easier if the needed data is already safely present.

For server-backed lookup/filter operations over prepared indexes, target sub-second responses where feasible.

---

## 3. The five-second rule

At five seconds, an interactive Brisket surface must show a useful, honest state. It may be:

1. the fresh result;
2. a valid last-known-good result with freshness disclosed while revalidation continues;
3. a safe partial result with missing portions explicitly identified;
4. an explicit unavailable/error state with retry/recovery behavior.

It may **not** be an indefinite spinner hiding minutes of backend work.

A slow backend operation must not make the whole site unusable.

---

## 4. Architecture mandate: compute before the click

The default architectural posture is:

**acquire → normalize → compute expensive derivatives → materialize/index/cache → serve quickly → refresh asynchronously.**

User requests should normally consume prepared intelligence, not create it from scratch.

Heavy work that should generally stay off the interactive request path includes, where applicable:

- source crawling and network discovery;
- universe-wide ranking rebuilds;
- Sharp-manager discovery/scoring;
- large ledger scans;
- historical reconstruction;
- broad trade-market aggregation;
- multi-league ingestion;
- expensive simulations that can be refreshed on a schedule;
- projection/source normalization;
- model fitting/backtesting;
- large joins that can be materialized or indexed ahead of time;
- repeated parsing of large source files;
- work duplicated independently by several pages.

The browser should usually ask for the answer, not trigger the machinery required to manufacture the entire answer universe.

---

## 5. Rankings and canonical datasets

Rankings are a core user surface and must be fast.

Where correctness permits:

- canonical ranking boards should be generated/refreshed off-request-path;
- common league/scoring variants should have prepared snapshots or indexed transforms;
- pagination/virtualization should prevent the browser from rendering unnecessarily large lists;
- filters/sorts should use already-prepared fields instead of recomputing values;
- stale-while-revalidate should preserve a valid prior board during refresh;
- freshness/version metadata must make clear which prepared dataset is being served.

Do not sacrifice league/scoring correctness merely to hit a cache. Cache keys/materializations must include every dimension that changes the answer.

---

## 6. Stale-while-revalidate and last-known-good behavior

A valid previous result is normally preferable to a blank page while a newer result is prepared.

When safe for the feature:

- serve the last-known-good snapshot immediately;
- disclose meaningful staleness/freshness;
- refresh in the background;
- atomically replace the old result after successful refresh;
- do not delete valid old data because one refresh failed;
- distinguish stale from missing/unavailable.

This does not authorize serving factually incompatible league/model data. A fast wrong answer is still wrong.

---

## 7. Expensive user-initiated work

Some explicitly requested operations may legitimately take longer than five seconds, such as a deep backtest, large export, model-training job, or unusually large one-off research operation.

Those are **jobs**, not normal interactive page loads.

If such a task cannot complete inside the interactive budget:

- acknowledge it immediately;
- detach it from normal page rendering;
- provide progress/status if supported;
- keep the rest of the site responsive;
- return/view the result when complete;
- do not make ordinary navigation wait for it.

Do not relabel a routinely slow page as a "job" simply to evade the performance standard.

---

## 8. No timeout-as-optimization

Increasing a timeout is not a performance repair.

Before changing a timeout, identify why the work needs that much time.

Preferred repair classes include:

- eliminate repeated work;
- materialize/cache/index;
- fix request fan-out;
- remove accidental cache-busting;
- batch I/O;
- prefetch predictable data;
- paginate/virtualize;
- remove production-network dependencies from pure request/test paths;
- prevent cache stampedes;
- reduce payload/DOM size;
- split background computation from serving;
- use the canonical result once rather than recomputing it on every page.

A longer timeout may be appropriate for a legitimate background job, but it is not evidence that the interactive experience is acceptable.

---

## 9. Required measurements

Performance claims must be measured on realistic production-shaped inputs.

For important surfaces record, as applicable:

- navigation → shell;
- navigation → first useful content;
- navigation → complete primary content;
- API p50 / p95 / p99;
- backend compute time;
- cache hit/miss;
- database/file/index time;
- external-network time;
- payload bytes;
- hydration/render time;
- mobile behavior;
- cold and warm cases;
- filter/sort/drill-down time;
- concurrent-user / stampede behavior;
- freshness/revalidation behavior.

A microbenchmark of one helper is not proof that the page is fast.

---

## 10. Feature acceptance gate

Every materially new interactive feature or major rewrite must answer before owner acceptance:

1. What is its target time to useful state?
2. What is its measured warm/cold p50/p95 on production-shaped data?
3. What expensive work occurs on the request path?
4. Why can that work not be precomputed/materialized/indexed if it is expensive?
5. What happens when upstream data refresh fails?
6. Can it serve last-known-good safely?
7. Are cache keys complete and league/model-correct?
8. Does mobile performance satisfy the same useful-state ceiling?
9. Are there regression tests/probes/budgets appropriate to the feature?

A feature that materially violates the performance budget remains **DEFECTIVE / NOT FINISHED** even if functional tests pass.

---

## 11. Existing-site repair mandate

This standard applies retroactively.

Existing surfaces that take many seconds or minutes are product defects and should be inventoried, measured, prioritized, and repaired. Sharp Tracker is an already-observed severe example, but it is not the only surface covered by this rule.

High-use / high-value surfaces should be prioritized, including at minimum:

- rankings;
- Trade Analyzer / Trade Finder / package tools;
- Sharp Tracker / Sharp Roster % / Sharp People;
- Insider Trading;
- player profiles;
- team/league dashboards;
- waiver/draft tools;
- Game Day;
- playoff/pick-forecast views;
- search/navigation;
- AI/front-office orchestration surfaces when activated.

The final master audit must include user-facing performance rather than treating speed as a separate optional polish pass.

---

## 12. Performance regression prevention

One optimization pass is not enough.

Where stable measurement is possible, add repeatable performance probes/budgets so later changes cannot silently regress the site from seconds back to minutes.

Performance budget failures should block or require an explicit owner-reviewed exception, just like other correctness gates.

Prefer trend history over one isolated number so gradual degradation is visible.

---

## 13. Relationship to other canonical rules

Speed does not override:

- ONE CONCEPT, ONE CANONICAL OWNER;
- MISSING IS NEVER ZERO;
- scoring/league compatibility;
- source provenance;
- signal independence;
- security/privacy;
- champion/challenger governance;
- recommendation/execution separation.

Instead, performance architecture should reinforce those rules by serving canonical prepared outputs rather than creating page-local shortcuts.

The intended standard is:

> **Correct, explainable, current-enough, and fast enough to actually use.**

---

## 14. Status

**Global speed mandate:** OWNER-APPROVED.  
**<=5-second useful-state ceiling:** OWNER-APPROVED HARD INTERACTIVE CEILING.  
**<=1-second warm / <=2-second normal p95 targets:** OWNER-APPROVED DEFAULT TARGETS, subject to production-shaped measurement and feature-specific tightening where feasible.  
**Off-request-path materialization for expensive repeatable work:** OWNER-APPROVED DEFAULT ARCHITECTURE.  
**Retroactive performance repair of slow existing features:** OWNER-APPROVED.  
**Performance evidence required for new interactive feature acceptance:** OWNER-APPROVED.  
**Increasing timeouts instead of repairing root causes:** NOT an acceptable default optimization strategy.
