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
