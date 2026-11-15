# IDP deep-tail native-value challenger: preregistration

**Registration only. Nothing about this challenger has been implemented or run.**
No repriced vote, published value, metric or outcome has been computed for it.
If any definition below changes after results are seen, the change is reported as
a deviation beside the original. The rule here is never silently replaced.

Authority: owner closeout 2026-10-18, PART 2, Decision 6 ("IDP deep-tail
normalization: RUN A CHALLENGER"). It follows the repo's preregistration pattern
(`../joint-filter-shadow-2026-10-01/PREREGISTRATION.md`, as inherited by
`../rank-space-hampel-2026-10-17/`, `../rank-space-hampel-per-vote-2026-10-17/`
and `../idp-outlier-n3-2026-10-18/`). It is a new, separate question and does not
combine with any of those experiments.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. What motivated it (incumbent state only)

Finding N-1 of `docs/sources/IDP_REHABILITATION_EVALUATION_2026-10-18.md` §3,
measured on the incumbent at `c290dea0a8` with the 2026-10-18 11:47Z payload:

* For every IDP row the IDP Trade Calculator prices value-direct, its native value
  was compared with the GLOBAL-master Hill value a rank vote gets at the **same
  effective rank** in the `shared_market` pool.
* Median ln(native / Hill) by effective-rank band: 1–100 +0.119; 101–250 +0.118;
  251–500 +0.048; **501–904 −0.336** (n = 232, ratio ×0.71).
* Ranks 501–904 lie past the Hill fit domain (p > 1 at the 500-rank reference) and
  are priced by the B4 tail-policy extension, which saturates at rank 904.
* In that band sit 232 of IDP Trade Calculator's 377 IDP votes, 158 of Draft
  Sharks', 103 of FantasyPros' and 26 of DLF's (hold off).

These are facts about the incumbent. The question: **for deep IDP rank votes, does
pricing them at the IDP Trade Calculator's own native value for the same effective
rank give a better-calibrated board than the incumbent Hill/tail extrapolation,
without harming rank order, position balance, source independence or stability?**

The owner directive is explicit: the approved Hill method is not replaced unless
the challenger convincingly improves on it, and the tail saturation rank and the
global valuation coordinate are not altered.

## 1. Champion and challenger

* **Champion.** The served pipeline, unchanged: every rank vote is priced
  `percentile_to_value(rank_to_percentile(r, N = 500))` on the master its pool
  routes to (`shared_market` → GLOBAL), with the B4 tail policy saturating at
  `TAIL_SATURATION_RANK = 904`.
* **Challenger `idp-deep-tail-native-v1`.** A new flag,
  `idp_deep_tail_native_challenger`, default **OFF**, added in the implementation
  unit and not by this document. With it ON, a vote is repriced when **all** hold:
  1. the row's `assetClass == "idp"`;
  2. the source is priced by the rank path (it is not one of the value-direct
     sources; a value-direct source's fallback to the curve is not repriced);
  3. the vote's recorded `rankCoordinatePool` is `shared_market`;
  4. its effective rank r satisfies **500 < r ≤ 904**;
  5. r lies inside the native ladder's covered range on that build (below).

  Its value becomes **N(r)**, the native ladder's value at r. Nothing else about
  the vote changes: effective rank, pool, percentile stamp, freshness / health /
  coverage weight, family, TE handling (IDP rows have none), outlier filter, blend,
  haircut and confidence code paths are the incumbent's.
* **The native ladder N.** Built once per build, before the blend loop, from the
  IDP Trade Calculator's value-direct votes exactly as the pipeline prices them:
  * one point per row (offense, IDP and pick rows alike) where `idpTradeCalc` has
    an effective rank and takes the value-direct path (raw value positive, inside
    its declared range, source not suppressed, site maximum positive);
  * the point is (effective rank, raw / site_max × 9999), before any TE transform;
  * synthetic far-future pick rows (the board's own derivations,
    `synthetic_pick_derivation_map`) are excluded, as the bridge backbone excludes
    them, so a value the board derived never shapes the curve;
  * points are sorted by rank and made non-increasing by pool-adjacent-violators
    (isotonic regression; ties in rank are averaged first);
  * N(r) is linear interpolation between the two nearest points;
  * the covered range is from the shallowest to the deepest point. A rank outside
    it, or a ladder with fewer than two points deeper than rank 500, is not
    repriced: the incumbent value stands. Missing is never zero.
* **What is held fixed, by construction.** No Hill constant, no reference N, no
  tail saturation rank and no rank coordinate changes. Ranks ≤ 500 and ranks
  beyond 904 are priced exactly as today. Offense and pick rows are not repriced.
  The map is monotone non-increasing in r, so every source's own ordering of the
  players it ranks is preserved exactly: the challenger changes the level of deep
  votes, never a source's opinion of order.
* **Precedence and pins.** Every filter challenger stays OFF in every build
  (`joint_outlier_sparse_challenger`, `joint_sparse_limited_evidence`,
  `rank_space_hampel_challenger`, `rank_space_hampel_per_vote_challenger`,
  `idp_hampel_n3_challenger`).
* **Stamp.** A repriced vote carries `deepTailNative = {hillValue, nativeValue}`
  in its `sourceRankMeta` entry, so the name travels with the number.

**Stated in advance:** at the median the challenger lowers a deep rank vote by
about e^−0.34 (N-1). Its calibration against the IDP Trade Calculator's own values
is therefore expected to improve *by construction*. §3 treats that metric as
necessary, not sufficient.

## 2. Inputs and pins

* **Dataset (frozen).** The same frozen manifest as `idp-hampel-n3-v1`:
  `../idp-outlier-n3-2026-10-18/ARCHIVE_MANIFEST.json`, sha256
  `0a3d5c1f6129e9fddc4ecf777b9bc478edd93a06f6099e1cce1a3707f1d82318`:
  * 140 boards; **105 complete** (2026-08-18 23:02Z → 2026-10-18 11:47Z);
  * the other 35, degraded only in `KTC_TradeDB` / `KTC_WaiverDB`, are used only
    in S1.

  Boards added later are excluded. A missing or hash-mismatched board makes the
  run incomplete, and it is reported as such.
* **Rebuild procedure.** Inherited unchanged from the joint-filter
  preregistration §2 (each board's payload; `CSVs/site_raw/` as committed with the
  archive, overlaid with the archive's `site_raw/`; per-source dataset state
  replayed from git history; freshness at `scrapeTimestamp`;
  `value_replay.build` → `build_api_data_contract(csv_root=…)`; one code revision,
  clean tree).
* **Flags pinned on every build:** `dlf_offense_only_vote` ON (production state),
  `source_freshness_weighting` ON, `source_family_cap` ON, the filter challengers
  OFF.
* **Builds per board** (builds 1 and 3 are the same builds `idp-hampel-n3-v1`
  uses, so the two experiments share them):
  1. incumbent;
  2. challenger (`idp_deep_tail_native_challenger` ON);
  3. holdout read: the incumbent with `dlf_offense_only_vote` OFF, used only to
     read DLF IDP's own raw rank. Nothing from build 3 is compared as a board.
* **Ledger.** Gitignored, `data/idp_evidence_challengers/`. Each record carries the
  code SHA, the clean-tree flag, the payload sha256, the CSV / state tree hashes,
  the flag snapshot, the Hill constants and the tail saturation rank.

## 3. Units, targets, metrics, decision

**Origins and targets** (inherited): origins are the last complete board of each
UTC day; the target board for horizon h is the last complete board on day d + h,
or the next later day up to `max(1, h // 7)` days late, never earlier. Primary
h = 7; secondary 3, 14, 21.

**Bootstrap** (inherited form): date-block bootstrap over 7-day calendar blocks
from the first origin day, 4,000 resamples, percentile 95% intervals,
**seed 2031**. The seed is new (not 1571, 17, 2027 or 2029).

### C1 — calibration (primary, necessary)

* **Unit.** One vote on an origin board (build 1) that the challenger would
  reprice under §1 rules 1–5, from a source other than `idpTradeCalc`, that voted
  (no `excludedReason`).
* **Target T.** The same player's IDP Trade Calculator value-direct vote
  (`valueContribution`) on the target board (build 1). A vote whose player has no
  such vote on the target board is not evaluable: counted, never imputed.
* **Predictions.** P_inc = the vote's own `valueContribution` on the origin board.
  P_ch = N₋ᵢ(r): the native ladder of the origin board rebuilt **without the
  player's own IDP Trade Calculator point** (leave-player-out), from build 1's
  stamps, through the same ladder function the pipeline uses.
* **C1** = mean over evaluable votes of |ln P_ch − ln T| − |ln P_inc − ln T|.
  Negative favours the challenger.
* **Why it is not sufficient.** T and N come from one provider. Leave-player-out
  and the forward horizon stop a player's own number from grading itself, but the
  level of N is the IDP Trade Calculator's. C1 measures agreement with that market's
  scale, which is what the coordinate claims to be, and it cannot by itself show
  the challenger is closer to truth.

### B1 — bias and position-level effects (gate)

* Median signed ln P − ln T, per method, for C1's votes; overall and per family
  DL / LB / DB (`canonical_position_group`).
* **Position harm.** C1 recomputed within each family that has ≥ 30 evaluable
  votes at h = 7.

### R1 — rank preservation against a held-out opinion (primary, non-circular)

* **Unit.** One origin day.
* **Rows.** IDP rows priced (`rankDerivedValue` > 0) in both build 1 and build 2
  on the origin board, and listed on the **target** board's DLF IDP board
  (`dlfIdp` raw rank, from build 3). `dlfRookieIdp` ranks within the rookie class
  only and is not used here.
* **R1** = mean over origin days of ρ(V_ch, −rank_DLF) − ρ(V_inc, −rank_DLF), with
  ρ the Spearman correlation on that day's rows. Positive favours the challenger.
* DLF IDP votes in neither build, and an order comparison does not depend on how
  either method prices values, so R1 does not grade a method by its own scale.
* **Independence caveat.** DLF IDP's order correlates with the IDP Trade
  Calculator's (raw 0.87, leave-pair-out residual 0.45; recorded as measured
  dependence). Under gate 7 of `docs/valuation/HILL_AUTOPILOT_V2.md` it is
  therefore **not** an eligible independent validation target.

### H1 — historical stability (gate)

* For each pair of consecutive origin days, the mean over IDP rows priced on both
  days in both builds of |ln V(d′) − ln V(d)|, per method.
* **H1** = (mean over pairs, challenger) / (mean over pairs, incumbent). Values
  above 1 mean the challenger's published IDP values move more from day to day.

### S — source independence (structural guard)

On every board, between builds 1 and 2:

* every row's voting sources, exclusions, freshness / health / coverage weights,
  family assignment, family-cap factors, `effectiveSourceCount` and
  `independentSourceCount` are identical;
* every repriced vote is a vote the incumbent also cast, with the same effective
  rank and pool;
* within each source, no two repriced votes invert order relative to effective
  rank (the map is monotone).

A violation is a bug: fix it, note it and re-run. The frozen definitions do not
change. Reported alongside, deciding nothing: the share of moved rows whose
published value moves toward the row's own IDP Trade Calculator vote.

### Structural scope guard (implementation check)

Every non-IDP row's votes, drops and value are identical between builds 1 and 2,
except the documented downstream couplings, which are reported, not suppressed:
current-year slot picks tethered to the merged rookie pool, the two-way player
boost, and board-wide ordinal fields (rank, percentile, tier). IDP rows with no
repriced vote may differ only through those couplings or because the outlier
filter's decision on the row changed; each such row is counted.

### Board-impact rails (gate)

On **every** complete board, incumbent vs challenger over the whole board, the
catastrophe rails of `config/model_registry/hill_autopilot_policy.json` →
`boardImpact`: unpriced fraction ≤ 5%; median / p90 / max absolute relative value
change ≤ 30% / 45% / 65%; top-25 overlap ≥ 20; top-100 overlap ≥ 85; median / p90
absolute rank shift ≤ 30 / 125.

### Minimum sample

At h = 7: C1 needs ≥ 200 evaluable votes from ≥ 10 distinct origin days covering
≥ 4 week-blocks; R1 needs ≥ 10 origin days with ≥ 30 rows each. Otherwise the
verdict is **INSUFFICIENT**.

### Verdicts

| verdict | rule |
|---|---|
| PROMOTION-ELIGIBLE (pending independent review, then owner decision) | C1 upper95 < 0 at h = 7 **and** C1 < 0 at ≥ 2 of 3 secondary horizons **and** C1 ≤ 0 in every family with ≥ 30 votes **and** R1 lower95 ≥ −0.005 **and** H1 upper95 ≤ 1.10 **and** the guards hold **and** the rails hold on every complete board |
| NOT BETTER | C1 lower95 > 0, **or** C1 lower95 > 0 within any family with ≥ 30 votes, **or** R1 upper95 < 0, **or** H1 lower95 > 1.10, **or** a rail fails on any complete board |
| INCONCLUSIVE | anything else that meets the minimum sample |

Where the thresholds come from:

* the bootstrap decision form and the "≥ 2 of 3 secondary horizons" rule are the
  ones `idp-hampel-n3-v1` and the per-vote experiment use;
* 1.10 is `maxBoardWorseningFraction` (0.10) of the Hill Autopilot policy;
* −0.005 is the per-vote experiment's non-inferiority margin (G1 +0.005), carried
  to a correlation scale;
* the rails are the Autopilot's board-impact rails, unchanged.

Near-ties keep the incumbent.

**Governance overlay.** Gate 7 requires an eligible independent validation target
before any automatic promotion. None exists for IDP: DLF IDP is measured-dependent
on the IDP Trade Calculator and the IDP Show's order copies it. So even
PROMOTION-ELIGIBLE here reads `AUTO_PROMOTION_BLOCKED: no_independent_validation_target`.
It leads only to an independent fresh-context review and an owner decision.

## 4. Reports (diagnostic; they do not decide)

* **D1 — reprice census.** Repriced votes per board, by source, family and band
  (501–600, 601–700, 701–800, 801–904); votes skipped for lack of ladder coverage.
* **D2 — size.** Median and p10 / p90 of ln(P_ch / P_inc) per band.
* **D3 — published moves.** Rows moved, median / p90 / max relative move,
  top-24 / 50 / 100 IDP membership churn, per board and pooled.
* **D4 — confidence.** Confidence bucket transitions between builds.
* **D5.** The 20 largest moves on the newest complete board: both values and the
  repriced votes.

## 5. Sensitivities (they report; they do not decide)

| id | sensitivity |
|---|---|
| S1 | All 140 archives |
| S3 | DL / LB / DB separately (C1, R1, H1) |
| S4 | C1 with the in-sample ladder (the player's own point kept), as build 2 prices |
| S5 | C1 persistence: T taken on the origin board |
| S6 | C1 on players the IDP Trade Calculator did not list on the origin board (out of sample by player) |
| S7 | Rookies excluded |
| S8 | C1 per voting source |
| S9 | Bands 501–700 and 701–904 separately |

## 6. Decision and what happens next

* **No parameter is tuned after results are seen.** The challenger, the ladder,
  the dataset, the targets, the horizons, the seed, the minimum sample, the
  thresholds and the verdict table are fixed here.
* **NOT BETTER, INCONCLUSIVE or INSUFFICIENT closes this experiment.** The
  incumbent Hill method is retained, the flag stays OFF, and no follow-up variant
  is implied.
* **PROMOTION-ELIGIBLE** leads only to an independent fresh-context review and an
  owner decision. Nothing flips a flag.
* **Byte-identical default.** The implementation ships with the flag OFF, and a
  default board must be byte-identical before and after it
  (`scripts/board_diff.py --expect-no-value-change`).

## 7. Known limitations, stated in advance

* **One market.** The IDP Trade Calculator is the only value-direct IDP market.
  C1's target and the challenger's ladder share it; R1 is the only non-circular
  primary, and its target is itself measured-dependent on that market.
* **Thin overlap.** DLF IDP lists about 175 players, mostly above rank 500, so R1
  sees the deep tail mainly through rows with a mix of shallow and deep votes.
  INCONCLUSIVE or INSUFFICIENT is a plausible and legitimate answer.
* **Different pools at one rank.** A Draft Sharks rank and a translated
  FantasyPros rank are numbers in the same coordinate but come from different
  populations. The challenger, like the incumbent, prices them by rank alone.
* **Today's code, not production history.** Every board is a replay through one
  code revision; freshness approximations are inherited.
* **Dependent boards.** Daily boards are strongly dependent. 7-day blocks absorb
  part of that.

## 8. Implementation status

Not implemented in this commit. The implementation adds the flag, the seam in
`src/api/data_contract.py` and the replay harness in a later commit, and must not
edit this file except to append deviations.
