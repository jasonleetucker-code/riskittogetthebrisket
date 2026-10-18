# Rank-space Hampel challenger: evidence (2026-10-17)

Owner master package 2026-10-17, Workstream H; source & valuation audit
2026-10-13, finding F1. The challenger is `rank-space-hampel-v1`
(`rank_space_hampel_challenger`): the served per-player Hampel filter with the
same K, guards and floor, computed on Hill-curve percentile coordinates instead
of values. **No flag was flipped and nothing was promoted.**
`rank_space_hampel_challenger` still ships OFF.

Every number below comes from **archived inputs rebuilt through today's
pipeline code**. It is never what production served that day.

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | the challenger, the inherited evaluation and the F1 diagnostics. Committed in `76c1c71d7` **before** the challenger was run. |
| `evaluation_historical_replay.json` | the preregistered evaluation: primary result plus S1–S6 (bootstrap seed 17) |
| `summary_historical_replay.json` | per-board census for all 138 replayed boards |
| `diagnostics_historical_replay.json` | §3 F1 diagnostics D1–D5: pooled over the complete boards, the newest complete board alone, and all boards |

## Preregistered verdict: NOT BETTER

The challenger is **not** promoted. Under the inherited §5 rule, NOT BETTER keeps
the champion (PREREGISTRATION §4).

- **P1.** Δ = mean_K(m) − mean_X(m) at h = 7 is **−0.0127, 95% CI [−0.0204, −0.0053]**.
  The upper bound is below 0, so the rule returns NOT BETTER. The evidence the
  challenger rescued was later led-to **less** by the independent consensus than
  the evidence it newly threw away.
- **G1.** +0.0036, 95% CI [−0.0036, +0.0127]. The upper bound is above the
  +0.005 margin, so non-inferiority of the published values is **not** shown
  either.
- **Secondary horizons.** Δ is negative at 3 of 3 (positive at 0 of the 2 needed).
- **Minimum sample.** Met: 2,827 K and 2,912 X observations, 53 origin days,
  8 week-blocks.
- **F1 itself (diagnostics, not deciding).** The challenger does not reduce the
  F1 rejections at the top of the board. It **increases** them: in the top 24 it
  rejects 12.5% of value-direct market observations, against 8.2% for the
  champion (D1).

## Inputs (pinned)

- **Boards.** All 138 archives in `exports/archive/` (2026-07-14 → 2026-10-17).
  - **103 are complete** under the contract's own source-health rule
    (2026-08-18 → 2026-10-17). They are the primary population.
  - The other 35 (2026-07-14 → 2026-08-17) fail on exactly `KTC_TradeDB` and
    `KTC_WaiverDB`, and are used only in S1.
  - The archive now keeps one board per day before 2026-10-01 (retention).
    That is why the count differs from the joint evaluation's 133.
- **Point-in-time inputs per board.** Identical to the joint evaluation. Each
  board was rebuilt from:
  - the archive's own payload;
  - `CSVs/site_raw/` as committed with that archive, overlaid with the archive's
    own `site_raw/` copies;
  - per-source dataset state replayed from git history up to that commit.

  Freshness was evaluated at each payload's `scrapeTimestamp`. Builds ran
  through `value_replay.build` → `build_api_data_contract(csv_root=…)`.
- **Code.** Every one of the 138 records was built at `996f70b7d`, with
  `workingTreeDirty: false` and one `pipelineFingerprint` (`a9052069…`).
  `996f70b7d` adds only the shadow-recorder parameterisation on top of the
  challenger commit `b921964f8`. The records were written in one run,
  backfill to evaluation, in about 10 minutes.
- **Variants.** Two builds per board on identical inputs:

  | build | `rank_space_hampel_challenger` | `joint_outlier_sparse_challenger` | `joint_sparse_limited_evidence` |
  |---|---|---|---|
  | incumbent | OFF | OFF | OFF |
  | challenger | ON | OFF | OFF |

  `source_family_cap` and `source_freshness_weighting` stay at their defaults
  (on). Records keep the ledger schema `joint-filter-shadow/v1` with
  `pins.challengerVersion = "rank-space-hampel-v1"`. They live in their own
  gitignored ledger, `data/robust_filter_shadow_rank_space/`.
- **Reproduction check.** Re-running both filters on the stamped votes matches
  the stamped drop sets:

  | filter | matched rows (complete boards) |
  |---|---|
  | incumbent | 10,058 / 10,065 |
  | challenger | 10,063 / 10,065 |

  The misses come from rounding the votes to integers.

## What the challenger does on real boards (103 complete)

| per board | median | range | total |
|---|---|---|---|
| rows where the two filters disagree | 97 | 58–174 | 10,051 (offense 7,944 · IDP 2,107) |
| K: dropped by the incumbent, kept by the challenger | 53 | 24–114 | 5,265 |
| X: kept by the incumbent, dropped by the challenger | 62 | 21–96 | 6,209 |
| R: both drop (context) | — | — | 10,235 |
| incumbent drops / challenger drops | 145 / 164 | — | 15,500 / 16,444 |
| rows whose published value moved | 138 | 72–184 | 13,645 |

The challenger drops more observations than the incumbent: 16,444 against
15,500.

Top-N membership churn (incumbent members missing from the challenger's top N):

| depth | swaps | boards with any change |
|---|---|---|
| top 50 | 132 | 59 of 103 |
| top 100 | 180 | 74 of 103 |
| top 200 | 303 | 96 of 103 |
| top 400 | 354 | 101 of 103 |

**IDP disagreements stop on 2026-10-12.** From 2026-08-21 to 2026-10-12 there
were 18–42 IDP disagreement rows per board. From 2026-10-12 16:11 onward there
are **0**. Since then IDP rows rarely reach the filter's n ≥ 4 minimum
(audit F2: about 3 voters). On this population every recent disagreement is
offense.

**Puka Nacua**, the F1 example, on the newest board (`dynasty_export_20261017_185402`):

| filter | drops | value | rank |
|---|---|---|---|
| champion | Draft Sharks, Fitzmaurice, IDPTC | 9,110 | 8 |
| challenger | the same three, **plus KTC Crowd and KTC Trades** | 9,282 | 8 |

KTC Market (normalised) is 8,143 for comparison. KTC Market is a diagnostic
here, not a target.

The joint robust-filter evaluation (`joint-filter-shadow-2026-10-01`) reported
that its safeguards never fired. Those counters belong to the joint filter only:
the rank-space filter stamps no `jointFilterReasons`, so its safeguard counts are
structurally 0. They are not evidence about this filter.

## Preregistered evaluation (inherited §§2–6, seed 17)

Primary result: 103 complete boards, 60 board days (2026-08-18 → 2026-10-17),
53 paired origin days at h = 7, 8 week-blocks, 4,000 resamples.

| quantity | n | point | 95% CI |
|---|---|---|---|
| mean *m*, K (rescued) | 2,827 | 0.0027 | [−0.0066, 0.0099] |
| mean *m*, X (newly rejected) | 2,912 | 0.0155 | [0.0071, 0.0243] |
| mean *m*, R (agreed outliers, context) | 5,991 | 0.0035 | [−0.0015, 0.0077] |
| **P1: Δ = K − X** | 53 days, 8 blocks | **−0.0127** | **[−0.0204, −0.0053]** |
| **G1: challenger − incumbent value error** vs. later consensus | 5,029 rows | **+0.0036** | **[−0.0036, +0.0127]** |
| S5: G1 relative to persistence | 5,029 rows | −0.0008 | [−0.0022, 0.0010] |

Secondary horizons:

| horizon | Δ | 95% CI | days / blocks | G1 |
|---|---|---|---|---|
| 3 days | −0.0012 | [−0.0049, 0.0018] | 57 / 9 | +0.0033 [−0.0032, 0.0116] |
| 14 days | −0.0296 | [−0.0419, −0.0174] | 46 / 7 | +0.0056 [−0.0017, 0.0148] |
| 21 days | −0.0458 | [−0.0573, −0.0334] | 40 / 6 | +0.0045 [−0.0021, 0.0124] |

The longer the horizon, the more clearly the newly rejected evidence (X) was
the evidence the independent consensus later moved toward.

Outcome classes at h = 7:

| group | abandoned | led | delisted | mean retreat share |
|---|---|---|---|---|
| K | 160 of 2,827 (5.7%) | 9 | 94 | 0.061 |
| X | 220 of 2,912 (7.6%) | 12 | 50 | 0.070 |
| R | 843 of 5,991 (14.1%) | 3 | 111 | 0.140 |

### Sensitivities (they report; they do not decide)

| id | population | Δ at h = 7 | 95% CI | G1 | rule would say |
|---|---|---|---|---|---|
| S1 | all 138 archives | −0.0104 | [−0.0172, −0.0030] | +0.0094 [+0.0014, +0.0182] | not better (Δ **and** G1) |
| S2 | episode-deduplicated (519 K / 705 X) | +0.0074 | [−0.0101, 0.0208] | +0.0036 [−0.0036, 0.0127] | inconclusive |
| S3 | offense only | −0.0110 | [−0.0203, −0.0021] | +0.0090 [+0.0012, +0.0189] | not better (Δ **and** G1) |
| S3 | IDP only | −0.0288 | [−0.0532, −0.0063] | −0.0131 [−0.0257, −0.0018] | not better (Δ); G1 favours the challenger |
| S4 | KTC Crowd/Trades split era (from 2026-09-09; 5 blocks) | −0.0162 | [−0.0274, −0.0035] | −0.0026 [−0.0081, 0.0015] | not better |
| S6 | KTC families merged for targets | −0.0155 | [−0.0226, −0.0091] | +0.0050 [−0.0018, 0.0135] | not better |

Six of the seven readings agree with the primary. The exception is S2:
episode deduplication removes the persistence of each disagreement, and on what
remains the sign is positive but undetermined.

IDP's published values sit closer to the later consensus under the challenger
(S3 G1 < 0). Its rescued IDP evidence is still led-to less than what it
rejected. This is a post-hoc subgroup and decides nothing.

## F1 diagnostics D1–D5 (§3; they do not decide)

These are pooled board-rows over the 103 complete boards. Each band is set by
the **incumbent's** consensus rank, for both filters, so the two are compared
on the same rows.

- Value-direct market sources: `ktcCrowdSfTep`, `ktcTradesSfTep`, `idpTradeCalc`.
  These are exactly `data_contract._VALUE_BASED_SOURCES`, and a test pins that.
- D1, D2 and D4 exclude picks, which the filter never judges.
- The single-board reading for the newest board is in the JSON
  (`newestCompleteBoard`).

**D1: share of value-direct market observations rejected**

| band | market obs | champion | challenger |
|---|---|---|---|
| 1–24 | 6,312 | 8.17% | **12.50%** |
| 25–50 | 6,247 | 1.06% | 2.32% |
| 51–100 | 10,701 | 1.50% | 0.82% |
| 101–200 | 18,266 | 0.99% | 0.17% |
| 201–400 | 36,142 | 0.56% | 0.27% |
| 401–800 | 55,734 | 0.18% | 1.53% |
| all 1–800 | 133,402 | 0.92% | 1.50% |

**D2: rows with at least one market observation rejected**

| band | rows | champion | challenger |
|---|---|---|---|
| 1–24 | 2,472 | 374 | 547 |
| 25–50 | 2,551 | 66 | 136 |
| 51–100 | 4,679 | 158 | 88 |
| 101–200 | 9,419 | 166 | 31 |
| 201–400 | 19,252 | 192 | 98 |
| 401–800 | 34,513 | 98 | 846 |

The newest board alone reads, top 24: champion 7 rows, challenger 10. The
champion's 7 matches the audit's F1 table.

**D3: published-value movement, |V_ch / V_inc − 1|**

| class | rows | rows moved | median (all) | p90 (all) | median (moved) | p90 (moved) | max |
|---|---|---|---|---|---|---|---|
| offense | 49,366 | 7,851 | 0 | 1.12% | 1.50% | 4.41% | 82.0% |
| IDP | 40,225 | 2,107 | 0 | 0 | 17.5% | 48.5% | 162.7% |

Top-N membership changes, summed over boards. "Out" means a member of the
incumbent's top N that is not in the challenger's. "In" is the reverse.

| class | top 24 out / in (boards) | top 100 out / in (boards) | top 200 out / in (boards) |
|---|---|---|---|
| offense | 25 / 25 (25) | 136 / 32 (68) | 211 / 49 (94) |
| IDP | 0 / 0 (0) | 24 / 148 (64) | 71 / 254 (92) |

The challenger moves IDP rows up into the top 100–200 at offense's expense.
Each IDP row that moves moves a lot: the largest moves are on 2- to 4-voter rows,
for example Kool-Aid McKinstry, about 1,020 → 2,620.

**D4: filter rows where every observation of one family was removed**

| band | filter rows | champion | challenger |
|---|---|---|---|
| 1–24 | 2,472 | 1,762 | 1,906 |
| 25–50 | 2,515 | 1,467 | 1,537 |
| 51–100 | 4,429 | 1,606 | 1,807 |
| 101–200 | 8,444 | 2,188 | 2,264 |
| 201–400 | 16,040 | 1,250 | 986 |
| 401–800 | 22,576 | 1,366 | 1,005 |
| all | 61,376 | 9,771 | 9,702 |

Most B10 families have a single member, so D4 is close to "rows with any drop".
The families most often wiped by the challenger, against the champion:

| family | challenger | champion |
|---|---|---|
| Draft Sharks | 4,308 | 6,019 |
| Yahoo/Boone | 1,311 | 1,056 |
| IDPTC | 1,219 | 566 |
| Dynasty Nerds | 866 | 512 |
| KTC Trades | 349 | 157 |

**D5: median model value vs KTC Market (normalised), model / market − 1.**
A diagnostic, never a target.

| band | rows | champion | challenger |
|---|---|---|---|
| 1–24 | 1,944 | +6.9% | +7.1% |
| 25–50 | 1,954 | +2.1% | +2.5% |
| 51–100 | 3,419 | −3.7% | −3.3% |
| 101–200 | 5,196 | −6.3% | −6.2% |
| 201–400 | 9,820 | −12.8% | −12.7% |
| 401–800 | 12,808 | −11.7% | −11.6% |

The F1 gap pattern is essentially unchanged. At the top it widens slightly.

### Why F1 is not relieved (a post-hoc reading, not part of the decision)

Near the ceiling the offense Hill curve, V = 9999 / (1 + (p/c)^s), behaves like
a power law. The inverse therefore keeps the *relative* geometry of top-of-board
disagreements. Two figures from the newest board, computed after the result
and so stated with that caveat:

- **Puka.** The rank votes 9,210–9,345 span about 0.002 in p, and the market
  votes at about 8,150 sit about 0.02 away. The ratio is roughly what it is in
  value space.
- **The carried floor** protects down to about 960 points below the median,
  roughly what the incumbent protects.

So the premise that compression alone makes the market read as an outlier does
not hold in this coordinate. The market votes are far from the rank consensus in
percentile terms too.

## Discrepancy found during evaluation (implementation vs. preregistration premise; not fixed)

PREREGISTRATION §1.1 says H is "the row's own scope master Hill curve … the
curve that produced the rank-signal votes", so rank-signal votes "map back to
the percentile they came from". The committed challenger
(`data_contract._hampel_filter_rank_space` at its call site) uses **one curve
per row**: the IDP master for `assetClass == "idp"` and the OFFENSE master
otherwise.

The pipeline prices each rank vote through
`curve_for_pool(rankCoordinatePool)`, which varies per (row, source). On the
newest board:

| votes | count | curve that produced them | curve the challenger inverts with |
|---|---|---|---|
| IDP-row votes | 945 (all of them) | `shared_market` (c = 0.112, s = 0.725) | IDP master (c = 0.083, s = 1.11) |
| offense-row votes | 800 of 5,926 | `shared_market` | OFFENSE master |
| TE votes with the TE basis multiplier | 550 | Hill, then the post-Hill multiplier | inverted as if no multiplier applied |

So for IDP rows, part of the offense rows and every TE vote, u is not the
percentile the vote came from.

The evaluation tests the challenger **as implemented and committed**. Changing
the coordinate now, after results, would be a new challenger. A per-vote-pool
inverse is a candidate for a **new** preregistration, not a re-tune of this one.
This mainly qualifies the IDP results (S3 IDP, the D3 IDP rows). For offense
rows, 86% of votes carry the OFFENSE pool, and for those that are rank votes on
non-TE rows the inverse is exact.

## Deviations from the preregistration

**None in the decision rule or its inputs.** The evaluation applies the inherited
§§2–6 exactly, with seed 17. The following are interpretations of
under-specified §3 diagnostics, chosen before the diagnostics were computed and
stated here so they can be challenged:

- **Bands use the incumbent's (served) consensus rank for both filters**, so
  the champion and the challenger are compared on the same rows. Rows the
  incumbent leaves unranked fall outside every band.
- **D1, D2 and D4 count non-pick rows.** The filter never judges picks. D5
  counts every ranked row carrying `ktcMarket.normalizedValue`.
- **D5 is the median of model / ktcMarket.normalizedValue − 1.** "Model" is the
  published `rankDerivedValue` of each build.
- **D4 counts a family wiped when every one of its voting members on the row
  was dropped.** Single-member families make this close to "any drop".
- **Pooled tables are board-rows over the complete boards.** A per-board
  reading is in the JSON.

One plain disclosure: the preregistration's inherited minimum-sample rule
counts board-observations, not independent observations. The same is true
here, as it was for the joint evaluation.

## Disposition

- **Verdict: NOT BETTER. The champion stays.**
- `rank_space_hampel_challenger` remains OFF.
- No independent review or owner approval is requested, because the §5 rule did
  not return PROMOTION-ELIGIBLE.
- Per PREREGISTRATION §4, the challenger is recorded as **not reducing the F1
  rejections, and not passing P1 or G1**.

Reproduce (full git history needed; about 10 minutes):

```bash
python scripts/joint_filter_shadow.py --challenger rank_space backfill --include-degraded
python scripts/joint_filter_shadow.py --challenger rank_space evaluate --sensitivities
python scripts/joint_filter_shadow.py --challenger rank_space summary
python scripts/joint_filter_shadow.py --challenger rank_space diagnostics
```

`--challenger rank_space` writes to `data/robust_filter_shadow_rank_space/` and
uses seed 17 and this preregistration. `record` and `adversarial` refuse it: it
is preregistered for the historical replay only, and its learning receipts would
otherwise be filed under the joint filter.

## Known limitations

- **Today's code, not production history.** Every replay runs today's code and
  config.
- **Freshness approximations.** Per-row freshness clocks fall back to the source
  clock, and the vendor `upstreamPublishedAt` sidecar is not replayed. Both are
  inherited from the joint evaluation.
- **The target is a model output.** It is an equal-family median of board-scale
  votes, which shares the Hill transform. It measures agreement with later
  independent evidence, not truth.
- **H⁻¹ is the curve-per-row inverse described above.** It is exact only for
  OFFENSE-pool, non-TE votes.
- **Dependent boards.** Daily boards are strongly dependent, and the h = 7
  outcome windows of neighbouring origins overlap. Percentile intervals from 8
  week-blocks probably under-cover. The primary Δ interval excludes 0 by a
  margin (upper −0.0053), and every horizon of 7 days or more points the same
  way. S2, which removes persistence, is the one reading that is undetermined.
- **IDP is absent from recent disagreements.** It has been out since
  2026-10-12, because of the n ≥ 4 minimum.
- **The ledger is a rebuildable replay.** Its directory is not in the box's
  state-backup list (which covers `robust_filter_shadow` only).

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
