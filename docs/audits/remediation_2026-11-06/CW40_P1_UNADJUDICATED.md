# CW-40: adjudication of 12 "ran_clean_changed_or_nonquantitative" master-site-audit P1 findings

Adjudicated against `main` at `d838d012b6` (2026-11-06), the same way `CW40_P0_ADJUDICATION.md` and
`CW40_P1_OPEN_ADJUDICATION.md` did for the P0 and "still open" P1 sets. The November recount
(`master_audit_recount.json`) ran each August repro, saw it execute, and never compared its output to the
claim; "ran clean" therefore carries no evidence either way. Every check below is offline and deterministic:
pure functions, synthetic inputs, source-shape scans, or the tracked export archive
(`exports/archive/dynasty_export_20261106_194518.zip`, pinned by name where a number matters). No network, no
live board. Nothing here changes served behaviour, values, thresholds or methodology, and CLAUDE.md is not edited.

| id | classification | one-line evidence |
|---|---|---|
| W10-F001 | CLOSED_VERIFIED | `myMaxBid` / `myWinningBid` / `bayesianWinningBid` / `enforceUpTo` are all capped at `myRemaining` (`draft-logic.js:735,751-759,762,780`); pinned by `draft-bid-budget-invariant.test.js` |
| W11-F006 | CLOSED_VERIFIED | `ManualAddDrop.jsx:406` unwraps `data?.data` with no `\|\| data` fallback; pinned by `waiver-faab-context-envelope.test.jsx` |
| W12-F003 | PARTIAL | dead arbiter deleted, `src/signals/reconciler.py` + `GET /api/signals/reconciled` exist, five cutoffs now two; still no tracker/verdict by owner design |
| W12-F006 | OPEN | one player in one sweep still emails twice through two uncoordinated detectors (strict xfail) |
| W15-F009 | CLOSED_VERIFIED | rows carry `distinctManagers` + `managerConcentration` (`roster_percentage.py:816-863`), page shows them; pinned by `test_roster_percentage.py` |
| W19-F004 | CLOSED_VERIFIED | a season with zero games emits no awards (`awards.py:3256-3295`, one `_has_begun` rule); pinned by `test_awards_need_games.py` |
| W20-F001 | OPEN | no quoted `/api/gameplan` in any frontend source and no bridge route (strict xfail) |
| W20-F007 | CLOSED_VERIFIED | `scoreTeamTiers` deleted; /rosters renders one ordering and no `#` rank (`league-analysis.js:1094-1117`); pinned by `no-frontend-team-strength-methodology.test.js` |
| W20-F008 | PARTIAL | age axis is now continuous, but strict-`<` Rebuild still yields zero rebuilders on a tied league and the panel says nothing (`it.fails`) |
| W25-F003 | OPEN | CLAUDE.md still says rank-less rows are "past the 800 limit"; 76 of 251 are unpriced, max player rank is 740 (strict xfail on the doc) |
| W26-F003 | PARTIAL | `view=compact` (39% of full) via one URL helper; two of three reads still `cache: "no-store"` (strict xfail) |
| W27-F005 | PARTIAL | rank-space gap retired; residual TE skew 22 SELL / 1 BUY on the pinned board (strict xfail) |

Tally: 5 CLOSED_VERIFIED, 4 PARTIAL, 3 OPEN.

## W10-F001 (draft bids ignore remaining budget) - CLOSED_VERIFIED

**Claim.** With $4 left the /draft board said "Win at $69 / Max bid $80 / Push up to $48"; no ceiling read
`myRemaining`.

**Live path now.** `frontend/lib/draft-logic.js:735` `myWinningBid = max(0, min(theoreticalMaxBid, winByCompetitor,
myRemaining))`; `:751-759` `bayesianWinningBid` ends in `myRemaining`; `:762` `enforceUpTo` is `min(..., myRemaining)`;
`:780-782` `myMaxBid` is capped and `budgetCapped` says when the cap bit (`theoreticalMaxBid` keeps the uncapped
figure). `lib/perfect-draft.js::computeMaxBid` / `evaluateBid` are covered by the same test. Fixed by #2074.

**Evidence.** Existing test, not duplicated: `frontend/__tests__/draft-bid-budget-invariant.test.js`
(remaining of $4/$1/$25/$120 across every enriched player; $0 team gets Pass; recorded picks lower the ceiling;
an unaffordable bid is never "Push up"; plan max bid and verdict stay within budget). It passes on this head.

## W11-F006 (/waivers FAAB panel reads `data.body`) - CLOSED_VERIFIED

**Claim.** The panel unwrapped `data?.body || data`; the API envelope is `{contractVersion, league, section,
data}`, so every tile read undefined and rendered an em-dash.

**Live path now.** `frontend/components/waivers/ManualAddDrop.jsx:406` `const body = data?.data;`, ready only when
it is an object, else `feedUnavailable("response carried no analytics")` (`:407-411`). The comment at `:395-405` records
why no `|| data` fallback exists.

**Evidence.** Existing tests: `frontend/__tests__/components/waiver-faab-context-envelope.test.jsx` (populated
envelope produces numbers; a genuinely empty body still produces the em-dash, so a hard-coded fallback cannot pass) and
`waiver-faab-context-no-team.test.jsx`. Both pass.

## W12-F003 (no central Buy/Sell tracker) - PARTIAL

**Claim.** 16 emitters, five cutoffs on one quantity, no central tracker; the two arbiters were one flag-off and one
caller-less.

**Closed.** `src/news/unified_signal_engine.py` is deleted and nothing imports it. `src/signals/reconciler.py`
(C6-SIG-01) is the single read of every live emitter, side by side, deduped by lineage, and never blends; it is served by
`GET /api/signals/reconciled` (`server.py:19325-19326`) and consumed by the terminal ticker
(`frontend/components/terminal/MarketTicker.jsx`, `useReconciledSignals.js`). The five cutoffs collapsed on the surfaces the
audit named: `getPlayerEdge` (`trade-logic.js:1321-1328`) and `marketAction` (`display-helpers.js:259-310`) read the one
backend-stamped value-space ratio against the one constant `MARKET_GAP_MIN_VALUE_RATIO = 0.05` (`thresholds.js:99`);
the /edge premium panels use `PREMIUM_SUMMARY_VALUE_RATIO = 0.15` (`thresholds.js:120`).

**Still open.** There is no tracker page and no single verdict: the reconciler publishes disagreement as `conflict` by
design, `docs/EXECUTION_PLAN.md` keeps "central Buy/Sell reconciliation post-V1", `idpMarketAction` keeps its own IDPTC gate,
and the `consensus_edge` flag is still default OFF (`feature_flags.py:769`, ADR-023).

**Tests added.** `tests/api/test_audit_w12_f003_regression.py` (arbiter deleted and unimported; reconciler + route exist;
flag default pinned so a flip is deliberate) and `frontend/__tests__/audit-w12-f003-regression.test.js` (popup and
Rankings agree on BUY/SELL/none across both directions and the floor boundary; two constants, not five).

**Smallest candidate repair / gate.** None is a routine bug fix. A tracker surface or a cross-emitter verdict is owner
methodology (EXECUTION_PLAN post-V1; `docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md` section 3).

## W12-F006 (three email detectors, one player, one day) - OPEN

**Claim.** `signal_alerts` and `bdvm_signal_alerts` run back to back in one sweep over the same roster with the same
`email`, each delivering on its own with its own cooldown namespace; `custom_alerts` can add a third.

**Live path now.** `server.py:21340-21346` calls `_signal_alerts.process_user_alerts(... email=email,
delivery=_deliver_email_smtp ...)` and `:21357-21363` calls `_bdvm_alerts.process_user_bdvm_alerts(... same email,
delivery=_deliver_email_smtp ...)` in the same loop iteration. Each `process_user_*` builds and sends its own message
(`signal_alerts.py:281-340`, `bdvm_signal_alerts.py:279-321`). Nothing passes state from one to the other.

**Rebuilt repro.** `tests/api/test_audit_w12_f006_regression.py`: tmp `user_kv`, BDVM baseline seeded, then the same
player (Josh Allen) shown to both detectors with the same address and one stub transport. Result: two messages to one
address, one carrying "SELL" and one "STRONG_BUY" (opposite-capable vocabularies).

**Test added.** Passing: each detector delivers independently (documents the two-email state). `xfail(strict)`: at most
one message per user per player per sweep.

**Smallest candidate repair / gate.** In the sweep, collect the player keys the terminal detector just emailed
(`sleeperId`) and pass them to the BDVM call as a suppression set (BDVM keeps recording state but skips delivery for those
players), or merge both into one message. Gate: mostly routine, but "which detector wins / whether to merge" is a
one-line owner product call; `custom_alerts` is a separate route and out of this smallest repair.

## W15-F009 (Sharp Roster % has no per-manager concentration) - CLOSED_VERIFIED

**Claim.** One manager's five teams rendered as 83% with nothing on the row saying it is one person.

**Live path now.** `src/sharp/roster_percentage.py:816-822` computes `Counter(roster_manager[rk] for rk in counted)`;
every row carries `distinctManagers` and `managerConcentration` (`:862-863`). The page shows them through
`describeManagerConcentration` / `formatSample` (`frontend/lib/sharp-roster-percentage.js:78-105`, used at
`app/market/sharp-roster-percentage/page.jsx:266`).

**Evidence.** Existing tests: `tests/sharp/test_roster_percentage.py` (one manager holding five rosters gives
`distinctManagers == 1`, `managerConcentration == 1.0`; four managers 0.25; mixed 3 managers / 0.5) and
`frontend/__tests__/sharp-roster-percentage-lib.test.js` ("manager concentration" block). Both pass. The board-level
`transparency.uniqueSharpManagers` is unchanged. Not changed and not claimed: the headline percentage is still
roster-weighted (documented), the row now discloses concentration beside it.

## W19-F004 (awards manufactured from a season with zero games) - CLOSED_VERIFIED

**Claim.** The in-season 2026 block emitted eight all-zero awards (Points King 0.0 PF, Regular-Season Crown 0-0, League
MVP 0.0 VORP) and the Awards tab counted them in the "N yrs" badge.

**Live path now.** `src/public_league/awards.py:3247-3295`: `_has_played_games` / `_has_begun` are the single season-start
rule; a season that has not begun is refused by name, not emitted as an empty success, and also governs which season is
featured. `hasPlayerScoring` stays a diagnostic.

**Evidence.** Existing test file `tests/public_league/test_awards_need_games.py` (whose docstring cites this finding):
zero games manufactures no awards, the named defect awards are specifically absent, the refusal is explicit, one real
scored game lets awards appear, completed seasons are unchanged, there is exactly one season-start rule. 64 passed with the
sharp tests on this head.

## W20-F001 (`GET /api/gameplan` / `src/roster_intel` have no frontend consumer) - OPEN

**Claim.** The 92 KB per-team gameplan payload is called by nothing in `frontend/`.

**Live path now.** The endpoint is registered (`server.py:9707`). No quoted `/api/gameplan` appears in
`frontend/app|components|lib` outside comments and there is no `frontend/app/api/gameplan` bridge; the only mentions are
comments (`app/api/valuation/league-adjusted/route.js:32`, `lib/trade-war-room.js:361`, `lib/league-analysis.js:1112`).
Server-side consumers are real (`gameplan.league_competitive_postures` feeds trade posture, the league-adjusted overlay reuses
its cached bundle), so what is still true is only that the per-team gameplan itself reaches no UI.

**Test added.** `tests/api/test_audit_w20_f001_regression.py`: endpoint registered (passes); `xfail(strict)` a frontend
surface consumes it.

**Smallest candidate repair / gate.** Owner-gated: choosing the surface (e.g. /rosters or the trade War Room) is a
product/IA decision that needs `docs/EXECUTION_PLAN.md` authorization. Mechanically it is a bridge route plus one reader.

## W20-F007 (/rosters two contradictory rankings) - CLOSED_VERIFIED

**Claim.** The power table and the tier cards ordered the same 12 teams differently (Jason #1 vs #5).

**Live path now.** `scoreTeamTiers` is deleted (`frontend/lib/league-analysis.js:1094-1117`, retirement note). /rosters
sorts by the user's chosen column and carries no `#` rank (`app/rosters/page.jsx:121-130`, comment at `:348-358`); Team
Strength comes from the canonical owner via `TeamStrengthCard`.

**Evidence.** Existing test: `frontend/__tests__/no-frontend-team-strength-methodology.test.js` (`scoreTeamTiers` is gone
from the production graph, no frontend team-score formula) plus `components/team-strength-card.test.jsx`. Both pass.

## W20-F008 (/phases classifies zero teams as Rebuild and never says why) - PARTIAL

**Claim.** On live data six teams sat exactly at the integer league median age, Rebuild requires age strictly below it,
so zero rebuilders, `partnerships == []` and an unexplained blank.

**What changed.** The age input is now the canonical continuous `valueWeightedCoreAge`
(`team-phase.js` header; ladder from `GET /api/roster/intelligence`), not an integer median of a top-25, so the live
tie-at-the-median collapse is much less likely. Nothing offline can say what today's live league shows.

**What is unchanged.** `team-phase.js:55-57` still requires `medianAge < leagueMedians.age`, and
`TeamPhasePanel.jsx:230` renders the partner block only when `myPartnerships.length > 0`, with no empty state.

**Rebuilt repro.** `frontend/__tests__/components/audit-w20-f008-regression.test.jsx`: 12 fixed teams (five young
high-value, one old high-value, six low-value exactly at the median 26.0). `analyzeLeaguePhases`: zero Rebuild, six Mixed,
`partnerships == []`; the rendered panel is the table and the caption with no sentence about partners.

**Test added.** Passing: the zero-rebuild/zero-partner computation. `it.fails`: the panel explains an empty partner list.

**Smallest candidate repair / gate.** Routine: when `partnerships` is empty (or there is no Rebuild team) render one
sentence saying so and why. Changing the strict `<` rule or the quadrant cut is methodology and is not proposed.

## W25-F003 (CLAUDE.md attributes rank-less rows to the 800 limit) - OPEN (doc accuracy)

**Claim.** CLAUDE.md says rows `buildRows` numbers itself are "players past the backend's `OVERALL_RANK_LIMIT` (800) -
rows the backend deliberately left unranked"; the live board never reached 800 and all 239 such rows were unpriced.

**Measured now** (pinned archive, real `build_api_data_contract`): 1,105 rows, 740 ranked, maximum stamped rank 740, 251
unranked non-picks. They are two populations: 175 are priced past the cap (`offCapPlayerValue`, #1101: value stamped, no
rank) and 76 are unpriced (`rankDerivedValue` null, 74 of them single-source, mostly K/DL/DB) - not past any cutoff. The
other half of the original number changed (#1101 priced 175 of the rows the audit counted as null), but the doc is still
wrong for the 76, and the cap is shared with pick rows so no player sits at rank 800.

**Exact CLAUDE.md correction (not applied in this PR).** In the paragraph beginning "One precise nuance on ranks",
replace the sentence "In practice that is players past the backend's `OVERALL_RANK_LIMIT` (800) - rows the backend
deliberately left unranked - and it is suppressed for picks and whenever a valuation overlay is active." with:

> In practice that is two populations of non-pick rows the backend left unranked: players PRICED but past the rank
> limit (`OVERALL_RANK_LIMIT` = 800 counts pick rows too, so the highest stamped player rank is lower; these carry
> `offCapPlayerValue: true` and a real `rankDerivedValue`), and players the board could NOT price at all
> (`rankDerivedValue: null`, mostly single-source K/DL/DB). The second group is not "past a cutoff". The ordinal is
> suppressed for picks and whenever a valuation overlay is active.

and update the two stale line references in the same paragraph (`dynasty-data.js:1366` -> `:1594`, `:1378` -> `:1606`).

**Tests added.** `tests/api/test_audit_w25_f003_regression.py`: the unranked players partition into the two populations
(passes), max player rank is below 800 (passes), `xfail(strict)` CLAUDE.md names the unpriced population (flips when the
doc is corrected). `frontend/__tests__/audit-w25-f003-regression.test.js`: backend ranks win and priced rank-less rows
sort by value (passes); `it.fails` an unpriced row gets no `#` ordinal (today `buildRows` still numbers it, the finding's
display consequence).

**Smallest candidate repair / gate.** Routine doc-only edit to CLAUDE.md (above). The display consequence (unpriced rows
showing a `#`) is a separate small frontend change in `buildRows` and is routine unless the owner wants unpriced rows hidden.

## W26-F003 (/draft downloads the full contract) - PARTIAL

**Claim.** /draft fetched the full 11.95 MB `/api/data` to read 46.8 KB of team names from three call sites, two
with `cache: "no-store"`.

**Closed (#2079).** All three reads go through `draftContractUrl` -> `/api/data?view=compact&leagueKey=...`
(`frontend/lib/draft-feed.js`, `app/draft/page.jsx:4102,4373,4690`); no literal `/api/data` or `/api/dynasty-data` target
remains. On the pinned archive board the compact view is 7.11 MB against 18.09 MB full (0.39). Field coverage is pinned by
`tests/api/test_draft_contract_view_fields.py`.

**Still open.** The mount read (`page.jsx:4103`) needs only `sleeper.teams` yet pulls the whole compact view, and two of the
three sites still pass `cache: "no-store"` (`:4103`, `:4380`; `:4691` uses `force-cache`), defeating the HTTP cache and the
ETag/304 path.

**Tests added.** `tests/api/test_audit_w26_f003_regression.py`: no bypass of the compact URL (passes), compact under half
the full size (passes), `xfail(strict)` no `no-store` contract read.

**Smallest candidate repair / gate.** Routine performance fix: switch `:4103` to the cached read (it is idempotent
league-scoped data, same as `:4691`), and give the manual-sync read at `:4380` an explicit freshness reason or a conditional
fetch; optionally add a teams-only view. No methodology involved.

## W27-F005 (market-gap direction in rank space, 33/33 TE SELL) - PARTIAL

**Claim.** `marketGapDirection` was derived from ordinal ranks where no TE-basis correction exists, so every
edge-eligible TE was SELL.

**Closed.** `data_contract.py:4764-4824` (`_compute_market_gap`, `_stamp_ktc_market_benchmark`) delegates to
`ktc_market.compute_market_gap`: our `rankDerivedValue` against KTC Market in value space, no rank, no position;
`marketGapMagnitude` is stamped None. The stamper's position-blindness is pinned by
`tests/api/test_audit_w12_f002_regression.py` (the W12-F002 P0 PARTIAL record).

**Still open.** On the pinned board, rows the board labels (top-250, ratio >= 0.05): TE 22 retail_premium / 1
consensus_premium (96% SELL), RB 27/5, WR 27/15, QB 6/15. At the stricter 0.15 panel gate the sets are tiny (TE 4/0, RB 7/0).
The 33/0 became 22/1; it did not become balanced.

**Tests added.** `tests/api/test_audit_w27_f005_regression.py`: rank-space field retired on every real row (passes); the
August 33/0 shape is gone but the skew is real (passes); `xfail(strict)` TE labels are not >90% one-sided.

**Smallest candidate repair / gate.** Gated. The residual is a TE basis/calibration question in our value versus KTC TE++
pricing, the same owner decision already routed for W12-F002 (CW-36). No routine fix exists.

## Routing summary

Routine bug fixes (candidates for an immediate follow-up PR): W25-F003 (CLAUDE.md edit, exact text above), W26-F003
(drop `no-store` on the two /draft reads), W20-F008 (empty-state sentence on /phases), W12-F006 (cross-detector suppression;
confirm the merge rule with the owner in one line).
Owner / methodology gated: W12-F003 (central Buy/Sell is post-V1), W20-F001 (which UI consumes gameplan), W27-F005 (TE basis).

## Reproduction commands

```
python -m pytest tests/api/test_audit_w12_f003_regression.py tests/api/test_audit_w12_f006_regression.py \
  tests/api/test_audit_w20_f001_regression.py tests/api/test_audit_w25_f003_regression.py \
  tests/api/test_audit_w26_f003_regression.py tests/api/test_audit_w27_f005_regression.py -q
cd frontend && npx vitest run __tests__/audit-w12-f003-regression.test.js \
  __tests__/audit-w25-f003-regression.test.js __tests__/components/audit-w20-f008-regression.test.jsx
```

Existing tests cited for CLOSED_VERIFIED rows: `frontend/__tests__/draft-bid-budget-invariant.test.js`,
`frontend/__tests__/components/waiver-faab-context-envelope.test.jsx`, `tests/sharp/test_roster_percentage.py`,
`frontend/__tests__/sharp-roster-percentage-lib.test.js`, `tests/public_league/test_awards_need_games.py`,
`frontend/__tests__/no-frontend-team-strength-methodology.test.js`.
