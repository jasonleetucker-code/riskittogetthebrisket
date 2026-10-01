# Joint outlier + sparse-evidence challenger — evidence (2026-10-01)

#1555 Batch 2 Unit C, owner decision B. Challenger `joint-robust-v1`, flag
`joint_outlier_sparse_challenger` (**default OFF; not promoted**). Machine-readable
results: `diagnostics.json` (pins, board diffs, per-row drop-set changes, every
former-haircut row, membership churn, outlier census on and off).

## Inputs (pinned)

- Board: newest complete archived scrape, `dynasty_export_20260930_130404.zip`,
  rebuilt locally through `src/api/value_replay.py` (`pins` block in
  `diagnostics.json`: code revision, payload/source-CSV/config/freshness hashes,
  local league snapshots, flag snapshot). **Local, not production.** The working
  tree carried uncommitted challenger code when this ran (`workingTreeDirty`).
- Same inputs for every variant; only the flag / diagnostic seam differ.

## What the challenger changes

1. **Filter half.** The per-player outlier filter uses family-capped evidence
   weights (weighted median centre, weighted MAD scale, the incumbent's
   `max(2.75·scale, 1000)` threshold and `min_n = 4`). Dominant evidence (≥ 50% of
   the row's weight) is never dropped for disagreeing. The filter never turns a
   row of 2+ families into a single-family row. The outcome is the same in any
   input order.
2. **Sparse half.** The 0.30 single-family value retention is replaced by a
   `limitedEvidence` stamp. The value stays as the evidence gives it, and B11
   confidence already caps one family at LOW.

## Results

| variant | rows changed | top-50 / 100 / 200 / 400 churn | notes |
|---|---|---|---|
| filter only (sparse treatment = incumbent haircut) | 38 | 1 / 0 / 0 / 0 | median abs Δ 18–78 by group; max 1007 (CJ Allen, IDP) |
| full challenger (filter + no haircut) | 89 | 1 / 0 / 0 / 3 | the 51 former-haircut rows rise ×3.33; three single-source TEs enter the top 300 |

- **Trap (synthetic):** 3000/3100/3200 @ 0.03 and 4600 @ 1.0. The challenger keeps
  all four and the pipeline's own weighted blend gives **≈ 4538**. The incumbent
  drops the fresh 4600 (→ 3100), and a naive weighted filter plus the haircut
  gives 1380. This is pinned in `tests/api/test_joint_robust_filter.py`.
- **Live-shaped board:** neither safeguard fired (0 `dominant_evidence_kept`, 0
  `kept_to_avoid_single_family`). On this board the trap is latent: it appears
  when freshness weights get small. Every filter difference comes from the
  weighted centre and scale.
- **Drops:** 161 (incumbent) → 175 (challenger). The most dropped from one row is
  5 of 16 (Joe Burrow, Jalen Hurts), against the incumbent's 4 of 16. The top-50
  swap is Carson Schwesinger in, DeVonta Smith out.
- **Sparse half:** removing the haircut alone moves DJ Rogers (TE, Draft Sharks
  only) from unranked 695 to rank 271 at 2319. That is one rank list's opinion
  promoted with no corroboration. Thin coverage is itself evidence here: the
  other eligible sources did not list the player. A haircut-free value ignores
  that.

## Recommendation (one candidate)

**Candidate for the owner's promotion decision: the filter half only**
(`joint-robust-v1` filter with the single-family value treatment unchanged). Its
blast radius is bounded (38 rows, no top-100 change), it fixes the documented
weak-removes-strong defect structurally, and its order invariance and
no-singleton guarantees are tested.

**Not recommended: the sparse half as built.** Removing the haircut without an
independent prior over-promotes single-list players. The owner's rejection of
"one family ⇒ 30%" stands. What replaces it has to be a calibrated, independent
estimate, not just "no haircut". A defensible next candidate (v2, not built) is
to treat each eligible source that did **not** list the player as censored
evidence: the player sits below that source's list end. That gives an upper bound
from evidence independent of the one source that did list him, and the bound
would be calibrated by holdout on rows near list ends. That is new
methodology, and it needs its own evidence and approval.

## Remaining promotion decision (owner)

1. Promote the filter half? That means turning the flag on with the sparse
   treatment set to the incumbent haircut, which needs the seam turned into a
   real configuration value first. The alternative is to keep the incumbent.
2. Authorise a v2 sparse-evidence unit (censored-absence bound), or keep the
   incumbent haircut until one exists.

Independent review status: requested, not yet completed when this file was
written. See the PR.
