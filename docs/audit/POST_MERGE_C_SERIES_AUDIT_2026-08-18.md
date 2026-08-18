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

## 1. Open findings — not repaired

### F-1 · 2029 pick tier ordering is inverted on the live board · CONFIRMED · data integrity

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

**Why not repaired here.** Choosing how to restore monotonicity (clamp the crossing cell?
isotonic-regress the ratio surface? shrink toward `stepByRound`?) is a calibration methodology
change, which the freeze names as not permitted. An ERROR-level census check would turn the
board red and block deploy; a warning-only one changes no value but still lands a new gate
under a freeze. Both were considered and declined.

**Recommendation.** First authorized unit after the audit: constrain the derived-year surface
to preserve tier and round ordering, declare the constraint as part of the `PRIOR` family, and
measure its effect on all 18 cells before and after.

### F-2 · `/api/data` serves the raw snapshot, HTTP 200, until the first scrape succeeds · CONFIRMED · serving path

Booted `server:app` with the browser deliberately unavailable — the E2E config's own posture —
so the startup scrape fails:

```
[Scrape] scrape_failed — BrowserType.launch: Executable doesn't exist ...
GET /api/data?view=app  ->  200
playersArray=0   legacyPlayers=1109   stamped=0   meta.contractVersion=None
```

Polled for 100 s after the failure: unchanged. The same on-disk export builds a **complete
1,109-row stamped contract in 1.36 s** in-process. The data is present and buildable; it is
simply never built.

**Mechanism.** At startup `latest_data = load_from_disk()` then `_prime_latest_payload(...)`,
which primes the raw payload's bytes/gzip/etag. `latest_contract_data` is assigned in exactly
one place — inside the scrape path — so it stays `None`. `get_data`'s `if latest_contract_data:`
is False and the handler falls through to serving the primed **raw** bytes with 200. The
`503 {"error": "No data available yet"}` at the end fires only when there is no data at all.

The startup log prints **"Dashboard ready with cached data"** and the comment above the load
says it exists "so the dashboard is usable right away". Neither is true since the `buildRows`
fail-fast landed: with zero rank stamps the materializer returns `[]` **by design** and the page
renders "No player data available" — while the API reports 200 OK.

**Why it matters.**

* It is a **hidden fallback** — the shape `docs/C_SERIES_EXECUTION_MAP.md` §0.3 rule 3 forbids.
  The response is not a contract and nothing in it says so.
* Every process restart is exposed until the next scrape succeeds. Deploys restart the service.
* The deploy's own smoke test cannot catch it: it asserts `/api/data` returns **401**
  anonymously, which it does.
* It is the deterministic cause of two E2E failures measured here.

**Correction to a prior diagnosis.** Open PR #762 attributes this class to "the Next bridge
serves an unstamped snapshot as the contract". Measured against the backend directly, with no
Next in the path: **the backend serves it.** The bridge may also; it is not the origin.

**Why not repaired here.** It changes what a live production process serves in its first
minutes. Recommended, with owner approval: build the contract from the disk-loaded payload at
startup so a failed scrape degrades to a **stale contract** rather than to a non-contract, and
return the existing 503 when a contract genuinely cannot be built.

### F-3 · The E2E regression suite has been red on `main` for seven consecutive days · CONFIRMED · process

The `e2e.yml` workflow's scheduled run on `main` has concluded `failure` on **2026-08-11, -12,
-13, -14, -15, -16 and -17**, and on the open dependabot PR. Its last success was 2026-08-10, on
`claude/bridge-timeout-root-cause` — the branch of PR #762, still open, which diagnosed F-2's
class.

The repository's end-to-end regression signal has therefore been unread for a week. Local run
during this audit: **148 passed, 5 failed** — one flake (Streaks; passed on re-run), two
deterministic from F-2, two repaired by batch G.

**Recommendation.** Either land F-2's repair (which is most of the red) or make the suite's
verdict something a person is required to look at. A signal nobody reads is not a signal.

### F-4 · Production proof outstanding for five units · BLOCKED-EXTERNAL

`C0-R`, `C1-U5`, `C1-U8`, `C1-U9` and `C2-U1` are all `CLOSED-PENDING-PROD`. Their code is in
production (deployed `5a5f1507f`), but **not one of the five named checklists has been
executed**. Each requires an authenticated production session. Recorded honestly in
`docs/EXECUTION_PLAN.md` §0.3 as `IN PRODUCTION, CHECKLIST UNEXECUTED` — the deploy landing is
the precondition, not the proof.

Also outstanding on production, because it cannot be measured here:

* the `canonical_board` lane of the temporal ledger (an archive-only backfill populates
  `scraper_blend` and `source_value`; the canonical lane comes from live recording);
* `rankChange`, which is correctly `null` on all 1,109 rows offline for want of a ledger
  comparator.

### F-5 · `value_as_of` raises a raw `strptime` error on an ISO datetime string · CONFIRMED · minor

Its signature accepts `str`, but an ISO-8601 *datetime* string produces
`ValueError: unconverted data remains: T23:00:00` from `strptime` rather than being parsed or
refused with the module's own `ObservationError`. Cosmetic — `value_known_before` is the
instant API, and it refuses a naive datetime correctly and clearly.

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

## 5. Still to run

Phase 3 (performance budgets, accessibility, the remainder of observability), Phase 4 (the
independent adversarial pass over all 20 lenses), and Phase 5 (production proof against the
deployed SHA, the §22 board diff, and the full regression sweep) have not been completed. The
verdict is withheld until they have.
