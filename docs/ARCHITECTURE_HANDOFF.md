# Architecture Handoff

**What the next model/session must not have to rediscover.**

This file exists because the engagement runs across model handoffs (Fable/UltraCode for planning
and canonical foundations → Opus/High for bulk implementation → Fable/UltraMax for the final
adversarial audit), and the failure mode it guards against is an implementing model solving a
problem page-locally that already has a canonical owner. Update it at **every** handoff.

`docs/WORK_CLAIMS.md` says who is touching what right now. `docs/master-site-audit/` holds audit
state. This file holds **architecture** state.

---

## Current position

| | |
|---|---|
| Branch | `claude/dynasty-audit-consolidation-e75vdy` |
| **Validated implementation HEAD** | `efa18f0e6` — the exact tree that received the full Python suite, full frontend suite, build and lint below |
| **Validation base** | `origin/main` @ `4ac9b22b2` (the merge-base). `main` has since advanced 5 automated-refresh commits to `73c5e2776`; none is merged here, deliberately — see the B1 input-pinning note |
| **Post-validation commits** | Correction-pass commits after `efa18f0e6` carry their own targeted gates, recorded per commit. Any that change production or test behavior re-run the suites; documentation-only commits do not |
| **Handoff document commit** | This file is committed *after* the state it describes, so it cannot contain its own SHA. Read the fields above, not "current HEAD" |
| PR | [#776](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/776) — Validate PR **green** at the last pushed state |
| Working tree | clean at each recorded gate |
| **Model-input snapshot** | Pinned and hashed by `docs/master-site-audit/evidence/W30/b1_denominator_measure.py` — required before any B1 comparison, because `main`'s 2-hourly refreshes rewrite the fit's own CSVs |
| Phase | **A FORMALLY CLOSED 2026-08-11.** B1 authorized and executed to the evidence boundary: coordinate repair merged, challenger measured, **nothing promoted**. B2 and later NOT started — owner gate below. |

> **Why these fields and not "current HEAD".** A Markdown file committed at one
> SHA cannot literally contain that SHA, so a field claiming to be "the commit
> containing this document" is stale the instant it is written, and inviting a
> reader to trust it is worse than omitting it. What a reader actually needs is
> *which tree was tested*, *what it was tested against*, and *what has moved
> since* — which is what the rows above state separately.

### Measured gates at this HEAD

| gate | result |
|---|---|
| `pytest tests/ -q` | **7,070 passed / 0 failed** / 25 skipped / 633 subtests. Trail: 7,001 at `4ac9b22` → 7,008 at `efa18f0e6` (+7 closure-harness) → 7,026 (+18 when those were rewritten to drive real production logic) → 7,038 (+12 B1 pin-coverage guard) → 7,070 (+32 percentile-coordinate contract, minus one file's rename). Every delta is accounted for by new tests; no existing test changed state. |
| `vitest run` (frontend) | **2,010 passed / 0 failed**, 121 files — trail: 2,004 → 2,007 (+3 FAAB missing-vs-zero) → 2,010 (+3 multi-team trade crash regression) |
| `ruff format --check .` | 991 files already formatted |
| `ruff check .` | All checks passed |
| `scripts/check_decision_coercions.py` | clean — no new coercions, no stale allowances |
| `scripts/audit_status.py` | no drift (C-tracker: 21 closed / 19 open / 2 needs_review / 1 deferred) |
| `npm --prefix frontend run build` | compiled; **all 14 route bundle budgets under** |
| Stack bring-up | `/api/status` `has_data: true`, 1,095 players, scrape suppressed |

Environment: python 3.11.15 in `.venv` (`scripts/setup.sh`), node 22.22.2, vitest 4.1.10.
The clone must be **unshallowed** (`git fetch --unshallow`) or every git-derived audit signal lies.

> **CI splits the Python suite; add both halves.** `Validate PR` runs
> `pytest tests/ -x -q -m "not livedata"` as the hard gate (6,817 passed / 278 deselected /
> 295 subtests, 456s) plus a non-blocking livedata pass (253 passed / 25 skipped / 338
> subtests, 41s) — and 6,817 + 253 = the 7,070 above.
>
> **This container runs the same suite in ~24 minutes, about 3x CI.** Measured end to end:
> 6,881 passed / 0 failed / 278 deselected / 295 subtests in **1429s (23m49s)**, CPU-bound
> throughout, no disk or memory pressure. `tests/api` (118 files, each building the 4 MB
> contract) dominates. Do **not** extrapolate a total from the early percentage — the run is
> front-loaded with slow work and an early-phase rate implies wildly wrong totals; an earlier
> note here claimed "a pace implying ~4 hours" on exactly that mistake. Let it finish, or read
> the CI job.

### Phase A formal closure — 2026-08-11

All nine exit criteria satisfied and evidenced:

| # | Criterion | Result |
|---|---|---|
| 1 | Claim ledger frozen and committed | `claims-frozen-2026-08-05.json`, 85 claims; ledger now 86 |
| 2 | Unshallow verdict recorded | 4,878 commits; all 85 claim SHAs resolve; `8b88623f` confirmed NOT an ancestor of main |
| 3 | Stack answers `/api/status has_data:true` | 1,095 players; `last_scrape: null`; exactly one SUPPRESSED line |
| 4 | Test figures recorded with toolchain stamp | 7,008 / 0 python, 2,004 / 0 frontend — both above |
| 5 | WORK_CLAIMS row live | Added; `check_work_claims.py` clean |
| 6 | #758–763 dispositioned | `docs/BRANCH_DISPOSITION_2026-08-11.md` — all six re-derive, never merge |
| 7 | Quick wins green or explicitly deferred | 3 landed red→green; W31-F001 explicitly deferred with its prescribed fix refuted |
| 8 | Zero edits to the concurrent session's file set | Verified by set intersection: empty |
| 9 | Branch pushed, PR open, CI green | PR #776, Validate PR success |

**Phase B is NOT started.** Owner gate 2026-08-11: no B1-or-later source implementation until
explicitly authorized; no `promote` / `apply`, production constant change or challenger promotion
without evidence presented for approval first.

---

## Rules the implementing model must not bypass

These are load-bearing invariants, not style preferences. Each has an incident behind it.

1. **No frontend ranking engine, ever.** `buildRows` is a pure materializer; it consumes backend
   stamps verbatim. The one exception is a display ordinal for rows the backend deliberately left
   unranked. A client-side blend fallback was deleted for a reason — if stamps are missing, the
   pipeline is broken upstream.
2. **Missing is never zero.** Return `None`, stamp a reason, let the surface abstain. This is the
   platform's characteristic defect; `scripts/check_decision_coercions.py` gates it with a
   ratchet (692 accepted as debt, new ones blocked).
3. **One FAAB formula**, in `src/trade/faab_engine.py`. The JS port was deleted deliberately.
4. **Team Strength is Top-N by canonical league-adjusted value** — QB3/RB3/WR5/TE3/DL5/LB5/DB5 —
   **never solver-derived.** The lineup solver (`src/ros/lineup.py::solve_optimal_assignment`) is
   for lineup utility, Flex, Team Weakness and Perfect Waivers; it stays conceptually separate.
   (Owner ruling, 2026-08-11.)
5. **Scoring profile controls rankings; league key controls context.** Never index rankings
   per-league; never collapse rosters across leagues.
6. **Tools must not destroy the evidence they maintain.** Two instances found and fixed in
   Phase A; **the third was found in B1.2** — `load_or_seed_registry` treated any load failure
   as "no registry" and overwrote the champion history with a fresh seed. It fired for real:
   `championVersion` 2 → 1, versions `[1,2,3]` → `[1]`, restored from git. Fixed and pinned
   (`W30-F024`). Assume a fourth exists.
7. **A claim is not a measurement.** Reproduction settles closure. `Closes W##-F###` in a commit
   is a claim; the audit harness now labels reruns honestly rather than calling them closed.
8. **One root cause per commit**, red-before-green, full suites only on a quiescent tree.
9. **A green build is not evidence a symbol resolves.** Bundlers compile an un-imported free
   variable to a global lookup, so a missing import is a *runtime* `ReferenceError` on the first
   call site that executes — not a link error. `/trade` shipped with `defaultDestination` called
   at nine sites and imported at none; it loaded fine, two-team trades worked, and the entire
   3+-team feature was dead for two and a half weeks under green CI and a green
   `npm run build`. Regression tests for this class must **drive the component**, never grep the
   import. Full write-up: `docs/master-site-audit/evidence/W08/TRADE_MULTI_TEAM_CRASH.md`.

---

## Canonical owners (as of this handoff)

| concept | canonical owner | status |
|---|---|---|
| Live player value | `src/api/data_contract.py::_compute_unified_rankings` | established |
| Hill curves / percentile→value | `src/canonical/player_valuation.py` | **coordinate repaired this session (B1)**; it now owns `PERCENTILE_REFERENCE_N` / `rank_to_percentile` / `training_percentiles` and fit + holdout + serving all consume it. Constants unchanged — challenger measured, not promoted |
| Player identity | `src/identity/` + `unified_mapper` | defects open (W06 batch — B5) |
| League registry / scoring | `src/api/league_registry.py`, `src/league_intel/config.py` | profile identity defect open (W18-F001 — B6) |
| Trade asset eligibility | `frontend/lib/trade-logic.js::isTradeableBoardRow` | **established this session** |
| Multi-team destination routing | `frontend/lib/trade-logic.js::defaultDestination` | established; **the page stopped importing it in #552 and crashed for 3+ teams until this session** — see rule 9 |
| FAAB bids | `src/trade/faab_engine.py` | established |
| Rookie auction optimization | `src/draft/` + `frontend/lib/perfect-draft.js` | established (registry's "missing" is stale) |
| Closure measurement | `docs/master-site-audit/tools/verify_closure.py` | **repaired this session** |
| Team Strength | — | **does not exist; C1 build** |
| Team Weakness | `src/roster_intel/` (unconsumed, unverified) | **C2 must verify/repair before canonicalizing** |
| Acquisition history | — | **does not exist; C3 build** |
| Central Buy/Sell | — | **does not exist; E2 build (22 emitters today)** |
| ~~Schedule generator~~ | — | **REMOVED FROM SCOPE by the owner 2026-08-11** — not a build, not a blocker, not backlog. `W28-F001` is `published: false`. See `docs/OWNER_FEATURE_INVENTORY.md`. |
| Podcast intelligence | — | **does not exist; E6 build** |

---

## What Phase A established (do not re-derive)

- **The registry is stale in both directions.** Five corrections recorded in
  `docs/master-site-audit/REBASELINE_2026-08-11.md`. Verify every finding at HEAD before
  scheduling repair. The sharpest case: findings marked closed by `00a3ce2c`, a commit on the
  audit branch whose code half never reached `main` (PR #745 lifted only the docs).
- **Claims do not survive squash-merges.** `claims-frozen-2026-08-05.json` is now the durable
  ledger; `verify_closure.py` merges it under a live range scan. Without it the tool reports 2
  claims instead of 86 and reclassifies 84 findings.
- **The closure harness had two evidence-destroying defects**, both fixed and pinned by
  `tests/audit/test_verify_closure.py`: a crashed reproduction was stamped closed, and `--id`
  published a truncated ledger (429 records silently discarded in a live run).
- **W31-F001's prescribed fix is refuted.** `git rm --cached` on the runtime-written data files
  would freeze production's `source_health` — CI force-adds those paths every 2h and keys deploy
  dispatch on the resulting commits. Real repair: reroute the prod backend's runtime writes to an
  untracked path (touches `server.py`, currently claimed).

## Competitive expansion addendum (OTC Fantasy + Play For Keeps)

Owner-approved 2026-08-11 as **future product scope and an
architecture/planning directive** — **NOT** production-implementation
authorization. CE-01 … CE-16 product code must not begin yet, and did not begin
during B1.

What is authorized now: discovery, reconciliation, architecture, feature-inventory
integration, dependency mapping, plan integration. What is not: any
competitor-derived production feature.

Standing constraints recorded so a later session cannot lose them:

- Current execution priority remains **foundational repair**. If forced to choose,
  canonical identity beats a competitor page; Team Strength correctness beats a
  Pick Projector UI; a correct Trade Calculator beats send-to-Sleeper.
- Minimum new canonical owners when CE work is authorized: `market_trade_ledger`,
  `market_adp`, `manager_intelligence`, `projection_and_stats`,
  `league_action_gateway`, `share_renderer` (plus `command_center`,
  `pick_forecast`). Pages consume; pages do not reimplement methodology.
- Signal populations stay distinct: Market Trade Ledger (broad market) is NOT the
  Sharp Ledger (curated managers) is NOT Insider Trading (specific leaguemates).
  No observation population may be counted twice.
- Decision plane and mutation plane are separate. A recommendation must never
  execute as a side effect; every Sleeper write goes through the Action Gateway.
- Removed scope stays removed: Schedule Generator, Dispersal Draft, standalone
  Rookie WR model, generic Best Ball suite, article CMS, podcast hosting,
  automatic trade spam, social network, billing.
- Manager Scout is fantasy-behavior analysis only — no real-world identity
  enrichment, external personal-data scraping, financial or psychological
  profiling.
- Competitor research boundary: study capabilities and workflows; never copy
  source, private APIs, copy, branding or protected assets.

**Not yet produced** (the reconciliation pass, deliberately deferred so it could
not contaminate B1): `docs/competitive/OTC_PFK_FEATURE_AUDIT.md` and
`docs/competitive/COMPETITIVE_EXPANSION_ARCHITECTURE.md`, plus the CE-01…CE-16
rows in `OWNER_FEATURE_INVENTORY.md`.

## Deliberate refusals — do not silently undo

| finding | why |
|---|---|
| W08-F003 | Trade-meter non-monotonicity is KeepTradeCut's own published algorithm, ported verbatim in `src/trade/ktc_va.py` for parity. "Fixing" it breaks what the port exists for. Owner decision pending on advisory-badge vs clamp. |
| W20-F013 | Accepting a query param no UI can set converts a missing feature into a hidden one. |
| W12-F007 (half) | Suppressing the verb on low `confidenceBucket` is a category error — that bucket measures source *agreement* while the market gap measures *disagreement*. |
| W04-F001 | Overturned entirely under adversarial review; publishes as refuted with the argument attached (`published: false`). |

---

## Phase B entry state

Dependency order, from the approved plan. **B1 is the roadmap's stated "must land first"** for
the value chain.

- **B0 (verify-only)** — runtime-confirm the 9 P0 closures now that the stack boots. Progress:
  - **W03-F001 VERIFIED CLOSED BY REPRODUCTION** (not by claim). Its own evidence script
    (`evidence/W03/delta_rt.py`) reports **0 field-value mismatches, 0 missing fields, and 0
    `GET /api/data` vs `POST overrides(view=full)` mismatches** over all 1,095 rows. The recorded
    `actual` was 627 rank / 654 tier / 135 value divergences. Fixtures the dead session left
    behind (`full_noop.json`, `delta_noop.json`, `data_full.json`) were regenerated locally.
  - `W20-F002` exits 0 with every team reading "Insufficient evidence" — the fixed state; it
    previously told the #1 roster to sell.
  - `W10-F002` crashes on a missing fixture (`/tmp/dc-auth.json`): a broken repro, not a code
    regression. Needs a repaired reproduction.
- **B4 is CONFIRMED LIVE and larger than recorded** (measured this session, backend up). Posting
  `tep_multiplier: 1.15` — a value **equal to the derived default**
  (`tepMultiplierDefault == tepMultiplierDerived == 1.15`) — diverges from an empty body by
  **130 `rankDerivedValue`, 614 `canonicalConsensusRank`, 666 `canonicalTierId`** across 1,095
  rows, while stamping `isCustomized: false` and `tepMultiplierSource: "override"`.
  That is the ORIGINAL P0's magnitude (135/627/654) still intact on the backend: the P0 was
  closed by making the FRONTEND stop sending the value (`useSettings.js:51` `tepMultiplier: null`),
  not by making the backend treat a derived-equal value as the default. Blast radius is
  board-wide, not TE-only — the top diffs are PICKS (`2026 Pick 1.07` 4738 → 4540), because
  moving TE values reshuffles the global ranking the picks tether to. Fix at
  `data_contract.py:9134-9139`; regression test asserts POST-derived is byte-identical to
  POST `{}`.
- **B1 — W30-F008** (P1, L). `FIT_TOP_N = 400` (`src/model_registry/holdout.py:85`) vs
  `_PERCENTILE_REFERENCE_N = 500` (`src/api/data_contract.py:5368`). The fit maps rank to
  `i/399`, serving maps to `(rank-1)/499`. **This moves board values** — expect wide downstream
  diffs and measure them.

  **Investigated 2026-08-11; the finding understates it.** The recorded OFFENSE numbers
  reproduce exactly (rank 50 +13.2%, 100 +18.5%, 400 +25.4%), but the finding documents only
  that scope, and the mismatch is **per-scope and unequal** because truncation is applied at the
  CALL SITE, not inside `_percentile_pairs`:

  | scope | fit denominator | serve denominator | served-vs-fit error, ranks 25 / 50 / 100 / 200 / 400 |
  |---|---|---|---|
  | OFFENSE | 399 (`values[:400]`, `fit_hill_curve_percentile.py:335`) | 499 | +8.0% / +13.2% / +18.5% / +22.7% / +25.4% |
  | GLOBAL | 399 (`:356`) | 499 | +6.2% / +8.4% / +10.6% / +12.6% / +14.2% |
  | **IDP** | **369** — `_percentile_pairs(idp_values)` at `:370` is **untruncated**, and the IDP slice is only 370 rows | 499 | **+14.0% / +21.7% / +28.8% / +33.9% / +26.1%** |

  Every scope inflates (serve percentile is smaller than fit percentile, and V(p) decreases in
  p), so this is not a wash — but IDP inflates **roughly double** OFFENSE at depth. The
  user-visible harm is therefore not "all values are high by a constant", which would be
  harmless: it is a **non-uniform, scope-dependent distortion of the value ladder**, so IDP and
  offense rows on the same board are stretched differently. That is a cross-scope comparability
  defect, and it is the same coordinate-system family as **W02-F001** — treat B1 and B2 as one
  root cause with two symptoms, which is why the plan forbids shipping W02-F001's one-line
  scope re-route alone.

  **Fix direction** (chosen; not yet implemented): make the FIT adopt the SERVE coordinate
  system — map row `i` to `i / (_PERCENTILE_REFERENCE_N - 1)` regardless of how many rows train
  the curve. Truncation then limits *which rows train*, not *what percentile they represent*.
  This preserves both documented intents (`_PERCENTILE_REFERENCE_N = 500` "aligns with KTC's
  native pool"; `FIT_TOP_N = 400` exists "so train and holdout RMSE are the same quantity"),
  where changing the serve denominator to 400 would contradict the first, reprice the whole
  board, and still leave IDP mismatched at 369.

  **This repair cannot promote itself.** ADR-008 gates production constants behind
  `scripts/model_registry.py promote` + `apply`, run by a human. So B1 delivers: the fit-side
  coordinate fix, a test asserting fit and serve denominators agree, a refit **challenger** with
  its holdout verdict recorded — and production constants left alone until a human promotes.
  Until then the served error above stands, and must be stated rather than implied fixed.

  **STATUS: COORDINATE REPAIR MERGED. CHALLENGER MEASURED. NOTHING PROMOTED.**

  The fit-side coordinate repair above is **implemented and merged**:
  `src/canonical/player_valuation.py` now owns `PERCENTILE_REFERENCE_N`, `rank_to_percentile`
  and `training_percentiles`, and the fitter, `src/model_registry/holdout.py` and
  `src/api/data_contract.py` all consume it instead of computing their own. The three
  denominators in the table above are gone; `tests/canonical/test_percentile_coordinate_contract.py`
  (31 tests) fails if any of them comes back.

  **Production constants are UNCHANGED and still equal registry v2.** The served error in the
  table above therefore still stands on the live board. That is deliberate: ADR-008 gates
  constants behind a human `promote` + `apply`, and the evidence does not support one yet.

  Evidence, in order:

  | file | what it establishes |
  |---|---|
  | `evidence/W30/b1_denominator_measure.py` | pins and hashes every fit input incl. the board snapshot; holdout/fit overlap verified CLEAN |
  | `evidence/W30/B1_CHALLENGER_EVIDENCE.md` | the challenger, its constants, its OFFENSE holdout (+42.2%, unanimous), and the board impact (762/787 rows reorder) |
  | `evidence/W30/b1_1_model_set_measure.py` + `B1_1_MODEL_SET_EVIDENCE.md` | B1.1 — the questions B1 left open |

  **Verdict after B1.1: MORE EVIDENCE REQUIRED.** Do not promote. The five things a later
  session should not re-derive:

  1. The coordinate is now CONSISTENT. What remains is **coverage**, and for GLOBAL/OFFENSE it
     is self-inflicted: they stop at p = 0.7996 because `FIT_TOP_N = 400`, while KTC publishes
     500 rows and IDPTradeCalc 900. IDP's 26% blind tail is the only real one.
  2. The **p = 1.0 clamp is a live IDP defect** independent of any promotion: 877 of 7,130
     served observations (12.3%) share one percentile, touching 487 of 1,095 board rows —
     63.8% of `draftSharksIdp`, 58.2% of `idpShow`, 44.4% of `idpTradeCalc`, and **zero** for
     every non-IDP source. `OVERALL_RANK_LIMIT = 800` publishes 300 ranks deeper than the
     coordinate can distinguish.
  3. **Unanimity and mean disagree.** Every holdout board improves only for c ∈ [0.068, 0.108];
     below that the three deep boards keep improving while PFKDynasty reverses. The challenger
     (c = 0.0770) is inside the band but **not at its optimum** — c ≈ 0.068 is unanimous and
     scores 579.69 against 671.21. Chasing the mean optimum (c ≈ 0.052, 488.77) buys it by
     giving up unanimity.
  4. **The IDP master is internally incoherent** — its two sources disagree by ~6× at rank 400,
     and the shallower one (146 rows, top 29%) votes equally. No setting of this evidence
     justifies promoting it.
  5. **Promoting OFFENSE alone churns MORE, not less** (788/799 rows, mean |shift| 63.5, vs
     762/787 and 51.9 for all three). The intuitive "promote only what is validated" fallback
     is the higher-disruption option.

  Two pre-existing gaps recorded but **not fixed** (the execution order stopped at evidence):

  * the weekly refit does not pin its snapshot — `RISKIT_FIT_SNAPSHOT` appears nowhere under
    `.github/`, so `_latest_snapshot()` picks by mtime and the IDP and ROOKIE scopes train on an
    unrecorded input;
  * the registry pins 6 inputs for a model set with ≥ 10, scores one scope while promoting four,
    and leaves `measuredAt` null on every version and `appliedAt` null on a champion that IS
    applied. The v1 → v2 promotion already moved GLOBAL and IDP with zero out-of-sample
    evidence.

  **B1.2 (2026-08-11) superseded one B1.1 conclusion and hardened governance.** Full evidence:
  `evidence/W30/B1_2_COORDINATE_TAIL_GOVERNANCE_EVIDENCE.md`.

  * **Reference N is a UNIT, not a model.** `V` depends on rank only through `M = c·(N−1)` and
    `s`, so refitting under a different N rescales `c` and leaves the curve alone. B1.1's
    "N=800 scores 502 and recovers the holdout optimum" was a units error — it passed an N=800
    `c` to an evaluator that scores at N=500. Corrected, coordinate-equivalent candidates score
    664.81 / 671.21 / 669.64 (0.96% spread) against 933.19 / 671.21 / 502.12 (85.8%) before.
    **That B1.1 claim is withdrawn.** Compare `rankSpaceMidpoint`, never `c`.
  * **The clamp is the substantive tail choice**, and "declare a bigger N" is provably just
    "extrapolate, but stop at N₂" — continuous-at-500 and transformed-N=800 agree to
    max |diff| **0.0** through rank 800. A pure tail change moves ranks 1..500 by 0.0.
  * **`.068` is holdout-SELECTED, not validated** — the four boards that chose it are no longer
    an untouched set for it. No second validation layer exists, and no time split is possible:
    **0 of 140 archives contain any holdout board.** Archiving those four CSVs is the only route
    to validating anything selected against the current holdout.
  * **`FIT_TOP_N`**: OFFENSE `M` does not move at all from 400→500; GLOBAL moves +6.74% and
    saturates by 800; IDP has no ranks 401+ to add. Not what limits IDP.
  * **Governance**: five repairs, one actively destructive — see the invariant below and
    `W30-F024`. Scope-specific promotion gate added (`src/model_registry/scope_validation.py`):
    a changed routed scope now needs its own evidence or a recorded owner override.
  * **Unanimity NOT codified.** ADR-008's Decision specifies a mean criterion and a 25-point
    margin; the unanimity language is descriptive commentary. Owner decision, not invented here.

  Owner directive 2026-08-11 still stands for everything beyond this: no `promote` / `apply`, no
  production constant change, no B2/B3, no competitive-expansion implementation.

  **Inputs are pinned** (`docs/master-site-audit/evidence/W30/b1_denominator_measure.py`), and
  that is not ceremony: between the Phase A branch point and 2026-08-11, `main` took 5 automated
  refresh commits that rewrote 6 of the fit's own CSVs. Any challenger-vs-champion comparison
  spanning that movement would confound model code with scraper data. The script hashes every
  fit source, holdout source and model file, records commit + dirty state, and asserts the
  holdout does not overlap the fit set (verified CLEAN). Re-run it before and after any B1 change
  and compare snapshots, or the numbers mean nothing.
- **B2 — W02-F001**: re-derivation, NOT the registry's one-line scope re-route, which its own
  verifier refuted. Never ship the re-route alone (`REPAIR_ROADMAP.md:1492`).
- **B3** — re-measure Hampel anchor ejection (W02-F002) and corridor-clamp binding (W02-F003)
  **on the post-B2 board** before changing either.
- Then B4 (TEP residual), B5 (W06 identity batch), B6/B7 (league config + realized points —
  W18-F003 has an NFL-week-1 deadline), B8 (security chain, incl. owner-decided draft-capital
  redaction), B10 (W12-F008 circularity), B11 (confidence), B9 (value-scale semantics — **hard
  prerequisite for C1**).

### Blocked / deferred

| item | blocker |
|---|---|
| 338 safe reproduction adjudications | Not run. Needs the stack (now up) + manual stdout-vs-`expected` comparison per repro; the harness cannot judge. 3 sampled so far. |
| 77 unsafe reproductions | Need the hand-checked worklist `REPAIR_PROTOCOL.md` calls for; they POST/write. |
| 35 repros + `tools/trace_asset.py` | Hardcode `/tmp/claude-0/…/0f0078ff-…/scratchpad/e2e_secret.txt` from a dead session. Directory recreated this session; the secret still needs minting per boot. |
| W31-F001 real repair | Touches `server.py` — claimed by the live `claude/bridge-timeout-root-cause` session. |
| E2E flake root cause (G1b) | Requires independent reproduction; #762's file set is claimed. G1a diagnostics can move earlier once the claim clears. |
| Prod-only data | `data/rank_history.jsonl` accrual, board-snapshot timer, sharp platform ledger, `data/bdvm/`, `data/intel/` — invisible from this container. 9 findings stay BLOCKED, never "passed". |
| C01–C43 / U01–U06 trackers | Live and CI-enforced (`scripts/audit_status.py`), still unmapped to W-ids. |
| Multi-team trade E2E coverage | **No E2E spec exercises a 3+-team trade** — `journey-trade.spec.js` and the mobile specs are two-team only, which is why the crash above survived. Closing it is E2E-track work, not a hotfix. |
| Mobile/WebKit verification | WebKit is not installable here (`/opt/pw-browsers` is Chromium-only; `mobile-390`/`mobile-430` are local-only projects CI never runs). The trade crash was verified RED→GREEN in Chromium at the mobile viewport; the owner's exact browser path stays **unverified, not claimed**. |
| Refit snapshot pinning | `RISKIT_FIT_SNAPSHOT` unset in `.github/workflows/refit-hill-curves.yml`. One-line fix, deliberately not made — the execution order stopped at evidence. |
| Model registry provenance | 6 of ≥10 inputs pinned; one scope scored while four are promoted; `measuredAt` null everywhere; `appliedAt` null on an applied champion. |

### Off-limits file set (live `claude/bridge-timeout-root-cause` session)

`server.py`, `src/api/sleeper_overlay.py`, `frontend/app/api/{auth/status,dynasty-data,health,rankings/overrides}/route.js`,
`tests/e2e/helpers/journey.js`, `tests/api/test_sleeper_overlay_concurrency.py`,
`docs/performance-optimization.md`. Phase A modified **none** of them (verified by set
intersection).
