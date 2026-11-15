# Per-vote rank-space Hampel challenger: evidence (2026-10-17, FOLLOW-UP)

A **separate follow-up experiment**, not a correction of the original rank-space
experiment. The original (`../rank-space-hampel-2026-10-17/`,
`rank-space-hampel-v1`) keeps its preregistered verdict **NOT BETTER**
(Δ −0.0127 [−0.0204, −0.0053]); none of its files, its flag or its code changed.

The challenger here is `rank-space-hampel-per-vote-v1`
(`rank_space_hampel_per_vote_challenger`): the served per-player Hampel filter
with the same K, min_n, guards and floor rule, computed on each vote's own
percentile coordinate. Each vote is inverted through the forward map that
produced it: the TE transform first, then the curve. **No flag was flipped and
nothing was promoted.** The flag ships OFF. The production filter is unchanged.

Every number below comes from **archived inputs rebuilt through one replay code
revision**. None of it is what production served on that day.

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | committed in `d8116ee12` and pushed at 2026-10-17 22:25 UTC, **before** the challenger was implemented or run |
| `evaluation_historical_replay.json` | the preregistered evaluation: primary, S1–S6 and the offense non-TE / TE / IDP segments (seed 2027) |
| `summary_historical_replay.json` | a per-board census of all 138 replayed boards |
| `diagnostics_historical_replay.json` | D1–D6, player-level disagreements and the Puka Nacua diagnostic |
| `precheck_implementation_check.json` | the pre-run implementation check on two archives (not evidence) |

## Preregistered verdict: INCONCLUSIVE

The frozen rule is the inherited §5, primary horizon h = 7. **It returns
INCONCLUSIVE**: the challenger shows no detectable advantage. PREREGISTRATION §4
says what follows from that, and all of it applies:

- this experiment is **closed** with an undetermined, no-advantage conclusion;
- the production filter is **retained**;
- `rank_space_hampel_per_vote_challenger` stays **OFF**;
- no follow-up variant is implied;
- no owner review is requested, because the rule did not return
  PROMOTION-ELIGIBLE.

The rule's three checks:

- **P1.** Δ = mean_K(m) − mean_X(m) = **−0.0071, 95% CI [−0.0229, +0.0076]**.
  - The CI straddles 0, so the rule's NOT BETTER clause (upper95 < 0) does not
    fire.
  - Its PROMOTION-ELIGIBLE clause (lower95 > 0) does not fire either.
- **G1.** **−0.0006, 95% CI [−0.0041, +0.0031]**. The upper bound is below the
  +0.005 margin, so the published values are non-inferior. G1 lower95 is not
  above 0, so G1 does not trigger NOT BETTER.
- **Secondary horizons.** Δ is positive at **0 of 3**. Promotion would need 2.

Minimum sample is met:

| requirement | needed | observed |
|---|---|---|
| K observations | ≥ 30 | 3,699 |
| X observations | ≥ 30 | 12,928 |
| origin days | ≥ 10 | 53 |
| week-blocks | ≥ 4 | 8 |

The inherited code also prints an `accumulation` block for an INCONCLUSIVE
result. Its "1 block" figure says the current CI half-width (0.0152) is already
smaller than the minimum effect of interest (|Δ| = 0.10). It is **not** a request
to gather more data. An effect of 0.10 of the gap in either direction would have
been visible; none is.

## Inputs (pinned)

- **Boards.** The frozen dataset is the same 138 archives as the original
  replay. The `payloadSha256` set is **identical** to the original
  `summary_historical_replay.json`.
  - 103 boards are complete (2026-08-18 → 2026-10-17). They are the primary
    population.
  - The other 35 are used in S1 only.
- **Rebuild procedure.** The same as the original replay:
  - the archive's payload;
  - `CSVs/site_raw/` as committed with that archive, overlaid with the archive's
    own `site_raw/`;
  - dataset state replayed from git history;
  - freshness evaluated at each `scrapeTimestamp`;
  - `value_replay.build` → `build_api_data_contract(csv_root=…)`.
- **Code.** All 138 records were built at `de33727a9`:
  - `workingTreeDirty: false`;
  - one `pipelineFingerprint`;
  - written in one run, about 18 minutes.
- **Variants.** Two builds per board. Both pin
  `joint_outlier_sparse_challenger`, `joint_sparse_limited_evidence` and
  `rank_space_hampel_challenger` OFF. Only the per-vote flag differs.
- **Ledger.** `data/robust_filter_shadow_rank_space_per_vote/` (gitignored).
- **Incumbent identity.** On every one of the 138 boards, the incumbent's
  `incumbentDrops` and `filterRows` equal the original replay's numbers. The
  champion is the same filter on the same inputs.
- **Default path byte-identical.** The full `playersArray` JSON of
  `dynasty_export_20261005_152048` and `dynasty_export_20261017_185402` was
  rebuilt from point-in-time inputs at the pre-implementation commit and again
  after the implementation. It is identical byte for byte.
  `tests/api/test_rank_space_hampel_per_vote_challenger.py` pins OFF ==
  incumbent and checks that OFF never calls the challenger.
- **Reproduction from stamps.** Re-running both filters on the integer-stamped
  votes, over the complete boards' listed filter rows:

  | filter | rows reproduced |
  |---|---|
  | incumbent | 26,936 / 26,954 |
  | challenger | 26,927 / 26,954 |

  The misses come from integer rounding of the stamps.

## What the challenger does (103 complete boards)

| per board | median | range | total |
|---|---|---|---|
| filter rows | 639 | 404–688 | 61,376 |
| rows where the filters disagree | 266 | 153–347 | 26,940 |
| K: incumbent drops, challenger keeps | 71 | 41–142 | 7,016 |
| X: incumbent keeps, challenger drops | 280 | 113–330 | 26,939 |
| incumbent drops / challenger drops | 145 / 359 | — | 15,500 / 35,423 |
| rows whose published value moved | 307 | 189–365 | 30,616 |

Top-N churn (incumbent members missing from the challenger's top N):

| depth | swaps | boards with any change |
|---|---|---|
| top 50 | 137 | 64 of 103 |
| top 100 | 222 | 85 of 103 |
| top 200 | 302 | 85 of 103 |
| top 400 | 422 | 103 of 103 |

The challenger drops **2.3×** as many observations as the incumbent. The
original challenger dropped 1.06× as many.

## Preregistered evaluation (seed 2027)

Primary population: 103 complete boards, 60 board days, 53 paired origin days at
h = 7, 8 week-blocks, 4,000 resamples.

| horizon | mean *m*, K (n) | mean *m*, X (n) | **Δ = K − X** [95% CI] | days / blocks | **G1** [95% CI] (rows) | S5 (G1 vs persistence) |
|---|---|---|---|---|---|---|
| **7 (primary)** | +0.0054 [−0.0009, +0.0109] (3,699) | +0.0125 [−0.0025, +0.0287] (12,928) | **−0.0071 [−0.0229, +0.0076]** | 53 / 8 | **−0.0006 [−0.0041, +0.0031]** (13,473) | −0.0003 [−0.0013, +0.0007] |
| 3 | +0.0053 [+0.0030, +0.0077] (3,955) | +0.0053 [−0.0032, +0.0149] (13,972) | −0.0001 [−0.0104, +0.0097] | 57 / 9 | −0.0008 [−0.0040, +0.0027] | −0.0003 [−0.0008, +0.0003] |
| 14 | +0.0065 [−0.0012, +0.0133] (3,155) | +0.0206 [−0.0039, +0.0506] (10,793) | −0.0142 [−0.0408, +0.0090] | 46 / 7 | +0.0005 [−0.0020, +0.0037] | +0.0001 [−0.0008, +0.0013] |
| 21 | +0.0096 [−0.0014, +0.0195] (2,702) | +0.0311 [+0.0042, +0.0608] (9,143) | −0.0215 [−0.0462, +0.0001] | 40 / 6 | +0.0004 [−0.0021, +0.0034] | +0.0002 [−0.0008, +0.0013] |

Context group R (both filters drop) at h = 7: 5,119 observations.

Outcome classes at h = 7:

| group | LED | ABANDONED | DELISTED | UNRESOLVED | mean retreat |
|---|---|---|---|---|---|
| K | 10 | 213 | 125 | 3,351 | 0.057 |
| X | 1,550 | 840 | 486 | 10,052 | 0.039 |
| R | 2 | 790 | 80 | 4,247 | 0.156 |

**Reading.** Every Δ point estimate is ≤ 0. The longer the horizon, the more
the observations the challenger newly rejects (X) were led-to:

- the X mean lead share rises from 0.005 at 3 days to 0.031 at 21 days;
- 1,550 X observations are LED at h = 7, against 10 for K.

The intervals are wide because X is large and heterogeneous, so the rule does
not separate the two filters. This reading is descriptive. It does not change
the verdict.

### Required segment reports (they report; they do not decide)

Position is the origin row's `position`. Every judged observation was classified;
none was left unclassified. Segment counts sum to the primary's K and X.

| segment | h | K n | X n | Δ [95% CI] | G1 [95% CI] | the §5 rule applied to the segment alone |
|---|---|---|---|---|---|---|
| **offense non-TE** | 7 | 1,961 | 9,996 | −0.0022 [−0.0264, +0.0177] | +0.0018 [−0.0006, +0.0050] | inconclusive |
| | 3 | 2,155 | 10,861 | +0.0030 [−0.0112, +0.0150] | +0.0013 [−0.0011, +0.0044] | |
| | 14 | 1,625 | 8,370 | −0.0181 [−0.0569, +0.0135] | +0.0026 [+0.0003, +0.0058] | |
| | 21 | 1,367 | 7,092 | −0.0352 [−0.0723, +0.0022] | +0.0033 [+0.0012, +0.0061] | |
| **TE** | 7 | 1,139 | 1,780 | −0.0023 [−0.0416, +0.0289] | **+0.0023 [+0.0011, +0.0035]** | not better (G1 lower95 > 0) |
| | 3 | 1,186 | 1,926 | +0.0020 [−0.0192, +0.0203] | +0.0023 [+0.0005, +0.0037] | |
| | 14 | 1,035 | 1,473 | +0.0271 [−0.0120, +0.0562] | +0.0005 [−0.0005, +0.0014] | |
| | 21 | 921 | 1,249 | +0.0517 [+0.0152, +0.0813] | −0.0010 [−0.0040, +0.0017] | |
| **IDP** | 7 | 599 | 1,152 | **−0.0186 [−0.0326, −0.0044]** | −0.0186 [−0.0358, −0.0033] | not better (Δ upper95 < 0) |
| | 3 | 614 | 1,185 | −0.0056 [−0.0109, −0.0009] | −0.0184 [−0.0330, −0.0037] | |
| | 14 | 495 | 950 | −0.0371 [−0.0700, −0.0107] | −0.0124 [−0.0218, +0.0005] | |
| | 21 | 414 | 802 | −0.0461 [−0.0788, −0.0165] | −0.0155 [−0.0293, +0.0016] | |

- **Offense non-TE.** Undetermined at h = 7. G1 drifts against the challenger at
  14 and 21 days.
- **TE.** The challenger's published TE values sit slightly further from the
  later consensus at h = 7 (G1 +0.0023, CI above 0). Its TE rescues are led-to
  more at 21 days (Δ +0.0517, CI above 0). The segment is mixed, not a pass.
- **IDP.** The rescued IDP evidence is led-to less than what the challenger
  rejects, at every horizon. The published IDP values nevertheless sit closer to
  the later consensus (G1 < 0). That is the same pattern as the original
  experiment's S3 IDP.

These are reports, not decisions.

### Sensitivities S1–S6 (they report; they do not decide)

| id | population | Δ at h = 7 [95% CI] | G1 [95% CI] | the rule applied alone |
|---|---|---|---|---|
| S1 | all 138 archives (13 blocks) | −0.0047 [−0.0176, +0.0086] | +0.0023 [−0.0016, +0.0070] | inconclusive |
| S2 | episode-deduplicated (619 K / 1,594 X) | +0.0080 [−0.0149, +0.0291] | −0.0006 [−0.0041, +0.0031] | inconclusive (Δ > 0 at 3 of 3 secondary horizons, all CIs span 0) |
| S3 | offense | −0.0031 [−0.0200, +0.0114] | +0.0019 [−0.0003, +0.0046] | inconclusive |
| S3 | IDP | −0.0186 [−0.0326, −0.0044] | −0.0186 [−0.0358, −0.0033] | not better (Δ) |
| S4 | KTC Crowd/Trades split era (from 2026-09-09; 5 blocks) | −0.0030 [−0.0281, +0.0198] | −0.0031 [−0.0074, −0.0005] | inconclusive |
| S5 | G1 relative to persistence | — | −0.0003 [−0.0013, +0.0007] | — |
| S6 | KTC families merged for targets | −0.0062 [−0.0206, +0.0063] | −0.0004 [−0.0038, +0.0034] | inconclusive |

- No sensitivity reaches PROMOTION-ELIGIBLE.
- S3 IDP alone reads NOT BETTER.
- S2 is the only reading with a positive Δ, and it is undetermined.

## Diagnostics (§3; they do not decide)

Bands use the **incumbent's** consensus rank for both filters. Picks are
excluded from D1, D2 and D4. KTC Market is a benchmark, never a target.

**D1: share of value-direct market observations rejected** (KTC Crowd, KTC Trades, IDPTC)

| band | market obs | champion | challenger |
|---|---|---|---|
| 1–24 | 6,312 | 8.17% | **11.47%** |
| 25–50 | 6,247 | 1.06% | 2.66% |
| 51–100 | 10,701 | 1.50% | 4.15% |
| 101–200 | 18,266 | 0.99% | 0.82% |
| 201–400 | 36,142 | 0.56% | 3.80% |
| 401–800 | 55,734 | 0.18% | **14.06%** |
| all 1–800 | 133,402 | 0.92% | 8.01% |

**D2: rows with at least one market observation rejected**

| band | rows | champion | challenger |
|---|---|---|---|
| 1–24 | 2,472 | 374 | 584 |
| 25–50 | 2,551 | 66 | 163 |
| 51–100 | 4,679 | 158 | 353 |
| 101–200 | 9,419 | 166 | 148 |
| 201–400 | 19,252 | 192 | 1,372 |
| 401–800 | 34,513 | 98 | 7,778 |

On the newest board alone, in the top 24, the champion rejects market votes on
7 rows and the challenger on 11. Like the original challenger, the per-vote
challenger does not relieve F1 at the top. It raises market rejections in most
bands.

**D3: published-value movement, |V_ch / V_inc − 1|**

| class | rows | rows moved | p90 (all) | median (moved) | p90 (moved) | max |
|---|---|---|---|---|---|---|
| offense | 49,366 | 23,089 | 2.24% | 0.99% | 3.52% | 82.0% |
| IDP | 40,225 | 2,772 | 0 | 17.8% | 45.1% | 162.7% |

Top-N membership changes, summed over boards ("out" means a member of the
incumbent's top N that is missing from the challenger's):

| class | top 24 out / in (boards) | top 100 out / in (boards) | top 200 out / in (boards) |
|---|---|---|---|
| offense | 42 / 42 (36) | 170 / 31 (81) | 221 / 16 (82) |
| IDP | 0 / 0 (0) | 26 / 190 (74) | 61 / 286 (81) |

**D4: filter rows where every observation of one family was removed**

| scope | champion | challenger |
|---|---|---|
| all 61,376 filter rows | 9,771 | 26,258 |
| band 401–800 | 1,366 | 9,617 |

Families wiped most often by the challenger:

| family | challenger | champion |
|---|---|---|
| Draft Sharks | 7,798 | 6,019 |
| IDP Show | 5,449 | 544 |
| DLF | 891 | 728 |
| FantasyPros | 814 | 674 |

**D5: median model value vs KTC Market (normalised), model / market − 1.**
The bands are essentially unchanged; at the top the challenger reads +7.4%
against the champion's +6.9%.

**D6: coordinate census.** The share of votes dropped per curve family, complete
boards:

| curve family | votes | champion | challenger |
|---|---|---|---|
| OFFENSE | 340,440 | 1.72% | 1.78% |
| OFFENSE + TE | 69,726 | 1.85% | 1.69% |
| OFFENSE + value-direct (KTC) | 73,006 | 0.90% | 2.16% |
| GLOBAL (shared market) | 98,773 | 5.71% | 12.39% |
| GLOBAL + TE | 11,787 | 12.77% | 14.87% |
| GLOBAL + value-direct (IDPTC) | 50,314 | 1.06% | **22.13%** |
| GLOBAL + TE + value-direct (IDPTC on TEs) | 7,360 | 0.46% | 20.31% |

**71.6% of filter rows mix curves** (43,941 of 61,376); on the newest board,
94.4%. On OFFENSE-curve votes the challenger behaves almost like the champion.
The extra rejections fall on votes read through the shared-market (GLOBAL)
curve, above all IDPTC's value-direct vote. Its implied shared-market percentile
sits systematically away from the OFFENSE-pool percentiles of the same row.

PREREGISTRATION §5 named this risk in advance ("Mixed coordinates on one row").
D6 measures that it dominates. This is a description of the result; it does not
change the definition or the verdict.

## Player-level disagreements (§3)

**Largest published-value moves (complete boards).** All 20 of the largest are
Kool-Aid McKinstry (IDP DB), 2026-10-02 → 2026-10-08:

| filter | drops | value |
|---|---|---|
| champion | `draftSharksIdp` | ~1,005–1,022 |
| challenger | `idpTradeCalc` | ~2,600–2,660 (rank ~225–241) |

The largest move is 1,006 → 2,643 (+162.7%) on `20261007_015227`. The original
README cites the same player as its example of a large IDP move.

**Largest moves on the newest board** (`dynasty_export_20261017_185402`). All
are offense rows ranked past ~200, and most move because the challenger drops
the IDPTC vote:

| player | value champion → challenger | move | challenger drops |
|---|---|---|---|
| Adam Trautman (TE) | 1,180 → 1,352 | +14.6% | IDPTC |
| Damien Martinez | 1,083 → 1,218 | +12.5% | KTC Crowd |
| Reggie Virgil | 944 → 1,036 | +9.7% | IDPTC (the champion drops Draft Sharks) |
| Jahdae Walker | 1,095 → 1,198 | +9.4% | KTC Trades |
| Deshaun Watson | 2,427 → 2,647 | +9.1% | Draft Sharks and IDPTC (the champion drops Yahoo/Boone) |

The JSON has the top 20.

**Top-24 market rejections, newest board** (incumbent rank in brackets):

| player | champion drops | challenger drops |
|---|---|---|
| Josh Allen (2) | — | KTC Trades |
| Puka Nacua (8) | IDPTC | KTC Crowd, KTC Trades |
| Amon-Ra St. Brown (9) | KTC Crowd | KTC Crowd, KTC Trades |
| Caleb Williams (10) | KTC Crowd, KTC Trades | KTC Crowd, KTC Trades |
| Lamar Jackson (11) | — | KTC Crowd |
| Drake Maye (12) | — | KTC Crowd, KTC Trades |
| CeeDee Lamb (13) | — | KTC Crowd |
| Joe Burrow (14) | KTC Crowd | KTC Crowd |
| Justin Jefferson (16) | — | KTC Crowd |
| Patrick Mahomes (17) | IDPTC, KTC Crowd | KTC Crowd |
| Jayden Daniels (20) | IDPTC, KTC Crowd | KTC Crowd |
| Drake London (22) | IDPTC | — |

In the top 24, the challenger rejects KTC more often and IDPTC less often. That
pattern holds over all complete boards. For example, Jayden Daniels / KTC Crowd
is rejected on 76 of 80 boards by the challenger and 58 by the champion, while
Patrick Mahomes / IDPTC is rejected on 2 of 53 by the challenger and 53 by the
champion.

## Puka Nacua (diagnostic only; nothing is tuned toward any player)

Newest complete board, `dynasty_export_20261017_185402`. The row has 15 votes.

**Champion** (value space). Median 9,210, MAD 396, threshold 1,089.

| | drops | value | rank |
|---|---|---|---|
| champion | Draft Sharks, Fantasy Pros Fitzmaurice, IDPTC | **9,110** | 8 |
| challenger | Draft Sharks, Fantasy Pros Fitzmaurice, **KTC Crowd, KTC Trades** (keeps IDPTC) | **9,200** | 8 |

For reference only: KTC Market (normalised) is 8,143. The original challenger
dropped Draft Sharks, Fitzmaurice, IDPTC and both KTC votes, for 9,282.

**Challenger** (per-vote coordinates). Median u = 0.01202, MAD 0.00405. The
per-vote threshold is 0.01503 for an OFFENSE-curve vote and 0.01209 for a GLOBAL
one; each threshold is set by the carried floor.

| vote | value | curve | u | \|u − median\| | threshold | champion | challenger |
|---|---|---|---|---|---|---|---|
| dlfSf, dynastyDaddySf, fantasyCalc, flockFantasySf, otcffbSf | 9,345 | OFFENSE | 0.01002 | 0.0020 | 0.0150 | keep | keep |
| dynastyNerdsSfTep, pfkDynasty | 9,210 | OFFENSE | 0.01202 | 0 | 0.0150 | keep | keep |
| fantasyNavigatorSf | 9,617 | OFFENSE | 0.00602 | 0.0060 | 0.0150 | keep | keep |
| fantasyProsSf | 8,814 | OFFENSE | 0.01804 | 0.0060 | 0.0150 | keep | keep |
| yahooBoone | 8,318 | OFFENSE | 0.02605 | 0.0140 | 0.0150 | keep | keep |
| ktcCrowdSfTep | 8,153 | OFFENSE (value-direct) | 0.02886 | 0.0168 | 0.0150 | keep | **drop** |
| ktcTradesSfTep | 8,162 | OFFENSE (value-direct) | 0.02870 | 0.0167 | 0.0150 | keep | **drop** |
| fantasyProsFitzmaurice | 7,859 | OFFENSE | 0.03407 | 0.0221 | 0.0150 | drop | drop |
| idpTradeCalc | 8,033 | GLOBAL (value-direct) | 0.01607 | 0.0041 | 0.0121 | **drop** | **keep** |
| draftSharks | 6,703 | GLOBAL | 0.04207 | 0.0301 | 0.0121 | drop | drop |

Why the two filters differ:

- **IDPTC (8,033).** The champion drops it as 1,177 points below the value
  median. The challenger keeps it: read through the shared-market curve, its
  implied percentile, 0.0161, sits close to the OFFENSE-pool median.
- **KTC Crowd and Trades (≈ 8,155).** These votes are about 120 points higher
  than IDPTC. Read through the OFFENSE curve they imply u ≈ 0.0287, beyond the
  OFFENSE threshold, so the challenger drops them. The champion keeps them,
  1,048–1,057 points below the value median, inside its 1,089 threshold.

This is the mixed-coordinate effect measured in D6, on one row.

Over the 103 complete boards:

| filter | most common drop set | boards |
|---|---|---|
| champion | `{draftSharks}` | 44 |
| challenger | `{draftSharks, fantasyProsFitzmaurice, ktcCrowdSfTep}` | 22 |
| challenger | the same plus `ktcTradesSfTep` | 20 |

The full series is in `diagnosticPlayers` in the diagnostics JSON. This case
decides nothing and was not used to tune anything.

## Pre-run implementation check (§3; not evidence)

This check ran on `dynasty_export_20261005_152048` and `…_20261017_185402` at
the implementation commit, before the full run. Full output is in
`precheck_implementation_check.json`.

- **Forward ∘ inverse round trip** on every curve family present (OFFENSE,
  GLOBAL, with and without TE, value-direct): max error ≤ 1.8e-12 vote points,
  and 2.4e-8 for OFFENSE + TE basis conversion (bisection).
- **Recovering the build's own stamped percentile** from the integer
  `valueContribution` stamps:
  - median error is about 4e-5 to 1.3e-4;
  - max error is 0.0008, from `percentile_to_value`'s integer rounding;
  - the 0.018 / 0.020 OFFENSE + TE maxima are four top tight ends whose lifted
    vote (about 9,998.6) rounds to a 9,999 stamp.

  In the pipeline the challenger inverts the unrounded float vote, so this
  affects only the stamp-based reproduction check.
- **Reproduction from stamps:** 678 / 678 and 465 / 466 rows.
- **Segment behaviour** checked separately:

  | segment | 2026-10-05 drops (champion → challenger) | 2026-10-17 drops (champion → challenger) |
  |---|---|---|
  | offense non-TE | 92 → 288 | 82 → 237 |
  | TE | 22 → 51 | 16 → 30 |
  | IDP | 28 → 41 | no IDP filter rows (IDP rows fall below n ≥ 4) |

- **No implementation bug was found.** Nothing in the frozen definitions or
  evaluation changed.

## Deviations from the preregistration

**None in the decision rule, the dataset, the rebuild procedure or the
challenger definition.** The inherited §5 rule, seed 2027 and the frozen 138 /
103 archives were applied as written.

Interpretations stated so they can be challenged:

- **Point-in-time.** PREREGISTRATION §1 fixes this. Each vote's forward map is
  the one its own replay build applied, captured as the vote was priced. Every
  record ran on one replay revision (`de33727a9`), so these are that revision's
  constants and TE curve: the ones that actually produced the vote being
  filtered.
- **Agreed-drop positions.** Positions for agreed drops (R, context only) come
  from a `positions` map that the per-vote records carry. This does not affect
  K, X, Δ or G1.
- **D1–D5** use the original README's interpretations: bands by the
  incumbent's rank, pick rows excluded, D5 = median of model /
  `ktcMarket.normalizedValue` − 1.
- **The `accumulation` block** printed by the inherited code is explained above.
  It is not a request to accumulate.

## Disposition

- **Verdict: INCONCLUSIVE.** Per PREREGISTRATION §4, the experiment is **closed**
  with a no-detectable-advantage conclusion.
- The production Hampel filter is retained.
- `rank_space_hampel_per_vote_challenger` stays OFF.
- Nothing is promoted, and no owner review is requested.
- The original experiment's NOT BETTER verdict stands unchanged. This result is a
  separate answer to a separate question, not a replication of it.

Reproduce (full git history needed; about 20 minutes):

```bash
python scripts/joint_filter_shadow.py --challenger rank_space_per_vote backfill --include-degraded
python scripts/joint_filter_shadow.py --challenger rank_space_per_vote evaluate --sensitivities
python scripts/joint_filter_shadow.py --challenger rank_space_per_vote summary
python scripts/joint_filter_shadow.py --challenger rank_space_per_vote diagnostics
```

## Known limitations

- **Mixed coordinates on one row** (PREREGISTRATION §5). Per-vote percentiles of
  different populations share one median and MAD. D6 shows this drives most of
  the extra rejections.
- **Value-direct coordinates are implied**, through the source's own pool curve.
- **Today's code, not production history.** The freshness approximations and
  the target's dependence on a model output are inherited from the original
  replay.
- **Dependent boards.** Overlapping h = 7 windows mean percentile intervals from
  8 week-blocks probably under-cover. The minimum-sample rule counts
  board-observations.
- **IDP rows rarely reach n ≥ 4 after 2026-10-12**, so the IDP segment comes from
  earlier boards.
- **Same 103 boards as the original experiment.** The two results do not
  combine.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
