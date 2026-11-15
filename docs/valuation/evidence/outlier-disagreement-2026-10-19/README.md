# Disagreement-preserving outlier policy: evidence (2026-10-19)

Owner directive 2026-10-19, "Universal source voting and freshness policy": §6 (fix the
IDP outlier-filter problem), with §1 (DLF IDP and DLF Rookie IDP restored to voting) and
the outlier part of §9 (validate before deployment).

**Evaluation and a default-OFF implementation. Nothing was activated.** The flag
`outlier_disagreement_policy` ships OFF, the DLF IDP hold is not changed here (PR #1817
owns it; every DLF-restored number below is a local build with `dlf_offense_only_vote`
OFF), and a default board is byte-identical to `main`.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | committed in `b579a5fdd5` and pushed at 2026-10-19 07:56 UTC, before the candidate was implemented in the pipeline or run on any frozen board |
| `diagnosis_2026-10-19.json` | every rejection on the current board, its evidence and class; the §9 comparison (`ownerEvidence`) |
| `evaluation_historical_replay.json` | M1, M3-M6 and the verdict on the frozen 105 complete boards; S1-S7 |
| `evaluation_m2_g1.json` | M2 (reported, not decisive) |
| `adversarial_suite.json` | M7: the function-level corruption cases and the end-to-end checks |
| `n3_reproduction.json` | `idp-hampel-n3-v1` re-run exactly as its own preregistration states |

## Summary

* **Diagnosis.** On the current board with DLF IDP restored, the incumbent filter rejects
  **130** votes (98 offense, 32 IDP). **All 130 are legitimate disagreement; none shows
  evidence of a data error** (identity, normalization or staleness). 126 of them are the
  same source's view on all 105 replayed boards since 2026-08-18. On 90 of the 130 the
  filter's threshold had collapsed to its 1,000-point floor.
* **The policy** keeps every one of them except one (Draft Sharks on Brock Bowers): IDP
  values then move only by DLF's own vote (max 5.4%), and **no row moves 40-50%**.
* **Two real data errors exist in the replayed history**, and they cut both ways (§1.4):
  rookie boards voting untranslated ranks (both filters remove them; the policy as a whole
  board) and a transient IDP Trade Calculator offense glitch (the incumbent removes most of
  it, the policy does not).
* **Preregistered verdict: NOT ELIGIBLE.** The policy fails its own adversarial gate on 3
  of 6 per-row corruption cases (AD1b vote ×0.2, AD1d ×0.05, AD2 misidentified player) and on
  1 of 16 wrong-scale boards, and its board screen fires on 22 replay boards, which the
  frozen rule counts as false positives. It still beats the incumbent on 5 of the 6 per-row
  cases, and on held-out accuracy it is better than the incumbent (M1 P1 −0.0021
  [−0.0026, −0.0014]) with stability within the bar.
* **`idp-hampel-n3-v1`** re-run exactly as preregistered reproduces its committed result
  byte for byte (INSUFFICIENT, P1 +0.112).
* **Recommendation:** `outlier_disagreement_policy` stays OFF (the rule says so). The owner
  decision is framed as three options in §7: (a) activate despite the failed gate,
  (b) preregister a v2 that addresses the named misses, (c) restore DLF IDP under the
  incumbent and accept the explained moves.

## 1. Diagnosis

### 1.1 Where the filter runs and why a fourth voter switches it on

`data_contract._hampel_filter_per_player` runs on **every non-pick row**, offense and IDP
alike, before the family cap and the blend: K = 2.75, scale = median absolute deviation
(MAD), absolute floor 1,000 Hill points, at least 4 voting observations, never fewer than
2 survivors. Picks are skipped.

* **n-dependence.** Below 4 observations nothing is ever examined. With DLF IDP held, no
  IDP row reaches 4 (IDP Show combined is freshness-quarantined), so the IDP side of the
  board has had no outlier handling at all. Restoring DLF puts **158** IDP rows at n ≥ 4.
* **MAD collapse.** At n = 4 the MAD is the mean of the two middle deviations, and the two
  middle votes straddle the median by construction, so it is small. Several votes are also
  near-identical by construction: value-direct sources share one market, and the IDP rank
  boards are translated onto the IDP Trade Calculator's rank backbone, so DLF IDP and
  FantasyPros IDP land on the same value whenever they agree on the ordinal. Aidan
  Hutchinson: IDP Trade Calculator 6,444, DLF 6,227, FantasyPros 6,227, Draft Sharks
  3,181 → MAD 108.5 → threshold max(2.75 × 108.5, 1,000) = **1,000** → Draft Sharks
  dropped.
* **Depth inconsistency.** The rule therefore becomes "drop any vote more than 1,000
  points from the median": 16% of value at 6,227, 50% at 2,000, and almost nothing in the
  deep tail. On the current board **90 of 130** rejections sit exactly on the floor
  (67 offense, 23 IDP).

### 1.2 Every rejection on the current board, classified

Board: `exports/latest/dynasty_data_2026-10-19.json` (scrape 2026-10-19T05:23:48Z,
sha256 `b639608f…e11c`), DLF IDP hold off, code `c36c4427ee`. Evidence per rejection is
in `diagnosis_2026-10-19.json` → `drops`.

| source | offense | IDP |
|---|---|---|
| Draft Sharks | 52 | 18 |
| FantasyPros (IDP / SF / Fitzmaurice) | 10 | 10 |
| DLF (SF / IDP) | 10 | 1 |
| Yahoo (Boone) | 7 | |
| KTC Crowd / Trades | 5 / 1 | |
| Dynasty Nerds | 4 | |
| IDP Trade Calculator | 2 | 3 |
| Flock / PFK / OTC / FantasyCalc | 3 / 2 / 1 / 1 | |
| **total** | **98** | **32** |

What the evidence was checked against, and what it found:

| check | what would make it a data error | found |
|---|---|---|
| identity | ambiguous match, several candidates, the source's own position in a different class, or its Sleeper id ≠ the row's | **0**: every row `canonical_id`, every match unambiguous; 107 of 130 carry a source position label and all agree |
| normalization | a pricing fallback, an IDP backbone fallback, or the source's whole board failing the scale screen | **0**: standard paths only (119 rank→Hill, 11 value-direct); no source board fails the screen (largest median shift 0.21 against 0.405) |
| staleness / corruption | a zero-weight vote, or a value the source has not held before | **0** zero-weight; **126 of 130** are the source's view on all 105 replayed boards (Hutchinson / Draft Sharks: same side, same size, 105 of 105) |

So all 130 are **legitimate disagreement**:

* 120 of 130 are **corroborated**: another provider family sits within 2x of the rejected
  vote. Two independent providers agreeing on an outlying view is disagreement, not error;
* 103 of 130 are **consistent with the source's own positional methodology** (within 2x
  once the source's median bias at that position is removed); the other 27 are
  player-specific views;
* the size of the disagreements: median 1.7x in implied rank, p90 2.5x, max 4.0x.

Examples (IDP):

| player | votes | incumbent | evidence |
|---|---|---|---|
| Aidan Hutchinson (DL) | IDPTC 6,444, DLF 6,227, FP 6,227, **DS 3,181** | DS dropped (floor) | DS ranks him 32nd IDP on its own board; held on 105 of 105 boards |
| Myles Garrett (DL) | IDPTC 5,399, FP 4,726, DLF 3,721, **DS 1,905** | DS dropped | DS's age-weighted 3/5/10-year projection view; 105 of 105 boards |
| CJ Allen (LB) | DLF 2,645 / 2,557, IDPTC 2,129, FP 2,095, **DS 5,741** | DS dropped | DS's young-LB view (its top 4 IDP are first- and second-year LBs); 102 of 105 boards |
| Trevin Wallace (LB) | DLF 1,517, FP 1,558, IDPTC 814, **DS 2,886** | DS dropped | corroborated within 2x by DLF and FantasyPros |
| Jacob Rodriguez (LB) | IDPTC 5,667, DLF 5,165 / 4,726, DS 4,376, **FP 1,578** | FP dropped | FantasyPros' view, 92 of 105 boards |

The owner's example holds exactly: three sources near 5,000 and Draft Sharks at 3,000 is
dropped by the incumbent (the MAD collapses) and kept by the policy (pinned by
`tests/api/test_outlier_policy.py::test_owner_example_three_sites_near_5000_keep_draft_sharks_at_3000`).

### 1.3 Offense is affected too

The same mechanism removes 98 offense votes per board today, with DLF's hold irrelevant to
them; Draft Sharks alone loses 52 (its QB-heavy, non-TE-premium methodology: Brock Bowers
is its 32nd asset). These rows mostly carry 10-14 families, where the count-aware blend
already trims the extremes, so the incumbent's drops move offense values little (§5).

### 1.4 Real data errors found in the replayed history

The 105-board replay found two genuine data errors, which is what an outlier policy exists
for:

1. **Rookie boards voting untranslated ranks** (complete boards 2026-08-18 → 2026-09-08,
   22 boards). `dlfRookieSf` and `flockFantasySfRookies` translate a rookie rank
   onto the overall board through `ktcCrowdSfTep`'s rookie ladder (`ROOKIE_LADDER_PAIRS`).
   Before `ktcCrowdSfTep.csv` existed (first committed 2026-09-09), today's code falls back
   to voting the within-class rank as an overall rank, so a rookie ranked 1st among rookies
   is priced as the 1st player overall: every vote ~5x too high in implied rank (median
   shift −1.66). The incumbent drops them row by row (56 of 56 `dlfRookieSf` votes on
   2026-08-18); the policy's board screen flags both boards and excludes them. This is a
   replay artifact for those dates (production then used another reference), **but the
   fallback is live code**: `scale_integrity_lost` already declares that excluding the
   reference breaks the rookie scale, and a user override that disables KTC Crowd reaches
   it.
2. **A transient IDP Trade Calculator offense glitch** on 2026-10-07 09:25Z and
   2026-10-08 14:12Z: against the consensus, its WR/RB votes were +0.24 (log) instead of
   the usual +0.09 and its QBs −0.16 instead of −0.03, consistent with a one-scrape
   format switch; the next scrape reverted. The incumbent drops 81-94 of those votes; the
   policy drops 1-2 and its board screen does not fire (median shift −0.20 against a
   0.405 limit). A real, moderate (~15%) error the policy does not catch.

## 2. Preregistration and order of work

| step | commit | time (UTC) |
|---|---|---|
| work claim | `6aa2800196` | 07:39 |
| **preregistration** (this directory's `PREREGISTRATION.md`) | **`b579a5fdd5`** | **pushed 07:56** |
| implementation (module, hook, flag, harness, tests) | `92fa036b27` | 08:15 |
| frozen-board replay (140 records, clean tree at `92fa036b27`) | — | 08:16 → 08:45 |
| diagnosis script owner-evidence section | `c36c4427ee` | 08:50 |

Before registration only the diagnosis board (outside the frozen set) had been examined;
see `PREREGISTRATION.md` §0.

## 3. Results on the frozen 105 complete boards

All 140 manifest boards were rebuilt at `92fa036b27` with a clean tree (three builds each,
DLF IDP hold OFF in all of them); the 105 complete boards are the decision population.
Every record passed the structural check: **every vote is identical across the three
builds** (140 / 140).

### 3.1 Verdict: NOT ELIGIBLE

| rule (PREREGISTRATION §5) | result |
|---|---|
| minimum sample (≥ 300 disputed M1 units, ≥ 10 days, ≥ 4 blocks) | met: 51,414 units, 54 origin days, 8 blocks |
| P1 upper95 ≤ +0.005 (non-inferior) | **passes**, and better: P1 = −0.0021 [−0.0026, −0.0014] |
| M7 adversarial gate | **fails**: AD1b, AD1d, AD2 below their bars; AD3 15 of 16 |
| no board-screen false positive | **fails by the letter**: 22 firings, all the rookie-ladder failure of §1.4 |
| M4 stability ratio upper95 ≤ 1.10 | passes: 1.014 [0.997, 1.029] |

**Verdict: NOT ELIGIBLE.** The adversarial gate alone decides it; the board-screen rule
decides it independently. The accuracy and stability rules both pass; on accuracy the
policy is better than the incumbent (P1 upper95 < 0). `outlier_disagreement_policy` stays OFF.

### 3.2 M1: agreement with a held-out source (primary)

Disputed units are (origin board, row, held-out family) where the method's survivor set
differs from the incumbent's on the votes left after the family is removed. P1 is the mean of
L_method − L_incumbent, where L = |ln consensus − ln held-out family's vote a horizon later|.
Negative means the method's consensus sits closer to the held-out source's later opinion.

| horizon | policy: disputed units | **policy P1 [95% CI]** | share closer | `idp-hampel-n3-v1` P1 (units) | no filter P1 (units) |
|---|---|---|---|---|---|
| **7 (primary)** | 51,414 | **−0.0021 [−0.0026, −0.0014]** | 52.7% | +0.030 [−0.109, +0.051] (364) | +0.0009 [−0.0012, +0.0028] (64,798) |
| 3 | 55,362 | −0.0023 [−0.0027, −0.0017] | 53.0% | +0.027 [−0.040, +0.046] (731) | +0.0007 [−0.0015, +0.0028] |
| 14 | 43,242 | −0.0016 [−0.0020, −0.0010] | 52.7% | +0.032 [−0.148, +0.051] (347) | +0.0017 [−0.0005, +0.0036] |
| 21 | 36,223 | −0.0011 [−0.0016, −0.0005] | 52.1% | +0.029 [−0.139, +0.044] (337) | +0.0026 [+0.0001, +0.0049] |

* The policy's consensus is **closer to held-out sources at every horizon**. The effect is
  small, 0.1-0.2% in log value per disputed unit: valid disagreement carries information,
  and keeping it does not cost accuracy. Removing the filter entirely is neutral to slightly
  worse; the policy's few rejections matter.
* Sensitivities (they report; they do not decide):

  | id | P1 at h = 7 |
  |---|---|
  | S1 all 140 archives | −0.0023 [−0.0029, −0.0018] |
  | S2 IDP / offense | −0.0074 [−0.0104, −0.0037] / −0.0013 [−0.0017, −0.0010] |
  | S4 persistence (target on the origin board) | −0.0024 [−0.0029, −0.0018] |
  | S5 per-row rule only, no board screen | −0.0008 [−0.0017, +0.0002] |
  | S6 DLF never held out | −0.0026 [−0.0031, −0.0021] |
  | S7 episode-deduplicated | −0.0022 [−0.0034, −0.0012] |

* S3 by held-out family: closer for 9 families (largest IDP Show −0.020, Draft Sharks −0.008,
  FantasyPros −0.005); **further for 5**: DLF +0.004 [+0.001, +0.007], IDP Trade Calculator
  +0.006 [+0.003, +0.009], Dynasty Nerds +0.005, OTC +0.002, Flock +0.001. The sources that
  sit closest to the cluster the incumbent keeps are predicted better by that cluster.

### 3.3 M7: adversarial suite (newest frozen board, seed 2033)

Pass = the corrupted vote is dropped, or the published value moves less than 10%.
Only material cases (≥ 10% harm with no filter at all) count.

| case | material / all | incumbent | `idp-hampel-n3-v1` | **policy** | gate | policy |
|---|---|---|---|---|---|---|
| AD1a vote ×5 | 303 / 730 | 65.0% | 96.4% | **93.7%** | 90% | pass |
| AD1b vote ×0.2 | 228 / 730 | 36.4% | 53.1% | **58.3%** | 90% | **fail** |
| AD1c vote ×20 | 333 / 730 | 67.9% | 97.3% | **97.9%** | 95% | pass |
| AD1d vote ×0.05 | 256 / 730 | 46.5% | 71.5% | **92.6%** | 95% | **fail** |
| AD2 misidentified player (≥ 100 ranks apart) | 127 / 657 | 31.5% | 49.6% | **15.0%** | 90% | **fail** |
| AD4 single-source spike (rank 150-400 → 9,000) | 97 / 226 | 89.7% | 100% | **100%** | 95% | pass |
| AD3 wrong-scale whole board (4 sources × 4 kinds) | 16 boards | no board check | no board check | **15 / 16 flagged** | 16 / 16 | **fail** (FantasyPros IDP reversed not flagged) |

* The policy beats the incumbent on every per-row case except AD2. The incumbent fails most
  on thin rows: at 3 families it passes 10% of AD1a and 5.5% of AD1b, because it never looks
  at fewer than 4 votes.
* **Why AD1b / AD1d fail**: a ×0.2 corruption of a vote that already sat above the field
  lands within 4x of it (not gross), and deep-tail corruptions fall under the absolute
  1,000-point floor while still moving a 3-4-vote row by 10% or more.
* **Why AD2 fails**: a misidentified player whose value is within 4x of the real one is
  indistinguishable from an opinion by distance. Any per-row rule that catches it would also
  drop the valid disagreements of §1.2. The defence belongs upstream, in identity
  resolution.

End-to-end through the full pipeline, flag ON, on the newest frozen board's own tree:

| check | result |
|---|---|
| E1 as registered: every `dynastyNerdsSfTep` rank doubled | **no-op**: 0 votes change (rank boards are dense re-ranked within the source), so nothing to catch |
| E1 reversed ranks | flagged (median absolute shift 1.00), second ranking pass, 284 of 284 votes excluded |
| E1b first page lost (top 150 rows missing, re-ranked from 1) | flagged (median shift −1.04), 134 of 134 votes excluded |
| E2 three far-apart pairs swapped in `flockFantasySf` | policy rejects 5 of 6 swapped votes (incumbent 6 of 6); kept: Breece Hall at 2,013 against 5,547 (2.8x) |

### 3.4 M5: what each filter rejects

| per complete board | incumbent | policy | n3 (restored state) |
|---|---|---|---|
| votes rejected, median (min-max) | 158 (114-248) | **1** (0-129) | 159 (115-249) |
| total over 105 boards | 17,621 | 2,763 | 17,732 |

* The policy's 2,763 are **2,678 board-screen exclusions** (the two rookie boards on the 22
  boards of §1.4) and **85 gross rejections**.
* On the 83 boards after the rookie ladder reference exists (from 2026-09-09) the policy
  rejects **0-2 votes per board**: Draft Sharks 54 (mostly Brock Bowers), KTC Trades 23,
  IDP Trade Calculator 4, KTC Crowd 3, Fantasy Navigator 1. The incumbent rejects 114-236.
* Board-screen firings on complete boards: 22, every one `dlfRookieSf` +
  `flockFantasySfRookies`, 2026-08-18 23:02Z → 2026-09-08 21:28Z.

### 3.5 M6: value changes on the newest frozen board (`dynasty_export_20261018_114711`)

Policy vs incumbent, both with DLF restored:

| class | rows moved | median moved | p99 | max |
|---|---|---|---|---|
| IDP | 31 of 396 | 16.4% | 32.1% | 92.7% |
| offense | 76 of 488 | 1.1% | 3.4% | 7.2% |
| picks (rookie-pool tether) | 35 of 144 | 1.1% | 5.6% | 5.9% |

Every move above 30%, each the incumbent dropping a vote the policy keeps (DLF's own vote is
in both builds):

| player | incumbent → policy | the vote the incumbent drops | the other votes |
|---|---|---|---|
| Trevin Wallace (LB) | 887 → 1,709 (+92.7%) | Draft Sharks 2,878 | DLF 1,538, FP 1,558, IDPTC 814 |
| CJ Allen (LB) | 2,133 → 3,572 (+67.5%) | Draft Sharks 5,741 | DLF 2,657 / 2,054, IDPTC 2,129, FP 2,095 |
| Trey Hendrickson (DL) | 1,516 → 2,245 (+48.1%) | IDP Trade Calculator 2,927 | FP 1,916, DLF 1,884, DS 1,474 |
| Nick Herbig (DL) | 1,635 → 2,335 (+42.8%) | IDP Trade Calculator 2,999 | DLF 2,007, FP 1,780, DS 1,604 |
| Barrett Carter (LB) | 2,044 → 2,701 (+32.1%) | Draft Sharks 3,706 | IDPTC 2,056, DLF 1,979, FP 1,876 |

These are the same mechanism as §5 read from the other side: rows of four votes where three
cluster and the fourth disagrees by ~2x. `idp-hampel-n3-v1` in the restored state moves one
row (Kool-Aid McKinstry, −33%), because with DLF voting almost every IDP row already has
four votes.

### 3.6 M3, M4, M2

**M3, what happened to the votes the policy keeps and the incumbent drops** (K side;
the X side has only 8-25 observations):

| horizon | K observations | LED | ABANDONED by own source | DELISTED | UNRESOLVED (view held) | mean lead / retreat share |
|---|---|---|---|---|---|---|
| 3 | 7,700 | 0 | 180 (2.3%) | 65 | 7,455 | 0.004 / 0.026 |
| **7** | 7,140 | 15 | **330 (4.6%)** | 103 | **6,692 (93.7%)** | 0.005 / 0.047 |
| 14 | 6,007 | 54 | 386 (6.4%) | 84 | 5,483 | 0.007 / 0.062 |
| 21 | 5,037 | 131 | 377 (7.5%) | 77 | 4,452 | 0.010 / 0.073 |

The great majority of rescued observations are views their source keeps holding, not
transient errors it later corrects. The 4.6-7.5% later abandoned are the candidates for
transient errors (the IDP Trade Calculator glitch of §1.4 is among them).

**M4, board stability** (mean daily |Δ ln value|, consecutive origin days, 60 pairs):
incumbent 0.0190, policy 0.0193, ratio **1.014 [0.997, 1.029]** (passes ≤ 1.10). IDP
1.048 [1.021, 1.076] (the IDP side moves ~5% more day to day, because rescued Draft Sharks /
FantasyPros views now move with their sources); offense 0.977 [0.966, 0.987].

* **M2** (G1 on published values, reported, not decisive): +0.024 [+0.017, +0.031] at
  h = 7. The policy's published values sit further from the equal-family median of the
  families the incumbent kept, which is the bias stated in advance (that target is built from
  the incumbent's survivors). `idp-hampel-n3-v1`: −0.067 [−0.090, −0.024] on 31 rows.
* **Emulator fidelity** (M1's consensus vs the published blend, incumbent): 70.6% of 49,002 rows within 0.5%, 76.6% within 2%, median 0.02%, p90 6.7% (the IDP anchor shrinkage and post-blend overrides are not emulated; the emulator is the same for every method).

### 3.7 On PR #1817's board

`pr1817_board_check.json` (`scripts/outlier_policy_check_branch_board.py`): #1817's own
build at `7f4153c089` (DLF IDP restored by default), same payload, with this branch's policy
applied to its stamped votes:

* the incumbent's 31 newly dropped other-source votes on 30 rows (Draft Sharks IDP 18,
  FantasyPros IDP 10, IDP Trade Calculator 3; LB 20, DL 9, DB 2): **the policy keeps 31 of
  31**;
* all incumbent rejections: IDP 32 → the policy keeps 32; offense 107 → keeps 106 (it drops
  Draft Sharks on Brock Bowers);
* the board screen flags nothing.


## 4. `idp-hampel-n3-v1`, re-run exactly as preregistered

`scripts/idp_evidence_challengers.py backfill` (both shards) and `evaluate-n3`, unmodified,
at `c36c4427ee`, into `n3_reproduction.json`. Its preregistration was not touched.

* **Verdict: INSUFFICIENT** (117 evaluable units, 17 origin days, **3** week-blocks of the
  4 required). P1 at h = 7 = **+0.1124 [+0.1009, +0.1274]**: the challenger sits further
  from DLF IDP's held-out later vote.
* The output is **identical** to the committed
  `../idp-outlier-n3-2026-10-18/evaluation_historical_replay.json` except the code SHA
  (`58161d8e02` → `c36c4427ee`): same numbers, same verdict, same per-board census.
* In the directive's restored state (DLF voting) it is evaluated here only descriptively
  (the `n3` columns): it drops slightly more than the incumbent and moves IDP values away
  from held-out evidence (M1 P1 +0.030 [−0.109, +0.051] on only 364 disputed units at h = 7; it differs from the incumbent on one row of the newest board).

## 5. Owner evidence (directive §9, outlier part): DLF restored under each filter

Current board (2026-10-19 05:23Z), five builds through the canonical pipeline
(`diagnosis_2026-10-19.json` → `ownerEvidence`). "Production" is today's served state (DLF
IDP held, incumbent filter). Relative |Δ| of `rankDerivedValue`:

| change | class | rows moved | median moved | p90 | p99 | max |
|---|---|---|---|---|---|---|
| DLF IDP's own vote alone (filter off in both builds) | IDP | 179 of 397 | 1.0% | 2.1% | 4.3% | **5.4%** |
| production → DLF restored, **incumbent filter** | IDP | 179 of 397 | 1.5% | 3.0% | 41.4% | **53.8%** |
| production → DLF restored, **policy** | IDP | 179 of 397 | 1.0% | 2.1% | 4.3% | **5.4%** |
| production → DLF restored, policy | offense | 72 of 488 | 1.5% | 0.9% | 3.9% | 35.5% |
| production → DLF restored, policy | picks (rookie-pool tether) | 48 of 144 | 0.9% | 1.4% | 2.8% | 3.1% |

Under the policy the IDP side moves by **exactly** DLF's own vote: the two rows of the table
are identical. Under the incumbent the same restoration moves seven IDP players by 34-54%,
none of it DLF's own doing.

Votes on the board (non-pick rows):

| build | IDP votes / rejected | offense votes / rejected |
|---|---|---|
| production | 946 / 0 | 5,488 / 98 |
| DLF restored, incumbent | 1,146 / **32** | 5,488 / 98 |
| DLF restored, policy | 1,146 / **0** | 5,488 / **1** |

**Every move above 30%, with its cause.** Each move decomposes exactly into the builds'
differences: the incumbent's drops in production removed, DLF's own vote added, and the
filter's drops with DLF voting.

Production → DLF restored under the **policy**: one row.

| player | production → policy | cause |
|---|---|---|
| LaJohntay Wester (WR) | 651 → 882 (+35.5%) | not DLF: Flock (1,889) values him ~3x KTC Crowd / Trades (594 / 596) and OTC (930). The incumbent drops Flock in production today (1,126 points off the median); the policy keeps it (2.9x in implied rank, under the 4x gross line). A deep player on four votes |

Production → DLF restored under the **incumbent** (what restoring DLF does if this PR is
not used): seven rows, every one driven by the filter, not by DLF's vote.

| player | production → incumbent | DLF's own vote | filter's drop with DLF voting |
|---|---|---|---|
| Trevin Wallace (LB) | 1,916 → 885 (−53.8%) | −0.1% | Draft Sharks 2,886 dropped (−53.8%) |
| Myles Garrett (DL) | 3,597 → 5,267 (+46.4%) | −1.8% | Draft Sharks 1,905 dropped (+49.1%) |
| CJ Allen (LB) | 3,918 → 2,162 (−44.8%) | +0.9% | Draft Sharks 5,741 dropped (−45.3%) |
| T.J. Watt (DL) | 2,418 → 3,431 (+41.9%) | +0.7% | Draft Sharks 1,450 dropped (+41.0%) |
| Josiah Trotter (LB) | 2,390 → 3,379 (+41.4%) | +4.3% | Draft Sharks 1,677 and FantasyPros 1,868 dropped (+35.6%) |
| Will Anderson (DL) | 4,395 → 5,966 (+35.8%) | +0.9% | Draft Sharks 2,878 dropped (+34.5%) |
| Aidan Hutchinson (DL) | 4,802 → 6,422 (+33.7%) | 0.0% | Draft Sharks 3,181 dropped (+33.7%) |

Each of those dropped votes is classified in §1.2 as legitimate disagreement held on
(almost) every replayed board.

Other §9 measures for the policy build against production:

* **Top-N membership**: top-24 / 50 / 100 unchanged; top-200 two swaps (both DLF's own vote).
  Under the incumbent with DLF: top-50 two, top-100 two, top-200 five.
* **Confidence**: IDP 25 low → medium and 21 medium → low (DLF's own vote: the same counts
  appear with the filter off); offense 6 high → medium, 2 medium → high, 2 medium → low
  (rescued votes now enter the agreement axis).
* **Two-way player (Travis Hunter)**: 3,738 → 3,468 (−7.2%) under the policy and 3,458
  (−7.5%) under the incumbent; the cause is DLF IDP's vote on his DB side in both.
* **Single-source haircut**: unchanged; the policy never leaves a multi-family row with one
  family (guard), and on this board it removes one vote on a 14-vote row.


## 6. Deviations and disclosures (stated so they can be challenged)

* **Adversarial smoke test before the frozen run.** After `92fa036b27`, the M7 code was run
  once on the diagnosis board (outside the frozen set) as an implementation check. It
  showed the gate would likely fail on AD1b, AD1d, AD2 and AD3. **Nothing was changed in
  response**; the frozen-board result below is the registered one.
* **E1 as registered is a no-op.** "Every rank of `dynastyNerdsSfTep.csv` doubled" changes
  no vote: rank-signal boards are dense re-ranked within the source, so a uniform rank
  scale cannot reach the board. Registered and reported (0 votes changed); two
  end-to-end corruptions that do reach the board were added and reported beside it.
* **The board-screen false-positive rule was mis-specified in advance.** It counts a firing
  as a true positive only with a structural CSV change against neighbouring boards. The
  rookie-board firings (§1.4) are a persistent translation failure with no CSV change, so
  **by the letter they are false positives**, and the verdict applies them as such. In
  substance they are a real normalization failure that the incumbent also removes vote by
  vote. Both readings are reported.
* **M2 was added to the harness after the main evaluation started** (`evaluation_m2_g1.json`);
  its definition is the registered one.

## 7. Recommendation and the owner decision

**The preregistered verdict is NOT ELIGIBLE.** The flag stays OFF and nothing here
activates it. In the release train, PR #1817 ships with the DLF IDP hold re-applied as a
temporary hold "pending the outlier fix" (coordinator decision, 2026-10-19), so production
values do not move because of this question.

What the evidence establishes, independent of the verdict:

* every vote the incumbent rejects on today's board is a correctly identified, normally
  priced, long-held opinion (§1.2), and restoring DLF under the incumbent moves seven IDP
  players by 34-54% through those rejections alone (§5);
* the policy keeps them, moves IDP values only by DLF's own vote, and beats the incumbent on
  five of the six per-row corruption cases (§3.3);
* but it misses its own absolute bars on three of the six per-row cases (AD1b, AD1d, AD2) and
  one of sixteen whole-board cases, and it does not catch the transient IDP Trade Calculator
  offense glitch the incumbent partly removed (§1.4).

**The owner decision, three options:**

| option | what it means | evidence for | evidence against |
|---|---|---|---|
| **(a) activate `outlier-corroborated-v1` despite the failed gate** | an explicit owner override of the preregistered rule (the rule itself cannot be changed after the fact); independent fresh-context validation first | keeps all 130 valid opinions; IDP restore moves ≤ 5.4%; better than the incumbent on AD1a-d, AD4 and whole-board errors | fails 3 of 6 per-row gates and AD3; misses non-gross misidentification (15% vs the incumbent's 31.5%) and the IDPTC format glitch |
| **(b) preregister `outlier-corroborated-v2`** | a new preregistration before any run: a per-position board screen (would have caught the IDPTC glitch: QB −0.16, WR/RB +0.24), a deep-tail floor relative to value instead of the absolute 1,000 points (AD1b/AD1d), a true-positive rule for persistent translation failures; then the same frozen evaluation and gate | addresses every named miss except AD2 | takes another evaluation cycle; AD2 stays unreachable for any rule that keeps valid disagreement (it belongs to identity resolution) |
| **(c) restore DLF IDP under the incumbent filter** | lift the hold with today's filter and accept the moves of §5, now explained | no new methodology | removes Draft Sharks / FantasyPros / IDP Trade Calculator opinions on ~30 IDP rows, contrary to §6 ("a source should not be removed simply because its ranking is significantly higher or lower") |

Independent of the choice, two named follow-ups that are **not** filter questions:

* **The rookie-ladder fallback** (`ROOKIE_LADDER_PAIRS`): when `ktcCrowdSfTep` is excluded
  (a user override, or a missing board), rookie boards vote their within-class rank as an
  overall rank, ~5x too high. It should refuse those votes rather than fall back; today only
  the outlier filter (either one) contains it.
* After PR #1817 merges, the policy's `family_of` switches to #1817's row-scoped lineage
  (`_row_family_of`) in a follow-up commit on this branch, so the corroboration and
  reference rules see the same families as the family cap.


## 8. Reproduce

Full git history; about 30 minutes for the replay on 2 cores, then the evaluations:

```bash
python scripts/outlier_policy_replay.py backfill --shard 0/2   # and --shard 1/2
python scripts/outlier_policy_replay.py adversarial --out docs/valuation/evidence/outlier-disagreement-2026-10-19/adversarial_suite.json
python scripts/outlier_policy_replay.py evaluate --out docs/valuation/evidence/outlier-disagreement-2026-10-19/evaluation_historical_replay.json
python scripts/outlier_policy_replay.py evaluate-m2 --out docs/valuation/evidence/outlier-disagreement-2026-10-19/evaluation_m2_g1.json
python scripts/outlier_policy_diagnose.py --history data/outlier_policy_replay --owner-evidence \
    --out docs/valuation/evidence/outlier-disagreement-2026-10-19/diagnosis_2026-10-19.json
python scripts/idp_evidence_challengers.py backfill --shard 0/2   # and --shard 1/2
python scripts/idp_evidence_challengers.py evaluate-n3 --out docs/valuation/evidence/outlier-disagreement-2026-10-19/n3_reproduction.json
```

