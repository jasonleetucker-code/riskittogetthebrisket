# CW-40: adjudication of 7 UNKNOWN master-site-audit P0 findings

Adjudicated against `main` at `19ea4e80b` (2026-11-06). The August repro output was not trusted. Each
repro was rebuilt as an offline, deterministic check: the pure function, or a FastAPI `TestClient`
against the isolated app (no network, no production calls, nothing written outside tmp). Boards come from
`tests/archive_fixtures` (tracked export archive).

Git history is shallow in this checkout (the earliest visible commit is a graft), so "history" below cites
in-code owner comments and PR numbers rather than `git log -S` origin commits.

| id | classification | one-line evidence |
|---|---|---|
| W03-F001 | CLOSED_VERIFIED | stock/any manual TE body now returns the `GET /api/data` board on a real TE-bearing archive board |
| W07-F001 | CLOSED_VERIFIED | frontend default `tepMultiplier` is `null` (no POST); server ignores manual TE keys |
| W08-F001 | CLOSED_VERIFIED | same path as W07; /trade reads the base contract (no override POST) |
| W10-F002 | CLOSED_VERIFIED | slot machinery deleted; 31-pick team merges with full budget, no slot fields |
| W12-F002 | PARTIAL | SELL is no longer TE-only (gap is value-space vs KTC Market, position-blind); the TE SELL skew remains (23/31 = 0.742 vs target 0.137 +/- 0.05) |
| W17-F001 | PARTIAL | selector called with `s.season` at all four sites; newest season chosen whatever the load order; no preseason guard exists |
| W17-F002 | PARTIAL | absent-from-sim owner gets null odds and a non-sell label, never a coerced 0.0; `classify_team` still ignores strength for the label |

## W03-F001, W07-F001, W08-F001 (one root cause: manual `tep_multiplier` bypasses ADR-015)

**Claim.** The frontend posted `{"tep_multiplier":1.15}` on every load. `data_contract.py` gates the
TE-basis conversion behind `if not tep_multiplier_is_override:` (now `data_contract.py:12145`), so the delta
board differed from `GET /api/data` (627/740 ranks, 129-135 values, TEs up to -21%) while
`isCustomized` stayed false. W07/W08 add that `SETTINGS_DEFAULTS.tepMultiplier = 1.15` made the stock body
unavoidable.

**Live path now.**
- Client: `frontend/components/useSettings.js:51` default `tepMultiplier: null`, with a one-time migration
  (`:213-217`) restoring persisted 1.15/1.0/1.25 to null. `frontend/lib/dynasty-data.js:1080`
  `tepMultiplierIsCustomized(null) === false`, so `fetchDynastyData` takes the no-POST base-contract path
  (`:2283-2316`). /rankings and /trade both read through it.
- Server ingress: `server.py:5977-5993` calls `normalize_tep_multiplier` / `normalize_tep_native_multiplier`,
  which return `None` while `data_contract._TEP_OVERRIDES_DISABLED = True` (`data_contract.py:4144-4222`).
  The request is ignored, `tepMultiplierSource` is `canonical`, and `warnings` carries
  `tep_override_withdrawn: not_canonical`. Withdrawn by DEFECT-02 (#2003); `tepMultiplier: null` default
  landed with it.
- The library parameter `tep_multiplier=` of `build_api_data_contract` still bypasses the curve. It is
  reachable only from research scripts and tests, not from HTTP.

**Rebuilt repro.** Raw payload from `newest_complete_raw_payload()` (a real TE-bearing board; the
synthetic fixture in older tests has no tight ends and could not see this defect). Isolated app via
`TestClient`, `POST /api/rankings/overrides?view=delta` with all three manual TE keys, compared per player
(`rankDerivedValue`, `canonicalConsensusRank`, `canonicalTierId`) to `build_api_data_contract(raw)`.

**Result.** Every compared row identical; `tepMultiplierSource != "override"`; withdrawal note present.
The other pieces were already pinned by `tests/api/test_source_overrides.py:827-900` (normalizers return
None, rollback gate does move the board), `tests/api/test_overrides_response_cache.py`
(`test_withdrawn_tep_bodies_serve_the_canonical_board`) and the frontend
`tep-auto-default.test.js` / `useSettings.tep-auto-restore.test.jsx` /
`use-dynasty-data-tep-withdrawn.test.jsx`.

**Classification.** All three CLOSED_VERIFIED. **Test added:**
`tests/api/test_audit_tep_override_regression.py` (hard gate). Positive: the stock/any manual TE body serves
the `GET /api/data` board. Negative control: with `_TEP_OVERRIDES_DISABLED` monkeypatched to False the same POST
reports `tepMultiplierSource == "override"` and MOVES the board (reviewer measured 2027 Pick 1.08: 4636 vs
4651), proving the test detects the defect.

## W10-F002 (draft slot accounting)

**Claim.** `buildTeam()` clamped `initialSlots = min(feedSlots, DEFAULT_INITIAL_SLOTS=6)`, so a 31-pick team
rendered "0/6" with MDV $114 instead of about $22.

**Live path now.** `frontend/lib/draft-logic.js:1338` `mergeDraftCapitalTeams` builds rows from `{name,
initialBudget, feedBudget}` only; the `picks` option is accepted and deliberately unused (`:1352-1358`). The
slot model (`DEFAULT_INITIAL_SLOTS`, `slotPressure`, `phaseMultiplier`, `mdv`, `slotsByTeamFromPicks`) was
deleted (file header `:20-45`, owner-confirmed "no min or max rookie count"; roster capacity lives in
`lib/perfect-draft.js`).

**Rebuilt repro.** Node ESM import of the real module (no vitest install in this worktree): merge a feed of
`Heavy $685` + 31 pick rows, then `computeDraftStats`. Output: `initialBudget 685`, `initialSlots undefined`,
team row has no `initialSlots` or `mdv`; `DEFAULT_INITIAL_SLOTS` is not exported.

**Classification.** CLOSED_VERIFIED. The fixture uses the real pick shape (`{ currentOwner: "Heavy" }`, which the retired
`slotsByTeamFromPicks` read) so it mirrors the original 31-to-6 clamp scenario. **Test added:** a case in the existing block "the rookie draft has no
per-team slot limit" in `frontend/__tests__/draft-logic.test.js` (assertions replicated and verified with the
node harness; vitest itself could not be run here because `node_modules` is absent, so CI is its first run).

## W12-F002 (Edge column TE SELL skew)

**Claim.** The gap compared ranks of the single retail TE++ board (`ktcSfTep`) against 13 expert boards, so
32 of 35 top-250 TEs were SELL and every top-250 SELL was a TE.

**Live path now.** `data_contract.py:4764` `_compute_market_gap` delegates to
`src/sources/ktc_market.py::compute_market_gap(model_value, market_normalized)`: OUR `rankDerivedValue` against
KTC Market's normalized value, symmetric ratio in value space, no position, no rank (redefined 2026-09-23).
`_stamp_ktc_market_benchmark` (`:4790`) runs last. Frontend label: `display-helpers.js:224-300`, threshold
`thresholds.js:99` (0.05).

**Rebuilt repro.** `newest_complete_contract()` (archive `dynasty_export_20261106_123200`), labels at the
frontend 0.05 threshold, top 250 by `canonicalConsensusRank`:

| pos | SELL | HOLD | BUY | median signed gap (+ = KTC higher) |
|---|---|---|---|---|
| QB | 5 | 13 | 15 | -0.034 |
| RB | 27 | 15 | 4 | +0.074 |
| WR | 27 | 21 | 14 | +0.036 |
| TE | 23 | 7 | 1 | +0.076 |

SELLs in the top 250 span QB, RB, WR and TE (5/27/27/23). The defect as stated (SELL exclusive to TE, driven by
TE-premium rank basis) is gone.

**Closed part.** SELL is no longer TE-only; the gap is value-space vs KTC Market and position-blind.

**Residual (why this is PARTIAL).** The finding's own target is P(SELL | TE, top-250) = 0.137 +/- 0.05. On
`dynasty_export_20261106_123200` it is still 0.742 (23/31) vs 0.418 for other offense and 0.15 for QB. The
median gap (+0.076) matches RB (+0.074), so the skew is a level/position effect between our TE values and KTC
Market, not a label bug. Residual routed by the coordinator to CW-36 (TE++ uplift / board constants).

**Classification.** PARTIAL. **Test added:** `tests/api/test_audit_w12_f002_regression.py`: synthetic rows
through the real `_stamp_ktc_market_benchmark` (no archive or market data, so a KTC refresh cannot flip it).
Positive: a TE and a WR with identical model-vs-market gaps get the same direction and ratio. Negatives: a
sub-threshold gap is not SELL, the opposite sign is a model premium (not SELL), and a missing market is
`none`/null rather than a zero gap. The live-board TE skew is deliberately NOT asserted.

## W17-F001 (ROS sims on the oldest season)

**Claim.** `luck._season_sort_key(season: str)` was handed `SeasonSnapshot` objects, every key was 0, and
`seasons_sorted[-1]` returned the oldest season (2024 with 2025/2026 loaded).

**Live path now.** All four ROS call sites pass `s.season`: `src/ros/playoff_sim.py:767`, `:901`, `:1059`
(`_simulated_season`) and `src/ros/power_v2.py:1003`. Key defined at `src/public_league/luck.py:316`.

**Rebuilt repro.** Synthetic snapshots `[2026, 2025, 2024]` and the reverse through
`playoff_sim._simulated_season`: both return 2026; empty returns `None`. Existing
`tests/ros/test_season_selection.py` (11 tests with the deadline file) passes, including the source-shape
tripwire.

**Coverage.** The first version of the test covered only `_simulated_season` (added 2026-10-04, never
defective). The audited inline selections are now covered: `playoff_sim._remaining_schedule` behaviorally (the
season handed to the schedule reader is the newest, both load orders), and `playoff_sim._build_team_distributions`
(`:767`) / `power_v2.build_section` (`:1003`) by source shape (their bodies need a full league snapshot): each
passes `s.season`, never the snapshot object.

**Preseason guard.** None exists. The finding asked for one; `simulate_playoff_odds` always selects the newest
season and only STAMPS `regularSeasonProgress` (`weeksFinal` / `complete`); it does not refuse a season with no
finished weeks. `power_v2._is_preseason` guards strength weighting only.

**Classification.** PARTIAL. Closed: newest season selected at all four sites. Residual: no preseason guard
(routed by the coordinator). **Test added:** `tests/ros/test_audit_w17_regression.py`.

## W17-F002 (absent owner told "Seller")

**Claim.** `playoffs.get(owner) or 0.0` conflated "missed the playoffs" with "not in the sim"; the #1
ROS-strength roster was labelled Seller.

**Live path now.** `src/ros/trade_deadline.py:build_team_directions` reads raw odds and, when either is
non-numeric, emits `_unmeasurable_team(...)` with null odds, an `Unknown(reason="team_absent_from_sim")` and a
label that is not one of the seven buy/sell verbs. Unmeasurable rows sort last. A genuinely measured 0 still
sells (`tests/ros/test_trade_deadline_unknown.py`). The code comment records it as audit N-2 / Critical batch C3.

**Rebuilt repro.** Pure call with injected maps (no sim file read): owner `new` is rank 1 in team strength and
absent from both sim maps; result has null odds and no sell-family label; a measured owner keeps its odds.

**Closed part.** An owner absent from the sim gets null odds, not 0 (the test would have failed on the old
`or 0.0`). **Not addressed (why PARTIAL).** `classify_team` still ignores team strength when choosing the label
(`src/ros/direction.py` coerces it with `or 0.0`; it is used only in the summary text). Routed by the
coordinator to CW-33. The stale `build_team_directions` docstring ("classifier degrades cleanly") was corrected
(docstring only).

**Classification.** PARTIAL. **Test added:** `tests/ros/test_audit_w17_regression.py`.

## Routing

Final tally: W03-F001, W07-F001, W08-F001, W10-F002 CLOSED_VERIFIED; W12-F002, W17-F001, W17-F002 PARTIAL
(residuals routed by the coordinator: TE SELL skew to CW-36, `classify_team` strength to CW-33, no preseason
guard for the sim). None is UNVERIFIABLE. Nothing in this PR changes served behaviour,
values, weights or confidence; it adds tests and this record only. Coordinator to record outcomes in the
audit status tooling.
