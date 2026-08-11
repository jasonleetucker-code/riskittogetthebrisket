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
| Phase | **A FORMALLY CLOSED 2026-08-11.** B is NOT started — owner gate below. |

> **Why these fields and not "current HEAD".** A Markdown file committed at one
> SHA cannot literally contain that SHA, so a field claiming to be "the commit
> containing this document" is stale the instant it is written, and inviting a
> reader to trust it is worse than omitting it. What a reader actually needs is
> *which tree was tested*, *what it was tested against*, and *what has moved
> since* — which is what the rows above state separately.

### Measured gates at this HEAD

| gate | result |
|---|---|
| `pytest tests/ -q` | **7,038 passed / 0 failed** / 25 skipped / 633 subtests (1533s) — quiescent tree at `0dc0a7778`. Trail: 7,001 at `4ac9b22` → 7,008 at `efa18f0e6` (+7 closure-harness) → 7,026 (+18 when those were rewritten to drive real production logic) → 7,038 (+12 B1 pin-coverage guard). Every delta is accounted for by new tests; no existing test changed state. |
| `vitest run` (frontend) | **2,007 passed / 0 failed**, 120 files — was 2,004; +3 from the FAAB missing-vs-zero cases |
| `ruff format --check .` | 991 files already formatted |
| `ruff check .` | All checks passed |
| `scripts/check_decision_coercions.py` | clean — no new coercions, no stale allowances |
| `scripts/audit_status.py` | no drift (C-tracker: 21 closed / 19 open / 2 needs_review / 1 deferred) |
| `npm --prefix frontend run build` | compiled; **all 14 route bundle budgets under** |
| Stack bring-up | `/api/status` `has_data: true`, 1,095 players, scrape suppressed |

Environment: python 3.11.15 in `.venv` (`scripts/setup.sh`), node 22.22.2, vitest 4.1.10.
The clone must be **unshallowed** (`git fetch --unshallow`) or every git-derived audit signal lies.

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
6. **Tools must not destroy the evidence they maintain.** Two instances found and fixed this
   session (see below). Assume a third exists.
7. **A claim is not a measurement.** Reproduction settles closure. `Closes W##-F###` in a commit
   is a claim; the audit harness now labels reruns honestly rather than calling them closed.
8. **One root cause per commit**, red-before-green, full suites only on a quiescent tree.

---

## Canonical owners (as of this handoff)

| concept | canonical owner | status |
|---|---|---|
| Live player value | `src/api/data_contract.py::_compute_unified_rankings` | established |
| Hill curves / percentile→value | `src/canonical/player_valuation.py` | **denominator defect open — B1** |
| Player identity | `src/identity/` + `unified_mapper` | defects open (W06 batch — B5) |
| League registry / scoring | `src/api/league_registry.py`, `src/league_intel/config.py` | profile identity defect open (W18-F001 — B6) |
| Trade asset eligibility | `frontend/lib/trade-logic.js::isTradeableBoardRow` | **established this session** |
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

  **STATUS: INVESTIGATION ONLY — NO IMPLEMENTATION HAS BEGUN.** Owner directive 2026-08-11: do
  not start B1 (or any later) source implementation until explicitly authorized, and do not run
  or authorize `promote` / `apply`, change production model constants, or promote a challenger
  without first presenting holdout/backtest evidence, expected board impact, risks and the exact
  proposed change for approval. Zero production source files have been modified for B1.

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

### Off-limits file set (live `claude/bridge-timeout-root-cause` session)

`server.py`, `src/api/sleeper_overlay.py`, `frontend/app/api/{auth/status,dynasty-data,health,rankings/overrides}/route.js`,
`tests/e2e/helpers/journey.js`, `tests/api/test_sleeper_overlay_concurrency.py`,
`docs/performance-optimization.md`. Phase A modified **none** of them (verified by set
intersection).
