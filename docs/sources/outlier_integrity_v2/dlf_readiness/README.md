# Outlier integrity v2: DLF restoration readiness (directive §9, prereg §15)

Authority: owner directive 2026-10-20 "Fix the outlier filter and restore DLF IDP voting"
§9 and its D4 addendum; preregistration `../../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md` §15
(activation criteria) and §6.1 (boards). Owner decision 2026-10-20 (Option 3) stands: the DLF
IDP hold `dlf_offense_only_vote` stays ON and D4 (`dlf_values_rank_hill_vote`) stays OFF, in
the repository and in production.

This is a measurement. It changes no code path, flag default, constant, weight, family cap,
Hill curve, freshness policy, Package VA or trade math. The flags differ only inside the local
build process, one board at a time. Nothing here recommends activation.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Status: constraint check, not evidence

* **Code:** `766468a75a` (V2 at `eb06823c57` plus the §6 evaluation docs), clean tree.
* **Thresholds:** `provisional_stage1` (τ_C = ln 6); NO-HISTORY (B3a/B4 abstain, persistence never confirms).
* **Inputs:** the two R pins only, identical to `../evaluation/` (payload and CSV/data tree hashes in `inputs_*.sha` and each `READINESS_*.md`). These are R_REGRESSION_PIN constraint checks under deviation T1 (same boards A–D, C′, C″ as the §6 run, plus two override stress boards). Nothing here selects a threshold.
* **Held-out boards:** none read. Prereg §15 asks for the activation impact "on the newest I board"; a V2 build on an I board is Stage 4/5 only, so that table is **deferred to Stage 4/5** and must be produced there with this script at the frozen code SHA.
* **Rerun:** `scripts/run_all.sh` reproduced every committed `.md`, `.csv` and `.csv.gz` byte for byte; in the JSON only `buildSeconds` and `peakRssMb` differ.

## Reproduce

```bash
bash docs/sources/outlier_integrity_v2/dlf_readiness/scripts/run_all.sh REPO WORK_DIR OUT_DIR
```

8 sequential full builds per pin (2–4 s each, ~300 MB peak RSS), in a throwaway sparse worktree
whose `CSVs/` and `data/` are pinned with `../rootcause/pin_inputs.sh`.

| board | DLF IDP + DLF Rookie IDP | D4 (DLF Values) | per-row filter | source override |
|---|---|---|---|---|
| A | held (production) | off | incumbent | — |
| B | restored | off | incumbent | — |
| D | held | off | V2 | — |
| C | restored | off | V2 | — |
| C′ | held | on | V2 | — |
| C″ | restored | on | V2 | — |
| C_noIDPTC | restored | off | V2 | `idpTradeCalc` excluded (no rookie-ladder reference) |
| B_noIDPTC | restored | off | incumbent | same |

"V2" = the primary configuration (prereg §3.6): `outlier_integrity_v2`, `identity_evidence_v2`,
`payload_provenance_guard`, `rookie_ladder_fail_closed` ON; D-1 OFF.

## Files

| file | content |
|---|---|
| `READINESS_<pin>.md` | checks R1–R10 with every number behind each verdict |
| `IMPACT_<pin>.md` | activation impact per scenario and class, top-100/200 membership, the 15 largest movers each with attribution |
| `impact_values_<pin>.csv` | **the exact table**: every row whose value or confidence bucket changes, in every scenario, with before/after value, rank, confidence and the source-level vote changes that caused it |
| `impact_all_<pin>.csv.gz` | the same plus rank-only cascades |
| `readiness_<pin>.json` | everything machine-readable |
| `scripts/` | `oiv2_dlf_readiness.py`, `run_all.sh` |
| `../../../../tests/api/test_oiv2_dlf_readiness.py` | the board-independent half of R1 as unit tests (one family, one provider, one cap; two DLF boards can never corroborate each other or a DLF tail in Layer C) |

## Readiness checks (both pins)

| check | directive §9 question | pin2015 | pin0527 |
|---|---|---|---|
| R1 | DLF IDP and DLF Rookie IDP vote through the one `dlf` family and share its cap; never a second DLF family vote | PASS | PASS |
| R2 | correct populations | PASS | PASS |
| R3 | DLF Rookie IDP rookie-value translation (and fail-closed without its ladder) | PASS | PASS |
| R4 | DLF IDP not wrongly rejected as an outlier | PASS | PASS |
| R5 | Draft Sharks / FantasyPros / IDP Trade Calculator keep voting when valid | PASS | PASS |
| R6 | confidence reflects the added evidence | PASS | PASS |
| R7 | IDP values consistent across the board | PASS | PASS |
| R8 | two-way players correct | PASS | PASS |
| R9 | downstream pick and trade values consistent | PASS | PASS |
| R10 | D4: DLF Values votes offense only, inside the same family cap | PASS | PASS |

What each verdict rests on (pin2015; pin0527 differs only where shown in its file):

* **R1 one family, one cap.**
  * All five DLF boards (`dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp`, `dlfValuesSfTep`) map to correlation group `dlf` and provider `dynastyLeagueFootball`.
  * Board C: 58 rows carry two voting DLF boards (18 rookie IDP rows `dlfIdp + dlfRookieIdp`, 40 `dlfSf + dlfRookieSf`); board C″: 311 (adds DLF Values). On every row the DLF members' applied weights sum to at most one provider's authority (0 violations); each member keeps its own vote (e.g. Jacob Rodriguez: DLF IDP 4726 and DLF Rookie IDP 5165 at 0.5 each).
  * `independentSourceCount` equals the number of distinct voting families on every row (0 mismatches), so B11 counts DLF once.
  * Layer C asks "another provider", never "another source": the unit tests show two agreeing DLF boards form no corroborated reference against a third source, and do not protect a DLF tail.
* **R2 populations.**
  * `dlfIdp`: 175 CSV entries, 171 voting rows, all IDP (DL 78, LB 58, DB 35); 0 position disagreements with DLF's own raw export.
  * `dlfRookieIdp`: 29 entries, 29 voting rows, all IDP rookies.
  * On board A both are held: 0 votes. Layer A refuses none of them (all NAME_ONLY: the DLF CSVs publish names only).
  * The 4 `dlfIdp` entries without a row: Travis Hunter (his DLF IDP observation enters only his two-way DB alt panel, R8), and 3 rookies (Emmanuel McNeil-Warren, R Mason Thomas, Cashius Howell) that the existing self-correcting rookie rule skips because they sit in the bottom 20 % of DLF IDP's depth; all three still vote through DLF Rookie IDP. See G1.
* **R3 rookie translation.**
  * All 29 DLF Rookie IDP votes use `rookie_ladder_translation_via_idpTradeCalc`. The translated rank equals the IDPTC rookie ladder recomputed from the built board on 29 / 29, and DLF's within-class order is preserved (no inversions).
  * Stress, with `idpTradeCalc` excluded through the source-override path (no ladder reference): under V2 all 29 are withheld `normalization_untranslated`. Under the incumbent, 21 of 29 vote **untranslated** within-class ranks (class #2 Sonny Styles priced 9841, row 6163 instead of V2's 5980). See G3.
  * DLF IDP itself stays on the shared market without IDPTC (171 / 171 still `sharedMarketTranslated` through the remaining bridges; median effective-rank ratio 0.94).
* **R4 DLF not rejected.** On C and C″ every DLF IDP and DLF Rookie IDP observation votes (171 + 29); none is a Layer C drop, a Layer B quarantine, a hold or a refusal; none is even `kept_dissent`. Contrast: the incumbent on board B drops DLF IDP on Jared Verse (4671).
* **R5 the other IDP sources.**
  * C vs D (DLF added under V2) and C″ vs C′: **0** status changes for any non-DLF IDP source. Draft Sharks IDP 320, FantasyPros IDP 249, IDPTC 377 voting rows before and after.
  * C vs A: 0 votes lost; one IDP Show observation that was already freshness-withheld is now refused by Layer A (Byron Murphy, `../evaluation/` F5).
  * Contrast B vs A: the incumbent drops 31 (Draft Sharks 18, FantasyPros 10, IDPTC 3), the documented defect.
* **R6 confidence** (`src/api/confidence.py` unchanged; C vs D on IDP rows).
  * Where DLF votes (182 rows) the independent-family count rises by exactly 1 on every row.
  * Buckets there: low → medium 26, medium → low 20. Every downgrade is the agreement axis (DLF disagrees with the published value), so disagreement lowers confidence and removes no voting power.
  * Where DLF is silent: 0 bucket changes, but see G2 (coverage axis).
* **R7 consistency.** On A, D, C, C′ and C″: 0 structural contract errors; ranks contiguous with 0 value inversions (whole board and IDP); DLF translations order-preserving; 0 values outside 1–9999; 0 blend-integrity violations; IDP quarantine count unchanged (10). Source-health errors identical on every board.
* **R8 two-way (Travis Hunter).** The published value is the DB alt-family value on every board: A 3599 → C 3493 (−2.9 %), because DLF IDP's own DB vote enters the alt panel (`_two_way_alt_center`), as the `dlf` family's one vote. V2 drops nothing in the alt panel. His offense (primary) value moves only through V2 (2323 → 2365) and D4 (→ 2331); it is not published.
* **R9 downstream.**
  * Picks: 51 move in C vs A, every one `rookie_pool_tether` (current-year slots tethered to the merged rookie pool). No derived far-future, derived-round or generic-grade pick moves.
  * Trades: `finder.board_values_from_contract` (the one value every trade engine reads) equals the canonical `rankDerivedValue` on every row of both boards; all 421 changed trade assets are explained by a canonical row change.
  * Three sample packages re-priced through `suggestions._va_gap` (the active geom_q078_v1 Value Adjustment) show the only changed input is the canonical value, e.g. Myles Garrett for T.J. Watt + Danielle Hunter: adjusted gap −659 → −747.
* **R10 D4.** DLF Values votes on 317 offense rows only (QB 54, RB 89, TE 46, WR 128), 0 on A and C, never on picks (`dlfValuesSfTepPicks` never votes), shares the `dlf` cap (R1). Two legitimate votes are Layer A holds under NO-HISTORY (Jarquez Hunter, Jerome Ford: vendor team lags a roster move, `../evaluation/` F1). See G5.

## Exact expected activation impact

Exact for these two frozen inputs, from production (board A). Every row with its attribution is
in `impact_values_<pin>.csv`. Cell = rows whose value moves / max |Δ| / rows ≥ 5 % / rank changes ≥ 25 / confidence-bucket changes.

| scenario | boards | pin | offense (488 priced) | IDP (397 priced) | picks (120 priced) |
|---|---|---|---|---|---|
| S1 V2 only | D vs A | pin2015 | 189 / 34.6 % / 2 / 4 / 14 | 0 | 25 / 3.1 % / 0 / 0 / 0 |
| | | pin0527 | 240 / 35.6 % / 2 / 3 / 16 | 0 | 33 / 2.8 % / 0 / 0 / 0 |
| **S2 V2 + DLF IDP + DLF Rookie IDP** | **C vs A** | pin2015 | 190 / 34.6 % / 2 / 5 / 14 | **180 / 6.7 % / 8 / 13 / 46** | 51 / 4.7 % / 0 / 0 / 0 |
| | | pin0527 | 241 / 35.6 % / 2 / 1 / 16 | **179 / 6.7 % / 8 / 10 / 47** | 53 / 3.8 % / 0 / 0 / 0 |
| S3 V2 + D4 | C′ vs A | pin2015 | 351 / 34.6 % / 3 / 6 / 28 | 0 | 50 / 4.1 % / 0 / 0 / 0 |
| | | pin0527 | 394 / 35.6 % / 3 / 7 / 28 | 0 | 54 / 4.2 % / 0 / 0 / 0 |
| S4 everything | C″ vs A | pin2015 | 352 / 34.6 % / 3 / 6 / 28 | 180 / 6.7 % / 8 / 13 / 46 | 66 / 4.7 % / 0 / 0 / 0 |
| | | pin0527 | 395 / 35.6 % / 3 / 6 / 28 | 179 / 6.7 % / 8 / 10 / 47 | 69 / 4.2 % / 0 / 0 / 0 |
| I1 DLF IDP given V2 | C vs D | pin2015 | 1 / 2.9 % (Travis Hunter) | 180 / 6.7 % / 8 / 13 / 46 | 38 / 4.7 % / 0 / 0 / 0 |
| | | pin0527 | 1 / 2.9 % (Travis Hunter) | 179 / 6.7 % / 8 / 10 / 47 | 38 / 3.8 % / 0 / 0 / 0 |
| I2 D4 given V2 | C′ vs D | pin2015 | 302 / 4.4 % / 0 / 2 / 16 | 0 | 43 / 1.5 % / 0 / 0 / 0 |
| | | pin0527 | 301 / 5.1 % / 1 / 3 / 14 | 0 | 39 / 1.3 % / 0 / 0 / 0 |

Reading it:

* **DLF IDP + DLF Rookie IDP** (I1, pin2015): IDP moves are DLF's own two votes and nothing else (R5: no other vote changes status). Median |Δ| of moved 1.3 %, p90 4.0 %, max +6.7 % (Jacob Rodriguez 4624 → 4932, DLF IDP 4726 + DLF Rookie IDP 5165, confidence low → medium); 100 up, 80 down. Top-100: Makai Lemon in, Fred Warner out. The one offense row is Travis Hunter (R8). Picks move only through the rookie tether.
* **V2 itself** (S1): all the offense moves of S2 come from V2 restoring 99 offense votes the incumbent drops (largest: LaJohntay Wester +34.6 %, Flock 1889 restored; attributed row by row in `../evaluation/`). V2 alone moves no IDP value.
* **D4** (I2): 302 offense rows, max 4.4 % (Jack Strand, DLF Values' own vote), 16 confidence changes; no IDP effect.
* These numbers agree with the independent §6 run in `../evaluation/` (C vs A IDP 180 rows max 6.7 %; C′ vs D 302 rows max 4.4 %).

## Findings (named, not resolved here)

* **G1. Stale registry declaration.** `dlfIdp` is declared `excludes_rookies: True` and depth 185, but DLF's IDP board now lists rookies: DLF IDP votes on 18 rookie rows, where it shares the `dlf` cap with DLF Rookie IDP (R1, correct). The declaration still drives `_expected_sources_for_position` and the bottom-20 % rookie skip that drops 3 rookie entries (R2). Value effect is bounded by the cap (those 3 still vote through DLF Rookie IDP). Correcting the declaration is a source-configuration change for its owner, not part of this lane.
  * *Note (2026-10-27, after measurement).* G2-D3 (#2001, live) corrected `excludes_rookies` to False for `dlfIdp`, which also switched off the bottom-20 % rookie skip this readiness evidence assumed (R2 / the 3 skipped rookies above). The draft PR `claude/hold-deep-tail-rookie-rule` [HOLD — owner decision] moves the skip onto its own registry field, `drop_deep_tail_rookies` (True for `dlfIdp` / `fantasyProsIdp`): if it merges, this document's assumption holds again; if it is closed, those 3 rookies' `dlfIdp` entries also vote once DLF IDP is released, and R2's counts are re-measured.
* **G2. Coverage axis on rows DLF does not cover.** B11 eligibility ignores a board's depth, so once DLF IDP is active it is an eligible-but-silent family on 215 IDP rows. Their coverage share falls (axis transitions high → medium 75, medium → low 69) with **0 bucket changes on both pins**, because another axis is already the bottleneck. This is the canonical owner's existing rule, applied to every IDP source alike. A depth-aware eligibility would be a distinct, separately evaluated confidence change (directive §2 Layer D).
* **G3. Activation order.** DLF IDP must not be restored without V2's B1 (`rookie_ladder_fail_closed`, owner-reserved O-4). Under the incumbent, any board without the IDPTC rookie-ladder reference (a user source override, or IDPTC absent from a build) lets 21 of 29 DLF Rookie IDP votes price within-class ranks as overall ranks (R3 stress; the historical H1 mechanism). If the owner approves, `rookie_ladder_fail_closed` should be on before, or together with, `dlf_offense_only_vote` OFF.
* **G4. Two-way.** Travis Hunter's published value moves −2.9 % on activation, entirely from DLF IDP's DB alt-panel vote (R8). Correct by construction, but it is the only offense-published row DLF IDP touches, so it should be called out to the owner.
* **G5. NO-HISTORY understates D4.** Two legitimate DLF Values votes are held by Layer A (C13) without a history lane; the ARRIVING variant (O-1) would release them if the lane recorded the vendor's matching team. The D4 impact here omits those two votes.
* **G6. Input-specific numbers.** The production board refreshes about every two hours. Activation-day numbers will differ; these tables fix the mechanism and the magnitude on frozen inputs. Stage 4/5 must regenerate them on the newest I board at the frozen SHA (prereg §15).

## Verdict for directive §9

Every DLF-specific readiness check (R1–R10) passes on both R pins under the provisional
thresholds. That is **necessary, not sufficient**: activation of DLF IDP, DLF Rookie IDP or D4
also requires the V2 verdict READY FOR APPROVAL (every prereg §11 criterion, including the §7
gates, the held-out Stage 4/5 runs, criterion 11 performance, the shadow window and the
independent review), a Stage 3 re-run of this report on the frozen thresholds, the I-board
impact table, and the owner's explicit approval. None of these exists yet. The holds stay as
they are.
