# Outlier integrity v2: directive §6 comparison boards (A–D, with the D4 addendum)

Authority: owner directive 2026-10-20 "Fix the outlier filter and restore DLF IDP voting",
§6 (primary acceptance test) and its D4 addendum. Preregistration
`../../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md` §6.1 and §11 criterion 2.

This is a measurement. It changes no code path, no flag default, no constant and no value.
The DLF IDP hold (`dlf_offense_only_vote`) and the D4 hold (`dlf_values_rank_hill_vote`) stay
ON / OFF in the repository and in production. They differ only inside the local build process,
one board at a time.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Status: constraint check, not evidence

* **Code:** V2 at `eb06823c57` (branch `claude/outlier-integrity-v2`), clean tree.
* **Thresholds:** `provisional_stage1`. `tau_C` = ln 6. The `tau_board` / `tau_c` tables are empty. Stage 2 has not frozen anything.
* **History:** NO-HISTORY (`historyLane: override_empty`), so B3a and B4 abstain and Layer C persistence never confirms.
* **Status of the results:** these are R_REGRESSION_PIN must-pass constraint checks (prereg §5.1, deviation T1). They are not evidence, and they **must be re-run at Stage 3 on the frozen thresholds**. Nothing here was used to choose a threshold.
* **Held-out boards:** none was built with V2. The newest I_INDEPENDENT board was rebuilt with the incumbent only, for the owner-named Theo Johnson case.

## Reproduce

```bash
bash docs/sources/outlier_integrity_v2/evaluation/scripts/run_all.sh REPO WORK_DIR OUT_DIR
```

* **What it does:**
  * creates a throwaway sparse worktree at `CODE_SHA` (default `eb06823c57`);
  * pins `CSVs/` + `data/` to each input commit with `../rootcause/pin_inputs.sh`;
  * builds every board through `oiv2_gates.build`, i.e. `build_api_data_contract` with the harness's pinned flags;
  * extracts every row and vote, compares, and removes the worktree.
* **Cost:** about 65 s and about 220 MB peak RSS in total.
* **Byte-identical reruns:** a rerun reproduced every committed `.md` byte for byte. In the JSON only `buildSeconds` and `peakRssMb` differ.

| input | commit | payload sha256 | CSV + data tree listing hash |
|---|---|---|---|
| pin2015 (`dynasty_export_20261019_201546`) | `d9680440a5` | `3ef54acd…9199` | `7e1ab657e16db922` |
| pin0527 (the documented 31 / 18 / 10 / 3) | `eb10d3e12d` | `b639608f…e11c` | `11b42e600d0e27e4` |
| newest I board `dynasty_export_20261020_052241` (incumbent only) | `d9c3a70209` | `8e9b826a…198a` (= `I_INDEPENDENT.json`) | `5ab3ffdbb2d84249` |

Both pin payloads match `../manifests/R_REGRESSION_PIN.json`, and both tree hashes match the root-cause runs.

**Determinism:** on both pins, board C was built twice and gave an identical board digest and an identical full `playersArray` sha256.

## Boards (identical payload, CSVs, data, weights and configuration)

| board | DLF IDP (`dlfIdp`, `dlfRookieIdp`) | D4 (DLF Values offense vote) | per-row filter |
|---|---|---|---|
| **A** | held (production) | off | incumbent Hampel |
| **B** | restored | off | incumbent |
| **C** | restored | off | **V2** |
| **D** | held | off | **V2** (isolates the filter change) |
| B′ | held | on | incumbent |
| C′ | held | on | V2 |
| B″ | restored | on | incumbent |
| C″ | restored | on | V2 |
| Anf / Bnf / B′nf / B″nf | as A / B / B′ / B″ | | none (attribution only) |

* A′ = A and D′ = D, exactly as in prereg §6.1.
* "V2" means the primary configuration: `outlier_integrity_v2`, `identity_evidence_v2`, `payload_provenance_guard` and `rookie_ladder_fail_closed` ON; D-1 (`integrity_holds_as_withheld`) OFF.
* The no-filter boards split every move into three parts:
  1. standing the incumbent down (A → Anf);
  2. the DLF flag with no filter (Anf → Bnf, B′nf or B″nf);
  3. the filter under test (no-filter board → X).
* These three log-steps are printed per row in `MATERIAL_ROWS_*`.

## Files

| file | content |
|---|---|
| `TABLES_<pin>.md` | per-pair summary; DLF flag-added votes; the 31 regression votes; D4 set; original movers; every V2 refusal / hold; the incumbent's own drops and their fate; two-way; picks |
| `MATERIAL_ROWS_<pin>.md` | **every row with \|Δ value\| ≥ 5 % or \|Δ rank\| ≥ 25, in all 17 comparisons, with source-level attribution**: each vote whose status changed (with its value), the largest vote-value changes, and the A → no-filter → X decomposition |
| `FOCUS_<pin>.md` | full per-player source tables on all 10 boards: Trevin Wallace, Myles Garrett, Aidan Hutchinson, CJ Allen, T.J. Watt, Josiah Trotter, Will Anderson, Danielle Hunter, Jared Verse, Theo Johnson, Travis Hunter |
| `THEO_JOHNSON_I052241.md` | the owner-named D4 case on its own board (incumbent only) |
| `abcd_<pin>.json.gz` | everything machine-readable (every changed exclusion, value / confidence / coverage / family deltas by class and position, the 31-vote records with provenance, the full list of 99 restored incumbent drops) |
| `team_history.txt` | independent team evidence for the Layer A holds (finding F1) |
| `scripts/` | `run_all.sh`, extractor, analyzer, I-board renderer, team-history probe |

## Results (pin2015; pin0527 in brackets where it differs)

Every p90 is taken over all rows of the class, moved or not. "Median of moved" counts only the rows that moved.

### 1. The documented DLF failure is fixed on both pins

* **B vs A (the defect).**
  * The incumbent newly drops **31 other-source IDP votes on 30 rows**: Draft Sharks 18, FantasyPros 10, IDP Trade Calculator 3. It also drops DLF's own vote on Jared Verse.
  * IDP rows move by up to 54.4 %, with 32 rank changes of 25 or more [30].
  * The pair set is identical on both pins.
* **C vs B (V2 vs the incumbent, DLF restored).**
  * All 31 votes vote again, plus Jared Verse's DLF vote, so 32 IDP votes in all.
  * V2 makes **no Layer C drop, no B quarantine and no B4 hold** on any V2 board.
* **The 31 votes, checked one by one** (`TABLES_*` §31):
  * Retained in C 31/31, C″ 31/31 and D 31/31, on both pins.
  * Layer A grades 18 of them NAME_ONLY and lets them vote (Draft Sharks publishes no ids); 10 are VERIFIED (FantasyPros IDP). IDP Trade Calculator is value-direct and has no identity grade.
  * No Layer A CONTRADICTED verdict, no Layer B finding, no segment or source quarantine touches any of them.
  * 6 carry `kept_dissent`: Layer C saw them as legitimate disagreement, with the nearest other provider 0.76 to 1.17 away in V2's coordinate `u`. That is below the provisional τ_C = ln 6 = 1.79 and below the grid floor ln 4 = 1.39, so no registered τ_C would drop them on these panels. The frozen-panel tests also assert retention at ln 4, ln 5 and ln 6.
  * The other 25 have another provider within 2x and are not dissent at all.
  * **No new, independently verifiable evidence of invalidity was found for any of the 31.**
* **What C vs A leaves:**
  * IDP moves are DLF's own votes only. 180 of 397 rows move (median of moved 1.3 %, p90 2.8 %, max 6.7 %: Jacob Rodriguez, DLF IDP 4726 + DLF Rookie IDP 5165).
  * Each IDP row of 5 % or more is attributed to DLF's own vote in `MATERIAL_ROWS_*` ("C vs A" and "C vs D"). Its decomposition step "Anf → Bnf" carries the whole move, and the step "Bnf → C" is 0.

**Original 30 %+ movers** (pin2015; pin0527 values in `TABLES_pin0527.md`):

| row | A | B (incumbent, DLF restored) | C (V2, DLF restored) | C vs A | vote the incumbent removed in B |
|---|---|---|---|---|---|
| Trevin Wallace | 1937 | 884 (−54.4 %) | 1934 | −0.1 % | Draft Sharks 2878 |
| Myles Garrett | 3555 | 5245 (+47.5 %) | 3469 | −2.4 % | Draft Sharks 1905 |
| CJ Allen | 3987 | 2172 (−45.5 %) | 4033 | +1.1 % | Draft Sharks 5790 |
| T.J. Watt | 2394 | 3436 (+43.5 %) | 2415 | +0.9 % | Draft Sharks 1450 |
| Josiah Trotter | 2368 | 3379 (+42.7 %) | 2493 | +5.3 % | FantasyPros 1868, Draft Sharks 1675 |
| Will Anderson | 4354 | 5980 (+37.3 %) | 4407 | +1.2 % | Draft Sharks 2870 |
| Aidan Hutchinson | 4772 | 6422 (+34.6 %) | 4772 | 0.0 % | Draft Sharks 3200 |
| Danielle Hunter | 2333 | 3035 (+30.1 %) | 2309 | −1.0 % | Draft Sharks 1641 |

The remaining C vs A moves are DLF's own votes, named per row in `FOCUS_*`. For example, Josiah Trotter's +5.3 % comes from DLF IDP 3171 and DLF Rookie IDP 3283.

**The three named rows**, with full tables in `FOCUS_pin2015.md`:

* **Trevin Wallace.**
  * Votes in A: Draft Sharks 2878, FantasyPros 1558, IDP Trade Calculator 814 (IDP Show 1842 is stale, weight 0).
  * B adds DLF IDP 1517. That makes n = 4, and the incumbent drops Draft Sharks: 884, unranked.
  * V2 keeps Draft Sharks (NAME_ONLY identity, within 2x of FantasyPros, so not dissent): C 1934.
* **Myles Garrett.**
  * Votes in A: Draft Sharks 1905, FantasyPros 4726, IDP Trade Calculator 5399.
  * B adds DLF IDP 3721, and the incumbent drops Draft Sharks: 5245.
  * V2 keeps it as `kept_dissent` (nearest provider 0.76 in `u`): C 3469.
* **Aidan Hutchinson.**
  * Votes in A: Draft Sharks 3200, FantasyPros 6227, IDP Trade Calculator 6444.
  * B adds DLF IDP 6227. FantasyPros and DLF land on the identical translated value: both are priced through IDP Trade Calculator's player order (root cause item 3). The MAD collapses, and Draft Sharks is dropped: 6422.
  * V2 keeps it as `kept_dissent` (0.92): C 4772.
* In C, the confidence of all three stays `low` (agreement axis low), as in A. Disagreement lowers confidence; it removes no voting power.

### 2. The D4 addendum

* **D4 regression set, by the registered rule** (B′ vs A, DLF Values' own vote excluded):
  * **20 votes on 14 rows [13]**: Draft Sharks 5, IDP Trade Calculator 5, KTC Crowd 5, Yahoo/Boone 3, FantasyPros SF 1, FantasyPros Fitzmaurice 1.
  * Retained in C′ 20/20 and C″ 20/20 on both pins. B″ vs B gives the same 20, all retained in C″.
* **Theo Johnson (owner-named).**
  * On the pins Draft Sharks votes 3001 / 3009, and the incumbent keeps it in B′ (2186 → 2105 is DLF Values' own vote). The rule therefore does not produce him there.
  * On his own board, the newest I board, an **incumbent-only** rebuild reproduces the owner's numbers exactly: A 2184 → B′ 2023, Draft Sharks 3182 dropped, confidence medium → low (`THEO_JOHNSON_I052241.md`). With no filter (B′nf) the row is 2106.
  * That rebuild's pre-filter panel is **identical, vote for vote**, to the frozen fixture `tests/fixtures/oiv2/panel_theo_johnson_pr1817_lane.json`.
  * On that fixture Layer C keeps Draft Sharks at every τ_C grid point: `tests/api/test_oiv2_regression_set.py`, 384 passed and 2 skipped at `eb06823c57`.
  * No V2 build was run on that held-out board.
* **D4 activation impact with V2 on** (C′ vs D):
  * 302 offense rows move: p90 1.1 %, max 4.4 % (Jack Strand, DLF Values 1357). On pin0527 it is 301 rows, max 5.1 %.
  * 43 pick rows move (max 1.5 %), all current-year slots tethered to the rookie pool.
  * 16 confidence-bucket changes; 2 rows change rank by 25 or more.
  * Every row is attributed in `MATERIAL_ROWS_*` under "C′ vs D".

### 3. Every §6 item, per pair

Full table: `TABLES_<pin>.md` → "Comparison summary". Headline pairs on pin2015:

| pair | other-source exclusion changes | offense moved / max | IDP moved / max | picks moved / max | confidence changes |
|---|---|---|---|---|---|
| B vs A | 31 voting → incumbent drop | 1 / 2.9 % | 180 / 54.4 % | 39 / 7.4 % | 55 |
| C vs A | 99 incumbent drops → voting; 5 voting → V2 Layer A hold; 5 refusals of non-voting observations (2 DLF Values with D4 off, 1 contradicted, 2 stale) | 190 / 34.6 % | 180 / 6.7 % | 51 / 4.7 % | 60 |
| C vs B | 131 incumbent drops → voting; same Layer A set | 189 / 34.6 % | 31 / 118.8 % | 40 / 8.1 % | 29 |
| **D vs A** (filter only) | 99 incumbent drops → voting; same Layer A set | 189 / 34.6 % | **0** | 25 / 3.1 % | 14 |
| C vs D (DLF IDP activation under V2) | none | 1 / 2.9 % (Travis Hunter, two-way) | 180 / 6.7 % | 38 / 4.7 % | 46 |
| C″ vs A | as C vs A, plus DLF Values' own votes | 352 / 34.6 % | 180 / 6.7 % | 66 / 4.7 % | 74 |

* **Votes retained and rejected.**
  * On A the incumbent drops 99 offense votes [98] and 0 IDP votes. Every IDP row has at most 3 voters, so the filter never runs.
  * V2 drops none of them by Layer C.
  * For per-source and per-class counts on every board see `boardVoteCensus` and `votesByClassSource` in the JSON.
* **Changed exclusion reasons.** Every changed reason is listed in the JSON (`changedExclusions`) and counted in the tables. The only reasons V2 adds are Layer A identity verdicts; see F1–F3.
* **Offense.**
  * D vs A moves 189 offense rows, median of moved 0.14 %, p90 0.9 %.
  * The one row of 10 % or more is LaJohntay Wester, 648 → 872 (+34.6 % [+35.6 %]). The incumbent drops Flock 1889 on a row voted by KTC Crowd 582, KTC Trades 602 and OTC 900. That is n = 4 with KTC counted twice, so the 1,000-point floor binds. V2 keeps Flock as `kept_dissent`: it is 2.1x from the nearest provider, below τ_C.
  * **98 of the 99 incumbent offense drops have another voting provider within 2x** on board D (`TABLES_*`, last-but-two section). The exception is Wester at 2.1x. The table above is the largest-distance list.
* **IDP.** D vs A: no IDP value moves. With DLF held the filter never runs on an IDP row, so V2 alone cannot change IDP values. IDP confidence: see F5.
* **Confidence.**
  * The confidence owner (`src/api/confidence.py`) is unchanged.
  * Bucket changes in C vs A: IDP low → medium 26, medium → low 20 (DLF's added evidence); offense 14 (restored votes move the agreement axis).
  * Axis-level transitions are in the JSON.
* **Coverage and families.**
  * C vs A adds DLF family representation on 182 IDP rows: DLF IDP votes on 171 rows and DLF Rookie IDP on 29. Restored incumbent drops add offense representation, mostly Draft Sharks on 54 rows.
  * B vs A instead removes Draft Sharks from 18 rows, FantasyPros from 10 and IDP Trade Calculator from 3.
  * Weights are untouched: DLF IDP and DLF Rookie IDP share the `dlf` family cap, and DLF Values does too (D4 boards, `familyAdjustment` 0.5).
* **Two-way (Travis Hunter).**
  * The published value is the DB alt-family value in every board. A, D, B′ and C′: 3599. B, C, B″ and C″: 3493, because DLF IDP's own vote enters the alt panel.
  * The alt panel (`_two_way_alt_center`, routed through the V2 dispatcher in C) drops nothing on any board.
  * The row-level incumbent drop of IDP Trade Calculator's offense vote (3599) is restored under V2. That changes the primary offense value (2323 → 2365), not the published value.
* **Derived picks.**
  * Only current-year slot picks tethered to the merged rookie pool move: max 4.7 % in C vs A, 3.1 % in D vs A.
  * No derived far-future, derived-round or generic-grade pick moves in any comparison. Every moved pick's provenance is `rookie_pool_tether`.

### 4. Findings for the reviewer (named, not resolved here)

* **F1. Under NO-HISTORY, Layer A holds legitimate votes.**
  * Four FantasyPros Fitzmaurice votes and, on D4 boards, two DLF Values votes are held `identity_unresolved:team_only_mismatch` (category `temporarily_held_by_policy`). The FantasyPros Fitzmaurice votes are Marvin Harrison 3118, Kaytron Allen 1735, Joe Milton 1473 and Jarquez Hunter 1473; the DLF Values votes are Jarquez Hunter and Jerome Ford.
  * Each name appears once in the board's own Sleeper team map, with the same position.
  * The vendor's team is the player's **own previous team** in that map's committed git history (`team_history.txt`):

    | player | team history | vendor team |
    |---|---|---|
    | Marvin Harrison | ARI through 10-09, HOU by 10-15 | ARI |
    | Kaytron Allen | WAS, then MIA | WAS |
    | Joe Milton | DAL, then PHI after 10-15 | DAL |
    | Jarquez Hunter | MIA, then NO | MIA |
    | Jerome Ford | MIN in late September, then ARI | MIN |

  * So each is the same person, reported by a vendor that lags a roster move. This is the registered rule (C13), not evidence of invalidity. With a history lane that had recorded the vendor's matching team, C13 would release them.
  * Largest row effect: Joe Milton 1435 → 1388 (−3.3 %), also listed in `MATERIAL_ROWS_*` under the "V2 vs no-filter" pairs.
  * The genuinely ambiguous refusals are defensible from the CSVs: Flock lists "Cole Payton" twice (ranks 275 and 348), giving −3.8 %. On pin0527 only, OTC lists "Kyle Williams" at ranks 291 and 320; on pin2015 the same rank three times, which is treated as one person (C4).
  * The CONTRADICTED verdict (Draft Sharks IDP "Justin Jefferson", LB, against WR Justin Jefferson) is correct, and that observation never voted in production either.
* **F2. A Layer A refusal re-ranks the rest of the vendor's board.**
  * The refusal removes the entry before the source's dense re-rank (C9), so every entry below it moves up.
  * On pin2015 this changes 179 FantasyPros Fitzmaurice votes (median 0.6 %, max 1.4 %) and 143 Flock votes (max 0.4 %). Pin0527 adds 154 OTC votes.
  * 131 rows [183] move by this alone, max 0.5 %.
  * A held identity arguably should keep its rank slot, since the vendor still ranked someone there. This is a methodology question for the implementation owner.
* **F3. Identity verdicts are stamped on non-voting observations.**
  * DLF Values entries carry identity stamps on boards where D4 is off; IDP Show carries them although it is freshness-withheld.
  * They change no value.
  * For B11 seats see F5. The transparency layer must not present them as a source's voting state.
* **F4. V2 makes zero Layer C drops on both pins.**
  * The 99 [98] incumbent offense drops are all restored, consistent with prereg §13.
  * These boards show that legitimate opinions are preserved. They do **not** show that corrupted values are caught. That is the §7 gates' question (owned by the sibling replay lane), and an activation verdict needs both.
* **F5. IDP confidence through B11 seats.**
  * D vs A changes no IDP bucket, but it changes the reasons on 2 rows.
  * Byron Murphy: IDP Show's stale observation is now refused by identity, so it no longer seats as lost evidence.
  * Jack Campbell: the V2 lost-evidence replay now seats IDP Show as lost, where the incumbent statistic had rejected it.
* **F6. Correction to `../r_constraints/README.md`.** Its line "V2 drops on C / C′ / C″ / D (any layer) 0 / 0 / 0 / 0" counted only stamped vote exclusions. Layer A refusals are recorded in `row.sourceIntegrity` only, because the refused observation never reaches `sourceRankMeta`. The precise statement on both pins is:
  * 0 Layer C drops and 0 B quarantines or holds;
  * Layer A refusals of 5 voting observations [6], plus the 2 DLF Values observations, which vote only on D4 boards;
  * 1 CONTRADICTED non-voting observation;
  * 2 refusals of freshness-withheld observations.

## What remains (named, not resolved here)

* A re-run at Stage 3 on frozen thresholds, and with the ARRIVING history variant (O-1), which releases the F1 holds if the lane recorded continuity.
* A design decision on F2, and the transparency mapping for F3.
* No activation is implied. DLF IDP, DLF Rookie IDP, D4 and V2 stay held / off pending every §11 criterion and explicit owner approval.
