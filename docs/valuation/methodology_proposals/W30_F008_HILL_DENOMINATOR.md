# W30-F008 — Hill fit vs serve percentile denominator: methodology proposal

**Activation status: NOT ACTIVATED.** Research only. Nothing on a served path changed: no
file under `src/`, `config/`, `config/model_registry/` or the live Hill constants was edited,
and no feature flag was touched. The Hill constants move only through
`scripts/model_registry.py promote` + `apply`, run by a human (ADR-008 in
`docs/roster-trade-intelligence/DECISIONS.md`), and automatic promotion stays blocked by
gate 7 (`no_independent_validation_target`, `docs/valuation/HILL_AUTOPILOT_V2.md`).

Authority: `docs/owner/SESSION_RESUMPTION_DIRECTIVE_2026-11-07.md` §3 (investigation,
correction proposals, independent testing and comparative evaluation authorized; changing
production formulas, weights, thresholds or activation flags not authorized);
`docs/EXECUTION_PLAN.md` line 13 and intake MD-59 list W30-F008 as research / preparation
only.

| | |
|---|---|
| Finding | W30-F008 (P1, `docs/master-site-audit/findings.json`; open in `closure.json` and the 2026-11-06 recount) |
| Script | `scripts/research/w30_f008_hill_denominator.py` |
| Evidence | `docs/valuation/methodology_proposals/evidence/w30_f008_hill_denominator.json` (deterministic; re-run reproduces it byte for byte apart from `treeRevision`) |
| Test | `tests/scripts/test_w30_f008_hill_denominator_research.py` (8 tests) |
| Tree | `d7db52a43b8c96a7c44e2d62a24cb70c9114c37a` (origin/main when the work started) |

---

## 1. Summary

1. **The code defect the audit described is already fixed on main.** Fitting, holdout
   scoring and serving all call one coordinate function, `rank_to_percentile`, with
   `PERCENTILE_REFERENCE_N = 500` (`p = (rank − 1) / 499`) and one tail policy. An
   independent exact oracle agrees with production at every edge rank: 0 integer
   mismatches, largest float difference 1.8e-12.
2. **The served constants still carry the defect.** Champion v2 (OFFENSE `c = 0.110,
   s = 1.110`; GLOBAL `0.112 / 0.725`; IDP `0.083 / 1.110`) was fitted before the fix, in a
   coordinate that divided by each source's own truncated length (399, 325, 293, 298 or 141).
   I re-implemented that fitter independently and ran it on the exact input files of the
   commit that produced v2 (`3df9cc4`). It reproduces all three v2 masters exactly. Changing
   only the coordinate gives **C0**: OFFENSE `0.077 / 1.110`, GLOBAL `0.088 / 0.720`, IDP
   `0.024 / 1.150`. C0 is the curve v2 would have been without the defect. Against C0 the
   served OFFENSE curve is **+22.8 % at rank 50, +32.0 % at 100 and +43.7 % at 400**, and
   GLOBAL is +9.1 % / +11.2 % / +14.4 %. The audit's own figures (+13.2 / +18.5 / +25.4 %)
   assumed one denominator of 399; three of the six OFFENSE trainers were shallower than
   that, so those figures understate the gap.
3. **On curve shape, C0 is much better.** Scored on three markets the fit never read
   (FantasyCalc, OTCFFB, PFKDynasty), C0 beats the incumbent on **102 of 102 days** of
   committed history after its 2026-07-28 fit date. The median gap is −457 points, from
   about 1,000–1,150 down to about 550–630. Both curves are fixed by July 28 information, so
   no later board can leak into either.
4. **Installed into today's blend, C0 makes the board worse, so it must not be activated on
   its own.** On the pinned 2026-11-07 board:
   - the outlier filter starts throwing out real market votes. Offense rows with a
     discarded KTC Crowd, KTC Trades or IDPTC vote go from **14 to 186**;
   - offense ordering against later markets gets worse in **23 of 23** forward
     (date × market) pairs. The measured targets are biased in opposite directions, and C0
     loses against both;
   - high-confidence rows fall from **134 to 75**;
   - the offense/IDP balance moves about 18–26 % away from IDPTC's own exchange rate (ranks 101–600);
   - 2027 slotted R1 picks drop below 2028 R1s: the 2027/2028 R1 ratio goes from 1.068 to
     0.941.

   The incumbent's inflation is load-bearing. It happens to keep rank votes on roughly the
   same scale as the value-direct votes, and the blend needs that.
5. **The open question is what scale the translation curve should target, not which
   denominator to use.** The current fitter targets the average shape of six value boards
   (call it framing A). The blend instead needs rank votes on the scale of the value-direct
   voters (framing B). A diagnostic framing-B curve, **C_vd** (canonical-coordinate fit to
   the v2-era value-direct voters: OFFENSE `0.115 / 0.945`, GLOBAL `0.149 / 0.780`), keeps
   the incumbent's ordering quality (mean Spearman difference −0.002). It restores vote
   coherence: the rank/value-direct ratio is about 1.0, value-direct drops stay at 14, and
   high-confidence rows rise to 221. But it scores worse than the incumbent on the holdout
   (1,410 against 1,145). **No candidate wins on both measures.**
6. **The routine Hill refit is pointed at framing A.** The newest challenger, v302 (OFFENSE
   `0.064 / 1.095`), would discard value-direct votes on **275** offense rows. It also fails
   two or three of the Autopilot's own board-impact bounds. The board-impact gate is the only
   thing between the Autopilot and that outcome once gate 7 opens.

**Recommendation:** keep v2 served, unchanged. Close the code half of W30-F008 as verified.
Re-scope the open half as an owner methodology decision about the translation scale, and
approve an **offline** shadow evaluation of C0 and C_vd (§16). Owner decisions requested: §17.

---

## 2. Controlling requirement — which denominator is canonical, and why

The requirement comes from three recorded places, and they agree:

- **CLAUDE.md, "Live Value Pipeline" step 2:** percentiles are taken against a FIXED
  500-rank combined-pool reference, owned by
  `src/canonical/player_valuation.py::PERCENTILE_REFERENCE_N`. The formula is
  `p = (rank − 1) / 499`. "500 is the coordinate UNIT, not the tail boundary." Ranks past
  500 keep resolving (`p > 1`) up to `src/canonical/tail_policy.py::TAIL_SATURATION_RANK =
  904`.
- **The coordinate contract** at `src/canonical/player_valuation.py:110-150`. There is one
  owner for rank → percentile. Fitting, holdout evaluation and serving all consume it, and
  none may rebuild the equation locally. *Truncation (`FIT_TOP_N`) selects which
  observations take part. It does not redefine the universe.* The same comment rejects
  "serve at 399/369 to match the fits": that would make each scope consistent with itself
  but incompatible with the others.
- **B1.2** (`docs/master-site-audit/evidence/W30/B1_2_COORDINATE_TAIL_GOVERNANCE_EVIDENCE.md`
  §1–2) proved that N is a **unit, not a model parameter**:
  `V = 9999 / (1 + ((r − 1)/M)^s)` with `M = c·(N − 1)`. Refitting the same data under a
  different N rescales `c` and leaves the curve unchanged. Any N is admissible as long as
  fit, holdout and serve use the same one. 500 is canonical because serving already used
  it, because it is aligned to KTC's 500-row board, and because the tail policy and
  `hillCurves.referenceN` are expressed in it.

**So the controlling requirement is "one coordinate, shared by fit, holdout and serve", not
"the number 500".** The audit's own required repair was "fit at 500, or serve at 400, plus a
test tying the constants together". Serving at 400 was rejected (it breaks
`test_ktc_reconciliation.py` 9 of 13, `FORMULA_INVENTORY.md` §9.14 row 2), and B1 chose "fit at
500". B4 has not changed the coordinate since the audit. It changed only where the tail
saturates (W30-F023), and did so through the same tail-policy owner on all four paths.

## 3. Current implementation on main (verified, not assumed)

| step | file:line | formula |
|---|---|---|
| reference unit | `src/canonical/player_valuation.py:150` | `PERCENTILE_REFERENCE_N = 500` |
| coordinate | `player_valuation.py:153-175` | `p = (rank − 1)/(N − 1)`, then `clamp_percentile` |
| training coordinates | `player_valuation.py:178-185` | row *i* (0-based) → `rank_to_percentile(i + 1)`; independent of list length |
| tail policy | `src/canonical/tail_policy.py:130, 133-161` | `TAIL_SATURATION_RANK = 904`; `p_max = 903/499 = 1.8096`; `clamp(p, 0, p_max)` |
| curve | `player_valuation.py:454-500` | `V(p) = 9999 / (1 + (p/c)^s)`, `p = 0 → 9999`, rounded half-even, bounded [1, 9999] |
| served constants | `player_valuation.py:201-217` | OFFENSE 0.1100/1.110, GLOBAL 0.1120/0.725, IDP 0.0830/1.110 (= registry champion v2) |
| curve routing | `src/canonical/rank_coordinates.py:97-101, 138-151` | pool `offense` → OFFENSE, `shared_market` → GLOBAL, `idp` → IDP |
| serving | `src/api/data_contract.py:13606-13612`, `11779-11805` | `rank_to_percentile(eff_rank, reference_n=500)` then `percentile_to_value` |
| fit | `scripts/fit_hill_curve_percentile.py:211-236` | `training_percentiles(len(values))` over the top `FIT_TOP_N = 400` (`src/model_registry/training_manifest.py:108`) |
| holdout | `src/model_registry/holdout.py:158-198` | same `training_percentiles`, same clamp owner |

The audit's code references (`holdout.py:81-85, 145`, `data_contract.py:5297-5303`) predate
B1. The fit-vs-serve mismatch they describe no longer exists in code. **What remains is in
the constants.** Champion v2 (`fittedAt 2026-07-28T09:08Z`, `producer
scripts/fit_hill_curve_percentile.py @ 3df9cc4`, promoted 2026-07-29, `appliedAt null`) was
produced by the pre-B1 fitter, which used `p = i/(n − 1)` over each source's own truncated
list. Those constants are served today in the canonical coordinate.

Two incidental observations (reported, not fixed: `src/` is out of scope):
- the `percentile_to_value` docstring (`player_valuation.py:463-468`) still says "ranks past
  500 clamp to p=1.0". That has been false since B4. CLAUDE.md step 2 and the code are
  correct.
- **the IDP master prices nothing on the served board.** Every rank-Hill vote on the pinned
  board lands in pool `offense` (4,239) or `shared_market` (1,622); none lands in `idp`. Nine
  archives sampled from 2026-07-14 to 2026-11-07, replayed through current code, show the
  same. Since B2 (W02-F001), IDP rank votes are priced on the GLOBAL curve. The IDP
  constants still reach the `hillCurves` stamp, the frontend explorer, and two default-OFF
  paths: the `outlier_disagreement_policy` (`src/api/outlier_policy.py:350-357`) and the
  `rank_space_hampel_challenger`.

## 4. Prior evidence

| record | what it established | status today |
|---|---|---|
| audit W30-F008 + verifier (`findings.json`) | train/serve skew; verifier refit under the serve denominator gave `0.075/1.10`, shipped curve 24.7–41.9 % above it | upheld; matches C0 (§6) |
| B1 (`evidence/W30/B1_CHALLENGER_EVIDENCE.md`) | coordinate repaired in code; challenger `0.077/1.11`, `0.089/0.72`, `0.038/0.87` on 2026-08-10 inputs; holdout 1160 → 671; **not promoted** | repair still live; C0 reproduces the OFFENSE/GLOBAL challenger from July 28 inputs |
| B1.1 | IDP master incoherent (sources disagree ~6×); OFFENSE-only promotion churns more; dropping KTC improves holdout | consistent with §8 |
| B1.2 | N is a unit; the clamp is the model; `.068` is holdout-selected, not validated; "time split blocked: holdout boards in 0/140 archives" | **the time-split blocker is superseded**: the holdout CSVs are tracked in git (`CSVs/site_raw/`, 755 / 142 / 56 committed versions), which is what §12.1 uses |
| B4 / B4F | tail saturates at 904 through one owner on all four paths | verified by the oracle (§7) |
| hill-alignment 2026-10-01 E3 | KTC trained with pick rows inside its top 400 | v2 was fitted that way; the C0 reproduction keeps v2's own population so only the coordinate changes |
| Autopilot (`config/model_registry/hill_autopilot_runs.jsonl`, last 2026-11-07) | champion criterion 1144.78 vs challenger v302 511.57 in the canonical coordinate; HOLD (forward persistence; gate 7) | reproduced exactly (§12.1) |

## 5. Defect evidence — exact reproduction of the champion

The v2 fitter is `git show 3df9cc4:scripts/fit_hill_curve_percentile.py`, and its inputs are
the blobs of that commit. Its child `ebc47fd8ed` recorded v2 as a challenger 30 minutes
later. I re-implemented the procedure (same grid and refinement, same first-minimum tie
rule, same unweighted master grid) and fed it those blobs:

| scope | native coordinate (v2's) | registry v2 | canonical coordinate (C0) |
|---|---|---|---|
| OFFENSE | **0.110 / 1.110** (rmse 28.0) | 0.110 / 1.110 | **0.077 / 1.110** |
| GLOBAL | **0.112 / 0.725** | 0.112 / 0.725 | **0.088 / 0.720** |
| IDP | **0.083 / 1.110** (rmse 0.0) | 0.083 / 1.110 | **0.024 / 1.150** |

Per source, the correction is exactly the unit transform `c_canonical = c_native·(n − 1)/499`,
within one grid step (max abs error 0.001):

| source | rows | native c | canonical c | predicted |
|---|---|---|---|---|
| KTC | 400 | 0.144 | 0.115 | 0.1151 |
| DynastyDaddy | 326 | 0.099 | 0.065 | 0.0645 |
| DynastyNerds | 294 | 0.096 | 0.057 | 0.0564 |
| YahooBoone | 400 | 0.095 | 0.076 | 0.0760 |
| Fitzmaurice | 299 | 0.206 | 0.123 | 0.1230 |
| DraftSharks | 400 | 0.064 | 0.051 | 0.0512 |
| IDPTradeCalc (GLOBAL) | 400 | 0.187 | 0.149 | 0.1495 |
| DraftSharks-Combined (GLOBAL) | 400 | 0.065 | 0.051 | 0.0520 |
| DraftSharks-IDP (IDP) | 142 | 0.083 | 0.024 | 0.0235 |

The **master** is not a single rescale, because it averages curves stretched by different
factors. That is why the audit's scalar `0.11 × 399/499 = 0.088` (candidate T) under-corrects
OFFENSE.

**New finding:** the v2 IDP master is **DraftSharks-IDP alone, 142 rows** (master rmse 0.0).
IDPTC's IDP slice of the v2 snapshot (`exports/latest/dynasty_data_2026-07-28.json` at
`3df9cc4`) was empty: none of its 281 IDP players carried an `idpTradeCalc` value. In the
native coordinate those 142 rows were stretched over the whole universe (`p = 1` at row
142). In the canonical one they cover `p ≤ 0.283`. Because the IDP master is not routed
(§3), this has no served effect today.

## 6. Served skew (incumbent vs corrected curve, fixed ranks)

`V` from the canonical coordinate; percentages are incumbent over candidate.

| rank | OFFENSE inc | OFFENSE C0 | inc/C0 | OFFENSE T | inc/T | GLOBAL inc | GLOBAL C0 | inc/C0 |
|---|---|---|---|---|---|---|---|---|
| 10 | 8814 | 8335 | +5.8 % | 8530 | +3.3 % | 7898 | 7578 | +4.2 % |
| 25 | 7146 | 6276 | +13.9 % | 6616 | +8.0 % | 6485 | 6070 | +6.8 % |
| 50 | 5314 | 4329 | **+22.8 %** | 4696 | +13.2 % | 5238 | 4802 | +9.1 % |
| 100 | 3419 | 2591 | **+32.0 %** | 2885 | +18.5 % | 3978 | 3577 | +11.2 % |
| 200 | 1931 | 1388 | +39.2 % | 1574 | +22.7 % | 2848 | 2520 | +13.0 % |
| 400 | 996 | 693 | **+43.7 %** | 795 | +25.3 % | 1939 | 1695 | +14.4 % |
| 500 | 794 | 549 | +44.7 % | 631 | +25.9 % | 1698 | 1480 | +14.7 % |
| 904 | 428 | 292 | +46.5 % | 337 | +26.9 % | 1174 | 1018 | +15.3 % |

Rank-space midpoint `M = c·499`: OFFENSE 54.9 → 38.4; GLOBAL 55.9 → 43.9. The T columns
reproduce the audit's numbers exactly (+13.2 / +18.5 / +25.3 %), and C0 reproduces the
verifier's 24.7–41.9 % range.

## 7. Independent oracle, edge cases and numerical stability

The oracle (`oracle_percentile`, `oracle_value`, `oracle_rank_form`) shares no code with
production. It uses `fractions.Fraction` for `p` and 60-digit `decimal` for `ln`/`exp`, and
it restates the documented constants (N = 500, tail 904) and asserts that production
equals them. It was run over 21 ranks × 3 scopes × 7 curves.

- **Coordinate:** max |oracle − `rank_to_percentile`| = **0** (exact).
- **Value:** max |oracle − production float| = **1.8e-12**; integer mismatches after
  half-even rounding = **0**.
- **Unit identity:** percentile form vs rank form with `M = c·(N − 1)` differ by **1.3e-56**.

Edge cases, measured on the production functions (incumbent and C0, every scope):

| case | result |
|---|---|
| rank 1 | `p = 0` → **9999** (short-circuit, no `0^s`) |
| rank 0.5 / below 1 | `p` clamps to 0 → 9999 |
| fractional ranks (Candidate F tie means) | priced as-is; oracle agrees |
| rank 500 vs 501 | `p = 1` exactly vs `500/499`; values **differ** (794 vs 793 OFFENSE): 500 is no longer a clamp |
| ranks 501–904 | `p ∈ (1, 1.8096]`, strictly decreasing raw value at every integer rank |
| rank 905+ | saturates: `V(905) = V(904) = V(1200)` (OFFENSE 428, GLOBAL 1174, IDP 316) |
| `p > 1` stability | largest base `p/c` is 1.8096/0.024 = 75 (C0-IDP); `75^1.15` ≈ 143; no overflow, no denormals, derivative finite |
| display floor | minimum served value ≥ 69 for every candidate, so `DISPLAY_SCALE_MIN = 1` never binds |
| integer resolution | C0-IDP's deep values (69–135) tie after rounding (rank 500 = 501 = 135); not routed, so no effect |

## 8. Candidates

All candidates use the canonical coordinate and tail. Only the `(c, s)` pairs differ.

| id | OFFENSE | GLOBAL | IDP | meaning |
|---|---|---|---|---|
| **incumbent** (v2) | 0.110 / 1.110 | 0.112 / 0.725 | 0.083 / 1.110 | native-coordinate fit served in the canonical coordinate |
| **C0** | 0.077 / 1.110 | 0.088 / 0.720 | 0.024 / 1.150 | the v2 procedure on v2's own inputs, coordinate corrected; framing A (consensus shape); no new data or method |
| **T** | 0.0878 / 1.110 | 0.0896 / 0.725 | 0.0614 / 1.110 | the audit's closed-form scalar (`c·399/499`, IDP `c·369/499`); assumes depths v2 did not have |
| **C_vd** (diagnostic) | 0.115 / 0.945 | 0.149 / 0.780 | (incumbent) | framing B: canonical fit to the v2-era value-direct voters (`ktcSfTep` players-only and IDPTC's offense slice for OFFENSE; IDPTC for GLOBAL) |
| R302 (reference) | 0.064 / 1.095 | 0.056 / 0.705 | 0.038 / 0.835 | newest routine challenger (2026-11-07 inputs, today's fitter), read-only from the registry; `_offense_only` = what the Autopilot would compose |

C0 and `C0_offense_global` (IDP held at the incumbent) produce **identical boards**, because
the IDP master is not routed. Every board figure for C0 below therefore covers both.

## 9. Independently computed expected results (oracle, C0)

| rank | p (exact) | OFFENSE V | GLOBAL V |
|---|---|---|---|
| 1 | 0 | 9999 | 9999 |
| 50 | 49/499 | 4328.9 | 4802.3 |
| 100 | 99/499 | 2590.9 | 3576.8 |
| 500 | 1 | 548.8 | 1480.4 |
| 904 | 903/499 | 291.9 | 1018.3 |
| 905 | 903/499 (clamped) | 291.9 | 1018.3 |

The full table (all candidates, 21 ranks, exact `p` as a fraction) is in the evidence JSON
under `oracle.table`.

## 10. Before/after player impacts (pinned board)

Pinned input: `exports/archive/dynasty_export_20261107_063955.zip`, sha256
`f1ad8517f83008d44c7de1a942626115798d12a4ebdd629887b9ae225157fb60`. Each candidate is
installed in-process only and restored afterwards. The test asserts the restore. The
incumbent rebuild is byte-identical to the plain build (`incumbentRebuildEqualsPlainBuild:
true`). The board has 1,103 rows, 1,010 of them priced on both sides, and 864 carry at least
one rank-Hill vote.

| | C0 | T | C_vd | R302 offense-only | R302 all |
|---|---|---|---|---|---|
| rows value changed | 904 | 904 | 904 | 553 | 904 |
| rows rising / falling | 0 / 904 | 0 / 904 | 861 / 43 | 0 / 553 | 0 / 904 |
| median abs % value change | 12.9 % | 8.4 % | 4.4 % | 15.4 % | 22.4 % |
| p90 / max abs % | 26.8 / 36.6 % | 17.2 / 24.3 % | 25.5 / 42.1 % | 39.5 / 46.3 % | 39.0 / 45.8 % |
| rows reordered (of ranked) | 687 / 705 | 704 / 726 | 691 / 721 | 661 / 671 | 676 / 686 |
| median / p90 / max abs rank shift | 55 / 109 / 155 | 27 / 69 / 131 | 38 / 85 / 136 | 96 / 170 / 237 | 79 / 147 / 229 |
| top-25 / top-100 overlap | 24 / 89 | 25 / 95 | 25 / 97 | 24 / 83 | 24 / 86 |
| Autopilot board-impact bounds failed | median rank shift | none | median rank shift | median rank shift, p90 rank shift, top-100 | median rank shift, p90 rank shift |
| offense rows with a dropped value-direct vote (incumbent 14) | **186** | 78 | 14 | **274** | **275** |
| blend-integrity violations | 0 | 0 | 0 | 0 | 0 |

Rows priced only value-direct do not move, with one family of exceptions: the **48 changed
"value-direct-only" rows are all 2027 slot picks** (`pickValueProvenance.class =
rookie_pool_tether`). They inherit rookie player values, which are rank-Hill heavy.

Largest C0 movers among the top 300 are all offense, falling: Malachi Fields WR 2406 → 1648
(rank 249 → 359), Michael Mayer TE 2943 → 2028 (193 → 246), Colby Parkinson TE 2097 → 1446,
Darnell Washington TE 2248 → 1562, Tre Tucker WR 2499 → 1740. The largest rank movers are
deep offense, for example Zachariah Branch 362 → 513 and Cade Klubnik 512 → 657.

**Outlier-filter mechanism.** `_HAMPEL_K = 2.75` with a 1,000-point floor
(`data_contract.py:325-340`) operates in value space, and its floor was tuned in April 2026 on the values of
pre-repair (native-coordinate) curves. C0 deflates rank votes by 13–44 % while KTC Crowd, KTC Trades and IDPTC
keep their native scale. Those three real markets then fall outside the band and are
discarded: KTC Trades on 116 offense rows, IDPTC on 95, KTC Crowd on 82. Under the
incumbent the counts are 2, 12 and 4. The same pattern holds on every forward date (C0
146–192 rows against the incumbent's 11–28). This is the main reason C0 cannot be activated
on its own. It changes who votes, not just how much each vote is worth, and "agreement
between different providers is consensus" (CLAUDE.md governance invariants).

## 11. Position and league-format impacts

Median value change and median rank shift per position (positive shift = moves up):

| pos | C0 % | C0 shift | T % | C_vd % | C_vd shift |
|---|---|---|---|---|---|
| QB | −24.8 | −33.5 | −15.3 | +15.9 | +12.5 |
| RB | −24.9 | −47 | −16.0 | +17.4 | +14 |
| WR | −24.3 | −44 | −15.8 | +19.9 | +17 |
| TE | −21.6 | −33 | −13.7 | +17.3 | +24 |
| DL | −3.0 | +62 | −3.0 | +2.2 | −67 |
| LB | −2.9 | +57 | −2.9 | +2.4 | −44 |
| DB | −3.8 | +80 | −3.8 | +2.5 | −68 |
| PICK | −8.4 | +50.5 | −4.7 | +4.4 | −36.5 |

- **Offense vs IDP balance.** IDP rows are anchored on IDPTC with α = 0.10 shrinkage
  (CLAUDE.md step 6), while offense takes a flat mean-median that is mostly rank votes. A
  curve-level change therefore moves offense and barely moves IDP. Relative to IDPTC's own
  value for the same row (IDPTC prices both on one scale), the board's offense/IDP ratio in
  ranks 101–300 is **0.898** under the incumbent, **0.735** under C0 and **1.014** under
  C_vd. In ranks 301–600 it is 0.868 / 0.641 / 1.113. C0 moves the exchange rate about
  18–26 % away from IDPTC's. IDPTC votes on both populations, so this is a coherence
  diagnostic, not truth.
- **Superflex.** QB moves with the rest of offense (no QB-specific term). No Superflex rule
  changes.
- **TE premium.** TE falls slightly less than WR under C0 (−21.6 vs −24.3 %). The TE basis
  conversion's uplift rises as values fall (1.209 at the top towards 2.05). That is an
  interaction, not a TE rule change.
- **Leagues.** There is one board per scoring profile. Both live leagues carry the
  `superflex_tep15_ppr1` label and the curve has no league dimension. `dynasty_main` (in
  scope; 3 DL / 3 LB / 3 DB starters, 2 TE, SF) feels the offense/IDP shift directly.
  `dynasty_new` (no IDP) sees only the offense re-pricing.
- **Picks.** Only the slotted 2027 class (rookie-pool tether) moves. 2028/2029 vendor-priced
  and derived picks do not. The mean 2027 R1 slot divided by the mean 2028 R1 tier is
  **1.068** under the incumbent, **0.941** under C0 and **1.094** under C_vd; for R2 it is
  1.119 / 0.932 / 1.200. Under C0 a nearer first would be worth less than a later one. That
  contradicts the term premium the vendor-priced years encode (CLAUDE.md, T-3/C-2).

## 12. Historical predictive evaluation

### 12.1 Curve shape, forward in time (look-ahead free)

The incumbent, C0 and T are all functions of 2026-07-28 information. C_vd is too: it was
fitted on `3df9cc4` blobs. For every day from 2026-07-29 to 2026-11-07, each candidate's
OFFENSE curve was scored on the holdout CSVs committed by the end of that day (FantasyCalc,
OTCFFB, PFKDynasty). Scoring uses the canonical coordinate, the top 400 rows, and
normalisation to top = 9999. The score is the mean per-board RMSE, the production criterion,
cross-checked against `evaluate_offense_master` to within 0.01.

| month | days | incumbent | C0 | T | C_vd |
|---|---|---|---|---|---|
| 2026-07 | 3 | 1002.8 | 548.9 | 664.8 | 1295.7 |
| 2026-08 | 31 | 1041.4 | 587.9 | 704.0 | 1330.7 |
| 2026-09 | 30 | 1066.5 | 609.7 | 728.6 | 1347.1 |
| 2026-10 | 31 | 1118.7 | 624.4 | 763.9 | 1388.7 |
| 2026-11 | 7 | 1147.5 | 626.5 | 784.6 | 1412.3 |

- C0 beats the incumbent on **102 of 102 days**, and on every board every day. Median
  improvement 457, range 451–527.
- T wins on 102 of 102 days with a median of 338. C_vd loses on 102 of 102 days, median −280.
- There are 101 distinct board states, but consecutive days are strongly autocorrelated: the
  shape drifts slowly. The effective sample is far smaller than 102, and the stability of the
  gap is the informative part.
- The same incumbent scored **658.8** on 2026-07-29 in its own native coordinate (the
  quantity v2's promotion gate saw), against **998.6** in the coordinate it is served in.
  That gap is the governance face of W30-F008.

On today's committed boards (`d7db52a43b`), the criterion is: incumbent 1144.78, C0 624.39,
T 782.22, C_vd 1410.32, R302 511.57. The incumbent and R302 values reproduce the 2026-11-07
Autopilot record exactly. Per-board best fits show how wide the market-shape spread is
(midpoint rank `M = c·499`):

| board | role | M | s |
|---|---|---|---|
| DraftSharks | train | 12.0 | 0.81 |
| OTCFFB | holdout | 20.0 | 1.025 |
| FantasyCalc | holdout | 22.0 | 1.075 |
| DynastyDaddy | train | 24.5 | 1.15 |
| DynastyNerds | train | 27.5 | 1.77 |
| PFKDynasty | holdout | 37.4 | 1.05 |
| YahooBoone | train | 37.9 | 1.25 |
| KTC | train | 50.9 | 0.905 |
| Fitzmaurice | train | 57.9 | 1.31 |

The served incumbent (`M = 54.9`) sits next to KTC. C0 (`M = 38.4`) sits at the panel
average. The holdout boards are steeper still.

### 12.2 Board ordering against later markets (bracketed, no look-ahead)

For six dates from 2026-08-01 to 2026-10-10, I rebuilt the archived board at *t* under each
candidate. I then measured the Spearman correlation of offense `rankDerivedValue` with each
market's values at *t* + 28 days. Two kinds of target exist, and neither is independent. They
are contaminated in **opposite directions**:

| target | bias | C0 − incumbent | C_vd − incumbent |
|---|---|---|---|
| FantasyCalc / OTCFFB / PFKDynasty (they vote **by rank** at *t*) | favours the incumbent, because C0 deflates their own votes | **0 of 18 pairs better**; mean −0.0188 (−0.0085 … −0.0269) | 1 of 18; mean −0.0021 |
| KTC Market `ktcCrowdTradesSfTep` (benchmark-only, descendant of value-direct KTC votes) | favours C0, because C0 raises KTC's relative influence | **0 of 5 pairs better**; mean −0.0162 | 2 of 5; mean −0.0002 |

C0 loses against **both** targets, including the one biased in its favour. The mechanism is
the vote loss in §10. C_vd is indistinguishable from the incumbent. Baseline Spearmans are
0.90–0.98 on 354–397 joined rows per pair.

### 12.3 What this evaluation cannot show, and what would enable it

There is no independent target for dynasty value in the corpus.
`src/model_registry/independent_validation.py` has an empty registry, and every value board
is either a voter, a trainer or a descendant of one. §12.1 measures agreement of curve shape
with other markets. §12.2 measures ordering agreement with later markets. Neither measures
accuracy against reality. Measuring that needs a preregistered independent validation target
(gate 7). Examples would be realised trade-price outcomes from a league trade ledger the
curve never reads, or multi-season realised production under exact league scoring. It also
needs enough of that history to cover the offense/IDP balance, not only offense. GLOBAL and
IDP have no holdout at all (B1.1 §9 re-confirmed: no value-publishing IDP board exists that
the fit does not read).

## 13. Confidence, calibration and uncertainty implications

| bucket (1,010 comparable rows) | incumbent | C0 | T | C_vd | R302 all |
|---|---|---|---|---|---|
| high | 134 | **75** | 78 | **221** | 54 |
| medium | 240 | 201 | 226 | 203 | 229 |
| low | 636 | 734 | 706 | 586 | 727 |

The B11 agreement axis (`src/api/confidence.py`) counts families within 15 % of
`rankDerivedValue`. C0 pulls rank votes and value-direct votes apart, so agreement falls.
C_vd pulls them together. The vote calibration (median rank-Hill vote ÷ median value-direct
vote on the same row, QB/RB/WR) tells the same story:

| board rank | incumbent | C0 | C_vd |
|---|---|---|---|
| 1–50 | 1.079 | 0.984 | 1.070 |
| 101–200 | 0.926 | 0.724 | 1.007 |
| 201–400 | 0.847 | 0.633 | 1.020 |
| 401–800 | 0.837 | 0.584 | 1.134 |

The disagreement C0 exposes is real: KTC's value shape is flatter than the market average
(§12.1 table). Confidence would correctly report it. But because the outlier filter discards
the dissenting value-direct votes, the published value would also lose that information
rather than merely flagging it. Uncertainty about the right curve is wide: the trainers'
midpoints span 12–58 ranks. Choosing between C0-like and C_vd-like curves moves mid-board
offense values by roughly ±25 %.

## 14. Downstream consumer effects (if anything were ever activated)

- `rankDerivedValue`, which feeds `/rankings`, `/trade` (geometric package model: VA depends
  on the value arrays, so package verdicts move), the trade finder and suggestions (top-150
  gates are rank-based and membership changes), Angle, waivers, the Terminal, BDVM's /rankings
  gap column (it compares fundamental to market, so the gap shifts by the market move), and
  Consensus Edge.
- **Confidence buckets** (§13), and through them Consensus Edge `WITHHELD` and BDVM row skips.
- **Picks**: 2027 slot picks through the rookie tether. Draft-capital dollars come from the
  rookie-auction generation module, not from `rankDerivedValue`. `rookieBoardValue` on
  `/api/draft-capital` and Perfect Draft's surplus math read board values, so they move.
- **FAAB**: `V_allin` / `V_repl` are read off the board per refresh, so dollar ceilings
  follow the relative ladder. Absolute anchors move.
- **Temporal ledger**: `rankChange` would show a one-day step on activation. History must
  never re-derive old values with a new curve (C1-U4).
- **Contract stamps**: `hillCurves` (c, s, midpoint) and the HillCurveExplorer.
- **Not affected**: value-direct-only rows (except tethered picks), 2028/2029 picks, BDVM
  fundamentals (zero market inputs), the market layer of BDVM (value-signal sources only),
  league scoring and identity.

## 15. Rollback

Nothing is activated, so there is nothing to roll back. If a future owner-approved promotion
happened, the path is `scripts/model_registry.py rollback` followed by `apply` (both human),
which restores v2's eight constants verbatim. There is no flag. The board is a pure function
of the constants and the scrape, so a rebuild restores the pre-promotion board exactly. That
was verified here: the incumbent rebuild equals the plain build. `rankChange` would show one
step on each transition.

## 16. Recommendation

1. **Do not activate any candidate.** Keep v2 served.
2. **Close the code half of W30-F008 as verified.** Fit, holdout and serve share one
   coordinate and tail policy. The oracle and `tests/canonical/test_percentile_coordinate_contract.py`
   pin it.
3. **Re-scope the open half.** Today's finding text should become: "the served constants are
   a native-coordinate fit; the coordinate-correct curve (C0) is known exactly, but the
   blend's value scale makes the incumbent's inflation load-bearing (outlier filter, IDP
   anchor, pick tether, confidence)". Correcting the constants alone is not a repair.
4. **Approve an offline shadow evaluation** of **C0** (framing A) and **C_vd** (framing B),
   not of T: C0 dominates T on curve shape, and T rests on depths v2 never had. The shadow
   runs this script against each new archive and the committed CSV history and tracks the
   §10–§13 metrics over time (value-direct drops, forward ordering, curve-shape forward score,
   offense/IDP exchange rate, pick term structure, confidence). It needs no served-path
   change. An experimental named contract field would be a served-path change and would need
   separate authorization.
5. **Treat the Autopilot as affected.** Its criterion optimises framing A. The current
   routine challenger (v302) would discard value-direct votes on 275 offense rows. A board
   ordering or value-vote-retention check is a candidate promotion condition for the owner to
   consider. It is not implemented here.

## 17. Owner decisions requested

1. **Scale definition.** Which statement must the OFFENSE/GLOBAL translation curves satisfy?
   - (A) the consensus shape of value-publishing markets (what ADR-008's holdout measures).
     This needs a companion decision so value-direct votes are not discarded as outliers, plus
     a cross-scope anchor rule.
   - (B) the scale of the value-direct voters the rank votes are blended with. This needs the
     holdout criterion's role in promotion to be redefined, since it would reject a B curve
     indefinitely.
   - (C) keep v2 as a declared interim, labelled as a native-coordinate curve.
2. **Authorize the offline shadow evaluation in §16.4** (research only, no served change), or
   decline it.
3. **Acknowledge the Autopilot interaction** (§16.5), so that gate 7 opening cannot promote a
   framing-A curve before decision 1 is made.

## 18. Limitations

- One pinned board for the board impact (2026-11-07). Six archived dates for forward
  ordering. The structural results (drops, direction of moves) held on every date examined;
  exact counts will drift.
- The forward curve-shape series is strongly autocorrelated. Treat it as a stable margin, not
  102 independent trials.
- C_vd is a diagnostic built to bracket the decision. It was not optimised or validated, and
  it uses `ktcSfTep` (the v2-era voter) while today's voters are KTC Crowd and KTC Trades.
- The research fitter is an independent re-implementation, vectorised with numpy. It
  reproduces registry v2 exactly. Near-ties could resolve differently from the pure-Python
  production fitter on other inputs.
- The KTC-pick population defect (hill-alignment E3) is deliberately left in C0, so that only
  the coordinate changes. A players-only refit would move OFFENSE further.
- Joins in §12.2 are by normalised name (`normalize_player_name`). Unjoined rows are dropped
  equally for both candidates.
- `exports/archive` retention could remove the pinned bundle; the board test then skips. The
  v2 inputs are carried in the evidence JSON, so the reproduction test runs on a shallow CI
  checkout, and it re-verifies against the git blobs when history is present.

## 19. Reproduce

```bash
python scripts/research/w30_f008_hill_denominator.py \
  --holdout-rev d7db52a43b8c96a7c44e2d62a24cb70c9114c37a --forward-end 2026-11-07 \
  --json-out docs/valuation/methodology_proposals/evidence/w30_f008_hill_denominator.json
python -m pytest tests/scripts/test_w30_f008_hill_denominator_research.py -q
```

Pinned inputs: v2 producer `3df9cc42db95fb81989f0ee218699464a8581b35` with these blobs:
`ktc.csv` 1451af35, `dynastyDaddySf.csv` 293296a3, `dynastyNerdsSfTep.csv` 29c808b4,
`yahooBoone.csv` 4969600b, `fantasyProsFitzmaurice.csv` efd66dcc, `draftSharksSf.csv`
7b8b4776, `draftSharksIdp.csv` 5e70dc62, `idpTradeCalc.csv` 1ec63e6b,
`exports/latest/dynasty_data_2026-07-28.json` 5831644b. Board archive sha256 f1ad8517…fb60.
Holdout boards at `d7db52a43b`: FantasyCalc 27bfee70, OTCFFB 89f23f9d, PFKDynasty ea0475e8.
Runtime is about 30 s and needs no network. With `--skip-board` it reproduces the curve
sections only.
