# Source independence: owner closeout Decisions 2-5 (2026-10-18)

> **Status 2026-10-19 — D2 and D3 are WITHDRAWN.** The owner's source-voting
> directive of 2026-10-19 sets the policy:
>
> * agreement between different providers is consensus, not duplication;
> * only credible shared-data lineage may merge votes;
> * similarity never removes, caps or haircuts a vote.
>
> The D2 shared cap and the D3 offense-vote exclusion rested on similarity, so both
> mechanisms were deleted before release. D4 and D5 continue under their own flags,
> and the two-way boost gets an alt-evidence fix.
>
> The record of the rework, its evidence on the current production board, the
> haircut investigation and the cross-provider audit is
> `docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`. The D2/D3 sections below are
> kept as history. The `scripts/source_independence_closeout.py` instrument they cite
> was removed together with the mechanisms. Its outputs under
> `evidence/SOURCE_INDEPENDENCE_2026-10-18/` are historical: they were produced at
> commit `8692603f3a` and cannot be regenerated from the current tree.
>
> **Later on 2026-10-19 — Decision 1 (the DLF IDP hold) is RESCINDED** by the owner's
> universal source-voting directive. DLF IDP and DLF Rookie IDP vote again under the
> one DLF family cap (`dlf_offense_only_vote` now defaults OFF; `=1` re-applies the
> hold). Where this record says DLF IDP is held, read that as the 2026-10-18 state.
> The measured restore, split into DLF's own vote and the outlier-filter side
> effect, is in the consensus record.

Owner directive "Master owner decision closeout & evidence-unblock", 2026-10-18,
PART 2, Decisions 2, 3, 4 and 5 (Decision 8, the active package model, is
unchanged: `geom_q078_v1`, q = 0.78). This record covers implementation and
evidence. Each change goes through an existing canonical owner: source
lineage plus the family cap (`data_contract.cap_family_weights`), the
owner-policy vote-hold gate, and the freshness owner
(`config/sources/freshness_v1.json`). There is no second weighting system,
and no `_RANKING_SOURCES` base weight, Hill constant, q or model gate changes.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## Summary

| decision | change | flag (default) | value effect on the pinned board |
|---|---|---|---|
| D2: IDP-scoped shared correlation cap | On a defensive row where both `idpTradeCalc` and `idpShowCombined` vote, they are one lineage, for the family cap and for the B11 family count | **WITHDRAWN 2026-10-19** (deleted; similarity is not lineage) | historical: engaged on 0 rows while The IDP Show was quarantined; on boards where both vote, ~300 IDP rows, including ~30 that fell 70% through the single-source haircut |
| D3: IDP Trade Calculator offense vote | Its offense vote is excluded: an extra vote whose independence from KTC Crowd is unproven. IDP and pick votes are unchanged | **WITHDRAWN 2026-10-19** (deleted; its offense votes are main's) | historical: 428 offense + 62 tethered pick rows |
| D4: DLF Values rank → Hill | `dlfValuesSfTep` is registered as an offense-only member of the `dlf` family, under DLF's one provider cap | `dlf_values_rank_hill_vote` (**ON**: every gate passed) | 300 offense + 40 tethered pick rows. Offense p50 0.27%, p90 1.7%, max 11.7%; top-50 max 1.8% |
| D5: FantasyPros upstream clock | `fantasyProsIdp` style is `EXPLICIT_UPSTREAM_TIMESTAMP`; the voting clock is the vendor's expert-update time | config (no flag) | **none**. Freshness 0.58 → 0.18 (STALE → SEVERELY_STALE). Freshness-axis confidence labels change on 142 IDP rows; no bucket changes |
| combined (2026-10-18 defaults, superseded) | D2 + D3 + D4 + D5 | | 427 offense + 60 pick rows. Offense p50 1.3%, p90 3.7%, max 14.2%; top-50 max 3.7%; top-50 / top-200 membership swaps 1 / 1; 0 rows newly unpriced |

## Pins and reproduction

| input | identity |
|---|---|
| code | branch `claude/idp-source-independence`, stacked on release train 8 (`integration/train-8-2026-10-18`, PR #1809) |
| raw payload | `exports/latest/dynasty_data_2026-10-18.json`: sha256 `1d26baef…d1d216`, scrape 2026-10-18T18:59:52Z |
| historical archives | sha256 of each in `evidence/SOURCE_INDEPENDENCE_2026-10-18/closeout.json` → `history[]` |
| baseline | all four decisions off: the three flags at 0, and `fantasyProsIdp` style unset |

Reproduce, offline:

* `python scripts/source_independence_closeout.py --out docs/sources/evidence/SOURCE_INDEPENDENCE_2026-10-18/closeout.json`.
  The script builds through the canonical pipeline (`src/api/value_replay.build`) with
  one controlled change per build. Its independent checks recompute the B11 family
  count from each row's own per-source stamps, using a declaration written in the
  script rather than read from the production map. They also check every merged
  family's applied weight. Historical archives replay through the contract's
  `csv_root` seam: `CSVs/site_raw` and `data/scrape_state` as committed by the commit
  that added the archive, overlaid with the archive's own `site_raw`.
* `scripts/golden_board.py` / `scripts/board_diff.py` captures for each flag:
  `evidence/SOURCE_INDEPENDENCE_2026-10-18/board_diff_*.txt`.

## `board_diff` (golden captures, pinned board, before = all four off)

| capture | values moved | newly (un)priced | ranks | confidence buckets | other labels |
|---|---|---|---|---|---|
| D2 only (`board_diff_d2.txt`) | **0** (`--expect-no-value-change` OK) | 0 / 0 | 0 | 0 | none |
| D3 only (`board_diff_d3.txt`) | 490 | 0 / 0 | 622 | 60 | tiers 599, gap direction 19, disagreement 20 |
| D4 only (`board_diff_d4.txt`) | 340 | 0 / 0 | 475 | 24 | tiers 592, gap direction 8, disagreement 6 |
| D5 only (`board_diff_d5.txt`) | **0** (`--expect-no-value-change` OK) | 0 / 0 | 0 | 0 | 142 confidence labels (freshness axis) |
| all, production defaults (`board_diff_combined.txt`) | 487 (p50 1.2%, p90 3.5%, max 14.2%) | 0 / 0 | 649 | 69 | tiers 645, gap direction 16, disagreement 23 |

Tier IDs are the board's natural-break tiers, so any value movement renumbers them
board-wide (including picks whose value did not move). Every moved value is either an
offense row (D3 and D4 votes) or a current-year pick tethered to the rookie pool, or
its tier alias. No IDP row moves under any of D3, D4 or D5.

## D2: IDP-scoped shared correlation cap

**Mechanism.**

* `data_contract.ROW_SCOPED_CORRELATION_GROUPS` declares one rule: members
  `idpTradeCalc` and `idpShowCombined`, group `idpShow`, asset class `idp`, lineage
  `pair-idptradecalc-idpshow`.
* `row_scoped_family_map` engages the rule on a row only when the row is defensive
  and every member casts a positive-weight vote.
* The resulting per-row family map feeds the existing owners:
  * `cap_family_weights(family_of=…)`, the same owner and the same cap;
  * the `independentSourceCount`;
  * the retained-authority denominator;
  * the B11 confidence assembly: `_family_evidence_for_row` and the eligible-family
    set.
* Offense and pick rows never engage. The IDP-only board (`idpShow`) stays
  unregistered, so it can never vote.
* Engagement is stamped per row (`sharedLineageCaps`) and per build
  (`sourceWeighting.independencePolicy.rowScopedCorrelation[...].rowsEngaged`).

**Replay.** Independent family-count check: 0 count mismatches and 0 independence-axis
mismatches on every build. Recomputed engagement equals stamped engagement everywhere,
and no merged lineage carried more than one provider's authority.

| archive | dataset state | IDP rows where both vote | rows engaged | values moved (IDP / offense / pick) | IDP p90 / max | confidence flips |
|---|---|---|---|---|---|---|
| 2026-09-05 | absent (full base weights) | 303 | 303 | 239 / 1 / 53 | 10.3% / 23.2% | 109 IDP (108 medium→low) |
| 2026-09-15 | absent | 302 | 302 | 240 / 1 / 59 | 10.1% / 22.9% | 101 IDP |
| 2026-09-25 | present | 301 | 301 | 237 / 1 / 31 | 2.2% / 3.6% | 83 IDP |
| 2026-10-02 | present | 301 | 301 | 0 / 0 / 0 | — | 86 IDP (medium→low) |
| 2026-10-10 | present | 300 | 300 | 229 / 1 / 23 | 0.6% / 1.1% | 73 IDP |
| **2026-10-18 (pinned newest)** | present | **0** | **0** | **0 / 0 / 0** | — | **0** |

* The single offense row that moves is the two-way player, Travis Hunter. His
  alt-position (DB) value feeds `_apply_two_way_player_boost`. The moved picks are
  current-year slots tethered to the merged rookie pool.
* On 2026-10-02 the cap did not bind in value (the members' combined weight was at or
  under one provider's), but the merged family still counts once, hence the confidence
  changes.
* The boards before 2026-09-23 predate the dataset-state store, so freshness
  weighting is off there and every source votes at full base authority. The 22-23%
  maxima come from that state. They show what the cap does when both members are
  fully fresh.

**Default ON.** The coordinator's rule was met: the cap engages solely where both
members are eligible, and `board_diff` on the pinned board shows 0 values, 0 ranks and
0 labels moved, byte-identical to the baseline.

The owner should be aware of one consequence. When the vendor republishes its
combined chart, The IDP Show's quarantine lifts automatically. From that build on, the
cap engages on roughly 300 IDP rows, with the movement profile of the replay rows
above. That movement is this release's validated behaviour, not a new activation. For
roughly 80-110 rows it lowers B11 confidence (medium→low), because two correlated
copies now count as one family. To keep two families instead, set
`RISKIT_FEATURE_IDP_SHARED_CORRELATION_CAP=0` and restart.

### Review follow-ups (2026-10-19): superseded

Review found that D2's merged lineage did not yet reach the single-source haircut or
the two-way boost. Commit `e7f8286e10` extended it there. Measured on boards where
both providers vote, that turned about 30 defenders into one-lineage rows at 30% of
their value (L'Jarius Sneed 1,133 → 339).

The owner's 2026-10-19 directive then withdrew D2, and those changes went with it.
The two-way boost keeps a correctness fix of its own (flag
`two_way_alt_evidence_rules`), on the existing B10 families. See
`docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md` for the haircut decomposition:
grouping, the 0.30 step and eligibility.

## D3: IDP Trade Calculator offense vote, verified and excluded

**Verified existing behaviour.**

* `idpTradeCalc` is registered with `scope=overall_idp` plus
  `extra_scopes=[overall_offense]` (`src/api/data_contract.py`, registry entry
  `idpTradeCalc`). It is in `_VALUE_BASED_SOURCES`, and its family is its own key
  (no `correlation_group`).
* So on every offense row it voted **value-direct as an independent B10 family**. On
  the pinned board that was 434 offense rows, freshness 0.89, family adjustment 1.0,
  outside the `ktcCrowd` cap.
* Lineage (`pair-idptradecalc-offense-ktc`) records batch-level value identity with
  KTC's base superflex crowd at 2 of 4 earlier batches.
* Measured here: the offense batch voting since 2026-10-10 is **not** an identity
  batch. Against every KTC base-SF capture and every KTC Crowd TE++ capture from
  2026-09-25 to 2026-10-18, at most 4 of 343-353 non-TE offense rows are exactly
  equal, and at most 51 are within 1%.
* Control: the same method reproduces the known identity batch (the September CSV vs
  KTC 2026-08-26 gives 209/353 exact and 352/353 within 1%).
* Independence is therefore not evidenced, and derivation is not proven. That matches
  the coordinator's description of the defect: an independent family vote without
  lineage proof.

**Change.**

* `POLICY_SOURCE_ROW_CLASS_VOTE_HOLDS["idpTradeCalc"]` (asset class `offense`) holds
  the vote on QB/RB/WR/TE rows only. It applies after the Phase 1 ordinal pass, so the
  source's ranks on the rows it still votes on are byte-identical.
* On offense rows it is also not an eligible B11 family, so its silence is not counted
  as missing evidence.
* It does **not** enter the KTC Crowd cap, because derivation is not proven.
* Picks are out of the hold's scope (`overall_offense` also reaches `PICK`; the hold
  is by player class, not by scope).

**Measured on the pinned board** (`board_diff_d3.txt`):

* `idpTradeCalc` offense votes: 434 → 0. IDP and pick votes: 0 changed.
* Offense rows where it was the only voter: 0. Newly unpriced: 0.
* Offense values: 428 moved. p50 1.2%, p90 3.0%, max 13.4% (Adam Trautman, 1183 →
  1341; four voters remain). Top-50 max 2.2%; top-150 max 2.3%; top-50 membership
  swaps 1.
* Picks: 62 moved, max 2.4%, all rookie-pool tether or tier alias.
* Confidence: 60 offense bucket flips, 29 down (one family fewer) and 31 up (where the
  IDP Trade Calculator had been the disagreeing or stale family).
* `independentSourceCount` falls by one on 426 offense rows.
* Package model (`geom_q078_v1`, 2,000 seeded offense pairings): 0 invariant failures;
  8 side flips and 13 crossings of the 250-point band, all from raw value movement.
* Five historical archives give the same profile: offense p90 0.4-3.6%, max 3.7-13.0%,
  0 IDP/pick votes changed and 0 rows unpriced.

**Default ON.** The owner chose exclusion as policy, and the contribution is measured
here. Rollback: `RISKIT_FEATURE_IDPTC_OFFENSE_VOTE_EXCLUDED=0` plus a restart restores
the prior board byte for byte.

## D4: DLF Values rank → Hill

**Mechanism.**

* `dlfValuesSfTep` is registered in `_RANKING_SOURCES` with:
  * `correlation_group: "dlf"`, `scope: overall_offense` and no extra scopes;
  * `is_tep_premium: true`, because the vendor titles the board "with TE Premium";
  * `depth: 320`.
* `_SOURCE_CSV_PATHS` declares `signal: rank` with `rank_from: value_order`. The parser
  derives competition ranks from the published value column: ties share the better
  rank, and a non-positive value is missing, never a rank.
* It is not in `_VALUE_BASED_SOURCES`, so raw / max is rejected structurally. The
  native number stays visible in `sourceNativeValues`.
* While the flag is off, it is held through `POLICY_SOURCE_VOTE_HOLDS`, the same gate
  as the DLF IDP hold, with `holdWhileFlag: "off"`.
* The dataset recorder reads the value column for a `value_order` board. Recording it
  as a rank board would read FAILED on every fetch.

**Activation gates.** Declared in this PR, before the release decision. The thresholds
are informed by the 2026-09-25 and 2026-10-18 gate records; they were not blind to
them. All are measured against the all-off baseline on the pinned board.

| gate | criterion | measured | result |
|---|---|---|---|
| source timestamps | content clock from observed broad changes (not fetch time), ON_SCHEDULE, HEALTHY | SNAPSHOT style; clock = last broad change 2026-10-18T12:27Z; age 6.5 h of 24 h expected; freshness 1.0; HEALTHY | pass |
| completeness | ≥ 300 player rows, all of QB/RB/WR/TE, no non-positive values, no pick rows in the voting CSV | 319 rows (QB 54, RB 91, TE 46, WR 128), 319 distinct values, 0 non-positive, 0 pick rows | pass |
| longitudinal stability | ≥ 10 distinct releases; consecutive-release Spearman ≥ 0.95; top-24 overlap ≥ 20 | 24 releases, 2026-09-25 → 10-18 (29 commits); Spearman 0.986-1.000; top-24 overlap 22-24 | pass |
| top-player movement | top-50 max \|Δ\| ≤ 5%, top-50 membership swaps ≤ 2, offense p90 ≤ 3% | top-50 max 1.8%; 1 swap; p90 1.7%; top-150 max 3.5% | pass |
| outlier diagnostic | DLF Values Hampel drop rate ≤ 5% | 0.31% (1 of 319) | pass |
| picks / IDP non-interference | votes only on offense rows; 0 IDP value moves; pick moves only via the rookie tether or a tier alias | 319 votes, all offense; 0 IDP moves; 40 pick moves, all tether/alias | pass |
| one DLF family | DLF family applied weight ≤ 1.0 on every row; no second DLF family counted | max 1.0001 (rounding); 0 rows with a second DLF family | pass |
| geometric package model | 0 invariant failures; side flips ≤ 1% of 2,000 seeded pairings | 0 failures; 6 flips (0.3%); 9 band crossings | pass |
| regression suite | `tests/api tests/canonical tests/sources -m "not livedata"` green with the flag ON; contract validator structural + full lanes OK | see Validation | pass |

Movement notes:

* The largest mover, Josh Cameron (+11.7%), is the incumbent outlier filter, not DLF
  Values' own vote. His DLF Values vote is 1714, near the row's centre. With one more
  observation the filter keeps Draft Sharks' 2639, which it had dropped before.
* The same happens on three more rows (Bryce Young, Jeremiyah Love, Justin Herbert): a
  non-DLF family returns. The two DLF members still enter the outlier statistic as two
  observations, as `dlfSf` + `dlfRookieSf` already do. That is the existing design;
  `joint_outlier_sparse_challenger` addresses it and is not changed here.
* On 33 offense rows that DLF Rank does not reach, DLF gains coverage. It is still one
  family.

**Default ON.** Every gate passed. Rollback:
`RISKIT_FEATURE_DLF_VALUES_RANK_HILL_VOTE=0` plus a restart re-applies the declared
hold. The source stays collected and displayed, and the board returns byte for byte.

## D5: FantasyPros on its actual upstream clock

**Change.**

* `config/sources/freshness_v1.json` gives `fantasyProsIdp` the style
  `EXPLICIT_UPSTREAM_TIMESTAMP`. The voting clock is
  `min(vendor expert-update time, last broad dataset change)`
  (`freshness.assess_subset`). The vendor time is the page's `last_updated_ts`,
  persisted by `scripts/fetch_fantasypros_idp.py` in
  `data/scrape_state/fantasyProsIdp_upstream.json` (2026-09-04T02:34:24Z, 2 of 6
  experts).
* A re-scrape, a revert or a parser re-keying moves only the broad-change clock, so it
  can never refresh the age. Pinned by
  `test_d5_rescraping_unchanged_content_cannot_refresh_the_age`.
* One owner and no flag: the same config is read by the board, the source-weighting
  report, the inventory and the training manifest, so they cannot disagree.
* Rollback: remove the `style` key from that one line.

**Measured on the pinned board.**

| | before | after |
|---|---|---|
| clock | last broad change 2026-09-23T21:54Z (a vendor revert counted as a change) | vendor expert update 2026-09-04T02:34Z |
| age / expected | 597 h / 253 h | 1,072 h / 253 h |
| freshness / state | 0.581 STALE | **0.180 SEVERELY_STALE** |
| voting rows | 249 | 249 (it votes at reduced weight, never at zero; it is excluded as a non-vote only once below the 0.02 quarantine floor) |

* Values moved: **0**. On these IDP rows FantasyPros is the only subgroup member of the
  hierarchical blend (anchor = the IDP Trade Calculator + Draft Sharks), and a lone
  member's weight does not move a weighted mean. The weight would matter once a second
  subgroup member votes, for example DLF IDP if its hold were lifted.
* Confidence: the freshness axis now names FantasyPros as stale. Labels change on 142
  IDP rows; buckets do not change.

**Dual-family duplicate identities: analysis completed.**

* The CSV lists 15 dual-eligible edge rushers twice (the DL and LB pages, for example
  Dallas Turner at LB 89 and DL 118).
* The contract ranks the source over **board rows**, one per player (Phase 1 of
  `_compute_unified_rankings`). Each duplicated player therefore casts exactly one
  vote, at the better effective rank, and no other player's rank shifts. On the pinned
  board, 249 votes come from 249 distinct names.
* There is **no vote amplification** to remove, and no independent material is
  suppressed.
* The duplicates' one remaining effect was on the broad-change clock (a dual-listed
  player's two entries both count as changed rows). That clock no longer decides voting
  freshness.
* The fetcher dedupe stays deferred, for a narrower reason than before. Dropping the
  `name#2` rows would still add one false closed interval to cadence learning, which
  would raise the learned expected cadence slightly. Recorded on the lineage defect
  `fantasypros-idp-dual-family-duplicates`.

**Scope.** `fantasyProsSf` (offense) and `fantasyProsFitzmaurice` publish no
vendor-stated time that we collect.

* Their clocks are content-change clocks, not fetch times. `fantasyProsSf` changes
  broadly almost daily (329-383 rows per event), and Fitzmaurice monthly.
* Re-scraping unchanged content cannot refresh either one.
* Whether the FantasyPros offense page states an update time is unverified offline:
  UNRESOLVED.

## Validation

See the PR for the exact command output. In summary:

* `scripts/format_python_changes.sh`;
* `scripts/check_decision_coercions.py`;
* the planning and governance gates;
* `pytest -n 3 tests/api tests/canonical tests/sources -m "not livedata"`;
* the source-registry parity test;
* `scripts/validate_api_contract.py --lane structural` and `--lane full` (ok, 0
  errors).

## Completion result

* **STATUS:** DONE for implementation and evidence. Production verification is
  pending, after merge and deploy.
* **ACCEPTANCE:**
  * D2: cap through lineage plus the family-cap owner, behind a flag; replay with
    independent confidence-count checks; current values preserved.
  * D3: behaviour verified with code references and a measured contribution; the
    unproven vote excluded.
  * D4: rank → Hill inside the DLF family, behind a flag, every gate measured.
  * D5: upstream clock, duplicate analysis, stale reported honestly.
* **EVIDENCE:** `scripts/source_independence_closeout.py`;
  `evidence/SOURCE_INDEPENDENCE_2026-10-18/`; `tests/api/test_source_independence_closeout.py`.
* **UNRESOLVED:**
  * production verification of the deployed build;
  * whether the FantasyPros offense page states an expert-update time;
  * the FantasyPros IDP fetcher dedupe, which needs a representation-change marker in
    the dataset-state owner;
  * D2's activation on The IDP Show's republication moves IDP values automatically,
    measured above;
  * D2/D3 withdrawn 2026-10-19; the open items of the rework are listed in
    `docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`.
* **NEXT_ACTION:** release-train integration of this PR, then the deploy and
  observation of `sourceWeighting.independencePolicy` on production.
