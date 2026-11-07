# CW-40 P1 re-audit — batch t1

Owner directive 2026-11-07 §4 (CW-40). Fourteen P1 findings from the 2026 master site audit, re-derived against current `main` (`17d8bd7290`). The recount's `repro_rotted` / `unsafe-to-rerun` labels were treated as baselines, not verdicts: every repro below was re-run on current code against the tracked export archive (`tests/archive_fixtures.newest_complete_contract()`, archive `dynasty_export_20261107_063955`), never the network. Assertions are invariants, not absolute counts over the live board.

Scope notes. Not touched (owned elsewhere): `frontend/app/api/trade/suggestions/route.js`, `frontend/app/draft/page.jsx`, `src/api/gameplan.py`, `frontend/app/rosters`, `src/api/signal_alerts.py`, `src/api/bdvm_signal_alerts.py`. No repair in this batch changes a player value, rank, threshold, weight or formula; no source edits were made at all (every re-verified-closed finding is closed in code already; the open ones are methodology or product choices).

Tests: JS `frontend/__tests__/audit-cw40-batch-t1.test.js` (11 tests); Python `tests/api/test_audit_cw40_batch_t1_closed.py` (11 tests) and `tests/api/test_audit_cw40_batch_t1_open.py` (5 passing characterizations + 3 strict xfails).

## Verdict summary

| Finding | Verdict |
|---|---|
| W08-F002 | CLOSED_VERIFIED |
| W08-F003 | CLOSED_VERIFIED |
| W08-F004 | CLOSED_VERIFIED |
| W08-F005 | CLOSED_VERIFIED (identity/representability; owned-pick pricing is the deferred C1-U7, see section) |
| W08-F007 | CLOSED_VERIFIED |
| W09-F001 | CLOSED_VERIFIED (whole-roster analysis + diagnosis; zero-result rate 8→5 of 12, not asserted) |
| W09-F002 | CLOSED_VERIFIED (shape skew toward 1-for-2 remains; scoring is owner-reserved) |
| W09-F003 | PARTIAL (finder fixed via posture-aware generation; suggestions send side still player-only — owner decision) |
| W09-F004 | CLOSED_VERIFIED |
| W09-F005 | PARTIAL |
| W09-F006 | CLOSED_VERIFIED (superseded: lens withdrawn, offense-only board deleted) |
| W10-F004 | OPEN |
| W13-F002 | OPEN |
| W27-F003 | REQUIRES_OWNER_DECISION |

---

## W08-F002 — VA tooltip said "fewer pieces" — CLOSED_VERIFIED

**Claim.** `SideCard` told users the VA bonus goes to the side with fewer pieces; 46.7% of fired VAs went elsewhere.
**Requirement.** CLAUDE.md "Trade comparison": active model is geometric `geom_q078_v1` (owner 2026-10-17); VA credits concentration, `adjusted = raw + VA`.
**Code.** `frontend/app/trade/trade-sections.jsx:714-735` (retired `title=` removed; comment records why); `frontend/components/help/TradeHelp.jsx:46-66` (`ValueAdjustmentTip`: "usually the side with fewer, better pieces, but it can fire on equal-count trades too", "Never applied to a 1-for-1"). `frontend/lib/trade-logic.js:751-770` (`packageAdjustPair`).
**Repro (current).** `packageAdjustPair([9000,1000],[5000,5000])` fires on equal counts; 4-piece `[9000,3000,2000,1700]` vs 3-piece `[5500,4300,4000]` credits the four-piece side; 1v1 never fires. Copy now says exactly that.
**Test.** `audit-cw40-batch-t1.test.js` › "W08-F002" (copy absent from source; the denied behaviours are real).

## W08-F003 — adding an asset can worsen your side — CLOSED_VERIFIED

**Claim.** KTC-model VA is discontinuous in the piece set, so adding a positive asset to A could lower A's adjusted total (1.1-1.9% of trades).
**Requirement.** Owner activation 2026-10-17 of geometric `U = Σ q^(i-1)·v_i`; `adjustedA − adjustedB = U_A − U_B` (trade-logic.js:781-792 docstring).
**Code.** `trade-logic.js:751-770`, `:824-846`, `:1157-1175`. Under the geometric model `U_A` is strictly increasing in every added piece, and the only discontinuity (1v1 suppression) is a no-op because depth is 0 there.
**Repro (current).** 4,000 seeded 1-3 v 1-3 trades, add a 300-5,000 asset to A: 0 cases where the gap falls by more than 1 point (integer rounding of VA). The audit's KTC-era counts do not reproduce.
**Test.** `audit-cw40-batch-t1.test.js` › "W08-F003" (seeded sweep + the 1v1→2v1 shape).

## W08-F004 — 2026 picks unsearchable (hardcoded `/^2026\b/`) — CLOSED_VERIFIED

**Claim.** `searchAssets()` and both balancer pools excluded every 2026 pick row by a hardcoded year regex.
**Code.** Eligibility is now one predicate, `isTradeableBoardRow` / `isSuppressedGenericPickRow` (`trade-logic.js:1529-1558`), keyed on the backend stamp `pickGenericSuppressed`, not a year; used by `app/trade/page.jsx:1335-1357` (balancer pool) and `searchCalculatorAssets` (page.jsx:1448-1470).
**Repro (current).** For years 2026, 2027, 2031 the slot row is offered and only the suppressed alias is hidden; no year-literal `.test(` remains in `page.jsx` or `trade-logic.js`.
**Test.** `audit-cw40-batch-t1.test.js` › "W08-F004". (Existing `trade-pick-search.test.js` covers the same on synthetic rows.)

## W08-F005 — pick original-owner identity discarded — CLOSED_VERIFIED (identity); pricing deferred

**Claim.** `/trade` read only `team.picks` (label strings); eight "2027 1st" collapsed to one row and the duplicate-name guard made seven untradeable.
**Requirement.** CLAUDE.md "Pick identity" + owner decision 2026-10-03 (every asset repeatable).
**Code.** `frontend/lib/trade-assets.js:175-239` (`ownedPickEntry`/`teamPickEntriesKnown` read `pickDetails[].assetId`), `:71` (`tradeEntryKey` = assetId), `:94` (`canAddEntry` is always yes for a valid row); `page.jsx:1470-1485` (`addToSide` has no name guard).
**Repro (current).** Eight same-label `pickDetails` → eight entries, eight distinct keys, all addable, eight groups.
**Residual (not a defect of this finding).** Owned picks whose slot is unknown still price at the generic/tier grade by the declared C1-U6/U7 design ("no owned-pick forecasting — that is C1-U7"); a rebuilding team's first is therefore priced like a contender's on the calculator. That is the deferred C1-U7 methodology, owner-gated, not re-opened here.
**Test.** `audit-cw40-batch-t1.test.js` › "W08-F005".

## W08-F007 — 'Raw' value mode incomparable across asset classes — CLOSED_VERIFIED

**Claim.** The Raw dropdown put the legacy scraper composite (non-constant ratio to the board) on the meter; one click flipped FAIR to UNFAIR.
**Code.** `trade-logic.js` `VALUE_MODES` is `[{key:"full"}]` and `TRADE_VALUE_MODE = "full"`; `page.jsx` has `const valueMode = TRADE_VALUE_MODE;` and no Value-mode select (TC-A / UX audit P0-4).
**Repro (current).** LaPorta (5,222, raw 5,564) vs Styles (5,222, raw 4,180) totals 5,222 vs 5,222 whatever `.raw` says; no select in the page source.
**Test.** `audit-cw40-batch-t1.test.js` › "W08-F007".

## W09-F001 — suggestions returned zero for 8 of 12 teams, no diagnosis — CLOSED_VERIFIED

**Claim.** Single-population top-150 gate left `rosterMatched` at 3-21 of 44-58; no reason in the payload.
**Requirement.** CLAUDE.md "Trade Engines": roster ANALYSIS reads the whole roster; what may be OFFERED stays in the quality pool (owner inventory 2.3/2.4).
**Code.** `server.py:10379-10420` builds the full board once and passes `roster_pool=full_pool`; `src/trade/suggestions.py:2269-2314` (`noResultReason`, `rosterAnalysisPool: "full_board"`, `positionalFloor`).
**Repro (current, 12 archived rosters).** `rosterMatched`/`rosterProvided` 51-57 of 56-58 for every team; unmatched players are named in `rosterUnpriced`; every zero-suggestion team carries `noResultReason` (`no_offerable_surplus_in_quality_pool`) + label + `generatorDiagnostics`.
**Limitation.** On the archived board 5 of 12 teams still get zero suggestions (audit: 8 of 12) when called without `league_rosters` — now explained, with the generic reason `no_offerable_surplus_in_quality_pool`, which is the original finding's complaint ("no diagnosis"). Whether zero is the right *answer* for them is a product-quality question, not asserted here.
**Test.** `test_audit_cw40_batch_t1_closed.py` › `test_w09_f001_*`.

## W09-F002 — every finder trade was 1-for-2 — CLOSED_VERIFIED

**Claim.** 480/480 returned trades were 1-for-2; first 1-for-1 at rank 2,159; 2-for-1 never qualified. Cause: `board_gain_norm = board_delta / give_model` rewards a smaller give side against a flat −3 simplicity term.
**Code.** `src/trade/finder.py:722-910` (`_score_trade_on_values`; the give-side normaliser is unchanged) but scoring now runs through the package Value Adjustment (`score_with_value_adjustment`), and generation covers 2-for-1, 2-for-2, 3-for-2, 2-for-3 (C3-TOPO-01).
**Repro (current, one team, `max_results=100000`, 4,582 qualified).** shapes: 1-for-2 3,593; 2-for-1 615; 1-for-1 226; 2-for-3 100; 2-for-2 48. First 1-for-1 is rank 0, first 2-for-1 rank 159. League-wide default (40 per team): 1-for-2 343, 1-for-1 134, 2-for-1 3.
**Limitation.** 1-for-2 is still ~70-78% of the list and 2-for-1 is thin. The give-side normalisation is a ranking-methodology choice, so it was not touched; flagged as an observation, not a defect of this finding.
**Test.** `test_w09_f002_finder_returns_more_than_one_package_shape`.

## W09-F003 — picks never appear in finder/suggestion results — PARTIAL

**Claim.** `_resolve_roster` reads only `players`, so no pick reaches a trade.
**Requirement.** C7-PICKGEN-01: picks enter generated trades only through a posture-aware generator (a complementary PUSH vs RETOOL/REBUILD pair, Team Context ON), never as filler.
**Code.** `finder.py:1219-1340` (`_owned_pick_assets` from canonical `pickDetails`/`assetId`) and `:1339-1428` (`_posture_pick_packages`); `server.py:10620-10650` passes `postures` and `pick_forecasts`.
**Repro (current).** PUSH requester vs RETOOL league, Team Context ON: 196 of 4,778 qualified trades carry a pick (assetId `pick:dynasty_main:…`, flag `posture_aware_pick`); with no posture pair, none (`pickGeneration.applied=false`). The suggestions engine's *send* side is still player-only. C7-PICKGEN-01 rule 5 (cited at `suggestions.py:1621`) only forbids picks as balancers; it does not make a player-only send side intended, so the suggestions half of the finding stays open.
**Owner decision.** Should `/api/trade/suggestions` propose sending owned picks through the same posture-aware generator the finder uses (C7-PICKGEN-01), or is a player-only suggestions engine intended? No xfail is pinned until that intent is decided.
**Test.** `test_w09_f003_*` (two).

## W09-F004 — no DB eligible for any suggestion — CLOSED_VERIFIED

**Claim.** The top-150 pool held zero DBs while the league starts three.
**Code.** `suggestions.py` positional floor (2026-10-14): each demanded position admits its top `starters × teamCount`; `metadata.positionalFloor.addedByPosition`.
**Repro (current).** Top-150 holds 1 DB; the floor adds 35 more; `starterNeeds.DB == 3`.
**Test.** `test_w09_f004_dbs_enter_the_pool_through_the_positional_floor`.

## W09-F005 — Monte Carlo flat ±15% and 9999 clamp — PARTIAL

**Claim.** (a) flat ±15% band on every asset; (b) `_shifted()` clamped to 9999 so elite assets simulate below board; (c) no convergence diagnostic.
**Code.** `src/trade/monte_carlo.py:454-478` (clamp removed, zero floor only), `:495-509` (synthetic fallback labelled `band_source`), `:112-150` (`to_dict` disclaimer names the synthesized band).
**Repro (current).** (b) CLOSED: the board's top asset simulates within 1% of its value (20,000 draws, seeded). (a) still true — no stamped `valueBand` exists on any live row, so the ±15% fallback is the production path; but it is now explicitly labelled (`bandSources`, disclaimer "an assumption, not a measurement"). (c) OPEN: no seed echo / standard error / CI on the result.
**Decision needed (methodology).** Whether to replace the constant band with a measured one (e.g. from `src/canonical/confidence_intervals.py`) — owner-reserved; not touched. Sampling-error disclosure is routine but was left unimplemented because the field names/semantics are an API contract choice.
**Tests.** closed: `test_w09_f005_*` (2); open: `test_audit_cw40_batch_t1_open.py` › `test_w09_f005_result_discloses_its_own_sampling_error` (strict xfail) + characterization.

## W09-F006 — leagueAdjusted lens a silent no-op — CLOSED_VERIFIED (superseded)

**Claim.** The overlay scaled `rankDerivedValue` only; engines preferred `offenseOnlyRankDerivedValue`, so the lens did nothing yet was stamped `leagueAdjusted`.
**Requirement.** CLAUDE.md "valuation_mode: accepted, ignored, and stamped" (lens WITHDRAWN 2026-08-14) and B9a (second canonical board deleted).
**Code.** `src/trade/valuation_scope.py:24-36` (`scoped_contract`: same object, mode `market`, note `league_adjusted_withdrawn: not_canonical`); `server.py:12295-12380`. `offenseOnlyRankDerivedValue` no longer exists in any engine or the overlay.
**Repro (current).** `POST /api/trade/simulate` for Bowers-for-Taylor+Mahomes with `valuationMode` `market` vs `leagueAdjusted`: identical per-asset values and equity; response stamps `valuationMode: "market"` in both, plus the withdrawal note on the second.
**Test.** `test_w09_f006_*` (3, incl. the real route).

## W10-F004 — vendor "Market" dollars normalised over different row counts — OPEN

**Claim.** `_vendor_dollars_for_rookies` spreads $1,200 over each vendor's own covered rookies (45 KTC, 63-70 IDPTC vs our 72), so KTC overrates ~every covered rookie.
**Requirement.** `page.jsx` / `draft-logic.js:2047-2121` document `vendorDollar − preDraft` as an honest "how many more dollars would a vendor-following leaguemate spend at this slot than my board does".
**Code.** `server.py:12918-12950` (`_vendor_dollars_for_rookies`) → `_rookie_dollars_from_values` (`:13019`); consumers `server.py:14263` (default league) and `:14780` (fallback). `_rookie_dollars_from_values`'s own docstring says it "stretches the curve over however many there are".
**Repro (current).** Archived board: KTC covers 45 of 72; its dollar exceeds ours for 43 and is below for 2 (audit: 44/0). Synthetic control: a vendor that agrees with our board on every covered rookie still shows gaps up to ~$4 on the first rookie because its 45 rows share the same $1,200.
**Why not repaired.** The honest alternative (price a vendor's rank-n rookie at our ladder's rank-n dollars; leave the uncovered tail missing; or scale the vendor's pool to its covered share) changes displayed dollars and the nomination/best-value ordering — a methodology choice.
**Decision needed (owner).** Which basis for a partial-coverage vendor list: (A) vendor rank-n ⇒ our canonical ladder dollars at rank n, tail unpriced; (B) normalise to the covered share of the $1,200 our board assigns to those ranks; (C) hide vendor dollars below a coverage floor.
**Tests.** characterization ×2 (pass); strict xfail `test_w10_f004_a_fully_agreeing_partial_vendor_shows_no_gap`.

## W13-F002 — BDVM roster capitals exclude draft picks — OPEN

**Claim.** `analyze_rosters` builds `assets` from `playerIds` only; `picks` feeds only `pickCount`; no "pick capital" exists although the module docstring promises it; 2 of 12 direction labels flip when picks are counted.
**Code.** `src/bdvm/roster.py:6` (docstring), `:60-72` (picks normalised, unknown ⇒ `None`), `:150-172`, `:223-224` (`pickCount` only). Unknown pick ownership is handled correctly (`None` + reason) — that part is fine.
**Repro (current).** Fixture roster holding two picks: `capitals.rebuilder` is the players' sum only (23,700); no pick-capital key. `capitals`, `nowFutureRatio`, `valueWeightedAge`, the direction label and every asset in the double-positive scan remain player-only.
**Why not repaired.** Folding pick EV (`src/bdvm/picks.py` distributions per strategy) into strategy capitals changes `nowFutureRatio` and therefore league-relative direction labels and trade-scan output, and needs a choice for unknown-slot picks.
**Decision needed (owner).** Do picks enter BDVM strategy capitals (and the trade scan) at all, and if so at which grade for an unknown-slot pick (generic EV vs forecast)? Interim, no-value option if wanted: correct the docstring and add an explicit `capitalsIncludePicks: false` field so `/bdvm` cannot read `pickCount` as priced.
**Tests.** characterization (pass); strict xfail `test_w13_f002_a_roster_holding_picks_reports_pick_capital`.

## W27-F003 — /angle can never return an IDP player in a counter-package — REQUIRES_OWNER_DECISION

**Claim.** `include_idp` defaults False in the engine and server, and the page never sends `includeIdp`.
**Code.** `src/trade/angle.py:712,915` and `:1278,1482` (exclusion is intentional, documented: "most leaguemates don't gravitate toward them"); `server.py:11982-11994` (default False; an explicit IDP `positions` entry implies opt-in); `frontend/app/angle/page.jsx:317-345` builds the body without it; `grep includeIdp frontend/` is empty.
**Repro (current).** Unchanged from the audit: the control does not exist in the UI.
**Why not repaired.** Whether a counter-package may include defenders by default — or behind a toggle, or only in `idpEnabled` leagues — is a product choice; the engine default is a documented, deliberate rule, and the page copy "KTC for offense, IDPTC for IDP" is true of the *offer* side (IDP accepted).
**Decision needed (owner).** Pick one: (1) add a visible "Include IDP" toggle, default off; (2) default on when the league has `idpEnabled`; (3) keep exclusion and amend the page copy to say counter-packages are offense-only.
**Test.** characterization pinning page / engine / route defaults (passes today; update it when the decision lands).

---

## Adjacent observations (not adjudicated)

- Under pytest the league registry is isolated, so `starter_needs_for_league("dynasty_main")` returns `None`; tests must pass the needs dict explicitly (done here).
- `tests/api/test_league_routing.py`'s `two_league_registry` fixture is reusable from other test modules (done here for the simulate route test).
