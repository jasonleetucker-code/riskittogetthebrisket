# Per-vote rank-space Hampel challenger: preregistration (FOLLOW-UP experiment)

**This is a new, separate experiment. It is not a correction, re-run or
reinterpretation of the original rank-space experiment.** The original
(`docs/valuation/evidence/rank-space-hampel-2026-10-17/`, challenger
`rank-space-hampel-v1`, flag `rank_space_hampel_challenger`) stands as committed
with its preregistered verdict **NOT BETTER** (Δ = −0.0127, 95% CI
[−0.0204, −0.0053]). None of its files, its flag or its code path is changed by
this follow-up. Whatever this experiment returns, that negative result remains
the answer to the question it asked.

Owner instructions 2026-10-17 (follow-up): keep the production Hampel filter
unchanged, preserve the original experiment and its negative result, and
preregister a corrected per-vote challenger before implementing or running it.

This document is committed and pushed **before** the challenger below has been
implemented or run. Nothing about it has been computed: no drop set, no
disagreement count, no outcome. If any definition changes after results are
seen, the change is reported as a deviation beside the original; the rule here
is never silently replaced.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 0. What motivated it

The original preregistration §1.1 says each observation maps to u = H⁻¹(v)
where H is "the curve that produced the rank-signal votes", so rank votes "map
back to the percentile they came from". The committed challenger instead uses
**one curve per row**: the IDP master for `assetClass == "idp"`, the OFFENSE
master otherwise. The pipeline prices each rank vote through a **per-(row,
source)** curve, `rank_coordinates.curve_for_pool(rankCoordinatePool)`, and some
votes carry a post-curve TE transform. On the newest board of the original
replay (`dynasty_export_20261017_185402`), as reported in the original README's
"Discrepancy" section:

| votes | count | curve that produced them | curve the original challenger inverted with |
|---|---|---|---|
| IDP-row votes | 945 (all) | `shared_market` (GLOBAL master) | IDP master |
| offense-row votes | 800 of 5,926 | `shared_market` | OFFENSE master |
| TE votes with a post-curve TE multiplier | 550 | Hill curve, then the TE transform | inverted as if no transform applied |

The original README recorded this as a discrepancy, did not fix it, and named a
per-vote inverse as a candidate for a **new** preregistration. This is that
preregistration. It asks a different question from the original: *does
outlier detection in each vote's own production coordinate beat the served
value-space filter?*

## 1. Champion and challenger

* **Champion** — the served per-player Hampel filter
  (`data_contract._hampel_filter_per_player`: K = 2.75, n ≥ 4, MAD > 0 handling,
  ≥ 2 survivors, 1,000-point absolute floor), unchanged. It is not modified,
  re-tuned or re-evaluated.
* **Challenger `rank-space-hampel-per-vote-v1`** (new flag
  `rank_space_hampel_per_vote_challenger`, default **OFF**). The same filter with
  the same K, min_n and guards, computed on each vote's own percentile
  coordinate. For every voting observation i on a non-pick row:

  1. **Forward map recorded at pricing time.** When the pipeline prices vote i,
     it records the exact forward map F_i it applied: F_i = T_i ∘ H_i, where
     * H_i is the Hill curve `percentile_to_value(p, c_i, s_i)` with the
       `(c_i, s_i)` the build itself resolved for that (row, source) through
       `_curve_for_rank` → `curve_for_pool(rankCoordinatePool)` (or the source's
       native pool when no pass stamped one — the same fallback the pipeline
       uses). This is read from the build at the moment the vote is priced,
       never re-derived from a separate lookup of constants.
     * T_i is the post-curve TE transform the build actually applied to that
       vote, or the identity:
       - `basis`: `_te_lift_under_ceiling(convert_te_value(x, "base", "tepp"))`
         (non-TEP sources on TE rows while `te_basis_conversion` is active);
       - `flat(m)`: `_te_lift_under_ceiling(m · x)` with the m the build used —
         the non-TEP fallback/operator multiplier, or the TEP-native flat
         multiplier (default 1.10);
       - identity: every non-TE row, and the KTC-exempt sources on TE rows.
  2. **Inverse, multiplier first, then the curve.** u_i = H_i⁻¹(T_i⁻¹(v_i)):
     * the lift is inverted exactly (identity at or below the 9,900 knee;
       knee − span · ln((9,999 − v)/span) above it);
     * `basis` is inverted with the owner's own inverse,
       `te_premium.convert_te_value(x, from_basis="tepp", to_basis="base")`
       (the base→tepp map is strictly increasing: k < 1 and both clamps are
       linear), `flat(m)` by dividing by m;
     * H_i⁻¹ is `_hill_inverse(x, c_i, s_i)` (p = c · (9,999/x − 1)^(1/s); x at
       or above the ceiling is p = 0).
  3. **Value-direct sources** (`_VALUE_BASED_SOURCES`: `ktcCrowdSfTep`,
     `ktcTradesSfTep`, `idpTradeCalc`; v = raw / site_max × 9,999) have no rank
     curve producing their value. They are mapped with the same inverse, using
     the curve `(c_i, s_i)` the build resolves for **that source on that row**
     (the curve of the population that source's own rank counts within — the
     curve the pipeline would price that same source's rank with, and does when
     the value-direct path falls back), after inverting any TE transform
     (`idpTradeCalc` is TEP-native: `flat(1.10)` on TE rows; KTC is exempt).
     Justification: the original preregistration's intent was that value-direct
     votes "map to the percentile they imply"; keeping them in value space would
     leave no common coordinate for one median/MAD. This keeps that intent and
     replaces only the row-wide curve with the source's own.
     A value-direct vote that took the Hill fallback is a rank vote and is
     inverted as one.
  4. **Statistic.** Median and MAD over the finite u_i (the textbook Hampel
     statistic, as the incumbent and the original challenger).
  5. **Floor carry-over (same rule, per vote).** The incumbent's 1,000-point
     absolute floor is carried into each vote's own coordinate at the row's
     median: with w_i = F_i(u_med),
     floor_i = | F_i⁻¹(max(1, w_i − 500)) − F_i⁻¹(min(F_i(0), w_i + 500)) |,
     where F_i(0) is that vote's largest reachable value (its inverse is u = 0).
     Vote i is an outlier when |u_i − u_med| > max(K · MAD, floor_i). When every
     vote on a row shares one curve and no TE transform, this is exactly the
     original challenger's floor formula evaluated with the correct curve. No
     constant is introduced or tuned.
  6. **Guards, unchanged.** Fewer than `_HAMPEL_MIN_N` pairs, or fewer than
     `_HAMPEL_MIN_N` finite coordinates → no filtering. A filter that would leave
     fewer than 2 survivors → no filtering. Pick rows skip the filter.
  7. **Missing is never zero.** A vote without a finite coordinate (non-positive
     value, or no recorded forward map) is excluded from the median/MAD and is
     never dropped — the same treatment the original challenger gives a
     non-finite u. It is never given u = 0 or v = 0.
  8. **Independence untouched.** The filter decides only which votes are
     dropped. Source/family membership, the B10 family cap, freshness weights,
     the blend, the single-source haircut and confidence are the incumbent's code
     paths, unchanged.
  9. **Precedence.** The joint challenger, then the original rank-space
     challenger, take precedence when their flags are on, so two challengers
     never mix. Every build in this experiment pins both of them OFF.

* **Point-in-time.** The forward map is the one in force **for that archive's
  build**, captured from that build as each vote is priced. In this experiment
  every board is a historical replay (inherited §2: *archived inputs rebuilt
  through one replay code revision*), so the vote itself was produced by the
  replay build's curves and TE transform, and an exact inverse must use exactly
  those. Inverting with the constants production happened to run on that date
  would not invert the vote being filtered. The challenger never consults
  constants other than those its own build used.
* Exactly one new challenger. The joint robust filter and the original
  rank-space challenger are not modified or re-evaluated here.

## 2. Evaluation (inherited, unchanged)

Inputs, pins, units of analysis, outcomes, metrics, horizons, uncertainty,
minimum sample and the decision table are **exactly** those of
`docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md`
§§2–6, as inherited by the original rank-space preregistration §2, with
"challenger" read as `rank-space-hampel-per-vote-v1`:

* **Dataset — frozen.** The same 138 archives as the original replay, identified
  by name and `payloadSha256` in
  `docs/valuation/evidence/rank-space-hampel-2026-10-17/summary_historical_replay.json`
  (2026-07-14 → 2026-10-17). The primary population is the **103** of them that
  are complete under the contract's own source-health rule; the other 35 are used
  only in S1. Boards added to `exports/archive/` after that run are **not**
  included; if any of the 138 is missing, the run is reported as incomplete.
* **Rebuild procedure — the same.** Each board rebuilt from its own archived
  payload, `CSVs/site_raw/` as committed with that archive overlaid with the
  archive's own `site_raw/` copies, and per-source dataset state replayed from
  git history up to that commit; freshness at the payload's `scrapeTimestamp`;
  `value_replay.build` → `build_api_data_contract(csv_root=…)`; one code revision
  for every record; a clean working tree. Two builds per board, differing only
  in `rank_space_hampel_per_vote_challenger` (the joint challenger, its sparse
  half and `rank_space_hampel_challenger` OFF in both). Records go to a new
  gitignored ledger, `data/robust_filter_shadow_rank_space_per_vote/`.
* **Decision rule — inherited §5, unchanged.**
  * P1: Δ = mean_K(m) − mean_X(m) at the primary horizon **h = 7** (leave-family-
    out equal-family consensus target; consensus-lead share m).
  * G1: mean over rows of (|ln V_ch − T| − |ln V_inc − T|) at h = 7;
    non-inferiority margin **+0.005**.
  * Secondary horizons **3, 14, 21** days.
  * Uncertainty: date-block bootstrap over 7-day calendar blocks counted from the
    first origin day (the original replay's primary population spans 8 such
    blocks at h = 7), 4,000 resamples, percentile 95% intervals, **seed 2027**
    (new; neither 1571 nor 17, so the three evaluations are never mistaken for
    one another).
  * Minimum sample: ≥ 30 evaluable observations in each of K and X at h = 7,
    from ≥ 10 distinct origin days, covering ≥ 4 week-blocks; otherwise
    INSUFFICIENT.
  * Verdicts:

    | verdict | rule |
    |---|---|
    | PROMOTION-ELIGIBLE (pending independent review) | Δ lower95 > 0 **and** G1 upper95 ≤ +0.005 **and** Δ > 0 at ≥ 2 of the 3 secondary horizons |
    | NOT BETTER | Δ upper95 < 0, **or** G1 lower95 > 0 |
    | INCONCLUSIVE | anything else that meets the minimum sample |

* **Sensitivities S1–S6** exactly as inherited (they report; they do not decide):
  S1 all 138 archives; S2 episode-deduplicated; S3 offense vs IDP; S4 the KTC
  Crowd/Trades split era; S5 G1 relative to persistence; S6 KTC Crowd and Trades
  merged for the targets.
* **Required segment reports** (they report; they do not decide): the full
  inherited evaluation (Δ and G1 with 95% CIs at h = 3, 7, 14, 21, sample sizes)
  restricted to each of
  * **offense non-TE** — `assetClass == "offense"` and position ≠ TE;
  * **TE** — `assetClass == "offense"` and position = TE;
  * **IDP** — `assetClass == "idp"`.

  Position is the row's `position` on the origin board. An observation whose
  position cannot be established is counted and excluded from the two offense
  segments (never guessed).

## 3. Reports (diagnostic; they do not decide)

* **D1–D5** exactly as the original preregistration §3 (market-observation
  rejection share by consensus-rank band, rows with a market rejection, value
  movement and top-N membership, family wipes, model vs KTC Market — KTC Market
  is a benchmark, never a target), with the original README's interpretations
  (bands by the incumbent's rank for both filters, pick rows excluded).
* **D6 — coordinate census.** Per curve family (OFFENSE master, IDP master,
  `shared_market`/GLOBAL master; TE-transformed; value-direct): votes judged and
  drop rates under each filter, and the share of filter rows whose votes span
  more than one curve.
* **Player-level disagreements.** (a) The 20 board-rows with the largest
  published-value move |V_ch / V_inc − 1| on the complete boards, and the 20
  largest on the newest complete board, each with both values and both drop
  sets. (b) Every value-direct market observation (KTC Crowd, KTC Trades, IDPTC)
  rejected by either filter on rows in the incumbent's top 24, on the newest
  complete board (player, source, vote, which filter rejected it), plus pooled
  counts per (player, source) over the complete boards.
* **Puka Nacua (diagnostic only).** On the newest complete board: every vote with
  its source, value, curve, TE transform, coordinate u, the row median and MAD,
  its per-vote threshold, and keep/drop under each filter; his published value
  and rank under each filter; KTC Market (normalised) beside them for reference.
  **No parameter is tuned toward any player's valuation, Puka's included**, and
  his case cannot change the verdict.
* **Pre-run implementation check.** Before the full run, a sanity check on one or
  two archives may verify the inverse per curve family and the offense non-TE /
  TE / IDP behaviour separately. It is reported as an implementation check, not
  as evidence. It cannot change anything in §§1–3: if it reveals an
  implementation bug, the bug is fixed and noted, and the frozen definitions and
  evaluation stay as written.

## 4. Decision and what happens next

* **No parameter is tuned after results are seen.** K, min_n, the floor rule, the
  guards, the dataset, the target, the horizons, the margin, the seed and the
  verdict table are fixed here.
* **NOT BETTER or INCONCLUSIVE closes this experiment** with a documented negative
  (or undetermined) conclusion. The production filter is retained and the flag
  stays OFF. No follow-up variant is implied.
* **PROMOTION-ELIGIBLE leads only to presenting the evidence for owner review**
  (with an independent fresh-context review). Nothing here flips a flag, changes
  a default or promotes the challenger; activation is a separate owner decision.
* The default path ships byte-identical: the new flag is OFF, and a default board
  built before and after the implementation must be identical.

## 5. Known limitations, stated in advance

* **Mixed coordinates on one row.** A per-vote inverse returns each vote to the
  percentile of the population its own rank counts within. Where a row mixes
  pools (e.g. `shared_market` votes on an offense row), the median and MAD are
  taken over coordinates of different populations. That is what "the coordinate
  the evidence was produced in" means per vote; D6 reports how often it happens
  and how drop rates differ by curve.
* **Value-direct coordinates are implied, not native.** A value-direct vote's u
  is only as meaningful as its source's pool curve at that level.
* **Today's code, not production history.** Every replay runs one replay code
  revision and config; the boards are never what production served that day.
  Freshness approximations are inherited (per-row clocks fall back to the source
  clock; the `upstreamPublishedAt` sidecar is not replayed).
* **The target is a model output** (an equal-family median of value-space votes
  sharing the Hill transform); it measures agreement with later independent
  evidence, not truth.
* **Dependent boards.** Daily boards are strongly dependent and h = 7 windows of
  neighbouring origins overlap; 7-day blocks absorb part of it, S2 removes it.
  The inherited minimum-sample rule counts board-observations.
* **IDP reaches the filter rarely after 2026-10-12** (about 3 voters per row,
  below n ≥ 4), as the original replay found, so the IDP segment is thin late in
  the span.
* **Same population as the original.** This is a second test on the same 103
  boards. Its result is a separate answer to a separate question, not a
  replication, and it does not combine with or overturn the original verdict.
