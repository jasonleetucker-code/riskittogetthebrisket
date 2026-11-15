# Outlier integrity v2: deviations and implementation clarifications

Required by the preregistration (`../OUTLIER_INTEGRITY_V2_PREREGISTRATION.md` §16): every
departure from the registered text is logged here, with the original rule, the change,
the reason and the commit, **before** any result that depends on it is read.

Agent-OS-Receipt: cb64f74cf4d2763aa16d55ba0d6350f585a2a42f

## Status at Stage 1 (Layers A + B implemented behind default-OFF flags)

**No acceptance criterion, gate, population, seed or metric has changed.** Nothing below
was chosen by looking at a V_HELDOUT, I_INDEPENDENT or R_REGRESSION_PIN board. The only
boards read with any V2 flag ON during Stage 1 were exploratory: E_DEV
`dynasty_export_20260818_230211` through `_20260823_230044` and `_20260930_130404`, and
E_BASELINE `_20260803_235610` and `_20260806_150742` (the H3/H4 control boards). The
selectable thresholds are NOT frozen yet (Stage 2); `config/sources/outlier_integrity_v2.json`
holds the most conservative point of each registered grid, with `status:
provisional_stage1`.

The registration leaves some implementation details open. Each choice made in Stage 1 is
recorded as a clarification. **C4 and C5 refuse fewer observations than the most literal
reading of the registered sentence would**, so they are flagged for the independent
reviewer; neither changes a gate, and both were found on exploratory boards.

| id | registered text | implementation | reason |
|---|---|---|---|
| C1 | §3: "every non-pick vote v maps to u = ln(10 + 500·p) … on the row's scope master … For rank-signal sources the effective-rank percentile is used directly." | Every vote, rank-signal or value-direct, is placed with V1's `outlier_policy.rank_coordinate` on the vote value the blend uses, on the row's scope master (`source_integrity.vote_coordinate`). | One coordinate for every vote on a row. It equals the effective-rank percentile wherever the rank's pool curve is the scope master and no TE transform applied; on TE rows (TE basis lift) and cross-pool rank votes the percentile form would place two votes of one row on different scales. B3 compares a source with its own history and B4 a vote with its own history, so a static offset cancels either way. |
| C2 | §3.2 B3b: "any smaller shift → kept + `segment_break_unproven` + advisory" | A sub-gross shift is noted only from `ln 1.25` (the registered B3a floor, `B3_SHIFT_FLOOR`). | Read literally, every segment of every board carries some non-zero shift and would always be advised; the floor is the registration's own a-priori constant for "a shift worth naming". |
| C3 | §3.2 B3: "leave-source-out reference" (no minimum stated) | The reference needs at least 2 other providers on the row (`B3_MIN_REFERENCE_PROVIDERS`), mirroring V1's `MIN_OTHER_FAMILIES`. | A one-provider "consensus" is that provider's opinion; the same minimum V1 used for its board screen. |
| C4 | §3.1 A4: "two entries of one source collapse on one key without disambiguating id / position / team (both refused; replaces 'keep the higher value')" | Disambiguation narrows by Sleeper id, position group, position FAMILY (DL / LB drift allowed), then team. Survivors that publish the SAME team and compatible positions are treated as ONE person listed twice and keep the join's choice; survivors with no team or conflicting evidence are refused. | Measured on E_DEV `20260930_130404`: FantasyPros IDP lists 15 edge rushers on both its DL and LB pages (same name, same team). They are one person each; refusing them is an observation-selection question presented as an identity refusal, and would remove legitimate FantasyPros IDP votes. Two people on one key (Byron Murphy II, DT SEA / Byron Murphy Jr., CB MIN) are still split by their own published position, and indistinguishable name-only entries (Flock "Cole Payton") are still refused. |
| C5 | §3.1 A1: "Sleeper / vendor id resolves to a different canonical player" | A1 fires only when the source's Sleeper id belongs to a DIFFERENT row of the board being built. An id that resolves to nobody is no evidence. | Measured on E_DEV `20260930_130404`: Dynasty Nerds published Sleeper ids that resolve to no player for four correctly named, correctly teamed players (Zay Flowers 8133 vs 9997, …). Refusing them would punish a vendor id column for a correct observation. This is the registered wording ("resolves to"); the existing `refuse_sid_contradiction` guard is stricter and is unchanged. |
| C6 | §3.2 B4: "τ_c(source, depth band)" (band basis not stated) | The band is read from the implied rank of the source's own prior-history median (`exp(u) − 10`), never from the new observation. | The band should not be chosen by the very value being judged. |
| C7 | Architecture §3: "U4: record-only `source_rank` lane in `src/history`" | `src/history/source_rank.py`: an append-only `records.jsonl` plus an atomically replaced folded `state.json` under `data/history/source_rank/` (gitignored). Not a new lane in `data/temporal_ledger.sqlite`. | That ledger's lane set (`store.VALID_LANES`) is a production-wide schema; this lane holds a folded per-source state, not per-asset observations. Same owner package, no migration. Recording is gated by `source_rank_history_record`; a build reads only a state strictly older than the board. |
| C8 | §3.2 B2: "per position group m_g"; "on proof: proven payload values are absent" | Groups are QB / RB / WR / TE / DL / LB / DB / PICK (and OTHER for a row with no position). A board proof makes EVERY payload value of that source on that board absent (the vendor's CSV value votes where it exists); a row proof only that row. | A board proof says the capture is broken, not only the groups that cleared the statistic. Picks are in the same payload. |
| C9 | §3.6 / O-5: D-1 "held and unresolved votes become B11 lost-evidence seats" | D-1 (`integrity_holds_as_withheld`) seats B4 holds. A Layer A refusal (incl. UNRESOLVED) happens before ranking: the observation never receives a rank or a vote value, so there is nothing to seat. | Seating a refused observation would require pricing it, i.e. inventing its rank. Recorded as an open item for the V2+D1 comparator; D-1 stays a separate, owner-reserved evaluation. |
| C10 | §3.2 B0: "vendor rank-vs-value Spearman ≠ −1" | Implemented as "at least one row whose value exceeds the value of a strictly better-ranked row" (zero discordance). | Exactly Spearman −1 on a tie-free board, and tie-tolerant: equal values at different ranks (or one rank shared) are not a format error. Non-positive values are never read (DLF / Yahoo blanks). |
| C11 | §3.2 / §6: "accepted observations" | Accepted = passed Layers A and B (not refused, withheld, quarantined or held). A Layer C drop does not make an observation unaccepted. | Layer C's persistence rule needs a contrarian's history to accumulate; C is not an integrity verdict. |
| C12 | §4.5: "an unrecorded provider fails closed" | An unrecorded provider is mapped onto the source's B10 family (`data_contract._integrity_provider_of`), never treated as an independent provider of its own. Every registered voter has a recorded provider today. | Fail closed = never split. |
| C13 | §3.1: "team-only mismatch with no continuity in the source's own history" | Continuity = the history lane's team on the source's last ACCEPTED observation of this player equals the team the source publishes now (the row's team moved, the vendor lags). With no history there is no continuity and the vote is held, exactly as registered. | Measured on E_DEV `20260930_130404`: J.J. McCarthy (row NYG, FantasyPros Fitzmaurice MIN) is held without history. A player whose team was already mismatched when the lane started stays held until the vendor updates, because a held observation never enters the accepted history; a mismatch that begins after the lane recorded the vendor's matching team is released. |
| C14 | §3.1: "rookie-board entry outside that board's class" | Contradicted only when the row's NFL experience is KNOWN and above zero and the row is not flagged rookie. | Unknown experience is no evidence. |

## Not implemented in Stage 1 (named, not papered over)

* **U2 / U2b** (scraper stamps of matching rung, page position, acquisition path and the
  SF / TEP toggle state on payload captures) and **U3** (position and team captured on
  name-only boards) — scraper-side changes in `Dynasty Scraper.py`. Without them, Layer A
  cannot judge payload-attached values (the scraper's own join) or name-only boards; B2's
  `format_toggle_off` input is always `False`. The prereg's §3.6 already states that a
  missing stamp is absent evidence, never inferred.
* **Vendor-id → player mapping on the board path.** `src/sources/ktc_identity` needs the
  vendor page; A1's vendor-id branch therefore abstains (`vendor_id_resolver=None`).
* **Layer C** and the dispatcher feeding every filter call site — outside this unit.
* **`src/sources/voting_status.py`** (PR #1831) is not on `main`; the reason codes and
  their §10 categories live in `src/api/source_integrity.py` (`REASON_CATEGORY`) for that
  module to map when it lands.
* **B2 supporting evidence** "payload count < 0.6 × trailing-5 median" needs a payload-count
  history that is not recorded yet; supporting evidence is recorded only as counts and is
  never sufficient, as registered.

## Status at Stage 1, second unit (Layer C, Layer D wiring, transparency)

Same rules as above: **no acceptance criterion, gate, population, seed or metric has
changed**, and nothing below was chosen by looking at a V_HELDOUT, I_INDEPENDENT or
R_REGRESSION_PIN board. The only board built with Layer C on was E_DEV
`dynasty_export_20260930_130404` (a development smoke: 0 Layer C drops at the provisional
`tau_C`, 146 incumbent drops not made, 36 votes stamped `kept_dissent`). Before Layer C
was written, `origin/main` was merged into the branch (merge `cf88b11783`), because PR
#1817 had landed `_two_way_alt_center` (the second filter call site) and the D4 code.

| id | registered text | implementation | reason |
|---|---|---|---|
| C15 | §3.3 guard 4: "≥ 2 consecutive accepted observations of this source for this player within τ_c of u_o" | The last two entries of the source's accepted-observation window, each within `tau_c` of `u_o`, where `tau_c` is the source's B4 threshold for the band of its own prior median. While the `tau_c` table is empty (before Stage 2) the registered floor `ln 1.5` is used. | The floor is the smallest value any frozen `tau_c` can take (`tau_c = max(ln 1.5, …)`), so it never exempts a vote that a frozen threshold would not. No history = not confirmed (the registered cold-start rule). |
| C16 | Architecture §3: "PR #1817's `_two_way_alt_center` … routes through the V2 dispatcher" | `_two_way_alt_center` takes an `outlier_filter`; with V2 on it is Layer C on the alt family's scope curve, with the alt votes' own family-capped weights, **no translation lineage and no persistence history** (cold start). | An alt-family panel has no row-level translation metadata and no player history of its own; inventing either would be guessing. Cold start without lineage is the stricter reading for a vote and the looser one for a reference pair; it is recorded so the reviewer can weigh it. Travis Hunter is the only row it reaches. |
| C17 | §3.3 guard 1: "≥ 3 providers on the row" | Layer C is asked on every non-pick row with ≥ 2 votes; guard 1 is enforced inside the rule. | Rows with two providers can still carry a `kept_dissent` stamp (transparency); no drop is possible below three providers. |
| C18 | §3.3: "Remove vote o" (stamp shape not stated) | A Layer C drop keeps the incumbent filter's existing shape (`hampelDropped: true`, `droppedSources`), plus `integrity = {status: rejected_tail, primaryReason: extreme_uncorroborated_tail, category: rejected_by_integrity_rule, layerC: {...}}` and `row.outlierIntegrityReasons`. Kept dissent stays `status: voting` with primary reason `kept_dissent`. | Every existing consumer of a filter drop (confidence evidence, census, explainers, B11 seats) reads it unchanged, so Layer D sees a C drop exactly as it sees an incumbent drop today (§3.4: "behave like today's filter drops"). |
| C19 | §3.3 guard 2: "≥ 2 providers other than o's, each within ln 2 of another of them, not formed solely by a translated vote and its own declared translation backbone" | Satisfied iff two votes of two different providers (neither o's) lie within `ln 2` of each other and are not lineage-linked. Lineage: a vote stamped `sharedMarketTranslated` is linked to every key of the bridges that seeded the build's shared-market ladder (`bridge_ladder.contributors`); a `rookie_ladder_translation_*` vote to its `ROOKIE_LADDER_PAIRS` reference; a coverage-aligned family vote to its `levelSource`. Compared at provider level. | "Each within ln 2 of another" is satisfiable iff such a pair exists. Lineage is read only from declared, stamped provenance -- never from numerical similarity -- and can only remove a reference, i.e. only reduce drops. Two translated votes of different providers (FantasyPros IDP, DLF IDP) are independent ordinals and do form a reference. |
| C20 | §3.3 guard 5: "o's family holds < 0.5 of the row's family-capped weight" | Weights are the row's freshness/health-adjusted weights passed through the existing `cap_family_weights`. In the B11 lost-evidence replay, a withheld observation (weight 0 on the row) is seated at its base registry weight. | The replay asks "what would the panel have decided while the source still voted", so the withheld source is weighed as a voter. The cap owner is consumed, never changed. |
| C21 | §3.5: `tau_C` selected on E_DEV from {ln 4, ln 5, ln 6} | Provisional `tau_C = ln 6` in `config/sources/outlier_integrity_v2.json` until the Stage 2 freeze. | The largest registered grid point (fewest drops), consistent with the other provisional constants. |
| C22 | Architecture §3 / §9: reason codes "added to PR #1831's `src/sources/voting_status.py`" | #1831 is still not on `main`. The codes and categories stay in `source_integrity.REASON_CATEGORY`; the contract carries `sourceIntegrity.votingCategories` (per source: observation counts by §10 category and by primary reason, plus the source-level state from the existing `sourceVotingEligibility`). The frontend's one source-voting label module (`frontend/lib/source-voting-status.js`, #1846) labels the categories; the per-row explainer shows them. | Coordinate, never fork: when #1831 lands, its `_row_tallies` already keys not-voting rows by `excludedReason` / `outlier_filter`, and the frontend label map resolves every V2 code by prefix. |

Layer D: `src/api/confidence.py` and `config/confidence/gate_v1.json` are byte-identical to
`main` (pinned by test). The only confidence-relevant wiring is §3.4's: the B11
lost-evidence replay asks Layer C through the same per-row context as the vote (one
dispatcher), and D-1 (`integrity_holds_as_withheld`) is unchanged and separately evaluated.

### Not implemented in this unit (named)

* **Stage 2 threshold freeze** (`FROZEN_THRESHOLDS.json`), **Stage 3** R constraints and the
  §6 comparison boards (A–D, A′–D′, B″–C″, now buildable because D4 code is on the branch),
  the regression-set tests on the 31 IDP votes and the D4 set (they are R data; the
  registration orders them after the freeze), and every V / I evaluation.
* **Performance (criterion 11)**: on E_DEV `20260930_130404`, warm builds measured
  ~1.6–1.8x the incumbent build with V2 on (Layer C itself ~0.05 s of ~1.6 s; the rest is
  Layers A/B: identity grading, the evidence re-parse and the segment screen's snapshot
  copy). Criterion 11 (≤ 1.25x) currently fails and is open.

## Test-matrix unit (recorded before any R or gate result was read)

**No acceptance criterion, gate, bar, population, seed or metric has changed, and no
threshold was selected or moved.** `config/sources/outlier_integrity_v2.json` is untouched
(still `provisional_stage1`). Logged here, as §16 requires, before the results that depend
on them were read.

| id | registered text | what this unit does | reason / why it loosens nothing |
|---|---|---|---|
| T1 | §5.3: Stage 3 (R constraints, §6 boards, regression membership) follows the Stage 2 threshold freeze | The R constraint checks (the 31 IDP votes, the D4 set, the focus rows, boards A–D / A′–C″, determinism) are executed on pin2015 and pin0527 **before** Stage 2, at the coordinator's request. | Ordering only. To keep R from informing selection: (a) the frozen-panel regression tests assert retention at **every** registered `tau_C` grid point (ln 4, ln 5, ln 6), so no Stage 2 choice can be steered by them; (b) the §3.5 selection rules read E only and are not touched; (c) every R result is a must-pass constraint, never evidence (§5.1). The full-pipeline R builds run at the provisional thresholds and under NO-HISTORY (B4 and B3a abstain; persistence never confirms), and are reported as such — they must be re-run at Stage 3 proper on the frozen thresholds. |
| T2 | §5.3 Stage 3: "D4 regression membership committed" into the regression set | Membership is computed by the registered rule (`REGRESSION_SET.json` → `d4.definition`) on pin2015 and committed as a separate file under `outlier_integrity_v2/r_constraints/`, never into `manifests/` (whose bytes are frozen and `--check`ed). | The frozen manifest stays byte-identical; the rule, not a hand list, decides membership. |
| T3 | §7: gates are built on the registered V gate board (Stage 4) and the newest I board (Stage 5) | The full-pipeline gate harness (`src/robust_filter_shadow/oiv2_gates.py`, `scripts/oiv2_gates.py`) is run only on the E_DEV board `dynasty_export_20260930_130404` (already the Stage 1 development board) as a **development run, not the gate of record**. The script refuses V / I / R boards unless `--stage4-gate-of-record`, which itself needs frozen thresholds and a clean tree. | Held-out data stays unread. Development seed: the registered gate seed 2033 is used on the E board (the selection seed 20261020 is reserved for Stage 2). |
| T4 | §7: "the complete layered system (A + B + C + history)" | The harness injects each corrupted observation through a replay-only seam (`data_contract._ADVERSARIAL_VOTE_TRANSFORM`, `None` in serving) after the vote is priced and before every integrity layer, filter, cap and blend. Layer A, B0 and B2 therefore have no signature to read by construction (a correctly formatted, correctly attributed number on which payload and CSV agree): the worst case for V2. AD3's transform is applied to priced votes (as V1's `_reprice`), because an input-level uniform rank rescaling is a no-op under dense re-ranking (V1 §4 E1). | Stated per gate in the harness docstring. It can only make a gate harder to pass, never easier. ARRIVING / PERSISTENT history variants are not run in this unit (NO-HISTORY is the gate of record, §7.1). |

## Stage 2 and replay unit (recorded before any Stage 2 input, R, V or I result was read)

**No acceptance criterion, gate, bar, population, seed, grid or selection rule has
changed.** The rows below fix how the registered selection rules (§3.5) and the
replay (§6, §7, §10) are executed where the registration leaves a detail open. They
were written before `scripts/oiv2_replay.py collect-e` produced its first record.
Driver: `scripts/oiv2_replay.py`; library: `src/robust_filter_shadow/oiv2_replay.py`
(read-only recorders around Layer C's `LayerCContext.assess` and Layer A's
`assess_identity_evidence`, which call the originals unchanged).

| id | registered text | execution | why it loosens nothing |
|---|---|---|---|
| S1 | §6: history lane "degraded sources excluded" | On the 35 E_BASELINE boards the degraded run sources are `KTC_TradeDB` / `KTC_WaiverDB` (critical primary `KTC`); every `ktc*` source key's observations, hashes and segment medians are left out of those boards' history records (`oiv2_replay.degraded_filter`). No other manifest board is degraded. | Less history can only make B3/B4/persistence abstain more. |
| S2 | §6: history "all manifest boards up to but excluding the evaluated board" | Chain = E_BASELINE → E_DEV → V_HELDOUT → I_INDEPENDENT in add-commit time order. EXCLUDED (V1's diagnosis board) and the R pins are not in the chain (they are not chronological archive boards of the evaluated populations). | — |
| S3 | §3.5 τ_age: "0 CONTRADICTED verdicts on Sleeper-id-verified joins over E_DEV" | Counted over every Layer A join on the 44 E_DEV boards (chained V2 build) whose entry and row both carry an age, whose join rung was `sleeper_id` or whose entry Sleeper id equals the row's, and that no rule BEFORE the age rule (A1/A2/A3/rookie class) already decided. τ_age = the smallest grid value with zero |Δage| > τ_age among them; if none, the largest (2), reported as infeasible. | The largest grid value refuses least. |
| S4 | §3.5 ε: "no board proof on any E board where payload and CSV are from the same healthy capture" | E_DEV ∪ E_BASELINE minus the H3/H4 boards (`20260803_235610`, `20260806_150742`), using the B2 group statistics the chained V2 build stamped (`sourceIntegrity.provenance`), re-thresholded per grid ε with the registered fixed rules (≥ 2 groups, ≥ 15 rows, ≥ 80 % sign). None feasible → 0.05, reported. | — |
| S5 | §3.5 τ_board: "standard deviation over E_DEV of the class median residual" | Sample SD (n − 1) of `segmentMedians["source|class|*"]` over the E_DEV boards where the cell exists, from the chained V2 build; a cell with < 3 boards gets no τ_board (B3a abstains for it). | Abstention cannot quarantine. |
| S6 | §3.5 B3b selection: "zero clean E_DEV segments flagged hard … 100 % of the E_DEV source-split AD3-style injections caught" | Clean = the 22 non-H1 E_DEV boards. A setting's hard findings = B3b (direction or gross scale) and B3a (with the selected τ_board), on baselines simulated per setting from the chained build's per-board segment medians with the setting's own quarantines withheld from the window (exactly `source_integrity.advance`'s rule). Injections: on each of the 44 E_DEV boards, the 7 non-registered (source, class) cells (`dlfSf`, `draftSharks`, `fantasyProsSf`, `ktcCrowdSfTep`, `idpTradeCalc` offense; `draftSharksIdp`, `idpTradeCalc` IDP) × {ranks ×2, ranks ×5, values ×0.01, reversed}, injected on priced votes (as AD3, T4), built with the board's chained history; caught = any hard B3 finding on that source and class. The simulation does not model a quarantine's effect on OTHER sources' references; at a feasible setting no clean segment is quarantined, so on clean boards it is exact. | The feasibility test counts B3a as well as B3b against "zero clean flags": stricter, never looser. |
| S7 | §3.5 τ_c: "MAD of the source's own consecutive same-player Δu over E" | Over E_BASELINE ∪ E_DEV (S1 applied), Δu between consecutive chain boards on which the source's observation of the player was accepted on both; band = depth band of the earlier observation. A (source, band) cell needs ≥ 20 Δu; otherwise the source's pooled MAD is used; a source with < 20 in total gets no cell (B4 abstains for it). τ_c = max(ln 1.5, k_c × 1.4826 × MAD). | A missing cell abstains (no hold). |
| S8 | §3.5 k_c: "false-hold rate ≤ 0.5 % of votes on every clean E_DEV board" | Three chained V2 runs over E (k_c 4 / 6 / 8, every other constant at its selected value); rate = B4 holds ÷ observations that reached the filter or were held, per non-H1 E_DEV board; the smallest feasible k_c; none → 8 (as registered). | — |
| S9 | §3.5 τ_C: "LARGEST value catching ≥ 95 % of material cold-start ×20 and ×0.05 injections on E_DEV (seed 20261020)" | V2-NOHIST builds; cases = the gate harness's AD1c / AD1d construction at seed 20261020; material and pass exactly as §7; on 4 E_DEV boards fixed now for cost (E_DEV indices 0, 14, 29, 43: `20260818_230211`, `20260901_212308`, `20260916_214700`, `20260930_130404`); ×20 and ×0.05 must EACH reach 95 %. None feasible → ln 4 (the floor, the most catching value), reported as infeasible. | Each-family bar is stricter than a pooled one. |
| S10 | §10 M1: V2's decision on the reduced panel "recomputed with the held-out family removed everywhere" | Layer C's reduced-panel decision is V2's own (the build's `LayerCContext`, recorded per row). A/B exclusions and B3 decisions are held at their full-board values (B3's leave-source-out reference without the held-out family is not recomputed); targets are the held-out family's votes on the incumbent build (V1 §4); V2's dropped set is everything in the incumbent's panel that does not vote in V2's (A/B exclusions included). | Reported as an approximation; M1 cannot reach its minimum sample before Stage 5 in any case. |
| S11 | §7.2 INJ-H1: "the rookie-ladder reference marked inactive" | Both `ROOKIE_LADDER_PAIRS` references (`ktcCrowdSfTep`, `idpTradeCalc`) disabled through the documented source-override path on each V and I board. | — |
| S12 | §7.2 INJ-SEG | IDP Trade Calculator payload copies (both payload fields), per-Sleeper-position random-sign shifts |0.1–0.3| log on 70 % of rows, seed 2033; the CSV keeps the true values; on each V and I board. | — |
| S13 | §7.2 / §2.2 | NOT RUN in this unit (named): AD2-ID, AD2-SUR and AD2-N as full-pipeline injections, INJ-DUP end to end, the PERSISTENT history variant, and the V2-RPC comparator (not implemented in Stage 1). Criterion 1 cannot be shown passing without AD2-N. | Unrun gates are reported as not run, never as passes. |
| S14 | §5.3 Stage 4: "every record and result committed as produced" | Per-board records are gitignored (`data/oiv2_replay/`, §6 "gitignored ledger"); committed: every result file, a per-board summary and the sha256 of every record. | — |
| S15 | §3.5 τ_age selection rule | Observed while debugging the selector on the partial E pass (E only): **no** age-publishing source carries a Sleeper id that agrees with the row on any E_DEV join, so the registered evidence set is EMPTY and every grid value satisfies "zero contradictions"; the rule as written selects the smallest, **τ_age = 1**. Applied literally, not overridden. Its effect (`identity_contradicted:age` refusals, ~70 joins over 44 E_DEV boards differ by > 1 year on name-only joins) is counted in the clean-board false-exclusion census, never as a true exclusion. | Literal application; the alternative (2) would have been a judgment call. |
| S16 | §7.2 INJ-SEG "B2 board proof on 100 % of injected boards" vs §3.2 B2 "≥ 80 % of rows sharing m_g's sign" | Observed on an E_DEV smoke (`20260930_130404`) before the Stage 4 run: with 70 % of rows shifted, the 30 % unshifted rows have ln(payload/CSV) = 0 exactly and do not count toward the sign share, so every group's share is ≈ 0.6–0.76 < 0.80 and B2 cannot board-prove the registered injection **by construction**. Executed exactly as registered anyway (shift groups follow the pipeline's position vocabulary, `POSITION_ALIASES`); INJ-SEG is expected to fail and is reported as it comes out. Neither the injection nor the B2 rule is changed. | Nothing is loosened; the gate stands. |
