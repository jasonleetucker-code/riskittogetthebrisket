# IDP three-voter outlier challenger: preregistration

**Registration only. Nothing about this challenger has been implemented or run.**
No drop set, disputed-row count, target value or outcome has been computed for it.
If any definition below changes after results are seen, the change is reported as
a deviation beside the original. The rule here is never silently replaced.

Owner master package 2026-10-17 ("Source independence, IDP normalization, outlier
challenger (preregistered) …"). It follows the repo's preregistration pattern:
`docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md`, as
inherited by `rank-space-hampel-2026-10-17/` and
`rank-space-hampel-per-vote-2026-10-17/`. It is a new, separate question. It
neither reopens nor combines with those experiments: their verdicts were NOT BETTER
and INCONCLUSIVE.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. What motivated it (incumbent state only)

Measured on the production configuration at `c290dea0a8` with the 2026-10-18 11:47Z
payload (`docs/sources/IDP_REHABILITATION_EVALUATION_2026-10-18.md`, §3). These
are facts about the **incumbent**, not about the challenger:

* The per-player Hampel filter (`data_contract._hampel_filter_per_player`) needs
  `_HAMPEL_MIN_N = 4` weighted voting observations on a row.
* **0 of 427 IDP rows reach it today.** Weighted voters per IDP row:
  0 → 31 rows, 1 → 72, 2 → 99, 3 → 225.
* Two things took IDP below n = 4:
  * the IDP Show combined board is freshness-quarantined (vendor chart last
    modified 2026-08-19);
  * DLF IDP is held from voting by owner policy (2026-10-16).
* So no IDP observation is examined for outliers at all. The rank-space replays
  already recorded that "IDP reaches the filter rarely after 2026-10-12".
* With the DLF hold off, 158 IDP rows reach the filter and it drops 32
  observations from other sources (Draft Sharks 18, FantasyPros 10, IDP Trade
  Calculator 3, DLF 1). Every IDP move above 5.2% in that counterfactual comes from
  those drops, not from DLF's own vote. So whether IDP rows get outlier handling
  currently depends on a source-policy decision, not on a methodology decision.

The question: **for an IDP row with exactly three voting observations, does
applying the incumbent outlier rule produce a published value closer to later
independent evidence than leaving the row unfiltered?**

## 1. Champion and challenger

* **Champion.** The served filter, unchanged: K = 2.75; MAD > 0 handling;
  1,000-point absolute floor; at least 2 survivors; n ≥ 4; picks skipped.
* **Challenger `idp-hampel-n3-v1`.** A new flag, `idp_hampel_n3_challenger`,
  default **OFF**, added in the implementation unit and not by this document.
  * It runs the **identical** function, with identical K, floor, MAD handling and
    survivor guard, in the same value space.
  * Its only change: `min_n = 3` on rows whose `assetClass == "idp"`.
  * Offense rows (n ≥ 4) and pick rows (skipped) take the incumbent path
    byte-for-byte.
  * No constant is introduced or tuned.
* **What it means at n = 3.** Write the deviations from the row median as
  {0, d₁, d₂}. The MAD is min(d₁, d₂). An outer vote is dropped only when both
  hold:
  * its deviation exceeds 2.75 × the other outer vote's deviation;
  * its deviation exceeds the 1,000-point floor.

  So the rule fires only on a strongly asymmetric triple, and rarely on deep
  rows, where values sit near or below 1,000 apart. Stated in advance, not
  discovered.
* **Unchanged by construction.** Everything outside the drop decision is the
  incumbent's code path:
  * family membership and the B10 family cap;
  * freshness weights and the blend;
  * the single-source haircut;
  * confidence, the lost-evidence seats included.
* **Missing is never zero.** A vote without a finite value is excluded from the
  statistic and never dropped. This is the incumbent's treatment.
* **Precedence.** All other filter challengers are pinned **OFF** in every build:
  the joint challenger and its sparse half, `rank_space_hampel_challenger` and
  `rank_space_hampel_per_vote_challenger`.

## 2. Inputs and pins

* **Dataset (frozen).** `ARCHIVE_MANIFEST.json`, in this directory, lists every
  archive in `exports/archive/` at `c290dea0a8` with its zip and payload sha256:
  * 140 boards in total;
  * **105 complete** under the contract's own source-health rule, spanning
    2026-08-18 23:02Z → 2026-10-18 11:47Z;
  * the other 35 are degraded only in `KTC_TradeDB` / `KTC_WaiverDB` and are used
    only in S1.

  Boards added later are excluded. A missing or hash-mismatched board makes the
  run incomplete, and it is reported as such.
* **Rebuild procedure.** Inherited unchanged from the joint-filter
  preregistration §2:
  * each board's own payload;
  * `CSVs/site_raw/` as committed with that archive, overlaid with the archive's
    `site_raw/` copies;
  * per-source dataset state replayed from git history;
  * freshness at the payload's `scrapeTimestamp`;
  * `value_replay.build` → `build_api_data_contract(csv_root=…)`;
  * one code revision and a clean tree for every record.
* **Flags pinned on every build:**
  * `dlf_offense_only_vote` **ON** (the production state at registration). DLF
    IDP therefore votes in neither the incumbent nor the challenger build, which
    is what makes target T1 possible;
  * `source_freshness_weighting` ON;
  * `source_family_cap` ON;
  * the other filter challengers OFF, as listed in §1.
* **Three builds per board:**
  1. incumbent;
  2. challenger;
  3. a **holdout read**: the incumbent with `dlf_offense_only_vote` OFF. It is
     used only to read DLF IDP's own priced vote, `valueContribution`, which is
     computed before the filter. Nothing from build 3 is published or compared
     as a board.
* **Ledger.** Records go to a new gitignored ledger,
  `data/robust_filter_shadow_idp_n3/`. Each record carries:
  * the code SHA and the clean-tree flag;
  * the payload sha256 and the CSV / state tree hashes;
  * the flag snapshot and the Hampel constants.

## 3. Units, target, metric, decision

* **Origins.** The last complete board of each UTC day.
* **Target board.** The last complete board on day d + h, or the next later day
  up to `max(1, h // 7)` days late, never earlier. These rules are inherited.
* **Disputed row.** A non-pick IDP row on an origin board whose published
  `rankDerivedValue` differs between the incumbent (V_inc) and the challenger
  (V_ch).
* **Target T1 (primary, holdout).** T1 = ln of DLF's priced IDP vote for that
  player on the **target** board, read from build 3:
  * use `dlfIdp`, or `dlfRookieIdp` when only that board lists the player;
  * when neither lists the player, the row is not evaluable for T1. It is
    counted and never imputed.
  * Rationale: with three voters, any consensus built from the voting families is
    the challenger's own two survivors, so the challenger would be graded by its
    own rule. DLF IDP is the one dynasty IDP opinion that votes in neither build.
* **P1 (primary).** At h = 7, the mean over evaluable disputed rows of
  |ln V_ch − T1| − |ln V_inc − T1|. Negative means the challenger's published
  value sits closer to the held-out opinion a week later.
* **Secondary horizons.** 3, 14 and 21 days.
* **Uncertainty.** Date-block bootstrap over 7-day calendar blocks from the first
  origin day: 4,000 resamples, percentile 95% intervals, **seed 2029**. The seed is
  new, so this evaluation is never confused with seeds 1571, 17 or 2027.
* **Minimum sample.** At h = 7: at least 30 evaluable disputed row-origins, from
  at least 10 distinct origin days, covering at least 4 week-blocks. Otherwise the
  verdict is **INSUFFICIENT**.
* **Structural guard (an implementation check, not a verdict).** On every board,
  every non-IDP row and every IDP row with n ≠ 3 must be byte-identical between
  builds 1 and 2. A violation is a bug: fix it, note it and re-run. The frozen
  definitions do not change.
* **Verdicts:**

  | verdict | rule |
  |---|---|
  | PROMOTION-ELIGIBLE (pending independent review, then owner decision) | P1 upper95 < 0 **and** P1 < 0 at ≥ 2 of the 3 secondary horizons |
  | NOT BETTER | P1 lower95 > 0 |
  | INCONCLUSIVE | anything else that meets the minimum sample |

  Near-ties keep the incumbent.

## 4. Reports (diagnostic; they do not decide)

* **D1 — drop census.** Challenger-only drops by source, by family (DL / LB / DB)
  and by consensus-rank band.
* **D2 — lead share of the new rejects.** The inherited consensus-lead share *m*
  and own-source retreat share *r* for each challenger-only drop.
  * The leave-family-out consensus is computed with `idpTradeCalc` and `idpShow`
    as **one** lineage group, because their IDP orders are identical (§3 of the
    evaluation document).
  * Delisted observations are counted separately, never as zero.
* **D3 — persistence.** P1 with T1 taken on the origin board (S5). It shows how
  much of P1 is level agreement with DLF rather than later movement.
* **D4.** The 20 largest disputed moves on the newest complete board: both values,
  the dropped vote and T1.

## 5. Sensitivities (they report; they do not decide)

| id | sensitivity |
|---|---|
| S1 | All 140 archives |
| S2 | Episode-deduplicated: first origin of each run of the same (player, dropped source) |
| S3 | DL / LB / DB separately |
| S5 | Persistence (D3) |
| S6 | Target T2: equal-family median over the families other than the dropped vote's, `idpTradeCalc` + `idpShow` merged; it needs ≥ 2 such families. **Expected to be circular at n = 3** and reported as such |
| S7 | Rookies excluded |
| S8 | Origins before vs after the first board on which `idpShowCombined` carries zero freshness weight |

## 6. Decision and what happens next

* **No parameter is tuned after results are seen.** The rule, the dataset, the
  target, the horizons, the seed, the minimum sample and the verdict table are
  fixed here.
* **NOT BETTER, INCONCLUSIVE or INSUFFICIENT closes this experiment.** The
  production filter is retained, the flag stays OFF, and no follow-up variant is
  implied.
* **PROMOTION-ELIGIBLE** leads only to presenting the evidence for an independent
  fresh-context review and an owner decision. Nothing flips a flag.
* **Byte-identical default.** The implementation ships with the flag OFF, and a
  default board must be byte-identical before and after it
  (`scripts/board_diff.py --expect-no-value-change`).

## 7. Known limitations, stated in advance

* **T1 is one provider.** DLF IDP's order correlates with the IDP Trade
  Calculator at 0.87 raw, and its leave-pair-out residual is 0.29–0.45. Its priced
  vote is placed through the shared-market translation onto the IDP Trade
  Calculator's rank backbone. A challenger that drops an IDP Trade Calculator vote
  is therefore graded against a target that partly shares its coordinate.
* **Policy coupling.** T1 exists only because of the owner's DLF hold.
  * If the owner reverses the hold, live accumulation loses the holdout, and
    158 IDP rows reach the incumbent filter anyway, which shrinks this
    challenger's scope.
  * The frozen historical dataset pins the hold ON, so the registered question
    stays answerable.
* **Thin, asymmetric scope.** At n = 3 the rule fires only on asymmetric triples
  above the 1,000-point floor. INSUFFICIENT is a plausible outcome and is a
  legitimate answer.
* **Today's code, not production history.** Every board is a replay through one
  code revision. Freshness approximations are inherited.
* **Dependent boards.** Daily boards are strongly dependent. 7-day blocks absorb
  part of that, and S2 removes it.

## 8. Implementation status

Not implemented in this unit. The pattern requires three pieces:

* a flag-gated seam in `src/api/data_contract.py`;
* a new challenger parameterisation of `src/robust_filter_shadow/`;
* about 315 rebuilds.

That is neither cheap nor isolated: `data_contract.py` is shared with other active
lanes. This preregistration is committed first, as the pattern requires. The
implementation is a separately authorized unit, and it must not edit this file
except to append deviations.
