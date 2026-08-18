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

**CORRECTION 2026-08-18 — the third gate was closable, and this entry said it was not.**

This finding originally read: *"the scrape-promotion gate `server.py::_missing_expected_sites`
still watches `ktc`, because `ktcSfTep` never reaches `raw.sites` at all … `_reported_rows` could
not find it if `expectedSites` named it."* The first clause is true. **The conclusion was wrong**,
and it was wrong in the way an audit can least afford — it declared a repair impossible and
deferred it.

`_missing_expected_sites` reads `siteStats` as well as `sites` (`server.py:1179-1182`), and
`siteStats` carries `ktcSfTep` with a real count — **644** on the 2026-08-18 board. Measured
directly against the live payload, an `expectedSites.offense` of `["ktcSfTep"]` resolves with
`missing: []`. I had traced only the `sites` half and stopped.

Surfaced by an adversarial reviewer on the S-2 design panel, then re-measured here before being
accepted.

**So the anchor now names the board that votes.** `TOP_OFF_EXPECTED_SITE_KEYS` is `("ktcSfTep",)`.
Replayed over **all 176 committed export archives**, `["ktc"]` and `["ktcSfTep"]` block the
**identical 4** — the same set, not merely the same count — because both CSVs come from one KTC
API response and fail together. The anchors diverge only when the TE++ extraction breaks on its
own, which is exactly the failure the old anchor missed and this one now catches. Guarded as a
*property* (the anchor must name a registered voter) rather than as a literal string, and pinned
one-wide so S-1's anchor-detector-vs-population distinction cannot be undone here.

What genuinely remains for census **S-2** is narrower than this entry claimed: scraper-run names
still do not round-trip onto registry keys, `sites_meta` still never emits `ktcSfTep`, and a
run-level "complete" still does not decompose into which boards arrived.

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

**S-2's PROPOSED DESIGN IS REFUTED — do not implement it more carefully (2026-08-18).**
Two reviewers refuted it at high confidence; both halves were then re-verified directly at HEAD
rather than relayed, and both hold.

The proposal was to emit `playerCount: null` so that "reported zero" and "did not report" stop
reading the same.

1. `server.py` computes
   `site_count = len([s for s in result.get("sites", []) if s.get("playerCount", 0) > 0])`.
   A **present** key defeats `dict.get`'s default, so `None > 0` is evaluated and raises
   `TypeError` — confirmed by execution, not by reading.
2. That line sits above the promotion decision, inside a handler whose enclosing
   `except Exception as e:` calls `_mark_scrape_failure(e, elapsed)`. The change would therefore
   mark whole scrapes **FAILED** and break the two-hourly refresh.

**A correction to the refutation's own wording.** It has circulated as "`failedSources` is empty
in 176/176 inspected archives". Measured here across all 176 committed export archives: the key
is **absent from every one**, not present-and-empty. That is a stronger statement and a different
one — the field has never been populated, so a detector keyed on it would observe nothing. The
degradation historically capable of taking the board down was timeout-related, which the proposal
would not have observed either.

**Required posture.** The underlying defect above is real and stays OPEN. Any replacement must be
designed from actual failure data and adversarially tested before implementation. This entry is
the reason S-2 must not be read as an actionable ready fix; the finding survives, the design does
not.

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

### F-16 · No blocking gate bounds the production payload, and the one that looks like it measures something else · CONFIRMED · performance / test integrity · **OPEN**

Three separate defects, all verified:

**The two budgets that read the real board cannot block a merge.**
`tests/api/test_launch_readiness.py` carries the only assertions measured against a live
contract — `build_time < 5.0` (:458) and `test_gzipped_payload_under_2mb` (:460). Its module is
in `_LIVEDATA_MODULES` (`tests/conftest.py:135`), and that CI step is
`continue-on-error: true` (`pr-validation.yml:245`). The lane choice is defensible — a source
row-count dip is not a code defect — but its consequence for *performance* is that every
real-board performance assertion in the repo is advisory.

**And the 2 MB check measures a quantity production never sends.** It uses
`json.dumps(contract)` with **default separators**, `gzip.compress` at **default level 9**, on
the **full** contract. Production serializes compactly and serves `app` / `array` / `compact`,
never `full`. Measured at level 6 with compact separators on 1109 rows: full 1144.2 KB gz,
array 662.6, compact 764.6. The cap has ~44% headroom against a figure nobody receives — it
would not trip on F-13 even if it were blocking.

**`--strict` is documented and does not exist.** `frontend/scripts/check-bundle-sizes.mjs`
names it at :17 and :225 ("``--strict`` flag below would change this") and the file contains
**no `process.argv` at all**. Missing pages are therefore always a warning, so a page dropping
out of the build manifest passes silently — and this *is* the blocking budget (PR validation,
release-candidate, deploy, and `deploy/deploy.sh`).

**A correction to the lens that raised this.** It reported the `delta_bytes < 60_000`
assertion in `test_source_overrides.py` as "the only BLOCKING byte budget … while the live
delta is 74x the cap". The arithmetic is right and the framing is not: that is a fixture
regression guard, and the comment directly above it already records the real production
figures ("3.864 → 4.136 MB raw and **314.3 → 334.1 KB over the wire**"). The honest statement
is *no blocking gate bounds the production payload*, not that a cap was breached.

Not repaired here. `--strict` should be implemented or both mentions deleted — a documented
flag with no reader reads as coverage that exists. A real payload budget would have to measure
the served views with the server's own serialization, in the blocking lane, against a pinned
fixture (§3d forbids a live-board assertion there).

---

### F-17 · The critical-source gate cannot fire for DLF · CONFIRMED · source integrity · **OPEN (census S-2)**

`_CRITICAL_PRIMARY_SOURCES` (`data_contract.py:1024`) contains `"DLF"`. The name that would
reach it does not. `Dynasty Scraper.py` keeps three hand-written run-name registries and they
already disagree:

| | |
|---|---|
| `SITES` (:1493) | `"DLF": False` |
| `source_timeouts` (:3063) | `"DLF_LocalCSV"` |
| `source_enabled_map` (:3067) | `"DLF_LocalCSV": bool(SITES.get("DLF"))` |

`source_enabled_map` seeds `source_run_state` (:3107) → `sourceRunSummary`, so a DLF failure is
emitted as `DLF_LocalCSV`, and `"DLF_LocalCSV" in ("KTC","IDPTradeCalc","DLF","DynastyNerds")`
is `False`. Result: `partial_run_unknown:DLF_LocalCSV` — a **warning** — for one of four
sources the repo declares critical. Line :3067 is the tell: it reads `SITES.get("DLF")` and
registers the result under a different name.

**Latent, not active.** `SITES["DLF"] = False` today and DLF reaches the board via
`scripts/fetch_dlf.py`, which does not populate `sourceRunSummary`; the other three criticals
match exactly and the `startswith` clause covers IDPTC's sub-endpoints. It matters because
re-enabling DLF in `SITES` looks like a one-line change and would ship with its critical gate
disabled.

The repair belongs to the S-2 mapping owner. Adding `"DLF_LocalCSV"` to the tuple would be a
fourth hand-maintained list agreeing with the third — the defect, not the fix.

---

### F-18 · Seven freshness budgets measure vendor publication against a fetch-success signal · CONFIRMED · observability · **REPAIRED 2026-08-18**

The contract's `_SOURCE_MAX_AGE_HOURS` and the alert engine's `resolve_threshold` disagree on
**22 of 22** sources. Seven contract budgets are 168h or 720h and every justification in the
file cites the **vendor's publication cadence** — "refresh ~monthly, so allow a 30-day window"
(`yahooBoone`), "refreshes monthly as a new FP article" (`fantasyProsFitzmaurice`), "Substack
article updated periodically" (`idpShow`), and so on.

The signal is not publication. All seven have a `data/scrape_state/<key>_last_success` stamp —
which `_build_source_timestamps` prefers over CSV mtime, and which records **fetch success** by
construction — and all seven were **1.1–1.7 hours old** when measured. A 720h budget is ~400×
the observed fetch interval.

**The repository already decided this rule and applied it to two of nine.**
`data_contract.py:758-767`: *"mtime measures fetch success, not the vendors' editorial cadence
… (An earlier 720h/168h pair conflated this with how often the vendors PUBLISH — which mtime
cannot observe; Codex review on PR #532.)"* — applied to `fantasyNavigatorSf` / `pfkDynasty`
only. Repairing the rest is applying an existing owner decision, not inventing policy; census
**S-6** is untouched.

**Impact measured, and smaller than reported.** Rebuilding with all seven held to 6h — stricter
than the alert engine's 24h — moves **0 confidenceBucket and 0 confidenceLabel** across 1109
rows, because everything is currently fresh. This **corrects** the lens's claim that 705 rows
carry a freshness reason on that basis and that 230 of 232 HIGH rows would change.

It still matters: the exposure is F-6's failure mode with confidence blind to it. DraftSharks
went 12.6 days unfetched at full weight and its 6h budget would have degraded its rows; for
these seven a 12.6-day outage sits comfortably inside budget.

**REPAIRED.** The seven are now **24** — not a number of mine: it is what
`config/source_staleness.json` already gives them, and what `scheduled-refresh.yml`'s own
"Assert DLF freshness" step already enforces (`THRESHOLD_HOURS=24`, commented *"same threshold
the email alert engine uses"*). Deliberately **not** the 6h of the #532 correction: that
derivation was made for CI 2-hourly fetchers and three of these run production-side, so 24 is
the value two existing owners already state and needs no new derivation.

The four surviving prose justifications were corrected too — each described a publication
cadence the budget no longer encodes, and a stale explanation beside a repaired number is how
the next reader re-introduces the defect.

**The relation, not the number, is what is pinned.**
`tests/api/test_freshness_budget_not_laxer_than_alerts.py` asserts *contract budget ≤ alert
threshold* for every entry — the same relational shape `test_source_floor_invariant` uses for
scraper-floor ≥ contract-floor, so it invents nothing. The direction is the point: the contract
owner decides whether a row's evidence counts as current; the alert owner decides whether a
human is told. A source the alert engine calls stale while the board still counts its evidence
current is precisely F-6 with confidence blind to it. The allowlist starts **empty** and has
its own assertion, so adding an entry is a visible act rather than something a parametrised
skip hides.

One further guard reads `_build_source_timestamps` from the **AST** to confirm the
fetch-success stamp is still the preferred signal — because if that preference were ever
reversed, the publication-cadence reasoning would become defensible again and this invariant
would need revisiting rather than silently continuing to hold.

Board-inert, measured: the live contract still validates `ok=True`, `status=healthy`,
`sourceHealthErrors []`, and the confidence distribution is unchanged (medium 355 / none 260 /
high 258 / low 236). Mutation-proven — restoring any single 720h entry reddens its case by
name. Pinned by 23 assertions.

---

### F-19 · Four surfaces report process-load time as data age · CONFIRMED · observability · **REPAIRED 2026-08-18**

`latest_data_source["loadedAt"]` is stamped `_utc_now_iso()` when **this process** loads a
payload (`server.py:1511`). Three surfaces treat it as when the board was produced:

| surface | field |
|---|---|
| `/api/health` (:5109) | `data_age_hours`, `data_stale` — comment: *"flag stale if no refresh in SCRAPE_INTERVAL_HOURS * 3"* |
| `/api/metrics` (:5270) | `data_age_seconds` |
| `/api/status` (:4842) | `"last_data_refresh_at"` — a name that states the wrong fact outright |

"No refresh" is therefore measured as "no process restart". Measured against the real server:
a payload 12.74 h old — more than 2× the 6 h budget — returned `data_age_hours = 0.0`,
`data_stale = False`.

**The repo already knows.** `deploy/systemd/dynasty-healthcheck.sh:17-20`: *"a restart clears
the in-memory scrape error and reloads the disk cache with a fresh `loadedAt`, flipping health
green WITHOUT a successful scrape and concealing the ingestion fault."* The response was a
restart **policy** — degraded 503s are log-only — which protects the one path the watchdog
controls and leaves every other restart laundering a stale board. **A production deploy is one
of those**, and deploys happen several times a day.

The correct value exists and is unused: the payload carries `scrapeTimestamp`
(`2026-08-18T11:04:55.664246` on today's export) and the contract carries `generatedAt`.

**REPAIRED.** `latest_data_source` gains `producedAt`, set from the payload's own
`scrapeTimestamp` at both load sites, and `server.py::_board_age_hours()` becomes the one owner
of "how old is the board". All three age consumers route through it; `/api/status` reads
`producedAt` directly because it publishes a *timestamp*, not a duration, and gains
`last_payload_loaded_at` so the process fact keeps its own honest name rather than being
deleted. `None` means UNKNOWN and is never approximated from `loadedAt`.

**The trap that would have made this repair inert.** `scrapeTimestamp` is written with
`datetime.datetime.now()` and is therefore **naive**. Subtracting a naive datetime from a
tz-aware `now` raises `TypeError`, which every one of these call sites swallowed with
`except (ValueError, TypeError): pass` — so the obvious implementation returns `None`
everywhere and looks like it worked. The helper attaches UTC explicitly when `tzinfo is None`,
and records that this is an *assumption* about where the scraper runs.

Mutation-proven both ways: making the helper fall back to `loadedAt` reddens the
never-falls-back assertion; removing the UTC attach reddens three, including the naive-stamp
one written for exactly that purpose. Pinned by `tests/api/test_data_age_is_board_age.py` (10).

---

### F-20 · The ops alerter records "we decided to alert" as "an alert happened" · CONFIRMED · observability · **REPAIRED 2026-08-18**

`src/api/ops_alerts.py::check_and_alert` writes `state[a.category] = {"firedAt": now, …}` and
`_save_ops_state(...)` **before** delivery is attempted, then returns early when
`delivery is None or not to_email`. The 4-hour cooldown is already banked, so the next sweep
inside that window sees `firedAt`, `_should_fire` returns False, and the operator is never
told. The `except` branch reports `delivered: False` and does not roll the state back either,
so a mail-server blip burns the window too.

Worse than silence: `_detect_recovery` reads the same state, so once the condition clears the
operator receives `[RECOVERY] <category> resolved` — a resolution notice for an incident they
were never told about. Reproduced over three sweeps on a persistent kv: the only email
delivered was the recovery.

41 tests exercise the module and all pass. None runs it with `delivery=None`, an empty
`to_email`, or a delivery callable that raises — the three paths on which the cooldown is spent
without an email being sent.

**REPAIRED.** The sweep now records `attemptedAt` when it decides to alert and `deliveredAt`
only after an email actually goes out; `_should_fire` keys on `deliveredAt`. A category that
fired for the first time and was not delivered has its bookkeeping dropped, so the next sweep
is free to try again, while a category already carrying a delivered notice keeps its window.
Recovery is marked only on the delivered path, so a resolution notice can no longer be sent
for an incident nobody was told about. `deliveryConfigured` is published in the summary
because "nothing to send" and "could not send" must not read the same.

`_should_fire` still reads a legacy `firedAt` when `deliveredAt` is absent, so a state file
written by the previous implementation keeps suppressing what it already suppressed rather
than producing a burst on upgrade.

Mutation-proven: restoring the pre-delivery write reddens 6 of 8, including the
no-recovery-for-an-unreported-incident case. The pre-existing 41-assertion suite still passes.
Pinned by `tests/api/test_ops_alert_cooldown_needs_delivery.py` (8) — whose first test asserts
a *working* mailer still gets its cooldown, so the repair cannot degrade into a mail flood.

---

### F-21 · The external production check exempts the one status that means something is wrong · CONFIRMED · observability · **REPAIRED 2026-08-18**

`.github/workflows/health-check.yml`:

    :42   elif [[ "${HTTP_CODE}" == "503" ]]; then
    :44        echo "::warning title=Health Degraded::Service returned 503 (degraded)."
    :48   else echo "::error title=Health Check Failed::…" ; exit 1

`503` is exactly what `get_health` returns for stale data, a failed or stalled scrape, or
contract validation failure — and it is the **only** non-200 that does not fail the run. There
is no `if: failure()` handler in the workflow, so even the codes that do exit 1 open no issue.

Three further steps (:68, :116, :155) **skip** the coverage and backup assertions with a
warning whenever `/api/status` is unreachable — so "we could not check" reads identically to
"we checked and it is fine", precisely when it matters most.

Compounds F-19: the staleness signal usually cannot fire, and when it does, the watchdog does
not act on it. Twenty consecutive scheduled runs are green.

**REPAIRED.** `503` now fails — but as a *delay, not an exemption*: the step probes up to
`HEALTH_PROBES = 3` times, `HEALTH_PROBE_GAP_SEC = 30` apart, and fails only if every probe
reports degraded. The concern behind the original exemption (a momentary degrade should not
page anyone) is answered the way `deploy/systemd/dynasty-healthcheck.sh` already answers it
for liveness, rather than by permanently exempting the status. This workflow keeps no state
between its 6-hourly runs, so "consecutive" is measured within the run. Any other non-200
still fails immediately — re-probing an unreachable service tells us nothing new.

The three "Status Unreachable" branches now `::error` and exit non-zero instead of skipping
their assertion with a warning, and their message says the assertion did **not** run.

A rolling `production-health` tracking issue is opened or commented on failure, and closed on
a green run — both halves, because the repo already learned on `stale-sources` that an alert
which cannot clear stops being read.

**Expected consequence, stated plainly:** if production is genuinely degraded this check will
now go red. That is the intended outcome, and F-19 landed alongside it so the staleness input
it keys on is trustworthy.

Mutation-proven: restoring the warning-only 503 branch reddens two assertions; weakening the
handler's `if: failure()` reddens the reaches-a-human one. The guard reads workflow source
with comment lines stripped — this file's own comments quote the old
`::warning title=Health Degraded` line verbatim, so a raw-text match would have matched the
explanation as readily as a regression. Pinned by
`tests/deploy/test_health_check_does_not_exempt_degraded.py` (9).

---

### F-22 · `pickAnchors` reporting is inconsistent with the contract · CONFIRMED · reporting · **RECLASSIFIED P0 → P2 2026-08-18**

**Original framing, preserved:** the sweep recorded discarded `ktcSfTep` pick anchors as a
**live value defect** — i.e. a P0 canonical-value corruption incident.

**Refuted by measurement.** The canonical contract reads the CSV independently and obtains all
**36** vendor pick rows. There is therefore **no demonstrated canonical pick-value error**, and
the P0 framing overstated the finding.

**Correct classification: P2 reporting inconsistency.** Two surfaces describe the same anchors
differently; the served values are not implicated.

Recorded rather than deleted, per §0's rule that a refuted finding may still be real and that
audit conclusions are themselves auditable. Carried in the V1 contract as `V1-85`.

### F-23 · The E2E tracker identity is dead in both directions · CONFIRMED · CI / observability · **REPAIRED 2026-08-18**

Both tracker steps in `.github/workflows/e2e.yml` select
`select(.author.login=="github-actions")`. The Actions bot files issues under
**`github-actions[bot]`**, so the lookup matches nothing: every failing run takes the `create`
branch, and the close step — carrying the identical clause — can never drain the result.

| measurement | value |
|---|---|
| open issues titled "E2E safety net failing" | **15** |
| comments on #732 | **9** (the dedup demonstrably worked once) |
| comments on every tracker filed after #732 | **0** |
| 2026-08-18 scheduled run, with #881 open and identically titled | filed **#896** anyway |

The last row is the current selector tested in production under exactly the conditions it exists
for.

**The close direction is the worse one.** That step is what makes an open `e2e-failures` issue
mean "broken now" rather than "broke once, ever" — the distinction #588 was filed over. Dead, a
green run cannot clear the board, so the repository reads permanently red.

**The guard test was green throughout.** `tests/deploy/test_e2e_workflow_triggers.py` asserted
the losing spelling as a **literal string**, so it passed for the entire two weeks the mechanism
was dead. Same class as F-8 and as the contract gate that could not find its payload: a check
that cannot observe its subject reads exactly like a check that passed.

**Repair.** `gh` reports a bot's login differently depending on which API answers — GraphQL's
`Bot` type gives `github-actions`, REST gives `github-actions[bot]` — so pinning either spelling
is a bet. `sub("\\[bot\\]$"; "")` is correct under both. Verified against sample issue JSON
covering both bot spellings, a human author and a foreign bot: the normalised filter matches the
two bot rows and still excludes #753, the hand-filed defect the author clause exists for; the old
filter misses the real spelling entirely. Lookup failure is no longer swallowed — the alert step
`::error`s and files anyway, the close step `::error`s and exits 1, because a silent failure
there is a green run declining to clear a real alert.

Draining the accumulated duplicates is tracked separately.

### F-24 · A live, defaulted-ON feature flag is invisible to every operator surface · CONFIRMED · observability · **OPEN — repair BLOCKED on a measurement**

`RISKIT_FEATURE_LEDGER_RANK_CHANGE` is read directly at `src/api/data_contract.py:5545` via
`os.environ.get(..., "1")` — **default ON** — but is absent from `feature_flags._DEFAULTS`
(`src/api/feature_flags.py:55-297`).

Consequence: it does not appear in `snapshot()`, `effective_flags()` or `/api/status`, and
`tests/api/test_feature_flag_reachability.py` cannot see it. An operator reading the flag list
gets one that omits a live gate on the canonical board's `rankChange` derivation. The rollback
lever documented in CLAUDE.md is real; the inventory that would tell you it exists is not.

**The obvious repair was attempted and backed out, deliberately.** Registering it in
`_DEFAULTS` works mechanically — the registry derives exactly the env var already in use, so the
rollback lever is unchanged, and equivalence was proven across all six spellings the direct read
accepts (`0`/`false`/`off` disable; `1`/empty/garbage enable).

It is refused by `tests/api/test_feature_flags.py`, which requires every defaulted-ON flag to be
classified either `safe_on` (additive, inert, **cannot move a number**) or `value_moving_on`
(with a **MEASURED** blast radius). This flag is neither cheaply:

* it **mutates the contract** — ON stamps ledger-derived `rankChange`, OFF stamps `None` — so the
  `safe_on` standard `perfect_draft` meets ("writes no value, mutates no contract") does not hold;
* `value_moving_on` demands a measurement, and the guard's own comment forbids substituting an
  argument that the change is probably fine.

**The measurement is not obtainable from this environment, and faking it would be worse than
leaving the finding open.** It needs the temporal ledger and a built board: with no
`data/temporal_ledger.sqlite` present, BOTH branches stamp `None`, so a local on/off diff reports
"0 rows changed" — a vacuous figure that would read as evidence. `/api/data` requires
authentication, so the live board is equally out of reach here.

**To close F-24:** with the ledger present, measure ON vs OFF over a real board — how many rows'
`rankChange` becomes `None`, and the distribution of the non-null values — then register the flag
carrying that blast radius. Until then the direct read stays, and the reason it stays is recorded
both at the read site and in the `feature_flags` module docstring, so the gap is documented where
a reader of either file will meet it.

Carried as `V1-87`, status `BLOCKED`.

### F-25 · The nav offers a page whose every endpoint 503s · CONFIRMED · truthful degraded state · **OPEN**

`consensus_edge` defaults `False` (`src/api/feature_flags.py:296`) and gates every handler
(`src/consensus_edge/api.py:44`), while `/consensus-edge` is an **unconditional** nav entry
(`frontend/lib/nav-model.js:191`) with no client-side flag check. In the default configuration a
user can navigate to a page whose three endpoints all answer 503.

The hold itself is deliberate and documented (ADR-023 — its own ship gate said do not ship). The
defect is that the nav entry was not gated with it, so "deliberately held" and "broken" render
identically.

**Ownership: lane 6.** The feature stays post-V1; the nav gating is the V1-required part.

### F-26 · Flag documentation names an endpoint the flag does not gate · CONFIRMED · evidence integrity · **REPAIRED 2026-08-18**

`src/api/feature_flags.py` stated that `reception_scoring_fit` "reaches the OPT-IN
league-adjusted lens (`/api/gameplan`)". Measured: the gates at `src/api/gameplan.py:1157` and
`:1253` are called only from `get_league_adjusted_values` (`:1332-1333`), which backs
**`/api/valuation/league-adjusted`**. The flag is genuinely live; the endpoint named is not the
one it serves.

**Scoped down from the original sweep finding, on inspection.** That finding named *two* comment
sites, `reception_scoring_fit` and `idp_scoring_fit`. Only the first was wrong. The
`idp_scoring_fit` comment says the axis "reaches only `build_board_adjustments` — the OPT-IN
league-adjusted lens", which names the function rather than a route and is accurate. One site,
not two — recorded rather than left overstated, on the same principle as F-22.

Related, and separately recorded: `/api/gameplan` itself has **zero frontend consumers** — the
string appears once in the whole frontend, in a comment. That is the Scope Manifest's
`C2-GP-01` DISCONNECTED row, whose declared outcome is binary: reachable or retired.

Carried as `V1-88`.

### F-27 · `normalizationHealth` has been red in production since C1-U6, on a correct board · CONFIRMED · observability · **REPAIRED 2026-08-18**

Measured on the live board via `/api/status`, 2026-08-18:

```
pickNameMalformed: 18      playerNameDrift:    0
assetClassMismatch: 0      dupKeys:            0      healthy: false
```

All 18 samples are `2027 Round 1` … `2029 Round 6` — three future years by six
rounds, every one a **deliberate canonical row**. Nothing was wrong with the board.

**Mechanism: duplicate ownership.** `src/canonical/normalization_validator.py` carried its own
pick-name grammar — three regexes for the tier, slot and legacy shapes. `C1-ID-02` states pick
identity has exactly one owner and consumers must not parse it elsewhere. C1-U6 then added the
GENERIC grade, a rank-less row named `"2027 Round 1"`; the legacy pattern here reads
`"2026 1st Round"` — the same words in the opposite order — so it matched none of them.

**This is a FALSE RED**, and it is the same failure as a signal nobody reads: a health surface
that is permanently alarming trains its readers to stop looking (#588, F-3, from the other
direction). It also means the regression this check exists to catch would have arrived as no
visible change at all.

**Repair.** Canonical shapes now resolve through `picks.parse_board_pick_name`, which answers
slot, tier and generic together. The legacy display shape is retained locally and deliberately —
the owner does not MINT it, so delegating outright would newly flag any surviving legacy row.
Widening a health check is a repair; silently tightening one is a regression wearing a repair's
clothes. The module docstring was stale in the identical way and is corrected.

RED-first, and the arithmetic matches: replaying the retired grammar over the generic rows
rejects exactly **18**, the number production reports. Five tests pin it, including a structural
one that fails if the canonical grammar is ever restated locally again.

No value path touched — `is_valid_pick_name` is a reporting predicate.

### F-28 · F-19's UTC assumption is false in production, and `data_stale` can never fire · CONFIRMED · observability · **FIXED — awaiting production verification**

**Found by verifying the F-19 deploy against production rather than trusting the merge**, which is
the whole reason that step exists. `#909` deployed at 14:27 UTC on 2026-08-18. Measured minutes
later against `chaseupside.com`:

| field | value | |
|---|---|---|
| `data_runtime.last_payload_loaded_at` | `2026-08-18T14:27:50.636651+00:00` | tz-aware, and correct |
| `data_runtime.last_data_refresh_at` / `active_data_source.producedAt` | `2026-08-18T15:20:51.104768` | **naive, and 53 minutes in the FUTURE** |
| `/api/health.data_age_hours` | **-0.9** | |
| `/api/health.data_stale` | `false` | |

**A board cannot be produced after the process that loaded it.** The production box writes
`scrapeTimestamp` as naive **local** time, and `server.py::_board_age_hours` attaches **UTC**.

**The offset is exactly +2 hours (UTC+2 / CEST), measured against the payload's own scrape.**
The first reading above compared `producedAt` with `loadedAt` and inferred +1h — that was wrong,
because the payload loaded at 14:27:50Z had been produced by the *previous* scrape, so the
comparison mixed two different boards. The clean measurement came from the next completed scrape,
where `/api/status` carries both stamps for the SAME run:

```
last_scrape (tz-aware)  2026-08-18T14:31:58.928436+00:00
producedAt  (naive)     2026-08-18T16:31:45.336015
offset                  1:59:46  ->  UTC+2
```

The 14-second shortfall is the gap between stamping the payload and recording the run, so the
offset is two hours exactly. Note that `last_scrape` is already tz-aware UTC while
`scrapeTimestamp` is naive local — the correct reference is present in the same response.

F-19's own docstring names this precisely — *"Treating a naive stamp as UTC is an ASSUMPTION about
where the scraper runs; it is stated here rather than left implicit."* The assumption is stated,
and production says it is false. Stating an assumption is not the same as verifying it.

**Consequence — worse than the first assessment, and worth stating precisely.** The scrape
cadence is 2-hourly, so the TRUE board age ranges 0h..2h. Subtracting a 2-hour offset puts the
REPORTED age in **-2h..0h — never positive**. `data_stale` fires at
`age > SCRAPE_INTERVAL_HOURS * 3` (6h), so on this deployment it is **structurally unreachable**:
no amount of staleness can raise a non-positive number above six.

Observed twice within half an hour: `data_age_hours` = **-0.9**, then **-1.6**.

`/api/metrics` `data_age_seconds` carries the same error, and the ops alerter — the surface F-19
exists to feed — keys on this number. So the staleness detector F-19 repaired is, on the box it
actually runs on, incapable of alarming.

**Is it still an improvement on what it replaced?** Only in a narrow sense, and the honest answer
is less comfortable than the first draft of this entry. The retired measure was *process* age,
which returned `0.0` for a 12.74-hour-old payload — wrong, unbounded, and also unable to alarm.
The new measure is wrong by a constant and *also* unable to alarm. The repair moved the defect
from "measures the wrong quantity" to "measures the right quantity in the wrong timezone"; it did
not restore the alarm. That is a smaller win than F-19's merge claimed, and it is recorded here
rather than left implied.

**Deliberately NOT hot-patched onto the in-flight PR.** The obvious guard — refuse to publish a
negative age — would now turn EVERY reading into UNKNOWN on this deployment, not half of them, so
it is not a stopgap: it would replace a silent failure with a loud one, which is better, but it
needs the alerter's `None` handling checked first. The correct repair is at the source:
make `scrapeTimestamp` unambiguous (tz-aware UTC in `Dynasty Scraper.py`), which touches every
consumer of that field including the temporal ledger and the freshness map, plus a guard that a
board produced in the future is reported UNKNOWN rather than as a number. That is its own unit
with its own verification, not a rushed addition to an observability PR already in CI.

Owner: lane 5. Carried in the V1 contract as `V1-128`.

**THE REPAIR (2026-08-18, this session).** Confirmed once more against production immediately
before fixing, so the fix is measured against a live reading rather than a recalled one:

```
2026-08-18T18:35:32Z   /api/health.data_age_hours   -1.0
                       /api/health.data_stale       false
                       /api/status.last_scrape      2026-08-18T17:36:12.758337+00:00
```

A board produced 59 minutes earlier, reported as an hour in the future. Same +2h.

Four changes, and the first two are load-bearing **together** — either alone is worse than
neither:

1. **`Dynasty Scraper.py`** stamps `scrapeTimestamp` with
   `datetime.datetime.now(datetime.timezone.utc)`. This retires the assumption at its source
   rather than restating it correctly in three files, and puts the field on the same footing as
   the contract's `generatedAt`, which has always been `utc_now_iso()`.
2. **`server.py::_board_age_hours`** refuses a board produced in the future — UNKNOWN, never a
   number. Alone this would turn *every* production reading into UNKNOWN, which is why it lands
   with (1). `ops_alerts._check_data_freshness` already returns no alert on `None`, verified
   before writing the guard, so UNKNOWN degrades quietly rather than inventing an alarm.
   Tolerance is `5 minutes`, bounded from both sides rather than picked: larger than real
   NTP skew between two synced hosts (seconds), smaller than the smallest timezone quantum in
   use anywhere (15 minutes — UTC+05:45, UTC+12:45), because swallowing a genuine timezone
   misreading is the one thing the guard must not do.
3. **`src/history/record.py`** — the naive branch survives for legacy payloads and now says so.
   Live rows stamp `observed_at_zone: "utc"` on the producer's own statement instead of on an
   assumption about the host.
4. **`src/history/asof.py::_instant_at_or_before`** — same correction to the comparison rule.
   Naive stamps are still read as UTC, deliberately: refusing them would make the entire
   pre-F-28 ledger unreadable to as-of queries. The zone column records which rows are affected.

**The ledger's existing live-origin rows are NOT rewritten.** They are two hours ahead of the
instant they claim, `src/history` is append-only by design, and corrections are explicit
correction rows. Rewriting history to fix history is a destructive migration needing owner
judgment, so it is recorded here as a known-skewed population rather than performed. No
user-facing wrong answer has been demonstrated from it (`value_as_of` has no route).

Pinned by `tests/api/test_data_age_is_board_age.py`: the measured production state as an
assertion, a two-hour future board, the clock-skew tolerance in both directions, and a
source-text guard on the producer — because the guard without the source fix trades a wrong
number for a permanently missing one, and nothing else would catch that.

**Still owed:** production verification after deploy — `data_age_hours` positive and tracking the
2-hourly cadence (0h..2h), `data_stale` reachable in principle, and `/api/status.last_data_refresh_at`
agreeing with `last_scrape` rather than leading it by two hours.

**A correction to this session's own verification attempt.** F-10's production check was first
pointed at `source_health.anchor_row_counts`, which still reads `ktc` after a completed scrape on
the new code. That is **not** evidence against F-10: `server.py` documents `anchor_row_counts` as
the scraper's own anchor counts and states explicitly *"NOT `coverageAudit.expectedSites`: that
block is an anchor-loss detector... Different question, different owner."* `TOP_OFF_EXPECTED_SITE_KEYS`
feeds `expectedSites`, which `/api/status` does not expose at all. F-10 therefore remains
**unverified in production** — it needs the contract payload or an export archive, not this
endpoint — and the watcher aimed at the wrong field was stopped rather than left to report a
false negative.

### F-29 · The E2E failure set has grown from 1 to 4, and one of the three is unexplained · CONFIRMED · CI · **OPEN**

Measured on run `32148846855` (PR #910, head `f8a2402`, a tree containing `#909`):

```
4 failed
  [desktop-1366] journey-settings-overrides.spec.js:45 › toggling a source fires the overrides request
  [desktop-1366] journey-tools-health.spec.js:31      › /tools/source-health lists real scraper sources
  [desktop-1366] public-league.spec.js:533            › teamAssignment returns 12 manager slots (Phase A)
  [mobile-chromium] public-league.spec.js:533         › teamAssignment returns 12 manager slots (Phase A)
1 flaky
  [mobile-chromium] public-league.spec.js:193         › deep links via ?tab= land on the right tab
149 passed, 52 skipped (8.5m)
```

The audit's own earlier CI re-measurement recorded **1 failed + 1 flaky**. Three of these are
therefore new *to this register*, and each is accounted for differently:

* **`journey-settings-overrides`** — this is `F-3a`, already recorded and diagnosed (the backend
  answered 200 four of four times; the spec fails downstream of the serving path).
* **`public-league:533` (both projects)** — **not a regression.** `git log` puts this spec's
  introduction at `f9b9f29`, *Audit batch G* (#891), on 2026-08-17. It asserts
  `assignments.length >= 8` and a non-empty `nflTeams` per manager, which is precisely the defect
  open as **#815** ("teamAssignment serves a degraded snapshot as zero assignments, HTTP 200").
  It is a regression test written for a defect that has not been fixed yet — a deliberate red,
  and it will stay red until `V1-94` lands. Counting it as new breakage would be wrong.
* **`journey-tools-health:31`** — **UNEXPLAINED, and it is the one to chase.** The spec reads
  `status.source_health.source_runtime.enabled_sources` and renders `/tools/source-health`.
  `#909` did not touch that field, but it did touch `server.py`, which is where `/api/status` is
  built — so a relationship cannot be ruled out from the file list alone, and it is not being
  ruled out here on the strength of an argument.
* **The flaky one is explained by the harness's own banner**: React 19.2 stages a Suspense
  boundary in `<div hidden id="S:n">` and reveals it a frame later, so a full copy legitimately
  exists for a window. The banner is explicit that this is React's behaviour, not a product
  defect, and that `.first()` must NOT be used to silence it because two specs are the repo's only
  detectors for a PERMANENT duplicate (#709's `dynamic()` bug).

**Not attributed to `#909` without evidence.** The correct next step is to run
`journey-tools-health` against `main` immediately before and after `82b25bd`, which needs a booted
stack. Recorded as an open question with the measurement that raised it rather than as a verdict.

Owner: lane 5.

---

**ANSWERED (2026-08-18, same day). Not a `#909` regression, and the diagnosis did not need a
booted stack after all.**

The cheaper measurement was the workflow's own history. `E2E Safety Net` on `main`:

```
2026-08-18T07:08Z  schedule  failure  cc9e1630   <- BEFORE #909 merged (14:27Z)
2026-08-17T07:26Z  schedule  failure  b1c6a42a
2026-08-16T07:03Z  schedule  failure  45b7142e
…  13 consecutive scheduled runs, every night back to 2026-08-05, all failure
```

The suite has been red on `main` for two weeks. A failure occurring at 07:08 on the day `#909`
merged at 14:27, and every night for the thirteen nights before it, is not caused by `#909`. The
planned before/after bisect would have measured a difference that the run history says does not
exist.

**`journey-tools-health:31` is a STALE SPEC, not a product defect — and it was failing the repair
of an earlier finding.** The current failure is exact:

```
Error: expanding the strip should reveal 2 per-source rows
Expected: 2      <- status.source_health.source_runtime.enabled_sources.length
Received: 21     <- .source-health-name rows the page rendered
```

The spec carried a note asserting that `source_runtime.enabled_sources` is "what the strip renders
from". **Audit F-7 made that false.** `SourceHealthStrip` now renders
`source_health.registered_sources`, with an in-code comment giving the reason: `enabled_sources`
carries the scraper's own run names for the two ANCHOR markets only, so a page whose subtitle
promises "every ranking source in the pipeline" was rendering 2 rows out of 21 and looking their
counts up under keys that did not match.

Confirmed against production the same day — the two numbers are both real and both correct for
their own question:

| field | value |
|---|---|
| `source_runtime.enabled_sources` | `["IDPTradeCalc", "KTC"]` — the browser-scraped anchor markets |
| `source_runtime.complete_sources` | the same two, `overall_status: complete`, 121.97 s |
| `registered_sources` | all 21 |
| `sources_with_data` | **21** |
| `missing_sources` / `source_failures` / `partial_run` | `[]` / `[]` / `false` |

So the page showing 21 is correct and the spec expecting 2 is the pre-F-7 expectation. This is the
**same failure class as F-23**: a guard pinned to a fact it never re-verified, which then reported
the fix as the fault.

**Repaired — by LANE 6, in `#912`, not by this lane.** Both lanes reached the same diagnosis
independently and edited the same file. Integration takes lane 6's version and **withdraws this
lane's**, for a reason stronger than "the frontend surface is theirs":

*This lane's version was defective, and lane 6's is not.* The withdrawn version derived the
expectation from `registered_sources` alone, on the principle that a test recomputing what the
component computes cannot catch the component computing the wrong thing. The principle stands;
the implementation did not honour it. With an empty registry but a live runtime list — the exact
case its own comment described — it skipped the zero-state branch and then asserted **0** rendered
rows against a page that legitimately renders the runtime fallback. Lane 6 mirrors the
component's ladder (`registered.length ? registered : runtimeEnabled`) and is correct there.

Recorded rather than quietly dropped, because "whoever wrote it first wins" is precisely the
failure mode this lane exists to police, and the deciding fact must be the code, not the order of
arrival.

What this lane contributes instead is the half lane 6 does not have: the **`#909` attribution is
refuted** by the run history above, and the two `/api/status` numbers are **measured on live
production** rather than reasoned about.

**Still open, and separated rather than folded in:** `journey-settings-overrides:45`. Its retry
carries a different and more interesting diagnostic than the first failure —

```
[board diagnostic] /api/data?view=app: 200, playerCount=988, playersArray=0,
legacyPlayers=988, rankStamps=740  => the payload looks serveable, so the board had data
and still did not render it. That points at the client, not the contract.
```

— which is `F-3a`'s territory, not this one's. It keeps `F-29` from closing, and it is the next
E2E question.

Status: `journey-tools-health` half **FIXED**; `#909` attribution **REFUTED**; `F-3a` half remains
open.

### F-30 · A truncated pick market exposes a real derivation gap — and my first fix was wrong · CONFIRMED · data integrity · **OPEN (assigned)**

**Symptom.** `idpTradeCalc` dropped from 84 pick anchors to 16 (round 1 only, every year) between
two scrapes of 2026-08-18. 20 census errors followed —
`pick_completeness_census:2029 Round 2..6:missing_or_unpriced` — reddening every open PR.

**And it was worse than "every open PR": it SKIPPED A PRODUCTION DEPLOY.** Found while looking
for the deployed SHA for an unrelated checklist, which is its own small lesson about what routine
verification turns up. `Deploy Production` run `32164548748` (`main`, `f9444f7b`, 17:14:24Z)
failed its `Validate Build Inputs` job at **`Run unit tests (hard gate — pure logic)`** —

```
1 failed, 298 passed, 25 skipped, 8197 deselected …
  Picks missing a finite canonical value:
  ['2029 Early 2nd', '2029 Early 3rd', '2029 Early 4th', '2029 Early 5th', '2029 Early 6th',
   '2029 Late 2nd',  '2029 Late 3rd',  '2029 Late 4th',  '2029 Late 5th',  '2029 Late 6th', …]
```

— and the `Deploy To Production` job was consequently **skipped**. Note the ordering: the failure
came from the *unit-test* gate, so the FULL contract lane never even ran (`skipped`). Production
therefore stayed on `8ec1978e` (15:11:36Z, the last successful deploy) while `main` moved on.

Two things this makes concrete. First, the owner's instruction to fix this before anything else
("it blocks everything") was not an overstatement — a vendor truncating one feed halted the
release path. Second, it is a live instance of the case `docs/ops/STABILIZATION_2026-08-16.md`
§3d already legislates: a hard-gate test asserting an absolute property **over the live board**
turns an upstream availability event into a red build. The lasting repair is the derivation fix
below, which makes the property true again from the evidence that did arrive.

**My first diagnosis was that the census was in the wrong lane, and it was wrong.** I moved
`…:missing_or_unpriced` to source-health on the theory that a vendor truncation causes it. CI then
failed on an existing, explicitly parametrized test —
`tests/api/test_contract_health_lanes.py::TestTheTaxonomyItself::test_statements_about_our_code_are_structural[pick_completeness_census:2029 Round 5:missing_or_unpriced]`
— which had already decided this string is a statement about OUR code. I overrode a recorded
decision without reading it first. **Reverted**, and the taxonomy is right.

**The real defect, measured on the live board.** `ktc` publishes rounds 1-4 for 2026/2027/2028
throughout; only `idpTradeCalc` truncated. The 2029 rows that price are exactly the rounds
`idpTradeCalc` still covers:

| row | backing sources | value |
|---|---|---|
| `2028 Early 2nd` (template) | idpTradeCalc, ktc, ktcSfTep | 3176 |
| `2029 Early 1st` (derived) | idpTradeCalc, ktc | 4497 |
| **`2029 Early 2nd`** (derived) | **ktc only** | **None** |

`2029 Early 2nd` carries COMPLETE provenance — `derived_year_step`, `basis: 2028 Early 2nd`,
`factor: 0.8532`, `family: measured_vendor_year_step_v1` — against a basis row priced at 3176, and
still resolves to `None`. The clone LOST `idpTradeCalc` and `ktcSfTep` relative to its own
template, fell to a single source, and the single-source gate nulled it.

So a row can assert "I was derived from that basis by that factor" while carrying no value. The
provenance and the valuation disagree, which is worse than either failing alone: the census
correctly reports `missing_or_unpriced`, but `pickValueProvenance` reads as a successful
derivation, so the row looks explained.

**Why it is structural, not vendor availability.** `ktc` alone carries every (tier, round) cell
needed for 2029 R2-R4, and `derivedRoundModel` derives R5-R6 from R4. The inputs were present; the
derivation did not use them. That is our code, exactly as the taxonomy test asserts.

**Ownership: this is C1-U6 pick valuation, NOT integration.** Recorded and assigned rather than
repaired from lane 5 — the fix is in `_inject_far_future_pick_sources`'s per-source combination
rule (why a clone drops sources its template had) and its interaction with the single-source gate,
which is pick-valuation methodology.

**What lane 5 did land:** the three hard-gate tests that build from `exports/latest` now skip on a
per-source anchor-coverage premise. That stands independently of the lane question — a hard-gate
test may not assert over the live board at all (`STABILIZATION_2026-08-16` §3d). The guard was
verified to keep its teeth rather than assumed: replayed against the healthy 15:09 board the class
runs 16 tests with 0 failures and 1 pre-existing skip; against the truncated board it skips 11.

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


### F-31 · C2-U1's "unpriced" third state is unreachable on the live snapshot path · CONFIRMED · false green · **OPEN (assigned: lane 1)**

**Found by reviewing `#914`, and disclosed BY `#914` rather than caught in spite of it.** Lane 1's
own docstring for the new canonical `roster_player_from_row` adapter says it, and the claim was
verified against the tree rather than taken on trust.

C2-U1 made `RosterPlayer.ros_value` a `float | None` on a deliberate distinction: `0.0` is a real
objective (assignable, contributes nothing) and `None` is UNKNOWN (not assignable, reported in
`unpriced_ids`, its slot reported unfilled). That third state is the point of the type — the
retired `float(player.ros_value or 0.0)` scored both identically while reporting slots as filled
by players nobody can price.

**The only live producer of the adapter's input destroys that state before the adapter sees it.**
`src/ros/team_strength.py:123` drops any row whose `rosValue` is `<= 0` before writing the
snapshot the roster adapters read, and line 165 carries its own `float(agg.get("rosValue") or 0.0)`.
So on the production path `LineupAssignment.unpriced_ids` is **empty by construction**, however
correct the canonical owner is.

This is the false-green test applied to a repair rather than to a feature. The implementation is
truthful; its live input is not, so the honest-missing state that C2-U1 exists to preserve never
reaches it. Nothing is *wrong* on the board today — an unpriced player is excluded rather than
mis-scored — but the guarantee C2-U1 is credited with is not in force where it matters, and
`V1-27`'s production evidence should not be read as covering it.

**Not fixed here, deliberately.** The repair is upstream in `ros/team_strength.py`, which is lane
1's surface, and it is a behaviour change to the snapshot every roster consumer reads — it needs
its own measured blast radius, not a drive-by edit from the integration lane. `#914` is not
blocked on it: the adapter consolidation is a strict improvement and the disclosure is what makes
this finding possible.

Owner: lane 1. Related: `V1-27` (C2-U1), `#914`.

### F-32 · The mobile view rendered different numbers than desktop, and was the larger payload · CONFIRMED · false green · **FOUND AND FIXED BY LANE 6 (#912)**

Recorded here because it is a **canonical-value integrity** finding, not merely a frontend one, and
because the V1 row for mobile/desktop parity should point at it. The work and the credit are lane
6's; this register entry is the integration lane confirming and filing it.

`/api/data?view=compact` exists to send a phone FEWER BYTES. It may not send a phone a
**different board**. It did both wrongly:

* **It was lossy in a way that changed rendered numbers.** `_materializePlayerArrayRow` reads
  **14 of the 17** fields `compact_view` pruned, so the compact board rendered differently from
  the array board for the same player on the same day — `anomalyFlags` (so /edge's "Flagged" tile
  read **0**), `confidenceLabel` (a different confidence string), the `anchorValue` /
  `subgroupBlendValue` / `subgroupDelta` / `alphaShrinkage` chain (so PlayerPopup's value
  derivation collapsed), and — worst — **`blendedSourceRank`, which is a SORT KEY**, so the
  Consensus sort collapsed on mobile.
* **It was BIGGER than the view it was meant to beat.** Measured on the 1,109-row contract at
  gzip 6: full 13.09 MB / 1,092.8 KB gz, array 7.25 MB / 631.8 KB gz, compact 8.28 MB /
  735.0 KB gz — **+16.3% against `array`**. Compact still carried the legacy `players` dict,
  which `buildRows` never reads when `playersArray` is present; `?view=array` had already dropped
  it and compact had not.

This is the false-green test failing on a *delivery* surface rather than an engine: the intended
production consumer was reading the canonical implementation, but through a view that silently
removed the inputs it materializes from. It sits directly against the invariant CLAUDE.md states
as **one canonical value per player per session** — two devices, one player, one day, two
answers — and it reached users, unlike the two W29 violations that motivated that wording.

**Why nothing caught it:** there was no test relating the view to its consumer. A shape test that
pins "compact prunes these fields" passes forever while the consumer quietly starts reading one of
them. #912's structural fix is the right one — `test_compact_view_consumer_parity.py` plus
`tests/e2e/specs/api-view-parity.spec.js` make the *relationship* the assertion rather than the
field list.

Owner: lane 6, fixed in `#912`. Related: `V1` mobile/desktop parity; the "no second canonical
board" family (`F-VAL-02`, W29-F001/F002), which this joins as the first member measured on a
user-facing delivery path.


### F-33 · The external crowd-FAAB pool admitted evidence it cannot compare · CONFIRMED · data integrity · **FOUND AND FIXED BY LANE 4 (#911)**

Filed by the integration lane so `V1-129` has a register entry to point at. The work and the
credit are lane 4's.

The crowd waiver feed reaches `faab_engine.rival_bid_cdf` through
`data/faab/crowd_history_<leagueKey>.json` → `crowd_bid_index`, and is blended into the modelled
rival share at **weight 0.6**. What that pool admits therefore moves **real recommended bids** —
this is not an observability field.

It admitted three kinds of evidence it had no standing to use: leagues whose format is not
comparable to the target league, a ledger that had not been refreshed inside its budget, and
**positions the retained population cannot price at all** (measured: no external league in the
feed starts an individual defender, so an IDP recommendation would have been answered from a
population that never prices one). `#911` refuses each, and reports the refusal rather than
silently narrowing.

Two things worth keeping visible because they are easy to lose:

* **Own-league history was already correct and is untouched.** `fetch_bid_history` normalises to
  percent-of-original-budget across the $1,000 / $200 / $100 eras, keeps `$0` bids, and refuses a
  season with no usable `waiver_budget` rather than fabricating `$100`. The defect was in the
  *external* lane only, and saying so stops a future reader "fixing" the half that works.
* **A snapshot proves when it was taken, not that it is still true** — the staleness refusal is
  the same posture as the scoring-fingerprint evidence states, not a new rule.

This is the CLAUDE.md signal-independence discipline applied to admission rather than to counting:
evidence that cannot be compared to the question is not weak evidence, it is *not evidence*, and
weighting it at 0.6 was the defect.

Owner: lane 4, fixed in `#911`. Related: `V1-129`, `V1-55`.


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
