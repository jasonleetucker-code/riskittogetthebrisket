# Post-merge C-Series audit and stability gate — findings register

**Status:** IN PROGRESS. This file is the durable record of what has been measured.
The binding `PASS` / `FAIL` verdict is not recorded here until every phase has run and the
outstanding production proofs have been attempted against the deployed SHA.

**Authorization:** the feature freeze in `docs/EXECUTION_PLAN.md` §0. Nothing in this file
authorizes implementation work.

**Audit base:** `96ecc22a9`. Repairs derived from it are named per finding.

---

## 0. How to read this

Every claim below is traceable to a measurement taken during the audit, not to a PR
description, not to prior green CI, and not to this session's own earlier statements. Where a
check could not be run here, it says so and says why — an unreachable check is
`BLOCKED-EXTERNAL`, never a pass.

Two conventions are load-bearing:

- **CONFIRMED** means reproduced by me at or after the audit base.
- **A refuted finding may still be real.** C2-U1 proved that during the campaign, so refuted
  items are recorded rather than deleted.

---

## 1. Findings

### F-1 · 2029 pick tier ordering is inverted on the live board · CONFIRMED · data integrity · **REPAIRED 2026-08-18**

An earlier pick must be worth more than a later one. On the 2026-08-17 contract it is not,
for every round of 2029:

| year | round | Early | Mid | Late | verdict |
|---|---|---|---|---|---|
| 2027 | 1–6 | highest | middle | lowest | OK (all 6) |
| 2028 | 1–6 | highest | middle | lowest | OK (all 6) |
| 2029 | 1st | 3593 | **3676** | 3446 | Mid > Early by +2.31% |
| 2029 | 2nd | 2590 | **2596** | 2440 | Mid > Early by +0.23% |
| 2029 | 3rd | 1811 | 1758 | **1794** | Late > Mid |
| 2029 | 4th | 1412 | **1421** | 980 | Mid > Early by +0.64% |
| 2029 | 5th | 1312 | **1320** | 910 | Mid > Early by +0.61% |
| 2029 | 6th | 1202 | **1209** | 834 | Mid > Early by +0.58% |

**6 of 18 (year, round) cells violate tier ordering. All six are 2029** — the only fully
derived year.

**Mechanism.** `derivedYearModel.stepByTierRound` carries an independent per-cell ratio
(`early.1 = 0.7138`, `mid.1 = 0.8078`, `late.1 = 0.8339`). The ratios rise with tier, so
applying them to a correctly ordered 2028 board compresses the Early–Late spread by more than
the spread itself and crosses it. Rounds 5–6 inherit the inversion because
`derived_round_step` derives from round 4 of the same year and tier.

The *direction* is defensible — spread compression further out is economically sensible. The
*magnitude* is untested by construction: the config's own `classificationNote` says applying a
1-out→2-out ratio to the 2-out→3-out gap "is an extrapolation no market evidence can test
today", which is why the family is classified `PRIOR`. Nothing constrains the extrapolation to
preserve ordering, and nothing checks the result.

**It reaches the decision surface.** Through the canonical resolver, with provenance:

```
resolve_pick_value(contract, MarketPickRef(2029, 1, tier="early")) -> 3593  factor 0.7138
resolve_pick_value(contract, MarketPickRef(2029, 1, tier="mid"))   -> 3676  factor 0.8078
```

So the trade calculator books a **gain** for downgrading a 2029 early first to a mid first.
`validate_api_data_contract`'s pick census passes: it checks finiteness, not-zero-as-missing
and provenance — never ordering.

**Attempted refutation, three ways — all failed, and two made it worse.**

1. *"The 2029 tier rows are internal derivations nothing selects."* Refuted. All 24 are priced
   **and ranked**, and all 24 appear in the legacy `players` dict the UI consumes.
2. *"It only affects trade math, not anything a user sees."* Refuted, and this is the
   escalation: the inversion is visible on the **published ranked board**.

   | rank | row | value |
   |---|---|---|
   | **#117** | `2029 Mid 1st` | 3676 |
   | **#123** | `2029 Early 1st` | 3593 |
   | #139 | `2029 Late 1st` | 3446 |

   A user browsing `/rankings` sees a mid first ranked above an early first.
3. *"Maybe Early > Mid > Late is my assumption, not the product's."* Refuted by the other two
   years: 2027 and 2028 satisfy it in all 12 of their cells. It is the board's own rule.

A fourth check strengthens the impact rather than reducing it: there are **no slot-form rows
for 2027–2029** — the tier grade is the entire user-facing granularity for every future pick,
so there is no finer-grained correct value sitting behind the wrong one.

**Why not repaired here.** Choosing how to restore monotonicity (clamp the crossing cell?
isotonic-regress the ratio surface? shrink toward `stepByRound`?) is a calibration methodology
change, which the freeze names as not permitted. An ERROR-level census check would turn the
board red and block deploy; a warning-only one changes no value but still lands a new gate
under a freeze. Both were considered and declined.

**Recommendation.** First authorized unit after the audit: constrain the derived-year surface
to preserve tier and round ordering, declare the constraint as part of the `PRIOR` family, and
measure its effect on all 18 cells before and after.

**REPAIRED 2026-08-18** — owner authorised the repair and chose the isotonic method.

*What was done.* Within a round, the year step is projected onto the **non-increasing cone** by
isotonic regression (pool-adjacent-violators), at config load, in
`data_contract._project_tier_steps_monotone`. The measured surface is preserved untouched under
`yearStepByTierRoundMeasured` — the evidence is not overwritten by the model built from it — and
the constraint is declared in `config/weights/pick_year_discount.json` under
`derivedYearModel.monotonicityConstraint`, classification **PRIOR** with the rest of the family.

*Why this and not a value-space projection or an output clamp.* It acts on the derivation
**surface**, so nothing clamps downstream of the blend. And because a **constant ratio applied to
a strictly ordered template year yields a strictly ordered derived year**, pooling can never
produce a TIE in value space — ordering holds **by construction**, for every source and every
template, with no epsilon. A least-squares projection in *value* space would instead sit exactly
**on** the ordering boundary and produce ties, which is why it was rejected.

*Effect on the surface* — 11 of 12 cells changed; `late.4` already complied:

| round | measured (early / mid / late) | projected |
|---|---|---|
| 1 | 0.7138 / 0.8078 / 0.8339 | 0.7852 / 0.7852 / 0.7852 |
| 2 | 0.8174 / 0.8662 / 0.8760 | 0.8532 / 0.8532 / 0.8532 |
| 3 | 0.8328 / 0.8399 / 0.8954 | 0.8560 / 0.8560 / 0.8560 |
| 4 | 0.8633 / 0.8938 / 0.7726 | 0.8786 / 0.8786 / **0.7726** |

*Effect on the board* — **18 of 18 complete tier cells now satisfy Early > Mid > Late; violations
0.** The denominator is 18, not the 24 an earlier count in this session reported: 2026 rows exist
but are slot-based rather than complete tier triples, so they were never eligible cells. The
register's original "6 of 18" was correct.

*Board diff, pinned input, code varied only:*

```
VALUES: 20 moved, 0 newly priced, 0 newly unpriced   |pct| p50=1.7% p90=5.9% max=10.0%
RANKS:  130 changed        canonicalTierId: 499 flipped
```

Classified per §25:

* **EXPECTED REPAIR MOVEMENT** — the 20 value moves. Every one is a 2029 tier row, which is
  exactly the population the constraint targets. Largest: `2029 Early 1st` 3593 → 3952 (+10.0%),
  `2029 Late 1st` 3446 → 3243 (−5.9%). No 2027 or 2028 row moved; no player moved.
* **INCIDENTAL BUT EXPLAINED** — the 130 rank changes (115 on non-pick rows, 88% of them ±1: the
  ordinal reshuffle as 2029 rows pass other rows) and the 499 `canonicalTierId` flips. Mechanism
  verified rather than assumed: the board **lost two tiers** (136 → 134) because the repair
  changed the gap structure the tier cutter reads, and tier ids are **dense ordinals**, so every
  row below the shallowest affected boundary renumbers by 1–2. The shallowest flipped tier is
  **21**, and all **113 rows in tiers 1–20 are unchanged**. Tier membership semantics are intact;
  only the ordinal label shifted.
* **UNEXPECTED** — none.

*Enforcement, mutation-proven.* `validate_api_data_contract`'s pick census gained a
`pick_tier_ordering:*` **ERROR** (the gate keys on `ok` and ignores warnings), and
`tests/picks/test_future_tier_ordering.py` asserts the invariant on both the surface (deterministic)
and a contract built from an archive fixture (all-of-them, never a count — §3d). Bypassing the
projection reproduces **6** census errors; projecting the wrong direction reproduces **3**. Both
also fail the tests; clean restore is green.

*Known characteristic, named rather than smoothed.* The projection constrains ordering; it does
not denoise. `late.4` (0.7726) survives unpooled and carries the surface's largest cross-provider
disagreement (**0.086**, 3–8× every other cell), so 2029 R4–R6 show a wide Mid → Late step
(e.g. R4: 1436 / 1396 / 980). That is the measured value preserved, not an artifact of the
constraint. Recalibrating it is a separate evidence question, not this repair's.

### F-2 · The E2E board diagnostic reports a false root cause · CONFIRMED · observability · REPAIRED (#893)

**This entry replaces a REFUTED finding, and the refutation is the point.**

I first recorded F-2 as *"`/api/data` serves the raw snapshot, HTTP 200, until the first scrape
succeeds"*, having measured `playersArray=0`, `stamped=0`, `contractVersion=None` against a
locally booted backend whose startup scrape had failed. **That finding was wrong**, and the
owner had approved a startup-wiring repair on the strength of it before I re-measured. The
repair was not built.

What is actually true: the contract **is** built at startup. `_prime_latest_payload` calls
`build_api_data_contract` and the default and `array` views carry 1,109 rows with **740
stamped**. `view=app` is the *runtime* view and **deliberately drops `playersArray`** —
`server.py` does `runtime_payload.pop("playersArray", None)`, the documented payload-size
optimisation — so its rows live in the legacy `players` dict and carry
**`_canonicalConsensusRank`**, the underscore-prefixed key the legacy materializer in
`dynasty-data.js` actually reads. Measured on that exact payload:
`_canonicalConsensusRank` on **740/1109**, `rankDerivedValue` on **849/1109**. I had checked
the un-prefixed key. So had the diagnostic.

**The real defect.** `tests/e2e/helpers/journey.js` counts stamps only over `body.playersArray`,
using the un-prefixed key — over a view that always returns that array empty. `stamped` was
therefore unconditionally `0`, the "NO RANK STAMPS" branch fired on **every** board failure, and
the "looks serveable — that points at the client" branch was unreachable. What it printed:

```
=> PAYLOAD HAS ROWS BUT NO RANK STAMPS ... The scrape pipeline is not stamping
   canonicalConsensusRank — investigate upstream, do NOT add a client-side blend.
```

A confident, wrong headline naming a subsystem that is fine, on every red board run for a week.
Replaying both expressions against the captured payload: old yields `0` and fires the false
branch; new yields `740` and reports the payload serveable.

**Repaired** in #893: count with the key each materializer reads, and report both halves so a
future mismatch is visible rather than collapsed.

**The board failures themselves are a stack-readiness race, not a contract defect.** The same
error context carries four 404s, a **502** and a 503 — none of which the diagnostic mentions.
The mobile board test passes in isolation and failed twice under parallel load; the Streaks
test passed on re-run. Classified as flaky-under-load, not deterministic. The earlier claim in
this register that two failures were "deterministic from F-2" is withdrawn.

**Process note, recorded deliberately.** A diagnostic that is wrong is worse than one that is
absent: it spends the reader's attention on the wrong subsystem and forecloses the right
question. It cost this audit a full investigation cycle — a booted backend, a serving-path
probe, and a provisional finding — and it would have cost an owner-approved production change
had I not re-measured before writing code.


### F-3 · The E2E regression suite has been red on `main` for seven consecutive days · CONFIRMED · process

The `e2e.yml` workflow's scheduled run on `main` has concluded `failure` on **2026-08-11, -12,
-13, -14, -15, -16 and -17**, and on the open dependabot PR. Its last success was 2026-08-10, on
`claude/bridge-timeout-root-cause` — the branch of PR #762, still open.

The repository's end-to-end regression signal has therefore been unread for a week. Local run
during this audit: **148 passed, 5 failed** — two repaired by batch G, and three that are
**flaky under parallel load rather than deterministic**: Streaks passed on re-run, and the
mobile board test passes in isolation having failed twice under load. The console evidence on
the board failures is four 404s, a 502 and a 503 — a stack-readiness race.

The week of red was legible only through F-2's diagnostic, which named the wrong subsystem
every time. That is repaired (#893); the underlying readiness race is not, and is the honest
next question.

**Recommendation.** Make the suite's verdict something a person is required to look at, and
treat the readiness race as its own unit. A signal nobody reads is not a signal — and one that
lies when read is worse.

**RE-MEASURED 2026-08-18, on CI rather than locally.** Batch G merged and #893 was rebased onto
it, so the suite was re-run on a current base. Measured on run `32120428479`:

```
1 failed   journey-settings-overrides.spec.js:45 › toggling a source fires the overrides request
1 flaky    journey-rankings.spec.js:28        › board loads with real rows and clean values
152 passed (was 148), 52 skipped, 5.2m
```

So the count improved from **5 failures to 1 failure + 1 flaky**, which is batch G's two repairs
landing plus the rebase. Two things this corrects in the entry above:

* the earlier "three flaky under parallel load" figure was taken from a **local** run on a stale
  base; on CI at a current base it is **one** flaky (`journey-rankings`, the board-readiness
  race) — the same class, a smaller population;
* **`journey-settings-overrides` is a hard failure, not flakiness.** It exercises the rankings
  **override** path (`POST /api/rankings/overrides`), which is a canonical serving path, so it is
  carried as an open audit item rather than absorbed into F-3's "readiness race" framing.

The run exits non-zero partly *because* the repo sets `failOnFlakyTests` — a retried green is
deliberately not accepted, and the banner explains why (without it, `e2e.yml`'s close step would
drain every open `e2e-failures` issue). That is correct policy and is not itself a defect.

**Open:** `F-3a` — diagnose `journey-settings-overrides`; **`F-3b`** — the `journey-rankings`
board-readiness race. Neither is caused by #893, which changes only the diagnostic helper.

**F-3a and F-3b diagnosed 2026-08-18**, from run `32120428479`'s server logs (artifact
`e2e-server-logs`, 7.5 KB — the 73 MB Playwright report was not needed).

**F-3a is NOT a backend failure on the overrides path.** Every `POST /api/rankings/overrides`
in that run returned **200**, four of four:

```
INFO: "POST /api/rankings/overrides?view=delta HTTP/1.1" 200 OK   (×4)
```

So the earlier framing — "a hard failure on a canonical serving path" — overstated it. The
canonical serving path answered correctly every time; the spec fails downstream of it, on the
badge or a console guard. **Corrected here rather than left standing**, and re-scoped: `F-3a` is
a spec/UI question, not a serving defect. It does not gate the audit's canonical-value work.

**F-3b is a readiness window, and the diagnostic cannot see it.** The board failure's console
shows four 404s, a **502** and a **503** during load, then:

```
[dynasty-data] buildRows received a payload with zero backend rank stamps
```

`buildRows` refusing to render is **correct** — that is the fail-fast doing its job rather than
publishing a silently-wrong board. The backend log confirms the window is real (`GET /api/health`
→ **503** while priming).

But the diagnostic that runs afterwards reports:

```
/api/data?view=app: 200, playerCount=1109, playersArray=0, legacyPlayers=1109, rankStamps=740
 => The payload looks serveable ... That points at the client, not the contract.
```

Two things make that verdict unreliable, and **neither is a defect in #893's repair** — its
`_canonicalConsensusRank` counting is right, and `playersArray=0` is correct for the runtime view
(`server.py` pops it by design):

1. **It samples a different view.** The page fetches `?view=array`; the diagnostic fetches
   `?view=app`. Those are two different payloads built from the same contract, and a degradation
   confined to one is invisible from the other.
2. **It samples after the window has closed.** It issues a *new* request once the 60 s locator
   timeout has already expired, by which time the backend has primed. A probe of a recovered
   system cannot distinguish "the client is broken" from "the server was not ready when the
   client asked".

So its confident "points at the client" is a post-hoc measurement. The repair is to sample the
**failing request** — the response the page actually received — rather than issue a fresh one,
and to probe the view the page uses. Recorded rather than fixed here: it is a separate unit, and
the audit's rule is that a diagnostic which names a subsystem must be able to prove it.


### F-4 · Production proof outstanding for five units · BLOCKED-EXTERNAL

`C0-R`, `C1-U5`, `C1-U8`, `C1-U9` and `C2-U1` are all `CLOSED-PENDING-PROD`. Their code is in
production (deployed `5a5f1507f`), but **not one of the five named checklists has been
executed**. Each requires an authenticated production session. Recorded honestly in
`docs/EXECUTION_PLAN.md` §0.3 as `IN PRODUCTION, CHECKLIST UNEXECUTED` — the deploy landing is
the precondition, not the proof.

**Owner decision, 2026-08-18, recorded verbatim in substance:**

> Run everything reachable from this environment. Do not request or accept my permanent
> production credentials. Mark only the authenticated production checks as
> `BLOCKED-EXTERNAL` / `PENDING-PROD` and keep the affected units `CLOSED-PENDING-PROD`.
> This is not a manufactured pass and does not satisfy final production closure. Finish the
> remainder of the audit, then identify exactly what authenticated production verification
> remains so it can be completed separately through a safe access method.

Three consequences, stated so they cannot be softened later:

1. **No production credentials were requested, offered or used.** Everything measured in this
   audit was measured from the development environment against the repository, a locally
   built contract, a locally built temporal ledger and a locally booted stack.
2. **The five units stay `CLOSED-PENDING-PROD`.** Completing this audit does not advance them.
   `docs/EXECUTION_PLAN.md` §0.2 is unchanged: a unit becomes `CLOSED` only when its
   production verification succeeds against the deployed merge SHA, and the reserved
   completion phrase in `docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md` §15 stays unclaimed.
3. **This audit's verdict is not production closure and must not be cited as one.** It is a
   verdict on what is reachable. §6 enumerates exactly what remains.

Outstanding on production because it cannot be measured here at all:

* the `canonical_board` lane of the temporal ledger — an archive-only backfill populates
  `scraper_blend` and `source_value`, while the canonical lane comes from live recording at
  the fresh-scrape site in `server.py`;
* `rankChange`, correctly `null` on all 1,109 rows offline for want of a ledger comparator.

### F-5 · `value_as_of` raises a raw `strptime` error on an ISO datetime string · CONFIRMED · minor

Its signature accepts `str`, but an ISO-8601 *datetime* string produces
`ValueError: unconverted data remains: T23:00:00` from `strptime` rather than being parsed or
refused with the module's own `ObservationError`. Cosmetic — `value_known_before` is the
instant API, and it refuses a naive datetime correctly and clearly.

**REPAIRED 2026-08-18 (#903, `274f701cd`).** The string branch now delegates to the datetime
branch rather than carrying its own narrower parse, so one rule governs both entry points.

---

### F-6 · A production source went unfetched for 12.6 days while every surface called it OK · CONFIRMED · source integrity · **REPAIRED 2026-08-18**

`draftSharks` and `draftSharksIdp` last fetched successfully at **2026-08-05T18:13:02Z** and had
failed every 2-hourly cycle since — **303.5 h** at measurement. Both boards were still voting in
the canonical blend at full weight, on twelve-day-old evidence.

**Three surfaces reported it healthy, for three different reasons:**

| surface | what it said | why it was wrong |
|---|---|---|
| refresh **scrape sanity** | `draftSharksSf: 454 rows OK` | it counts rows in the file **on disk**. A stale file still has rows |
| `data/scrape_state` at a glance | `draftSharksRos_last_success` = 1.8 h | the ROS feed is a **different endpoint** and always worked |
| `/api/status` `source_health` | `total_sources: 2` | its denominator is the 2-row `sites` list — see F-7 |

Only `scripts/watchdog_freshness.py` caught it, and its verdict was the **sole** condition
failing the scheduled refresh on six consecutive runs.

**Root cause.** The dynasty board is htmx-delivered and parameterised by `#sharedParams`; its
unfiltered form returns 250 rows and **no IDP at all**. The fetcher read that single pass.

**Repaired** by #894 (`77f037ef2`): traverse the page's own `fantasyPosition` filter on the same
authenticated league-scored session, union on the vendor's `data-key`, with three fail-closed
guards (vendor-id union, expected-family completeness, per-pass league-scoring proof) and an
exact-`Decimal` cross-pass equivalence gate.

**Production proof — green.** `scheduled-refresh` run `32123775865` passed every gate and
auto-closed tracking issue #765; stamps **303.5 h → 0.03 h**. The production CSVs are
**byte-identical** to the candidate that was verified beforehand, so the measured board movement
is the actual production movement: 418 values moved (p50 0.2%, p90 1.0%, max 6.9%), 438 ranks,
660 tier renumberings, 6 rank-cap boundary crossings, **0 unexpected**. Full record and §25
classification: `docs/sources/DRAFTSHARKS_DYNASTY_INGESTION_REPAIR.md`.

**What this leaves open:** the scrape-sanity row count still cannot distinguish "the vendor
answered" from "the file is still there" (census **S-3**), and F-7 below.

---

### F-7 · The source-health headline counts 2 sources for a board carried by 21 · CONFIRMED · observability · **REPAIRED 2026-08-18**

`server.py::_build_source_health_snapshot` derives `total_sources`, `sources_with_data`,
`source_counts` and `missing_sources` from `payload["sites"]`. Measured on the live export
`exports/latest/dynasty_data_2026-08-18.json`, `sites` has exactly **2 rows** — `ktc` (500) and
`idpTradeCalc` (900). So `/api/status` reports **2 of 2 healthy, 0 missing** for a board carried
by **21 registered production voters**, and `/tools/source-health` renders that.

The defect is the **denominator**, not the arithmetic. Twenty voters are absent from the
population, so a source that stops contributing entirely cannot appear in `missing_sources` — it
was never counted. This is `MISSING IS NEVER ZERO` at the health layer, and it is the rule the
confidence gate already gets right ("a family that stops covering a row stays eligible, so its
silence is permanent missing evidence").

**It is already known in the code, and the response was a second surface rather than a fix.**
`server.py:4765` says verbatim that `source_health` *"is derived from the 3-source legacy `sites`
list and cannot detect a degraded board"* — and the payload then adds
`served_source_coverage` beside it. That is a **second owner of one concept**, and it has the
same defect from the other direction: it counts `sourceRankMeta` occurrences with no registry
denominator, so a zero-contribution source is simply an absent key. Two surfaces, neither able to
say a registered source went silent.

(The comment is also stale by one — the population is 2 today, not 3.)

**Not `coverageAudit.expectedSites`.** That block is an *anchor-loss detector*
(`{"offense": ["ktc"], "idp": ["idpTradeCalc"]}`) and **2 is correct for it**. Widening it would
break the thing it does well. The population belongs to a separate owner.

**The page symptom is worse than the headline.** `/tools/source-health` — subtitled *"Scraper
status for every ranking source in the pipeline"* — builds its row list from
`source_runtime.enabled_sources`, which on the live export is `["KTC", "IDPTradeCalc"]`: the
scraper's own **run names**, two of them. It then looks each up in `source_counts`, whose keys
are registry-shaped. `"KTC".toLowerCase()` finds `ktc`; `"IDPTradeCalc".toLowerCase()` is
`idptradecalc`, which matches nothing. So the page rendered **two rows for a 21-source pipeline,
one of them showing a dash**.

**REPAIRED.** The population now comes from `data_contract.get_ranking_source_keys()` — the
registry that already owns it, no new owner invented. Per-source counts come from the served
board's `sourceRankMeta` (`_compute_served_source_coverage`), so `served_source_coverage` becomes
the *input* the answer is built from rather than a second competing answer. Measured on the
golden fixture: **`total_sources` 2 → 21**, every registered voter present with a real count.

Three states are now distinct, because collapsing them is the defect:

| state | field | meaning |
|---|---|---|
| contributed | `source_counts[k] > 0` | it voted on N rows |
| silent | `missing_sources` | registered, measured, voted on **nothing** |
| unknown | `unmeasured_sources`, count `null` | no served board was supplied — **unknown is not zero** |

The scraper's anchor row counts survive under `anchor_row_counts`, named for what they are; they
are a different quantity from board contribution and merging them into one map was the defect.
`coverageAudit.expectedSites` is untouched at 2 entries and is now pinned by a test that fails if
a future change smuggles the population into it.

Measuring it also corrected the census's own vote figures: counting `canonicalSiteValues > 0`
drops legitimately **negative** vendor values, so `draftSharksIdp` reads 143 against 269 actual
votes. Health counts off `sourceRankMeta`, which is sign-agnostic.

Guards: `tests/api/test_source_health_population.py` (4 assertions, mutation-proven against
"population back to the anchor list" and "count silence as healthy") and two cases in
`frontend/__tests__/components/source-health-strip.test.jsx` (mutation-proven against reverting
the row list to `enabled_sources`). Census item **S-1** closes.

---

### F-8 · 18 build-check suppressions rested on a source that no longer exists · CONFIRMED · evidence integrity · **REPAIRED 2026-08-18**

`SINGLE_SOURCE_ALLOWLIST` suppresses `assert_no_unexplained_single_source` for top-board players
legitimately carried by one source. Every entry is a human-readable statement of **why**. Nothing
checked that the statement was still true.

Measured on the 2026-08-18 board: **25 of 52 entries mentioned FootballGuys, and 18 named it as
the sole ranker** — a source that is in no registry, has no CSV path, no CSV file, and last
stamped `2026-05-24` (86 days). Not one of the 18 was true:

| | count | what was actually there |
|---|---|---|
| not on the board at all | 2 | Lavonte David, Zyon McCollum — dead entries |
| on the board, **not single-source** | 14 | most extreme: **Zavion Thomas carries 13 sources** under an entry reading "only ranked by FootballGuys" |
| still single-source | 2 | but by `draftSharks` and `fantasyProsSf` — and both sit past `OVERALL_RANK_LIMIT`, outside the window the gate polices |

So the gate was being suppressed by explanations that had quietly become fiction. Removing all 18
leaves the contract at **`ok: True`, 0 errors** — they were guarding nothing.

Three further inconsistencies surfaced while normalising the machine-readable prefix:

- `source_gap:ktc_only` (×3) used the grammar **backwards** — the prefix lists the sources that do
  NOT carry the player, and this one named the one that does. The prose already said it correctly.
- `dynastyNerds` (×7) and `flock` (×2) were loose spellings that resolve to no source key or
  family name.

**REPAIRED**: 18 false entries deleted, 7 entries stripped of the phantom `footballGuysIdp` in
their gap lists, the three grammar/spelling classes normalised, and the orphaned
`footballGuys*_last_success` stamps (frozen at 2026-05-24, no writer, no CSV, no registry entry)
untracked.

**The durable repair is the guard, not the deletion.** `tests/api/test_single_source_allowlist_integrity.py`
asserts every prefix token resolves to a live source key, CSV-path key or correlation-family name,
**and** that no prose reason names a sole ranker the registry does not contain — the prose half
matters, because all 18 named FootballGuys in prose while their prefixes named other sources, so a
prefix-only check would have passed every one. Mutation-proven against reinstating a FootballGuys
entry and against reinstating a loose token. Census item **S-5** closes.

---

### F-9 · The board-diff harness hashes two inputs; the board has three · CONFIRMED · test integrity · **REPAIRED 2026-08-18**

`scripts/golden_board.py` exists so that a board change is measurable, and its own docstring says
so in capitals: *"THE CONTRACT HAS **TWO** INPUTS, AND BOTH MOVE"* — the pinned export and the
per-source CSVs, both hashed, with `board_diff.py` refusing to compare captures whose inputs
differ.

There is a third. `data_contract._source_freshness_flags()` stats every registered source's
`data/scrape_state/<key>_last_success` **at build time** and feeds the tri-state to the B11
confidence gate.

Measured by perturbing **only** the stamps, with the export and all 24 CSVs byte-identical:

| perturbation | values | ranks | confidenceBucket | confidenceLabel |
|---|---|---|---|---|
| one stamp (`draftSharks` → 303 h) | 0 | 0 | 0 | 0 |
| **all 28 stamps → deeply stale** | **0** | **0** | **588** | **705** |

So the stamps drive **confidence, not price** — `A.J. Brown: high → low`, *"High — every axis
high"* → *"Low — limited by freshness"*. A single stale stamp moves nothing, because `overall` is
the weakest axis and one source rarely decides it, which is exactly what makes this drift easy to
miss. And `data/scrape_state` is force-added by the 2-hourly refresh, so **two captures spanning
one refresh are guaranteed to differ here** while both value assertions read clean.

**REPAIRED**: `freshnessSha256` / `freshnessStampCount` are hashed into every capture (content, not
mtime — a checkout rewrites mtimes and a digest that cried wolf would teach people to pass
`--allow-input-change` unread), and `board_diff.py` refuses on a mismatch and on a capture that
does not record it. Verified: a repeat capture on one tree state is exactly identical (0 values, 0
ranks, 0 labels), and the guard names the stamp drift by hash.

**A correction to my own working note.** An earlier A/B in this session attributed 47
`confidenceLabel` flips and 5 pick-value moves to stamp drift. That was wrong — those captures also
spanned the 09:54–09:57 scrape, so the CSV set had moved too. The one-stamp perturbation above
moves **nothing**, and the all-stale figure is the honest evidence. The finding stands on the
measurement, not on the guess that led to it.

---

### F-10 · The board's only retail anchor is watched by nothing · CONFIRMED · source integrity · **REPAIRED 2026-08-18**

`ktcSfTep` is the single most load-bearing offense input the pipeline has. It is the only
`is_retail` source in `_RANKING_SOURCES`; it is the TE basis the whole board is anchored on, so
every non-TEP TE row is *converted onto* it (ADR-015); it is half the pick anchor set
(`pick_anchor = cross_market | {"ktcSfTep"}`); and it is the head of the `ktc` correlation group.

Nothing watched it. Measured on the 2026-08-18 board by removing KTC's TE++ sub-board entirely
while leaving the base `ktc` CSV intact:

| gate | verdict on a board with no retail anchor |
|---|---|
| `validate_api_data_contract` → `sourceHealthErrors` | **`[]`** — no floor is configured for `ktcSfTep` |
| `validate_api_data_contract` → `ok` | **`True`** (`status: degraded`) |
| `coverageAudit.offense` | **`deficitPlayers: 0`, `missingBySite: {}`** |
| structural lane | one error: `confidence_basis_contradicts_value:Travis Hunter` |

**Board movement under that silence: 444 of 468 comparable offense rows, median |Δ| 804, p90 3907,
max 8405** (Joe Royer 1592 → 9997, Malik Benson 1347 → 9695, Nate Boerkircher 1714 → 9998). Both CI
lanes pass and Deploy Production ships it.

The one thing that reddened the live-board mutation was **incidental**: the two-way boost lost its
offense input for Travis Hunter, producing a structural self-consistency error naming one player.
Removing that single player from the same mutant restores `ok: True`. A coincidence is not a guard,
and the diagnosis it offers points at the wrong thing entirely.

**Why the anchor was pointed at the wrong board.** `coverageAudit.expectedSites.offense` names
`ktc` — which is *not a blend voter*. `_RANKING_SOURCES` says so explicitly: the standard `ktc` CSV
was dropped from the blend on **2026-04-28** as a KTC double-count and `ktcSfTep` was promoted to
the canonical retail source. Every offense health gate stayed pointed at the retired spelling —
**three of them**, for 112 days:

| gate | watched | should watch |
|---|---|---|
| `config/weights/source_row_floors.json` | `ktc: 400` | + `ktcSfTep` |
| `config/weights/top50_coverage_floors.json` `offense` | `ktc: 48` | + `ktcSfTep` |
| `Dynasty Scraper.py::TOP_OFF_EXPECTED_SITE_KEYS` → `coverageAudit.expectedSites.offense` | `("ktc",)` | see S-2 below |

`ktc` is nevertheless **not** dead weight, and this document should not imply it: measured on the
2026-08-18 board it covers the 501 rows `ktcSfTep` covers **plus 60 pick rows `ktcSfTep` does not
cover at all**, and both `src/trade/finder.py` and `src/bdvm/market.py` resolve
`("ktcSfTep", "ktc")` in that order — so on those 60 picks `ktc` is the only KTC market answer
either engine has. Retiring it from the *blend* was right; it is still a consumed input. The defect
is that the guards watched the non-voter **instead of**, not **as well as**, the voter.

The failure mode is not hypothetical. `_ktc_extract_tep`'s own docstring records it: a KTC payload
shape change makes the extractor return `None` for every row while base SF values parse fine — the
earlier version "crashed on `int(float({}))` and silently skipped — **leaving ktcSfTep.csv empty**".

**It is nevertheless a latent hole, not a shipped board, and this document says so.** Scanning
every committed export archive in the window, exactly one carries zero `ktcSfTep` rows
(`dynasty_export_20260816_190904`), and that one was a **whole-KTC timeout**
(`sourceRunSummary.timedOut: ["KTC"]`, `sites` playerCount 0) which the existing guards *did* catch
— `coverageAudit.offense` reported `deficitPlayers: 300`. It is the 2026-08-16 incident, not this
one. No committed archive shows a board published with the asymmetric failure.

**REPAIRED**, at both ends, because they guard different moments:

* **contract floor** — `_DEFAULT_SOURCE_ROW_FLOORS["ktcSfTep"] = 400`, so the condition becomes
  `source_missing:ktcSfTep`, which is already a `_SOURCE_HEALTH_ERROR_KINDS` prefix. That puts it
  in the **correct lane**: the FULL lane blocks the deploy without the structural lane turning
  every open PR red — the split `docs/ops/STABILIZATION_2026-08-16.md` established, used as
  designed.
* **top-50 coverage floor** — `top50_coverage_floors.json` `offense.ktcSfTep = 48`, catching the
  other failure: a board that still returns enough rows to clear the row floor but has stopped
  covering the premium tier. Live coverage is 50/50, so 48 is the same baseline-minus-5% this file
  already applies to `ktc`.
* **scraper floor** — `_KTC_TEP_SITE_RAW_FLOOR = 400` wired into `Dynasty Scraper.py`'s
  `_site_raw_floors`, so a degraded map SKIPS the write and the restore-previous pass preserves
  last-good. The contract floor only reports a board that already arrived empty; this one stops
  the empty board overwriting the good one.

`tests/api/test_source_floor_invariant.py` demanded the second half — adding the contract floor
alone made it fail with *"ktcSfTep: no internal scraper floor found, but not in
`_KNOWN_FLOOR_GAPS`"*. That allowlist carries an explicit instruction to **fix the scraper rather
than allowlist the gap**, and it is still empty.

**400 is not an invented number.** It is ~80% of the 501-row live baseline (this file's own stated
floor policy) *and* the floor already carried by `ktc` — the twin board produced from the same KTC
API response, with an identical 501-row count.

**Mutation-proven both ways.** Removing the contract floor reddens 7 of 9 assertions including the
behavioural one; un-wiring the scraper dict while leaving the constant defined reddens the two
wiring assertions, which read the `_site_raw_floors` dict literal from the **AST** rather than a
constant name or a comment. Pinned by `tests/api/test_retail_anchor_row_floor.py` (13).

**What this does NOT close, named rather than implied.** The scrape-promotion gate
`server.py::_missing_expected_sites` still watches `ktc`, because `ktcSfTep` never reaches
`raw.sites` at all: `KTC_TEP` is a sub-product held in `FULL_DATA`, not a member of `active_sites`,
so `sites_meta` never emits it and `_reported_rows` could not find it if `expectedSites` named it.
That is census item **S-2** — scraper-run names do not round-trip onto registry keys, and a
run-level "complete" does not decompose into which boards arrived — and F-10 is S-2 seen from the
consequence end.

---

### F-11 · A source that loses all its evidence vanishes from the freshness watchdog · CONFIRMED · observability · **REPAIRED 2026-08-18**

`scripts/watchdog_freshness._read_freshness` prefers the `_last_success` stamp, falls back to
the CSV mtime, and when **neither** exists does `except OSError: continue` — the source leaves
the population entirely. `classify_freshness` then iterates only what survived, so it is not
fresh, not soft-stale and not hard-stale: it is unaccounted for, and nothing says so.

Measured by injecting one evidence-less registry key:

```
present in freshness dict : False
hard_stale=0  soft_stale=0  fresh=22
named in ANY bucket       : False
=> "22 sources fresh, 0 hard-stale", exit 0
```

`main()`'s `if not freshness` guard catches only the **total** wipe ("No sources could be
read"), never a partial one — so deleting evidence promoted health. Same defect class as F-7's
empty coverage map, and the same rule `src/api/confidence.py` applies to its coverage axis: the
denominator is what COULD have been observed.

It propagated: `scripts/check_source_health.py` deliberately reuses this rule ("no second
freshness rule"), so the advisory PR check inherited the hole.

**REPAIRED** by a named fourth state, `unmeasurable_sources()`, consumed by both scripts — the
watchdog fails on it and names each one, `check_source_health` reports it in its JSON and its
summary line. Counts appear on **both** exit paths, because the defect being reported is
precisely a source vanishing from the report.

Kept as a separate function rather than a fourth bucket on `classify_freshness`: that 3-tuple
is unpacked at eight call sites and `_read_freshness`'s shape is consumed by three more
scripts. `test_unmeasurable_is_invisible_to_classify_freshness` pins that the two mechanisms
stay complementary rather than one silently covering for the other.

**It reports UNKNOWN and nothing more** — no age, no threshold, no staleness verdict is
invented, so census item **S-6** (is stale evidence still a full-weight vote?) is untouched.
Inert today: all 22 registered sources carry evidence.

**Mutation-proven, and the first version of the wiring guard FAILED that proof.** It walked
every `ast.If` in `main()` and collected the names appearing in any of them — which the summary
block's own `if unmeasurable:` satisfied, so it passed with the success gate reading
`if not hard_stale:` and an unmeasurable source still exiting 0. It now targets the branch that
actually returns 0. Pinned by `tests/api/test_watchdog_unmeasurable_source.py` (7).

---

### F-12 · Every failure-attribution path in the health UI compares two disjoint vocabularies · CONFIRMED · observability · **OPEN (census S-2)**

`server.py::_push_failure` writes `failures[].source` as the scraper **run name** verbatim.
`frontend/components/SourceHealthStrip.jsx` compares it against **registry keys** — `toneFor`'s
"Hard signals first" branch (`runtime.failed_sources.includes(source)` /
`partial_sources.includes(source)`, lines 51-52) and `failedReason`'s
`health.source_failures.find(f => f.source === src)`.

Measured over 176 committed export archives:

```
archives carrying a failed/timedOut/partial source : 170
of those, naming a REGISTRY key                    :   0

run-name vocabulary emitted:  KTC_TradeDB 170 · KTC_WaiverDB 170 · KTC 1
```

So the hard-signal branch has never been reachable and per-row `failedReason` is always null;
tone always falls through to the age rule, and a source that failed under 4 hours ago renders
green.

**Honest sample note**: 170×2 of those entries are `KTC_TradeDB` / `KTC_WaiverDB`, the crowd-DB
paths retired by KTC-4 on 2026-08-18, so they are largely pre-retirement noise. The one genuine
critical failure in the window is `KTC` on 2026-08-16 — which matches no registry key either.
The defect is the disjoint vocabularies, not the volume.

Tracked as census **S-2**, with F-10 as its other consequence. Not repaired in this pass: the
repair is a mapping owner touching the scraper and a production scrape-promotion gate, which is
its own unit.

---

### F-13 · The mobile view is the LARGEST of the optimized views · CONFIRMED · performance · **OPEN**

Measured on a 1109-row contract, each view serialized as `server.py` does and gzipped at
level 6:

| view | raw MB | gzip KB |
|---|---|---|
| full | 14.21 | 1144.2 |
| **array** (desktop) | 7.86 | **662.6** |
| **compact** (mobile / slow network) | 8.96 | **764.6** |

**compact is +15.4% over the wire versus array.** `src/api/compact_view.compact_contract`
prunes ~20 audit/trust fields but keeps **both** parallel player encodings — verified, the
returned object carries `players` (dict) *and* `playersArray` — while the array view drops the
legacy dict outright, which is where the weight is. `frontend/lib/device-profile.js` routes
"mobile / slow network" to compact and desktop to array, so phones on slow connections receive
102 KB more gzipped than desktops on fast ones.

`server.py`'s comment on that branch claims "~90% byte reduction". Measured against full it is
37% raw / 33% gzip, and against the other optimized view it is an increase.

Not repaired here: dropping the dict needs a consumer sweep for `players[name]` reads, which is
its own unit. The budget test that would have caught it does not exist — see the performance
census.

---

### F-14 · The `/api/dynasty-data` bridge answers 200 off disk when the backend says 401 · CONFIRMED · security / data integrity · **REPAIRED 2026-08-18**

`frontend/app/api/dynasty-data/route.js` streams the backend response only when
`res.ok && isJson`. Its own comment states the else branch plainly: *"Non-2xx, or a 200 that
isn't JSON — fall through to disk."* The fallback is
`const parsed = loadFromDisk(); if (parsed) return NextResponse.json(parsed);` — **HTTP 200** —
and `loadFromDisk` reads the newest `dynasty_data_YYYY-MM-DD.json`, which is the **raw scraper
export**, not the contract. It also fires on a `BACKEND_IDLE_TIMEOUT_MS = 4000` header stall.

Two independent defects:

**(a) A refusal is converted into a grant.** `401` is non-2xx, so an unauthenticated caller
gets the board off disk under 200. The Next gate cannot save this — `frontend/middleware.js`'s
matcher is `"/((?!_next/static|_next/image|api/|.*\.[\w]+$).*)"`, which **excludes `api/`** by
design, because the backend's `/api/*` gate is meant to be the authority. The fallback overrides
it. Measured against a real booted stack: unauthenticated request → `code=200 size=635170`
while the backend answered `401`, byte-identical to the disk file; CI artifact for run
32120428479 shows ten `GET /api/data?view=array HTTP/1.1 401 Unauthorized`.

**(b) 200 for a payload that is not the contract.** I measured the raw export's shape — no
`playersArray`, no `contractVersion`, no `meta`, zero rank stamps. That is exactly what
`buildRows` fail-fasts on, so a 4-second stall or a 401 renders an empty board while every
status surface stays green, and the client cannot distinguish "here is the board" from "here is
a raw scraper dump" because both are 200. MISSING IS NEVER ZERO, at the HTTP layer.

**Scope, stated honestly.** Production as configured is **not** affected: I verified the
route's own claim — `deploy/nginx/chaseupside-proxy.conf:54` and
`deploy/nginx/riskittogetthebrisket.org.conf:186` both carry
`location /api/ { proxy_pass … backend; }`, so `/api/dynasty-data` never reaches Next in
production. (The comment cites `chaseupside.com.conf`; the block actually lives in the shared
`chaseupside-proxy.conf` snippet.) Affected: dev, CI/E2E, and "any Next-fronted deployment" — a
topology the route says it handles. The protection is a deployment convention, not a property of
the code, and nothing tests it.

This also supersedes the standing **F-3b** diagnosis, which attributed the journey-rankings
failure to a stack-readiness race. The readiness gate passes; the board never talks to the
backend at all.

**REPAIRED by removing the fallback, not by validating it.** Measured every candidate
`loadFromDisk` could reach — `exports/latest/dynasty_data_*.json`, `data/dynasty_data_*.json`
and `dynasty_data.js` — and **all three are the raw scraper export**: no `contractVersion`, no
`playersArray`, zero rank stamps. So the path could not serve a usable board on ANY input; it
only ever converted a diagnosable backend status into an undiagnosable empty board. Validating
it would have rejected all three candidates, i.e. disabled it while leaving the seam.

The backend's answer now propagates: `401` / `403` / `5xx` verbatim (with `www-authenticate`
preserved, so a refusal keeps its challenge), a transport failure or header-time abort becomes
`503` with `reason: backend_unreachable` / `backend_idle_timeout`, and a non-JSON 200 becomes
`502 backend_non_json`. No client change was needed — `fetchDynastyData` already throws on
`!res.ok` (`frontend/lib/dynasty-data.js:1587`), so the hook's existing error state surfaces an
explicit banner where the old path rendered a silent empty board.

`loadFromDisk`, `listCandidates`, `newestFile`, `parseDynastyDataJs` and the `node:fs` import
are **deleted**, not left dormant — a fallback nobody can reach is a seam somebody re-threads,
and one of the new assertions reads the file to prove it is gone rather than merely unused.

**RED first, and measured**: 9 of 12 assertions fail against the pre-repair route — every
auth-propagation case, both transport cases, the non-JSON case and the structural one. The 3
that pass are the happy paths (streaming, 304 round-trip, cookie + `view`/`leagueKey`
forwarding), which are deliberately unchanged. Frontend suite: 2055 passed across 127 files.
Pinned by `frontend/__tests__/dynasty-data-bridge-no-disk-fallback.test.js` (12).

The stale nginx filename in the route's own comment is corrected to
`deploy/nginx/chaseupside-proxy.conf` at the same time.

---

### F-15 · The row-floor guard is opt-in, and 8 of 21 registered voters had opted out · CONFIRMED · source integrity · **REPAIRED 2026-08-18**

F-10 repaired one source. This is the class it belonged to.

`validate_api_data_contract` drove its zero check off `_load_source_row_floors()`, iterating
`row_floors.items()` — so a key with no floor entry was never counted and never checked.
**Absence of a threshold silently meant absence of a check.**

Measured with F-10's `ktcSfTep` floor already in place, zeroing each registered voter's
`canonicalSiteValues` in a built contract one at a time — 8 of 21 produced `ok=True` with an
empty source-health lane:

| still silent | live rows |
|---|---|
| `fantasyProsSf` | 474 |
| `pfkDynasty` | 472 |
| `fantasyNavigatorSf` | 454 |
| `otcffbSf` | 447 |
| `fantasyCalc` | 388 |
| `dlfRookieSf` | 112 |
| `flockFantasySfRookies` | 76 |
| `dlfRookieIdp` | 29 |

Three of those were not oversights but **expired promises**: the `_DEFAULT_SOURCE_ROW_FLOORS`
note of 2026-07-25 said floors for `fantasyCalc` / `fantasyNavigatorSf` / `pfkDynasty` were
"intentionally NOT set yet … Add entries here once live canonical match counts are observed."
The counts now exist — 388 / 454 / 472 — and the entries were never added.

**REPAIRED** by separating two questions, only one of which needs a number. *Is it gone?* needs
no calibration, so its population is the **registry** (`get_ranking_source_keys()`) union the
keys that declare a floor — the union keeping `ktc`'s guard, since it carries a floor and the
KTC pick market while not being a blend voter. *Is it thin?* keeps the floors map. Nothing is
invented, so **S-6 is untouched**.

**Is zero ever legitimate? Checked, not assumed.** The rookie boards were the plausible
seasonal exception, so I read the tracked git history of every previously-unguarded CSV (up to
60 commits each): `ever_zero = 0` on all eight, minimums 29 to 758 rows. Should a source ever
acquire a legitimate empty state it gets an explicit reasoned declaration, never a silent
omission.

Board-inert: the live contract still validates `ok=True`, `status=healthy`,
`sourceHealthErrors []`, no new warning. Mutation-proven — restoring the floors-driven loop
reddens 9 of 26 assertions, including the structural one that states the population as a
*property* rather than a name. Pinned by `tests/api/test_registered_voter_zero_check.py` (26).

**Separately, and not conflated with the above**: the three expired promises should either
become real floors at the file's own stated ~75-80% policy or be deleted as promises. Adding
them is not required for the zero check and is left as an owner-visible decision.

---

## 2. Repairs made during the audit

Each is a repair-only PR: exact-head CI, mutation-proven where structural, merged on green.

| batch | PR | what was wrong |
|---|---|---|
| **A** | #885 | The deploy's readiness loop accepted only 200 while `/api/health` returns **503 when degraded**, so it could not tell "booting" from "degraded" — it exhausted silently and hard-failed a deploy whose remote script had already succeeded. An empty `PROD_PUBLIC_URL` silently skipped both post-deploy steps **green**. `release-candidate.yml` claimed parity with PR Validation and omitted **8 gates**, including `npm test` and the frontend build — the HEAD-FREEZE tree was validated more weakly than any PR. |
| **B** | #886 | Three §3d violations in the blocking gate: hard-gate tests asserting absolute counts and floors over the **live board**, so a source outage reads as a code regression. Worst was a `decisions > 1000` floor that would fail every open PR. |
| **C** | #887 | `tests/picks/` had no source-text owner guard — which is why C2-U1's retirements held and the pick duplicates did not. Added the guard, routed the `tier_centre_slot` literal through the owner, and re-pointed a parity test that had been comparing **two literals to each other** (so both could drift from the owner together). |
| **D** | #888 | An unknown FAAB budget became a fabricated `$100` — verbatim the example the repo's own coercion gate names in its docstring, still live on the path that builds the market priors, and the **denominator** of every `bidPct` in a league that has run $1,000 and $200. Separately, `resolveAssetValue` booked unpriced assets at `$0` of team value while the correct helper sat 900 lines above it in the same file; it bites hardest on picks, where every 2027/2028 5th and 6th is legitimately unpriced. |
| **F** | #890 | The blocking hard gate **had a midnight**. `tests/deploy/test_backup_root_resolution.py` reads the clock once at import; two tests re-read it later, so a suite crossing 00:00 UTC collapses `yesterday` onto `TODAY` and builds its deliberately-older generation on top of the newer one. It took down #886 and #888. Reproduced byte-for-byte against the CI log. A `DATE_STAMP` fix the day before had pinned the *script's* clock and stopped there. |
| **H** | #893 | The E2E board diagnostic — see F-2. |
| **G** | #891 | A regression test **required private intelligence to be public** — it asserted `faabAnalytics` answers an anonymous caller with 200, when B8 made it one of three `PRIVATE_INTELLIGENCE_SECTIONS` returning 401. The obvious way to green it is to reopen the section, deleting a privacy boundary to satisfy a stale test. The boundary is now pinned for all three sections through **both** doors (the `.csv` route was untested); the shape coverage moved to a signed-in spec rather than being dropped. |
| **E** | #889 | Governance — see §3. |

---

## 3. Governance drift repaired (batch E, #889)

`docs/EXECUTION_PLAN.md` is, by the repository's own classification, **"the ONLY record of
current sequencing and explicit next authorized scope"**. It said the continuous C0→C10
campaign was authorized and that units execute *"without asking permission between them"* —
after the freeze had been imposed. **A fresh session reading the canonical authorization record
would have started `C2-U2`**, which the directive names first among the things not to begin.

Also repaired: five merge-queue rows still reading "deploy frozen since 00:35Z" nine hours after
it unfroze; two scope-manifest rows contradicting rows further down the same file (pick identity
"to be created — 7 representations" vs the owner created and the census measured at 39 sites;
acquisition history "ABSENT" vs `src/acquisition/` delivered); three C1 units with no state
line; and two `WORK_CLAIMS` rows advertising live editors for finished work, one of them
pointing at a branch that **no longer exists on the remote**.

---

## 4. Checks that passed, measured

| area | result |
|---|---|
| §21 pick census | 144 non-alias pick rows: **0 zero-valued, 0 null-valued, 0 provenance-less**. 2029 stamps **no** `direct_market_blend`. 18/18 cells strictly below their 2028 twin, by derivation. Round monotonicity holds in all 9 year×tier groups. |
| §7 one canonical value | No `offenseOnly*` second board survives (W29-F001 stays closed). 849 priced values all within [834, 9992] — inside the declared 1–9999 scale. Zero duplicate `displayName` rows. |
| §11 confidence | 849 priced rows, **0 without a `confidenceBasis`**. Bucket equals the **weakest** axis on every row carrying axes — the bottleneck holds, nothing averages. The 260 `none` buckets are exactly the 260 unpriced rows. |
| §14 lineup | All 12 teams carry a server-stamped `optimalLineup`. **78 unpriced players across the 12 rosters, none in starters or bench** — the third state is real. No player in two slots. `slotSource='sleeper_roster_positions'` (the live ladder's top rung, not a literal). One roster honestly reports `unfilledSlots=['K']`. |
| §10 temporal | 8/8 queries `exact`, **0 selections of an observation later than the query**, distinct per-day values. Far-future → `nearest-prior`, inventing nothing. Pre-floor → `before_history_boundary`; in-floor-but-uncovered → `no_prior_observation` — **distinguishable**. A naive datetime is refused outright. |
| §25 league boundary | `/api/leagues` leaks no Sleeper IDs. `dynasty_new` is **refused** rather than served `dynasty_main`'s board. An unknown key 400s `unknown_league`. |
| missing≠zero | `pickValueProvenance`, `confidenceBasis`, `rankChange`, `marketGapValueRatio` — every one uses `null` for missing, **zero occurrences of 0-as-missing**. |
| governance gates | `check_planning_integrity` (11 invariants), `check_product_plan_governance`, `audit_status` ("no drift: every recorded status matches its probe"), `tests/docs` all clean. |

---

## 5b. §22 board diff — the repairs are inert on the canonical board

Captured with `scripts/golden_board.py` **holding the input fixed** and varying only the code,
which is the comparison that isolates code effect (the script's own help warns that diffing
captures whose inputs differ is invalid, and `exports/latest` has taken several automated
refreshes since the audit base).

* **before** — code at audit base `96ecc22a9`, in a throwaway worktree
* **after** — code at current `main`, all seven repair batches merged
* **input** — one pinned copy of `exports/latest/dynasty_data_2026-08-17.json` for both

```
rows: 1109 -> 1109   ranked: 740 -> 740   priced: 849 -> 849
picks: 162 -> 162    idp:    397 -> 397

VALUES: 0 moved, 0 newly priced, 0 newly unpriced
RANKS:  0 changed
ASSERTION OK: no value changed.          (--expect-no-value-change, exit 0)
```

**Classification: EXPECTED — inert.** No `INCIDENTAL-BUT-EXPLAINED`, no `UNEXPECTED`.

This is the predicted result rather than a lucky one, and the prediction is what makes it
evidence: of the seven batches, only three touch anything importable by the board path, and
each was chosen not to move a value — batch C replaced a duplicated `tier_centre_slot` literal
with a call to the owner on an **alias-only, non-pricing** path; batch D repaired
`src/trade/faab_history.py` (a market-prior input, not a board input) and a frontend
materializer; the rest are workflows, tests and documentation. A non-zero diff here would have
meant one of those three was not what it claimed to be.

---

## 6. What authenticated production verification remains

Enumerated so it can be completed separately, through whatever access method is safe, by
someone who already holds the credentials. **None of this requires handing credentials to an
agent** — each item is a check a human or a scheduled job on the box can run and record.

| # | check | where it is specified | why it cannot be done here |
|---|---|---|---|
| P-1 | `C0-R` production checklist | `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` §7 | needs an authenticated session against the deployed SHA |
| P-2 | `C1-U5` — every priced row on the LIVE board carries a valid `confidenceBasis` | `docs/confidence/C1_U5_CONFIDENCE_NAMING.md` §6 | the live board is not this board |
| P-3 | `C1-U8` — acquisition ledger populated by real production transactions | `docs/acquisition/C1_U8_ACQUISITION_LEDGER.md` §8 | the ledger is gitignored and lives on the box |
| P-4 | `C1-U9` — source archive receiving real paired variants per scrape cycle | `docs/sources/C1_U9_MULTI_FORMAT_SOURCE_ARCHIVE.md` §7 | requires observed scrape cycles |
| P-5 | `C2-U1` — `optimalLineup` survives the LIVE Sleeper overlay splice on the normal path | `docs/lineup/C2_U1_CANONICAL_LINEUP.md` §10 step 3a | the defect it exists for only appears when Sleeper is UP |
| P-6 | temporal ledger `canonical_board` lane is being recorded | `docs/history/C1_U4_TEMPORAL_LEDGER.md` | populated only by live post-scrape recording |
| P-7 | `rankChange` resolves against a real prior board date | same | needs ≥2 recorded canonical board dates |
| P-8 | §7 cross-surface value parity on real production (API vs desktop vs mobile vs trade vs profile) | audit directive §7 | needs an authenticated production session |

A safe method for each: run the check **on the box** (or in the existing scheduled-job
context) and paste the output back. Nothing in this list needs an interactive credential
handoff.

---

## 5. Still to run

Phase 3 (performance budgets, accessibility, the remainder of observability), Phase 4 (the
independent adversarial pass over all 20 lenses), and Phase 5 (production proof against the
deployed SHA, the §22 board diff, and the full regression sweep) have not been completed. The
verdict is withheld until they have.

### Interruption: the 2026-08-18 CI incident

This audit was suspended mid-phase to work a reported seven-workflow CI failure. Record:
`docs/ops/CI_INCIDENT_2026-08-18.md`. Three of its outcomes belong to this audit's evidence
base and are carried here so the verdict accounts for them:

* **Scheduled Data Refresh had failed on EVERY run for at least three days** — 30 consecutive
  failures from 2026-08-16 through 2026-08-18 09:13Z, on the single condition F-6 names.
  The first green run in that window is the production proof recorded under F-6.
* **`Audit Rank-Form Curve Drift` is red because an approved pipeline change made the
  committed rank-form constants obsolete.** Bisected to `2449af9ac` (B2, #787 — "route the
  Hill master by the rank's coordinate pool"): holding the payload fixed, offense excess goes
  +7.0 → +44.8 and IDP +4.0 → +30.0. **This is a board-relation change that merged without
  being measured**, which is precisely what §25 board-diff control exists to catch — and the
  weekly cron caught it a week later rather than the merge catching it. Repairing the
  constants is an owner action under ADR-008; the process gap is this audit's to record.
* **`Retention health` reports `ok=7 stale=1`** — identity-resolution reports last written
  **2026-04-20 (119 days)**, and `/api/scaffold/identity` serves the newest file, so a halted
  collector presents a 119-day-old report as current. That is a live
  missing-is-never-zero surface and is carried as an open production condition.
