# Joint robust filter shadow evaluation: preregistration

Batch 3 Unit F (`docs/EXECUTION_PLAN.md`, "Valuation Trust Program — Batch 3").
Challenger: `joint-robust-v2`, the **filter half** of #1571
(`joint_outlier_sparse_challenger`). The sparse half
(`joint_sparse_limited_evidence`) stays **OFF** throughout and nothing here
evaluates it.

This document is committed **before** any outcome in it has been computed.
When it was written, two things had already been computed:

- the single-board reproduction of #1571's 54 changed rows on
  `dynasty_export_20260930_130404.zip`;
- archive metadata: the list of archives, their completeness under
  `tests/archive_fixtures`, and their dates.

No later-board movement, consensus target or bootstrap had been computed. If
any definition below changes after outcomes are seen, the change is reported
as a deviation next to the original. The original rule is never silently
replaced.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. Question

When the two filters disagree about one observation, which filter made the
better call? The test is what happens to that observation afterwards:

- Does the independent market later move toward it? Then it was **leading**
  evidence.
- Does its own source later retreat toward the market? Then it was
  **abandoned**.

## 2. Inputs

- **Boards.** Every archived scrape in `exports/archive/` that the contract's
  own source-health rule calls complete (`tests/archive_fixtures.
  _degraded_critical_sources` returns nothing). At registration that is
  98 of 133, spanning 2026-08-18 → 2026-09-30.
  - The other 35 (2026-07-14 → 2026-08-17) all fail on exactly
    `KTC_TradeDB` and `KTC_WaiverDB`. Those are transaction databases, not
    voting value sources.
  - Sensitivity S1 includes all 133.
- **What each replay is.** Each replay is *archived inputs rebuilt through
  today's pipeline code*. It is **never** presented as what production served
  that day.
  - Inputs per board:
    - the archived raw payload;
    - `CSVs/site_raw/` exactly as committed in the commit that added that
      archive, overlaid with the archive's own `site_raw/` copies;
    - per-source dataset state, replayed from git history through
      `src.sources.dataset_state.observe` using commits at or before that
      commit (the same method as `scripts/backfill_source_datasets.py`).
  - Freshness is evaluated at the payload's own `scrapeTimestamp`.
  - Built with `build_api_data_contract(raw, csv_root=<that tree>)` via
    `src/api/value_replay.build`.
- **Pins.** Recorded on every ledger record:
  - code SHA, plus a clean-tree flag;
  - payload sha256;
  - CSV-tree and state-tree content hashes;
  - flag snapshot;
  - Hampel constants;
  - local league-snapshot hashes.
- **Variants.** Each board is built twice. Only the challenger flag differs:
  - incumbent: flag off;
  - challenger: `joint_outlier_sparse_challenger` on.

  `source_family_cap` and `source_freshness_weighting` stay at their defaults
  (on).

## 3. Units of analysis

These definitions apply on one board (the origin, time *t*), over non-pick rows
where the filter runs (at least `_HAMPEL_MIN_N` voting observations).

- **Observation** *o = (p, s)*: player *p*, voting source *s*. Its value *v* is
  the stamped `valueContribution`: the source's vote on the board scale,
  computed **before** the filter (so it is identical in both builds; checked).
  - "Voting" means no `excludedReason`.
  - Work in logs: ℓ = ln v.
- **Family** *F(s)*: `data_contract.correlation_group_for(s)`, the B10
  correlation group.
- **K(t), challenger rescues**: observations the incumbent drops and the
  challenger keeps.
- **X(t), challenger rejects**: observations the incumbent keeps and the
  challenger drops.
- **R(t), agreed outliers**: observations both filters drop. Context only.
- **Leave-family-out consensus** *C₋f(p, t)*, the equal-family median:
  1. For each family *g ≠ f* that has a voting observation for *p* on board
     *t*, take *M_g* = the median of ℓ over *g*'s members.
  2. *C₋f* = the median of those *M_g*.

  It is defined only when at least 2 such families exist; otherwise the
  observation is not evaluable. It is unweighted on purpose: a target that used
  the challenger's freshness weights would grade the challenger with its own
  rule.
- **Daily thinning.**
  - **Origins** are the last complete board of each UTC day. Every board still
    gets a ledger record.
  - The **target** for horizon *h* (days) is the last complete board on day
    *d + h*. If that day has no board, the next later day is used, up to
    `max(1, h // 7)` days late. Never earlier. If no board falls in that
    window, the pair is missing.

## 4. Outcomes

Notation for an observation *o = (p, s)* with *f = F(s)*:

- *x* = its log value on the origin board;
- *c₀* = *C₋f(p, t)* on the origin board;
- *c₁* = *C₋f(p, t+h)* on the target board.

An observation is evaluable only when *c₀* and *c₁* exist and the gap is at
least 1% (|x − c₀| ≥ 0.01). Degenerate cases are counted and reported.

- **Consensus-lead share** *m* = clip((c₁ − c₀) / (x − c₀), −1, 1): the share
  of the gap the **independent** consensus closed toward the observation.
  - 1 means the consensus moved all the way to the observation.
  - 0 means it did not move.
  - Negative means it moved away.
- **Own-source retreat share** *r* = clip((x′ − x) / (c₀ − x), −1, 1), where
  *x′* is source *s*'s log value for *p* on the target board.
  - If *s* no longer lists *p* there, the observation is **delisted**. It is
    excluded from *r*, counted separately, and never treated as zero.
- **Descriptive classes**, at each horizon:

  | class | rule |
  |---|---|
  | LED | *m* ≥ 0.5 |
  | ABANDONED | *r* ≥ 0.5 and *m* < 0.5 |
  | DELISTED | the source no longer lists *p* |
  | UNRESOLVED | everything else |

## 5. Metrics, horizons, decision rule

- **Horizons**, fitted to the 43-day complete span:

  | role | horizon |
  |---|---|
  | primary | *h* = 7 days |
  | secondary | 3, 14 and 21 days |
- **P1 (primary)**: Δ = mean_K(m) − mean_X(m) at *h* = 7. A positive Δ means the
  evidence the challenger rescued was later led-to more than the evidence it
  newly rejected. That is the owner's question.
- **G1 (guard)**: is the challenger's published value no worse? For each origin
  row with at least one disagreement, let *D* be the families of its disputed
  observations, and *T* = *C₋D(p, t+h)*, the equal-family median over the other
  families, needing at least 2. Then

  > G1 = mean over rows of ( |ln V_ch − T| − |ln V_inc − T| ), at *h* = 7.

  Negative means the challenger's value sits closer to the later independent
  consensus.
- **Uncertainty.** Date-block bootstrap over 7-day calendar blocks counted from
  the first origin day: 4,000 resamples, seed 1571, percentile 95% intervals.
  Consecutive boards are strongly dependent: the same disagreement persists for
  days. Blocks absorb part of that dependence, and S2 removes it.
- **Minimum sample** (otherwise the answer is INSUFFICIENT):
  - at least 30 evaluable observations in each of K and X at *h* = 7;
  - from at least 10 distinct origin days;
  - covering at least 4 week-blocks.
- **Decision.**

  | verdict | rule |
  |---|---|
  | PROMOTION-ELIGIBLE (pending independent review) | Δ lower95 > 0 **and** G1 upper95 ≤ +0.005 **and** Δ > 0 at ≥ 2 of the 3 secondary horizons |
  | NOT BETTER | Δ upper95 < 0, **or** G1 lower95 > 0 |
  | INCONCLUSIVE | anything else that meets the minimum sample |

  - G1 upper95 ≤ +0.005 means non-inferior to within 0.5% log error.
  - INCONCLUSIVE has no detectable advantage. Near-ties keep the incumbent.
    It is reported with the accumulation needed (below).
  - Nothing here flips a flag. Promotion is an owner decision after
    independent review (Section N).
- **Accumulation target, when not decided.** Minimum effect of interest:
  |Δ| = 0.10, i.e. 10% of the gap. Blocks needed = current blocks ×
  (observed half-width / 0.10)², assuming SE scales as 1/√blocks. This is
  stated as a projection, not a promise.

## 6. Prespecified sensitivities (they report; they do not decide)

| id | sensitivity |
|---|---|
| S1 | All 133 archives, including the 35 that are degraded only in KTC_TradeDB/WaiverDB. |
| S2 | Episode-deduplicated: only the first origin of each consecutive run of the same (player, source, side). |
| S3 | Offense rows vs IDP rows, separately. |
| S4 | Origins on or after the first board where both `ktcCrowdSfTep` and `ktcTradesSfTep` vote. |
| S5 | G1 relative to persistence: G1 minus the same statistic with the target taken on the origin board. |
| S6 | KTC Crowd and KTC Trades merged into one exclusion group for the leave-family-out targets, because both are KTC. |

## 7. Adversarial checks (behaviour, not the decision)

Each check runs on **real rows** taken from the replayed boards, using their
real values, capped weights and families. Each is perturbed into one shape:

- **A1, the trap.** Three observations near 3000–3200 at weight 0.03, one fresh
  4600 at 1.0.
- **A2, stale cluster vs fresh single.** Several stale members of different
  families against one fresh outlier.
- **A3, correlated family members.** Several members of one family agree on a
  value far from the independent families.
- **A4, broken scale on a subset.** One source's values multiplied by ×5 and by
  ×0.2 on a subset of rows.

**Expected behaviour**, which follows from `src/api/joint_robust_filter.py`:

- dominant evidence is never dropped (`dominant_evidence_kept`);
- a multi-family row never becomes single-family (`kept_to_avoid_single_family`);
- a low-weight broken observation is dropped by both filters;
- a broken observation holding at least 50% of the row's weight is kept (a
  disclosed limitation).

Run through the filter function, and through the full pipeline wherever a
`csv_root` tree can express the perturbation. Every case is reported, pass or
fail.

## 8. Known limitations, stated in advance

- **Today's code, not production history.** Every replay uses today's code
  and config, so these are not historical production boards.
- **Freshness approximations.**
  - Per-row freshness clocks cannot be reconstructed from git: rows fall back
    to the source clock.
  - The vendor-published `upstreamPublishedAt` sidecar is not replayed, so
    those sources use their content clock.
- **The target is itself a model output:** an equal-family median of
  board-scale votes. It is independent of the disputed family, not of every
  modelling choice.
- **KTC Crowd and KTC Trades** are separate families in the registry (owner
  directive 2026-09-23). S6 tests whether that matters.
- **Shared Hill transform.** The leave-family-out target removes the source's
  own family. It does not remove the Hill transform every rank source shares.

## 9. Addendum: live shadow and accumulation (2026-10-01)

Written after the historical evaluation in §1–§8 had been computed. It changes
**nothing** about that evaluation. It governs only the live-shadow records
(`mode: live_shadow`), and none of those existed when it was written.

- **Same rules.** The live evaluation uses the definitions, horizons, metrics,
  bootstrap and decision rule of §3–§5 unchanged.
- **Pairs need the same pipeline fingerprint.** An origin board and its target
  board are paired only when both records carry the same
  `pipelineFingerprint`. The fingerprint is the sha256 of `data_contract.py`,
  `joint_robust_filter.py`, `player_valuation.py` and `freshness_v1.json`.
  - Votes built by different value code or curves are not on one scale, so a
    cross-version movement would measure the deploy, not the evidence.
  - `main` changes those files often, so live pairs will be sparse.
  - The live ledger therefore mainly answers **census** questions on real
    production boards:
    - how often each filter drops;
    - how often the two disagree;
    - whether either safeguard ever fires.
- **The decisive accumulating evaluation** is a re-run of `backfill`, which
  rebuilds every complete archived scrape under **one** code revision. The
  scheduled refresh adds new boards to the archive every day, so each re-run
  re-tests the §5 rule on a longer span.
  - Each re-run reports its span and code revision.
  - A re-run is a fresh application of the same rule, never a re-tuning of it.
