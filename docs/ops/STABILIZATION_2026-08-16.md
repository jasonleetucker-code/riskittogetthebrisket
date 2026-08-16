# Stabilization pass — 2026-08-16

**Status:** DELIVERED · owner-authorized as a bounded repair pass, not a feature unit
**Scope:** repository / CI / source-health / release-discipline / bookkeeping repair, plus
disposition of the eleven C1-U6 follow-ups
**Not in scope:** C1-U5, C1-U7, C1-U8, C1-U9, C1B, C2+, trade methodology, projections, UI

This is the design record for the pass that returns `main` to a trustworthy baseline and
lets C1-U6 close. It is an operations record, not a planning record: it authorizes nothing.

---

## 1. The incident, stated correctly

| time (UTC) | event |
|---|---|
| 18:20:37 | PR Validation run **31964305868** starts on `6d7b9dd47` |
| ~18:35 | that run concludes **SUCCESS** |
| 18:53:28 | PR Validation run **31965928453** starts on `edc25300d` (the final head) |
| **19:08:58** | run **31965928453** concludes **SUCCESS** — status `completed`, conclusion `success` |
| 19:10:04 | an automated data refresh pushes `801bf940d` to `main` |
| **19:10:41** | the owner merges PR #871 → GitHub creates `ce8a8341a` = merge(`801bf940d`, `edc25300d`) |
| 19:12:21 | Deploy Production run **31966802715** starts on `ce8a8341a` |
| 19:13:44 | its `Run unit tests (hard gate — pure logic)` step **fails** |
| 19:14:20 | `Deploy To Production` **skipped** — nothing shipped |

**Correction of the record.** Earlier documents (PR #872's body, `docs/EXECUTION_PLAN.md`,
`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §13) stated that run 31965928453 was
*cancelled by the merge and never concluded*, and that the merged tree was therefore
verified directly "instead". **That is false.** GitHub records the run as `status:
completed`, `conclusion: success`, `updated_at: 2026-08-16T19:08:58Z` — one minute and
forty-three seconds *before* the merge. The exact final head was validated. Every
occurrence has been corrected; the direct post-merge verification remains valuable
evidence and is retained, but it was an addition, not a substitute.

**What actually failed** was the POST-MERGE tree `ce8a8341a`, whose *other* parent brought
in a newer scrape in which KTC had timed out. The failure was not introduced by C1-U6: an
A/B on the identical payload reproduced the same contract-health status and the same
13-named / 29-with-subtests failure set on the pre-C1-U6 parent `801bf940d`, with zero
failures unique to C1-U6.

---

## 2. KTC — diagnosed, not guessed

`sourceRunSummary.sources.KTC.durationSec` across the last 40 archived bundles:

* 39 runs: **18.49 s – 19.19 s** (state `complete`, 4 values, every run)
* the 19:09:04 run: **300.09 s**, state `timeout`, 0 values

A 16× deviation from a two-day-stable baseline, once. **Not a repository defect** — no
scraper change is warranted, and none was made.

The freshness layer behaved correctly throughout and was NOT touched:
`data/scrape_state/ktc_last_success` still reads the 17:03:43 success, so the timeout did
not present as a fresh run. `exports/latest/manifest.json` separately records
`siteRawFresh: [idpTradeCalc.csv]` and `siteRawPreserved: [ktc.csv, ktcSfTep.csv]` — the
last-known-good CSVs are labelled as preserved, not as fresh. No stale value was promoted,
no replacement data was fabricated, and no health signal was deleted.

### IDPTC staleness (follow-up 7) — measured

Fetch freshness and CONTENT freshness are different claims, and only the first was
measured anywhere. Over all 165 tracked archives:

| source | whole-board content changes | pick rows last changed |
|---|---|---|
| `ktcSfTep` | 164 of 165 | 2026-08-16 17:03 |
| `idpTradeCalc` | **6** of 165 | **2026-07-14 23:36** (32 days) |

`idpTradeCalc` fetches fresh every two hours and is one of only **two** families that price
picks at all. `config/source_staleness.json` already named this gap in its own comment
("CSV mtime tracks 'fetch succeeded' rather than 'vendor published new content'"); nothing
measured it. `scripts/check_source_health.py` now does, whole-board and pick-rows
separately, read-only over the tracked archive. Reported, not acted on: no methodology
changed, and a frozen vendor board is the vendor's business — being unable to SEE it was
ours.

---

## 3. The CI architecture defect, and the repair

### 3a. What was actually wrong

Two failures that had been concealing each other:

1. **A deterministic test consumed live source health.**
   `tests/api/test_canonical_value_scale_contract.py` asserted
   `validate_api_data_contract(contract)["ok"] is True` as a *precondition* before
   injecting an out-of-scale value. `ok` covers the whole report, including external
   source health, so `partial_run_critical:KTC` failed it. Because the hard gate runs
   `pytest -x`, one provider timeout turned every open PR red and skipped the deploy.

2. **The gate that was supposed to catch source degradation had never run.**
   `scripts/validate_api_contract.py` searched for its payload in `repo/data` and the repo
   root. Both are gitignored for that artifact; the only tracked payload is
   `exports/latest/dynasty_data_*.json`. Every CI invocation since the step was written
   printed "No sample data; skipping". **A gate that cannot find its input reads exactly
   like a gate that passed** — so the accidental unit-test failure in (1) was, in practice,
   the only thing standing between a source-degraded payload and production.

### 3b. The lane split

`validate_api_data_contract` now partitions its errors and publishes both halves
(`sourceHealthErrors` / `structuralErrors`, plus `sourceHealthOk` / `structurallyOk`).
`ok` is unchanged and still means "everything passed".

An error is **source-health** iff it can flip purely because an upstream provider returned
less data than usual, with our code byte-identical: `partial_run_critical:*`,
`source_missing:*`, `pick_count_below_floor:*`, missing/empty `pickAnchors`, an
implausibly small IDP pool. Everything else — schema, rank invariants, the 1..9999 scale,
blend-hull integrity, the pick-completeness census — is **structural**.

| lane | where it blocks | why |
|---|---|---|
| structural | PR Validation, Release Candidate | statements about our code, given whatever payload arrived |
| full (structural + source health) | Deploy Production | the deploy ships `exports/` and `data/` to the box, so refusing to ship a board built without a critical market is fail-safe — production keeps serving what it already has |
| advisory | PR Validation (`scripts/check_source_health.py`) | a provider outage stays loud without being evidence about a diff |

Recovery needs no override: the 2-hourly refresh re-scrapes and the condition clears.

### 3c. Proof the signal survives

`tests/api/test_contract_health_lanes.py` — every case built from a SYNTHETIC payload, no
live board, no network:

* a timed-out critical source is still an **error**, still makes the contract `invalid`,
  and lands in `sourceHealthErrors` and nowhere else;
* the structural lane is **byte-identical** between a healthy payload and the same payload
  with KTC timed out (the A/B that defines the boundary);
* a real code defect (an out-of-scale canonical value) still fails the structural lane —
  and both conditions are reported simultaneously in their own lanes, so a degraded scrape
  cannot mask a code defect;
* the partition is total: `sourceHealthErrors + structuralErrors == errors`.

Live evidence on the real degraded payload: `--lane structural` exits 0 while printing
`::warning title=Source health::partial_run_critical:KTC`; `--lane full` exits 1.

### 3d. The census — every same-class site, measured not guessed

Method: run the full `-m "not livedata"` suite twice, once against the degraded 19:09
payload and once against the healthy 17:03 payload from the archive, and diff the failure
sets. 7,600+ tests each pass.

| module | tests | what made it live-coupled | disposition |
|---|---|---|---|
| `api/test_canonical_value_scale_contract.py` | 1 | `ok is True` precondition | **repaired** — asserts the absence/presence of `canonical_value_out_of_scale` specifically, which is strictly stronger for its own purpose and cannot be flipped upstream |
| `consensus_edge/test_wiring.py` | 10 | built its board from `zips[-1]`, *the newest* archive | **repaired** — `tests/archive_fixtures.newest_complete_raw_payload()` selects the newest archive the contract's own source-health definition calls complete |
| `consensus_edge/test_fair_value.py` | 2 | same | **repaired** — same helper |
| `consensus_edge/test_snapshot.py` | 0 (latent) | same shape, weaker assertion | **repaired** — same helper, before it could fire |
| `history/test_temporal_ledger.py` | 1 | `assertGreater(zeros, 500)` — absolute count over the live board | **repaired** — asserts *every* ranked row stamps 0 and that there is at least one: board-size independent and strictly stronger |
| `api/test_draftsharks_negative_values.py` | 1 | absolute coverage floors (326/…) over a variable player population | **reclassified** (single test) — the carve-out's own three gates stay blocking and passed throughout the outage |
| `trade/test_faab_calibration.py` | 2 | anchors resolved FROM the live board; its own docstring says "against the REAL exported board" | **reclassified** (module) — the engine's deterministic invariants are already pinned on a synthetic board in `tests/trade/test_faab_engine.py` |

17 tests across 7 modules. Five modules were **repaired** (they keep blocking); two tests /
one module were **reclassified**, each with the deterministic coverage that replaces them
named explicitly. Nothing was marked `livedata` to make CI green.

One apparent finding was NOT real: `league_intel/test_te_premium_invariants.py` failed in
the healthy-payload run because it calls `inspect.getsource(_compute_unified_rankings)` and
this session was editing that file mid-run. Recorded so nobody re-hunts it.

---

## 4. Release discipline

**Root cause.** `pull_request` CI validates a merge ref computed when the run starts.
GitHub's merge button then builds a *new* merge commit against whatever the base is at
click time. The gap on 2026-08-16 was **103 seconds**, and what landed in it was a data
refresh — which in this repository is an input to the build, the tests and the contract,
not inert drift.

**Mechanism.** `scripts/check_release_candidate.py` classifies what the base has moved by
that the head does not contain:

* **A — inert**: prose nothing reads at build or test time.
* **B — source / governance**: code, tests, workflows, deploy scripts, canonical planning records.
* **C — build/test/contract-consumed data**: `data/`, `exports/`, `CSVs/`, `config/`.

Advisory on every PR (so the state is always visible), and **strict once**, at the release
moment, from `.github/workflows/release-candidate.yml` — a `workflow_dispatch` job that
asserts the property, then merges the base in and runs the gates against *the tree that
will exist*, under a `release-candidate` concurrency group.

**Deliberately bounded.** Blocking on every base change would chase a 2-hourly refresh
forever (green → refresh → revalidate → refresh), which the owner explicitly ruled out. The
discipline is: develop → full checks → one bounded final review → **HEAD FREEZE** →
integrate the base ONCE → validate that exact SHA → merge promptly → the deploy validates
the merged tree anyway.

**Residual, stated rather than hidden:** this makes the race *detectable and bounded*, not
impossible. No in-repo gate can hold a lock across a human clicking merge. The deploy's
validate job remains the backstop, and it held on the day.

---

## 5. The eleven C1-U6 follow-ups

| # | item | classification | outcome |
|---|---|---|---|
| 1 | Scraper rollover year-literals | **CURRENT DEFECT (latent)** | Fixed. `2026` and `(2027, 2028)` derived from the vendor anchors through the canonical owner (`derive_current_draft_year_from_names` / `derive_future_tier_years_from_names`, which now parse via the C1-U3 identity owner instead of one hard-coded regex). Discount seeds/clamps re-keyed by year OFFSET — same numbers, now rolling. Verified byte-identical today: current 2026, future (2027, 2028). |
| 2 | Synthetic rows in translation pools | **CURRENT DEFECT** | Fixed. Derived far-future pick rows no longer enter the cross-market backbone's evidence pool. Measured below. |
| 3 | Scraper R5/R6 display values | **CURRENT DEFECT** | Fixed. The model composite is no longer published under the `ktc` key (row *and* exported anchor map) for rows no vendor priced, and `_sites` reports the true count instead of `max(1, …)`. Board-inert: 12 rows lose a fabricated vendor value, **0 canonical values move** — they never voted, exactly as the C1-U6 record said. |
| 4 | Frontend missing→0 | **CURRENT DEFECT** | Fixed. `league-analysis.js` returns `value: null` + `unresolved: true` on every unresolvable branch *and* for rows the board leaves unpriced; the aggregator excludes them (it was adding `pow(max(0,1), alpha)` = 1 per ghost) and counts them; `/trades` renders "—", not "0". `portfolio-insights.js` no longer collapses a null board value to 0, and its stale "the board publishes nothing for 2029" comment is corrected. |
| 5 | `check_product_plan_governance.py` red | **CURRENT DEFECT (in the script)** | Fixed. All four documents ARE classified in the governance index; the script compared against a hard-coded allowlist instead of reading the index. It now reads the index — stricter, not weaker (a doc named nowhere still fails; verified with a negative control). Now CI-wired, which it never was. |
| 6 | `roster_intel` `pickValue: 0.0` | **CURRENT DEFECT** | Fixed. `pick_value` is `float \| None`, defaulting to `None`; the payload publishes `pickValue: null` + `pickValueState: "unavailable"` when nobody supplied it. No pick pricer was added. |
| 7 | IDPTC staleness | **OBSERVABILITY GAP, not a valuation defect** | Measured (§2) and surfaced by the new source-health lane. No methodology change: C1-U6 already counted IDPTC as ONE observation, not 34. |
| 8 | Module-global derivation state | **CURRENT DEFECT (concurrency)** | Fixed. `_SYNTHETIC_FAR_FUTURE_PICK_NAMES` + `_SYNTHETIC_PICK_DERIVATIONS` are gone; the injection returns its map and it is threaded to the three passes that read it. Two overlapping override builds could previously reset each other's state mid-stamp. Proven: 3 sequential builds hash-identical, 4 concurrent builds hash-identical to them. |
| 9 | Transparency-stamp precision | **CURRENT DEFECT (label)** | Fixed. Every derived row that carries a year factor now names its basis: `yearStepBasisYear` + `yearStepInheritedFrom` on round-step rows, `yearStepFactorIsMeanOfBasis` on generic rows. Rows with a year factor and no stated basis year: **12 → 0**. No value changed. |
| 10 | Simulator name-keyed dedup | **CURRENT DEFECT** | Fixed. The after-state removes by MULTIPLICITY (caller label first, board identity second), so trading one of two picks that share a board row no longer removes both. |
| 11 | Export-leg census | **INTENTIONAL CURRENT CONTRACT — proven** | The export leg is scraper-produced throughout: `dynasty_full.csv` is `Player,Composite,Sites,<per-site raw>`, `dynasty_values.csv` is per-site raw, both written by `Dynasty Scraper.py`, and no export carries `rankDerivedValue`. It is the raw-evidence lane, not a canonical-value surface. Pinned by `tests/api/test_export_leg_is_raw_evidence.py` so that if a contract-derived export ever ships, the census stops being optional. |

Ten of eleven were current defects and are fixed; one is an intentional contract, proven and
now pinned. None was deferred to a future unit.

---

## 6. Value impact of the repairs

Only follow-up 2 moves canonical values. Measured on the healthy 2026-08-16 board,
before → after:

* **12** synthetic rows leave the backbone's evidence pool.
* The shared-market IDP ladder shifts by **at most 12 combined ranks** — exactly the number
  of rows removed, which is the arithmetic upper bound and confirms nothing else changed.
* **297** rows change value: **p50 0.085%, p90 0.152%**. Same order as the ±0.1% coupling
  C1-U6 measured and documented for the same mechanism.
* **2** IDP rows move ~29.5% (Derwin James, Rueben Bain). Mechanism: with five sources each,
  a ≤12-rank shift crosses the trim boundary of the count-aware mean-median (k ≥ 5 trims one
  extreme per side), so *which* observation is trimmed changes and the blend steps. That
  discontinuity is a designed property of the blend, not a new one.
* Direction: mostly upward for IDP, and that is the defect being corrected — synthetic rows
  were padding the vendor's pool with assets it never published, pushing IDP players to
  worse combined ranks and therefore lower translated values.

Everything else is inert: follow-ups 3 and 9 change 0 values (verified by rebuild), 8 is a
lifetime change with hash-identical output, and 1 produces byte-identical labels today.

No methodology was altered: no curve, weight, family or classification changed, the
per-cell year-step family remains **PRIOR**, no second pick pricer exists, and no derived
prior was relabelled as measured evidence.

---

## 7. What this pass deliberately did not do

No C1-U5, C1-U7, C1-U8, C1-U9, C1B or C2+ work. No owned-pick distributions, no team
strength, no `CANONICAL_V2` activation, no new source, no trade-recommendation methodology,
no projections, no UI redesign. No assertion was relaxed to obtain green, no production
health protection was removed, and no missing value was disguised as zero.
