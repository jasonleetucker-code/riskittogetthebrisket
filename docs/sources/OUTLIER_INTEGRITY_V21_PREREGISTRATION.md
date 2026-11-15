# Outlier integrity V2.1: successor preregistration

**Registration only.** This document, [`outlier_integrity_v21/HELDOUT_RULE.json`](outlier_integrity_v21/HELDOUT_RULE.json)
and [`outlier_integrity_v21/manifests/POPULATIONS.json`](outlier_integrity_v21/manifests/POPULATIONS.json)
(with its builder) are committed **before** any V2.1 code is written and before V2.1 is evaluated
on any board. No V2.1 drop set, hold, refusal, gate rate, stability figure or bootstrap exists.
**The criteria below may not change after this commit.** A change is logged as a deviation beside
the original (§16). A deviation that loosens any gate or criterion makes READY FOR APPROVAL
unreachable for this registration.

**V2 stands unchanged.** The V2 preregistration
([`OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`](OUTLIER_INTEGRITY_V2_PREREGISTRATION.md), anchor
`3c69945723`), its deviations log and its verdict, **MORE RESEARCH REQUIRED**
([`outlier_integrity_v2/OWNER_REPORT.md`](outlier_integrity_v2/OWNER_REPORT.md)), are not
reinterpreted, re-scored or relabelled here. V1 (`outlier-corroborated-v1`, NOT ELIGIBLE) stands
unchanged too.

**V2's held-out boards are SPENT.** V_HELDOUT (61), I_INDEPENDENT (7), V2's EXCLUDED board and
every archive added during V2's prospective window before this commit are listed as SPENT in
`POPULATIONS.json`. V2.1 never builds, scores or reads them (§5.2). The V2.1 held-out set does not
exist yet. It is made of boards the automated refresh produces **after this commit** (§5.3).

Authority:

* the owner implementation directive of 2026-10-20 ("Fix the outlier filter and restore DLF IDP
  voting", with its binding D4 addendum), verbatim at
  `docs/owner/OUTLIER_INTEGRITY_V2_DIRECTIVE_2026-10-20.md`;
* the owner's #1831 Option B decision of 2026-10-20, item 6 (wire the freshness-affected rows into
  V2's regression and integration tests), verbatim at
  `docs/owner/PR1831_OPTION_B_DECISION_2026-10-20.md`;
* the owner's O-1 decision of 2026-10-20 (~19:45 UTC), verbatim at
  [`docs/owner/OUTLIER_V21_O1_DECISION_2026-10-20.md`](../owner/OUTLIER_V21_O1_DECISION_2026-10-20.md):
  the gate of record is REAL PRIOR HISTORY (ARRIVING); NO-HISTORY results are still reported; with
  no history the filter must never drop a legitimate vote; the wrong-player and wrong-scale gates
  must still pass;
* the valuation invariants in `CLAUDE.md` (one canonical owner, missing is never zero, signal
  independence, champion ≠ challenger, family caps).

This document authorizes no activation. `outlier_integrity_v2` and every sub-flag stay default
OFF. The DLF IDP hold (`dlf_offense_only_vote`) stays ON, DLF Rookie IDP stays held, D4
(`dlf_values_rank_hill_vote`) stays OFF and freshness v2 (`source_freshness_schedule_v2`) stays
OFF. Activating any of them is owner-reserved.

**Boundary.** V2.1 changes input quality only. It does not change rank → value curves, Hill
constants, `_RANKING_SOURCES` weights, correlation groups, provider families, family caps, the
freshness rule or schedule, Package VA, `geom_q078_v1`, Trade Calculator fairness math or Trade
Finder logic. A hash test pins each of them (§9 property 11).

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

---

## 0. What was seen before registration (disclosures)

None of this is a V2.1 outcome. All of it shaped the design, and it is declared so that nobody
mistakes it for independent evidence.

1. **Every V2 result**: the Stage 4 held-out run (V ∪ I, 68 boards), the gate tables under
   NO-HISTORY and ARRIVING, the E_DEV exploratory replay, the §6 boards on pin2015 and pin0527,
   and the four independent reviews. Each repair in §3.2 targets a defect those reviews named.
2. **Repair constants informed by spent boards.** The B0 tolerance (R1) was chosen knowing that the
   KTC Crowd quarantines on V2's held-out boards came from 1-point rank/value inversions (Brock
   Wright, rank 352 at 1318 against rank 351 at 1317). The B3a minimum (R2) was chosen knowing the
   2026-10-10 IDPTC offense false positive rested on 2 rows. The age interval (R5) was chosen knowing
   the 48 Draft Sharks `identity_contradicted:age` refusals. These constants are fixed now and are
   never re-tuned; the spent boards that motivated them are never used to check them.
3. **The Option-B freshness fixture** (`tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json`,
   31 rows) and its board, pinOB (`dynasty_export_20261020_121619`, payload `67f6d56e…`), were
   built by the #1831 lane under the incumbent. pinOB is a must-pass constraint, never evidence.
4. **V2's design and its ARRIVING numbers** (AD1a 97.2%, AD1b 95.5%, AD1c 100%, AD1d 100%, AD4
   100%, AD2 48.8%, AD3 12/16) were seen before the owner chose O-1. The owner's choice was made
   on the question as asked. It was made knowing V2's NO-HISTORY failures, not knowing any V2.1
   number, because none exists.
5. **No V2.1 held-out board exists at this commit.** Every held-out board is produced by the
   automated refresh after this commit. It has no design contact of any kind.

## 1. Question

> With the defects V2's review named repaired, the upstream identity evidence in place, and real
> prior history as the gate of record, does the layered pipeline (A identity, B source and
> normalization integrity, C disagreement-preserving rule, D the unchanged confidence owner) catch
> corrupted, misidentified, mis-scaled and malformed observations at the directive's §5 rates,
> while dropping **no** legitimate vote when it has no history, keeping every legitimate vote the
> incumbent wrongly removes when DLF IDP, DLF Rookie IDP or D4 vote, and staying no less accurate
> or stable than the incumbent, within the performance and contract-size budgets?

## 2. Candidate and comparators

| name | definition | role |
|---|---|---|
| **incumbent** | `data_contract._hampel_filter_per_player` (K 2.75, MAD, floor 1,000, n ≥ 4), unchanged | champion |
| **V1** | `outlier-corroborated-v1`, unchanged | reported |
| **V2** | V2 at its frozen thresholds (`outlier_integrity_v2/FROZEN_THRESHOLDS.json`), unchanged | reported comparator; isolates the repairs' effect |
| **V2.1** | §3, primary configuration (§3.8) | candidate |
| **V2.1-NOHIST** | V2.1 with the history lane empty | the cold-start variant (§7.1); cold-start safety gate (§7.4) |
| **V2.1+D1** | V2.1 with `integrity_holds_as_withheld` ON | separate evaluation of the confidence change D-1; activation owner-reserved |
| **V2-RPC** | V2.1 with Layer C replaced by reliability-prior per-family error cells | **required** scientific comparator (V2 never built it); never a candidate |

## 3. Algorithm (registered)

V2.1 = V2 as registered and as clarified in V2's `DEVIATIONS.md` C1–C22, **plus** the repairs in
§3.2 and the persistence rules in §3.4, which supersede any V2 rule they name. Order, coordinate
and verdict vocabulary are V2's (V2 prereg §3): freshness and health weighting → **A** → **B** →
**C** → existing B10 family cap → existing count-aware blend → **D** (existing confidence owner).

A refused, held, withheld or quarantined observation is **absent**: never zero, never another
player's value, never a historical value from an unrelated curve.

### 3.1 Carried forward unchanged

* **B1 rookie ladder fail-closed** (`rookie_ladder_fail_closed`). An untranslated rookie-ladder vote
  is withheld `normalization_untranslated`. A vote translated through a quarantined backbone is
  `normalization_dependency_unavailable`.
* **B2 payload-vs-same-run-CSV provenance** (`payload_provenance_guard`), with V2's m_g, ε, ≥ 15 rows,
  value ≥ 100, row proof ln 2, and the CSV-fill replacement. The only change is the sign-share
  reading in R14.
* **Layer C, the six disagreement-preserving guards** (`oiv2-layer-c-v1`): ≥ 3 providers; a
  corroborated reference of 2 non-lineage-linked other providers within ln 2; beyond τ_C from every
  other provider; not persistence-confirmed (now under §3.4); family < 0.5 of the family-capped
  weight; ≥ 2 providers survive. No MAD, no scale estimated from the judged row, no 1,000-point
  floor. Similar numbers never merge providers. A kept dissent is stamped `kept_dissent` and still
  votes. τ_C floor ln 4.
* **One dispatcher.** The per-row filter slot, the B11 lost-evidence replay and
  `_two_way_alt_center` all route through one Layer C context. With V2.1 on, the incumbent filter is
  never called, and V1 and V2.1 are mutually exclusive.
* **Layer D.** `src/api/confidence.py` and `config/confidence/gate_v1.json` stay byte-identical.

### 3.2 Repairs (each a registered rule, with its expected effect)

| id | repair (V2 defect it answers) | registered rule | expected effect |
|---|---|---|---|
| **R1** | **B0 tolerance** (reviewers 1 #8, 2 #6, 4 #2: one 1-point inversion quarantined all ~460 KTC Crowd votes on 7 held-out boards) | For value-plus-rank CSVs, sort by vendor rank. An adjacent pair is *discordant* only if the worse-ranked entry's value exceeds the better-ranked entry's by more than max(2, 0.005 × the better-ranked value). Tied ranks or tied values are never discordant. **Whole-source B0** fires iff discordant pairs ≥ 5% of adjacent pairs **and** ≥ 10, **or** Spearman(rank, value) > −0.5. Below that, each discordant row is stamped advisory `format_minor_discordance` and **still votes**. Schema, column, non-numeric and `dataset_integrity` FAILED rules are unchanged. Constants fixed now. | KTC Crowd B0 quarantines from rounding inversions → 0. D4's 21 / 1,123 losses to B0 → 0. An order-reversed board (AD3) still fires through the Spearman test. Ranks ×2 / ×5 and values ×0.01 keep the rank order, so B0 does not catch them; B3 must. |
| **R2** | **B3a minimum n** (reviewer 4 #3: one class quarantined from 2 rows) | B3a (rank-mass conservation per source and asset class) is evaluated only when ≥ 20 rows of that source and class have a leave-source-out reference. Below that it abstains and stamps advisory `segment_too_small`. | The 2-row IDPTC offense board-level false positive → 0. B3a still fires on a whole-class scale break. |
| **R3** | **B3b n_min scope** (reviewer 1 #2: n_min guarded only the direction test) and **selector-rule match** (reviewer 1 #3) | n_min applies to **every** B3b test: direction, gross scale and proof escalation. A segment below n_min abstains. A B1 or B2 proof acts only within its own scope, never through a B3b test on a sub-n_min segment. The Stage 2 selector evaluates the **served** rule exactly, with B1 untranslated votes, B2 row proofs and B2 board proofs all counted, through the same code path the pipeline runs. | Small-segment quarantines (TE, DB) occur only with B1/B2 proof. The selection's feasibility check measures the rule that is served. |
| **R4** | **A3 family compatibility** (reviewer 2 #1: only OFFENSE / IDP / KICKER compared, so a QB entry on a WR row was never contradicted) | Position families: QB {QB}; RB {RB, FB, HB}; WR {WR}; TE {TE}; K {K, PK}; DL {DL, DE, DT, NT, IDL, EDGE}; LB {LB, ILB, OLB, MLB, EDGE}; DB {DB, CB, S, FS, SS}. The source's published position is compatible iff its families intersect the families of the row's Sleeper `position` ∪ `fantasy_positions` (where the identity owner's directory carries it), or the pair is an allowed drift (DL ↔ LB, LB ↔ DB, RB ↔ FB), or the player and family are in `_TWO_WAY_PLAYERS` under #1817's alt-evidence rules. Otherwise CONTRADICTED `identity_contradicted:position_family`. QB, RB, WR, TE and K are mutually incompatible; DL ↔ DB is incompatible. Table fixed now. | Swaps across offense families, and DL ↔ DB swaps, become catchable when the source publishes position (AD2-ID). False-refusal risk on real reclassifications is measured by the cold-start safety gate (§7.4). |
| **R5** | **Age comparison basis** (reviewers 2 #2, 4 #1: a decimal vendor age compared with Sleeper's integer age refused correct players; 48 held-out movers, Pete Werner −12.8%) | Represent each age as an interval: an integer age a as [a, a + 1); a decimal age as a point. When Sleeper carries `birth_date`, use the exact age at the vendor dataset's publication date. CONTRADICTED `identity_contradicted:age` iff the two intervals are more than τ_age = **1.0 year** apart. τ_age is fixed now, not selected (V2's selection ran on an empty evidence set, S15). | `identity_contradicted:age` false refusals of the same player → 0. A real age gap above one year is still refused. |
| **R6** | **Ordinal-slot preservation** (reviewer 2 #7, boards F2: removing a refused entry re-ranked 179–322 other votes of the same source by up to 1.4%) | A refused, held or withheld entry of a rank-signal source **keeps its ordinal slot**. The source's other entries keep the effective ranks they would have with the entry present. Only the refused entry stops voting. | Refusal side effects on other rows → 0. A refusal moves only its own row. |
| **R7** | **Layer A refusal explainer coverage** (reviewer 4 #8: refusals appeared only in the census) | Every A refusal or hold, B hold, withhold or quarantine, B4 hold and C drop appears in the per-player explainer (`sourceRankMeta` and the value explainer) with exactly one primary reason and one directive §10 category, mapped through `src/sources/voting_status.py` (now on `main` via #1831), never a fork. A vote that passed A and B is never shown in an invalid-identity, format, normalization or broken-feed category. Observations that never vote (a held source, stale IDP Show, DLF Values with D4 off) are labelled with their actual non-voting state, never with an identity verdict (boards F3). | 100% explainer coverage of exclusions; 0 legitimate votes shown as invalid. |
| **R8** | **Team-only mismatch at cold start** (boards F1: with no history, 4 FantasyPros Fitzmaurice and 2 DLF Values votes were held, each vendor team being the player's previous team) | A team-only mismatch, with name and position family agreeing, **never refuses without history**. It votes, stamped `voting_team_unconfirmed`. With history: continuity (the source's last accepted observation of this player carried the team it publishes now, or the team it publishes is the player's previous team per the team-history map) votes as VERIFIED-lag; a vendor that previously listed the player at Sleeper's team and now lists a team that is neither Sleeper's current nor previous team is UNRESOLVED (refused, held). | The 6 F1 false holds → 0. Team is never the sole refusal reason at cold start. |
| **R9** | **A4 rule registered explicitly** (reviewer 2 #3: V2's C4 changed a registered rule as a "clarification") | A4 is V2's C4 rule, registered here as V2.1's rule: disambiguate a collision by Sleeper id, position group, position family (DL / LB drift allowed), then team. Survivors with the same team and compatible positions are one person listed twice and keep the join's choice. Survivors with no team, or with conflicting evidence, are refused UNRESOLVED. | FantasyPros IDP's dual-page edge rushers keep voting. Byron Murphy II / Jr. stay split. Indistinguishable name-only entries are refused. |
| **R10** | Team continuity read from the wrong entry (reviewer 2 #8) | Continuity and the mismatch test both read the A4-chosen entry. | Bug fix. |
| **R11** | A1 directory scope (reviewer 2 #9) | A1 resolves Sleeper ids against the identity owner's full Sleeper player directory snapshot for the run, not against board rows only. | A Sleeper id belonging to a player outside the board is contradicted instead of ignored. |
| **R12** | B4 / C persistence (reviewer 1 #6) | §3.4. | §3.4. |
| **R13** | Performance and contract size (criterion 11 failed at 1.69×–2.0×; contract +13.8%) | Not a decision rule. Implementation intent: no full-board deep-copy snapshot (copy only touched rows); identity grading memoized per (source, CSV content hash); per-vote integrity stamps emitted only for non-default verdicts; census aggregated per source. Judged by criteria 13 and 14. | ≤ 1.25× build time; contract growth ≤ 2%. |
| **R14** | **INJ-SEG / B2 sign-share reading** (reviewer 1 #7, V2 S16: 30% unshifted rows made INJ-SEG fail by construction) | B2's "≥ 80% of rows sharing m_g's sign" counts only rows with \|ln(payload / CSV)\| > ε. Rows that agree with the CSV are neither sign. Every other B2 condition is unchanged. | INJ-SEG becomes passable as registered. A healthy capture (every row within ε) still never proves. H2 is covered by H2-SYN (§8), because the H2 boards are spent. |

### 3.3 Corrections carried in as rules (V2 evidence-process defects)

* **Theo Johnson.** The owner-cited case (Draft Sharks 3182 dropped, 2184 → 2023) is covered by
  V2's frozen-panel test, transcribed from the #1817 lane, and stays in the D4 set. The archives
  show 3001 (kept). Both are kept: the panel test must pass, and whatever the pins contain must
  pass. The board that holds the original case (`20261020_052241`) is SPENT and is not rebuilt.
* **Two-way panel (V2 C16).** Travis Hunter's alt panel goes through the same Layer C context with
  no special case. Its decisions are reported and are in scope for independent review.

### 3.4 Persistence and B4 release (resolves the self-confirming persistence risk)

V2 counted a Layer C drop as an accepted observation (C11). A B4 hold released by the cap counted
too. So a corrupted value repeated across boards could make itself persistence-confirmed and stop
being dropped. Worse, V2 counted "consecutive observations" across board rebuilds, and a vendor CSV
is re-read every refresh whether or not the vendor published anything new. A stale corrupted CSV
could therefore confirm itself within about 4 hours. V2.1 registers these rules:

* **P-1, content-distinct evidence only.** An observation contributes to persistence (Layer C
  guard 4) or to a B4 baseline only once per **vendor dataset content hash** (from
  `src/sources/dataset_state.py`). Re-reading the same vendor dataset on a later board adds
  nothing.
* **P-2, holds are not evidence.** An observation that was refused (A), held, withheld or
  quarantined (B), or held by B4, is never an accepted observation. It never counts toward
  persistence or a baseline.
* **P-3, cap release is not confirmation.** When a B4 hold reaches the release cap (2
  content-distinct fetches or 48 h), the vote counts in the blend, is stamped `released_by_cap`
  and raises a source-health alert. It does **not** become an accepted observation. It becomes
  accepted only on a cross-sectional release (another provider within ln 1.25 of it, or
  co-movement) or after it reproduces on ≥ 3 content-distinct vendor datasets spanning ≥ 72 h.
* **P-4, Layer C drops may accrue persistence, visibly.** A Layer C drop that passed A and B
  records the vendor's observation (C11 semantics, needed so a genuine consistent contrarian is not
  dropped forever) under P-1 and P-2. A vote that becomes persistence-confirmed while it is still
  beyond τ_C from every other provider votes, is stamped `persistent_gross_dissent` and raises a
  source-health alert naming the row, for human review. It is never silent.
* **P-5, measured.** The PERSISTENT variant (§7.1) is a required run. Its report names, for every
  case caught under ARRIVING and not caught under PERSISTENT, the mechanism that let it vote (cap
  release, or persistence confirmation under P-4). Structural property: no case passes under
  PERSISTENT by persistence earned from re-reads of one dataset or from refused or held
  observations (§9 property 18).

### 3.5 Layer A verdicts (V2 table, with R4, R5, R8, R9, R11 applied)

| verdict | conditions | effect |
|---|---|---|
| CONTRADICTED | A1 Sleeper or vendor id resolves to a different canonical player (full directory, R11; vendor ids through VID, §3.7); A2 the raw name, re-resolved through the owner, gives a different player; A3 incompatible position **family** (R4); a rookie-board entry outside that board's class (V2 C14); age intervals more than 1.0 year apart (R5) | refused (absent) |
| UNRESOLVED | A4 collision without disambiguating evidence (R9); same-group Sleeper homonyms the source cannot tell apart; A5 fuzzy or surname rung without agreement on position family AND (team OR id); team change against the source's own history as in R8 | refused (absent), labelled held |
| VERIFIED | an id agrees, or name + position family + team agree (team lag with continuity counts) | votes |
| NAME_ONLY / TEAM_UNCONFIRMED | no identity evidence available / team-only mismatch without history (R8) | votes, stamped `voting_name_only_identity` / `voting_team_unconfirmed` |

### 3.6 Thresholds

**Fixed now (a priori):** every V2 a priori constant (V2 prereg §3.5); R1 (2 points, 0.5%, 5%, 10
pairs, Spearman −0.5); R2 (20 rows); R4 family table; R5 (τ_age 1.0 year); P-3 (ln 1.25, 3
datasets, 72 h); τ_C floor ln 4.

**Selected on DEV only** (DEV = V2's E_BASELINE for baselines and history, V2's E_DEV for every
selection; `POPULATIONS.json`), selection seed **20261021**, injections on V2's non-registered
sources only (dlfSf, draftSharksSf, fantasyProsSf, ktcCrowdSfTep, idpTradeCalc offense,
draftSharksIdp, idpTradeCalc IDP; the four AD3 sources are never injected during selection). DEV
history is built in chronological order from DEV boards only:

| constant | grid | selection rule |
|---|---|---|
| ε (B2) | {0.01, 0.02, 0.05} | smallest value with no board proof on any DEV board whose payload and CSV come from the same healthy capture (H3/H4 boards excluded) |
| τ_board (B3a) | — | per (source, class): standard deviation over E_DEV of the class median residual; fire at max(6·τ_board, ln 1.25), with R2's minimum |
| n_min, ρ_min, τ_gross (B3b) | n_min ∈ {10, 20, 30}; ρ_min ∈ {0.0, 0.3}; τ_gross ∈ {ln 3, ln 4} | evaluated on the **served** rule (R3). Among settings with zero clean E_DEV segments flagged hard (H1 boards excluded from "clean"; N1/N2 boards included) and 100% of E_DEV source-split AD3-style injections caught **under ARRIVING (DEV history)**, choose the most conservative (largest n_min, smallest ρ_min, largest τ_gross, in that priority). No feasible setting → FAILED_SELECTION |
| τ_c(source, band) (B4) | k_c ∈ {4, 6, 8}; bands ≤ 50 / 51–150 / 151–400 / > 400 | τ_c = max(ln 1.5, k_c × 1.4826 × MAD of the source's own content-distinct (P-1) same-player Δu over DEV). Choose the smallest k_c whose false-hold rate is ≤ 0.5% of votes on every clean E_DEV board. None feasible → FAILED_SELECTION (V2's fallback to k_c = 8 is withdrawn) |
| τ_C (Layer C) | {ln 4, ln 5, ln 6} | the LARGEST value for which, on E_DEV under ARRIVING (DEV history), material cold-start injections are caught at AD1a ≥ 90%, AD1b ≥ 90%, AD1c ≥ 95%, AD1d ≥ 95% and AD4 ≥ 95%, **and** zero L4-DEV votes (§7.4) are dropped under NO-HISTORY. None feasible → FAILED_SELECTION |

Any FAILED_SELECTION means the run cannot reach READY FOR APPROVAL. The selected values, with the
DEV evidence that chose them, are committed in `outlier_integrity_v21/FROZEN_THRESHOLDS.json`
(Stage 2) before any R or held-out run.

### 3.7 Upstream identity evidence (prerequisites of the wrong-player gate)

V2 could not catch wrong-player swaps that carry no identity evidence, and its Layer A had nothing to
read on name-only and payload-attached values. These upstream changes are **prerequisites P-ID**.
Each is its own named change, with flags off or stamps only and **zero value change** (a byte-identical
board is required):

| id | change | owner / coordination |
|---|---|---|
| **U1** | the CSV parse tuple carries each source's published position, team, age, vendor id, Sleeper id, rookie class and raw display name, and `CsvJoinDecision` carries the per-observation verdict (V2 Stage 1; carried) | identity owner (`src/identity/`) |
| **U2** | `Dynasty Scraper.py` stamps, for each value attached on ktc, ktcSfTep and idpTradeCalc: the matching rung, the page position, and the acquisition path (API intercept, autocomplete fallback, recovered partial) | scraper-ops |
| **U2b** | the same stamp records the observed Superflex and TE-premium toggle state of the capture | scraper-ops |
| **U3** | the name-only boards (dlfIdp, dlfRookieIdp, idpTradeCalc, dlfSf, dlfRookieSf, ktc, ktcSfTep, fantasyCalc, OTC, DynastyDaddy, Flock, Navigator) capture position and team wherever the vendor page shows them | scraper-ops |
| **VID** | a vendor-id → canonical player mapping, append-only. Entries come only from (a) vendor-published Sleeper ids, or (b) VERIFIED joins whose id, name, position family and team agree on ≥ 2 content-distinct vendor datasets. A conflict is never resolved automatically: the id becomes UNRESOLVED | identity owner |

**Readiness rule.** The wrong-player gate is evaluable only when G1 and G2 (§5.3) carry U2, U2b and
U3 stamps and VID was live in the refresh that produced them. That requires these changes to be on
`main` and running in the automated refresh before 2026-11-04T00:00Z. If they are not, the
wrong-player gate is **BLOCKED (dependency)** and the verdict is BLOCKED (§11.1). It is never
inferred as passing. U2 and U3 change the scraper and are coordinated with scraper-ops. They ship
through the normal release process, never through this lane.

### 3.8 Primary evaluated configuration

`outlier_integrity_v2`, `identity_evidence_v2`, `payload_provenance_guard`,
`rookie_ladder_fail_closed` and `source_rank_history_record` **ON**; `integrity_holds_as_withheld`
**OFF** (D-1 is V2.1+D1). Any new V2.1 sub-flag (for example one per repair, if the implementation
needs it) defaults OFF in the registry and ON only in this evaluated configuration. Release defaults
apply otherwise: `source_freshness_weighting` ON, `source_family_cap` ON, `dlf_offense_only_vote`
ON except on DLF-restore boards, `dlf_values_rank_hill_vote` OFF except on D4 boards,
`source_freshness_schedule_v2` OFF except on the pinOB ON-state build. Evaluating a configuration in
replay needs no owner decision. Activating it does (§15).

## 4. Assumptions

V2's assumptions 1–7 (V2 prereg §4), plus:

8. A vendor dataset content hash from `dataset_state` identifies a distinct publication. Two
   boards with the same hash carry one observation, not two (P-1).
9. Sleeper `fantasy_positions` and `birth_date`, where present in the identity owner's directory,
   are correct. Where absent, R4 falls back to `position` and R5 to the integer-age interval.
10. Production would start V2.1's history lane empty at activation, so cold start is a real
    operating state, not only a test variant. This is why the cold-start safety gate is mandatory.

## 5. Populations, manifests and order of work

### 5.1 DEV and R pins (`POPULATIONS.json`)

| population | boards | use |
|---|---|---|
| **DEV** | 79: V2's E_BASELINE (35, history and baselines only) and E_DEV (44, all selection and development) | the only boards V2.1 may develop or select on. Holds H1 (22), H3 (2026-08-03, E_BASELINE), H4 (2 boards, E_BASELINE), H5, N1, N2, N3, N5 |
| **R_PIN** | pin2015 (`dynasty_export_20261019_201546`), pin0527 (refresh `eb10d3e12d`, payload `b639608f…`), pinOB (`dynasty_export_20261020_121619`, payload `67f6d56e…`) | must-pass constraints at Stage 3, never evidence |

`build_populations.py --check` reproduces `POPULATIONS.json` byte for byte. A missing or
hash-mismatched board makes a run incomplete, and the run reports it as such. It is never silently
replaced.

### 5.2 SPENT (never read by V2.1)

70 boards are listed in `POPULATIONS.json`: V_HELDOUT 61, I_INDEPENDENT 7, EXCLUDED 1, and
`dynasty_export_20261020_173527` (added to `main` during V2's prospective window). **Any archive
added to `main` at or before this commit and not listed is SPENT by rule.** A SPENT board is never
built, scored, injected, scanned or used as history input by V2.1. Its labelled cases (H2, the
October H3 rows) are covered only through H2-SYN (§8) and V2's committed record.

### 5.3 The fresh held-out set (sealed until Stage 4)

The full rule is in [`outlier_integrity_v21/HELDOUT_RULE.json`](outlier_integrity_v21/HELDOUT_RULE.json).
In short:

* **Eligibility.** An archive added to `main` by the automated data refresh, whose add-commit
  timestamp **and** payload `scrapeTimestamp` are strictly after T0 (this commit's timestamp), and
  which is not in `POPULATIONS.json`. Complete by V2's rule (`_degraded_critical_sources` empty).
* **H_BUFFER**: eligible boards from T0 to WINDOW_START (2026-10-21T00:00Z). History input only,
  never scored.
* **H_ORIGIN**: complete eligible boards added in [2026-10-21T00:00Z, 2026-11-18T00:00Z), 28 days
  and four week-blocks. Every metric origin, every per-board criterion and every DLF restore pair.
* **H_TARGET**: complete eligible boards in [2026-11-18, 2026-11-25). M1 horizon targets only.
* **Gate boards.** G1 is the first complete H_ORIGIN board at or after 2026-11-04T00:00Z. G2 is the
  last complete H_ORIGIN board. Each has as its prior the complete eligible board immediately
  before it.
* **Minimum sample**: ≥ 56 complete H_ORIGIN boards, on ≥ 20 distinct UTC days, with ≥ 7 in each
  week-block. If it is short at WINDOW_END, the end moves forward a day at a time, at most 14 days
  (G2 and H_TARGET move with it). Still short → INSUFFICIENT → MORE RESEARCH REQUIRED.
* If T0 falls on or after 2026-10-21T00:00Z, every date shifts to the first UTC midnight after T0.
* **Seal.** Until the Stage 4 run commit, no V2.1 or incumbent build, score, injection or
  descriptive scan may read an H board. The manifest builder may read only add-commit, hashes,
  `scrapeTimestamp` and completeness. If any lane is known to have used an H board for outlier,
  identity or source-integrity analysis, that use is logged in `DEVIATIONS.md` before Stage 4.
  Ordinary production use of the live board by other lanes is not an analysis of the held-out
  set.

**Earliest date the held-out set can be satisfied: 2026-11-25T00:00Z.** That is when the last
H_TARGET board exists, if no extension is needed. The wrong-player gate additionally needs U2, U2b,
U3 and VID live in the refresh before G1 (2026-11-04T00:00Z).

### 5.4 Stages (each a separate commit; the order is part of the registration)

| stage | content | may read |
|---|---|---|
| 0 | this preregistration, the O-1 record, `HELDOUT_RULE.json`, `POPULATIONS.json` | — |
| 1 | repairs R1–R14 and §3.4 behind default-OFF flags; V2-RPC; §9 property tests on synthetic rows; the Option-B fixture wired into the regression and integration tests (L3, §7.4); U1–U3 and VID through their own owners; DEV development | synthetic, DEV |
| 2 | **freeze**: `FROZEN_THRESHOLDS.json` plus the DEV selection evidence, and the evaluator code (gates, replay, metric and attribution scripts) frozen at the Stage 2 SHA | DEV |
| 3 | R constraints at frozen thresholds: §6 boards on pin2015 and pin0527; the cold-start safety gate on L1–L4; the labelled DEV cases; OFF-state byte identity; 24,024 identity parity; the full hard gate; frontend suite; performance and contract size on pin2015 | R, DEV, synthetic |
| 4 | **one** held-out run over H at one code SHA, with a clean tree, on or after the earliest-ready date; every record and result committed as produced | H |
| 5 | verdict (§11), independent fresh-context reviews, owner decision packet | all non-SPENT |

**Rules.** No threshold, rule or evaluator change after Stage 2. Stage 4 runs once. A rerun is
allowed only for an infrastructure failure (crash, incomplete record, hash mismatch) at the
**same** code SHA and thresholds, and the failed attempt is reported. A change to evaluator code
after Stage 4 records exist needs a `DEVIATIONS.md` entry **before** its output is read, and it caps
the verdict at MORE RESEARCH REQUIRED unless its outputs are byte-identical on every committed
Stage 4 result. Any decision-affecting code change after Stage 2 spends this registration.

## 6. Builds, records and the §6 comparison boards

Rebuild procedure, record schema (`oiv2-replay/v1`, extended with dataset content hashes, R-repair
stamps and persistence provenance) and pinned flags as V2 (V2 prereg §6), with these changes:

* **History lane for H.** Built in chronological order from H_BUFFER and H boards only, starting
  empty at the first H_BUFFER board, using V2.1's own decisions under P-1–P-4. The history lane is
  never fed from DEV, SPENT or R boards, so held-out ARRIVING history is the history a fresh
  production lane would have had.
* **History lane for DEV.** DEV boards only, chronological.
* **History lane for R pins.** The DEV-only lane as it stands after the last DEV board
  (2026-09-30). It is declared stale by about three weeks, because the boards between are SPENT and
  are never read. A stale baseline can only make B4 hold more, so a retention pass on it is the
  harder test.
* **Comparison boards** A, B, C, D, A′, B′, C′, D′, B″, C″ as V2 §6.1 (the D4 code is on `main`, so
  no D4 board is blocked), on pin2015 and pin0527 (Stage 3) and, for A / C / C″ / D, on every
  H_ORIGIN board (Stage 4). pinOB is built at A with `source_freshness_schedule_v2` OFF and ON, and
  at D with it OFF and ON. Focus rows as V2, plus LaJohntay Wester, Dee Alford, James Pierre, Kyle
  Dugger and Josh Cameron.

## 7. Gates and injection protocols

Built through the replay harness with the **complete layered system** (A + B + C + history), as
directive §5 requires. Corrupted observations are injected **before** Layer A, so identity
evidence, provenance stamps and CSV copies travel with the injected observation exactly as the
case defines. V2's post-pricing seam (T4) is retired for every case except AD1/AD4. Those
injections change a value, not an identity, so they still enter after pricing and before every
integrity layer. Source rows: every row with ≥ 3 voting families on the gate board. **Material**
and **pass** are defined as in V2 §7. Gate seed **2034**.

### 7.1 History variants

| variant | history lane state for the corrupted source | status |
|---|---|---|
| **ARRIVING** | the source's real, clean, content-distinct observations from the H_BUFFER and H boards before the gate board (P-1–P-4) | **gate of record** (owner O-1) |
| **NO-HISTORY** | empty for every source | reported (every gate); the variant of the cold-start safety gate (§7.4) and of criterion 8's cold-start half |
| **PERSISTENT** | the same corruption also injected into the 3 prior content-distinct datasets | **required run**, reported with the P-5 mechanism breakdown and §9 property 18 |

### 7.2 Gate of record (ARRIVING; on G1 **and** G2; both must pass)

Thresholds are the directive's §5 table, unchanged:

| id | corruption | bar |
|---|---|---|
| AD1a | one vote ×5 (cap 9,999) | ≥ 90% |
| AD1b | one vote ×0.2 | ≥ 90% |
| AD1c | one vote ×20 (cap) | ≥ 95% |
| AD1d | one vote ×0.05 (floor 1) | ≥ 95% |
| AD4 | single-source spike: consensus rank 150–400, one vote set to 9,000 | ≥ 95% |
| **wrong player** | **AD2 as registered** (the vote replaced by the same source's vote for a player ≥ 100 consensus ranks away, no identity evidence), unless the owner records O-2 before the Stage 4 commit, in which case **AD2-ID** | ≥ 90%; **evaluable only under P-ID (§3.7)**, otherwise BLOCKED |
| AD3 | 4 sources (dynastyNerdsSfTep, flockFantasySf, fantasyCalc offense; fantasyProsIdp IDP) × {ranks ×2, ranks ×5, values ×0.01, order reversed within the covered rows} | 16 / 16 boards flagged before voting |

### 7.3 Further mandatory gates and required runs

| id | definition | requirement |
|---|---|---|
| **AD2-N** | a real Sleeper same-group homonym pair | **must be refused, never attributed: 100%** (mandatory gate; V2 skipped it) |
| **AD2-ID** | the swapped entry carries the swapped player's own published non-name fields (position, team, age, ids, U2/U3 stamps as that source publishes them), with its name forced to the target's canonical name | **required run**; reported overall and with name-only sources separately; the wrong-player gate if O-2 is recorded |
| **AD2-SUR** | a surname-rung capture with its U2 page position and rung | **required run**, reported |
| **INJ-DUP** | synthetic rows with identical translated values from different boards, end to end through the replay | **required run**; the duplicate property holds (no band narrows, no provider merged): mandatory |
| **INJ-H1** | on every H_ORIGIN board, the rookie-ladder reference marked inactive | 100% of dlfRookieSf, flockFantasySfRookies and dlfRookieIdp votes withheld; 0 fires on unmodified boards: mandatory |
| **INJ-SEG** | a value-direct payload source: 70% of payload rows given per-position shifts of random sign, \|0.1–0.3\| log; the CSV keeps the true values | B2 board proof on 100% of injected H_ORIGIN boards (R14 reading): mandatory |
| **NO-HISTORY gates** | §7.2 rerun under NO-HISTORY on G1 and G2 | **required run**; reported, not a gate |
| **PERSISTENT** | §7.2 rerun under PERSISTENT on G1 and G2 | **required run**; reported with P-5 |
| **V2-RPC** | every §7.2 case and the H_ORIGIN metrics with V2-RPC | **required run**; reported comparator |
| **V2** | every §7.2 case with V2 at its frozen thresholds | reported comparator |

The incumbent's, V1's and V2's rates on the same fixtures, by family count (3, 4–5, ≥ 6), are
reported beside V2.1's. **A required run that is not run fails criterion 4.**

### 7.4 Cold-start safety gate (mandatory; owner O-1)

**Requirement.** With no history, V2.1 drops **zero** legitimate votes on the registered
legitimate set L.

**Variant.** V2.1-NOHIST: the primary configuration (§3.8) at the frozen thresholds, the full
layered system, the history lane empty for every source.

**Registered legitimate set L:**

| part | content | boards and builds |
|---|---|---|
| **L1** | the 31 IDP votes of `outlier_integrity_v2/manifests/REGRESSION_SET.json` (Draft Sharks 18, FantasyPros 10, IDPTC 3) | boards C and C″ on pin2015 and pin0527: 124 vote-instances |
| **L2** | the D4 set of `outlier_integrity_v2/r_constraints/D4_REGRESSION_SET.json` (20 votes per pin), plus Theo Johnson's frozen-panel Draft Sharks vote (3182) | boards C′ and C″ on pin2015 and pin0527, and the frozen panel test |
| **L3** | the Option-B freshness rows of `tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json`: on its 31 rows, every vote the incumbent excludes in either freshness state (27 flag-OFF + 23 flag-ON = 50 vote-instances, 39 distinct player-source pairs: Wester's Flock vote, the Draft Sharks, KTC Crowd, FantasyCalc, OTC, PFK, Yahoo/Boone, DLF, Dynasty Nerds, FantasyPros Fitzmaurice, IDPTC and Navigator exclusions) **and** every other vote that votes on those rows | pinOB at D with `source_freshness_schedule_v2` OFF and ON |
| **L4** | the labelled controls on DEV: every vote on the H4 boards (2026-08-03 and 2026-08-06) except the H3 row; every vote on the N1, N2, N3 and N5 boards; the N4 rule (Yahoo/Boone zero values never read as a value) and the N6 rule (no hard quarantine of an N6-listed source's votes) on every DEV board; excluding only votes inside a labelled positive's scope (H1 untranslated votes, the H3 row) | DEV boards at A-equivalent flags |

**Measurement.** A vote-instance in L is **dropped** if any V2.1 layer excludes it from the blend:
an A CONTRADICTED or UNRESOLVED refusal, a B0 or B3 hard quarantine, a B1 withhold, a B2
replacement or withhold, a B4 hold (which should be impossible without history; counted if it
happens), or a Layer C drop. Not counted, because V2.1 does not own them: existing policy holds,
freshness exclusions, the declared-range check and non-positive values. **Pass iff the dropped
count is 0 on each of L1, L2, L3 and L4**, each reported separately with the build, the vote, its
source and value, and the layer and reason of any drop.

A drop counts as legitimate unless it carries a deterministic contradiction (A1, A2 or A3, or a B0,
B1 or B2 proof) **and** an independent reviewer verifies the invalidity from the archive. Each
such case is then listed individually as new evidence of an invalid observation. No other
exemption exists. Also required: **0** L vote-instances labelled with an invalid §10 category
(R7).

L3 also asserts that LaJohntay Wester's Flock vote votes and is stamped `kept_dissent`; that Dee
Alford, James Pierre and Kyle Dugger remain unpriced (`null`, never 0) under freshness v2 ON and
keep their flag-OFF votes under OFF; and that Chris Moore and Jawhar Jordan stay priced when their
Navigator vote starts.

## 8. Labelled historical cases (DEV and synthetic only)

| case | required V2.1 outcome |
|---|---|
| H1, 22 E_DEV rookie boards | withheld by B1 on 22 / 22; 0 fires where the ladder exists |
| H3, 2026-08-03 (E_BASELINE) | Justin Jefferson's payload vote excluded or replaced by the CSV value |
| H4, 2026-08-03 and 2026-08-06 | no value quarantined except the H3 row |
| **H2-SYN** | a synthetic reconstruction of the H2 mechanism from V2's committed summary (per-group m_g: QB about −0.15 log, RB/WR/TE/IDP +0.17 to +0.21; 391–423 overlapping rows; healthy-capture m_g = 0.000) | B2 board proof under R14; no proof on the healthy-capture twin |
| H5 | reported separately, never in hard metrics |
| H6 | A4 (R9) refusal rate reported with a false-refusal audit |
| N1–N5 | no hard quarantine (part of L4) |

H2 and the October H3 rows sit on SPENT boards. They are not re-evaluated, and V2's record of them
stands.

## 9. Correctness properties (unit and property tests; offense and IDP; all mandatory)

V2's properties 1–17 (V2 prereg §9), unchanged, plus:

18. **No self-confirmation** (§3.4): persistence and B4 baselines count each vendor dataset content
    hash at most once; refused, held, withheld, quarantined and B4-held observations never count;
    a `released_by_cap` vote is not an accepted observation until P-3's release conditions hold.
19. **Ordinal slot** (R6): refusing one entry leaves every other entry's effective rank and vote
    value byte-identical.
20. **Cold-start properties**: with an empty history lane, a team-only mismatch votes (R8); an
    integer-versus-decimal age within one year votes (R5); B4 never holds; and for every
    regression panel of L1–L3, Layer C's decision does not depend on whether DLF is present.
21. **B0 tolerance** (R1): rounding-scale inversions and ties never quarantine; a reversed board
    always does.
22. **Small segments** (R2, R3): B3a and B3b abstain below their minimums, whatever the shift.
23. **Family compatibility** (R4): every pair in the table behaves as registered, both ways.
24. **Explainer coverage** (R7): every exclusion in a built contract appears in the per-player
    explainer with exactly one §10 category through `voting_status.py`.
25. **Byte-identical upstream changes**: U1, U2, U2b, U3 and VID with every V2.1 flag OFF leave the
    default board byte-identical.

## 10. Metrics

As V2 §10 (M1, M3, M4, M5/M6, clean-board false exclusions, board-level false positives,
performance), with these changes:

* **Populations.** M1 origins are H_ORIGIN; targets are H_ORIGIN ∪ H_TARGET. h = 7, 7-day blocks,
  4,000 resamples, seed 2034. Minimum: ≥ 300 V2.1-disputed units from ≥ 10 origin days covering
  ≥ 4 week-blocks, otherwise INSUFFICIENT. M4 runs on consecutive H_ORIGIN days.
* **Clean-board false exclusions** are counted under **both** ARRIVING and NO-HISTORY.
* **Attribution.** Every H_ORIGIN row moving ≥ 10% (V2.1 vs incumbent) is attributed to a named
  vote change: the vote, the layer and the reason. Rows that switch between priced and unpriced are
  included. Derived and tethered picks are attributed through their tether or derivation source.
  No unregistered exemption is allowed (reviewers 3 #2 and 4 #7).
* **Performance.** Sequential, same machine, median of 5 warm builds; V2.1-ON wall time and peak RSS
  against the incumbent build on pin2015 (Stage 3) and on G2 (Stage 4).
* **Contract size.** The full contract serialized as the export writes it, its gzip, and the
  rankings-overrides delta view, V2.1-ON against the incumbent, on pin2015 and G2.

## 11. Acceptance criteria scorecard (all mandatory)

| # | criterion | pass condition |
|---|---|---|
| 1 | Gate of record (§7.2) | ARRIVING, on G1 **and** G2: AD1a ≥ 90%, AD1b ≥ 90%, AD1c ≥ 95%, AD1d ≥ 95%, AD4 ≥ 95%, wrong player ≥ 90%, AD3 16 / 16 |
| 2 | Mandatory structural gates (§7.3) | AD2-N 100%; INJ-H1 100% with 0 fires; INJ-SEG 100%; INJ-DUP property holds |
| 3 | **Cold-start safety** (§7.4) | 0 legitimate votes dropped on each of L1, L2, L3 and L4 under NO-HISTORY; 0 labelled invalid |
| 4 | Required runs (§7.3) | NO-HISTORY gates, PERSISTENT with P-5, AD2-ID, AD2-SUR, INJ-DUP and V2-RPC all run and reported |
| 5 | Identity prerequisites (§3.7) | U2, U2b, U3 and VID live and stamped on G1 and G2; otherwise BLOCKED |
| 6 | Regression retention | under NO-HISTORY **and** under the R-pin history lane (§6): all 31 IDP votes retained in C and C″ on pin2015 and pin0527; the D4 set in C′ and C″; Theo Johnson's panel case; the L3 assertions |
| 7 | Labelled cases (§8) | H1 22 / 22; H3 (2026-08-03); H4; H2-SYN; N1–N5 clean |
| 8 | False exclusions | clean-board false exclusions ≤ 0.5% of voting observations on every clean H_ORIGIN board, under ARRIVING **and** under NO-HISTORY; 0 board-level false positives |
| 9 | Accuracy and stability | M1 meets the minimum sample with P1 upper95 ≤ +0.005; M4 ratio upper95 ≤ 1.10 |
| 10 | Attribution | every H_ORIGIN row moving ≥ 10% attributed to a named vote change (§10), no exemptions |
| 11 | OFF state and existing tests | every new flag OFF → default board byte-identical to the base (`golden_board` + `board_diff --expect-no-value-change`); `CONTRACT_CSV_JOIN_V1` 24,024 / 24,024 parity; V1 OFF and its tests unchanged; full pytest hard gate, frontend suite, API contract structural lane and all hold-lock tests (`test_dlf_idp_hold_locked`, `test_dlf_values_hold_locked`, `test_freshness_v2_hold_locked`) pass at the Stage 4 code SHA |
| 12 | Properties | §9 properties 1–25 pass at the Stage 4 code SHA |
| 13 | **Performance** | V2.1-ON build wall time ≤ **1.25×** the incumbent build on pin2015 **and** on G2; peak RSS ≤ incumbent + 50 MB |
| 14 | **Contract-size budget** | V2.1-ON full contract ≤ **1.02×** the incumbent's bytes, gzip ≤ 1.02×, and rankings-overrides delta ≤ 1.02×, on pin2015 and G2 |
| 15 | Transparency | 100% of exclusions in the per-player explainer with one §10 category through `voting_status.py`; 0 votes that passed A and B shown as invalid |
| 16 | Selection | no FAILED_SELECTION in Stage 2 |
| 17 | Process | the held-out seal intact; no unlogged deviation; no deviation that loosens a gate; evaluator frozen at Stage 2; no decision-affecting change after Stage 2 |
| 18 | Independent review | at least four fresh-context reviewers (algorithm and preregistration fidelity; identity and provenance; historical methodology and evidence integrity; performance, integration and transparency) each return `ok: true` |

### 11.1 Verdict (exactly one, per directive §13 H)

| verdict | rule |
|---|---|
| **READY FOR APPROVAL** | **every** criterion 1–18 passes **and** every independent reviewer returns `ok: true` |
| **MORE RESEARCH REQUIRED** | any criterion fails, M1 is INSUFFICIENT, the minimum held-out sample is not met after extension, a FAILED_SELECTION is recorded, or a decision-affecting change followed Stage 2 |
| **BLOCKED** | the evaluation cannot be completed for a reason outside the lane: P-ID not live on G1 or G2, an H board unrecoverable or hash-mismatched, or evidence that exists only on the production server |

A failure never becomes an activation recommendation. Rates below a bar are reported as failures,
never relabelled.

## 12. Owner decisions

| id | question | state |
|---|---|---|
| **O-1** | gate on ARRIVING instead of NO-HISTORY | **DECIDED 2026-10-20**: ARRIVING is the gate of record; NO-HISTORY reported; cold-start safety mandatory; wrong-player and wrong-scale gates must pass |
| **O-2** | gate wrong-player on AD2-ID instead of AD2 as registered | **OPEN.** Default: AD2 as registered. To count, it must be recorded in the repository before the Stage 4 run commit and blind to held-out results. AD2 as registered strips every identity field by construction, so upstream evidence (§3.7) cannot help it, and V2 reached only 48.8% on it under ARRIVING |
| O-3 / O-4 / O-5 | activation of `payload_provenance_guard`, `rookie_ladder_fail_closed`, D-1 | activation decisions only (§15) |

## 13. Expected results and failure modes (stated in advance, not evidence)

* **Cold-start safety.** Expected to pass on L1–L3 (V2 kept all 31 votes and the D4 set on the pins;
  the F1 holds, the age refusals and the B0 refusals are repaired). L4 is the risk: R4's family
  rule may refuse a real reclassification the allowed-drift table does not cover.
* **ARRIVING gates.** AD1a–d and AD4 expected at about V2's ARRIVING rates (95–100%), since B4 does
  most of the catching and P-1 may slightly reduce baseline depth. AD3 expected 12–16 / 16
  (uncertain): ranks ×2 and values ×0.01 on thin segments may fall below the R2/R3 minimums.
* **Wrong player.** AD2 as registered expected **below 90%** (V2 ARRIVING 48.8%). AD2-ID expected to
  improve with R4 and U3, and still to miss on boards that publish neither position nor team. AD2-N
  expected 100%.
* **Performance and size** are uncertain; R13 is engineering, not a guarantee.
* **Expected verdict: MORE RESEARCH REQUIRED** unless the owner records O-2 and AD2-ID clears 90%.
  BLOCKED if U2/U3/VID are not live in the refresh by 2026-11-04.

Failure modes stated in advance: name-only boards without U3 defeat Layer A; P-3 lets a persistent
corruption vote after the cap (flagged, never silent); correlated multi-source anomalies stay
undetectable; holds delay the first mover on real news by one fetch; a short or degraded refresh
period extends the window; B2 cannot fire when one broken fetch corrupts both copies.

## 14. Rollback

Every V2.1 flag defaults OFF. Rollback means every flag OFF and a restart, because flags are read
once per process. The disabled state is the byte-identical incumbent board (criterion 11). The
history lane is record-only and can be left in place or deleted without affecting values. U1–U3
and VID are stamps or lookups only.

## 15. Activation (owner-reserved)

* There is no activation recommendation unless the verdict is READY FOR APPROVAL.
* Even then, activating `outlier_integrity_v2` or any sub-flag needs the owner's explicit approval.
  Activation must fail closed on a readiness check of the history lane. It starts in cold start,
  which is what criterion 3 protects.
* DLF IDP and DLF Rookie IDP (`dlf_offense_only_vote` OFF), D4 (`dlf_values_rank_hill_vote` ON)
  and freshness v2 (`source_freshness_schedule_v2` ON) remain held until separate owner
  approvals. The combined shadow impact analysis with DLF voting and freshness v2 (Option B item 7,
  intake FS-B6) runs only after V2.1 is validated.
* Nothing in this lane merges, deploys, flips a production default or dispatches a release
  candidate.

## 16. Deviations, reruns and held-out discipline

* Any departure from this document is logged in `outlier_integrity_v21/DEVIATIONS.md`, with the
  original text, the change, the reason and the commit, **before** any result that depends on it is
  read. Logging a change as a "clarification" does not exempt it. A deviation that loosens any
  criterion makes READY FOR APPROVAL unreachable.
* H is evaluated once (Stage 4). No threshold, rule, variant or evaluator change is chosen after
  looking at it. SPENT boards are never read.
* Original evidence (V1's and V2's records, the archives, the frozen manifests) is never rewritten.

## 17. Sensitivities (report only)

V2's S1–S8 restricted to non-SPENT populations, plus: S9, V2.1 with each repair R1–R14 reverted in
turn; S10, P-1–P-4 off (V2 persistence semantics) under PERSISTENT; S11, the ARRIVING history lane
seeded from DEV as well as H (to show how much the cold start of the H lane matters).
