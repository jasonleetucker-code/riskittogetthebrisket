# CW-50 — waiver / streaming recommendation verification, 2026-11-07

Owner directive 2026-11-07 (sitewide feature verification, Parts 2–5): *"A waiver
recommendation must respect the actual eligible players, available FAAB, roster
capacity, dynasty protection rules, and NO TRANSACTION alternative."* This record
checks every waiver/streaming recommendation surface against that sentence and its
latest controlling requirements, using hand-built leagues whose expected answers are
written by hand (no production function produces an expectation).

Builds on CW-10 (`docs/waivers/FAAB_INTEGRITY_VERIFICATION_2026-11-06.md`, the FAAB
engine's own invariants), which this does not repeat.

Tests: `tests/trade/test_cw50_waiver_workflow.py` (engine level, 16),
`tests/api/test_cw50_waiver_desk.py` (HTTP level, 18),
`frontend/__tests__/components/FaabDeskRefusal.test.jsx` (5).

## Controlling requirements

| Concern | Controlling record (clause) |
|---|---|
| eligible players | Owner directive 2026-11-07; `CLAUDE.md` "Fields that follow leagueKey" (IDP display toggle per league `idpEnabled`); `frontend/lib/waiver-logic.js::buildCandidatePool` (IDP gated on `idpEnabled`); `src/ros/lineup.py` (one owner of slot eligibility) |
| available FAAB | `CLAUDE.md` "FAAB recommendations": recommended bid capped at the balance, objective ceiling separate; `docs/faab-model.md`; CW-10 W10-F001 |
| roster capacity | `CLAUDE.md` "Roster capacity and forced drops — one owner" (unknown cap is UNKNOWN, forced drops carry their value, reports never rejects); owner decision 2026-10-21 `forced_drop_cheapest_legal` held OFF (report, never apply) |
| protection | `src/trade/constraints.py` (C3-CON-01/02); inventory rows 1.5 / 2.10 / 2.11; `ODR-SR-UNPRICED` "unpriced assets in drop logic: never a free drop" |
| NO TRANSACTION | `docs/OWNER_PRODUCT_BACKLOG_SPEC.md` §IST (line 822, "explicit NO TRANSACTION"); `ODR-STREAMING-BUDGET` ("NO TRANSACTION valid"); Perfect Waivers stop rule (inventory 3.3) |
| missing ≠ 0 | `CLAUDE.md` governance invariant; `ODR-SR-UNPRICED` |
| league scoping | `CLAUDE.md` "League-aware routing" (400 `unknown_league`, 503 `data_not_ready`) |

The requirements are **silent** on whether the per-pair desk should refuse or warn for
a rostered add, and on whether an unknown own balance should withhold the list bids
(Perfect Waivers / streaming) or assume the full budget (list) — see owner questions.

## Surface table

| Surface | Live path | Flag | State |
|---|---|---|---|
| Waiver suggestions list | `POST /api/waiver/suggestions` → `src/trade/waiver.py::find_waiver_targets` → `faab_engine` | always on | **DEFECTIVE → repaired** (D1, D2) |
| Per-pair bid desk | `POST /api/waiver/faab-recommend` → `faab_recommender.recommend_faab` → `faab_engine` | always on | **DEFECTIVE → repaired** (D3–D6) |
| Perfect Waivers | `POST /api/waiver/perfect` → `perfect_waivers.build_perfect_waivers` | always on | **DEFECTIVE → repaired** (D1 via the shared pool, D7); capacity, protection, unpriced-never-dropped, NO TRANSACTION (empty plan) VERIFIED_AGAINST_INTENT |
| Waiver Advisor | `POST /api/waiver/advisor` → `src/waivers/advisor.py` (composes the pool + Perfect Waivers + `roster_capacity`) | `waiver_advisor` ON | VERIFIED_AGAINST_INTENT by composition (inherits D1/D2 repairs); forced drop reported-not-applied, existing tests |
| Weekly IDP streaming | `POST /api/waiver/streaming` → `src/waivers/streaming.py` + `streaming_solver` + `drop_assessment` | `waiver_advisor` + `idp_streaming` ON | VERIFIED_AGAINST_INTENT (existing owner-scenario suite: "no move" below materiality, protected/conditional/churn, unknown balance → $0 claims only, unknown cap → no open spot); inherits D1 |
| /waivers claim desk page | `frontend/app/waivers/page.jsx` + `lib/waiver-logic.js` + `useWaiverAnalysis` | always on | VERIFIED_AGAINST_INTENT (IDP gated on `idpEnabled`, drops only from the canonical cut ladder, two-source floor); desk refusal rendering repaired (D8) |
| Best available IDP card | `POST /api/waiver/best-available-idp` → `waiver_idp_best_available.py` | always on | INCOMPLETE (minor): backend serves the card for any league; only the UI gates it on `idpEnabled` |
| Public waiver compare | `GET /api/public/waiver-compare` → `src/waiver_compare` | always on | out of scope — a valued roster/availability view for `dynasty_main`, not a recommendation |

## Defects found and repaired

Each was reproduced first: the new tests run against `origin/main` (2b225e6) fail 23
of 33 written at the time (the 10 that pass on main are the verified-as-intended
behaviours: Perfect Waivers capacity / protection / NO TRANSACTION, league scoping).

| # | Defect | Root cause | Repair (canonical owner) |
|---|---|---|---|
| D1 | The backend add pool offered defenders (and any position) to a league whose lineup cannot start them. Reached Perfect Waivers / Advisor / list | `find_waiver_targets` offered a fixed position set; only the page gated IDP | `waiver_candidate_exclusion` refuses `position_not_started` when the league's slots are known, decided by the new `lineup.player_fills_any_slot` (the solver's own predicate, configured flex honoured), slots from `lineup.resolve_starter_slots`. Unknown lineup refuses nothing and is stamped `positionEligibility.state: "unverified"`. Measured on the 2026-11-07 board for `dynasty_main`: 216 candidates gated vs ungated, identical |
| D2 | A stale client balance lifted the bid cap above the live roster's balance: a $50 request against an observed $10 quoted a **$49** bid. Unknown balance was silently capped at the full budget, unlabelled | the request balance took precedence over the observed one | the lower of the two caps; folded into the ONE published balance state, `faabBudget` (#2138): `balance` is the spendable balance (never below $0), `source` names which observation bound it, `requestedBalance` / `observedBalance` carry the raw figures. The unknown half was fixed by #2138 (bids withheld on `/suggestions`) and is not duplicated here |
| D3 | Desk priced an add the board does not price at $0 (`rankDerivedValue or 0`) | coercion | 422 `add_player_unpriced`; no figure |
| D4 | Desk charged a named drop that was unpriced or not on the board nothing, and said "replacement level — free" (violates `ODR-SR-UNPRICED`) | coercion | 422 `drop_player_unpriced` with `dropValueState`; `resolvedDropValue` is `null` (not `0.0`) when no drop is named, `dropValueState` beside it |
| D5 | Desk quoted a bid for a player already on a roster in the league (another team's, or the requester's own) | no availability check | 409 `add_player_not_available` (`rosteredBy`, `onYourRoster`, `matchedBy` — Sleeper id first, name only for a roster without ids) |
| D6 | Desk never consulted roster capacity: a claim on a full roster read as a free add, with no forced release named | `roster_capacity` not consumed | `rosterCapacity` = `RosterCapacity.to_dict()` + `application: "reported_not_applied"`, and a warning naming the forced release(s) with value; unknown cap warns. **No figure moves** (pinned) — forced-drop selection is owner-held OFF. Scarcity is read warm-only (`gameplan.last_built_league_bundle`, the /trade simulate posture): the cold bundle solve measured 4.4–6.2 s on the 2026-11-07 board, then 15–21 ms per team |
| D7 | Perfect Waivers labelled an over-spent (negative) balance "unknown" | `>= 0` guard | a known balance clamped at $0 |
| D8 | The desk panel printed refusals as a raw `API 4xx: {...}` under "FAAB recommender unavailable" | — | `deskRefusal` renders the backend sentence under "No bid for this claim" |

Coercion baseline: the two removed `server.py` `or 0` entries are deleted from
`config/coercion_baseline.json` (on the reconciled tree 620 → 618).

Two existing tests were updated, neither weakened: the empty-board shape test in
`tests/trade/test_waiver.py` now pins `faabBudget` / `positionEligibility` exactly, and
`test_waiver_pool_filters_are_disclosed_by_reason` gains a FLEX so its WRs stay startable
(its value / source / kicker / unpriced reasons stay under test); the new
`test_unstartable_position_is_disclosed_by_reason` pins `position_not_started` on the
original QB/TE lineup.

Regression runs (local, `-m "not livedata"`): `tests/trade tests/waivers tests/lineup
tests/roster_intel` 11,087 passed + the 2 updated tests green on re-run; `tests/ros
tests/draft` + the waiver/FAAB/capacity/lineup/gameplan/draft slice of `tests/api` 1,470
passed; waiver/FAAB vitest suites 250 passed.

## Owner questions (methodology — not changed here)

1. ~~Unknown own balance on the list~~ — answered by #2138 (merged): `/api/waiver/suggestions`
   withholds balance-capped bids and states `faabBudget.state: "unknown"`.
2. **Full roster with no drop chosen at the desk.** The desk now names the forced
   release but still prices the claim as if no drop were needed. Should the desk charge
   the forced release's cost (the cheapest legal rung) once
   `forced_drop_cheapest_legal` is decided?

## Reconciled with #2138 (2026-11-07)

#2138 (merged first) verified the same workflow through the routes and fixed two of the
same defects. On reconciliation: `faabBudget` is the only balance-state field
(`faabBalance` folded in, never shipped beside it); #2138's id-first rostered check in
`find_waiver_targets` and its unknown-balance withholding are kept as the implementation,
#2136's duplicates dropped. Two #2138 property tests changed because they encoded the
opposite of D1 / D7: the eligible-set test's fixture lineup gains a FLEX (its QB/TE
lineup starts no WR/RB, so D1 would refuse them before the filters the test pins), and
the over-spent test now expects a known $0 balance.

## Gaps and limitations

- Route-level only for `/advisor` and `/streaming` through their existing suites; the
  new tests exercise their shared owners (`find_waiver_targets`, `build_perfect_waivers`).
- The desk resolves add/drop rows by display name (pre-existing); a same-name collision
  between two board players is not resolved by id there.
- The suggestions list and the desk's rivals still read name-keyed rosters
  (`rostered_name_set`), as documented in `waiver.py`.
- No production observation: not deployed by this change.
