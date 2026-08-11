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
| HEAD | `89404f2ff` (8 commits ahead of `origin/main` @ `4ac9b22`) |
| PR | [#776](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/776) — Validate PR **green** |
| Working tree | clean |
| Phase | A complete → **B starting** |

### Measured gates at this HEAD

| gate | result |
|---|---|
| `pytest tests/ -q` | 7,001 passed / 0 failed / 25 skipped / 633 subtests (measured at `4ac9b22` pre-repair; re-run in flight at this HEAD) |
| `vitest run` (frontend) | 120 files / 2,004 tests / 0 failed |
| `ruff format --check .` | 991 files already formatted |
| `ruff check .` | All checks passed |
| `scripts/check_decision_coercions.py` | clean — no new coercions, no stale allowances |
| `scripts/audit_status.py` | no drift (C-tracker: 21 closed / 19 open / 2 needs_review / 1 deferred) |
| `npm --prefix frontend run build` | compiled; **all 14 route bundle budgets under** |
| Stack bring-up | `/api/status` `has_data: true`, 1,095 players, scrape suppressed |

Environment: python 3.11.15 in `.venv` (`scripts/setup.sh`), node 22.22.2, vitest 4.1.10.
The clone must be **unshallowed** (`git fetch --unshallow`) or every git-derived audit signal lies.

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
| Schedule generator | — | **does not exist; D7 build** |
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
  `i/399`, serving maps to `(rank-1)/499`, so under the champion OFFENSE constants (c=0.11,
  s=1.11) rank 50 serves 13.2% high, rank 100 18.5%, rank 400 25.4%. **This moves board values** —
  expect wide downstream diffs and measure them.
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
