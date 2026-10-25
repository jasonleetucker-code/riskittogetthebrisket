# Forced-drop fix: production-box replay analysis and activation recommendation (2026-10-25)

**Status:** evidence and analysis only. The flag `forced_drop_cheapest_legal` is **OFF**. Nothing in this document
or its PR changes a flag, a config, an environment, the registry or `scripts/verify_owner_held_flags.py`. Activation
stays with the owner (`docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`, Package 1: "I am NOT authorizing activation").

**Authority:** owner decision 2026-10-21, LVA Package 1 items 4–6 (`docs/EXECUTION_PLAN.md`, "Low-value-asset decision
packages 1–5", P1). Runbook: [`FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md`](FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md).
Record: [`FORCED_DROP_FIX_2026-10-20.md`](FORCED_DROP_FIX_2026-10-20.md). Local analysis:
[`FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md`](FORCED_DROP_VERDICT_CHANGE_ANALYSIS_2026-10-21.md).

**Evidence committed with this document:**
[`evidence/forced_drop_fix_2026-10-20/box_replay.json`](evidence/forced_drop_fix_2026-10-20/box_replay.json), sha256
`f10fc997b1ef8c41b6022f97d1efcce4aba9e1eb76f492f9cd43ae7e1da1f2c3` (byte-identical to the operator's handover file).
Report stamp `generatedAt 2026-10-22T03:05:05Z`, elapsed 4,114.5 s, peak RSS 163.8 MB.

Aggregates only. This document names no league member, team, owner, roster or transaction. The only player names are
the synthetic labels in §6.

---

## 1. Acceptance check (runbook §4, §5, §6)

### 1a. The run happened as specified (runbook §4, §5 provenance rows): PASS

| check | expected | observed | result |
|---|---|---|---|
| exit code; stderr | `0`; empty | `0`; empty (operator handover) | pass |
| `provenance.pinsMatch` | `true` | `true` | pass |
| archive sha256 | `f660098f…6078e` | same | pass |
| archive JSON member sha256 | `8e9b826a…b198a` | same | pass |
| CSV tree revision · content sha256 | `d5236546f…` · `31687c60…bd54` | same | pass |
| built board sha256 · priced assets | `eed8df11…0833` · 1,003 | same | pass |
| deployed code | contains the dormant merge `<DORMANT_MERGE_SHA>` = `408742c99` (#1912) | `4d5b7ed21` (`deployedCodeSha` = `expectedCodeSha`); `git merge-base --is-ancestor 408742c99 4d5b7ed21` succeeds | pass |
| the seven pinned script and module hashes (runbook §3 step 0) | as listed | the LF content hashes of all seven files at `4d5b7ed21` equal the runbook's list (re-checked here with `git show 4d5b7ed21:<path> \| sha256sum`). The seven files are byte-identical between `408742c99`, `4d5b7ed21` and today's `main` | pass |
| `fairnessBands.version` · `packageModel.id` | `fairness_bands_v2` · `geom_q078_v1` | same; `classification: ACTIVE` | pass |
| `scarcityObserved` | 8 positions, every multiplier in 0.85–1.15; inert is the served state | 8 positions, all 1.0, `inert: true` | pass (amended gate) |
| `readOnlyGuard.refusedWriteOrProcessAttempts` | 0 | 0 | pass |
| `readOnlyGuard.refusedNetworkAttempts` | the contract build's Sleeper lookups | 4 refusals from 2 callers: `api/data_contract.py:9994` (the Sleeper league lookup) and `<frozen importlib._bootstrap>:488` | pass, see note |
| live inputs before vs after | byte-identical | `live_inputs_before.txt` = `live_inputs_after.txt`, both sha256 `69d31dd099e41e99ecf7c72daee41c8456a67abe9fbb6a71c69ad097231aaf43`. They record the ROS aggregate hash `3ac8726b…d325` and 29 BDVM projection files, the newest dated 2026-10-20 | pass: nothing moved during the run |
| `HEAD` before = after | no VOID line | no VOID line was handed over | pass |
| resource caps | within 4 GiB, 5,400 CPU s, 7,200 wall s | 163.8 MB, 4,114.5 s wall | pass |

**Network refusals.** The importlib caller means a third-party (site-packages) module attempted a `socket.*` call
while it was being imported. The guard reports the first frame outside the standard library and site-packages, which
for import-time code is the frozen importlib frame. The guard refused it, as designed. It was already present in the
2026-10-21 box rehearsal (also 4 refusals, same two callers), and it did not reach the measured board, which hashed to
the pin. The aggregate report cannot say which library made the call. That is listed in §10.

**The live-input files are not committed.** Runbook §4 step 8 names only the report as the committed file. Their
digest and contents are recorded in the row above. They hold hashes, sizes and timestamps only.

### 1b. The report is aggregate-only (runbook §1, "Aggregates only"): PASS

The in-run check had already refused anything else (exit 4). A second scan of the committed file found:

* no key naming a person or an identifier;
* no run of 9 or more digits outside the named provenance fields;
* no hex digest outside `provenance` and `provenance.configSha256`;
* no canonical asset id (`pick:`, `mpick:`, `player:`, `name:`).

The file holds 50 string values: design descriptions, rule ids, version labels, file paths of the pinned artifacts,
and the two guard caller locations. The per-trade and per-team blocks (`examples`, `perTeam`, `illustrations`) are
stripped (`BOX_STRIP_KEYS`). The only league named is the public registry key `dynasty_main`, in the design strings.

### 1c. Runbook §6 stop conditions: two are live, so this is not an activation result

| # | stop condition | observed | state |
|---|---|---|---|
| 1 | wrong-sign regret, or any V5-R anomaly | `negativeDefect` 0 everywhere; V5-R forward and reverse anomalies 0 in both designs | clear. These are zero by construction (§8), so they confirm the implementation, not the method |
| 2 | V5-R extra charge large against the band base | War Room p90 12.6% (local smoke run of #1912: p90 12.3%); census p90 8.9%. Tie census: 0 ties, 0 `player_id_search_bound` | clear: not "well above" the local figure |
| 2a | Component B overturns the A-driven result | 39 of 109 A-only favourable V5-R verdicts (35.8%) are no longer favourable when Component B votes (V5: 38 of 117, 32.5%). The ON cut lowers lineup points per game on 31 of 174 cut-changed trades, not most | **owner judgment.** The share is material, but on net it is withholding, not contradiction (§4) |
| 3 | the flag raises a charge at or under the cap | `atOrUnderCap:up` absent; War Room `up` 0 in both modes | clear |
| 4 | favourable verdicts depend on the single-source tail | under the stress, census favourable V5-R falls 103 → 9 and V5 111 → 12 | **LIVE.** The correction is not established unless the owner accepts the cheap-tail values as real cut costs |
| 5 | scarcity read degraded | 8 positions at 1.0 | clear (inert is the served state) |
| 6 | Component B unavailable on almost every trade | available on 278 of 278 trades in every mode | clear |
| 7 | a new evidence gap with the flag ON on more than a handful | `- -> unprojected_players` on 3 (V5) / 4 (V5-R) of 278; no `forced_drop_charge_unavailable` | clear: a handful, and explained in §4 |
| 8 | category changes outside the sensitivity band | War Room 109 / 105, inside 95–112; census 125 / 127, inside 122–130 | clear |
| 9 | guard refusal, non-zero exit, pin mismatch, report refused | none | clear |

**Verdict:** the run is **valid** evidence. It does **not** clear the activation bar. Condition 4 is live, and
condition 2a needs the owner's reading.

---

## 2. Box versus local: what differs and why

The flattened box report and the committed local `replay.json` share 248 numeric and string paths. **241 are
identical.** Every A-driven aggregate is equal to the last digit: filler flips, verdict transitions, charge
distributions, anomaly censuses, V5 vs V5-R, the Trade Finder and Perfect Draft. The 7 that differ:

| path | box | local | why |
|---|---|---|---|
| `defaultSelectionMode` | `roster_rational` | `package_consistent` | the local file was generated at `17765f0b6`, before the owner chose V5-R (2026-10-21). The replay measures both modes explicitly (`MODES`, with `SELECTION_MODE` set per run), so no number depends on this constant |
| `warRoom.shadowBandBase.stepsWhereBaseDiffersFromLargerAdjustedSide` | 0 | 135 | a diagnostic counter, not a measurement. #1898 (2026-10-21) changed `scripts/low_value_asset_forced_drop_diagnostic.py` to store the larger package utility directly as the step's band base. The replay's re-basing pass therefore finds nothing left to re-base. The base used for every classification is the same in both runs, which is why every flip count is identical |
| `elapsedSec`, `warRoom.elapsedSec`, `finder.elapsedSec` | 4,114.5 / 810.2 / 340.7 | 278.5 / 101.4 / 118.2 | the box run adds Component B, a second Component B census and the stress census, runs `nice -n 10` single-threaded, and is slower hardware |
| `generatedBy`, `purpose` | `--box` text | local text | labels |

**What this proves.** The two hosts agree exactly on everything both measured. Three things follow:

* The pins work: the board, the code and the configs are the same.
* Posture resolves identically on both hosts. It comes from the pinned contract, so it is not a box-only addition:
  254 of 278 census trades have a posture and 24 do not, as locally.
* The box's only material addition is **Component B**. It is the roster-utility lens, fed by the box's own BDVM
  projection snapshots, which a development machine does not have.

Real scarcity is not an addition either, because production scarcity is inert (§5).

The fields added in #1912 have no committed local counterpart: regret, tie census, Component B, stress and the
unpriced census. Where the #1912 PR body quotes a local smoke run, the box agrees:

* War Room charge regret: median 6.4% / p90 12.3% on 8 selections locally, against 6.3% / 12.6% on 49 selections on
  the box.
* Unpriced rostered players: 53 of 696 locally, against **54 of 696** on the box. Both runs count 21 kickers. The
  one-player difference is not explained by the aggregates (§10).
* Stress favourable counts: 111 → 12 and 103 → 9 in the local analysis §8. The box shows the same.

---

## 3. V5 versus V5-R (owner chose V5-R)

| (box, identical to local where both exist) | War Room (180 steps, 135 need a cut) | Census (278 trades, 181 need a cut) |
|---|---:|---:|
| cut sets that differ between V5 and V5-R | 49 | 36 |
| … of which V5-R charges more · less | 49 · 0 | 36 · 0 |
| … of which the private-decision category differs | 20 | 9 |
| **asset value V5 gives up that V5-R keeps**: median · p90 · max | 280 · 673 · 813 | 180.5 · 414 · 531 |
| **extra charge V5-R pays**: median · p90 · max | 430 · 874 · 979 | 128.5 · 369 · 433 |
| … as % of the fairness band base: median · p90 · max | 6.3 · 12.6 · 16.8 | 3.8 · 8.9 · 12.9 |
| V5 forward currency anomalies / selections releasing an acquired piece | 49 / 65 | 36 / 70 |
| V5-R forward anomalies / selections releasing an acquired piece | 0 / 20 | 0 / 34 |
| reverse anomalies, both modes | 0 | 0 |
| an incoming piece charged above its own value (V5 · V5-R) | 0 · 0 | 0 · 0 |
| Trade Finder top 20: V5-R vs V5 | identical on 12 of 12 teams | |

What this means: on every instance where they differ, V5 shows a higher net, and it gets there by releasing a more
valuable real player than V5-R would. In the median War Room case, V5 lets go of 280 more points of real dynasty value
and still displays a net 430 points higher. The gap between those two numbers is not roster information. It is the
package model's depth discount appearing inside a roster-spot calculation: a later piece of a geometric package is
credited 0.61x its value as the third of three, and 0.475x as the fourth of four.

**The owner's choice of V5-R is confirmed by production data.** V5 names a cut no rational manager makes in 85 of the
135 selections that release an acquired piece. The cost of V5-R is bounded: it charges more on 49 of 180 and 36 of 278
trades, and changes category on 20 and 9. The Trade Finder is unaffected.

---

## 4. Component B (the real roster-utility lens) and posture

Component B was available on **278 of 278** census trades in every mode. Posture was available on 254 and unknown on
24 (8.6%), identical across modes.

**Headline distribution with real Component B** (same 278 trades):

| | YES | NO_TOO_CLOSE | NO | NOT_ENOUGH_EVIDENCE |
|---|---:|---:|---:|---:|
| flag OFF | 16 | 3 | 120 | 139 |
| flag ON, V5 | 85 | 12 | 85 | 96 |
| flag ON, V5-R | **77** | **14** | **85** | **102** |

Category changes against OFF: V5 97, V5-R 93. With the A-only stand-in they were 125 and 127. The V5-R transitions:

| transition | trades |
|---|---:|
| UNFAVORABLE → FAVORABLE | 38 |
| UNAVAILABLE → FAVORABLE | 25 |
| UNAVAILABLE → UNFAVORABLE | 11 |
| UNFAVORABLE → APPROXIMATELY_EVEN | 8 |
| UNAVAILABLE → APPROXIMATELY_EVEN | 5 |
| FAVORABLE → UNAVAILABLE | 2 |
| APPROXIMATELY_EVEN → UNAVAILABLE | 2 |
| STRONGLY_UNFAVORABLE → UNFAVORABLE | 2 |

**Does Component B overturn the A-driven result? On net, no. It withholds.** For V5-R, the 278 trades move from the
A-only stand-in to real Component B as follows:

| (V5-R, same trades) | favourable (YES) | approximately even | unfavourable (NO) | withheld |
|---|---:|---:|---:|---:|
| A-only stand-in | 109 | 43 | 85 | 41 |
| real Component B | 77 | 14 | 85 | 102 |
| net change | −32 | −29 | **0** | **+61** |

V5 follows the same pattern (−32 / −24 / +1 / +55), and so does flag OFF (−10 / −3 / −31 / +44).

The decided-unfavourable count is unchanged. Every net loss of a favourable or even verdict is matched by an extra
withheld one. The aggregates give the net movement only. They cannot exclude offsetting gross moves, such as a few
favourable → NO balanced by a few NO → withheld, so "Component B never votes against" is not established. "Component
B's main effect is to withhold" is.

The mechanism is in the code. `trade_decision._evidence_gaps` raises `unprojected_players` when the roster lens reports
`partial_projection_coverage` for a traded player and the strategy is WIN_NOW or BALANCED. The census fillers are drawn
from a rival's ten cheapest players, and those are exactly the low-value depth pieces that most often lack a
league-scored projection. With the stand-in this gate never fires. The evidence-gap transitions show it:
`forced_drop_unpriced,unprojected_players -> unprojected_players` on 16 (V5) / 17 (V5-R) trades, meaning the forced-drop
gate lifts but Component B's own gate still withholds the headline.

**Why a "new" gap appears with the flag ON.** `- -> unprojected_players` appears on 3 (V5) / 4 (V5-R) trades, and the
opposite `unprojected_players -> -` on 8 / 4. In `roster_capacity.py`, a forced drop's role overrides `incoming`
(`roles.update({pid: "forcedDrop" …})`), and coverage counts only `incoming` and `outgoing` players. So when the OFF
cut released an unprojected incoming piece and the ON cut keeps him, the gap appears; the reverse makes it disappear.
This is not a new kind of gap. It is the existing gap applied to a different final roster. V5 removes it twice as often
(8 against 4) because V5 releases acquired pieces twice as often. One could call that "fixing" missing evidence by
cutting the player whose evidence is missing. V5-R does less of it.

**Lineup effect of the cut (Component B's own number).** On the 174 trades whose cut changed with Component B
available (V5-R):

* the ON cut **raises** the trade's lineup points per game on **111** (median +1.3 ppg, p90 +3.5, max +4.1);
* it **lowers** them on 31 (median −0.2, p90 −2.0, max −3.0);
* it leaves them unchanged on 32.

V5 is nearly identical (110 / 32 / 32). The incumbent's alphabetical or unpriced cut was usually a worse lineup choice
than the cheapest legal cut. This is the one result in the box run that comes from a different evidence domain
(projections) from the one the fix optimises (dynasty value), and it favours the fix. It is not fully independent:
projections and dynasty value are correlated, and the lineup guard already protects slot fill. The 31 lowering cases,
up to 3 ppg, are real. Selection is by roster value, not lineup (record §9, "Lineup-legal means rank-preserving").

---

## 5. Scarcity: inert 1.0 in production

`scarcityObserved`: 8 positions (DB, DL, K, LB, QB, RB, TE, WR), every multiplier 1.0, `inert: true`. Seven of the
eight positions have a waiver-level value. This is production's served state by construction: `gameplan.py` calls
`compute_scarcity` with no free agents, so `waiver_scarcity` is None and `scarcity_multiplier` returns 1.0, and owner
decision D8 keeps it inert.

Consequences, stated rather than hidden:

1. The box adds **nothing** about scarcity. Every local and box number is at 1.0.
2. **V5's reverse anomaly is structurally 0** at 1.0. A geometric credit never exceeds a piece's own value. The box
   reports 0 / 134 and 0 / 167 (V5) and 0 / 134 and 0 / 175 (V5-R). This is not evidence that the reverse direction
   is safe under real scarcity. It is untestable while scarcity is inert. The top-ranked-piece case in local §8, with
   a credit-to-value ratio of 0.88–0.99 above a 0.85 multiplier, stays untested.
3. V5-R's selection is invariant to uniform scarcity (local §8). If scarcity is ever activated (LI-5 §12 item 3), this
   replay must be re-run under it before the flag goes on top of it (runbook §6 item 5).

---

## 6. The non-monotonicity investigation (owner item 6)

**Question:** can a *better* incoming player make V5-R's calculated result *worse*?

**Answer: yes. It is a property of the objective, not a defect in the selection, and it is the same mechanism as V5's
anomalies, pointed the other way.**

### 6a. Reproduction (real selection code, `forced_drop_selection.select_forced_drops`, `main@503f08581`)

The team receives a 3,000 plus a second piece worth X and sends a 3,000. It is at the cap, so one cut is owed. Its
cheapest legal existing player is a 900 bench player. The geometric model credits the second piece at 0.78·X.

| X (incoming second piece) | V5 cut → net | V5-R cut → net | real roster outcome, V5 · V5-R |
|---:|---|---|---:|
| 850 | X released, charged its credit 663 → **0** | X released, charged 663 → **0** | 0 · 0 |
| 899 | X → 0 | X → **0** | 0 · 0 |
| **901** | X (credit 703) → **0** | **bench 900** (charged 900) → **−197** | 0 · **+1** |
| 1,000 | X (780) → 0 | bench 900 → **−120** | 0 · +100 |
| 1,100 | X (858) → 0 | bench 900 → −42 | 0 · +200 |
| 1,153 | X (899) → 0 | bench 900 → −1 | 0 · +253 |
| 1,154 | bench 900 → 0 | bench 900 → 0 | +254 · +254 |
| 1,300 | bench 900 → +114 | bench 900 → +114 | +400 · +400 |

"Real roster outcome" is raw board value kept minus raw board value released and sent.

Upgrading the incoming piece from 899 to 901 lowers V5-R's displayed net by 197 points, while the roster the manager
actually ends with is 1 point better. Upgrading to 1,000 shows −120 for a roster that is +100 better. The displayed
net is **discontinuous** at X = c(cheapest existing cut). Below that point the new piece is the cut and nets to zero.
Above it, the existing player is the cut, charged at full value, while the new piece is credited only 0.78 of its
value.

**Random sweep** (3,000 trades: 2–4 incoming, 1–3 cuts owed, one incoming piece strictly upgraded by 1–1,500):

| | V5 | V5-R |
|---|---:|---:|
| upgrades that lowered the displayed net | **0** | **122** |
| worst drop | 0 | 1,233 |
| … of the V5-R drops, the real roster outcome nevertheless improved | | **122 of 122** |
| … drop within the improved package's total depth discount (value − credit) | | 125 of 125 (second seed) |
| … single-cut drops within the upgraded piece's own depth discount | | 26 of 26 |

This complements the pinned free-extra-piece reproducer
(`tests/trade/test_forced_drop_selection.py::test_v5r_net_is_not_monotone_in_a_free_credited_extra_piece_v5_is`,
passing) and the reviewer's 313 of 3,000 V5-R against 6 under V5 (record §10 item 9).

### 6b. Why it happens

V5-R's net is `G(K \ J) − Σ_{E∩S} c`. The gain side counts each incoming piece at its **package credit**, a geometric
discount below its value for every non-top piece. The loss side counts each existing release at its **full value** `c`.

Adding or upgrading a piece f, where the cheapest existing legal cut c_min sits strictly between f's credit κ_f and
f's value v_f, makes V5-R cut the existing player. That cut is the rational one: c_min < v_f. The net then moves by
κ_f − c_min < 0. The drop is bounded by c_min − κ_f < v_f − κ_f, which is f's own depth discount. The sweep confirms
the bound.

V5 avoids this by cutting f at κ_f, the very cut that produces its forward anomalies. Either mode pays for the mixed
currency somewhere:

* **V5 is monotone but names irrational cuts.** It releases the more valuable player because his package credit looks
  cheap.
* **V5-R names the rational cut, but its displayed net is non-monotone and discontinuous.**

Neither is an implementation error. Both are exact for their stated rule: brute-force pinned up to d = 4, 666 tests
pass on `main`.

### 6c. Classification

| possibility | verdict |
|---|---|
| a defect in V5-R's selection | **no**: selection is the exact minimum-Σc legal set, and the cut it picks is the better roster outcome in 122 of 122 sweep violations |
| a property of the objective | **yes**: the package credit (discounted) and the release charge (full value) are in different currencies. Any accounting that nets a discounted gain against a full-value loss is non-monotone in the gain |
| unresolved | the *remedy* is unresolved, and it is an owner methodology decision, not an implementation one. Options: (i) accept it and state it plainly (record §10 item 9; wording in §9 below); (ii) charge an existing release in package-utility units, as if the released player were a package piece, which restores one currency at the cost of a new modelling assumption; (iii) charge sub-waiver releases over replacement, the V6 family, which makes most full-roster cuts nearly free and was rejected in record §2 for its asymmetric units. Only (i) is within current authority |

**What it means for a manager.** "This sweetener makes the trade worse" can appear in the War Room under V5-R when the
sweetener is worth slightly more than the player it forces out. The roster is in fact slightly better. The displayed
net understates it by at most the sweetener's depth discount. On this board, the V5-R-minus-V5 charge is at most 979
points in the War Room design and 433 in the census (`chargeRegretV5RMinusV5.max`). That is 16.8% and 12.9% of the
band base. This bounds how far the same currency effect moves a displayed net on real rosters.

---

## 7. Real player values against model-assigned package costs and credits

| quantity | what it is | where it is shown |
|---|---|---|
| `rankDerivedValue` (the board value) | the player's canonical dynasty value, one number per player | `forcedDrops[].value`; the Trade Calculator lists it per cut and sums it as "value released" (`trade-simulation-panel.jsx:227-241`): correct |
| `releaseCost` = c = base × scarcity | the cost of releasing a rostered player. Equals the board value at scarcity 1.0; for an unpriced player, the `assumedWaiver` ceiling (1,918–2,156 on this board) | per-drop evidence |
| `package_credit_forgone` | what the trade's package credited a just-acquired piece. **Not** the player's value: 0.78x / 0.61x / 0.475x of value for the 2nd / 3rd / 4th piece, and the sequential split across several released pieces can exceed one piece's own value (record §10 item 10) | `forcedDrops[].chargeBasis`, and summarised in `objectiveValue.forcedReleaseChargeBasis` (flag ON only) |
| `forcedDropCharge` / `objectiveValue.forcedReleaseCost` | the single marginal number the War Room subtracts: a mix of the two rows above, marginal to the trade, clamped at 0 | War Room reason sentence (§9) |

On the box the incumbent charge fell by a median 1,888 (War Room, V5-R) and 1,664 (census) on every changed step at or
under the cap. The cause is selection: the cheapest legal cut instead of the first name. 86–97% of the median shift is
selection alone (local §2). Package netting of a just-acquired release is small: −7,474 of −282,481 census V5 change.

The headline effect is therefore about **which real player is cut**, not about package credits. But the credits are
what the user would see attached to a name, which is why §9 matters.

---

## 8. Technical correctness against recommendation quality

These are different questions. The box run answers the first well and the second only partly.

**Technically correct (established):**

* The selection is the exact optimum of its stated rule (brute force; 666 tests pass on `main`).
* Flag-OFF output is byte-identical to the incumbent (`test_forced_drop_flag_off_identity.py`).
* Box and local agree to the last digit on every shared measure.
* The run was read-only and non-mutating (guard 0, live inputs identical).
* The flag never raises a charge at or under the cap.
* `forced_drop_unpriced` disappears on all 49 War Room steps and 61 census trades that had it.
* Perfect Draft is identical on 11 of 11 comparable teams.
* The Finder is stable (mean top-20 overlap 0.854; trades carrying a forced-drop cost 9 → 66).
* The #1912 tie-break is correct on its synthetic property test (60 of 60 id-relabelled seeds). See below for why the
  box says nothing about it.

**Mechanically guaranteed, therefore weak evidence:**

* V5-R forward and reverse anomalies = 0. Its set is the minimum-Σc legal set, so no single swap lowers Σc.
* V5 reverse anomalies = 0. Structural at scarcity 1.0.
* V5 "charge > filler credit" = 0. Releasing the fillers is always a legal option at their credit.
* `negativeDefect` = 0 in both regrets. V5 minimises the charge and V5-R minimises Σc.
* "Never up at or under the cap" is close to structural at scarcity 1.0: the incumbent's own cut is a legal candidate,
  and credit ≤ value.

These zeros confirm that the code is the rule. They say nothing about whether the rule gives better trade advice.

**Tie-break and ID-independence on production data.** `tieCensusV5R.tieBreakApplied` is **0** in both designs. No
exact tie between an existing and an incoming player decided any cut on the real board. The #1912 fix is correct, as
pinned by `test_v5r_exact_value_tie_is_broken_by_charge_not_player_id` and the 60-seed relabelling property, but it is
**inert on this board**. The box gives no evidence for or against it beyond "it never fired".

ID-independence of the decisions:

* Ties break on player id only as the last key, and only past the search bound. That never happened here
  (`player_id_search_bound` 0).
* The incumbent's 90–94 "tied cut" notes disappear with the flag (local §6).
* Renaming and shuffling are pinned not to move the cut set or charge (record §3).

**Recommendation quality (not established):**

* **More changed verdicts is not better accuracy.** There is no realized-outcome ground truth for any variant (record
  §3a). 93–127 category changes show the incumbent's charge was large, a median 54–60% of the band base (local §1). They
  do not show the new verdicts are right.
* **The favourable direction rests on the cheap single-source tail.** 254 single-source players are on the board. The
  cheapest legal cuts carry single-source values of 226–440. If those values are not real, census V5-R favourable
  verdicts fall from 103 to 9. Under the stress the flag still changes about as many categories (122), but mostly from
  withheld to UNFAVORABLE (12 → 88) and APPROXIMATELY_EVEN (43 → 61). The box reproduces the local stress exactly, so
  production data does not soften it.
* **The waiver anchors and the cheap tail disagree by an order of magnitude.** Unpriced cuts are charged the
  `assumedWaiver` ceiling of 1,918–2,156, the best unrostered value at the position. Rostered cheap-tail players sit at
  226–440. If the anchors are real, a manager could replace a sub-waiver player at no cost, and the economically right
  charge for a sub-waiver cut is about 0 (the V6 view). If the anchors are artefacts (unsigned or retired players still
  on the board), the ceiling overstates unpriced cuts. Neither reading is tested here (§10).
* **The lineup evidence leans the right way.** The ON cut raises the trade's lineup ppg on 111 of 174 and lowers it on
  31 (§4). It is the only cross-domain signal, and it is partly correlated.
* **Unpriced rostered players: 54 of 696 (7.8%).** By position: K 21, DL 13, DB 13, LB 3, WR 3, RB 1. Every team holds
  at least one; 11 of them are at the cap. With the flag ON an unpriced cut is charged the waiver ceiling, so these
  players are almost never cut. That is correct if they are real assets. It is wrong if they are dead roster spots,
  such as retired players or unrostered-in-reality kickers, which a manager would cut first and which cost nothing.
  One of the eight positions has no waiver value (7 of 8). An unpriced player there is charged the cheapest positional
  waiver level (`displacement._waiver_value_for`). The aggregates do not say which position; K is the likely one
  because the board prices no kickers.

---

## 9. User-facing copy review (no file changed)

| # | location | text | problem | proposed fix (owner / UI lane) |
|---|---|---|---|---|
| C1 | `frontend/lib/trade-war-room-copy.js:793` (`reasonSentence`, objectiveValue) | `After the forced cut of X (worth N), you …` with N = `objectiveValue.forcedReleaseCost` | **Flag ON only:** N is the marginal charge, which for a just-acquired release is the *package credit forgone*, not what the player is worth (record §10 item 4). Flag OFF (served today): N is the gross release value of the incumbent's cuts at board value, so "worth" is accurate there. An unpriced cut is gated to NOT ENOUGH EVIDENCE first | record §10 item 4 wording, by `forcedReleaseChargeBasis`. `release_value`: keep. `package_credit_forgone`: "After releasing X, whom this trade sends you (the package credited him N)". `mixed`: "After the forced cuts of X and Y (N of trade value given up)". Add "(N is an upper estimate — X has no board value)" for `assumed` / `mixed_bound`, and "(at least N)" for `lower_bound`. A neutral interim, "(N charged for the cut)", is accurate in both flag states |
| C2 | `trade-war-room-copy.js:910` (`cutNames` from `lenses.feasibility.detail.forcedDrops`) | every forced drop is named in the C1 sentence | for an over-cap roster the list includes cuts the roster owed before the trade, which are not in N. The sentence then attributes N to players not charged | needs a backend publish of `chargedInMarginal` per drop (record §10 item 10). That is a behaviour change, not copy |
| C3 | `src/trade/trade_decision.py::_forced_release_charge_meta` | `forcedReleaseChargeBasis` maps every non-`package_credit_forgone` basis, including `release_value_uncredited` and `release_value_no_package`, to `release_value`, computed over **all** forced drops | an uncredited unpriced cut is charged an *assumed* waiver ceiling but reads `release_value`; a pre-owed drop shapes the label | record §10 item 10: compute over charged drops only and keep the four bases distinct. Behaviour change |
| C4 | per-player package credits for released incoming players | not shown today | the sequential-removal split can exceed a piece's own value, so a per-player "credit N" would mislead | keep them unshown (record §10 item 10) |

Checked and found accurate:

* the Trade Calculator banner (`trade-simulation-panel.jsx:225-241`: "N value released", per-cut board value, "unpriced,
  not counted");
* Best Offers' factor label "Forced release cost (cost)";
* `market-arbitrage.js::rosterCapacityLine` (names and counts only);
* the backend notes in `roster_capacity.py` and `forced_drop_selection.py`. The clamp note says "raw credit … charged
  …", never "worth".

**Why no copy was edited.** C1 is false only with the flag ON, and the flag is OFF. Changing it now changes served text
for no correctness gain. The owner asked for the corrected War Room copy to come back for approval with the activation
request (Package 1). The full correction (C1–C3) needs basis-aware branching and a backend field, which is behaviour,
not wording. These are listed for the owner and the UI lane.

---

## 10. UNRESOLVED

1. **The cheap single-source tail** (runbook §6 item 4, live). Are values of 226–440 real cut costs? It is an owner
   decision, or evidence such as what `dynasty_main` managers actually release from full rosters.
2. **The Component B reading** (§6 item 2a). Is a 36% loss of A-only favourable verdicts material when, on net, it is
   withholding through `unprojected_players` and `posture_unknown`, not opposition? The gross decomposition needs
   per-trade data the aggregate report does not carry. A box re-run could add a `favourableLostTo` breakdown;
   authorization is needed.
3. **The non-monotonicity remedy** (§6c). Accept and state it, or change the accounting currency (owner methodology).
4. **Copy and backend publishes** C1–C3 (§9; record §10 items 4 and 10).
5. **Unpriced rostered players** (54; 21 kickers) and which position lacks a waiver value. Should they be cleaned, or
   charged the ceiling (record §10 item 8)?
6. **Waiver-anchor plausibility.** Are the 1,918–2,156 best-unrostered anchors real free agents or board artefacts (§8)?
7. **Over-cap marginal policy** (class D; 15 census charge increases, one roster): accept or reject (record §10 item 12).
8. **V5-R production-impact approval** (record §10 item 11). This document supplies the V5-R box numbers: War Room 105
   changes; census 127 with the A-only stand-in and 93 with real Component B; Finder identical to V5.
9. **Scarcity**: untestable while inert. If it is ever activated, re-run the replay first.
10. **Minor, not blocking:**
    * the site-packages import-time socket call refused by the guard (§1a), library unidentified;
    * the one-player difference in the unpriced census, 54 here against 53 in the #1912 local smoke run, not
      reproducible from aggregates;
    * the #1912 tie-break is inert on this board (0 ties), so it is verified synthetically only.

---

## 11. ACTIVATION RECOMMENDATION

**Do not activate yet. Recommendation: more research and owner decisions first.** The fix is technically ready. Its
recommendation quality is not established.

**Reasons:**

1. **Stop condition 4 is live.** The favourable shift collapses (census V5-R 103 → 9 favourable) if the cheap
   single-source tail is not real. The box reproduces the local stress exactly, so production data did not resolve it.
2. **With the real Component B, the user-visible gain is smaller and mostly withholding.** OFF → V5-R moves YES 16 → 77
   and NO 120 → 85 of 278, but 102 trades (37%) stay NOT ENOUGH EVIDENCE. A third of the A-only favourable verdicts are
   withheld once Component B votes, largely because the cheap depth pieces at the heart of the forced-drop question have
   no league-scored projection.
3. **V5-R's non-monotonicity is real** (§6). A better incoming player can lower the displayed net, by up to that piece's
   depth discount, while the roster improves. That must be stated to users (record §10 item 9) or fixed by an
   accounting decision.
4. **The War Room copy is not ready** (§9 C1–C3). Under the flag ON it would label a package credit as what a player is
   "worth" and could attribute a charge to cuts the trade did not cause.
5. **Owner decisions still open:** record §10 items 2, 7, 8, 11 and 12.

**What the box run does support:**

* the mode choice (V5-R over V5);
* the technical correctness, read-only safety and determinism of the implementation;
* stability of the Finder and Perfect Draft;
* the direction of the lineup effect: the ON cut is the better lineup choice on 111 of 174 trades;
* removal of the `forced_drop_unpriced` gate on 49 and 61 trades.

The incumbent is demonstrably wrong: an alphabetical cut charged a median 54–60% of the band base. But "the incumbent
is wrong" is not the same as "this replacement's verdicts are right".

**Evidence that would change this to "recommend":**

* **(a)** An owner ruling that single-source values are real cut costs. Alternatively, a measured comparison of the
  fix's chosen cuts with the cuts `dynasty_main` managers actually made on full rosters, using completed transactions,
  read-only. That would turn class A from conditional into established.
* **(b)** The corrected copy (C1, plus backend C2/C3) implemented behind the same OFF flag and approved by the owner.
* **(c)** The owner either accepts the §6 non-monotonicity with the plain-words statement, or chooses an accounting
  change, which would need its own replay.
* **(d)** A box re-run authorization only if the owner wants the gross Component B decomposition (UNRESOLVED 2). Not
  needed if (a) is answered.

**Narrower option, for the owner's consideration only and not recommended or implemented here:** selection alone, the
cheapest legal cut at the incumbent's own full-value charge with no package netting, reproduces 86–97% of the median
charge shift (local §2). It has neither V5's anomalies nor V5-R's currency-driven non-monotonicity, because both
currencies are full value. It is a different variant (close to V1 in record §2, whose remaining flaw is charging a
just-acquired filler its full value) and would need its own authorization and replay.

**What this means for trade advice in `dynasty_main` (12 teams, 58-man rosters, 11 of 12 at the cap on this board).**
Nearly every trade that brings back more players than it sends forces a cut. Today's War Room charges the full value
of whichever cheap player sorts first, often an unpriced one charged about 1,900–2,150. So most such trades read NO or
NOT ENOUGH EVIDENCE: 16 YES of 278 in the real-Component-B census. With the fix the cut becomes the genuinely cheapest
legal player, the charge drops by a median of about 1,700–1,900, and YES rises to about 77 of 278. Those new YES
verdicts are right only if the cheapest players on full rosters are really worth as little as the board says (226–440).
That is the question to settle before switching it on.
