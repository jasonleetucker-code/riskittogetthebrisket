# IDP source rehabilitation: evaluation of the pending rows (2026-10-18)

Owner master package 2026-10-17 ("Injury-Aware Simulations, Complete IDP Source
Rehabilitation, Valuation Accuracy & Trade Model Validation"). This document covers the
package's two PENDING rows in `docs/OWNER_REQUESTED_TODO.md`:

* DLF IDP incremental evidence;
* source independence, IDP normalization, the outlier challenger, the DLF Values gate
  re-run, and package-model evaluation.

**This is evaluation, not activation.** No vote hold, `_RANKING_SOURCES` weight,
canonical value or Hill constant changes here. Every reversal or activation below is a
recommendation for an explicit owner decision.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Pins and reproduction

| input | identity |
|---|---|
| code | `16bdd11370`, which is `c290dea0a8` (origin/main) plus this PR's read-only script, docs and the status-only `rehabilitation.json` edit; clean tree. No production code differs from main, and the board hashes are identical on both |
| raw payload | `exports/latest/dynasty_data_2026-10-18.json`, sha256 `01e141f7…920380`, scrape 2026-10-18T11:47:11Z (= archive `dynasty_export_20261018_114711.zip`) |
| IDP source CSVs | sha256 of each in `evidence/IDP_REHAB_2026-10-18/idp_rehab_eval.json` → `pins.idpSourceCsvs` |
| flags | `dlf_offense_only_vote` ON (production), `source_freshness_weighting` ON, `source_family_cap` ON; Hampel K 2.75 / min n 4 / floor 1,000 |
| board hashes | hold in force `5ef6b8fe…`, hold off `77fd86d7…` |

Reproduce, with no network required:

* `python scripts/idp_rehab_eval.py --out docs/sources/evidence/IDP_REHAB_2026-10-18/idp_rehab_eval.json`
  * Deterministic: two runs give the identical sha256.
  * It reuses `src/api/value_replay.build` (the canonical pipeline with one flag or
    patch per build) and the 2026-10-01 lineage sweep's board loader, Spearman and
    leave-pair-out residual (`scripts/audit/lineage_integrity_sweep.py`), so
    "ordering" and "residual" mean what they meant there.
* `python scripts/dlf_values_gate.py --out docs/sources/evidence/IDP_REHAB_2026-10-18/dlf_values_gate.json`
* `python scripts/package_model_trade_residuals.py --out docs/sources/evidence/IDP_REHAB_2026-10-18/package_model_trade_residuals.json`

## 1. Status refresh: what was stale in the owner-intake table

| row | was | evidence now | now |
|---|---|---|---|
| P0: availability in forward simulations | IN PROGRESS: #1772, #1774, #1775 | Merged in release train 5 (#1782, merge `69058c9f9e`, 2026-10-18 02:30Z = 2026-10-17 22:30 EDT). The train also carried the `claude/availability-forward-consumers` branch (`bc9f8615a8` roster utility, `9b98bfcc0e` playoff-sim presim, `e40fd1dac8` no missing-to-number coercions) and `claude/gameday-bye-availability` (`4a3ef5116e`). The Deploy Production run for `69058c9f` (started 2026-10-18 02:30Z) concluded **success** | DONE: merged and deployed |
| Rehabilitation registry | IN PROGRESS ("this PR") | `config/sources/rehabilitation.json` merged as #1776 in train 5; refreshed by this PR (below) | DONE (living registry) |
| The IDP Show | IN PROGRESS: #1770; needs a session | #1770 merged in train 5. The production collector has authenticated and committed every 2 h since 2026-10-17 20:32Z (`cd0fd9b73e` through `932c61b4e3`, 11 refreshes by 14:32Z on 10-18): combined 665 rows, IDP-only 350, both `HEALTHY`. The voting board's vendor chart is still `U8I37/v4`, `lastModifiedAt` 2026-08-19, so freshness weighting gives it weight 0 (age 1,434 h on this board). The quarantine is by design and lifts when the vendor republishes | VERIFIED (collection); combined board upstream-inactive |
| FantasyPros IDP | IN PROGRESS: parser repairs | #1777 merged: the page's own expert-update time is now persisted (`data/scrape_state/fantasyProsIdp_upstream.json`, `publishedAt` 2026-09-04, 2 of 6 experts). Dual-family dedup is still deferred: it is not freshness-neutral, and the CSV has 16 duplicate identities. On this board the source votes at freshness 0.59 | PARTIAL: evidence repair done; dedup deferred; the owner decision on `EXPLICIT_UPSTREAM_TIMESTAMP` is still open |
| DLF IDP re-evaluation | PENDING | Delivered 2026-10-17 (`docs/sources/DLF_IDP_REEVALUATION_2026-10-17.md`, merged in train 5); refreshed and corrected in §2 | DONE (evidence); OWNER DECISION NEEDED |
| Independence / normalization / outlier / DLF Values / package model | PENDING | §3–§6 | see each section |

Two more stale records found and corrected in this PR:

* **`config/sources/rehabilitation.json`, `idpShowCombined`.** It was still
  `auth_blocked` ("prod fetch timer has committed nothing since 2026-10-07"). It is
  now `upstream_inactive`, with the recovered collector as evidence.
* **`config/sources/rehabilitation.json`, `idpShow`.** Its trigger ("first
  authenticated verification run") has fired, and the measured result is in §3.

Neither entry changes a vote.

Not IDP, but stale: `fantasyNavigatorSf` is now `SEVERELY_STALE` (freshness 0.02, 192 h
against a 26 h cadence). Its rehabilitation entry predicted quarantine "around
2026-10-18". `scripts/check_source_health.py` reports it, and no action is needed on our
side.

One documentation drift was noted and **not** edited here (`CLAUDE.md` is owned by the
harness-auditor process):

* `CLAUDE.md` ("Live Value Pipeline" step 2) and the `percentile_to_value` docstring
  still say ranks past 500 "clamp to the curve tail".
* The served tail policy (`src/canonical/tail_policy.py`, B4) saturates at rank 904.
* Measured: Draft Sharks IDP votes at effective ranks 502–687 take 158 distinct
  values, not one tail value.

## 2. DLF IDP: incremental evidence if it voted again

The same payload was built with the owner's hold in force (production) and with it off
(`dlf_offense_only_vote` = False, the documented rollback flag).

| measure | value |
|---|---|
| DLF IDP + DLF Rookie IDP observations on IDP rows | 200 (175-row CSV, 29-row rookie CSV) |
| ranked IDP rows DLF covers | 182 of 290 |
| IDP rows whose value moves | 180 of 396 priced |
| relative value move, median / p90 / max | 0.0% / 3.1% / 48.3% |
| p90 by family | DL 3.1%, LB 7.1%, DB 1.0% |
| consensus-rank move, median / p90 | 3 / 21 |
| IDP rows gaining an independent family | 151 (32 of them had ≤ 2 families) |
| ranked IDP family counts, hold vs hold off | 1/2/3: 13/61/216 → 1/2/3/4: 11/34/126/119 |
| confidence bucket changes | 58 (38 low→medium, 20 medium→low) |
| top-24 / 50 / 100 IDP membership swaps (by value) | 4 / 3 / 4 |
| overall top-200 membership changes | 8 |
| offense rows moved / pick rows moved | 1 (the two-way player) / 41 (rookie-pool tether, allowed coupling) |
| DLF votes within 15% of the published value (confidence-gate band) | 127 of 199 |
| DLF signed log ratio vs the other voters, median | DL +0.074, LB −0.012, DB −0.046 |
| freshness | DLF IDP's last broad change 2026-10-18 12:27Z; not stale |

### The correction: the reversal is two changes, not one

The 2026-10-17 note reported "1 outlier drop in 197". That counted only DLF's own
rejected votes. The board shows a second mechanism:

| | hold in force (production) | hold off |
|---|---|---|
| IDP rows reaching the outlier filter (≥ 4 weighted voters) | **0** of 427 | 158 |
| IDP observations dropped by the filter | 0 | 32: Draft Sharks 18, FantasyPros 10, IDP Trade Calculator 3, DLF 1 |

Today **no IDP row is examined for outliers at all**. IDP Show combined is quarantined
and DLF is held, which leaves every IDP row with at most 3 voters. Restoring DLF makes
n = 4 on 158 rows and re-activates the incumbent filter there. The reversal's movement
decomposes into two parts:

| component | rows moved | p90 | max |
|---|---|---|---|
| DLF's own vote (hold off with the filter off, vs production; production drops no IDP observation, so its filter-off board is identical on IDP rows; checked) | 180 | 2.1% | **5.2%** |
| outlier filter re-activated on IDP rows | 31 | 0.0% | **48.2%** |
| total | 180 | 3.1% | 48.3% |

Every large move named in yesterday's note comes from the filter dropping an outlying
vote, mostly Draft Sharks. Examples:

* Aidan Hutchinson: {6444, 6227, DS 3181} → DS dropped, 5122 → 6422.
* Myles Garrett: DS 1902 dropped, 3938 → 5268.
* CJ Allen: DS 5741 dropped, 3564 → 2161.
* Trevin Wallace: DS 2878 dropped, 1710 → 885.

Also worth knowing: on 18 rookie IDP rows, DLF lists the player on both of its boards.
They share one family weight (cap 0.5 each), but both enter the outlier statistic as two
observations. That is the existing design (the family cap applies after the filter), and
offense already has it on 40 rows (`dlfSf` + `dlfRookieSf`). It is not a defect claim.

### Recommendation (owner decision; the hold is unchanged)

* **DLF's own IDP vote is low-risk and adds evidence.** At most 5.2% movement, +151
  rows gaining a fresh family, and no copying signature (§3). That supports
  **reversing** the hold for `dlfIdp` and `dlfRookieIdp`, as the 2026-10-17 note did.
* **Approving it also turns the outlier filter back on for 158 IDP rows**, where it
  drops 32 votes (mostly Draft Sharks) and moves 31 rows by up to 48%. That is the
  incumbent, approved filter doing what it does on offense. But it is a second
  decision, and it should be taken knowingly.
* Options:
  * (a) reverse now and accept both;
  * (b) keep the hold until the preregistered IDP outlier challenger (§4) reports on
    whether filtering thin IDP rows helps.
* Mechanism, if approved: `RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0` plus a restart, or a
  PR removing the two keys from `POLICY_SOURCE_VOTE_HOLDS`.

## 3. Source independence and IDP normalization

### Inventory

| source | B10 family | voting state on this board | rows (CSV / on-board IDP) |
|---|---|---|---|
| IDP Trade Calculator `idpTradeCalc` | `idpTradeCalc` | votes (freshness 0.86), value-direct | 900 / 375 |
| Draft Sharks IDP `draftSharksIdp` | `draftSharks` | votes (0.69), rank → Hill, combined offense+IDP list | 409 / 319 |
| FantasyPros IDP `fantasyProsIdp` | `fantasyPros` | votes (0.59, STALE upstream), rank → Hill via ladder | 299 / 255 |
| DLF IDP `dlfIdp` / `dlfRookieIdp` | `dlf` | policy-held | 175 / 174; 29 / 29 |
| The IDP Show combined `idpShowCombined` | `idpShow` | quarantined (freshness 0) | 665 / 301 |
| The IDP Show IDP-only `idpShow` | unregistered | non-voting | 350 / 346 |
| Signals DL / LB / DB `signalsIdp*` | `fantasyCalc` (own family on IDP rows) | shadow | **not provisioned here.** The boards are private and box-local (`data/sources/signals/board/`), so pairwise measurement is BLOCKED in this environment |

All share one rank coordinate, `shared_market` (the IDP Trade Calculator's
cross-market backbone): 377 / 319 / 249 / 171 / 301 votes respectively.

### Pairwise dependence on the board's IDP rows

Each source's own published ordering is restricted to the board's IDP identities. The
leave-pair-out residual is computed against a consensus of the **voting-capable pool**:

* IDP Trade Calculator, Draft Sharks, FantasyPros, DLF IDP, IDP Show combined;
* the IDP-only IDP Show cut is excluded, because it is a clone of one member (below);
* n residual is 152 for every pair.

| pair | Spearman | n | leave-pair-out residual |
|---|---|---|---|
| IDP Trade Calculator vs IDP Show combined | **0.898** | 301 | **0.770** |
| IDP Trade Calculator vs DLF IDP | 0.869 | 174 | 0.446 |
| DLF IDP vs IDP Show combined | 0.819 | 172 | 0.326 |
| FantasyPros vs IDP Show combined | 0.709 | 231 | 0.409 |
| IDP Trade Calculator vs Draft Sharks | 0.646 | 303 | 0.362 |
| Draft Sharks vs IDP Show combined | 0.656 | 258 | 0.335 |
| FantasyPros vs DLF IDP | 0.659 | 160 | 0.211 |
| Draft Sharks vs DLF IDP | 0.604 | 166 | 0.125 |
| Draft Sharks vs FantasyPros | 0.534 | 236 | 0.112 |
| IDP Trade Calculator vs FantasyPros | 0.610 | 247 | 0.015 |

The full matrix, with all seven boards and per-family DL / LB / DB versions, is in the
evidence JSON (`independence.csvOrderingDependence*`).

**Finding I-1 — the IDP Trade Calculator's IDP order IS The IDP Show's IDP-only order.**
Against the IDP-only cut: Spearman **0.9999** (n = 346), residual 0.993. The lead-lag is
now measured at a fourth publication:

| IDP Trade Calculator version | vs IDP Show capture of 2026-08-26 | vs IDP Show capture of 2026-10-17 (vendor republished 2026-10-08) |
|---|---|---|
| 2026-09-15 … 2026-10-08 20:15Z | 0.5–1.4% discordant | 7.5–8.1% |
| 2026-10-09 00:47Z | 7.0% | 2.15% |
| 2026-10-09 06:53Z | 8.1% | 0.28% |
| **2026-10-10 02:01Z → 2026-10-16 (every version)** | 8.1% | **0.00% (n = 346)** |

* The IDP Trade Calculator moved to exact order identity with the vendor's 10-08
  publication within about 30 hours.
* We captured that publication only on 10-17, because collection was down from
  10-07 to 10-17. The vendor's Substack post date is in
  `IDP_SHOW_RECOVERY_2026-10-17.md`.
* That is 4 of 6 publications with the follow signature.
* This is order identity, not value identity: The IDP Show publishes ranks only. The
  derivation is still not vendor-stated, so `source_lineage.json` keeps it
  `suspected`, but the measurement is now as strong as an order measurement can be.

Consequences:

* **No double count today.** The IDP-only cut does not vote, and the combined board
  carries zero weight.
* **Latent double count.** When the vendor republishes the combined chart, The IDP
  Show's opinion reaches IDP rows through two families: `idpShow`, via the combined
  board, with residual 0.77 to the IDP Trade Calculator; and `idpTradeCalc`. The
  confidence gate would count them as two independent families.
* **The rehabilitation plan's candidate path is a pure double count.** It proposed
  making the IDP-only cut the provider's voting board, which would add an
  order-identical copy of a voter that already counts. Recommendation: **do not**
  switch while `idpTradeCalc` votes as a separate family. `rehabilitation.json` is
  updated accordingly.
* The IDP Hill master trains on the IDP Trade Calculator's IDP board, which is
  effectively The IDP Show's ordering. This was already recorded in `source_lineage.json`.

**Proposed patch (NOT applied; owner review, as `source_lineage.json` already asks):**

* An IDP-scoped shared cap: on `assetClass == "idp"` rows, treat `idpTradeCalc` and
  `idpShowCombined` as one correlation lineage for `cap_family_weights` and for the
  confidence independence count. It would not affect the IDP Trade Calculator's
  offense and pick rows.
* Implementation sketch: a row-scoped override in `correlation_group_for(source, row)`,
  returning `"idpShow"` for `idpTradeCalc` when the row is IDP, behind a default-OFF
  flag. Prove it with the replay harness before review.
* Today it would change **nothing** (`idpShowCombined` weight 0). It only matters once
  the vendor republishes, so it can be decided before that, at no board risk.

**Finding I-2 — DLF IDP is correlated, not derived.**

* DLF's highest residual is with the IDP Trade Calculator (0.446), then IDP Show
  combined (0.326).
* It is nowhere near the 0.99 of a copy, and the 2026-10-17 lead-lag over 37 / 51
  versions found no snap-to-identity.
* DLF and its rookie board keep one family (`dlf`). No double count.

**Finding I-3 — no other IDP pair is a correlated descendant counted twice.**

* Draft Sharks IDP is one DOM slice of the same Draft Sharks page as `draftSharks`
  offense (one family, proven).
* FantasyPros IDP shares the `fantasyPros` family with its offense boards.
* Signals IDP sits in `fantasyCalc`, which has no IDP rows, so it is its own family
  there. It is not measurable here (box-local).

### IDP normalization

**Finding N-1 — value-direct vs rank → Hill disagree by depth, independent of opinion.**
For every IDP row the IDP Trade Calculator prices, its native value was compared with the
Hill value the pipeline would give a rank vote at the **same effective rank** in the
same coordinate pool (`shared_market` → GLOBAL master):

| effective rank band | n | median ln(native / Hill) | ratio |
|---|---|---|---|
| 1–100 | 10 | +0.119 | ×1.13 |
| 101–250 | 50 | +0.118 | ×1.12 |
| 251–500 | 85 | +0.048 | ×1.05 |
| **501–904** | **232** | **−0.336** | **×0.71** |

* A rank source that agrees **exactly** with the IDP Trade Calculator's order prices
  the deep IDP tail about 40% above it, and the top of the board about 11% below it.
* Ranks 501–904 lie beyond the Hill fit domain (p ≤ 1) and are priced by the B4
  tail-policy extension.
* 232 of the IDP Trade Calculator's 377 IDP votes sit in that band. So do 158 of
  Draft Sharks', 103 of FantasyPros' and 26 of DLF's.
* This is a coordinate effect, and it appears as a family-level skew. Median signed
  log ratio of each voter against the leave-one-out mean of the other voters:

  | source | DL | LB | DB |
  |---|---|---|---|
  | IDP Trade Calculator | +0.050 | −0.118 | **−0.223** |
  | Draft Sharks | +0.008 | +0.112 | +0.146 |
  | FantasyPros | −0.050 | +0.115 | +0.070 |
  | DLF IDP (hold off) | +0.080 | −0.033 | −0.059 |

  The skew is largest at DB and LB, the families whose rows sit deepest.
* **Not a code defect.** The tail extension, the shared coordinate and the
  value-direct path all behave as specified. It is a methodology question: whether
  deep IDP rank votes should be priced by Hill extrapolation or translated to the
  value-direct market's own value at that rank.
* That decision belongs to the owner and the Hill Autopilot governance. No constant
  or tail policy is changed here.
* **Proposed next step:** a preregistered challenger, using the same harness as §4,
  that prices `shared_market` rank votes past rank 500 at the IDP Trade Calculator's
  native value for that effective rank, compared on the same holdout target.
* **Context only, with no threshold change:** the existing IDP voters disagree with
  one another by family at ±5–22% (log scale). That bears on the Signals IDP gate's
  ±5% signed-bias criterion (6b), which compares against a single bridge. The gate is
  **not** weakened here.

## 4. Outlier challenger: preregistered, not run

`docs/valuation/evidence/idp-outlier-n3-2026-10-18/PREREGISTRATION.md` (+ `ARCHIVE_MANIFEST.json`):

* **Challenger.** `idp-hampel-n3-v1` runs the incumbent filter unchanged, with min n = 3
  on IDP rows only.
* **Target.** The primary target is DLF IDP's priced vote on the later board. DLF is the
  one IDP opinion that votes in neither build, so the challenger cannot be graded by its
  own survivors.
* **Dataset.** 105 complete archives, frozen by sha256.
* **Statistics.** Seed 2029; h = 7 primary, with 3, 14 and 21 secondary.

It is not implemented. The pattern needs a seam in the shared `data_contract.py`, a
ledger parameterisation and about 315 rebuilds, which makes it neither cheap nor
isolated in this lane. Production is unchanged.

## 5. DLF Values gate re-run

`scripts/dlf_values_gate.py` was re-run against the newest complete archive
(`dynasty_export_20261018_114711.zip`, HEAD `16bdd11370`). Output:
`evidence/IDP_REHAB_2026-10-18/dlf_values_gate.json`.

| criterion | 2026-09-25 | 2026-10-18 |
|---|---|---|
| capture | 322 rows | 319 rows (QB 54, RB 91, TE 46, WR 128), 0 inversions, 0 ties |
| ordering vs DLF Rank (matched) | Spearman 0.970, 7.1% discordant | 0.968 (287), 7.3% |
| new vs duplicate: rank → Hill vs DLF Rank's Hill, median / p90 | 8.3% / 18.1% | 8.4% / 18.5%; **not a duplicate** |
| raw/max spacing vs DLF Rank's Hill, median | −79.6% | −80.4% |
| DLF's own Hill fit / RMSE vs live master | c 0.062 s 1.69 / 1,742 | c 0.061 s 1.67 / 1,744 (other native boards 390–2,031) |
| Hampel drop rate: raw/max \| rank → Hill | 0.91 \| 0.00 | **0.897 \| 0.009** |
| board impact, rank → Hill (1,028 rows) | 340 changed, p90 1.31%, max 3.87% | 336 changed, p90 1.33%, max 5.75%, top-50 max 2.15% |
| family cap with DLF Rank | 0.5 each | 0.5 each |
| **capture stability** | untested (one version) | **measured**: 24 distinct daily releases (2026-09-25 → 10-18, 29 commits), consecutive-release Spearman 0.986–1.000, 42–97% of values change per release, top-24 overlap 22–24 |

**Gate result.**

* raw/max is still pathological: 90% of its votes cannot enter the blend.
* rank → Hill is still the only viable candidate.
* The one blocker the first gate named, capture stability, is now cleared. DLF Values
  is a stable, daily-recomputed board.
* The remaining step is an **owner decision**: rank → Hill as a second `dlf` family
  member (sharing DLF's one provider weight with DLF Rank under the family cap), or stay
  non-voting.
* It is offense-only, so it is compatible with the 2026-10-16 DLF offense-only policy.
* Nothing is activated.

## 6. Package-model evaluation on trade evidence

`scripts/package_model_trade_residuals.py` was run on the only trade evidence committed
here. That is `data/sleeper_last_good.json`: dynasty_main's own completed trades, priced
point-in-time from `exports/archive` (≤ 7-day lag, all-or-nothing coverage).

| census | count |
|---|---|
| trades in the file | 107 |
| not two-team | 3 |
| before the first archive (2026-07-14) | 65 |
| eligible | 39 |
| graded under KTC SF TE++ (excluded: an asset unpriced) | **16** (23) |
| graded under IDP Trade Calculator (excluded) | **23** (16) |

Relative residual |adjusted A − adjusted B| / mean; smaller means closer to the accepted
clearing:

| prices | model | n | median | p90 | > 20% |
|---|---|---|---|---|---|
| KTC SF TE++ | raw | 16 | 6.6% | 42.0% | 6 |
| | `geom_q078_v1` (active) | 16 | 4.7% | 25.3% | 3 |
| | `ktc_2026_04` (rollback) | 16 | 3.9% | 25.3% | 2 |
| IDP Trade Calculator | raw | 23 | 9.2% | 36.7% | 6 |
| | `geom_q078_v1` (active) | 23 | 6.9% | 17.5% | 2 |
| | `ktc_2026_04` (rollback) | 23 | 10.9% | 26.1% | 5 |

**Reading.**

* With 16 and 23 trades from one league, this is a diagnostic, not an accuracy score.
* Both package models agree with accepted trades better than raw sums.
* Under KTC prices the KTC-calibrated model fits slightly better, which is circular:
  those prices are its own calibration population. Under the IDP Trade Calculator, the
  active geometric model fits better.
* Nothing here bears on promotion: the active model is already owner-approved (#1771).

**BLOCKED.** The production trade archive (`data/intel`: Sharp / KTC market trades read by
`src/trade/market_trade_eval.py`) is **box-local and not available in this environment**.
The package-model evaluation "on the production trade archive" therefore remains to be
run on the box. The owner-league run above is a stand-in, not that evaluation.

## Completion result

* **STATUS:** PARTIAL. Every item is measured, but the box-local parts are BLOCKED.
* **ACCEPTANCE:** status refresh; DLF IDP evidence plus a recommendation; independence
  and normalization review with proposed patches only; outlier challenger
  preregistration; DLF Values gate re-run; package-model run on committed evidence. No
  production change.
* **EVIDENCE:** the three scripts above, pinned and deterministic; JSON under
  `docs/sources/evidence/IDP_REHAB_2026-10-18/`.
* **UNRESOLVED:**
  * Signals IDP pairwise dependence: box-local data.
  * Package-model evaluation on the production trade archive: box-local `data/intel`.
  * Outlier challenger implementation and run: a separately authorized unit.
  * N-1 deep-tail pricing: owner methodology decision; challenger proposed.
* **BLOCKERS:**
  * Owner decisions:
    * the DLF IDP reversal, (a) or (b) in §2;
    * the IDP-scoped IDP Show / IDP Trade Calculator lineage cap (§3);
    * DLF Values rank → Hill or non-voting (§5);
    * FantasyPros `EXPLICIT_UPSTREAM_TIMESTAMP`.
  * Box access: Signals and `data/intel`.
* **NEXT_ACTION:** owner decisions above; an on-box run of the package-model evaluation
  against `data/intel`; then the implementation unit for `idp-hampel-n3-v1`.

## Owner closeout D2–D5 (2026-10-18)

The owner's closeout directive of 2026-10-18 (PART 2, Decisions 2-5) decided the
blockers this evaluation left open. The record, with every measurement, is
`docs/sources/IDP_SOURCE_INDEPENDENCE_CLOSEOUT_2026-10-18.md`; the reproducible
instrument is `scripts/source_independence_closeout.py`. In brief:

* **§3, the IDP-scoped shared cap (D2): implemented.**
  * On a defensive row where both the IDP Trade Calculator and The IDP Show combined
    board vote, they are one lineage, for `cap_family_weights` and for the B11 family
    count. `data_contract.ROW_SCOPED_CORRELATION_GROUPS`; flag
    `idp_shared_correlation_cap`, default ON.
  * Offense and pick rows are untouched, and the IDP-only cut stays unregistered.
  * On the pinned board it engages on 0 rows: The IDP Show is still quarantined, and
    the board is byte-identical.
  * Replayed on five earlier archives, it engages on exactly the ~300 IDP rows where
    both vote, with 0 mismatches in the independent family-count check.
* **The IDP Trade Calculator's offense vote (D3): verified and excluded.**
  * It voted value-direct on 434 offense rows as its own family, outside the KTC Crowd
    cap.
  * Its independence is not evidenced. Its current batch (since 2026-10-10) is also
    not a KTC value-identity batch, so derivation is not proven either.
  * The vote is excluded on offense rows only:
    `POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS`, flag `idptc_offense_vote_excluded`, default
    ON.
  * Effect: 428 offense values move (p90 3.0%, max 13.4%, top-50 max 2.2%), plus 62
    tethered picks.
* **§5, DLF Values (D4): released.**
  * Rank → Hill, as an offense-only member of the `dlf` family under DLF's one
    provider cap. Flag `dlf_values_rank_hill_vote`, default ON, because every
    activation gate passed.
  * Effect: 300 offense values move (p90 1.7%, top-50 max 1.8%) plus 40 tethered
    picks. DLF Values' Hampel drop rate is 0.3%.
* **FantasyPros (D5): on the vendor's clock.**
  * `fantasyProsIdp` uses `EXPLICIT_UPSTREAM_TIMESTAMP`. Freshness goes from 0.58 to
    0.18 (SEVERELY_STALE). No value moves, because it is the lone subgroup member of
    the IDP blend.
  * The dual-family duplicate analysis is completed: each duplicated identity casts one
    vote, so there is no amplification.
* **Unchanged:** the DLF IDP hold (Decision 1, Option B), the Signals IDP hold
  (Decision 7), the deep-tail challenger (Decision 6, not started here) and the active
  package model (Decision 8, `geom_q078_v1`).
