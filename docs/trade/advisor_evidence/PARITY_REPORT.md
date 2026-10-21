# Lane E-1 — Multi-team parity and property report (directive §11, deliverables E and G)

Date: 2026-10-20. Lane: E-1, parity and properties. Mostly read-only; gap tests were added to Lane A.

## 1. What was tested, where

| Item | Value |
|---|---|
| Combined tree under test | Throwaway sparse worktree (removed after the run): Lane B head `cf5cda350d` (stacked on Lane A `44960d624c`) merged with Lane C head `82ca5fa984`. The merge was clean (local `ddea09d3dc`, not pushed). |
| Board | The real archived scrape `exports/archive/dynasty_export_20261020_052241.zip`, rebuilt through `build_api_data_contract`. It has the real `dynasty_main` rosters (12 teams, every roster at the 58-player cap, team 5 at 59), real owned picks with canonical ids, IDP families, the two-way player Travis Hunter (roster 11) and an orphan team (12, no `ownerId`). Rosters are stamped `live` because the archive predates the stamp (same convention as Lanes A and C). |
| Surfaces | **Shared backend:** `analyze_service.analyze_trade_n`, in team_context, asset_only and market_fairness modes. **Private API (Lane A):** `POST /api/trade/analyze-multi`, in team_context and asset_only. **Private UI computation (Lane B):** `buildMultiTeamLedger`, `perTeamPackageTotals`, `computeSideFlows`, `tradeImbalance` and the `MultiTeamWarRoom` render, in vitest. **Public API (Lane C):** `POST /api/public/league/trade-advisor/analyze`, from every perspective. **2-team War Room route:** `POST /api/trade/analyze`, for the N = 2 equivalence check. |
| In-process patches (local only) | Both flags on in-process (`trade_multi_team_analysis`, `brisket_trade_advisor`). The public launch gate (`_launch_gate_reason`), the public league key and the public-league predicate are patched open. The posture bundle is a LABELLED synthetic HOLD. `comparable_trades` returns a fixed "unavailable". Nothing ran against production, no flag default changed, and nothing was deployed. |
| Harness (not committed; copied out before the throwaway worktree was removed) | `<session-scratchpad>/tam/e1/harness/test_zz_e1_matrix.py` (goes in `tests/trade/`), `<session-scratchpad>/tam/e1/harness/zz-e1-ui-parity.test.js` (goes in `frontend/__tests__/`), `<session-scratchpad>/tam/e1/harness/zz-e1-war-room-real.test.jsx` (goes in `frontend/__tests__/components/`) |
| Raw outputs | `<session-scratchpad>/tam/e1/matrix.json`, `sweep.json`, `ui_cases.json`, `ui_results.json`, `private_S*.json` (full private bodies) |

## 2. Headline results

* **Deterministic §11 matrix:** 26 structures and 11 refused-request cases. 2,082 checks passed, 0 failed.
* **Seeded random sweep:** 36 real-board ledgers (12 each of 2, 3 and 4 teams, players and owned picks). 892 checks passed, 0 failed.
* **JavaScript (vitest):** 61 passed, 0 failed.
  - The UI ledger builder matches the canonical request in 25 of 25 structures.
  - The per-team package math matches the server's per-team totals and band in 25 of 25. A negative control (server totals perturbed by +1) fails all 25 math cases.
  - The War Room renders the real-board bodies verbatim from every perspective, with one request, for 8 structures.
* **Gap tests:** commit `52b2aef95a` on `claude/trade-nteam-engine` (PR #1882; section 6). 7 new tests pass, and the 19 existing route tests still pass beside them.
* **Defects:** no parity or invariance defect was found in the multi-team code. Two pre-existing or contract-level findings, F1 and F2 in section 5, matter for launch. F3 and F5 are small Lane B display items.

### Parity claims, as proven

| Claim (§10 / §11) | How it was checked | Result |
|---|---|---|
| Private route == shared engine | Route body minus per-request additions (`decisionRunIds`, `tradeRunId`, `analysisTiming`, `valuationMode/Note`, per-team `decisionRunId`) compared **byte-for-byte** against `multi_team_payload(analyze_trade_n(...))`, at 2, 3 and 4 teams, in both private modes | identical in every structure and every sweep ledger |
| 2-team generalized ≡ existing 2-team engine | For each N = 2 structure and each team, the engine's `simulation` and `analysis` compared byte-for-byte against `/api/trade/analyze` driven with the War Room's request shape, in both modes | identical |
| Public = privacy-safe reduction | Per team: public `result` == `_PUB[private fairness.state]` and `reasonCode` equal, in both private modes and against the market_fairness engine. Overall == the private `fairnessOverall`. `unavailableAssetIds` == the private team's unpriced or off-board legs. | equal everywhere |
| Public reveals nothing more from another perspective | Bodies compared across every `perspectiveRosterId`, with only that field excluded | byte-identical |
| Public value-free | `assert_advisor_payload_value_free` plus an independent scan (no floats, no `ADVISOR_KEY_BLOCKLIST` key) on every success and error body; `no-store` on every response | pass |
| Fairness is one quantity in every mode | `fairness` dict compared across team_context, asset_only and market_fairness | identical |
| Python/JS parity (shared math) | Lane B's `perTeamPackageTotals` over the server's per-asset values: raw, VA and adjusted send/recv, gap, band level and `tradeImbalance.perTeam[].level` vs the Python market lens and `fairness`; N = 2 identity `imb.gap == sendAdj − recvAdj` | equal (to 1e-6; gaps equal after rounding) |
| Private UI shows the server's answer | `MultiTeamWarRoom` with real-board bodies, per perspective tab: decision text == `headlineText`, fairness word == state, package totals table contains the server's raw and adjusted numbers, summary rows show each team's fairness; exactly one fetch; the request it sends == the ledger | pass |

### Invariances

| Invariant | Check | Result |
|---|---|---|
| Team reorder | Every structure: reversed `teams` plus shuffled legs through the private route (byte-equal) and the public route (byte-equal). 4-team structures: all 24 team orders through the engine. | invariant |
| Asset reorder | Shuffled legs, as above, plus 36 sweep ledgers | invariant |
| Display renaming | All 12 team names renamed in the contract. Per-team fairness, category, headline, market totals, delta, forced drops, overall and conservation are unchanged. | invariant |
| No double transfer | Same asset in two legs, or an identical leg twice: 400 `duplicate_asset` on the ledger, the private route and the public route. The UI builder refuses `duplicate_asset` before sending. | refused everywhere |
| Verified owner not overridable | A wrong `from` gives 409 `asset_not_owned` on all three surfaces, and the public 409 does not name the holder. An injected `owner` / `ownerRosterId` on legs is ignored by the private route (byte-equal result) and rejected or ignored by the public route (36 ledgers). A pick owned by a third team gives 409. | holds |
| Ledger reconciliation | Per team: `gives`/`receives` == the ledger legs from/to it, with `toRosterId`/`fromRosterId` == the leg. Post-trade holdings == before − gives + receives. The union of all holdings is preserved and the total count unchanged. `summary.conservation.balanced`, with sent == received == number of legs. | holds (no phantom or destroyed assets) |
| Simultaneous roster updates | Each team's `simulation.sending`/`receiving` counts == its ledger legs. Locality: adding a disjoint 2-team exchange between two OTHER teams (engine at N = 5, beyond the private cap) leaves every original team's fairness, category, headline, market totals, delta and forced drops unchanged. Each team's adjusted gap == `package_model.adjusted_pair_totals` over its FULL gives and receives. | holds; see the sequential demonstration below |
| One value per asset | Each asset's `(value, valueState)` is identical across all three engine modes, both route modes and every team row that touches it. Priced player value == board `rankDerivedValue`. The two-way player (S14) carries one value. Unpriced → `value: null` (never 0). | holds |
| Decision traceability | `summary.perTeam[i]`: headline == `analysis.decision.headline`; category == `team_category(decision)`; fairness == `team_fairness(simulation, analysis)`; overall == three-valued AND of the per-team states. Every team has a `decisionRunId` whose logged receipt carries the same headline (36 sweep ledgers). `recommendationOnly: true`, `executes: false`. The public path writes no receipt. | holds |
| Changed source data mid-session | The board moved (a traded player's value ×1.5, new `generatedAt`): private and public both report `snapshotChanged: true` against the earlier generation, the new value is used (no stale cache), and public == private after the move. Unchanged board → `snapshotChanged: false`. | holds |
| Stale roster ownership | `rosterSource: last_good`, 30 h old: private gives every team UNABLE and NOT_ENOUGH_EVIDENCE (`ownership_unverifiable`); public gives every team UNABLE TO DETERMINE (`ownership_unverifiable`). | fails closed everywhere |
| 3- and 4-team never "unsupported" | Every valid 3- and 4-team structure returns 200 with per-team results on both routes | holds |

**Simultaneous vs sequential (S06, 3 teams, two players each way).** The engine's per-team adjusted gap equals the package model on the team's full package. That differs from summing pairwise sub-trades, because VA is not additive:

| Team | Engine gap (full package, VA once) | Sum of pairwise gaps (what a sequence of 2-team trades would give) |
|---|---|---|
| Jason (1) | −5,762 | −6,415 (−10,036 vs Collin, +3,621 vs Roy) |
| Collin (4) | +335 | +460 |
| Roy (7) | +5,427 | +5,955 |

The engine does not decompose a trade into 2-team trades. Adjusted gaps are per-team quantities and need not sum to zero. In S06 they happen to (VA 653 received by Jason = 125 + 528 sent by Collin and Roy), but in S04 they sum to +108 (227 − 609 + 490) and in S05 to +245 (272 − 1,142 + 1,115). Raw routed value is always conserved (`summary.conservation`).


## 3. Structure matrix (directive §11) — every structure through every surface

Per-team fairness is identical on the engine (all three modes), the private route (both modes) and the public route (every perspective), so one column shows all of them. "Checks" counts the assertions made on that structure across the parity and invariance rows above.

| ID | §11 structure | N | Per-team fairness (private = public) | Asset-only decisions | Public overall | Checks passed |
|---|---|---|---|---|---|---|
| S01 | standard 2-team offense 1-for-1 | 2 | 1:NOT_FAIR, 7:NOT_FAIR | 1:NO, 7:YES | NOT FAIR | 62/62 |
| S02 | 3-team circular | 3 | 1:NOT_FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:NO, 4:YES, 7:YES | NOT FAIR | 84/84 |
| S03 | 4-team circular | 4 | 1:NOT_FAIR, 3:NOT_FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:NO, 3:NO, 4:YES, 7:YES | NOT FAIR | 114/114 |
| S04 | one team to multiple destinations | 3 | 1:FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:NO_TOO_CLOSE, 4:NO, 7:YES | NOT FAIR | 84/84 |
| S05 | multiple teams to one team (hub sends picks back) | 3 | 1:FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:NO_TOO_CLOSE, 4:NO, 7:YES | NOT FAIR | 83/83 |
| S05b | gift-like: two teams send to one, hub sends nothing (private only) | 3 | 1:NOT_FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:YES, 4:NO, 7:NO | refused `one_sided_trade` | 46/46 |
| S06 | 3-team, multiple players per side | 3 | 1:NOT_FAIR, 4:FAIR, 7:NOT_FAIR | 1:NO, 4:NO_TOO_CLOSE, 7:YES | NOT FAIR | 87/87 |
| S07a | 2-team IDP-for-IDP (DL/LB/DB) | 2 | 1:NOT_FAIR, 4:NOT_FAIR | 1:NO, 4:YES | NOT FAIR | 64/64 |
| S07b | 3-team mixed offense + IDP | 3 | 1:NOT_FAIR, 4:NOT_FAIR, 7:NOT_FAIR | 1:NO, 4:YES, 7:YES | NOT FAIR | 86/86 |
| S08 | 3-team mixed players and picks | 3 | 1:UNABLE, 3:UNABLE, 7:UNABLE | 1:NOT_ENOUGH_EVIDENCE, 3:NOT_ENOUGH_EVIDENCE, 7:NOT_ENOUGH_EVIDENCE | UNABLE TO DETERMINE | 84/84 |
| S09 | picks-only 3-team cycle | 3 | 1:FAIR, 4:FAIR, 7:FAIR | 1:NO_TOO_CLOSE, 4:NO_TOO_CLOSE, 7:NO_TOO_CLOSE | FAIR TRADE | 81/81 |
| S09b | picks-only 4-team, rounds 1-3 across seasons | 4 | 1:UNABLE, 3:UNABLE, 4:UNABLE, 7:UNABLE | 1:NOT_ENOUGH_EVIDENCE, 3:NOT_ENOUGH_EVIDENCE, 4:NOT_ENOUGH_EVIDENCE, 7:NOT_ENOUGH_EVIDENCE | UNABLE TO DETERMINE | 110/110 |
| S10 | deep packages (5-6 assets per team, 3 teams) | 3 | 1:UNABLE, 4:UNABLE, 7:NOT_FAIR | 1:NOT_ENOUGH_EVIDENCE, 4:NOT_ENOUGH_EVIDENCE, 7:YES | NOT FAIR | 96/96 |
| S11 | unequal package sizes (1 vs 4) | 2 | 1:NOT_FAIR, 4:NOT_FAIR | 1:YES, 4:NO | NOT FAIR | 65/65 |
| S12 | elite player vs depth (1 vs 5 depth) | 2 | 1:NOT_FAIR, 7:NOT_FAIR | 1:NO, 7:YES | NOT FAIR | 66/66 |
| S13 | S01 plus low-value filler from one side | 2 | 1:NOT_FAIR, 7:NOT_FAIR | 1:NO, 7:YES | NOT FAIR | 63/63 |
| S14 | two-way player (Travis Hunter) in a 3-team trade | 3 | 1:NOT_FAIR, 4:NOT_FAIR, 11:NOT_FAIR | 1:NO, 4:YES, 11:YES | NOT FAIR | 84/84 |
| S15 | unresolved player value (rostered, unpriced) | 3 | 1:NOT_FAIR, 4:UNABLE, 7:UNABLE | 1:NO, 4:NOT_ENOUGH_EVIDENCE, 7:NOT_ENOUGH_EVIDENCE | NOT FAIR | 96/96 |
| S16 | future picks with unknown slots (2028/2029 R1-R2) | 2 | 4:UNABLE, 7:UNABLE | 4:NOT_ENOUGH_EVIDENCE, 7:NOT_ENOUGH_EVIDENCE | UNABLE TO DETERMINE | 61/61 |
| S16q | quarantined future pick value (2028 R6) | 2 | 1:UNABLE, 4:UNABLE | 1:NOT_ENOUGH_EVIDENCE, 4:NOT_ENOUGH_EVIDENCE | UNABLE TO DETERMINE | 61/61 |
| S17 | exceeding roster limits (2-for-1 into 58-man rosters) | 2 | 1:NOT_FAIR, 7:NOT_FAIR | 1:NO, 7:YES | NOT FAIR | 63/63 |
| S18o | orphan team (no ownerId) in a 3-team trade | 3 | 1:FAIR, 4:NOT_FAIR, 12:NOT_FAIR | 1:NO_TOO_CLOSE, 4:YES, 12:NO | NOT FAIR | 84/84 |
| S19 | 4-team offense + IDP + picks, multiple per team | 4 | 1:UNABLE, 3:UNABLE, 4:NOT_FAIR, 7:UNABLE | 1:NOT_ENOUGH_EVIDENCE, 3:NOT_ENOUGH_EVIDENCE, 4:YES, 7:NOT_ENOUGH_EVIDENCE | NOT FAIR | 116/116 |
| S22 | 3-team cycle, near-equal values (every team fair) | 3 | 1:FAIR, 4:FAIR, 7:FAIR | 1:NO_TOO_CLOSE, 4:NO_TOO_CLOSE, 7:NO_TOO_CLOSE | FAIR TRADE | 84/84 |
| S23 | 4-team cycle, near-equal values (every team fair) | 4 | 1:FAIR, 3:FAIR, 4:FAIR, 7:FAIR | 1:NO_TOO_CLOSE, 3:NO_TOO_CLOSE, 4:NO_TOO_CLOSE, 7:NO_TOO_CLOSE | FAIR TRADE | 114/114 |
| S20-stale | stale roster ownership (rosters restored, 30 h old) | 3 | 1:UNABLE, 4:UNABLE, 7:UNABLE | 1:NOT_ENOUGH_EVIDENCE, 4:NOT_ENOUGH_EVIDENCE, 7:NOT_ENOUGH_EVIDENCE | UNABLE TO DETERMINE | 2/2 |

| ID | Refused request | Engine ledger | Private route | Public route | Checks |
|---|---|---|---|---|---|
| V01 | duplicate transfer (same asset in two legs) | 400 `duplicate_asset` | 400 `duplicate_asset` | 400 `duplicate_asset` | 3/3 |
| V02 | duplicate transfer (identical leg twice) | 400 `duplicate_asset` | 400 `duplicate_asset` | 400 `duplicate_asset` | 3/3 |
| V03 | invalid destination: team not in trade | 400 `invalid_destination` | 400 `invalid_destination` | 400 `invalid_destination` | 3/3 |
| V04 | invalid destination: self | 400 `destination_is_origin` | 400 `destination_is_origin` | 400 `destination_is_origin` | 3/3 |
| V05 | owner override: wrong 'from' (asset held by 4) | 409 `asset_not_owned` | 409 `asset_not_owned` | 409 `asset_not_owned` | 4/4 |
| V06 | team with no participation | 400 `idle_team` | 400 `idle_team` | 400 `idle_team` | 3/3 |
| V07 | nonexistent asset | 400 `unknown_asset` | 400 `unknown_asset` | 400 `unknown_asset` | 3/3 |
| V08 | unrecognised team | 400 `team_not_in_league` | 400 `team_not_in_league` | 400 `team_not_in_league` | 3/3 |
| V09 | pick owned by another team | 409 `asset_not_owned` | 409 `asset_not_owned` | 409 `asset_not_owned` | 4/4 |
| V10 | malformed asset id | 400 `unknown_asset` | 400 `unknown_asset` | 400 `schema` | 3/3 |
| V11 | five teams (above maxTeams 4) | 400 `too_many_teams` | 400 `too_many_teams` | 400 `schema` | 3/3 |

Notes:

* **UNABLE results:**
  - S08, S09b, S10, S16, S19 are UNABLE because they touch a quarantined pick row (finding F1).
  - S16q is UNABLE because of a genuinely quarantined 2028 Round 6 row.
  - S15 is UNABLE because of an unpriced rostered player: `value: null`, `asset_not_evaluable`, and the public `unavailableAssetIds` names it.
* **S05b (gift-like):** the private route evaluates it (`participation: any_leg`). The public route refuses it with `one_sided_trade` (`send_and_receive`, SD-5 / OD-8). This is an availability difference, not a different conclusion.
* **S17 (exceeds roster limits):** the receiving team, at the 58 cap, reports `overLimitAfter 1` with one forced drop. Fairness and the public result do not move (SD-3).
* **S18o (orphan team 12):** in Team Context mode the decision adds `posture_unknown` and never borrows another team's posture. Fairness is unaffected.
* **Every team is NOT_ENOUGH_EVIDENCE in Team Context mode (`roster_unknown`).** League-scored projection snapshots are box-local (`ros_ensemble ... sourcesUnavailable: clayProjections, idpShowProjections`). The engine reports an honest limitation rather than an asset-only verdict passed off as team-aware (directive §4). Team Context verdicts with real projections can only be observed on the box (U2).
* **V10 and V11:** the public route refuses earlier, at its Pydantic schema (`schema`: asset-id pattern, team-count ceiling). The engine and private route refuse at the ledger. All are 4xx and value-free.

## 4. Multi-team performance and timing

Out of scope for E-1, so not measured here. Lane A's local p50 figures are the only ones on record. The public response floor is still `null` (launch gate).

## 5. Findings

### F1 — HIGH (launch-relevant; pre-existing, not caused by the multi-team lanes): every 2028/2029 league pick is unevaluable

* **What happens.** Every league pick in a future season resolves, correctly, to the GENERIC board row (`boardRowName: "2028 Round 1"`, slot unknown). On the archived board, all twelve generic rows `2028 Round 1..6` and `2029 Round 1..6` carry `quarantined: true` and `anomalyFlags: ["no_valid_source_values"]`. Their provenance is `derived_uniform_tier_ev`, so they have no `canonicalSiteValues`, and `data_contract` Check 5 flags them.
* **The market-priced rows are fine.** The tier rows (`2028 Mid 1st` 4,631, `2029 Mid 1st` 4,087; `direct_market_blend`) are not quarantined.
* **Effect on results.** The decision owner's `quarantined_values` gate fires for any team that sends or receives such a pick. That team is UNABLE and NOT_ENOUGH_EVIDENCE in every surface. By I4 this includes the existing 2-team War Room on main: same code path, byte-equal.
* **What a user sees.** Any real trade that includes a 2028 or 2029 pick answers "Not enough evidence" privately and "UNABLE TO DETERMINE" publicly. This covers the directive §11 row "future picks with unknown slots" (S16) and most pick-bearing packages (S08, S09b, S10, S19).
* **Where it was checked.** On the archived board, built with the lane base's `data_contract`. Check 5 is unchanged on current `origin/main`.
* **Who fixes it.** The valuation and pick owners (`data_contract` Check 5 vs the C1-U6 generic-grade rows). Whether a derived PRIOR generic value is decision-grade is a methodology question, so this is an owner decision, not a multi-team fix. It is not fixed here.

### F2 — MEDIUM (contract, private display): a quarantined value is published as `valueState: "priced"`

* **Private.** In the engine and private `gives` / `receives` rows, a quarantined asset carries its number and `valueState: "priced"`, while the same team's decision says "Value withheld as untrustworthy (quarantined)". The market-lens totals include it. The War Room therefore shows a number the decision has refused to use. For example, in S16 the 2029 Mid 1st shows 4,136 next to "Not enough evidence".
* **Public.** The reduction gives `evaluation_unavailable` with empty `unavailableAssetIds`, so the public UI cannot point at the asset (it does for unpriced assets).
* **Suggested fix.**
  - A `valueState: "quarantined"`, or a flag on the row (Lane A contract).
  - Including quarantined ids in public `unavailableAssetIds` (Lane C).
* Both are contract changes for their owners, so neither is made here. The new Lane A test pins the current decision behaviour (UNABLE, `quarantined_values`, only the touching teams) and leaves the row shape free.

### F3 — LOW (Lane B UI): destinations are keyed by display name for players

`tradeEntryKey(entry)` (`frontend/lib/trade-assets.js`) returns `entry.name` for players. A side holding two different players with the same display name would share one destination entry in `side.destinations`, so routing both elsewhere is impossible. The ledger itself uses `p:<playerId>`, so this is not a value or ownership error. It is rare (same-named players on one roster) and recorded for Lane B.

### F5 — LOW-MEDIUM (Lane B display): package totals show 0 for a package of unpriced assets

* **The case.** In S15, Collin sends only Jake Bates, who is unpriced (`value: null`). The pre-existing market lens publishes `sendingValue: 0`, `sendingAdjusted: 0`, `incomplete: true`, `unpricedOut: ["Jake Bates"]`, and even a `band` of lopsided at 100%.
* **The War Room.** The multi-team `PackageTotals` table renders "Sends Raw 0 / Adjusted 0" with no incomplete marker, next to the correct "Unable to determine" and the asset row's "unknown, not zero".
* **Is the verdict affected?** No. Fairness and the decision are correctly UNABLE, and the public is unaffected. It is a missing-is-never-zero display gap.
* **Suggested fix.** `PackageTotals` shows "incomplete" (or "—") when `detail.incomplete` is true (Lane B). Whether the lens should stamp a band on an incomplete package belongs to the analyze_trade owner.

### F4 — INFO

* **Provisional threshold, visible in real trades (OD-F1..F6).** In S02, Collin's +253 (4.27%) is NOT_FAIR because it is just past the 250 floor and the 3.5% "slight" cut, while his asset-only decision is YES / FAVORABLE. The two answers are labelled separately (C4). In the other direction, near-equal ~2,100-value cycles (S22, S23) are FAIR at up to 4.5% relative because of the absolute floor.
* **Overall fairness is a Kleene AND.** One NOT_FAIR team makes the overall NOT FAIR even when other teams are UNABLE (S10, S15, S19). This is spec R2, and it matches the amendment's "NOT FAIR, provided sufficient evidence exists", because one proven NOT_FAIR team decides the AND.
* **Error wording differs, codes do not.** Private and public error copy differ for the same reason code (`duplicate_asset`: "can move only once" vs "can only appear once"). The codes are identical, and each surface uses its own fixed copy table.

## 6. Gap tests added to `claude/trade-nteam-engine`

New file: `tests/api/test_trade_analyze_multi_cross_surface.py`. It is tests only and reuses the route module's real-board fixtures. It covers what the existing suites left unpinned:

| Test | Pins |
|---|---|
| `test_route_equals_engine_byte_for_byte_at_two_three_and_four_teams[team_context / asset_only]` | Private route == `multi_team_payload(analyze_trade_n(...))`, byte-for-byte, at N = 2, 3 and 4. It runs over 8 directive §11 shapes on real rosters (circular 3 and 4, one-to-many, many-to-one, offense + IDP, picks only, deep 4-team mixed) plus 5 seeded random ledgers. Lane A had byte equality only at N = 2 (I4) and shape at N = 3. |
| `test_every_team_decision_is_traceable_to_its_owner_and_receipt` | The summary is a projection of the per-team rows (`team_category`, `team_fairness`); the overall is the three-valued AND; and each `decisionRunId`'s logged receipt carries the served headline and `deciding`. |
| `test_quarantined_value_withholds_only_the_touching_teams[3 modes]` | LABELLED synthetic league: the sender and receiver of a quarantined asset are UNABLE (`evaluation_unavailable`) and NOT_ENOUGH_EVIDENCE (`quarantined_values`). The untouched team is byte-identical to the clean board. Before this, only the `team_verdicts` unit test covered quarantine. |
| `test_real_board_quarantine_invariant` | On the real board, `quarantined_values` is in a team's decision exactly when a simulated row it touches is quarantined, and such a team is UNABLE. It also injects quarantine on a real row, so the property never depends on what the newest archive happens to quarantine. |

Evidence: those 7 tests plus the existing `tests/api/test_trade_analyze_multi_route.py` give 26 passed. The targeted multi-team suites give 179 passed. Collect-only over tests/api + tests/trade gives 9,652 tests with no collection conflict. Commit `52b2aef95a`, fast-forward pushed to `origin/claude/trade-nteam-engine`, so PR #1882's head is now `52b2aef95a`. Formatting: `scripts/format_python_changes.sh` GREEN (Ruff 0.6.9).

## 7. Example trades (deliverable G)

Real archived board, real rosters and owned picks. "Decision (asset-only)" is the private calculator with Team Context off. "Decision (Team Context)" is the private default, which locally answers NOT_ENOUGH_EVIDENCE (`roster_unknown`) because projection snapshots are box-local (section 3). The public block is the exact value-free body content, which is byte-identical for every perspective team. Public bodies carry no values. The numbers in the private tables are private-only.

### G1 — 2 teams · offense  (`S01`)

Ledger: Jason → Roy: `p:8137`; Roy → Jason: `p:8154`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | George Pickens 6,068→Roy | Brian Robinson 2,265←Roy | 6,068 / 2,265 | 0 / 0 | 6,068 / 2,265 | -3,803 (62.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Brian Robinson 2,265→Jason | George Pickens 6,068←Jason | 2,265 / 6,068 | 0 / 0 | 2,265 / 6,068 | 3,803 (62.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 2 assets, raw 8,333 = 8,333, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G2 — 3 teams · circular  (`S02`)

Ledger: Jason → Collin: `p:12508`; Collin → Roy: `p:8150`; Roy → Jason: `p:11597`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Jaxson Dart 5,921→Collin | Theo Johnson 2,184←Roy | 5,921 / 2,184 | 0 / 0 | 5,921 / 2,184 | -3,737 (63.11%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Kyren Williams 5,668→Roy | Jaxson Dart 5,921←Jason | 5,668 / 5,921 | 0 / 0 | 5,668 / 5,921 | 253 (4.27%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Theo Johnson 2,184→Jason | Kyren Williams 5,668←Collin | 2,184 / 5,668 | 0 / 0 | 2,184 / 5,668 | 3,484 (61.47%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 13,773 = 13,773, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G3 — 4 teams · circular  (`S03`)

Ledger: Jason → Collin: `p:6797`; Collin → Roy: `p:8155`; Roy → Ty: `p:12524`; Ty → Jason: `p:11584`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Justin Herbert 5,853→Collin | Bucky Irving 5,012←Ty | 5,853 / 5,012 | 0 / 0 | 5,853 / 5,012 | -841 (14.37%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Ty (3) | Bucky Irving 5,012→Jason | Shedeur Sanders 1,988←Roy | 5,012 / 1,988 | 0 / 0 | 5,012 / 1,988 | -3,024 (60.34%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Breece Hall 5,578→Roy | Justin Herbert 5,853←Jason | 5,578 / 5,853 | 0 / 0 | 5,578 / 5,853 | 275 (4.7%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Shedeur Sanders 1,988→Ty | Breece Hall 5,578←Collin | 1,988 / 5,578 | 0 / 0 | 1,988 / 5,578 | 3,590 (64.36%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Ty: Strongly unfavorable. Collin: Favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 18,431 = 18,431, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Ty (3) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G4 — IDP (DL/LB/DB for LB/DB)  (`S07a`)

Ledger: Jason → Collin: `p:13377`; Jason → Collin: `p:8339`; Collin → Jason: `p:10880`; Collin → Jason: `p:11739`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Arvell Reese 5,090→Collin, Kyle Hamilton 2,825→Collin | Jack Campbell 5,416←Collin, Evan Williams 1,847←Collin | 7,915 / 7,263 | 0 / 215 | 7,915 / 7,478 | -437 (5.52%) | slight | NOT_FAIR (`outside_fairness_threshold`) | NO · UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Jack Campbell 5,416→Jason, Evan Williams 1,847→Jason | Arvell Reese 5,090←Jason, Kyle Hamilton 2,825←Jason | 7,263 / 7,915 | 215 / 0 | 7,478 / 7,915 | 437 (5.52%) | slight | NOT_FAIR (`outside_fairness_threshold`) | YES · FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Unfavorable. Collin: Favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 15,178 = 15,178, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G5 — Picks only (3-team cycle, 2027 1sts)  (`S09`)

Ledger: Jason → Collin: `pick:dynasty_main:2027:r1:o10`; Collin → Roy: `pick:dynasty_main:2027:r1:o4`; Roy → Jason: `pick:dynasty_main:2027:r1:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | 2027 Mid 1st (from Kich) 4,707→Collin | 2027 Mid 1st (from Jason) 4,707←Roy | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | 2027 Mid 1st (own) 4,707→Roy | 2027 Mid 1st (from Kich) 4,707←Jason | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | 2027 Mid 1st (from Jason) 4,707→Jason | 2027 Mid 1st (own) 4,707←Collin | 4,707 / 4,707 | 0 / 0 | 4,707 / 4,707 | 0 (0.0%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Approximately even. Collin: Approximately even. Roy: Approximately even.  Overall fairness: `FAIR` (`all_teams_fair`). Conservation: 3 assets, raw 14,121 = 14,121, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **FAIR TRADE** — The trade is within our fairness threshold for every team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Collin (4) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Roy (7) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |

### G6 — Mixed players + pick, one team to two destinations  (`S04`)

Ledger: Jason → Collin: `p:6794`; Jason → Roy: `p:12514`; Collin → Jason: `p:11564`; Roy → Jason: `pick:dynasty_main:2027:r1:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Roy, Justin Jefferson 7,915→Collin | Drake Maye 8,524←Collin, 2027 Mid 1st (from Jason) 4,707←Roy | 13,112 / 13,231 | 0 / 108 | 13,112 / 13,339 | 227 (1.7%) | fair | FAIR (`within_fairness_threshold`) | NO_TOO_CLOSE · APPROXIMATELY_EVEN | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Drake Maye 8,524→Jason | Justin Jefferson 7,915←Jason | 8,524 / 7,915 | 0 / 0 | 8,524 / 7,915 | -609 (7.14%) | slight | NOT_FAIR (`outside_fairness_threshold`) | NO · UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | 2027 Mid 1st (from Jason) 4,707→Jason | Emeka Egbuka 5,197←Jason | 4,707 / 5,197 | 0 / 0 | 4,707 / 5,197 | 490 (9.43%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Approximately even. Collin: Unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 4 assets, raw 26,343 = 26,343, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | FAIR FOR THIS TEAM | This trade is within our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G7 — Benefits more than one team (asset-only: two YES)  (`S07b`)

Ledger: Jason → Collin: `p:12514`; Collin → Roy: `p:5332`; Collin → Roy: `p:6124`; Roy → Jason: `p:9757`; Roy → Jason: `p:12639`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Collin | Malachi Moore 1,897←Roy, Kendre Miller 1,787←Roy | 5,197 / 3,684 | 393 / 0 | 5,590 / 3,684 | -1,906 (34.1%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Foyesade Oluokun 2,950→Roy, Montez Sweat 1,913→Roy | Emeka Egbuka 5,197←Jason | 4,863 / 5,197 | 0 / 421 | 4,863 / 5,618 | 755 (13.44%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Malachi Moore 1,897→Jason, Kendre Miller 1,787→Jason | Foyesade Oluokun 2,950←Collin, Montez Sweat 1,913←Collin | 3,684 / 4,863 | 28 / 0 | 3,712 / 4,863 | 1,151 (23.67%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Strongly favorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 5 assets, raw 13,744 = 13,744, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G8 — Clearly disadvantages one team (elite for depth)  (`S12`)

Ledger: Jason → Roy: `p:11604`; Roy → Jason: `p:12505`; Roy → Jason: `p:12718`; Roy → Jason: `p:4950`; Roy → Jason: `p:5848`; Roy → Jason: `p:11569`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Brock Bowers 9,985→Roy | Jarquez Hunter 1,313←Roy, Jalen Royals 1,510←Roy, Konata Mumpfield 1,454←Roy, Christian Kirk 1,407←Roy, Marquise Brown 1,317←Roy | 9,985 / 7,001 | 2,390 / 0 | 12,375 / 7,001 | -5,374 (43.43%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Jarquez Hunter 1,313→Jason, Jalen Royals 1,510→Jason, Konata Mumpfield 1,454→Jason, Christian Kirk 1,407→Jason, Marquise Brown 1,317→Jason | Brock Bowers 9,985←Jason | 7,001 / 9,985 | 0 / 2,390 | 7,001 / 12,375 | 5,374 (43.43%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 6 assets, raw 16,986 = 16,986, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G9 — Cannot be evaluated reliably (unpriced rostered player)  (`S15`)

Ledger: Jason → Collin: `p:12514`; Collin → Roy: `p:11539`; Roy → Jason: `p:13307`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Emeka Egbuka 5,197→Collin | Marlin Klein 1,797←Roy | 5,197 / 1,797 | 0 / 0 | 5,197 / 1,797 | -3,400 (65.42%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Collin (4) | Jake Bates null→Roy | Emeka Egbuka 5,197←Jason | 0 / 5,197 | 0 / 0 | 0 / 5,197 | null | — | UNABLE (`asset_not_evaluable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: unpriced_assets | NOT_ENOUGH_EVIDENCE (unpriced_assets,roster_unknown) |
| Roy (7) | Marlin Klein 1,797→Jason | Jake Bates null←Collin | 1,797 / 0 | 0 / 0 | 1,797 / 0 | null | — | UNABLE (`asset_not_evaluable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: unpriced_assets | NOT_ENOUGH_EVIDENCE (unpriced_assets,roster_unknown) |

All-team summary lines (asset-only): Jason: Strongly unfavorable. Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 6,994 = 6,994, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Collin (4) | UNABLE TO DETERMINE | One or more assets this team sends or receives can't be valued right now. | ['p:11539'] |
| Roy (7) | UNABLE TO DETERMINE | One or more assets this team sends or receives can't be valued right now. | ['p:11539'] |

### G10 — Cannot be evaluated reliably (2028/2029 unknown-slot picks: generic rows quarantined)  (`S16`)

Ledger: Roy → Collin: `pick:dynasty_main:2029:r1:o1`; Roy → Collin: `pick:dynasty_main:2028:r2:o1`; Collin → Roy: `p:6804`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Collin (4) | Jordan Love 5,849→Roy | 2028 Mid 2nd (from Jason) 3,063←Roy, 2029 Mid 1st (from Jason) 4,136←Roy | 5,849 / 7,199 | 674 / 0 | 6,523 / 7,199 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Roy (7) | 2028 Mid 2nd (from Jason) 3,063→Collin, 2029 Mid 1st (from Jason) 4,136→Collin | Jordan Love 5,849←Collin | 7,199 / 5,849 | 0 / 674 | 7,199 / 6,523 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |

All-team summary lines (asset-only): Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `UNABLE` (`evidence_insufficient`). Conservation: 3 assets, raw 13,048 = 13,048, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **UNABLE TO DETERMINE** — There isn't enough reliable information to judge this whole trade.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Collin (4) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Roy (7) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |

### G11 — 4 teams · offense + IDP + picks (partly unevaluable)  (`S19`)

Ledger: Jason → Ty: `p:8137`; Jason → Roy: `p:12578`; Ty → Collin: `p:8138`; Ty → Jason: `pick:dynasty_main:2028:r1:o3`; Collin → Jason: `p:6804`; Collin → Ty: `p:13340`; Roy → Collin: `p:12509`; Roy → Ty: `pick:dynasty_main:2028:r2:o1`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Carson Schwesinger 6,229→Roy, George Pickens 6,068→Ty | Jordan Love 5,849←Collin, 2028 Mid 1st (own) 4,747←Ty | 12,297 / 10,596 | 0 / 291 | 12,297 / 10,887 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Ty (3) | James Cook 6,784→Collin, 2028 Mid 1st (own) 4,747→Jason | Rueben Bain 2,324←Collin, George Pickens 6,068←Jason, 2028 Mid 2nd (from Jason) 3,063←Roy | 11,531 / 11,455 | 540 / 0 | 12,071 / 11,455 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |
| Collin (4) | Rueben Bain 2,324→Ty, Jordan Love 5,849→Jason | Tre' Harris 2,387←Roy, James Cook 6,784←Ty | 8,173 / 9,171 | 14 / 0 | 8,187 / 9,171 | 984 (10.73%) | unfair | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Tre' Harris 2,387→Collin, 2028 Mid 2nd (from Jason) 3,063→Ty | Carson Schwesinger 6,229←Jason | 5,450 / 6,229 | 0 / 525 | 5,450 / 6,754 | null | — | UNABLE (`evaluation_unavailable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: quarantined_values | NOT_ENOUGH_EVIDENCE (quarantined_values,roster_unknown) |

All-team summary lines (asset-only): Jason: Unavailable — insufficient evidence. Ty: Unavailable — insufficient evidence. Collin: Strongly favorable. Roy: Unavailable — insufficient evidence.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 8 assets, raw 37,451 = 37,451, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Ty (3) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |
| Collin (4) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | UNABLE TO DETERMINE | This trade can't be evaluated reliably right now. | — |

### G12 — Exceeds roster limits (forced drop; fairness unaffected)  (`S17`)

Ledger: Jason → Roy: `p:12508`; Jason → Roy: `p:12490`; Roy → Jason: `p:8154`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Bhayshul Tuten 4,604→Roy, Jaxson Dart 5,921→Roy | Brian Robinson 2,265←Roy | 10,525 / 2,265 | 0 / 1,013 | 10,525 / 3,278 | -7,247 (68.86%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | NO · STRONGLY_UNFAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |
| Roy (7) | Brian Robinson 2,265→Jason | Bhayshul Tuten 4,604←Jason, Jaxson Dart 5,921←Jason | 2,265 / 10,525 | 1,013 / 0 | 3,278 / 10,525 | 7,247 (68.86%) | lopsided | NOT_FAIR (`outside_fairness_threshold`) | YES · STRONGLY_FAVORABLE | NOT_ENOUGH_EVIDENCE (roster_unknown) |

Roster capacity, Jason: `{"rosterLimit": 58, "sizeBefore": 58, "sizeAfter": 57, "overLimitAfter": 0, "requiresDrops": false, "forcedDropValue": 0.0}`; forced drops `[]`

Roster capacity, Roy: `{"rosterLimit": 58, "sizeBefore": 58, "sizeAfter": 59, "overLimitAfter": 1, "requiresDrops": true, "forcedDropValue": 1737.0}`; forced drops `[['Anthony Richardson', 1737.0]]`

All-team summary lines (asset-only): Jason: Strongly unfavorable. Roy: Strongly favorable.  Overall fairness: `NOT_FAIR` (`not_all_teams_fair`). Conservation: 3 assets, raw 12,790 = 12,790, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **NOT FAIR** — The trade falls outside our fairness threshold for at least one team.

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |
| Roy (7) | NOT FAIR FOR THIS TEAM | This trade falls outside our fairness threshold for this team. | — |

### G13 — Stale roster ownership (fails closed everywhere)  (`S20-stale`)

Ledger: Jason → Collin: `p:12508`; Collin → Roy: `p:8150`; Roy → Jason: `p:11597`

**Private (`/api/trade/analyze-multi`, numeric).** Values are canonical `rankDerivedValue`; VA = geom_q078_v1.

| Team | Sends (value → to) | Receives (value ← from) | Raw send / recv | VA send / recv | Adj send / recv | Gap (recv−send) | Band | Fairness | Decision (asset-only) | Decision (Team Context) |
|---|---|---|---|---|---|---|---|---|---|---|
| Jason (1) | Jaxson Dart 5,921→Collin | Theo Johnson 2,184←Roy | 5,921 / 2,184 | 0 / 0 | 5,921 / 2,184 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |
| Collin (4) | Kyren Williams 5,668→Roy | Jaxson Dart 5,921←Jason | 5,668 / 5,921 | 0 / 0 | 5,668 / 5,921 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |
| Roy (7) | Theo Johnson 2,184→Jason | Kyren Williams 5,668←Collin | 2,184 / 5,668 | 0 / 0 | 2,184 / 5,668 | null | — | UNABLE (`ownership_unverifiable`) | NOT_ENOUGH_EVIDENCE · UNAVAILABLE · missing: ownership_unverifiable,roster_unknown | NOT_ENOUGH_EVIDENCE (ownership_unverifiable,roster_unknown) |

All-team summary lines (asset-only): Jason: Unavailable — insufficient evidence. Collin: Unavailable — insufficient evidence. Roy: Unavailable — insufficient evidence.  Overall fairness: `UNABLE` (`evidence_insufficient`). Conservation: 3 assets, raw 13,773 = 13,773, balanced=True.

**Public (`/api/public/league/trade-advisor/analyze`, value-free; identical from every perspective).** Overall: **UNABLE TO DETERMINE** — There isn't enough reliable information to judge this whole trade. _A trade with more than two teams is fair only when it is fair for every team._

| Team | Result | Text | unavailableAssetIds |
|---|---|---|---|
| Jason (1) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:11597', 'p:12508'] |
| Collin (4) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:12508', 'p:8150'] |
| Roy (7) | UNABLE TO DETERMINE | We couldn't confirm who owns every asset this team sends or receives. | ['p:11597', 'p:8150'] |


## 8. How to reproduce

```bash
# combined tree: Lane B head merged with Lane C head, sparse worktree; copy the harness files in
E1_OUT=<dir> python -m pytest tests/trade/test_zz_e1_matrix.py -q -p no:cacheprovider     # ~105 s
cd frontend
E1_DIR=<dir> E1_UI_CASES=<dir>/ui_cases.json npx vitest run __tests__/zz-e1-ui-parity.test.js __tests__/components/zz-e1-war-room-real.test.jsx
# committed gap tests (Lane A branch)
python -m pytest tests/api/test_trade_analyze_multi_cross_surface.py -q
```

## 9. Completion result

* **STATUS:** DONE for the E-1 parity and properties lane.
* **ACCEPTANCE:**
  - The §11 structure matrix runs through the shared backend, private API, private UI computation path and public API on real archived data.
  - Numeric equality holds wherever one owner computes.
  - The public body is a privacy-safe reduction.
  - All §11 invariances hold.
  - Example trades for deliverable G are produced.
* **EVIDENCE:**
  - Matrix: 2,082 checks passed, 0 failed.
  - Random sweep: 892 checks passed, 0 failed.
  - vitest: 61 passed, including a negative control.
  - Lane A gap tests: 7 passed, 26 together with the route tests. Targeted multi-team suites with the new file: 179 passed (-n 3). Collect-only of tests/api + tests/trade (not livedata): 9,652 collected, with no collection conflicts. `tests/test_livedata_policy.py`: 4 passed. The full tests/api + tests/trade run was stopped early, because the shared 4-core machine was at load 16 and the change is one additive test file.
* **UNRESOLVED:**
  - **U1.** F1 (2028/2029 generic pick rows quarantined, so pick trades are unevaluable on every surface) needs a valuation or pick owner decision. It is launch-relevant for usefulness, not for privacy or parity.
  - **U2.** Team Context verdicts with real projections are verified only for "honest limitation" locally. Projections exist only on the box, so on-box verification is needed.
  - **U3.** F2 (quarantined assets shown as `priced`, and the public cannot name them) needs a contract decision from Lanes A and C.
  - **U4.** F3 (player destinations keyed by display name) and F5 (totals show 0 for an incomplete package) are for Lane B.
  - **U5.** Performance, the timing floor and abuse resistance are out of scope here (other Lane E work).
  - **U6.** CI has not been observed on the new Lane A head `52b2aef95a` (PR #1882). The full tests/api + tests/trade run was not completed locally (shared machine under load).
* **BLOCKERS:** none for this lane.
* **NEXT_ACTION:**
  - Route F1 to the valuation and pick owner, and F2/F3/F5 to Lanes A, C and B.
  - Lanes B and C pick up the new Lane A test commit when they next merge Lane A. It is a new file with no conflict.
