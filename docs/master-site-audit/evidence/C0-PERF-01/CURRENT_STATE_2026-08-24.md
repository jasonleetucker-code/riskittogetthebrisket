# V1-105 / `C0-PERF-01` — current state, and what is not recoverable

**Head:** `131abf9f9` · **Instrument:** `frontend/scripts/measure-route-baselines.mjs`
(the existing trusted one; unmodified) · **Raw:** `2026-08-24-current-state.json`
**Environment:** production build on `:3000`, real backend on `:8000`, authenticated,
real board (1,109 players), 5 runs per cell, p95 reported.

**This is a CURRENT-STATE measurement. It is not a baseline for `/rankings`, and it is
not presented as one.**

---

## 1. The owner decision is still open

PR **#1006** established that `/rankings`' true pre-feature, acceptance-grade baseline
is **gone and unrecoverable**: two rounds of feature work (windowing `a9136e13e`, PSI
migration #984) landed before the only instrument capable of producing a p95 existed,
and the sole genuinely pre-dated evidence (`PERFORMANCE_AUDIT.md`, 2026-08-04/05) is
explicitly single-run — a p95 cannot come from n = 1.

Verified 2026-08-24: **#1006 is still open and unmerged**, and
`docs/master-site-audit/evidence/C0-PERF-01/` did not exist on `origin/main` before
this commit. So the audit is not yet in the canonical record and the scope call it
raises — accept the `/rankings` gap as permanent, or hold the row open — remains
**`OWNER_DECISION_REQUIRED`**. This lane does not resolve it and has not touched the
row's status.

## 2. Measured now

Cold = first load, empty cache. Warm = repeat. "Useful" = the route's own declared
readiness marker (one owner: the E2E suite's `SEL` table), not `load`.

| viewport | route | cold p95 useful | warm p95 useful | cold p95 FCP |
|---|---|---|---|---|
| desktop | `/rankings` | 1556 ms | **1018 ms** | 136 ms |
| desktop | `/trade` | 1070 ms | 946 ms | 108 ms |
| desktop | `/league` | 219 ms | 148 ms | 152 ms |
| desktop | `/` | 503 ms | 314 ms | 116 ms |
| mobile | `/rankings` | 976 ms | 899 ms | 108 ms |
| mobile | `/trade` | 993 ms | 439 ms | 92 ms |
| mobile | `/league` | 288 ms | 187 ms | 164 ms |
| mobile | `/` | 433 ms | 248 ms | 88 ms |

**One miss, reported as a miss:** desktop `/rankings` **warm p95 useful 1018 ms >
1000 ms** (standard §2.2). Every other cell is inside target. Reporting it because the
dispatch asks for actual values even when the target is missed — and because 1018 vs
1000 is exactly the kind of near-miss that gets rounded away.

**How these may and may not be used:**

- `/trade`, `/league`, `/` — legitimate **prospective baselines**. Their own feature
  work (`C8-PERF-04`, `C8-PERF-05`, later `C8-PSI-02` routes) has not happened, so a
  measurement taken now is a genuine "before".
- `/rankings` — **current state only.** It is downstream of both #1003 and #984.
  Labelling it a baseline would be the retroactive fabrication this row exists to
  prevent.
- Not measured: `/waivers`, `/market/sharp-tracker`, `/market/sharp-roster-percentage`.
  Their readiness markers need production-timer-only data and time out locally
  (`BLOCKED_EXTERNAL`, matching #1006's finding). Recorded as unmeasured rather than
  silently dropped.

## 3. Two defects found in the instrumentation, both reported

**(a) The harness can report a pass having measured almost nothing.** The first attempt
at this run hit the public-API rate limiter (60/min): 39 of 40 session mints returned
429, every cell but one reported `—`, and the harness still printed:

> `All measured routes inside the standard's targets.`

A verdict computed over an empty set reads identically to a clean bill of health. This
is the same failure class the contract calls MISSING IS NEVER ZERO, in the one place
that decides whether a performance row passes. The run was discarded, not reported.
**Recommendation (not implemented here — it is `measure-route-baselines.mjs`'s owner's
call): exit non-zero, or state the refusal, when any requested cell is unmeasured.**

For the record, the run above bypassed the limiter for `127.0.0.1`
(`RATE_LIMIT_BYPASS_IPS`). That limiter throttles *session minting*, a public API path
— it does not touch the page loads being timed, so bypassing it removes a measurement
artifact rather than biasing a result.

**(b) Two canonical records carry figures their own instrument disowns.**
`docs/OWNER_FEATURE_INVENTORY.md:245` (inv 9.1) still reads:

- *"**no windowing implementation exists**"* — **false since `V1-106`**, which is
  `VERIFIED` on this head; and
- *"**59.5 FPS**"* — a number the FPS harness's own header retracts as a
  self-measurement artifact (#760's first harness paced its own scroll with
  `setTimeout(16)`, so the figure was a property of the loop). `C8-PERF-03` in
  `C_SERIES_SCOPE_MANIFEST.md:389` cites the same 59.5.

Reported, **not edited** — those are canonical records and belong to Integration.

## 4. Status

`V1-105` stays **`NOT STARTED`** in the contract; this lane changed nothing. What it
now has that it did not have this morning: a complete, controlled, current-state
measurement on the live board across both viewports, with the one target miss named,
the recoverable-vs-irrecoverable split stated explicitly, and the instrument's own
false-green flagged.

The remaining work is a **decision**, not a measurement.
