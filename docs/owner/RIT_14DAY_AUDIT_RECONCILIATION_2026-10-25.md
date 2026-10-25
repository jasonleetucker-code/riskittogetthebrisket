# 14-day owner requirements inventory — reconciliation (RIT-001 … RIT-088)

**Date:** 2026-10-25 · **Status:** RECORD (docs only). It authorizes nothing and activates nothing.
**Agent-OS-Receipt:** `cb64f74cf4d2763aa16d55ba0d6350f585a2a42f`

## 1. What this is, and what it is not

The owner recovered an inventory of 88 requirement tracks from 2026-10-11 to 2026-10-25:
`RiskIt_14Day_Master_Backlog.csv` (RIT-001 … RIT-088) and `RiskIt_14Day_Development_Audit.md`. Both were written
outside this repository. This document checks every row against GitHub and `origin/main`, with read-only public
production probes.

- **The inventory is a historical record, not authority.** Implementation authority stays in
  `docs/EXECUTION_PLAN.md` §0. Owner intake stays in `docs/OWNER_REQUESTED_TODO.md`, with verbatim owner records in
  `docs/owner/`. Where the inventory and a later recorded owner decision disagree, the later decision wins. Every row
  below cites the record that governs it.
- **Nothing here is a new owner decision.** No owner wording was invented. Open questions are listed as open (for
  example, Q2 stays `PROPOSED_PENDING_OWNER_Q2`).
- **Excluded:** the 2026-10-25 ChatGPT/plugin agent integration (PR #1921, branch `codex/chase-upside-private-mcp`).
  It was not researched, checked or counted. The inventory excludes it too.
- **No held flag was touched.** No login, credential or owner-held secret was used.

## 2. Method and evidence

1. **Every cited PR and issue** (128 numbers: 122 PRs and 6 issues) was read from the GitHub API: state, merge time, merge commit and file
   list. PR titles were not trusted for status.
2. **Code presence.** For every merged PR, each file it touched was checked on `origin/main` @ `503f08581b`
   (2026-10-25). 6 of the touched files are gone: they were deleted on purpose by later merged work in the same
   lane, for example `trade-retro-value.js`, `TradeDeltaHistogram.jsx` and `test_public_category_mapping.py`. None
   of them is a regression.
3. **Deployed tree.** Production `/api/status` reports `build.commit` **`40f5dc5694`** (2026-10-25 12:07 UTC). That
   commit is an ancestor of `origin/main`. **Every merge commit cited in the inventory is contained in it.** In other
   words, every merged item is in the deployed code. Whether it behaves correctly in production is a separate
   question, answered per row.
4. **Flags.** Defaults come from `src/api/feature_flags.py`. Held flags are enforced by
   `scripts/verify_owner_held_flags.py`. The effective production state is the `featureFlags` block of production
   `/api/status`, read 2026-10-25 15:32 UTC.
5. **Public production probes (read-only, no login):**
   - `/api/status` and `/api/health`;
   - `/api/public/league`, `/api/public/league/rosPower` and `/api/public/league/rosPlayoffOdds`;
   - `/api/public/league/trade-advisor/teams`;
   - `/api/public/waiver-compare` and `/waiver-wire/r7k4q9m2`;
   - the unauthenticated status code of `POST /api/trade/analyze-multi`;
   - the public Sleeper API (`/league/<id>/rosters`, `/traded_picks`), used to reconcile future pick ownership.
6. **Workflow runs** were read from `gh run list`, and the E2E Safety Net failure step from `gh run view --log-failed`.
7. **Facts supplied by the coordinator on 2026-10-25 and not re-observed here.** Each is labelled "(coordinator)"
   wherever it is used:
   - the three failed box units;
   - the forced-drop box replay digest `f10fc997`;
   - the waiver page's Sleeper ownership match (696 rostered / 228 waivers / 0 overlap) and its 0 formula
     violations.

### Status vocabulary

| Status | Meaning here |
|---|---|
| `VERIFIED_IN_CODE_AND_TESTS` | The cited PRs are merged and deployed. The owner code and its tests are on `origin/main`. Production behaviour is **not** separately proven unless the row lists a production observation. |
| `MERGED_PROD_UNVERIFIED` | Merged and deployed, but the requirement depends on runtime, box or session state that was not observed, or that is currently in doubt. |
| `DORMANT_FLAG_OFF` | Merged behind a default-OFF flag that is held. Production confirms the flag is OFF. Activation is a separate decision. |
| `PARTIAL` | Some of the requirement is merged. A named part remains. |
| `AWAITING_REVIEW` | The carrying PR is open. |
| `NOT_STARTED` | No implementation and no authorization found. |
| `BLOCKED_DEPENDENCY` | Waiting on an owner decision or action, time, data or another PR. |
| `DEFERRED_PAUSED` | Paused or parked by an explicit owner decision. |
| `SUPERSEDED` | Replaced by a later recorded decision. |
| `BROKEN_REGRESSED` | Observed failing now. |
| `UNVERIFIABLE` | Cannot be proven or disproven from the evidence available to this pass. |

## 3. Results


### 3.1 Summary count by status

| Status | Count | IDs |
|---|---|---|
| `VERIFIED_IN_CODE_AND_TESTS` | 56 | RIT-001, RIT-002, RIT-003, RIT-004, RIT-005, RIT-006, RIT-008, RIT-009, RIT-010, RIT-011, RIT-013, RIT-014, RIT-015, RIT-016, RIT-021, RIT-022, RIT-023, RIT-024, RIT-025, RIT-026, RIT-029, RIT-030, RIT-040, RIT-042, RIT-043, RIT-044, RIT-045, RIT-046, RIT-047, RIT-048, RIT-049, RIT-050, RIT-051, RIT-052, RIT-053, RIT-054, RIT-055, RIT-056, RIT-057, RIT-058, RIT-059, RIT-060, RIT-061, RIT-062, RIT-063, RIT-065, RIT-066, RIT-068, RIT-071, RIT-075, RIT-076, RIT-077, RIT-079, RIT-080, RIT-082, RIT-083 |
| `MERGED_PROD_UNVERIFIED` | 3 | RIT-012, RIT-027, RIT-028 |
| `DORMANT_FLAG_OFF` | 9 | RIT-017, RIT-018, RIT-019, RIT-020, RIT-031, RIT-032, RIT-038, RIT-064, RIT-070 |
| `PARTIAL` | 7 | RIT-007, RIT-035, RIT-036, RIT-037, RIT-039, RIT-072, RIT-084 |
| `AWAITING_REVIEW` | 2 | RIT-034, RIT-087 |
| `NOT_STARTED` | 1 | RIT-088 |
| `BLOCKED_DEPENDENCY` | 4 | RIT-033, RIT-041, RIT-067, RIT-081 |
| `DEFERRED_PAUSED` | 2 | RIT-085, RIT-086 |
| `SUPERSEDED` | 1 | RIT-069 |
| `BROKEN_REGRESSED` | 2 | RIT-073, RIT-078 |
| `UNVERIFIABLE` | 1 | RIT-074 |
| **Total** | **88** | |

### 3.2 Row by row

#### Trade discovery

**RIT-001 — Trade Finder constraint consistency** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Trade generators ignored some protections
- Final requirement (inventory): One canonical untouchable and LOCK/EXCLUDE policy across generators
- Inventory said: Approved; "Built in merged release work; live not verified" (Oct 14)
- PRs / issues (verified on GitHub): #1739 merged `138b0d08a7` (2026-10-14)
- Owner: `src/trade/constraints.py`; `frontend/lib/trade-refinement.js`
- Tests: `tests/trade/test_constraints_reach_every_generator.py`, `tests/trade/test_lock_exclude_refinement.py`, `tests/api/test_trade_protections_endpoint.py`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: Protected-asset replay per generator on the live board (not run here).

**RIT-002 — Trade Suggestions coverage** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Suggestions missed legitimate opportunities
- Final requirement (inventory): Repair opportunity enumeration and league roster coverage
- Inventory said: Approved; "Merged work; live not verified" (Oct 14)
- PRs / issues (verified on GitHub): #1739 merged `138b0d08a7` (2026-10-14)
- Owner: `src/trade/suggestions.py`
- Tests: `tests/trade/test_suggestions_coverage_and_diagnostics.py`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: League-wide coverage regression on the live board (not run here).

**RIT-003 — Best Trade to Send Each Team** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Offer genuinely viable trades to each opponent
- Final requirement (inventory): Use roster-aware meaningful deals including asymmetric piece counts and justified picks
- Inventory said: Approved; "Merged" (Oct 14)
- PRs / issues (verified on GitHub): #1741 merged `8e406f677f` (2026-10-14)
- Owner: `src/trade/best_offers.py` (`config/trade/best_offers_prior.json`)
- Tests: `tests/api/test_best_offers_endpoint.py`, `frontend/__tests__/components/best-offers-view.test.jsx`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: Per-partner live check (11 partners) not run here.

**RIT-004 — Golden Upgrades** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Find real roster upgrades rather than filler
- Final requirement (inventory): Select impactful upgrades; preserve constraints and avoid low-value filler
- Inventory said: Approved; "Merged underlying work" (Oct 14-18)
- PRs / issues (verified on GitHub): #1741 merged `8e406f677f` (2026-10-14); #1788 merged `0602333cef` (2026-10-18)
- Owner: `src/trade/golden_upgrades.py` (`config/trade/golden_upgrades.json`)
- Tests: `tests/api/test_golden_upgrades_endpoint.py`, `frontend/__tests__/components/golden-upgrades-view.test.jsx`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"; §0 "Trade Finder meaningful discovery — 2026-10-18"
- Next action: Quality review on real teams not run here.

**RIT-005 — Package Builder** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Construct strategic packages to acquire or sell
- Final requirement (inventory): Acquire Sell Improve modes; independent Sending and Receiving Offense/Defense/Both filters
- Inventory said: Approved; "Merged underlying work" (Oct 14-18)
- PRs / issues (verified on GitHub): #1741 merged `8e406f677f` (2026-10-14); #1746 merged `6be40a912c` (2026-10-15); #1789 merged `902e2553a2` (2026-10-18)
- Owner: `src/trade/package_builder.py`; `frontend/lib/package-builder.js`
- Tests: `tests/trade/test_package_builder_sides.py`, `frontend/__tests__/components/package-builder-sides.test.jsx`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"; §0 "Trade Finder meaningful discovery — 2026-10-18"
- Next action: Nine Sending×Receiving filter combinations are not individually pinned in what was read; confirm or add.

**RIT-006 — Best Offers threshold** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Absolute value opportunities hidden by percent rule
- Final requirement (inventory): Meaningful gain >=250 adjusted points qualifies even below 3.5 percent; FAIR classification independent
- Inventory said: Approved; "Merged" (Oct 18)
- PRs / issues (verified on GitHub): #1791 merged `2be548f517` (2026-10-18); #1794 merged `c290dea0a8` (2026-10-18)
- Owner: `config/trade/fairness_bands.json` (`absoluteMinimum: 250`, owner prior OD-F3); `src/trade/best_offers.py`
- Tests: `tests/trade/test_best_offers_meaningful_gain.py`
- Flag: none
- Authorization: §0 "Trade Finder meaningful discovery — 2026-10-18"; §0 "fairness_bands_v2 — 2026-10-20 (~19:45 UTC)"
- Next action: None beyond keeping the 249/250 boundary test.

**RIT-007 — Competitive posture and team context** · `PARTIAL`

- Original request: Trades should reflect contention/rebuild and roster goals
- Final requirement (inventory): Respect opponent competitive posture; Use Team Context; roster impacts and legal drops
- Inventory said: Approved; "Partially built; full behavior unverified" (Oct 14-20)
- PRs / issues (verified on GitHub): #1739 merged `138b0d08a7` (2026-10-14); #1741 merged `8e406f677f` (2026-10-14); #1890 merged `02725d18fe` (2026-10-21)
- Owner: `src/roster_intel/window.py::competitive_posture`; `src/trade/team_context.py`; `src/trade/roster_capacity.py`
- Tests: posture + capacity tests under `tests/roster_intel/`, `tests/trade/`
- Flag: `forced_drop_cheapest_legal` OFF (prod obs. 2026-10-25)
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"; §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved)
- Evidence note: Posture and Team Context are merged; the forced-drop correction is dormant and War Room Team Context is held until #1890 is settled (LVA-P4).
- Next action: Finish the forced-drop owner decision (RIT-031), then the held War Room Team Context.

**RIT-008 — Target Quality and Most Impactful** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Filter high percentage but inconsequential deals
- Final requirement (inventory): Expose meaningful target quality and impact sorting
- Inventory said: Approved; "Merged" (Oct 18)
- PRs / issues (verified on GitHub): #1788 merged `0602333cef` (2026-10-18); #1789 merged `902e2553a2` (2026-10-18)
- Owner: `frontend/lib/trade-discovery.js`; `config/trade/discovery_impact_prior.json`
- Tests: `frontend/__tests__/arbitrage-board-regression.test.js`, `tests/api/test_trade_discovery_endpoints.py`
- Flag: none
- Authorization: §0 "Trade Finder meaningful discovery — 2026-10-18"
- Next action: Spot-check against known trades (not run here).

**RIT-009 — Advanced mode separation** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Acquire Sell Improve should work predictably
- Final requirement (inventory): Distinct Package Builder search modes using same engine
- Inventory said: Approved; "PR evidence; live not verified" (Oct 14-18)
- PRs / issues (verified on GitHub): #1746 merged `6be40a912c` (2026-10-15)
- Owner: `src/trade/package_builder.py` (modes); `frontend/lib/package-builder.js`
- Tests: package-builder tests (see RIT-005)
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: None.

**RIT-010 — Trade Desk campaign** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Save potential offers and deal progress
- Final requirement (inventory): Private watchlist of trade ideas with user-entered status; no autonomous trades
- Inventory said: Approved; "PR evidence; live not verified" (Oct 14-15)
- PRs / issues (verified on GitHub): #1748 merged `b883e59c7f` (2026-10-16)
- Owner: `src/trade/trade_desk.py`; `frontend/lib/trade-desk.js`
- Tests: `tests/trade/test_trade_desk.py`, `tests/api/test_trade_desk_endpoint.py`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: Persistence check in a logged-in browser (not possible without credentials).

**RIT-011 — Comparable trades** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Provide actual relevant market precedents
- Final requirement (inventory): One canonical comparison engine; show as non-voting evidence
- Inventory said: Approved; "Merged" (Oct 14-15)
- PRs / issues (verified on GitHub): #1742 merged `1936a725dd` (2026-10-15); #1752 merged `f18df991e4` (2026-10-16)
- Owner: `src/trade/comparable_trades.py` (`config/trade/comparable_trades.json`)
- Tests: `tests/api/test_market_trade_comparable_endpoint.py`, `frontend/__tests__/components/comparable-trades.test.jsx`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Evidence note: Reads the box-local market-trade ledger; see RIT-012 for its refresh failure.
- Next action: None beyond RIT-073's ledger repair.

**RIT-012 — Trade Database** · `MERGED_PROD_UNVERIFIED`

- Original request: Search real completed deals and market evidence
- Final requirement (inventory): Canonical trade ledger with full comparable matching, not a second engine
- Inventory said: Approved; "Merged base work" (Oct 14-15)
- PRs / issues (verified on GitHub): #1742 merged `1936a725dd` (2026-10-15)
- Owner: `src/trade/market_trade_database.py`
- Tests: `tests/trade/test_market_trade_database.py`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Evidence note: Code is merged and deployed, but the box unit `dynasty-market-trade-ledger` timed out on 2026-10-25 (coordinator), so the database's data freshness is not current-verified.
- Next action: Repair the ledger unit (RIT-073), then audit search/filter coverage.

**RIT-013 — Manager Scout cards** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Use opponent tendencies inside offers
- Final requirement (inventory): Show manager-specific trade history in Best Offers and Package Builder
- Inventory said: Approved; "PR evidence; live not verified" (Oct 14-17)
- PRs / issues (verified on GitHub): #1745 merged `77d4c60b96` (2026-10-15)
- Owner: `frontend/lib/manager-evidence.js`; `frontend/components/trade/ManagerEvidence.jsx`
- Tests: `tests/intel/test_manager_scout_offer_evidence.py`, `frontend/__tests__/manager-evidence.test.js`
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: None.

**RIT-014 — Adversarial generator tests** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Avoid invalid or misleading offers
- Final requirement (inventory): Test locked players, picks, capacities, filters and full generator corpus
- Inventory said: Approved; "PR evidence; live not verified" (Oct 14-15)
- PRs / issues (verified on GitHub): #1749 merged `ec0aba47d3` (2026-10-16)
- Owner: (test deliverable)
- Tests: `tests/trade/test_trade_discovery_adversarial.py` (in the hard gate)
- Flag: none
- Authorization: §0 "Trade discovery — owner directive, 2026-10-14"
- Next action: Keep in the gate.

#### Trade calculator

**RIT-015 — Unified recommendation engine** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Trade Calculator must tell me YES or NO
- Final requirement (inventory): One private decision owner YES/NO/NO-TOO-CLOSE/NOT-ENOUGH-EVIDENCE and calibrated confidence
- Inventory said: Approved; "Merged" (Oct 18-19)
- PRs / issues (verified on GitHub): #1791 merged `2be548f517` (2026-10-18); #1853 merged `bb31542e6b` (2026-10-20)
- Owner: `src/trade/trade_decision.py` (one decision owner); `src/trade/analyze_service.py`
- Tests: decision tests under `tests/trade/`, `tests/fixtures/decision_engine/`
- Flag: none
- Authorization: §0 "Trade Calculator completion — 2026-10-17"
- Next action: None.

**RIT-016 — Fairness consistency** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Different trade surfaces had inconsistent bands
- Final requirement (inventory): fairness_bands_v2; gap divided by larger package utility; FAIR requires band fair for every team
- Inventory said: Approved; "Merged" (Oct 20-21)
- PRs / issues (verified on GitHub): #1886 merged `50614eb1ce` (2026-10-21); #1894 merged `9e3c52fdc6` (2026-10-21)
- Owner: `src/valuation_math/fairness_bands.py` + `config/trade/fairness_bands.json` (`fairness_bands_v2`, `PRIOR_OWNER_APPROVED_2026-10-20`); JS mirror `frontend/lib/fairness-bands.js`
- Tests: `tests/fixtures/fairness_band_cases.json` grid (both languages)
- Flag: none
- Authorization: §0 "fairness_bands_v2 — 2026-10-20 (~19:45 UTC)"
- Evidence note: OD-F4 post-launch validation is still PENDING by design.
- Next action: OD-F4 after any public launch.

**RIT-017 — Public Brisket Trade Advisor** · `DORMANT_FLAG_OFF`

- Original request: Make a simple public League Hub trade evaluator
- Final requirement (inventory): Same canonical private engine; public only Fair Trade/Not Fair/Unable to Determine; hide proprietary values/formulas
- Inventory said: Approved to build; launch reserved; "Merged; launch gate OFF in design" (Oct 19-20)
- PRs / issues (verified on GitHub): #1861 merged `9148ca9ba2` (2026-10-21); #1866 merged `b484775b57` (2026-10-21); #1894 merged `9e3c52fdc6` (2026-10-21)
- Owner: `src/trade/public_advisor.py`; `src/api/public_trade_advisor_api.py`; `config/trade/public_advisor.json`
- Tests: `tests/api/test_public_trade_advisor_*.py`, `tests/trade/test_public_advisor_*.py`
- Flag: `brisket_trade_advisor` OFF (prod obs. 2026-10-25); `GET /api/public/league/trade-advisor/teams` → 503 `advisor_unavailable` / `disabled`
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved)
- Next action: Owner decisions OD-3, AD-1, F-1, RF-1, LA-1 (see §5). No engineering activation.

**RIT-018 — Public vs private behavior** · `DORMANT_FLAG_OFF`

- Original request: Public answer not personalized accept/decline
- Final requirement (inventory): Fairness-only public; sophisticated directional YES/NO private; shared calculations
- Inventory said: Approved; "Merged" (Oct 20)
- PRs / issues (verified on GitHub): #1861 merged `9148ca9ba2` (2026-10-21); #1866 merged `b484775b57` (2026-10-21)
- Owner: `src/trade/public_advisor.py` (fairness-only) vs `src/trade/trade_decision.py` (private YES/NO)
- Tests: `tests/api/test_public_trade_advisor_privacy.py`, `tests/trade/test_public_advisor_withheld_values.py`
- Flag: `brisket_trade_advisor` OFF (prod obs. 2026-10-25)
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved)
- Evidence note: The private YES/NO side is live; the public side is dormant.
- Next action: Same as RIT-017.

**RIT-019 — Multi-team routed trades** · `DORMANT_FLAG_OFF`

- Original request: True 2/3/4-team trades must be evaluated
- Final requirement (inventory): Canonical routed asset ledger; ownership, side binding, per-team decisions, per-team fairness
- Inventory said: Approved; "Merged; private flag default OFF" (Oct 19-20)
- PRs / issues (verified on GitHub): #1882 merged `19bc344a00` (2026-10-21); #1883 merged `f86f37b2df` (2026-10-21); #1894 merged `9e3c52fdc6` (2026-10-21)
- Owner: `src/trade/trade_ledger.py`; `src/trade/analyze_service.py::analyze_trade_n`; `src/trade/team_verdicts.py`
- Tests: `tests/trade/test_trade_ledger.py`, `tests/api/test_trade_analyze_multi_route.py`, `tests/fixtures/multi_team_trade_parity_cases.json`
- Flag: `trade_multi_team_analysis` OFF (prod obs. 2026-10-25); `POST /api/trade/analyze-multi` → 401 unauthenticated
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved)
- Evidence note: E2E Safety Net (#1918) fails on `trade-multi-team.spec.js` (2 journeys) every day since 2026-10-22; the failing step is a pick search (`2027 Mid 1st (from Kich)` not found), which points at test-data drift, not yet confirmed.
- Next action: Fix the E2E journeys; run multi-team Lane E QA (claim row, not started); then enable through the normal release process (spec §6.1).

**RIT-020 — Multi-team private War Room** · `DORMANT_FLAG_OFF`

- Original request: Deep 3+ team suggestions and explanations
- Final requirement (inventory): Server analysis and preliminary per-team meter; avoid browser-only pseudo-analysis
- Inventory said: Approved to build; activation reserved; "Merged; flag OFF" (Oct 20)
- PRs / issues (verified on GitHub): #1883 merged `f86f37b2df` (2026-10-21); #1894 merged `9e3c52fdc6` (2026-10-21)
- Owner: `frontend/components/trade/MultiTeamWarRoom.jsx`; `frontend/lib/trade-multi-team.js`; `frontend/lib/trade-team-binding.js`
- Tests: `frontend/__tests__/components/multi-team-war-room.test.jsx`, `tests/e2e/specs/trade-multi-team*.spec.js`
- Flag: `trade_multi_team_analysis` OFF (prod obs. 2026-10-25)
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved)
- Evidence note: Same red E2E journeys as RIT-019.
- Next action: Same as RIT-019.

**RIT-021 — Shared engine identity defects** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Wrong Byron Murphy priced and Alim McNeill absent
- Final requirement (inventory): Resolve exact Sleeper player IDs; fail closed on ambiguous identities
- Inventory said: Approved; "Merged" (Oct 19-20)
- PRs / issues (verified on GitHub): #1853 merged `bb31542e6b` (2026-10-20)
- Owner: `src/api/trade_simulator.py` (id-first resolution); `src/trade/valuation_scope.py`
- Tests: `tests/api/test_trade_simulator_player_ids.py`
- Flag: none
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved) (B0)
- Next action: None.

**RIT-022 — Pick identity and values** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Mispriced or missing picks in trade components
- Final requirement (inventory): Resolve pick asset ID first, slot fallback only per contract; shared float VA handling
- Inventory said: Approved; "Merged" (Oct 19-20)
- PRs / issues (verified on GitHub): #1853 merged `bb31542e6b` (2026-10-20)
- Owner: `src/identity/picks.py::lookup_league_pick_owner`; `src/api/trade_simulator.py`
- Tests: `tests/api/test_trade_simulator_pick_identity.py`, `tests/valuation_math/test_package_model_float.py`
- Flag: none
- Authorization: §0 "Brisket Trade Advisor completion and multi-team trade support — 2026-10-20" (public launch owner-reserved) (B0)
- Next action: None.

**RIT-023 — Value Adjustment package model** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Avoid inconsistent package math across tools
- Final requirement (inventory): One sitewide versioned model, geom_q078_v1 q=.78 champion; not KTC value blend
- Inventory said: Approved; "Merged; production champion reported" (Oct 17-21)
- PRs / issues (verified on GitHub): #1768 merged `00d652bd21` (2026-10-17); #1771 merged `f57775c65c` (2026-10-17); #1833 merged `20a5a51934` (2026-10-21)
- Owner: `src/valuation_math/package_model.py`; `config/trade/package_model.json` (`active: geom_q078_v1`); JS `frontend/lib/trade-logic.js::packageAdjustPair`
- Tests: `tests/valuation_math/test_package_model.py`, `frontend/__tests__/package-model.test.js`
- Flag: none
- Authorization: §0 "Sitewide trade Value Adjustment package — 2026-10-17"; §0 "Hybrid Value Adjustment research — 2026-10-19" + LVA P2/P5C
- Evidence note: #1833 / #1913 research: KEEP `geom_q078_v1`.
- Next action: None (keep unchanged).

**RIT-024 — Second Opinions** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Show alternate source perspectives without corrupting votes
- Final requirement (inventory): Display raw source and canonical fallback; source and our VA correctly labeled; KTC-adjustment comparison
- Inventory said: Approved; "Merged base work" (Oct 17-19)
- PRs / issues (verified on GitHub): #1765 merged `2fc379a31a` (2026-10-17); #1826 merged `629069c284` (2026-10-19); #1836 merged `f3e24b3470` (2026-10-19)
- Owner: `frontend/lib/second-opinions.js`; `frontend/lib/va-comparison.js`
- Tests: `frontend/__tests__/components/second-opinions-*.test.jsx`, `frontend/__tests__/va-comparison.test.js`
- Flag: none
- Authorization: §0 "Sitewide trade Value Adjustment package — 2026-10-17"; §0 "Trade Calculator clarity, dual Value Adjustment and speed — 2026-10-19"
- Evidence note: Three superseded Second-Opinions test files were deleted inside the same PRs (not a regression).
- Next action: None.

**RIT-025 — History trade grading** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Historical valuation is not forward outcome
- Final requirement (inventory): Current, At-the-Time, How It Aged; adjusted nets; rename Fair trade tier Evenly valued without numeric changes
- Inventory said: Approved; "Merged" (Oct 17-21)
- PRs / issues (verified on GitHub): #1766 merged `118b143f28` (2026-10-17); #1906 merged `7fba86159c` (2026-10-21)
- Owner: `src/api/trade_history_asof.py`; `frontend/lib/trade-history-grades.js`; `frontend/lib/trade-history-grade-policy.js`
- Tests: `tests/api/test_trade_history_asof.py`, `tests/public_league/test_history_grade_relabel_no_change.py`
- Flag: none
- Authorization: §0 "Sitewide trade Value Adjustment package — 2026-10-17"; §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P2)
- Next action: None.

**RIT-026 — Trade War Room usability** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Need clear advice not contradictory numbers
- Final requirement (inventory): Plain-English one recommendation; honest loading, faster analysis, accountable limitations
- Inventory said: Approved; "Merged" (Oct 18-20)
- PRs / issues (verified on GitHub): #1827 merged `9b82be7812` (2026-10-19); #1828 merged `41472374f6` (2026-10-19); #1869 merged `f02689ee92` (2026-10-20)
- Owner: `frontend/lib/trade-war-room-copy.js`; `src/api/trade_analyze_runtime.py`
- Tests: `frontend/__tests__/trade-war-room-plain.test.js`, `tests/api/test_trade_analyze_runtime.py`
- Flag: none
- Authorization: §0 "Trade Calculator clarity, dual Value Adjustment and speed — 2026-10-19"
- Next action: Mobile latency check (not run here).

**RIT-027 — Calculator workspace redesign** · `MERGED_PROD_UNVERIFIED`

- Original request: Polish premium UI and avoid stale results
- Final requirement (inventory): Sequenced requests, immediate vs expensive results, correct errors, mobile and accessibility
- Inventory said: Approved; "Merged" (Oct 18-20)
- PRs / issues (verified on GitHub): #1800 merged `46be90076d` (2026-10-18); #1805 merged `335ab25c39` (2026-10-18); #1814 merged `1d56cacfc0` (2026-10-18); #1824 merged `7454511ffc` (2026-10-19)
- Owner: `frontend/app/trade/` (`trade-layout.jsx`, `trade-asset-sheet.jsx`); `frontend/lib/trade-package-facts.js`
- Tests: `frontend/__tests__/components/trade-tcd2.test.jsx`, `tests/e2e/specs/trade-tcd2.spec.js`
- Flag: none
- Authorization: §0 "Trade Calculator completion — 2026-10-17"
- Evidence note: Merged and deployed, but the TC-D2 E2E journey (`trade-tcd2.spec.js:61`, 3-team summary) fails daily since 2026-10-22 in #1918, same pick-search step as RIT-019.
- Next action: Fix the red journey, then smoke-test.

**RIT-028 — Screenshot import** · `MERGED_PROD_UNVERIFIED`

- Original request: Paste screenshots of offers from other sites
- Final requirement (inventory): PNG/JPEG/WEBP/multiple sides; OCR/vision extraction; reconcile canonical identities and edits
- Inventory said: Approved; "Merged code; OCR server availability requires verification" (Oct 15-19)
- PRs / issues (verified on GitHub): #1751 merged `721f91ef28` (2026-10-16); #1816 merged `b15f38acf1` (2026-10-18); #1841 merged `03741f08ca` (2026-10-20)
- Owner: `src/trade/screenshot_import/`; `frontend/lib/screenshot-import.js`
- Tests: `tests/trade/screenshot_import/`, `frontend/__tests__/screenshot-import.test.js`
- Flag: `trade_screenshot_import` ON (prod obs. 2026-10-25)
- Authorization: §0 "Universal Trade Screenshot Import (C3-IMPORT-IMAGE) — 2026-10-15"
- Evidence note: The owner reported Tesseract 5.3.4 installed on 2026-10-18 (`docs/ops/ADMIN_ONLY_ACTIONS_RUNBOOK.md` §4); the status route is auth-gated, so OCR availability and real phone screenshots were not observed here.
- Next action: Post-install recognition check with real phone screenshots (needs a logged-in session).

**RIT-029 — KTC trade URL import** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Import KTC offers after upstream map changes
- Final requirement (inventory): Repair parsing and canonical player mapping
- Inventory said: Approved bug fix; "Release PR evidence; live not verified" (Oct 11-13)
- PRs / issues (verified on GitHub): #1731 merged `7f5f7378d7` (2026-10-14); #1737 merged `5d7dc8f4f9` (2026-10-14)
- Owner: `frontend/lib/ktc-import.js`; `frontend/app/api/trade/export-ktc/route.js`
- Tests: `tests/trade/test_ktc_import_player_map.py`, `frontend/__tests__/ktc-import.test.js`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Next action: Replay a current KTC link (fixtures are from 2026-10-13).

**RIT-030 — Fairness and historical labels** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Do not conflate fairness with realized success
- Final requirement (inventory): One market FAIR calculation across 2/3/4 teams; distinguish Evenly valued history
- Inventory said: Approved; "Audit/label changes merged" (Oct 20-21)
- PRs / issues (verified on GitHub): #1889 merged `9c05f1e9fd` (2026-10-21); #1906 merged `7fba86159c` (2026-10-21)
- Owner: `scripts/public_fairness_audit.py`; `frontend/lib/trade-history-grade-policy.js`
- Tests: `frontend/__tests__/history-grade-relabel-no-change.test.js`
- Flag: none
- Authorization: §0 "fairness_bands_v2 — 2026-10-20 (~19:45 UTC)"; §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P2)
- Next action: None.

**RIT-031 — Forced-drop correctness** · `DORMANT_FLAG_OFF`

- Original request: Alphabetical sub-waiver cut and inconsistent unpriced charge
- Final requirement (inventory): Prefer cheapest legal package-consistent cut V5-R; respect roster limits; never silently zero unknowns
- Inventory said: Approved dormant only; "Merged; forced_drop_cheapest_legal OFF" (Oct 20-21)
- PRs / issues (verified on GitHub): #1890 merged `02725d18fe` (2026-10-21); #1912 merged `408742c992` (2026-10-21); #1916 merged `e6dd949693` (2026-10-21)
- Owner: `src/trade/forced_drop_selection.py`; `src/trade/roster_capacity.py`
- Tests: `tests/trade/test_forced_drop_selection.py`, `tests/trade/test_forced_drop_flag_off_identity.py`, `tests/trade/test_forced_drop_box_mode.py`
- Flag: `forced_drop_cheapest_legal` OFF (prod obs. 2026-10-25); held by `scripts/verify_owner_held_flags.py`
- Authorization: §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P1)
- Evidence note: The pinned read-only box replay finished 2026-10-22/23 with digest `f10fc997` and identical live inputs (coordinator); its evidence PR is in progress.
- Next action: Land the replay evidence, then the activation request to the owner.

**RIT-032 — Low-value depth note** · `DORMANT_FLAG_OFF`

- Original request: Need contextual warning for shallow-value filler
- Final requirement (inventory): Informational only; private shadow measurement, no new haircut or public formula exposure
- Inventory said: Approved research/shadow; "Shadow PR merged; display OFF" (Oct 20-21)
- PRs / issues (verified on GitHub): #1887 merged `eac2fbc16e` (2026-10-21); #1908 merged `e4b613efcf` (2026-10-21)
- Owner: `src/trade/depth_disclosure.py`; `src/trade/depth_disclosure_shadow.py`; design `docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md`
- Tests: `tests/trade/test_depth_disclosure*.py`, `tests/api/test_depth_disclosure_shadow_hold_locked.py`
- Flag: `low_value_depth_disclosure_shadow` OFF (prod obs. 2026-10-25); held at deploy
- Authorization: §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P4)
- Evidence note: No display exists, by decision.
- Next action: Owner G3 decision to start the shadow window.

**RIT-033 — Package model market-ledger evaluation** · `BLOCKED_DEPENDENCY`

- Original request: Validate geometric model with completed trade data
- Final requirement (inventory): Read-only archive/ledger evaluation, preserve q=.78 and incumbent
- Inventory said: Approved research; "PR #1873 open" (Oct 19-21)
- PRs / issues (verified on GitHub): #1833 merged `20a5a51934` (2026-10-21); #1873 PR open; #1913 merged `084c9c2bd9` (2026-10-21)
- Owner: `scripts/package_model_*.py` research; pinned command `docs/ops/PACKAGE_MODEL_PROSPECTIVE_RERUN_COMMAND_2026-11.md`
- Tests: `tests/scripts/test_package_model_*.py`
- Flag: none
- Authorization: §0 "Hybrid Value Adjustment research — 2026-10-19" + LVA P2/P5C; §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P5C)
- Evidence note: #1873 stays open and unmerged by owner decision; the prospective re-run needs ≥ 2,000 unequal-count trades after 2026-10-20 and a separate owner authorization.
- Next action: Wait for the data, then ask the owner to authorize the box run.

#### League models

**RIT-034 — Live scoring and rules fingerprint** · `AWAITING_REVIEW`

- Original request: All player advice must respect exact scoring
- Final requirement (inventory): Fetch 2026 Sleeper scoring/settings; compare snapshots and reconcile all actual awarded player-weeks
- Inventory said: Approved mandate; "Issue open, audit PR open" (Oct 19)
- PRs / issues (verified on GitHub): issue #1842 open; #1843 PR open
- Owner: audit PR #1843 (`audit(league)` branch); `src/league_comparison/sleeper_scoring.py::scoring_fingerprint` is the existing owner
- Tests: on the open PR
- Flag: none
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass)
- Evidence note: Issue #1842 and PR #1843 are both open.
- Next action: Review/land #1843 and finish the live parity audit.

**RIT-035 — League-specific value layers** · `PARTIAL`

- Original request: Market, league and roster values differ
- Final requirement (inventory): Independent market benchmark + league scoring, position demand, scarcity and roster fit; prevent double counting
- Inventory said: Approved research; "Partial shadow research merged; not served" (Oct 19-21)
- PRs / issues (verified on GitHub): issue #1842 open; #1856 merged `a7301e6da3` (2026-10-20); #1862 merged `18ae2ce5c3` (2026-10-20)
- Owner: `src/league_valuation/` (shadow challenger, `config/league_valuation/fair_value_v1.json`); `src/trade/decision_engine/`
- Tests: `tests/league_valuation/`
- Flag: none (shadow, not served)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass)
- Next action: Calibration and the preregistered holdout evaluation.

**RIT-036 — Best Ball true marginal value** · `PARTIAL`

- Original request: True Best Ball changes positional utility
- Final requirement (inventory): Paired simulations, legal lineup resolution and best unowned replacement; marginal F(R)-F(R-p+replacement)
- Inventory said: Approved research; "Offline library merged; no promotion" (Oct 19-21)
- PRs / issues (verified on GitHub): #1859 merged `2643c6a0c5` (2026-10-20)
- Owner: `src/bestball/` (`marginal.py`, `replacement.py`, `config/bestball/marginal_v1.json`)
- Tests: `tests/bestball/`
- Flag: none (offline library, no consumer)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass)
- Next action: Benchmark against real outcomes before any consumer.

**RIT-037 — Replacement-level LI-5 consolidation** · `PARTIAL`

- Original request: Unified trustworthy replacement evidence
- Final requirement (inventory): One helper and population builder preserving consumer-specific cohorts; no scarcity activation
- Inventory said: Approved P1-P2 only; "Merged but unwired" (Oct 21)
- PRs / issues (verified on GitHub): #1899 merged `7d1cc3f026` (2026-10-21); #1909 merged `6d841a1f17` (2026-10-21)
- Owner: `src/draft/waiver_population.py` (`POPULATION_RULE = li5_waiver_tier_v1`)
- Tests: `tests/draft/test_waiver_population.py`
- Flag: none yet (unwired)
- Authorization: §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P3)
- Evidence note: Design phases P1–P2 merged unwired (#1909). P3 was to start only after #1890 merged; #1890 merged 2026-10-21, P3 has not started.
- Next action: Confirm P3 is in scope, then build it behind its default-OFF flag.

**RIT-038 — Low-value league-aware depth evidence** · `DORMANT_FLAG_OFF`

- Original request: Depth can matter in deep roster league
- Final requirement (inventory): Shadow counters only, private and default OFF
- Inventory said: Approved shadow; "Merged; shadow only" (Oct 21)
- PRs / issues (verified on GitHub): #1908 merged `e4b613efcf` (2026-10-21)
- Owner: same owner as RIT-032
- Tests: same as RIT-032
- Flag: `low_value_depth_disclosure_shadow` OFF (prod obs. 2026-10-25)
- Authorization: §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P4)
- Evidence note: Same flag and code as RIT-032; tracked separately in the inventory.
- Next action: Same as RIT-032.

**RIT-039 — Decision engine v3 challenger** · `PARTIAL`

- Original request: Weight every validated factor defensibly
- Final requirement (inventory): Derived-evidence lineage, avoid overlapping signals and arbitrary stacked weights; promote only on holdouts
- Inventory said: Approved research; "Merged shadow library; inactive" (Oct 19-21)
- PRs / issues (verified on GitHub): #1862 merged `18ae2ce5c3` (2026-10-20)
- Owner: `src/trade/decision_engine/` (v3 shadow); `src/evidence_lineage/registry.py`
- Tests: `tests/trade/decision_engine/`, `tests/evidence_lineage/`
- Flag: none (shadow library, inactive)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass)
- Next action: Holdout validation against the private champion.

**RIT-040 — Knowledge cutoff replay** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Prevent hindsight leakage in backtesting
- Final requirement (inventory): Bitemporal knowledge cutoff and stale-read guards, default byte-identical
- Inventory said: Approved; "Merged from release train" (Oct 19-20)
- PRs / issues (verified on GitHub): #1864 merged `278a852a78` (2026-10-20); #1875 merged `9d07b9cebf` (2026-10-20)
- Owner: `src/history/asof.py` (knowledge_cutoff)
- Tests: `tests/history/test_asof_knowledge_cutoff.py`, `tests/trade/test_decision_replay_staleness.py`
- Flag: none (default byte-identical)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass)
- Next action: Extend replay tests as consumers adopt it.

**RIT-041 — Projection providers** · `BLOCKED_DEPENDENCY`

- Original request: Need league-scored ROS offense and IDP inputs
- Final requirement (inventory): Audit SportsDataIO/Fantasy Nerds adapter readiness, rights, coverage, correlation and uncertainty
- Inventory said: Research authorized; "Issue open / adapters flagged off" (Oct 19)
- PRs / issues (verified on GitHub): issue #1842 open; #1843 PR open
- Owner: projection adapters behind `sportsdataio_weekly_projections` / `fantasynerds_weekly_projections`
- Tests: —
- Flag: both OFF, gate status `UNREACHABLE` (prod obs. 2026-10-25)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass) (no paid data without the owner)
- Evidence note: Research rides the open #1843.
- Next action: Owner licence/spend decision; quality checks first.

**RIT-042 — Jaxson Dart availability** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Injured player incorrectly selected for simulated lineups
- Final requirement (inventory): Player-week injury/bye calendar, no points when unavailable, invalidate stale sim results
- Inventory said: Approved P0; "Merged" (Oct 17-18)
- PRs / issues (verified on GitHub): #1772 merged `6c3862dc77` (2026-10-18); #1774 merged `64e0d8c088` (2026-10-18); #1775 merged `066869d8c9` (2026-10-18)
- Owner: `src/ros/availability.py`; `src/nfl_data/injury_return_evidence.py`; `src/ros/game_day_week.py`
- Tests: `tests/ros/test_availability.py`, `tests/ros/test_playoff_presim_availability.py`, `tests/roster_intel/test_best_ball_availability.py`
- Flag: none
- Authorization: owner P0 report recorded on PR #1772 (no separate §0 entry found)
- Next action: Backtest against the live injuries feed (not run here).

**RIT-043 — Playoff double-count and manager attribution** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Probabilities should match roster and not double count ROS
- Final requirement (inventory): Evidence-gated incumbent until fix proven; playoff/title odds follow roster rather than manager
- Inventory said: Approved repairs; "Merged underlying work" (Oct 18-19)
- PRs / issues (verified on GitHub): #1821 merged `7941b37904` (2026-10-19); #1822 merged `302180d525` (2026-10-19)
- Owner: `src/public_league/playoff_odds.py`; `src/public_league/luck.py`
- Tests: `tests/ros/test_one_playoff_engine.py` and the #1822 tests
- Flag: `playoff_ros_counted_once` OFF (evidence-gated incumbent kept, D11)
- Authorization: §0 "Owner decision closeout + evidence unblock — 2026-10-18 (D1–D20)" (D11/D12)
- Evidence note: prod obs. 2026-10-25: `rosPlayoffOdds` 2,000 sims, converged; rosters 11/12 named John / schoeppeya.
- Next action: None.

**RIT-044 — Power Ranking roster identity** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Ownership handoffs corrupted rankings
- Final requirement (inventory): Attribute through roster and correct week-aware owner identities
- Inventory said: Approved fix; "Merged" (Oct 18-21)
- PRs / issues (verified on GitHub): #1834 merged `3f01c753e7` (2026-10-19); #1893 merged `85ee05620e` (2026-10-21)
- Owner: `src/ros/power_v2.py`; `src/ros/power_snapshots.py`
- Tests: `tests/ros/test_power_v2_roster_handoff.py`
- Flag: none
- Authorization: §0 "League manager replacement — 2026-10-16 (corrected 2026-10-17)"
- Evidence note: prod obs. 2026-10-25: `rosPower` names roster 11 John and roster 12 schoeppeya.
- Next action: Week-by-week historical reconciliation not done here.

#### League data

**RIT-045 — Manager handoff on roster 11** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Joel to John midseason
- Final requirement (inventory): From week 6 identify John/Jnesselhauf without rewriting historical roster identity
- Inventory said: Approved; "PR/release work evidenced" (Oct 17)
- PRs / issues (verified on GitHub): #1761 merged `7bafeb8862` (2026-10-17)
- Owner: `src/public_league/ownership.py`; `config/leagues/roster_ownership_changes.json`
- Tests: `tests/public_league/test_roster_handoff.py`
- Flag: none
- Authorization: §0 "League manager replacement — 2026-10-16 (corrected 2026-10-17)"
- Evidence note: prod obs. 2026-10-25: current surfaces name John. Historical weeks not re-checked.
- Next action: None.

**RIT-046 — Roster 12 owner handoff** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Blaine to schoeppeya from week 7
- Final requirement (inventory): Week-aware owner attribution with ownerless fallbacks
- Inventory said: Approved; "PR/release work evidenced" (Oct 20-21)
- PRs / issues (verified on GitHub): #1891 merged `d2e043762b` (2026-10-21); #1893 merged `85ee05620e` (2026-10-21); #1870 merged `1eec968a3a` (2026-10-20)
- Owner: `src/public_league/ownership.py` (week-aware); `config/leagues/roster_ownership_changes.json`
- Tests: `tests/public_league/test_roster12_handoff.py`, `tests/public_league/test_week_aware_owner_attribution.py`
- Flag: none
- Authorization: §0 "League manager replacement — 2026-10-16 (corrected 2026-10-17)"
- Evidence note: prod obs. 2026-10-25: current surfaces name schoeppeya. The effectiveWeek 7 was derived from evidence and is still OPEN for owner confirmation (`docs/OWNER_REQUESTED_TODO.md`).
- Next action: Owner to confirm the cutover week.

#### Draft

**RIT-047 — Canonical future pick ownership** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Draft page incorrectly shows historical owners
- Final requirement (inventory): Single canonical ownership fold and fail-closed if Sleeper traded_picks unavailable
- Inventory said: Approved P0; "Merged work" (Oct 17-19)
- PRs / issues (verified on GitHub): #1769 merged `0b3194f190` (2026-10-17); #1785 merged `deb50ca9b5` (2026-10-18); #1840 merged `c49ebec9c2` (2026-10-20)
- Owner: `src/identity/picks.py` (`build_pick_ownership`, `traded_picks_observation`); `src/public_league/draft.py::pick_inventory`
- Tests: `tests/public_league/test_draft_pick_ownership.py`, `tests/api/test_draft_capital_workbook_pick_ownership.py`
- Flag: none
- Authorization: §0 "Repository audit next batch — 2026-10-16"; §0 "Draft valuation automation — 2026-10-18" + "Whole-dollar rookie-draft allocation — 2026-10-18"
- Evidence note: prod obs. 2026-10-25: `/api/public/league` draft = `observed`, integrity ok; all 216 future picks (2027–2029 × 6 rounds × 12) match a fold of live Sleeper `/traded_picks` (93 rows), 0 mismatches.
- Next action: None.

**RIT-048 — Future pick horizon** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Make future classes current
- Final requirement (inventory): Latest completed draft plus 3 classes
- Inventory said: Approved; "Merged" (Oct 19)
- PRs / issues (verified on GitHub): #1844 merged `2d7a21c1bb` (2026-10-20)
- Owner: `src/identity/pick_lifecycle.py::board_pick_horizon`
- Tests: `tests/identity/test_pick_lifecycle.py`
- Flag: none
- Authorization: §0 "Site completion and universal source voting — 2026-10-19" (owner decision 2026-10-19)
- Evidence note: prod obs. 2026-10-25: public inventory covers 2027–2029.
- Next action: Check the rollover when the 2027 draft completes.

**RIT-049 — Rookie auction dollars** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Draft Data workbook and chart must match
- Final requirement (inventory): $1,200 per draft class, whole dollars, 72 slots, constrained minimization, monotone picks, preserve fractional reference values
- Inventory said: Approved; "Merged code; production promotion evidence needed" (Oct 18)
- PRs / issues (verified on GitHub): #1786 merged `e51db42b35` (2026-10-18)
- Owner: `src/draft/rookie_auction/` (`apportion.py`, `published.py`, `generation.py`)
- Tests: `tests/draft_valuation/test_constrained_whole_dollars.py`, `tests/draft_valuation/test_workbook_parity.py`, `tests/draft_valuation/test_curve_properties.py`
- Flag: `rookie_auction` ON (prod obs. 2026-10-25)
- Authorization: §0 "Draft valuation automation — 2026-10-18" + "Whole-dollar rookie-draft allocation — 2026-10-18"
- Evidence note: The $1,200 total and workbook parity are pinned by tests; the served total was not observed (auth-gated).
- Next action: Read the served board once logged in.

**RIT-050 — Rookie classes and rollover** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Do not break next-year prices
- Final requirement (inventory): Class readiness gates, last known-good, future classes, policy-driven promotion and dry run
- Inventory said: Approved; "Merged dry-run services" (Oct 18-19)
- PRs / issues (verified on GitHub): #1799 merged `9ef02bc094` (2026-10-18); #1802 merged `6f0efe3c7c` (2026-10-18); #1806 merged `5753f510e5` (2026-10-18)
- Owner: `src/draft/rookie_auction/promotion.py`; `config/draft_valuation/promotion_policy.json`
- Tests: `tests/draft_valuation/test_batch_d_promotion.py`
- Flag: `promotionMode` dry run
- Authorization: §0 "Draft valuation automation — 2026-10-18" + "Whole-dollar rookie-draft allocation — 2026-10-18"
- Evidence note: Issue #1807 reports 2027 `FALLBACK_VERIFIED` in dry run; the class window opens 2027-05-01.
- Next action: None until the window opens.

**RIT-051 — Draft capital valuation** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Multi-year picks as trade assets
- Final requirement (inventory): Curve values by draft class and actual ownership
- Inventory said: Approved; "Merged underlying work" (Oct 18)
- PRs / issues (verified on GitHub): #1802 merged `6f0efe3c7c` (2026-10-18); #1806 merged `5753f510e5` (2026-10-18)
- Owner: `src/api/draft_capital_classes.py`; `src/draft/rookie_auction/generation.py`
- Tests: `tests/api/test_draft_capital_all_years.py`, `tests/api/test_draft_capital_batch_f.py`
- Flag: none
- Authorization: §0 "Draft valuation automation — 2026-10-18" + "Whole-dollar rookie-draft allocation — 2026-10-18"
- Next action: None.

**RIT-052 — Draft transition observability** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Know why a class is fallback
- Final requirement (inventory): Readiness status and state transitions without premature 2027 opening
- Inventory said: Approved; "Open tracking issue" (Oct 18)
- PRs / issues (verified on GitHub): issue #1807 open
- Owner: `scripts/draft_valuation.py status`; Batch D/F state-transition alerts
- Tests: `tests/draft_valuation/test_batch_d_promotion.py`
- Flag: none
- Authorization: §0 "Draft valuation automation — 2026-10-18" + "Whole-dollar rookie-draft allocation — 2026-10-18"
- Evidence note: Issue #1807 is the state-transition notification channel (open by design): `NONE -> FALLBACK_VERIFIED`, gate `class_window_open` closed until 2027-05-01.
- Next action: Nothing until 2027-05-01.

#### Managers

**RIT-053 — Username Sleeper portfolio** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Track a manager across dynasty leagues
- Final requirement (inventory): Username lookup, owned players, multiple leagues and recent activity
- Inventory said: Approved prompt; "Merged manager-intel work" (Oct 17)
- PRs / issues (verified on GitHub): #1762 merged `048bcbf8ab` (2026-10-17)
- Owner: `src/intel/manager_portfolio.py`; `src/intel/manager_intel_api.py`
- Tests: `tests/intel/test_manager_portfolio.py`, `tests/intel/test_manager_intel_api.py`
- Flag: `manager_intelligence` ON (prod obs. 2026-10-25)
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: Rate-limit behaviour under load not observed.

**RIT-054 — Recent trades and activity feed** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Manager intelligence needs timelines
- Final requirement (inventory): Recent trades, acquired players, unified activity
- Inventory said: Approved; "Release work evidenced" (Oct 17-18)
- PRs / issues (verified on GitHub): #1779 merged `1ca3abbab1` (2026-10-18)
- Owner: `src/intel/manager_activity.py`
- Tests: `tests/intel/test_manager_activity.py`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-055 — Opponent scouting league-wide** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Know how league partners behave
- Final requirement (inventory): Opponent tendencies and profile linked from trade tools
- Inventory said: Approved; "Release work evidenced" (Oct 17-18)
- PRs / issues (verified on GitHub): #1783 merged `ec7d56ef5d` (2026-10-18)
- Owner: `src/intel/manager_league.py`
- Tests: `tests/intel/test_manager_league.py`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-056 — Manager draft capital and tendencies** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Opponent has pick holdings and trade patterns
- Final requirement (inventory): Actual future picks and trade tendencies in profile and trade surfaces
- Inventory said: Approved; "Release work evidenced" (Oct 18)
- PRs / issues (verified on GitHub): #1781 merged `013f581194` (2026-10-18)
- Owner: `src/intel/manager_trade_intel.py`
- Tests: `tests/intel/test_manager_trade_intel.py`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-057 — Career records/archetypes** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Manager comparisons and archetypes
- Final requirement (inventory): Career trade record, manager archetypes, comparable owners
- Inventory said: Approved; "Release work evidenced" (Oct 18)
- PRs / issues (verified on GitHub): #1796 merged `426496dc9c` (2026-10-18)
- Owner: `src/intel/manager_career.py`; `src/intel/manager_compare.py`
- Tests: `tests/intel/test_manager_career.py`, `tests/intel/test_manager_compare.py`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-058 — Seed trade tools from scout** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Quickly turn scouting into proposal
- Final requirement (inventory): Scouted manager/roster seeds calculators and offers
- Inventory said: Approved; "Release work evidenced" (Oct 18)
- PRs / issues (verified on GitHub): #1797 merged `90e9ca2da1` (2026-10-18)
- Owner: `frontend/lib/manager-trade-tools.js`
- Tests: `frontend/__tests__/manager-trade-tools.test.js`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-059 — Saved managers/activity alerts** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Follow notable owner transactions
- Final requirement (inventory): Saved profiles, new-activity alerts and scoped leaderboards
- Inventory said: Approved; "Merged" (Oct 18)
- PRs / issues (verified on GitHub): #1801 merged `6e97d43afc` (2026-10-18)
- Owner: `src/intel/manager_alerts.py`; `frontend/lib/manager-saved.js`
- Tests: `tests/intel/test_manager_alerts.py`, `tests/intel/test_manager_saved.py`
- Flag: `manager_intelligence` ON
- Authorization: §0 "Manager Intelligence (Batch A) — 2026-10-16" + intake "Added 2026-10-17 — Manager Intelligence addendum: Batches B–F"
- Next action: None.

**RIT-060 — Mobile Top Partner** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Mobile Trade Tendencies omitted it
- Final requirement (inventory): Show Manager, Trades and Top Partner columns on mobile
- Inventory said: Approved; "Merged" (Oct 18-19)
- PRs / issues (verified on GitHub): #1823 merged `23fed8b8cc` (2026-10-19); #1829 merged `a9f3918808` (2026-10-19)
- Owner: `frontend/app/trades/page.jsx`
- Tests: `frontend/__tests__/manager-scout.test.js`
- Flag: none
- Authorization: owner bug fix; intake "Added 2026-10-18 — Trade Tendencies top trading partner on mobile"
- Next action: None.

#### Sources

**RIT-061 — Source Health freshness status** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Users and operators need accurate freshness
- Final requirement (inventory): Per-source real upstream modification time, freshness verdict and voting status
- Inventory said: Approved; "PR evidence merged in trains" (Oct 11-20)
- PRs / issues (verified on GitHub): #1733 merged `0279fc41db` (2026-10-14); #1846 merged `820075a062` (2026-10-20)
- Owner: `src/sources/voting_status.py`; `frontend/lib/source-weighting.js`; `frontend/lib/source-voting-status.js`
- Tests: `tests/sources/test_voting_status.py`, `frontend/__tests__/source-voting-status.test.js`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"; §0 "Site completion and universal source voting — 2026-10-19"
- Next action: None.

**RIT-062 — KTC and Yahoo parser repairs** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Scrapers broke on vendor changes
- Final requirement (inventory): Repair moved KTC player map and Yahoo Boone smaller charts
- Inventory said: Approved repairs; "Release PR evidence" (Oct 11-13)
- PRs / issues (verified on GitHub): #1731 merged `7f5f7378d7` (2026-10-14); #1732 merged `14caa3d734` (2026-10-14); #1737 merged `5d7dc8f4f9` (2026-10-14)
- Owner: `frontend/lib/ktc-import.js`; `scripts/fetch_yahoo_boone.py`
- Tests: `tests/trade/test_ktc_import_player_map.py`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: prod obs. 2026-10-25: `yahooBoone` serves 352 rows, KTC Crowd/Trades 497 each.
- Next action: None.

**RIT-063 — DLF voting separation** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: DLF IDP data unreliable
- Final requirement (inventory): DLF offense-only; dlfIdp and dlfRookieIdp held
- Inventory said: Approved hold; "Merged policy" (Oct 16-20)
- PRs / issues (verified on GitHub): #1758 merged `a7c732e1ee` (2026-10-17); #1817 merged `4d85c9cb40` (2026-10-20)
- Owner: `src/api/data_contract.py` (vote hold); `src/api/feature_flags.py`
- Tests: `tests/api/test_dlf_offense_only_vote.py`, `tests/api/test_dlf_idp_hold_locked.py`
- Flag: `dlf_offense_only_vote` ON = hold active (prod obs. 2026-10-25); `dlfIdp` / `dlfRookieIdp` served absent
- Authorization: §0 "Repository audit next batch — 2026-10-16"; §0 "PR #1817 safe-portion release + outlier-filter Version 2 research — 2026-10-20 (Option 3)"
- Next action: None (lifting the hold is owner-reserved).

**RIT-064 — Signals, OTC and PFK** · `DORMANT_FLAG_OFF`

- Original request: Distinct sources should be independently evaluated
- Final requirement (inventory): Signals offense, OTC and Play For Keeps active when validated; Signals IDP held until quality criteria
- Inventory said: Approved with hold; "Signals IDP release gates off" (Oct 19-20)
- PRs / issues (verified on GitHub): #1817 merged `4d85c9cb40` (2026-10-20); #1860 merged `fa774af0c2` (2026-10-20); #1868 merged `7afffa9a8d` (2026-10-20)
- Owner: `src/sources/signals_health.py`; `src/bridges/family_crosswalk.py`; `src/api/data_contract.py`
- Tests: `tests/api/test_signals_idp_per_family.py`, `tests/api/test_signals_idp_crosswalk.py`
- Flag: every Signals IDP release flag OFF (prod obs. 2026-10-25); `signals_active_source` ON
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass); §0 "Site completion and universal source voting — 2026-10-19"
- Evidence note: prod obs. 2026-10-25: `signalsSf` 495, `otcffbSf` 453, `pfkDynasty` 450 rows serving; `signalsIdp*` absent.
- Next action: Per-family activation only after its gates pass (owner).

**RIT-065 — IDP Show outage** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Frozen IDP vendor shouldn't make all pipeline health red
- Final requirement (inventory): Acknowledge source outage; withhold vote when stale; keep last good board and lifecycle status
- Inventory said: Approved; "Release work evidenced" (Oct 16-18)
- PRs / issues (verified on GitHub): #1757 merged `d4520198b9` (2026-10-16); #1770 merged `f0602030dd` (2026-10-18); #1776 merged `7c83a3c8a0` (2026-10-18)
- Owner: `scripts/watchdog_freshness.py`; `src/sources/rehabilitation.py`
- Tests: `tests/api/test_watchdog_acknowledged_outage.py`, `tests/sources/test_rehabilitation_registry.py`
- Flag: none
- Authorization: §0 "Repository audit next batch — 2026-10-16"
- Evidence note: prod obs. 2026-10-25: `idpShowCombined` serves 655 rows.
- Next action: None.

**RIT-066 — FantasyPros IDP timestamps** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Age should reflect vendor update
- Final requirement (inventory): Track upstream expert-update time instead of scrape time
- Inventory said: Approved; "PR/release work evidenced" (Oct 17)
- PRs / issues (verified on GitHub): #1777 merged `7845544554` (2026-10-18)
- Owner: `scripts/fetch_fantasypros_idp.py`
- Tests: covered by #1817 closeout tests
- Flag: `fantasypros_idp_upstream_clock` ON (prod obs. 2026-10-25)
- Authorization: §0 "Repository audit next batch — 2026-10-16"; §0 "PR #1817 safe-portion release + outlier-filter Version 2 research — 2026-10-20 (Option 3)" (D5)
- Next action: None.

**RIT-067 — DLF IDP restoration experiment** · `BLOCKED_DEPENDENCY`

- Original request: Need fix that preserves genuine outliers
- Final requirement (inventory): Outlier-integrity V2 layered validation; maintain holds until preregistered gates pass
- Inventory said: Research only; "PR #1884 OPEN; default OFF" (Oct 19-21)
- PRs / issues (verified on GitHub): #1884 PR open; #1911 merged `5e881389ef` (2026-10-21)
- Owner: PR #1884 (open); research records on main via #1911 (`docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md`)
- Tests: on the open PR
- Flag: `outlier_integrity_v2` not on main
- Authorization: §0 "outlier-integrity-v2 implementation directive + 'Hold D4 for V2' — 2026-10-20" + LVA P5B
- Evidence note: Owner P5B: do not merge the whole V2/V2.1 implementation. Fresh held-out boards are ready no earlier than 2026-11-25; IV21-O2 is undecided.
- Next action: Wait for the held-out boards; owner O-2 decision before the Stage 4 run.

**RIT-068 — IDP identity capture** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Same-name cross-source attribution risk
- Final requirement (inventory): U2/U2b/U3/VID capture only, collect provenance without affecting values
- Inventory said: Approved prerequisite; "Merged" (Oct 21)
- PRs / issues (verified on GitHub): #1910 merged `5b41134278` (2026-10-21)
- Owner: `src/identity/capture_evidence.py`; `src/identity/published_fields.py`; `src/identity/vendor_ids.py`
- Tests: `tests/identity/test_capture_evidence*.py`
- Flag: none (collect-only)
- Authorization: §0 "outlier-integrity-v2 implementation directive + 'Hold D4 for V2' — 2026-10-20" + LVA P5B (P5B)
- Next action: Review captured artifacts at V2.1 time.

**RIT-069 — Outlier-corroborated V1** · `SUPERSEDED`

- Original request: Check preserving valid disagreement
- Final requirement (inventory): Experimental filter kept default OFF; evaluation not eligible
- Inventory said: Research only; "Merged dormant" (Oct 19-20)
- PRs / issues (verified on GitHub): #1847 merged `8775d01f75` (2026-10-20)
- Owner: `src/api/outlier_policy.py` (dormant)
- Tests: `tests/api/test_outlier_policy.py`
- Flag: `outlier_disagreement_policy` OFF (prod obs. 2026-10-25)
- Authorization: §0 "PR #1817 safe-portion release + outlier-filter Version 2 research — 2026-10-20 (Option 3)"
- Evidence note: The owner rejected this candidate outright on 2026-10-20 (failed 3 of 6 adversarial tests); superseded by outlier-integrity V2 / V2.1.
- Next action: None.

**RIT-070 — Universal freshness schedule V2** · `DORMANT_FLAG_OFF`

- Original request: Safer unified freshness policy
- Final requirement (inventory): Owner Option B merged disabled, no activation
- Inventory said: Approved dormant; "Merged; OFF" (Oct 20)
- PRs / issues (verified on GitHub): #1831 merged `1332aba1c6` (2026-10-20)
- Owner: `src/sources/freshness.py`; `config/sources/freshness_schedule_v2.json`
- Tests: `tests/api/test_freshness_v2_hold_locked.py`, `tests/sources/test_freshness_schedule_v2.py`
- Flag: `source_freshness_schedule_v2` OFF (prod obs. 2026-10-25); held at deploy
- Authorization: §0 "PR #1831 universal freshness schedule — 2026-10-20: OPTION B"
- Next action: Owner activation decision (FS-B7), after V2 validation (FS-B6).

**RIT-071 — Source vote withdrawal and two-way adjustment** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Improper two-way handling and Travis Hunter value change
- Final requirement (inventory): Ship D2/D3/D5 fixes while D4 and DLF held; protect player valuations
- Inventory said: Approved selective; "Merged" (Oct 19-20)
- PRs / issues (verified on GitHub): #1817 merged `4d85c9cb40` (2026-10-20)
- Owner: `src/api/data_contract.py` (two-way alt evidence)
- Tests: `tests/api/test_source_independence_closeout.py`
- Flag: `two_way_alt_evidence_rules` ON; `dlf_values_rank_hill_vote` (D4) OFF (prod obs. 2026-10-25)
- Authorization: §0 "PR #1817 safe-portion release + outlier-filter Version 2 research — 2026-10-20 (Option 3)"; §0 "outlier-integrity-v2 implementation directive + 'Hold D4 for V2' — 2026-10-20" + LVA P5B
- Evidence note: Travis Hunter's served value was not re-checked here.
- Next action: None.

**RIT-072 — Scraper outage Oct 23-24** · `PARTIAL`

- Original request: KTC/IDPTC scraped stale/timeout and HTTP 503
- Final requirement (inventory): Fix false deployment blocker; verify true timeouts separately
- Inventory said: Approved urgent; "Recovered by report; permanent root cause unverified" (Oct 23-24)
- PRs / issues (verified on GitHub): #1917 merged `1fdce81e41` (2026-10-23); issue #1919 closed
- Owner: `Dynasty Scraper.py`; `scripts/check_source_health.py`; `tests/fixtures/u3_pre_cutover/`
- Tests: `tests/fixtures/u3_pre_cutover/*` (#1917)
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: prod obs. 2026-10-25: two scheduled scrapes today, both success; KTC + IDPTC `complete`, no partial or timed-out source; #1919 closed 2026-10-24. The root cause of the 2026-10-23/24 timeouts is not established.
- Next action: Root-cause the timeouts from box logs.

**RIT-073 — Background worker failures** · `BROKEN_REGRESSED`

- Original request: Six dynasty-* units failing different reasons
- Final requirement (inventory): Fix Python import path, DLF fetch, player context schema guard, JSON serializability
- Inventory said: Approved urgent; "Exact current remediation not verified" (Oct 23-24)
- PRs / issues (verified on GitHub): issue #1919 closed
- Owner: box systemd units `dynasty-depth-charts-refresh`, `dynasty-market-trade-ledger`, `dynasty-game-day-capture`
- Tests: —
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: Coordinator, 2026-10-25: depth charts 0/32 teams since at least 2026-10-19; the market-trade ledger timed out 2026-10-25; Game Day capture missed its pregame window. Repair in progress in another lane.
- Next action: Repair each unit without bypassing its guard.

**RIT-074 — IDPTC partial scrape** · `UNVERIFIABLE`

- Original request: A scrape yielded roughly 979 versus usual 1111 and timed out
- Final requirement (inventory): Reject partial canonical publishing; preserve last good and instrument timeout
- Inventory said: Approved investigation; "Permanent fix unknown" (Oct 23-24)
- PRs / issues (verified on GitHub): #1910 merged `5b41134278` (2026-10-21)
- Owner: partial-run guards: `data_contract` `partial_run_critical:*`, `/api/status` `source_runtime` (`partial_sources`, `timed_out_sources`)
- Tests: `tests/api/test_contract_health_lanes.py`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: The cited PR #1910 is identity capture, not this incident. prod obs. 2026-10-25: the current run is complete (IDPTC 893 matched rows). The ~979-row run could not be reproduced from public evidence.
- Next action: Reproduce from box logs and compare the census.

#### Operations

**RIT-075 — Always-safe parallel coding** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: User wants high implementation throughput
- Final requirement (inventory): 3–5 isolated workers/worktrees; L0/L1 while coding; L2 integration and L3 release safety remain strict
- Inventory said: Approved standing policy; "Merged docs" (Oct 19)
- PRs / issues (verified on GitHub): #1839 merged `14b1446f6b` (2026-10-20)
- Owner: `docs/AGENT_OPERATING_SYSTEM.md` §3; `AI_INSTRUCTIONS.md`
- Tests: `tests/docs/test_cross_model_agent_entrypoints.py`
- Flag: none
- Authorization: §0 "Standing owner delivery method — 2026-10-19" + `docs/AGENT_OPERATING_SYSTEM.md` §3
- Next action: None.

**RIT-076 — Integration Authority merge discipline** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Avoid per-routine PR approval bottlenecks
- Final requirement (inventory): Authorized responsible coordinator may merge objectively reviewed green routine PRs; consequential activation remains reserved
- Inventory said: Approved; "Merged docs" (Oct 19)
- PRs / issues (verified on GitHub): #1839 merged `14b1446f6b` (2026-10-20)
- Owner: `docs/AGENT_OPERATING_SYSTEM.md` §3 item 3; `ASSISTANT_COORDINATION.md`
- Tests: `tests/docs/test_cross_model_agent_entrypoints.py`
- Flag: none
- Authorization: §0 "Standing owner delivery method — 2026-10-19" + `docs/AGENT_OPERATING_SYSTEM.md` §3
- Next action: None.

**RIT-077 — Release train CI and immutable heads** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Avoid repeated expensive CI before freeze
- Final requirement (inventory): Coordinate independent PRs and freeze tested candidate for green review/deploy
- Inventory said: Approved; "Multiple trains merged" (Oct 16-21)
- PRs / issues (verified on GitHub): #1875 merged `9d07b9cebf` (2026-10-20); #1876 merged `fd798c3ec0` (2026-10-20); #1894 merged `9e3c52fdc6` (2026-10-21)
- Owner: `.github/workflows/release-candidate.yml`; `scripts/check_release_candidate.py`
- Tests: release-candidate tests
- Flag: none
- Authorization: §0 "Standing owner delivery method — 2026-10-19" + `docs/AGENT_OPERATING_SYSTEM.md` §3
- Next action: None.

**RIT-078 — E2E failures** · `BROKEN_REGRESSED`

- Original request: Critical automation sometimes falsely passes or fails
- Final requirement (inventory): Real journey tests and trustworthy diagnostics; don't ship known red critical path
- Inventory said: Approved repair; "#1918 issue OPEN" (Oct 13-25)
- PRs / issues (verified on GitHub): issue #1730 closed; issue #1918 open
- Owner: `.github/workflows/e2e.yml` (E2E Safety Net); `tests/e2e/specs/trade-multi-team.spec.js`, `tests/e2e/specs/trade-tcd2.spec.js`
- Tests: —
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: E2E Safety Net failed on every run 2026-10-22 → 2026-10-25 (#1918 open), 3 specs × 2 projects, all at the step `search result for 2027 Mid 1st (from Kich)`. "Production E2E Smoke (public /league)" also failed 2026-10-24 18:47 and 2026-10-25 04:39 and passed in between. Repair in progress in another lane.
- Next action: Land the fix; close #1918 on a green run.

**RIT-079 — Deploy blocked by U3 live-data fixture** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Live CSV change broke immutable test assumption
- Final requirement (inventory): Pin pre-U3 fixtures instead of live data
- Inventory said: Approved repair; "Merged" (Oct 22-23)
- PRs / issues (verified on GitHub): #1917 merged `1fdce81e41` (2026-10-23)
- Owner: `tests/fixtures/u3_pre_cutover/`
- Tests: the pinned fixtures (#1917)
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: Deploy Production succeeded 2026-10-24 22:51, 2026-10-25 05:25 and 12:07; the production build is `40f5dc5` (2026-10-25 12:07).
- Next action: None.

**RIT-080 — Health checks** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: 503 might be stale/failure or unreachable services
- Final requirement (inventory): Accurate watchdog and status classification with upstream errors
- Inventory said: Approved repair; "Latest #1919 issue CLOSED after recovery" (Oct 16-24)
- PRs / issues (verified on GitHub): #1757 merged `d4520198b9` (2026-10-16); #1850 merged `680ba8ab39` (2026-10-20); issue #1919 closed
- Owner: `scripts/watchdog_freshness.py`; `deploy/systemd/dynasty-healthcheck.sh`
- Tests: `tests/api/test_watchdog_acknowledged_outage.py`, `tests/deploy/test_healthcheck_cgroup_snapshot.py`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: prod obs. 2026-10-25: `/api/health` ok; the last four Scheduled Health Checks succeeded; #1919 closed 2026-10-24.
- Next action: None.

**RIT-081 — Auth/session and sharp smoke verification** · `BLOCKED_DEPENDENCY`

- Original request: Health gate falsely green without credential
- Final requirement (inventory): Provision matching smoke secret before asserting Sharp production verification; guest sessions survive restart
- Inventory said: Approved repair; "Sharp gate issue OPEN" (Oct 12-21)
- PRs / issues (verified on GitHub): issue #1727 open; #1837 merged `65498c5296` (2026-10-19); #1903 merged `21a0a9100d` (2026-10-21)
- Owner: `src/api/session_store.py`, `src/api/guest_passes.py` (#1837); `scripts/v1_failure_classifier.py` (#1903)
- Tests: `tests/ops/test_v1_failure_classifier.py`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: `data/ops/sharp-production-smoke.json` (2026-10-25 14:28): `status: unverifiable_unauthenticated`, 401 from `/api/sharp/cohort`. Issue #1727 open.
- Next action: Owner provisions the smoke credential (owner-held secret).

**RIT-082 — Memory and uptime** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: Backend watchdog restarts and retention growth
- Final requirement (inventory): Bound process lifetime caches; self-diagnosing restart snapshots
- Inventory said: Approved repairs; "Merged" (Oct 19-21)
- PRs / issues (verified on GitHub): #1848 merged `00ef6631e3` (2026-10-20); #1879 merged `e5b7638797` (2026-10-20); #1880 merged `8481728fff` (2026-10-20); #1881 merged `202a0e375e` (2026-10-20)
- Owner: `server.py` (bounded caches); `deploy/diagnostics/prod_restart_diagnostics.sh`
- Tests: `tests/infra/test_memory_bounded_caches.py`, `tests/infra/test_memory_bounded_caches_followup.py`
- Flag: none
- Authorization: §0 "PR #1817 safe-portion release + outlier-filter Version 2 research — 2026-10-20 (Option 3)" (W8 lane)
- Next action: Inspect after a long uptime window (the current process started 2026-10-25 13:07).

**RIT-083 — Accessibility and hydration** · `VERIFIED_IN_CODE_AND_TESTS`

- Original request: UI controls not ready until hydrated
- Final requirement (inventory): Use correct aria, visible pending state, keyboard tests and E2E
- Inventory said: Approved; "Merged" (Oct 18-20)
- PRs / issues (verified on GitHub): #1849 merged `85021bedcc` (2026-10-20); #1872 merged `a5f16368cb` (2026-10-20); #1878 merged `f631607ff3` (2026-10-20)
- Owner: `frontend/components/ds/useHydrated.js`; `frontend/components/ds/DataTable.jsx`
- Tests: `frontend/__tests__/components/ds/hydration-gate.test.jsx`, `frontend/__tests__/components/a11y-cq30-visual-fixes.test.jsx`
- Flag: none
- Authorization: §0 "Site completion and universal source voting — 2026-10-19"
- Next action: None.

**RIT-084 — Documentation and claims** · `PARTIAL`

- Original request: Stale trackers hide obligations
- Final requirement (inventory): Keep owner intake, execution authorization, work claims and plan in sync
- Inventory said: Approved; "Merged docs" (Oct 14-21)
- PRs / issues (verified on GitHub): #1756 merged `fdf446e717` (2026-10-17); #1813 merged `69e7ca8f8d` (2026-10-18); #1838 PR open; #1902 merged `eedbac2424` (2026-10-21)
- Owner: `docs/WORK_CLAIMS.md`, `docs/OWNER_REQUESTED_TODO.md`, `docs/EXECUTION_PLAN.md`
- Tests: `tests/scripts/test_check_work_claims.py`; `scripts/check_planning_integrity.py`
- Flag: none
- Authorization: §0 "Repository stabilization / truth-reconciliation campaign — 2026-10-07"
- Evidence note: PR #1838 (live tracker) is still open. This pass closes 58 stale claim rows.
- Next action: Decide #1838's disposition; keep claims current.

#### Deferred

**RIT-085 — League Tycoon contract integration** · `DEFERRED_PAUSED`

- Original request: Consider move to contract dynasty platform
- Final requirement (inventory): Preserve 100 mechanisms and 44 ideas in Ideas; DO NOT implement until explicitly authorized; Best Ball nonnegotiable
- Inventory said: Deferred; "Documentation PR evidence" (Oct 15-16)
- PRs / issues (verified on GitHub): #1755 PR open; #1764 merged `569611763b` (2026-10-17)
- Owner: research `docs/research/league-tycoon-migration-2026-10-17/` (#1764)
- Tests: —
- Flag: none
- Authorization: §0 "Owner decision closeout + evidence unblock — 2026-10-18 (D1–D20)" (OWNER_PAUSED)
- Evidence note: The park PR #1755 is still OPEN; §0 records League Tycoon as parked.
- Next action: No implementation. #1755 disposition is the owner's.

**RIT-086 — DFS expansion** · `DEFERRED_PAUSED`

- Original request: Potential DFS tools and research
- Final requirement (inventory): Pause all new DFS features, integrations, modeling, research and merges until explicit resumption
- Inventory said: Explicitly paused; "Merged decision record" (Oct 18)
- PRs / issues (verified on GitHub): #1810 merged `6575c37f91` (2026-10-18)
- Owner: existing DFS (`src/dfs/`) stays deployed
- Tests: —
- Flag: `dfs_workspace` ON (existing feature kept)
- Authorization: §0 "DFS IMPLEMENTATION PAUSED — 2026-10-18"
- Next action: No new DFS work until the owner resumes it.

**RIT-087 — Chase Trade Market league maturity and reserves** · `AWAITING_REVIEW`

- Original request: Build high-quality trade market evidence layer
- Final requirement (inventory): Maturity based on verified league chains; reserve exists but selected Q2 method not chosen; shadow only
- Inventory said: Research and groundwork only; "PR #1852 OPEN; reserve unresolved" (Oct 19-21)
- PRs / issues (verified on GitHub): #1852 PR open; #1851 merged `c6f3f0b2b3` (2026-10-20); #1858 merged `5a1274e5e2` (2026-10-20); #1865 merged `d051e50a48` (2026-10-20)
- Owner: PR #1852 (open); merged groundwork `src/sources/chase_trade_market.py`, `src/model_registry/promotion_gates.py`, `src/trade/market_trade_sim.py`
- Tests: `tests/sources/test_chase_trade_market_shadow.py`, `tests/model_registry/test_promotion_gates.py`
- Flag: none (shadow, not voting)
- Authorization: §0 "League intelligence, trade decision engine … — 2026-10-19 (later)" (shadow until preregistered gates pass); §0 "Low-value-asset decision packages 1–5 — 2026-10-21" (develop/dormant only; activation owner-reserved) (P5A)
- Evidence note: The lineage census landed in #1907. Q2 stays `PROPOSED_PENDING_OWNER_Q2`; no reserve is drawn, persisted or exposed.
- Next action: Owner chooses the reserve policy (Q2), then review #1852.

**RIT-088 — League realignment schedule** · `NOT_STARTED`

- Original request: Possibly 2 divisions and strength-balanced schedules
- Final requirement (inventory): Proposal only, no approved app change; rank cross-division opponents fairly
- Inventory said: Proposal only; "No implementation authorization evidenced" (Oct 16)
- PRs / issues (verified on GitHub): none
- Owner: —
- Tests: —
- Flag: none
- Authorization: none found in `docs/EXECUTION_PLAN.md` or `docs/OWNER_REQUESTED_TODO.md`
- Evidence note: Proposal only. No record found in the repository. Kept here as an unpromoted owner idea.
- Next action: Nothing, unless the owner turns it into a request.

## 4. Genuinely open authorized work, in priority order

Each item below is open, and a §0 record authorizes it. The order puts broken production first, then evidence the
owner is waiting on, then research. Items marked "in progress elsewhere" already have a lane, so do not start a
duplicate.

| # | Item | RIT | Owner path | Authorization | State |
|---|---|---|---|---|---|
| 1 | Make the E2E Safety Net green. 3 specs × 2 projects fail at the step `search result for 2027 Mid 1st (from Kich)`, which suggests test-data drift (unconfirmed). Close #1918 on a green run | RIT-078, -019, -020, -027 | `tests/e2e/specs/trade-multi-team.spec.js`, `tests/e2e/specs/trade-tcd2.spec.js` | §0 2026-10-07 stabilization | in progress elsewhere (coordinator) |
| 2 | Repair the failed box units: depth charts (0/32 since ≥ 10-19), market-trade ledger (timeout 10-25) and Game Day capture (missed its pregame window). The ledger also feeds Comparable Trades and the Trade Database | RIT-073, -012, -011 | box units `dynasty-depth-charts-refresh`, `dynasty-market-trade-ledger`, `dynasty-game-day-capture` | §0 2026-10-07 stabilization | in progress elsewhere (coordinator) |
| 3 | Land the forced-drop box replay evidence (digest `f10fc997`, coordinator), then send the activation request to the owner | RIT-031, -007 | `src/trade/forced_drop_selection.py`, `docs/trade/FORCED_DROP_BOX_REPLAY_RUNBOOK_2026-10-21.md` | §0 2026-10-21 LVA P1 | evidence PR in progress elsewhere |
| 4 | Root-cause the 2026-10-23/24 KTC / IDPTC timeouts and the ~979-row partial IDPTC scrape from box logs. Scrapes are healthy today | RIT-072, -074 | `Dynasty Scraper.py`; `scripts/check_source_health.py` | §0 2026-10-07 stabilization | not started |
| 5 | Multi-team Lane E (quality, privacy, verification). Its claim row says "starts once A1 lands"; A1 merged 2026-10-21 and no Lane E branch exists. After Lane E and an independent review, `trade_multi_team_analysis` turns on through the normal release process (spec §6.1). It is not an owner-reserved activation | RIT-019, -020 | `tests/trade/`, `tests/e2e/specs/trade-multi-team*.spec.js` | §0 2026-10-20 Advisor/multi-team | not started |
| 6 | Review and land #1843, then finish the live Sleeper scoring/rules parity audit (#1842) | RIT-034, -041 | `src/league_comparison/sleeper_scoring.py` + #1843 | §0 2026-10-19 (later) league intelligence | PR open |
| 7 | LI-5 phase P3, behind its default-OFF flag. Its precondition (#1890 merged) is met. §0 lists "P1–P2" as authorized and says P3 starts after #1890, so confirm P3 is in scope before building | RIT-037 | `src/draft/waiver_population.py` | §0 2026-10-21 LVA P3 | not started; scope confirmation needed |
| 8 | League-intelligence shadow lanes: calibrate the league fair-value challenger and run its preregistered holdout; benchmark best-ball marginal value; validate decision engine v3 against the private champion. All stay shadow until their gates pass | RIT-035, -036, -039 | `src/league_valuation/`, `src/bestball/`, `src/trade/decision_engine/` | §0 2026-10-19 (later) | partial (shadow libraries merged) |
| 9 | Post-install OCR recognition check with real phone screenshots. Needs a logged-in session | RIT-028 | `src/trade/screenshot_import/` | §0 2026-10-15 | not run |
| 10 | Records: decide the disposition of PR #1838 (live tracker), and keep claims current (this PR closes 58 stale rows) | RIT-084 | `docs/WORK_CLAIMS.md` | §0 2026-10-07 stabilization | partial |
| 11 | Small coverage gaps: pin the nine Package Builder Sending × Receiving combinations (RIT-005), replay a current KTC trade link (RIT-029), re-check Travis Hunter's served value (RIT-071) | RIT-005, -029, -071 | see rows | §0 2026-10-14 / 2026-10-07 / Option 3 | not run |

**Not open work, by decision:**

- RIT-033: #1873 stays unmerged, and its box run needs separate authorization.
- RIT-067: #1884 is not merged whole.
- RIT-052: nothing to do until the 2027 class window opens on 2027-05-01.
- RIT-085 and RIT-086: paused.
- RIT-088: a proposal only.

## 5. Owner decisions still required

None of these is answered here. Each is quoted from, or points to, the record that holds it.

| Decision | Record | Current state |
|---|---|---|
| #1852 reserve policy (**Q2**) | `docs/OWNER_REQUESTED_TODO.md` LVA-P5A; census in #1907 | `PROPOSED_PENDING_OWNER_Q2`. No reserve drawn, persisted or exposed |
| Public Advisor launch: source-permission record (OD-3), admission sizes (AD-1), naming withheld assets publicly (F-1), response floor (RF-1), final launch approval (LA-1), plus the directive §16 exposure decisions (OD-4) | intake "Added 2026-10-20 (~19:45 UTC)"; `docs/owner/TRADE_ADVISOR_MULTITEAM_DIRECTIVE_2026-10-20.md` | each one "OPEN — not asked"; `brisket_trade_advisor` OFF |
| Activate `forced_drop_cheapest_legal` (V5-R) | LVA-P1 | waits for the replay evidence (open item 3) |
| Start the depth-disclosure shadow window (`low_value_depth_disclosure_shadow`, G3) | LVA-P4; `docs/trade/LOW_VALUE_DEPTH_DISCLOSURE_DESIGN_2026-10-20.md` §10 | OFF |
| Any served LI-5 replacement-level or scarcity change, or turning its flag on | LVA-P3 | owner-reserved |
| Activate `source_freshness_schedule_v2` | FS-B7 (after V2 validation, FS-B6) | OFF |
| Lift the DLF IDP / Rookie IDP vote hold (O3-1); activate D4 (`dlf_values_rank_hill_vote`, IV2-D4); activate outlier-integrity V2 / V2.1 | §0 Option 3 and IV2 entries | all held |
| IV21-O2: AD2-ID vs AD2 for the wrong-player gate | intake "Added 2026-10-20 (~19:45 UTC) — outlier-integrity V2.1" | OPEN. Must be recorded before the V2.1 Stage 4 run |
| Signals IDP per-family voting | §0 2026-10-19 (later) | every release flag OFF |
| Run the #1873 prospective command on the box | LVA-P5C; `docs/ops/PACKAGE_MODEL_PROSPECTIVE_RERUN_COMMAND_2026-11.md` | prepared, not run. Also needs ≥ 2,000 post-freeze unequal trades |
| Confirm the roster 12 cutover week (effectiveWeek 7) | `docs/OWNER_REQUESTED_TODO.md` (roster 12 row) | "OPEN — owner to confirm the cutover week" |
| Paid projection feeds (SportsDataIO / Fantasy Nerds): licence and spend | §0 2026-10-19 (later): "no paid data … without the owner" | flags OFF / `UNREACHABLE` |
| Provision the Sharp production-smoke credential (an owner-held secret, so an owner **action**) | issue #1727; `data/ops/sharp-production-smoke.json` | `unverifiable_unauthenticated` (2026-10-25 14:28) |
| Disposition of the League Tycoon park PR #1755; any DFS or League Tycoon resumption | §0 2026-10-18 closeout / DFS paused | parked / paused |
| Whether RIT-088 (two divisions, strength-balanced schedule) is real work | not recorded anywhere | proposal only. Not promoted to intake by this pass |

## 6. What could not be proven

- **The original conversations.** The inventory's dated wording ("Original request", "Final requirements") comes
  from conversation extracts that are not in the repository. This pass preserves that wording as the inventory
  states it, and can confirm only what a repository record also says.
- **Behaviour behind login**, which needs a session this pass may not create:
  - the trade calculator, War Room and Trade Desk;
  - served draft-capital dollars (the $1,200 total and parity are pinned by tests only);
  - Manager Intelligence;
  - OCR on real screenshots;
  - the multi-team route beyond its 401.
- **Box-local state**, reported by the coordinator and not observed here:
  - the replay digest;
  - the three failed units;
  - the market-trade ledger's contents;
  - the waiver page's Sleeper ownership match and its formula check.
- **Root causes:**
  - the 2026-10-23/24 scrape timeouts;
  - the ~979-row IDPTC run;
  - whether the red E2E journeys are test-data drift or a product defect (the failing step suggests drift, which is
    unconfirmed).
- **History.** Week-by-week historical owner attribution for rosters 11 and 12 was not re-checked. Only the current
  surfaces were.
- **Single decision owner (RIT-015).** "Every consumer uses one decision owner" rests on the merged tests and AST
  guards. No fresh full call-graph audit was done.
- **Vendor formats.** Current KTC, Yahoo and IDPTC formats are evidenced only by today's successful scrape counts.

## 7. Kinds of item in the inventory

These are kept apart so a recommendation is not read as authorization.

- **Historical requests already delivered.** Of these, 56 rows are `VERIFIED_IN_CODE_AND_TESTS`. They need no new
  work beyond the optional live spot-checks named in each row.
- **Authorized work still open.** These are the items in §4.
- **Research recommendations.** RIT-033, -035, -036, -039, -041, -067 and -069, plus the inventory's own §3
  "critical unfinished work" ranking and its §8 handoff prompt. These are advice. Their authority is only what §0
  already grants.
- **New proposals.** RIT-088 has no record. It is preserved here for owner review and not promoted.
- **Paused by owner.** RIT-085 (League Tycoon) and RIT-086 (DFS).

## 8. Records hygiene done with this document

- `docs/OWNER_REQUESTED_TODO.md`: one compact intake pointer to this document ("Added 2026-10-25").
- `docs/WORK_CLAIMS.md`: 58 claim rows were still `open` / `active` / `in review` / `claimed`, but their PRs are
  verifiably merged on `origin/main`. Each is now `done` with its merge commit and date, plus "Previously: <old
  status>", following the 2026-10-17 / 2026-10-18 housekeeping convention. This includes the "Unlisted Waiver Wire
  Comparison page" claim (#1915, `7890a5bef6`, 2026-10-21).
- Rows left open, on purpose:
  - multi-team Lane E and D-net loopback binds (no PR exists);
  - the calculator completion campaign umbrella;
  - Rookie Auction Phase 2 (#1533 open) and Unified Manager of the Year (#1513 open);
  - LVA-P1 box replay (its evidence PR is in progress);
  - two rows whose cells do not parse as a five-column row.
- The Codex MCP lane is not touched.
