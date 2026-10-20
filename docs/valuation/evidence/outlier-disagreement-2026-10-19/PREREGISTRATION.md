# Disagreement-preserving outlier policy: preregistration

**Registration only.** This document is committed before the candidate below has been
run on any board of the frozen dataset. No frozen-board drop set, consensus, target,
stability figure, adversarial result or bootstrap has been computed for it. If any
definition changes after results are seen, the change is reported as a deviation beside
the original, and the original rule is never silently replaced.

Authority: owner directive 2026-10-19, "Universal source voting and freshness policy",
§6 (fix the IDP outlier-filter problem), with §1 (DLF IDP and DLF Rookie IDP restored to
voting) and §9 (validate). It follows the repo's preregistration pattern
(`../joint-filter-shadow-2026-10-01/PREREGISTRATION.md`, inherited by
`../rank-space-hampel-2026-10-17/`, `../rank-space-hampel-per-vote-2026-10-17/` and
`../idp-outlier-n3-2026-10-18/`). It is a new, separate question and does not reopen or
combine with those experiments.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. What was seen before registration

Only these, and none of them is a frozen-board outcome for this candidate:

* **The diagnosis board**, outside the frozen dataset: `exports/latest/dynasty_data_2026-10-19.json`
  (scrape 2026-10-19T05:23:48Z, sha256 `b639608f…e11c`), built at `6aa2800196` with the
  DLF IDP hold OFF (`scripts/outlier_policy_diagnose.py`):
  * the incumbent filter rejects **130** votes (98 offense, 32 IDP; Draft Sharks 52 offense
    and 18 IDP). On 90 of them the threshold had collapsed to the 1,000-point floor;
  * every one of the 130 is a correctly identified, normally priced, non-stale
    observation (no ambiguous match, no position or Sleeper-id conflict, no pricing
    fallback, no zero-weight vote); 120 of 130 have another provider family within 2x
    of them;
  * the challenger's rule, applied to the same stamped votes, rejects **1** vote (Draft
    Sharks on Brock Bowers, at distance 1.393 against a 1.386 threshold).
* **Calibration statistics on that board**, used to fix the constants below. In the
  smoothed implied-rank coordinate with `RANK_OFFSET = 10`, the leave-family-out distance
  of all 6,397 assessable votes has p99 0.64-1.15 and maximum 1.39 in every consensus-rank
  band (0-12, 12-50, 50-150, 150-400, 400+); with offset 1 the top band's p99 was 2.34,
  which is why the offset exists. Per `(source, asset class)`, the largest median signed
  distance was 0.213 (Draft Sharks offense) and the largest median absolute distance 0.284.
* **The committed `idp-hampel-n3-v1` result** (`../idp-outlier-n3-2026-10-18/README.md`):
  INSUFFICIENT, P1 +0.112 at h = 7.

## 1. Question

The incumbent per-player filter (`data_contract._hampel_filter_per_player`: K 2.75, MAD
scale, 1,000-point floor, n ≥ 4) removes a vote whenever it sits far from the row median.
On most rows several votes are near-identical by construction, the MAD collapses and the
rule becomes a fixed 1,000-point band. The DLF IDP restoration adds a fourth voter on
~158 IDP rows and switches the rule on there.

**Does a policy that rejects only observations carrying evidence of data error (gross and
uncorroborated per row, or a mis-scaled whole board) keep the consensus at least as close
to independent later evidence as the incumbent, stay as stable, and still catch corrupted,
misidentified and mis-normalized observations?**

## 2. Champion and challengers

All three are built in the directive's restored state, **DLF IDP hold OFF**:

| name | definition | flag |
|---|---|---|
| **incumbent** (champion, "current production with DLF restored") | the served filter, unchanged | none |
| **policy** (`outlier-corroborated-v1`, the candidate) | `src/api/outlier_policy.py`, defined below | `outlier_disagreement_policy` ON |
| **n3** (descriptive comparison only) | the preregistered `idp-hampel-n3-v1` rule in the restored state | `idp_hampel_n3_challenger` ON |

Separately, `idp-hampel-n3-v1` is re-run **exactly as its own preregistration states**
(DLF hold ON, its own builds, target, seed and verdict table) with the unmodified
`scripts/idp_evidence_challengers.py`, to check that its committed verdict reproduces at
this code revision. That run answers its own question and does not feed this decision.

### The candidate, `outlier-corroborated-v1`

Constants (in `src/api/outlier_policy.py`, none tuned after registration):

| constant | value | meaning |
|---|---|---|
| `RANK_OFFSET` | 10 | rank smoothing at the top of the board |
| `REFERENCE_N` | 500 | the board's percentile reference |
| `GROSS_RANK_FACTOR` | 4 | gross distance, ln 4 = 1.386 |
| `CORROBORATION_FACTOR` | 2 | corroboration distance, ln 2 |
| `VALUE_FLOOR` | 1,000 | the incumbent's floor, now a second condition |
| `MIN_OTHER_FAMILIES` | 2 | families other than the vote's needed for a reference |
| `DOMINANT_SHARE` | 0.5 | dominant-evidence guard |
| `BOARD_MIN_ROWS` | 20 | rows a board needs to be screened |
| `BOARD_SHIFT_FACTOR` | 1.5 | median signed distance limit, ln 1.5 |
| `BOARD_SPREAD_FACTOR` | 2 | median absolute distance limit, ln 2 |

* **Coordinate.** Each vote `v` on a non-pick row maps to
  `u = ln(RANK_OFFSET + 500 · p)`, `p = c · (9999 / v − 1)^(1/s)`, with `(c, s)` the row's
  scope master (IDP rows the IDP master, every other row the OFFENSE master: the same
  selection as `rank-space-hampel-v1`). A non-positive or non-finite vote has no
  coordinate: it is never assessed and never dropped.
* **Reference.** For vote *k*, each provider family other than *k*'s
  (`data_contract.correlation_group_for`) contributes the median of its members'
  coordinates (and values); the reference is the median of those family medians. It needs
  at least 2 other families. One provider's two boards are one voice.
* **Per-row rejection** (`gross_uncorroborated_error`): all of
  * |u_k − reference| > ln 4;
  * |v_k − reference value| > 1,000;
  * no other family's median coordinate lies within ln 2 of u_k;
  * k's family-capped effective weight (`cap_family_weights` over the row's effective
    weights, the registry base) is below half of the row's total.
* **Board screen** (`board_scale_mismatch`): over every non-pick row, per
  `(source, asset class)` with at least 20 assessable votes, the median signed and the
  median absolute `u − reference`. A board with |median signed| > ln 1.5 or median
  absolute > ln 2 is flagged and its votes on that asset class are excluded (and are not a
  reference for other votes). In the pipeline this is a second ranking pass, run only when
  the first pass flags something; the votes are pre-filter, so the screen is exact.
* **Guards.** Picks are never assessed. If the drops would leave fewer than 2 observations,
  or one family on a row that had two or more, nothing is dropped on that row.
* **Everything else is the incumbent's code path**: freshness weights, the B10 family cap,
  the count-aware blend, the single-source haircut, confidence. Lost-evidence seats replay
  the same policy on the observed panel (unweighted).

## 3. Inputs and pins

* **Dataset (frozen).** `../idp-outlier-n3-2026-10-18/ARCHIVE_MANIFEST.json`: 140 boards,
  **105 complete** (2026-08-18 23:02Z → 2026-10-18 11:47Z). Boards added later are
  excluded. A manifest board pruned from the working tree is recovered byte-exact from the
  commit that added it and hash-checked. A missing or mismatched board makes the run
  incomplete, reported as such.
* **Rebuild procedure.** Inherited unchanged (joint-filter preregistration §2): each
  board's payload; `CSVs/site_raw/` as committed with that archive, overlaid with the
  archive's own `site_raw/`; per-source dataset state replayed from git history;
  freshness at the payload's `scrapeTimestamp`; `value_replay.build` →
  `build_api_data_contract(csv_root=…)`; one code revision, clean tree.
* **Flags pinned on every build:** `source_freshness_weighting` ON, `source_family_cap`
  ON, `idp_deep_tail_native_challenger` OFF, and the joint, sparse, rank-space and per-vote
  challengers OFF. Per build: `dlf_offense_only_vote` OFF; `outlier_disagreement_policy`
  and `idp_hampel_n3_challenger` as in §2.
* **Ledger.** One gitignored record per board, `data/outlier_policy_replay/`, carrying the
  code SHA and clean-tree flag, payload sha256, CSV and state tree hashes, the flag
  snapshot and every policy constant.
* **Structural checks** (implementation checks, not verdicts): every vote
  (`valueContribution`) is identical across the three builds; with the policy flag OFF a
  default board is byte-identical to `main` (`scripts/golden_board.py` +
  `scripts/board_diff.py --expect-no-value-change`).

## 4. Metrics

**Origins** are the last complete board of each UTC day. The **target** for horizon *h* is
the last complete board on day d + h, or the next later day up to `max(1, h // 7)` days
late, never earlier. Primary horizon h = 7; secondary 3, 14, 21. Uncertainty: date-block
bootstrap over 7-day calendar blocks from the first origin day, 4,000 resamples, percentile
95% intervals, **seed 2033** (new).

### M1 (primary): out-of-sample agreement with a held-out source

The held-out family is excluded from BOTH methods' inputs, so no method is graded by its
own survivors.

* **Units.** (origin board, non-pick row, held-out family F) where, in the incumbent
  build of the origin board, F votes on the row and the row has at least 3 other voting
  families, and F votes on the row on the target board.
* **Reduced votes.** R = the row's origin votes (`valueContribution`) without F's members;
  pre-cap effective weights from the stamps.
* **Each method's decision on R:** incumbent `_hampel_filter_per_player(R)`; policy
  `assess_row(R, …)` with the board screen recomputed on the origin board without F's
  members; n3 `_hampel_filter_per_player(R, min_n=3)` on IDP rows (incumbent elsewhere);
  none (keep all) for reference.
* **Consensus.** Survivors' weights family-capped (`cap_family_weights`, base 1.0), then
  `weighted_count_aware_mean_median_blend`. The post-blend stages (IDP anchor shrinkage,
  haircut, overrides) are not emulated; the emulator is identical for every method, and its
  fidelity to the published blend is reported.
* **Target.** T = median of ln(vote) over F's voting members on the target board.
* **Loss.** L = |ln V − T|.
* **P1** = mean over policy-disputed units (the policy and incumbent survivor sets differ)
  of L_policy − L_incumbent, at h = 7. Negative means the policy's consensus sits closer to
  the held-out provider's opinion a week later. The all-unit mean (zeros included) is
  reported beside it.

### M2 (reported, not decisive): G1 guard on published values

The joint framework's G1 on the full-pipeline published values: rows whose
`rankDerivedValue` differs between the policy and incumbent builds; T = equal-family median
on the target board over the families other than the disputed observations' (≥ 2);
G1 = mean of |ln V_policy − T| − |ln V_inc − T|. **Stated in advance:** when the challenger
mostly RESCUES votes, T is built from the families the incumbent kept, so G1 is biased
toward the incumbent by construction. It is reported, not used in the verdict.

### M3 (descriptive): what happened to the disputed observations

The inherited consensus-lead share *m* and own-source retreat share *r*
(joint-filter preregistration §4), for K (incumbent drops, policy keeps) and X (policy
drops, incumbent keeps), with the LED / ABANDONED / DELISTED / UNRESOLVED classes. An
observation that its own source later abandons is evidence of a transient error; one the
source keeps is evidence of a held opinion.

### M4: board stability

Per method, for consecutive origin days: mean over rows priced on both boards (non-pick,
`rankDerivedValue` > 0) of |ln V(d+1) − ln V(d)|. Ratio = Σ policy / Σ incumbent, with a
block-bootstrap interval over the pair's start day. IDP and offense also reported.

### M5, M6: rejection census and value changes

Votes rejected per board by method, source, asset class and reason; board-screen firings
listed board by board. Value changes policy vs incumbent (and n3 vs incumbent, and
incumbent hold-off vs hold-on): rows changed, median / p90 / p99 / max |Δ| by asset class,
on every board and on the newest frozen board. **Every row moving more than 30% on the
newest frozen board is explained** (which votes the methods treat differently, and their
values).

### M7: adversarial suite (gate)

Source rows: every row with at least 3 voting families on the newest frozen board
(`dynasty_export_20261018_114711`), incumbent build. Seed 2033 chooses one voting source
per row and case. Each method's decision plus the M1 emulator gives V(clean) and
V(corrupt); the policy's board screen is the clean board's (a one-row change cannot move a
board median by a material amount). A case is **material** when
|ln V_none(corrupt) − ln V_none(clean)| ≥ 0.10. A method **passes** a case when it drops
the corrupted observation, or when |ln V(corrupt) − ln V(clean)| < 0.10.

| case | corruption |
|---|---|
| AD1a / AD1b | the vote ×5 (capped at 9,999) / ×0.2 |
| AD1c / AD1d | the vote ×20 (capped) / ×0.05 (floored at 1) |
| AD2 | misidentification: the vote replaced by the same source's vote for another player on the board whose consensus rank differs by ≥ 100 |
| AD3 | a whole board on the wrong scale, for `dynastyNerdsSfTep`, `flockFantasySf`, `fantasyCalc` (offense) and `fantasyProsIdp` (IDP): (a) ranks ×2, (b) ranks ×5 (each vote re-priced at percentile 2p / 5p on the row's curve), (c) values ×0.01, (d) order reversed within the source's covered rows |
| AD4 | single-source spike: rows with consensus rank 150-400, one vote set to 9,000 |

**Gate for the policy** (fixed here): pass rate among material cases ≥ 95% for AD1c, AD1d
and AD4, and ≥ 90% for AD1a, AD1b and AD2; and all 16 AD3 boards flagged by the board
screen. The incumbent's and n3's pass rates are reported beside it, by family count
(3, 4-5, ≥ 6).

Two end-to-end checks through the full pipeline with the flag ON, on a copy of the newest
frozen board's tree: (E1) `dynastyNerdsSfTep.csv` with every rank doubled must be flagged
and its offense votes excluded; (E2) two far-apart players' rows swapped in one source CSV
must have the swapped votes rejected wherever the swap is material.

## 5. Decision

* **Minimum sample** at h = 7: ≥ 300 policy-disputed M1 units, from ≥ 10 origin days,
  covering ≥ 4 week-blocks. Otherwise **INSUFFICIENT**.
* **Board-screen false positives.** Every firing on a real frozen board is listed. A firing
  counts as a true positive only when that source's CSV for that board shows a recorded
  structural change against its neighbouring boards (row count, rank range or value
  scale). Any other firing is a false positive.

| verdict | rule |
|---|---|
| **PROMOTION-ELIGIBLE** (pending independent validation, then owner decision) | P1 upper95 ≤ +0.005 **and** the M7 gate passes **and** no board-screen false positive **and** M4 ratio upper95 ≤ 1.10 |
| **NOT ELIGIBLE** | P1 lower95 > +0.005, **or** the M7 gate fails, **or** a board-screen false positive, **or** M4 ratio lower95 > 1.10 |
| **INCONCLUSIVE** | anything else that meets the minimum sample |

* **Why non-inferiority, not superiority.** The owner's directive already decides the
  policy preference (keep valid opinions). The evidence question is whether doing so
  costs accuracy, stability or safety. P1 upper95 < 0 is reported as "better", a qualifier
  that changes no verdict.
* **No parameter is tuned after results are seen.** Nothing here flips a flag: the flag
  ships OFF; promotion needs an independent fresh-context validation and an owner
  decision.

## 6. Sensitivities (they report; they do not decide)

| id | sensitivity |
|---|---|
| S1 | all 140 archives |
| S2 | offense and IDP separately |
| S3 | each held-out family separately |
| S4 | h = 0: target on the origin board (persistence) |
| S5 | the policy without the board screen (per-row rule only) |
| S6 | DLF excluded as a held-out family |
| S7 | episode-deduplicated: the first origin of each run of the same (row, held-out family, disputed set) |

## 7. Known limitations, stated in advance

* **Emulated consensus in M1.** The held-out evaluation needs one consensus per held-out
  family, which the full pipeline cannot produce without a rebuild per family. The
  emulator reproduces the filter, the family cap and the count-aware blend, not the IDP
  anchor shrinkage or post-blend overrides.
* **One provider at a time.** A held-out family's later opinion is one provider's view, not
  truth. Averaging over every family and row is what makes it a test of predictive value.
* **Top-of-board blind spot.** Below `RANK_OFFSET` ranks, distances compress, so an upward
  corruption of a top vote that is capped at 9,999 is often not gross. Its harm is bounded
  by the cap and, on wide rows, by the blend's trim.
* **Coincidental corroboration.** A corrupted value that happens to land within 2x of
  another provider's real opinion is kept. Correlated errors in two providers are
  indistinguishable from shared opinion (the pipeline's existing named limitation).
* **Moderate scale errors.** A whole-board error below 1.5x is not caught by the screen and
  rarely by the row rule.
* **Today's code, not production history**, and the freshness approximations of every
  replay so far.
* **Cost.** A flagged board costs a second ranking pass; a healthy board costs one deep
  copy of the ranking inputs.
