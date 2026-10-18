# IDP deep-tail native-value challenger: evidence (2026-10-18)

`idp-deep-tail-native-v1` (flag `idp_deep_tail_native_challenger`, default **OFF**).

* **What it does.** An IDP row's `shared_market` rank vote at effective rank
  500 < r ≤ 904 is priced at the IDP Trade Calculator's own native value for rank r
  (`src/canonical/deep_tail_native.py`), not at the Hill / tail extrapolation.
* **What it does not touch.** No Hill constant, reference N, tail saturation rank or
  rank coordinate changes.

Authority: owner closeout 2026-10-18, PART 2, Decision 6.

* `PREREGISTRATION.md` was committed and pushed in `341099255b` at 20:11 UTC, **before**
  the challenger was implemented (`58161d8e02`) or any result was computed. It is
  unchanged since.
* **No flag was flipped and nothing was promoted. The incumbent Hill method stays in
  production.**

Every number below comes from archived inputs rebuilt through one replay code revision
(`58161d8e02`, clean tree, all 140 boards). None of it is what production served on that
day.

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | frozen |
| `evaluation_historical_replay.json` | C1 / B1 / R1 / H1, secondary horizons, families, board rails per board, structural guards, S1–S9, D1–D5 |

## Preregistered verdict: PROMOTION-ELIGIBLE, then the governance overlay: AUTO_PROMOTION_BLOCKED

All seven checks in the PROMOTION-ELIGIBLE row of PREREGISTRATION §3 hold. No NOT BETTER
trigger fires, and the minimum sample is met.

| check | result |
|---|---|
| C1 upper95 < 0 at h = 7 | **−0.0703 [−0.0722, −0.0681]**, n = 16,223 votes, 54 origin days, 8 blocks |
| C1 < 0 at ≥ 2 of 3 secondary horizons | 3 of 3: h3 −0.0698, h14 −0.0701, h21 −0.0691 (every upper95 < 0) |
| C1 ≤ 0 in every family with ≥ 30 votes | DL −0.0374 (6,635), LB −0.0730 (2,686), DB −0.1008 (6,902) |
| R1 lower95 ≥ −0.005 | **−0.00078 [−0.00168, +0.00010]**, 54 days, mean 166 rows; ρ_inc 0.8534 vs ρ_ch 0.8527 |
| H1 upper95 ≤ 1.10 | **0.959 [0.931, 0.991]**: the challenger's daily IDP moves are 4% smaller |
| guards hold | scope guard 0 violations; S guard 0 violations |
| rails hold on every complete board | 105 / 105. Worst board: max move 55.5% (rail 65%), p90 8.3% (45%), p90 rank shift 40 (125), top-25 / top-100 overlap 25 / 100 |

Governance overlay (§3), applied as written:

* Gate 7 of `docs/valuation/HILL_AUTOPILOT_V2.md` needs an eligible independent
  validation target. No IDP target qualifies:
  * DLF IDP is measured-dependent on the IDP Trade Calculator;
  * the IDP Show's IDP order is a copy of it.
* So the outcome is `AUTO_PROMOTION_BLOCKED: no_independent_validation_target`.
* Per §6, PROMOTION-ELIGIBLE leads only to an **independent fresh-context review** and an
  **owner decision**. Nothing flips a flag.

## Read this before treating it as a win

These points come from the same frozen run. They do not change the verdict, but a
reviewer must weigh them. The owner's bar is "convincingly improves".

1. **C1 is calibration against the challenger's own provider, as declared.**
   * The target and the ladder are both the IDP Trade Calculator. Leave-player-out and
     the 7-day horizon stop a player's own number from grading itself; S4 (in-sample
     ladder) is identical to 4 decimals.
   * The improvement is mostly level. Median signed log error falls from +0.253
     (incumbent prices deep rank votes 29% above the later market value) to +0.207.
   * The challenger still over-prices deep votes. It **narrows** the gap; it does not
     close it.
2. **The non-circular primary is flat, and slightly negative.**
   * R1 (board order vs DLF IDP's later order): −0.00078, with its CI straddling 0.
     It is non-inferior, not better.
   * On disputed rows only: −0.0035 [−0.0108, +0.0050].
   * S1 (all 140 archives): −0.00158 [−0.00291, **−0.00041**]. Its upper95 is below 0,
     which would be a NOT BETTER trigger if S1 decided. It does not, but it shows order
     against the one held-out opinion does not improve and may slip.
   * S3, LB: −0.00043 [−0.00077, −0.00013], the same slip within a family.
3. **A step at rank 500, not stated in §1.**
   * §1 says the challenger preserves every source's order exactly. That holds **within
     the repriced band**: 0 inversions, a preregistered guard.
   * It does not hold **across** the band's edge. On the median board, N(500.5) /
     Hill(500) = 1.046 (range 0.890–1.055).
   * A deep-band vote just past rank 500 is priced up to ~5% **above** a vote just
     inside it. Measured: 101 Draft Sharks and 99 IDP Show combined order inversions at
     the boundary, over 105 boards.
   * This is a discontinuity introduced by the band definition. It is a defect a
     promotion would have to repair, which would be a new preregistered variant, not a
     tweak to this one.
4. **Confidence moves.**
   * 1,423 IDP row-boards go medium → low and 1,016 go low → medium: net more low.
   * The agreement axis is measured against the moved value.
5. **Coverage.**
   * Repriced votes: Draft Sharks IDP 16,269; FantasyPros IDP 9,692; IDP Show combined
     8,320 (only while it voted).
   * By band: 501–600: 15,789; 601–700: 18,041; 701–800: 451. Nothing deeper; no
     deep-band vote fell outside the ladder.
   * S6 (players the IDP Trade Calculator did not list at origin, out of sample by
     player): only 7 votes, too few to read.
6. **Size.**
   * Median ln(native / Hill) per band: −0.078 (501–600), −0.151 (601–700),
     −0.118 (701–800). That is smaller than the −0.336 N-1 measured, which compared the
     calculator's own votes against Hill at the calculator's own ranks.
   * Pooled over boards, 23,044 IDP row-boards move: median 4.3%, p90 10.0%, max 55.5%.
   * IDP top-24 / 50 / 100 membership churn on the newest board: 0 / 0 / 0.
   * 16,663 of 21,408 moved rows with an own IDP Trade Calculator vote move **toward**
     that vote.

**Bottom line.** Under the frozen rule the challenger passes: it calibrates deep IDP rank
votes closer to the one IDP market's level without measurable damage to order, stability
or the board.

It does **not** show an improvement on any target independent of that market. It also
carries a ~5% step at rank 500. That is not "convincing improvement" on independent
evidence, and the governance overlay blocks automatic promotion anyway. **Recommendation
for the owner decision: retain the incumbent.** If the direction is wanted, preregister a
continuous variant that removes the rank-500 step, to be judged on boards published after
its registration.

## Implementation and pins

* **Code.** One revision, `58161d8e02`, clean tree.
  `scripts/idp_evidence_challengers.py backfill` built four variants per board:
  incumbent; n = 3; DLF hold off (read for DLF's raw rank, R1's target); deep-tail. The
  pins are in each record.
* **Dataset.** The frozen manifest of `../idp-outlier-n3-2026-10-18/`: 105 complete
  boards recorded out of 105 expected. One pruned archive was recovered byte-exact from
  git; see that README.
* **The ladder captured in the build.** It is captured from the exact call the challenger
  build made (`_idp_trade_calc_native_points`), 830–895 points per board. C1's
  leave-player-out ladders are rebuilt from those points with the same function.
* **Default path byte-identical.** `golden_board.py` before (`3bc9cbfcec`) and after
  gives the same sha256 (`3c77f550…`), and `board_diff.py --expect-no-value-change`
  passes. `tests/api/test_idp_deep_tail_native_challenger.py` pins OFF == incumbent and
  checks that OFF never builds a ladder.
* **Bootstrap.** 7-day blocks, 4,000 resamples, seed 2031. Means use a per-block-sum form
  of `outcomes.block_bootstrap`: same draws, same percentile rule, pinned equal by
  `tests/robust_filter_shadow/test_idp_challengers.py`.

## Deviations and interpretations

* **Scope guard couplings.** These are counted, not violations:

  | coupling | rows (all boards) |
  |---|---|
  | board-wide ordinals | 31,280 |
  | crossing the published-rank cap (`offCapPlayerValue`, `idpRank`, `blendedSourceRank` move while votes and value do not) | 1,049 |
  | rookie-pool tether picks | 1,400 |

  §3 names board-wide ordinals and the tether. Rank-cap membership is an ordinal fact of
  the same kind.
* **Outlier decisions that moved.** On 52 IDP row-boards the outlier filter's decision
  changed because repriced values changed. §3 allows this; those rows are excluded from
  the weight and source-count identity check, as §3 says.
* **The boundary inversion (point 3 above)** is reported as a finding. The preregistered
  structural guard covers order within the repriced band only, and it holds there.
* No definition, threshold, seed or dataset changed after results were seen.

Reproduce:

```bash
python scripts/idp_evidence_challengers.py backfill --shard 0/2   # and --shard 1/2
python scripts/idp_evidence_challengers.py evaluate-deep-tail \
    --out docs/valuation/evidence/idp-deep-tail-native-2026-10-18/evaluation_historical_replay.json
```

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
