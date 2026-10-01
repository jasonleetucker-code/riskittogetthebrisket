# Joint robust-filter shadow ledger: evidence (2026-10-01)

Batch 3 Unit F. The challenger is `joint-robust-v2`, the **filter half** of
#1571 (`joint_outlier_sparse_challenger`). The sparse half
(`joint_sparse_limited_evidence`) stayed **OFF** in every build. **No flag was
flipped and nothing was promoted.**

Every historical number below comes from **archived inputs rebuilt through
today's pipeline code**. It is never what production served that day.

| file | what it is |
|---|---|
| `PREREGISTRATION.md` | outcome definitions, horizons, metrics and the decision rule. Committed in `bfcf2e423` **before** any outcome was computed. §9 is an addendum for live records only. |
| `evaluation_historical_replay.json` | the preregistered evaluation: primary result plus S1–S6 |
| `summary_historical_replay.json` | per-board census for all 133 replayed boards |
| `adversarial.json` | constructed cases, at function level and through the full pipeline |

## Inputs (pinned)

- **Boards.** All 133 archives in `exports/archive/` (2026-07-14 → 2026-09-30).
  98 of them are **complete** under the contract's own source-health rule
  (2026-08-18 → 2026-09-30). The other 35 fail on exactly `KTC_TradeDB` and
  `KTC_WaiverDB`; they are used only in S1.
- **Point-in-time inputs per board.** Each board was rebuilt from:
  - the archive's own payload;
  - `CSVs/site_raw/` exactly as committed with that archive, overlaid with the
    archive's own `site_raw/` copies;
  - per-source dataset state replayed from git history up to that commit
    (`observe`, the same sequence as `scripts/backfill_source_datasets.py`).

  Freshness is evaluated at each payload's own `scrapeTimestamp`. The build
  runs through `build_api_data_contract(csv_root=…)` via `value_replay.build`.
- **Code.** Replay and evaluation ran at `42ae82fe0`. The adversarial run and
  the summary ran at `e7a19e523`. Neither commit changes the recorder or the
  outcome code relative to the other.
  - All 133 records carry `workingTreeDirty: false` and one
    `pipelineFingerprint`.
  - Local `data/leagues` snapshots are hashed in each record.
- **Variants.** Two builds per board on identical inputs. Only the challenger
  flag differs.
- **Reproduction check.** Re-running both filters on the stamped integer votes
  matches the stamped drop sets on:

  | filter | matched |
  |---|---|
  | incumbent | 3,445 / 3,445 rows |
  | challenger | 3,433 / 3,445 rows |

  The 12 misses come from rounding the votes to integers.
- **Cross-check against #1571.** The newest board gives 56 disagreement rows on
  its reconstructed tree, against #1571's 54 on the live tree.

## What the challenger does on real boards (98 complete)

| per board | median | range | total |
|---|---|---|---|
| rows where the two filters disagree | 34 | 7–63 | 3,414 (offense 2,229 · IDP 1,185) |
| K: dropped by the incumbent, kept by the challenger | 17 | 2–42 | 1,827 |
| X: kept by the incumbent, dropped by the challenger | 24 | 5–42 | 2,356 |
| incumbent drops / challenger drops | 151.5 / 149 | — | 15,879 / 16,408 |
| top-200 membership churn | — | — | 148 swaps, on 84 of 98 boards |

- **Both safeguards fired 0 times on all 133 real boards.** Neither
  `dominant_evidence_kept` nor `kept_to_avoid_single_family` ever decided a
  real row.
- **The differences come from weighting.**
  - 87% of rescued observations (1,592 / 1,827) carry full weight: they are
    observations the unweighted median called outliers.
  - 38% of newly rejected observations (892 / 2,356) carry reduced
    (freshness/health) weight.
- **Biggest moves on the newest board are IDP:**

  | player | incumbent value | challenger value | rank change |
  |---|---|---|---|
  | Cedric Gray | 3,053 | 4,507 | 179 → 86 |
  | Kool-Aid McKinstry | 1,026 | 1,828 | unranked → 397 |
  | Kevin Winston | 2,887 | 2,090 | 196 → 302 |
  | Josiah Trotter | 2,935 | 2,307 | 190 → 270 |

## Preregistered evaluation

The question: when the filters disagree on an observation, does the
**independent** consensus later move toward it? The consensus is the
equal-family median of the *other* B10 families. *m* is the share of the gap
that consensus closed, clipped to [−1, 1].

Primary result: 98 complete boards, 44 origin days, h = 7 days, 7-day block
bootstrap, 4,000 resamples.

| quantity | n | point | 95% CI |
|---|---|---|---|
| mean *m*, K (rescued) | 380 | 0.0068 | [−0.0104, 0.0214] |
| mean *m*, X (newly rejected) | 701 | 0.0024 | [−0.0120, 0.0188] |
| mean *m*, R (agreed outliers, context) | 6,627 | 0.0045 | — |
| **P1: Δ = K − X** | 37 days, 6 blocks | **0.0044** | **[−0.0091, 0.0133]** |
| **G1: challenger − incumbent value error** vs. later consensus | 865 rows | 0.0003 | [−0.0015, 0.0036] |
| S5: G1 relative to persistence | 865 rows | 0.0022 | [0.0014, 0.0030] |

Secondary horizons (Δ, point and 95% CI):

| horizon | Δ | 95% CI | days / blocks |
|---|---|---|---|
| 3 days | 0.0066 | [−0.0054, 0.0191] | 41 days |
| 14 days | 0.0015 | [−0.0256, 0.0304] | 30 days |
| 21 days | 0.0424 | [0.0182, 0.0926] | 23 days, 4 blocks |

Outcome classes at h = 7:

| group | abandoned (own source retreats) | led | delisted |
|---|---|---|---|
| K | 20 of 380 (5.3%) | 1 | 0 |
| X | 26 of 701 (3.7%) | 0 | 9 |
| R | 827 of 6,627 (12.5%) | — | 139 |

The agreed outliers are abandoned by their own source more than twice as often
as either disputed group. When the filters agree, they agree on genuine errors.

**Preregistered verdict: INCONCLUSIVE** (no detectable advantage; near-ties keep
the incumbent).

- The minimum sample is met: 380 / 701 observations, 37 days, 6 blocks.
- G1 is non-inferior: its upper bound 0.0036 is within the 0.005 margin.
- Δ is positive at 3 of 3 secondary horizons.
- **But Δ's lower bound is below 0**, so the challenger is not eligible.

### Sensitivities (they report; they do not decide)

| id | population | Δ at h = 7 | 95% CI | rule would say |
|---|---|---|---|---|
| S1 | all 133 archives | 0.0088 | [−0.0068, 0.0252] | inconclusive |
| S2 | episode-deduplicated | 0.0154 | [−0.0123, 0.0367] | inconclusive |
| S3 | offense only | **0.0301** | **[0.0115, 0.0407]** | eligible pattern (G1 0.0019 [−0.0007, 0.0040]) |
| S3 | IDP only | **−0.0325** | **[−0.0718, −0.0028]** | not better |
| S4 | KTC Crowd/Trades split era (from 2026-09-09) | — | — | insufficient (3 blocks) |
| S6 | KTC families merged for targets | −0.0041 | [−0.0134, 0.0065] | inconclusive |

**The asset classes point in opposite directions:**

- On offense, the challenger's rescues were slightly more often led-to.
- On IDP, which is where its largest value moves are, its rescues were led-to
  **less** than the evidence it threw away.

This split is a **post-hoc subgroup**. S3 was prespecified for reporting only,
so it cannot carry a decision. It is a hypothesis for a new preregistered
question on forward data.

## Adversarial cases

Source: `adversarial.json`. Built on real rows of `dynasty_export_20260930_130404`,
25 rows per case.

| case | rows meeting expectation | safeguard fires | incumbent |
|---|---|---|---|
| A1 trap (3 × ~3100 at 0.03 vs 4600 at 1.0) | 25 / 25: fresh kept, no single-family row | single-family 75 | drops the fresh 4600 on 25 / 25 |
| A1b trap on the whole row | 25 / 25 | single-family 311 | drops fresh 22 / 25 |
| A2 stale cluster vs one fresh low observation | 25 / 25 | single-family 345 | drops fresh 25 / 25 |
| A3 correlated family (2+ members agree at 1.6× the independents) | strict 23 / 25; **no worse than the incumbent 25 / 25** | — | drops an independent 6 / 25 |
| A4 one low-weight source ×5 | 25 / 25 dropped | — | 25 / 25 dropped |
| A4 one low-weight source ×0.2 | 25 / 25 dropped | — | 25 / 25 dropped |
| A4b broken source that is the dominant evidence (×5, others stale) | 25 / 25 **kept** (the disclosed limitation) | single-family 152 | drops it 15 / 25 |

Full-pipeline cases, run through `csv_root` trees:

- **`dlfSf` ranks ×5 on its top 60.** Of 276 perturbed observations, both
  filters dropped the same 97.
- **`dlfSf` ranks ×0.2 on ranks 150–250.** Of 222, both filters dropped 184.
  Both filters handle a scale break identically.
- **Three sources aged.** Two reached freshness 0.04. `pfkDynasty` stayed at
  0.98, because its replayed clock did not move under the 3-day cut. Neither
  safeguard fired; 51 rows disagreed.

**Finding: `dominant_evidence_kept` is unreachable at the production constant.**

- In 20,000 seeded random rows at k = 2.75 it fired **0** times. At k = 0.5 it
  fired 504 times, so the branch is live code.
- Why: an observation holding at least half the evidence weight pulls both the
  weighted median and the weighted MAD toward itself, so with k > 1 it never
  falls outside the threshold.
- Dominant evidence is still never dropped (A1, A2, A4b), but the protection
  comes from the weighted centre, not from the named rule.
- This is a **deviation from PREREGISTRATION §7**. §7 names the rule as the
  mechanism; the outcome it promised holds.
- `kept_to_avoid_single_family` is reachable and does decide the constructed
  traps. It just never occurred on a real board.
- No change was made to the filter. That is the filter owner's call.

## Disposition

**Filter half: NOT BETTER. Not promotion-eligible on this evidence.** Near-ties
keep the incumbent.

The preregistered verdict is INCONCLUSIVE, but it is **not** "insufficient":

- the minimum sample is met;
- the 95% interval for Δ, [−0.009, +0.013], already sits nine times inside the
  preregistered minimum effect of interest (±0.10).

So the archive does answer the question. On the full population, the challenger
does not preserve subsequently useful evidence more often than the incumbent by
any margin the rule cares about. It is equivalent within ±0.10, not better.

What would change this:

- **The S3 split.** A new preregistration restricted to offense (or excluding
  IDP), tested on boards **after** 2026-09-30. Neither the live ledger nor
  future archives have seen it.
- **A longer-horizon outcome.** The independent consensus barely moves over
  3–21 days (mean *m* is about 0 in every group), so the measure has little
  range. A season-scale horizon needs a longer archive.

## Accumulation (automatic, no promotion)

- **Box timer.** `dynasty-joint-filter-shadow` runs twice daily at 07:55 and
  19:55 UTC.
  - It records the newest production board both ways into the append-only
    `data/robust_filter_shadow/ledger.jsonl`, plus a write-once panel, then
    re-evaluates.
  - Per PREREGISTRATION §9, live pairs need an identical pipeline fingerprint.
    The live ledger therefore mainly answers census questions on real
    production boards: drop rates, disagreement, and whether a safeguard ever
    fires.
  - It never writes a served value.
- **Decisive re-test.** Re-run
  `python scripts/joint_filter_shadow.py backfill --include-degraded` followed
  by `evaluate --sensitivities`.
  - This rebuilds every archived scrape under one code revision.
  - The archive grows with each scheduled refresh.
  - Each re-run reports its span; the rule is never re-tuned.

Reproduce:

```bash
python scripts/joint_filter_shadow.py backfill --include-degraded   # ~7 min, full git history needed
python scripts/joint_filter_shadow.py evaluate --sensitivities
python scripts/joint_filter_shadow.py adversarial --full-pipeline
python scripts/joint_filter_shadow.py summary
```

## Known limitations

- **Today's code, not production history.** Every replay uses today's code and
  config.
- **Freshness approximations.**
  - Per-row freshness clocks fall back to the source clock.
  - The vendor `upstreamPublishedAt` sidecar is not replayed.
- **Confidence fields** in replays read the live tree's fetch stamps. Nothing
  here uses them.
- **The target is itself a model output.** It is an equal-family median of
  board-scale votes: independent of the disputed family, not of the shared Hill
  transform.
- **Short archive.** 43 complete days gives only 6 week-blocks at h = 7 and 4
  at h = 21.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c
