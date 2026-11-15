# Joint outlier + sparse-evidence challenger — evidence (2026-10-01)

#1555 Batch 2 Unit C, owner decision B. Challenger `joint-robust-v2`. **Both halves
ship OFF and are separately promotable; nothing is promoted.**

| half | flag | what it changes when ON |
|---|---|---|
| filter | `joint_outlier_sparse_challenger` | per-player outlier filter weighs family-capped evidence (needs `source_family_cap`; otherwise stands down to the incumbent) |
| sparse | `joint_sparse_limited_evidence` | one voting family is stamped `limitedEvidence`; the 0.30 retention is not applied |

Machine-readable results: `diagnostics.json`.

## Inputs (pinned, clean)

- Board: newest complete archived scrape `dynasty_export_20260930_130404.zip`
  (sha256 `27ffe6b9…`, scrape 2026-09-30T13:04Z), rebuilt through
  `src/api/value_replay.py` — 1,041 rows.
- Code: committed head `f2819ff96`, **clean worktree** (`workingTreeDirty: false`),
  with the local `data/leagues` snapshots copied in (gitignored; hashed in `pins`).
  **Local, not production.**
- One build per variant on identical inputs; only the flags differ.

## The filter half

- Uses the pipeline's own weighted median (`_weighted_median_sorted`: continuous
  in the weights, monotone in the values). v1 used a step median; review
  rejected it because it snaps the result on a 0.001 weight change.
- Under equal weights it **is** the incumbent: same median, MAD, threshold and
  survivor guard. Checked on 3,000 random rows.
- Dominant evidence (an observation with at least 50% of the row's weight) is
  never dropped for disagreeing.
- It never turns a row of two or more families into a single-family row, and
  the result doesn't depend on input order.

## Results

| variant | rows changed | top-50 / 100 / 200 / 400 churn | drops | notes |
|---|---|---|---|---|
| incumbent | — | — | 161 | |
| filter only | 54 | 1 / 1 / 4 / 1 | 173 | IDP 20 rows (median abs Δ 396, max 1,464); offense median abs Δ 18–75 |
| sparse only | 51 | 0 / 0 / 0 / 3 | 161 | the 51 former-haircut rows rise ×3.33 |
| both | 105 | 1 / 1 / 4 / 3 | 173 | |

- **Neither filter safeguard fired on this board** (0 `dominant_evidence_kept`,
  0 `kept_to_avoid_single_family`). Every filter difference comes from weighting
  the centre and scale toward fresher evidence. **It is not the trap being fixed.**
- **The trap** (3000/3100/3200 @ 0.03, 4600 @ 1.0) is latent on this board. The
  filter keeps all four and the pipeline's own blend gives about 4538. The
  incumbent gives 3100 (it drops the fresh 4600), and a naive weighted filter
  plus the haircut gives 1380. Tested on the filter and blend functions
  (`tests/api/test_joint_robust_filter.py`). A spy test proves the real capped
  freshness weights reach the filter inside the pipeline. **A synthetic trap
  row injected through the full payload is not built**, because freshness
  weights come from per-source dataset state, not from the row.
- **Biggest filter moves are IDP:**
  - Cedric Gray 3052 → 4516: the incumbent dropped Draft Sharks IDP and
    FantasyPros IDP; v2 keeps both.
  - Kevin Winston 2873 → 2090: v2 drops Draft Sharks IDP and IDP Show.
  - Top-200 entered: Antonio Williams, Laiatu Latu, Rhamondre Stevenson, Tuli
    Tuipulotu.
  - Top-200 left: Derwin James, Jamien Sherwood, Josiah Trotter, Kevin Winston.
  - Top-100: Cedric Gray in, Derrick Henry out.
- **Sparse half:** DJ Rogers (TE, Draft Sharks only) goes from unranked 695 to
  rank 271 at 2319. That promotes one rank list's opinion with no
  corroboration. Thin coverage is itself evidence here, because the other
  eligible sources did not list the player.

## Recommendation (one candidate)

**The candidate is the filter half (`joint-robust-v2`). My recommendation is not
to promote it yet.** It removes a real latent defect (weak evidence removing
strong evidence), and it is structurally safe: bounded influence, no
manufactured singletons, it reduces to the incumbent under equal weights, and
results don't depend on order.

On this board, though, its effect (54 rows, 4 top-200 swaps, mostly IDP) comes
entirely from weighting. We have no outcome evidence that the weighted centre is
more accurate than the unweighted one. Next step: run it in shadow on successive
boards, comparing the variants on each refresh. Promote it only if:

- the safeguards fire on real boards, or
- a point-in-time backtest favours it.

**The sparse half as built is not recommended.** Removing the haircut without an
independent prior over-promotes single-list players. Your rejection of "one
family ⇒ 30%" stands, so what replaces it has to be a calibrated, independent
estimate. Proposed v2 (not built): a censored-absence bound. Each eligible
**family** that did not list the player bounds the value from above at its list
end. Absences would be counted by family, because list depth and eligibility are
correlated within a family, and the bound calibrated by holdout near list ends.

## Remaining decisions (owner)

1. Filter half: shadow-only as recommended, or promote now with the disclosed
   54-row / 4-swap effect.
2. Sparse half: authorise the censored-absence v2 unit, or keep the incumbent
   haircut until it exists.

Independent review: the first review (REQUEST_CHANGES) led to v2. Its findings
are listed in the PR.
