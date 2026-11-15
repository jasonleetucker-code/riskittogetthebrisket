# Outlier integrity V2 — owner report

**Conclusion: MORE RESEARCH REQUIRED.**

Authority: owner directive "Fix the outlier filter and restore DLF IDP voting" (2026-10-20),
including its D4 addendum, and the owner's earlier Option 3 decision. This report covers directive
§13 deliverables A–H. It recommends no activation:

* `outlier_integrity_v2` and every V2 sub-flag are **default OFF**.
* The DLF IDP hold (`dlf_offense_only_vote`) stays **ON**. DLF Rookie IDP stays held.
* D4 (`dlf_values_rank_hill_vote`) stays **OFF**.
* Nothing activates without explicit owner approval.

Branch: `claude/outlier-integrity-v2`. Preregistration anchor: `3c69945723`. Evidence head
reviewed: `41836c7d17`. Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

No Hill constant, curve, source weight, correlation group, family cap, freshness policy, Package
VA, geom_q078_v1 or trade math changed. Reviewer 1 checked the diff against the merge base: it is
empty for `src/canonical`, `config/weights`, `config/confidence`, `src/api/confidence.py`,
`source_lineage.json`, `freshness_v1.json`, `src/sources` and `src/trade`.

---

## Summary in five lines

1. **The DLF defect is understood and V2 fixes it.** The incumbent Hampel filter never sees an IDP
   row until DLF lifts it to 4 votes. At n = 4 its scale collapses on a cluster of synthetic,
   translated values, and it then drops 31 legitimate votes. V2 keeps all 31 on both pins and keeps
   1,623 / 1,623 such votes across all 68 held-out boards.
2. **V2 catches the real historical feed failures:** rookie boards 22 / 22, the October IDPTC
   format switch 3 / 3 (V1 missed it), and the Justin Jefferson wrong-player row on every board.
3. **V2 fails every mandatory §5 safety gate on the gate of record.** It does not yet reliably
   catch corrupted values on three-provider rows without history, and it cannot catch wrong-player
   swaps that carry no identity evidence.
4. **Other preregistered criteria also fail:** stability (M4), clean-board false exclusions and
   board-level false positives, and performance (1.69× against a 1.25× limit). Stage 2 also
   recorded a FAILED_SELECTION.
5. **All four independent reviewers returned `ok: false`.** Three judged the problems not fixable
   within this registration. The held-out data has been spent, so a successor needs a new
   preregistration and fresh held-out boards.

---

## Artifact index

| what | where |
|---|---|
| Preregistration (anchor `3c69945723`) | [`../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`](../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md) |
| Architecture | [`../OUTLIER_INTEGRITY_V2_ARCHITECTURE.md`](../OUTLIER_INTEGRITY_V2_ARCHITECTURE.md) |
| Deviations log (C1–C22, T1–T4, S1–S16) | [`DEVIATIONS.md`](DEVIATIONS.md) |
| Frozen thresholds (Stage 2, E only) | [`FROZEN_THRESHOLDS.json`](FROZEN_THRESHOLDS.json) |
| Frozen test-population manifests + hashes | [`manifests/`](manifests/) ([`INDEX.json`](manifests/INDEX.json), [`MANIFEST_SHA256.txt`](manifests/MANIFEST_SHA256.txt), [`build_manifests.py`](manifests/build_manifests.py)) |
| Labelled history cases, regression set | [`manifests/HISTORY_CASES.json`](manifests/HISTORY_CASES.json), [`manifests/REGRESSION_SET.json`](manifests/REGRESSION_SET.json) |
| A. Root-cause reproduction | [`rootcause/README.md`](rootcause/README.md), [`rootcause/output/`](rootcause/output/), [`rootcause/run_all.sh`](rootcause/run_all.sh) |
| Development gate run (E_DEV, not of record) | [`gates_dev/README.md`](gates_dev/README.md), [`gates_dev/edev_20260930_130404.json`](gates_dev/edev_20260930_130404.json) |
| R constraints (31 votes, D4 set) | [`r_constraints/README.md`](r_constraints/README.md), [`r_constraints/D4_REGRESSION_SET.json`](r_constraints/D4_REGRESSION_SET.json), [`r_pin2015.json`](r_constraints/r_pin2015.json), [`r_pin0527.json`](r_constraints/r_pin0527.json) |
| §6 comparison boards A–D, A′–C″ | [`evaluation/README.md`](evaluation/README.md), [`TABLES_pin2015.md`](evaluation/TABLES_pin2015.md), [`TABLES_pin0527.md`](evaluation/TABLES_pin0527.md), [`MATERIAL_ROWS_pin2015.md`](evaluation/MATERIAL_ROWS_pin2015.md), [`MATERIAL_ROWS_pin0527.md`](evaluation/MATERIAL_ROWS_pin0527.md), [`FOCUS_pin2015.md`](evaluation/FOCUS_pin2015.md), [`FOCUS_pin0527.md`](evaluation/FOCUS_pin0527.md), [`THEO_JOHNSON_I052241.md`](evaluation/THEO_JOHNSON_I052241.md), [`team_history.txt`](evaluation/team_history.txt) |
| §7 historical replay (Stages 2–4) | [`replay/README.md`](replay/README.md) |
| Stage 3 at frozen thresholds + performance | [`replay/stage3_r/`](replay/stage3_r/) ([`README.md`](replay/stage3_r/README.md), [`perf_pin2015.json`](replay/stage3_r/perf_pin2015.json)) |
| Stage 4 held-out (the one run) | [`replay/stage4_heldout/evaluation.json`](replay/stage4_heldout/evaluation.json), [`gates_nohistory_gate_of_record.json`](replay/stage4_heldout/gates_nohistory_gate_of_record.json), [`gates_arriving_reported.json`](replay/stage4_heldout/gates_arriving_reported.json), [`dlf_restore_pairs.json`](replay/stage4_heldout/dlf_restore_pairs.json) |
| Exploratory E_DEV replay | [`replay/exploratory_e_dev/evaluation.json`](replay/exploratory_e_dev/evaluation.json) |
| H3/H4 check, restore-pair script | [`replay/checks/`](replay/checks/) |
| F. DLF restoration readiness | [`dlf_readiness/README.md`](dlf_readiness/README.md), [`READINESS_pin2015.md`](dlf_readiness/READINESS_pin2015.md), [`READINESS_pin0527.md`](dlf_readiness/READINESS_pin0527.md), [`IMPACT_pin2015.md`](dlf_readiness/IMPACT_pin2015.md), [`IMPACT_pin0527.md`](dlf_readiness/IMPACT_pin0527.md), [`impact_values_pin2015.csv`](dlf_readiness/impact_values_pin2015.csv), [`impact_values_pin0527.csv`](dlf_readiness/impact_values_pin0527.csv) |
| Implementation | `src/identity/resolution.py` (Layer A), `src/api/source_integrity.py` (Layer B + reason codes), `src/api/outlier_policy.py` (`oiv2-layer-c-v1`), `src/api/data_contract.py` (one dispatcher), `src/history/source_rank.py` (record-only history lane), `config/sources/outlier_integrity_v2.json`, `src/api/feature_flags.py`, `frontend/lib/source-voting-status.js`, `frontend/lib/value-explainers.js` |
| Research harness | `src/robust_filter_shadow/oiv2_gates.py`, `oiv2_replay.py`, `oiv2_select.py`, `oiv2_eval.py`; `scripts/oiv2_gates.py`, `oiv2_replay.py`, `oiv2_regression_boards.py`, `oiv2_perf.py` |
| Tests | `tests/api/test_source_integrity.py`, `tests/identity/test_identity_evidence_v2.py`, `tests/api/test_outlier_integrity_v2_layer_c.py`, `tests/api/test_oiv2_full_pipeline_gates.py`, `tests/api/test_oiv2_regression_set.py`, `tests/api/test_oiv2_scenario_matrix.py`, `tests/api/test_oiv2_dlf_readiness.py`, `frontend/__tests__/source-integrity-labels.test.js` |

---

## A. Root cause, confirmed and reproducible

Reproduce it with `bash docs/sources/outlier_integrity_v2/rootcause/run_all.sh`. Inputs are
pinned on two boards:

* **pin2015**: refresh `d9680440a5`, payload sha256 `3ef54acd…9199`.
* **pin0527**: refresh `eb10d3e12d`, payload sha256 `b639608f…e11c`. This is V1's diagnosis board.

A re-implementation of the incumbent filter reproduces every board-B decision with 0 mismatches.

1. **Board A never filters an IDP row.** IDP Show is freshness-withheld and DLF is held, so no IDP
   row has more than 3 voters. The filter's minimum is 4.
2. **Adding DLF brings 158 IDP rows to n ≥ 4.** With n = 4 and votes sorted x1 ≤ x2 ≤ x3 ≤ x4, the
   median is (x2+x3)/2 and MAD = ((x3−x2)/2 + min(m−x1, x4−m))/2. The farther outer vote never
   enters the scale.
3. **The cluster is tight by construction.** FantasyPros IDP, DLF IDP and DLF Rookie IDP are all
   priced through IDP Trade Calculator's own player order, so equal positional ranks land on
   identical values. Draft Sharks prices from its own list and is the dissent on 18 of the 31
   drops.
4. **The 1,000-point floor sets the band on 21 of the 30 rows,** but it is not the cause: remove
   the floor and the same 31 votes still drop.
5. **The dropped votes are disagreement, not corruption.** The median dropped vote sits 49% from
   the row median. No identity, scale or freshness defect was found on any of them.

| | pin2015 | pin0527 |
|---|---|---|
| other-source IDP votes dropped A → B | **31 on 30 rows** | **31 on 30 rows** (same set) |
| by source | Draft Sharks 18, FantasyPros 10, IDP Trade Calculator 3 | same |
| DLF's own share of the large moves | max 5.5%, median 1.0% across 179 moved rows | — |

Large moves on pin2015 (A → B): Trevin Wallace −54.3%, Myles Garrett +48.1%, CJ Allen −45.7%,
T.J. Watt +43.3%, Josiah Trotter +42.7%, Will Anderson +37.0%, Aidan Hutchinson +34.6%, Danielle
Hunter +30.3%. In every one, the filter's reaction accounts for almost all of the move and DLF's
own vote for at most 4.4%.

**Already in production, affecting confidence only.** The same statistic runs inside the B11
lost-evidence replay. It decides lost-evidence seats on 28 production IDP rows today, though it
removes no vote.

**D4 addendum.** The same mechanism appears on offense when D4 votes. The rule-defined D4
regression set is 20 votes, on 14 rows (pin2015) and 13 rows (pin0527):
[`r_constraints/D4_REGRESSION_SET.json`](r_constraints/D4_REGRESSION_SET.json).

## B. V2 architecture

Full text: [`../OUTLIER_INTEGRITY_V2_ARCHITECTURE.md`](../OUTLIER_INTEGRITY_V2_ARCHITECTURE.md).
The design principle is to answer structural questions first and judge disagreement last.

* **Layer A — identity** (`src/identity/resolution.py::assess_identity_evidence`). It grades each
  existing CSV join against the source's own published position, team, age and ids. The verdict is
  VERIFIED, NAME_ONLY, CONTRADICTED or UNRESOLVED. A refused observation is absent, never zero. The
  join itself is unchanged; there is no second matcher.
* **Layer B — source and normalization integrity** (`src/api/source_integrity.py`):
  * **B0 format:** a CSV's rank order must agree with its value order.
  * **B1 rookie ladder fail-closed:** an untranslated rookie vote is withheld as
    `normalization_untranslated`.
  * **B2 payload-vs-CSV provenance:** the scraper's payload copy of a source is checked against the
    vendor's own same-run CSV. Row proof and board proof both replace the payload value with the
    CSV value; with no CSV row the observation is withheld.
  * **B3 segment integrity:** direction, gross scale, and class conservation.
  * **B4 continuity holds:** each source is compared with its own history.
* **Layer C — legitimate disagreement** (`oiv2-layer-c-v1`). A vote is removed only when all six
  registered guards hold:
  1. at least 3 providers are on the row;
  2. two other providers, not lineage-linked, sit within ln 2 of each other;
  3. the vote is beyond τ_C from every other provider;
  4. the source's own history does not confirm the vote;
  5. the vote's family holds less than half of the family-capped weight;
  6. at least 2 providers survive.

  There is no MAD and no scale estimated from the row being judged. Similar numbers never merge
  providers; only stamped lineage does. A kept dissent is stamped `kept_dissent` and still votes.
* **Layer D — confidence.** `confidence.py` and `gate_v1.json` are byte-identical to main, so there
  is no second confidence engine. A Layer C drop reaches confidence exactly as a filter drop does
  today. The D-1 confidence change (`integrity_holds_as_withheld`) is a separate flag reserved for
  the owner.
* **One dispatcher.** The per-row filter slot, the B11 replay and `_two_way_alt_center` all route
  through one Layer C context. With V2 on, the incumbent filter is never called. V1 and V2 are
  mutually exclusive.
* **Transparency (§10).** Each judged observation carries one primary reason and one of the ten
  directive categories. The contract carries `sourceIntegrity.votingCategories`, and the frontend
  label map and per-player explainer render the categories.

## C. Implementation (reusable, tested, default OFF)

* **Flags**, all default OFF: `outlier_integrity_v2` (the master), `identity_evidence_v2`,
  `payload_provenance_guard`, `rookie_ladder_fail_closed`, `integrity_holds_as_withheld` and
  `source_rank_history_record` (record-only).
* **Flags-off identity.** The golden board plus `board_diff --expect-no-value-change` showed 0 moved
  and 0 rank changes, and the full-contract sha256 and `cmp` were identical, against the merge base
  at `4055904e40`. Reviewer 4 re-measured byte identity at HEAD `41836c7d17` on the full current
  export (sha `fc429671cfed7475`, 17,338,703 bytes): identical.
* **Tests**, all synthetic:
  * 75 for Layers A/B, 36 for Layer C, and 38 in the scenario matrix covering the full §5 scenario
    list for offense and IDP;
  * 384 regression-set cases, asserting retention at every τ_C grid point;
  * 12 + 7 env-gated full-pipeline gate tests, 10 DLF readiness tests and 7 frontend label tests.
* **Sweeps.** Backend sweeps passed at each implementation unit, the last being tests/api,
  tests/canonical and tests/identity with 6,030 passed. The coercion gate is clean and Ruff 0.6.9 is
  GREEN.

## D. Historical evidence vs incumbent and V1, including every adversarial case

### Adversarial gates — complete layered system (directive §5)

Gate board: the registered V board `dynasty_export_20261018_114711`, seed 2033, Stage 4, run once at
code `8c33447d0a` with a clean tree. Corrupted votes are injected after pricing and before every
integrity layer (T4), which is the worst case for V2. No owner O-1 or O-2 decision exists, so
**NO-HISTORY is the gate of record**.

| gate | V1 (its own registration, filter-only) | required | incumbent (full pipeline) | V1 (full pipeline, this board) | **V2 NO-HISTORY (gate of record)** | V2 ARRIVING history (reported only) |
|---|---|---|---|---|---|---|
| Extreme high ×5 | 93.7% | 90% | 16.4% | 87.6% | **53.1% — FAIL** | 97.2% |
| Extreme low ×0.2 | 58.3% | 90% | 1.5% | 52.0% | **26.5% — FAIL** | 95.5% |
| Extreme high ×20 | 97.9% | 95% | 24.0% | 93.8% | **70.1% — FAIL** | 100% |
| Extreme low ×0.05 | 92.6% | 95% | 4.4% | 84.3% | **67.7% — FAIL** | 100% |
| Wrong-player matching | 15.0% | 90% | 8.7% | 14.3% | **9.5% — FAIL** | 48.8% (FAIL) |
| Single-source spike | 100% | 95% | 0.0% | 91.0% | **62.9% — FAIL** | 100% |
| Wrong-scale board detection | 15/16 | 16/16 | — | — | **4/16 — FAIL** (only reversed boards) | 12/16 (FAIL) |

**Why V2 fails.** IDP Show was freshness-excluded on the gate board, so most material cases sit on
rows with exactly three voting families. On those rows Layer C often has no reference pair, and
without history neither B4 nor the persistence guard can act. With real history, B4 holds 94–100% of
the corrupted observations (the ARRIVING column), but ARRIVING is not the registered gate.

Wrong-player swaps in AD2 carry no identity evidence by construction, so Layer A has nothing to
read. Scraper evidence stamps (U2/U2b/U3) and a vendor-id mapping do not exist yet.

**Not run** (S13): AD2-ID, AD2-SUR, AD2-N (a mandatory 100% gate), INJ-DUP end to end, the
PERSISTENT history variant and the V2-RPC comparator.

**Other injections:**

* **INJ-H1** (rookie-ladder references disabled): 68 / 68 boards withheld correctly, 0 false fires.
  PASS.
* **INJ-SEG:** 3 / 68 boards proven. FAIL by construction, logged as S16 and disputed by
  reviewer 1.

### Labelled historical cases

| case | V2 | incumbent / V1 |
|---|---|---|
| H1 — 22 rookie boards voting untranslated within-class ranks | **22 / 22 withheld** (2,701 votes), 0 fires where the ladder exists | the incumbent drops them row by row; V1's board screen excluded them |
| H2 — IDPTC format switch on Oct 7, Oct 8 and Oct 16 (a third episode) | **3 / 3 board-proven by B2**; 391–423 values replaced from the vendor's own CSV | the incumbent drops 82–90 IDPTC votes; **V1 drops only 1–2** |
| H3 — Justin Jefferson wrong player (~800 vs ~7,500) | **caught on all 3 boards**; the payload value is replaced by the CSV value (837 → 7,674) | both drop it as an outlier |
| H4 — fallback with correct values | pass: no IDPTC exclusion beyond the H3 row | — |
| N1–N5 controls | 0 hard quarantines | — |
| N6 benign coverage changes | hard findings on N6-listed sources: 9 `ktcCrowdSfTep` B0, 3 `idpTradeCalc` B2 (the H2 boards), and 2 `idpTradeCalc` B3a, which are board-level false positives (reviewer 3's correction of the replay README) | — |

**Why V1 missed October.** The IDPTC shift was moderate and pointed different ways by position: QB
around −0.15 log, RB/WR/TE/IDP +0.17 to +0.21. V1 compared IDPTC with the other sources, and its
pooled offense statistics (−0.20 to −0.22 signed, 0.26 to 0.30 absolute) stayed below its ln 1.5 and
ln 2 limits. V2's B2 instead compares the payload with the vendor's own same-run CSV. On a healthy
capture the two agree (m_g = 0.000), so the shift is a deterministic provenance proof that does not
depend on anyone's opinion.

### Held-out metrics (V ∪ I, 68 boards, evaluated once)

| metric | result | criterion |
|---|---|---|
| M1 held-out-source agreement | P1 −0.00104 overall (V2 slightly closer); IDP +0.055 (n 53, worse) | **INSUFFICIENT**: 2 week-blocks, 4 required |
| M4 stability ratio | 1.033, upper bound **1.305** | **FAIL** (≤ 1.10) |
| clean-board false exclusions | above 0.5% on 2 boards (5.8%, B3a); up to 8.7% on 8 boards including B0 | **FAIL** |
| board-level false positives | B3a quarantines all IDPTC offense on 2026-10-10 from 2 rows; B0 quarantines all of KTC Crowd on 7 boards over 1–2 discordant rows | **FAIL** |
| ≥ 10% movers attributed | 902 movers: 884 named, 18 derived picks | reported as pass in the replay; **contested by reviewers 3 and 4** (see G) |

### Exploratory vs held-out

| | exploratory E_DEV (development; decides nothing) | held-out V ∪ I (the one run) |
|---|---|---|
| P1 | −0.00067 [−0.00159, −0.00008], 6 week-blocks; IDP +0.044 | −0.00104, only 2 week-blocks (INSUFFICIENT); IDP +0.055 |
| M4 | 1.026 [0.995, 1.074] (within the bar) | 1.033 [0.952, **1.305**] (FAIL) |
| board-level false positives | 0 B2/B3; B0 KTC Crowd on 2 boards | B3a IDPTC offense ×2; B0 KTC Crowd on 7 boards |
| ≥ 10% movers | 616, all attributed or derived picks | 902 (884 + 18) |

### Stage 2 selection (E only)

* **τ_C:** infeasible. The best grid point (ln 4) caught 91.8% / 91.0% against a 95% bar; the floor
  ln 4 is used.
* **B3b n_min / ρ_min / τ_gross:** FAILED_SELECTION (3 of 1,124 injections missed).
* **τ_age = 1:** selected from an empty evidence set (S15).

Under the preregistration, any one of these alone prevents READY FOR APPROVAL.

## E. Valuation impact (every material change, with source-level reason)

Every comparison board shares one input and changes only the flags. Results were built at the
provisional thresholds (§6 boards) and confirmed at the frozen thresholds (Stage 3). Every row
moving 5% or more, or 25 or more ranks, across 17 comparisons is attributed to source-level vote
changes in
[`evaluation/MATERIAL_ROWS_pin2015.md`](evaluation/MATERIAL_ROWS_pin2015.md) and
[`evaluation/MATERIAL_ROWS_pin0527.md`](evaluation/MATERIAL_ROWS_pin0527.md). The full per-row
activation impact is in [`dlf_readiness/impact_values_pin2015.csv`](dlf_readiness/impact_values_pin2015.csv)
and [`dlf_readiness/impact_values_pin0527.csv`](dlf_readiness/impact_values_pin0527.csv).

### Boards A–D summary

The boards are:

* **A:** production — DLF held, incumbent filter.
* **B:** DLF IDP + incumbent.
* **C:** DLF IDP + V2.
* **D:** V2, DLF held.
* **D4 boards:** B′ (D4 + incumbent), C′ (D4 + V2), and B″ / C″ (both restorations).

| comparison | pin2015 result |
|---|---|
| B vs A | the incumbent drops all 31 legitimate IDP votes (Draft Sharks 18, FantasyPros 10, IDPTC 3) |
| C vs A | all 31 kept. Every IDP change is DLF's own vote: 180 of 397 rows, max 6.7% (Jacob Rodriguez) |
| D vs A (filter change alone) | no IDP value moves. 189 offense rows move because V2 keeps the incumbent's 99 offense drops; 98 of those 99 votes have another source within 2×. The exception is LaJohntay Wester, +34.6%: Flock's vote is kept at 2.1× the nearest source and stamped `kept_dissent` |
| C′, C″ vs B′, B″ | D4 set 20 / 20 kept |
| C′ vs D (D4 on with V2) | 302 offense rows, max 4.4% (5.1% on pin0527) |

**Focus rows, A → B → C:**

| player | A | B | C |
|---|---|---|---|
| Trevin Wallace | 1937 | 884 | 1934 |
| Myles Garrett | 3555 | 5245 | 3469 |
| Aidan Hutchinson | 4772 | 6422 | 4772 |

CJ Allen, Watt, Trotter, Anderson and Danielle Hunter end between −1.0% and +5.3% of A, and the
remainder is DLF's own vote.

**Other effects:**

* **Two-way:** Travis Hunter goes 3599 → 3493, from DLF IDP's own vote entering his DB alt panel.
  Nothing is dropped there.
* **Picks:** only the 51 current-year slot picks tethered to the rookie pool move, max 4.7%. No
  derived future-year, round or generic pick moves.

**Side effects V2 introduces** (boards findings F1–F6):

* **F1:** with no history, Layer A holds 4 FantasyPros Fitzmaurice votes for team mismatch, plus 2
  DLF Values votes on D4 boards. In each case the vendor's team is the player's previous team, so
  these are false holds. Joe Milton moves −3.3%.
* **F2:** a refused entry is removed before the source is re-ranked, which shifts 179–322 other
  votes of the same source by up to 1.4%.
* **F3:** identity stamps appear on observations that don't vote.
* **F4:** there are zero Layer C drops on either pin.
* **F5:** two IDP rows' lost-evidence reasons change (Byron Murphy, Jack Campbell); no confidence
  bucket changes.
* **F6:** the r_constraints README understates identity-layer refusals.

**Held-out top causes of ≥ 10% movers:**

| cause | movers |
|---|---|
| Draft Sharks IDP vote restored from an incumbent drop | 534 |
| KTC Crowd B0 refusal | 85 |
| Draft Sharks IDP `identity_contradicted:age` (a false refusal; see G) | 48 |
| Draft Sharks offense vote restored | 31 |

## F. DLF restoration readiness (both feeds, D4, correct weights)

Readiness checks R1–R10 **pass on both pins**:
[`dlf_readiness/README.md`](dlf_readiness/README.md).

| check | result |
|---|---|
| R1 family and cap | all DLF boards are one `dlf` family under one cap |
| R2 populations | DLF IDP votes on 171 IDP rows; DLF Rookie IDP on 29 IDP rookie rows |
| R3 rookie translation | DLF Rookie IDP is translated through the IDPTC rookie ladder 29 / 29, and V2 withholds all 29 when the ladder is absent |
| R4 | no DLF vote rejected |
| R5 | adding DLF changes 0 Draft Sharks, FantasyPros or IDPTC vote statuses (the incumbent drops 31) |
| R6 confidence | +1 family on all 182 rows DLF votes on; low→medium 26 times and medium→low 20 times (all on the agreement axis); no change on rows DLF doesn't vote on |
| R7 board consistency | structural lane, ranks, scale and blend integrity all clean |
| R8 two-way | Travis Hunter's value comes from his DB alt panel |
| R9 picks | only the rookie-tether picks move; trade engines read the canonical value |
| R10 D4 | offense only, inside the `dlf` cap |

**Exact activation impact vs production, pin2015:**

| activation | IDP | offense | picks |
|---|---|---|---|
| V2 + DLF IDP + DLF Rookie IDP | 180 rows, max 6.7%, all from DLF's own votes | 190 rows, max +34.6% (Wester), from votes V2 restores | 51, max 4.7% |
| D4 on top | — | 302 rows, max 4.4% (Jack Strand) | — |

On pin0527: 179 IDP rows (max 6.7%) and 241 offense rows.

**Generalization on held-out data:**

* DLF IDP: V2 keeps **1,623 / 1,623** of the incumbent's newly dropped votes.
* D4: V2 keeps **1,102 / 1,123**. The 21 lost are KTC Crowd votes refused by B0 brittleness, not by
  Layer C.

**Readiness status: NOT READY TO ACTIVATE.** The DLF side is ready only conditionally: it depends on
V2 passing, and V2 has not passed. The owner should know these before any future activation:

* **G1:** the registry still declares DLF IDP `excludes_rookies=True`, but DLF's board now lists
  rookies.
* **G2:** confidence counts DLF IDP as eligible on rows it doesn't cover.
* **G3:** DLF IDP must never be restored without `rookie_ladder_fail_closed`. Under the incumbent
  filter, 21 of 29 DLF Rookie IDP votes would price within-class ranks as overall ranks.
* **G4:** Travis Hunter drops 2.9% on activation.
* **G5:** two DLF Values votes are held because there is no history lane.
* **G6:** activation-day numbers will differ from these, because the board refreshes about every
  two hours.

## G. Independent verification findings and how each was resolved

Four independent, fresh-context, read-only reviews ran against `41836c7d17`. **All four returned
`ok: false`.** Reviewers 1, 2 and 4 said `fixable: false` within this registration; reviewer 3 said
`fixable: true`, for evidence and disclosure defects only. Every reviewer agreed the verdict MORE
RESEARCH REQUIRED is correct and that nothing supports activation.

### Reviewer 1 — algorithm and preregistration fidelity

| # | finding | resolution |
|---|---|---|
| 1 | All seven §5 gates fail; criteria 5, 8 and 11 fail; B3b FAILED_SELECTION; no feasible τ_C. Part of the cause is in the coordinate: u saturates at ln 10 for values ≥ 9999, so ×5/×20 corruption of a high-value vote moves u by less than τ_C | **Accepted.** These drive the conclusion. A fix needs a new preregistration |
| 2 | B3b applies n_min only to the direction test; gross-scale and proof-escalated quarantines fire on any segment size. Not logged | **Open.** An unlogged implementation deviation, recorded here for the successor. It cannot be repaired under this registration because the held-out data is spent |
| 3 | The Stage 2 selector's proof set (B2 board proofs only) does not match the served rule, which also counts B1 untranslated votes and a single B2 row proof | **Open**, as above. It means the n_min/τ_gross feasibility check ran under a different rule than the one served |
| 4 | Post-held-out evaluator changes in `41836c7d17` (`DETERMINISTIC_PREFIXES`, the H3 "caught" definition, criterion-9 aggregation) are not logged | **Open; disclosed here.** The verdict is unchanged either way |
| 5 | The two lanes contradict each other on Theo Johnson | **Open**; see reviewer 2 #4 |
| 6 | Self-confirming persistence: a Layer C drop is recorded as accepted history, so a repeating corrupted value can become persistence-confirmed; B4 holds release at 2 fetches / 48 h | **Open design risk.** The PERSISTENT variant that would measure it was not run |
| 7 | The B2 sign-share reading makes INJ-SEG fail by construction; a reading consistent with both registered statements was available | **Open.** S16 logged the conflict but kept the failing reading. For the successor |
| 8 | B0 is brittle: duplicate ranks in the KTC Crowd CSV quarantine about 460 votes | **Accepted.** A registered-rule defect |
| 9 | Criterion 6 and the hard gate were not re-measured at HEAD | **Partly resolved.** Reviewer 4 re-measured flags-off byte identity at HEAD (identical). The 24,024 identity parity and the full hard gate remain unmeasured |
| 10 | AD2-N, AD2-ID, AD2-SUR, INJ-DUP, PERSISTENT and V2-RPC were not run | **Accepted, open.** Criterion 1 cannot pass regardless |

### Reviewer 2 — identity and provenance

| # | finding | resolution |
|---|---|---|
| 1 | A3 compares only three coarse position groups (OFFENSE/IDP/KICKER), so a QB entry on a WR row, or a DB entry on a DL row, is never contradicted | **Open implementation defect.** The fix is to apply family compatibility in A3. Successor work |
| 2 | The age rule compares a decimal vendor age with Sleeper's integer age and refuses correct players as `invalid_player_identity` (5 of 7 conflicts on current Draft Sharks CSVs are the same player) | **Open.** It contradicts directive §10 and is the source of the 48 `age` movers. Successor: compare against the interval [age, age+1) |
| 3 | Deviation C4 changes a registered A4 rule toward refusing less but is logged as a "clarification" | **Open.** It needs owner and reviewer acceptance or a revert in a successor registration |
| 4 | Theo Johnson provenance conflict: the boards lane (add-commit CSV tree) reports Draft Sharks 3182 dropped, 2184 → 2023; the replay (#1847 overlay of the archive's own `site_raw`) reports 3001, kept, 2184 → 2105 | **Open.** The archive's `site_raw/draftSharksSf.csv` lists rank 166, which supports 3001. Theo's 3182 case is covered only by a frozen panel transcribed from the #1817 lane |
| 5 | No full-pipeline gate exercises Layer A; its real detection rate is unmeasured | **Accepted, open.** It needs U2/U3 scraper evidence and a new registration |
| 6 | B0 whole-source quarantine on a single discordance; B3a class quarantine on 2 rows | **Accepted.** Registered-rule defects |
| 7 | An identity refusal re-ranks the source's other votes (F2) | **Open methodology question.** A refused entry should probably keep its ordinal slot |
| 8 | Team continuity is read from the join's entry while the mismatch check uses the A4-chosen entry | **Open.** A minor implementation bug |
| 9 | A1 resolves Sleeper ids against board rows only | **Open.** Minor; C5's rationale was never checked against a fuller directory |

### Reviewer 3 — historical methodology and evidence integrity

| # | finding | resolution |
|---|---|---|
| 1 | Analysis code changed after Stage 4 records existed, without a deviation entry | **Open; disclosed here**, same as reviewer 1 #4. The verdict holds under either evaluator because criteria 1, 5, 8 and 11 fail |
| 2 | Criterion 9 "pass" relies on an unregistered derived-pick exemption (18 rows), and 257 attributions name only a value change, with no layer or reason | **Accepted.** This report treats criterion 9 as **NOT DEMONSTRATED**, not pass |
| 3 | The replay README misstates N6, and criterion 4 has no verdict | **Accepted.** Corrected in §D above; criterion 4 is treated as **FAIL** (2 B3a board-level false positives on N6-listed IDPTC) |
| 4 | Stage order broken: R pins were read before the freeze (logged only as T1), and the held-out I board was rebuilt incumbent-only before Stage 4 without a deviation entry | **Disclosed here.** Neither loosens any gate, and the verdict is already MORE RESEARCH REQUIRED |
| 5 | Theo Johnson contradiction; criterion 2 overclaimed; R pin 3 (D4 on the newest I board) never built with V2 | **Accepted.** Criterion 2 is treated as pass on the two R pins only, with Theo's 3182 case unproven on a rebuilt board |
| 6 | 24,024 / 24,024 identity parity never measured | **Open.** Criterion 6 is partially evidenced |
| 7 | The full hard gate, full frontend suite and CI were never run on the final head | **Open.** This PR's CI will run them |
| 8 | A false "V2 drops 0 (any layer)" figure remains in `r_constraints/README.md` | **Disclosed here.** The correct figure is 5 identity refusals on pin2015 and 6 on pin0527. Historical evidence is not silently edited |
| 9 | `gates_arriving_reported.json` is labelled `gate_of_record_stage4`; the gate script has no single-start sentinel | **Disclosed here.** The NO-HISTORY file is the gate of record; ARRIVING is reported only |

### Reviewer 4 — performance, integration and transparency

| # | finding | resolution |
|---|---|---|
| 1 | The age rule refuses correct players (Pete Werner −12.8% on the current export) | **Open**, same as reviewer 2 #2 |
| 2 | B0 KTC Crowd quarantines are false positives (Brock Wright rank 352 at 1318 vs rank 351 at 1317) | **Resolved as a finding:** it answers the replay's open question. The refusals are false positives under the registered rule |
| 3 | B3a has no minimum-n guard | **Accepted.** A registered-rule gap |
| 4 | Performance: 1.8–2.0× on the full current export (deepcopy snapshot about 0.7 s, identity grading about 0.5 s); RSS +31 MB, within the bar | **Accepted.** Criterion 11 fails; reducible in a successor |
| 5 | V2 grows the contract by 2.39 MB (+13.8%), not measured or disclosed | **Disclosed here.** It bears on production memory; a successor should slim the per-vote stamps |
| 6 | Post-Stage-4 evaluator re-scoring is not logged | **Open; disclosed** (same as reviewer 1 #4 and reviewer 3 #1) |
| 7 | Criterion 9 skips rows that change between priced and unpriced (6 on the H2 boards) | **Accepted.** Part of criterion 9 being NOT DEMONSTRATED |
| 8 | Layer A refusals are absent from the per-player explainer (`sourceRankMeta`); they appear only in the census | **Open §10 transparency gap** |
| 9 | Mandatory gates fail; algorithm or registration changes needed | **Accepted** |

Reviewer 4 also confirmed:

* flags-off byte identity at HEAD;
* a clean merge with current `origin/main`;
* one canonical value and one trade path;
* `kept_dissent` correctly labelled "still voting" (Wester);
* every held-out ≥ 10% mover has a vote that moved by at least half of the row's log move.

## Unresolved risks

1. **Corruption detection without history is not reliable** on three-provider rows. The board
   evidence shows legitimate votes survive; it does not show corruption is caught.
2. **Wrong-player detection is unmeasured at the identity layer.** It needs upstream evidence that
   does not exist yet: U2/U2b/U3 scraper stamps and a vendor-id mapping.
3. **False refusals of legitimate votes:** the age rule, team-only holds with no history (F1), B0
   brittleness and B3a on 2 rows. Each would show a legitimate source as invalid, against directive
   §10.
4. **Self-confirming persistence and B4 release** could let a repeating corruption back in. This is
   unmeasured.
5. **Evidence-process defects:** unlogged post-held-out evaluator changes, the stage-order breaks,
   and the Theo Johnson provenance contradiction.
6. **Unmeasured items:** the 24,024 identity parity; the full hard gate and CI at HEAD; frontend
   bundle size; contract-size growth (+13.8%) and its production-memory effect.
7. **Two-way coupling:** Travis Hunter appears in adversarial batch contamination (≤ 0.64 log). C16
   judges his alt panel with no history and no lineage.
8. **Coordination:** #1831 (`voting_status.py`) is not on main, so the reason codes live in
   `source_integrity.REASON_CATEGORY` until it lands. Shared regions of `feature_flags` and
   `data_contract` may conflict with other open PRs.

## Criteria scorecard (prereg §11)

| # | criterion | result |
|---|---|---|
| 1 | §5 / §7 gates (gate of record) | **FAIL** (all seven; AD2-N not run) |
| 2 | 31 IDP votes and the D4 set retained | pass on R pins; D4 loses 21 / 1,123 on V / I to B0; Theo 3182 is not rebuilt |
| 3 | H1, H2, H3, H4 | **pass** |
| 4 | N1–N6 no hard quarantine | **FAIL** (N6: B3a IDPTC offense ×2; B0 KTC Crowd) |
| 5 | M1 and M4 | **FAIL** (M1 INSUFFICIENT; M4 upper bound 1.305) |
| 6 | flags-off byte identity, 24,024 parity | byte identity pass at HEAD; parity not measured |
| 7 | existing mandatory tests | targeted suites pass; full hard gate / CI pending |
| 8 | false exclusions ≤ 0.5%, zero board-level false positives | **FAIL** |
| 9 | ≥ 10% movers attributed | **NOT DEMONSTRATED** (reviewers 3 and 4) |
| 10 | §9 property tests | pass at Stage 1; not re-run at HEAD |
| 11 | performance ≤ 1.25× | **FAIL** (1.69× on the R pin, 1.8–2.0× on the current export) |
| 12 | independent review | **ran; all four `ok: false`** |
| — | Stage 2 selection | FAILED_SELECTION (B3b); τ_C infeasible |

## H. Owner decision

**MORE RESEARCH REQUIRED.**

Why not READY FOR APPROVAL: that verdict requires every mandatory gate to pass on the preregistered
criteria and every reviewer to be ok. Here all seven §5 gates fail on the gate of record, criteria
4, 5, 8 and 11 fail, criterion 9 is not demonstrated, Stage 2 recorded FAILED_SELECTION, and all
four reviewers returned `ok: false`.

Why not BLOCKED: no external dependency or owner decision stops further work. The failures are
design and evidence problems, and a successor registration can address them.

The registration's held-out data has been used once and may not be re-evaluated. Under
preregistration §11.1, a successor needs a new preregistration and fresh held-out boards collected
after it. What the evidence supports carrying forward:

* Keep B1 (rookie ladder fail-closed), B2 (payload vs same-run CSV) and Layer C's
  disagreement-preserving guards. They fix the DLF defect and catch the real historical failures.
* Repair B0 tolerance, B3a minimum n, B3b n_min scope, A3 family compatibility, the age comparison
  basis, ordinal-slot preservation for refused entries, and explainer coverage of Layer A refusals.
* Ship the upstream identity evidence (U2/U2b/U3, vendor ids) before re-running AD2.
* Decide O-1 (whether arriving history may be the gate) explicitly. With history, V2 passes
  AD1a–d and AD4.
* Reduce the build-time and contract-size overhead.

Nothing activates. `outlier_integrity_v2` and its sub-flags stay default OFF; the DLF IDP hold
(`dlf_offense_only_vote`) stays ON; DLF Rookie IDP stays held; D4 stays OFF. Activation of any of
them is owner-reserved and needs explicit owner approval.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
