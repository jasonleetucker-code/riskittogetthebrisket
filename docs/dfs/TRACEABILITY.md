# DFS — requirement traceability (zero-loss map)

Every requirement in the 2026-09-30 owner mandate has a stable ID `DFS-§<section>-<n>`. Status
vocabulary: **SLICE1** (implemented + tested on `claude/dfs-foundation`, PR #1534, not yet deployed),
**SLICE2** (contests slice, `claude/dfs-contests`, stacked on #1534, not yet deployed),
**PARTIAL**, **NOW**, **NEXT**, **LATER**, **BLOCKED(<reason>)**. Phases refer to
[`ROADMAP.md`](ROADMAP.md). A row leaves this table only by supersession, never deletion.

| ID | Requirement (compressed) | Phase | Status | Evidence / next action |
|---|---|---|---|---|
| DFS-§1-01 | Audit repo, reuse owners, no parallel engines | P0 | SLICE1 | No prior DFS code existed (only `DFS_PROJECTION` census label). Reused auth gate, feature flags, `name_clean`, DS primitives, nav model |
| DFS-§1-02 | Register mandate in canonical execution system | P0 | SLICE1 | `EXECUTION_PLAN.md` §0, `OWNER_REQUESTED_TODO.md`, `WORK_CLAIMS.md`, UI ledger |
| DFS-§1-03 | DFS data never enters dynasty valuation | P0 | SLICE1 | `tests/dfs/test_rules_and_imports.py::test_dfs_never_imports_dynasty_valuation_owners` |
| DFS-§1-04 | Missing ≠ zero; unresolved identity ≠ guess | P1 | SLICE1 | Unprojected excluded + reported; ambiguous/conflicting rows quarantined |
| DFS-§1-05 | Private decisions behind real access control | P1 | SLICE1 | `_private_api_gate` + per-owner scoping; cross-user 404 test |
| DFS-§1-06 | No purchases / wagering / entry / account automation | all | SLICE1 | Export only; `submitted: false`; no platform write path exists |
| DFS-§2-01 | Keep forecasts, field, generation, payouts, portfolio, research, entries distinct | P0 | PARTIAL | Module boundaries set (`rules/imports/optimizer/export/store`); field/payout/portfolio owners not built |
| DFS-§2-02 | Honest "insufficient / unavailable / infeasible / projection-only / stale" states | P1 | SLICE1 | Readiness levels, `CAPABILITY_UNAVAILABLE`, `projection_only`, conflict reports. Stale-build review → DFS-§11 |
| DFS-§3-01 | Competitive research with evidence levels + adoption matrix | P0/P3 | NEXT | Protocol in `SOURCES.md` §4; no product observed hands-on yet |
| DFS-§4-01 | DFS in canonical nav, `/dfs` route, auth, mobile parity | P1 | SLICE1 | Nav group "DFS"; canon + reachability tests |
| DFS-§4-02 | Eight workspace areas sharing one context | P1–P6 | PARTIAL | Overview+Optimizer+Lineups+Contests on `/dfs` (Contest panel keyed by platform×sport×format — SLICE2); Live/Research/Results/Sources pending |
| DFS-§4-03 | Persistent context selector (sport/platform/format/…); per-format settings | P1 | PARTIAL | Sport/platform/format persisted per viewer; date/slate/contest/objective/build version pending |
| DFS-§5-01 | Capability gating per platform × sport × format × rule version | P1 | SLICE1 | `capability_matrix()`; `RULESET_SUPERSEDED` on version drift |
| DFS-§5-02 | Verified rule sets with official evidence; fail closed for money mode | P1 | BLOCKED(official pages refused automated access) | `RULESET_UNVERIFIED` enforced; owner verification needed |
| DFS-§5-03 | Showdown / single-game / captain / MVP | A | PARTIAL (SLICE4) | DK NFL Showdown Captain encoded UNVERIFIED: row-label eligibility (`platform_slots`), one athlete = CPT row + FLEX row (group identity; never both rostered), captain 1.5x applied once at the slot and shown explicitly, stored projection untouched, brute-force parity. FanDuel single-game MVP and other sports' showdown still NEXT (layouts unverified) |
| DFS-§5-04 | NBA, NHL, MMA rule sets | A | PARTIAL (SLICE4, `claude/dfs-multisport`) | DK + FD NBA and NHL classic encoded as UNVERIFIED research-mode rule sets (solver exact vs brute force on all four, non-vacuity guarded; platform-file roster slots cross-checked on import). MMA still NEXT (no roster rules encoded; files are recognised) |
| DFS-§5-05 | Contest import/editor, payout ladder validation, rake, overlays, hypothetical profiles | P2 | SLICE2 (manual + pasted ladder) | `src/dfs/contests.py`: separate dimensions, integer cents, overlap/capacity errors, gap/inversion review flags (never rewritten), rake vs overlay vs underfill vs unknown, hypothetical suppresses exact EV; versioned per-owner storage. Platform/provider contest import still NEXT |
| DFS-§5-06 | Scoring contracts (weights, bonuses, rounding) versioned | P2 | NEXT | Needed before own-model projections (P3/P4) |
| DFS-§6-01 | "Optimal Lineup" one-click with validate → snapshot → solve → explain → save | P1 | SLICE1 (baseline objective) | Button runs the projection baseline explicitly; result names objective, status, snapshot hash, solver |
| DFS-§6-02 | Cash/GPP contest-aware objectives | P5 | BLOCKED(needs P4 field + payout models) | `contest_ev` returns 409, never substituted |
| DFS-§6-03 | Versioned strategy presets (H2H…150-max) | P5 | PARTIAL (SLICE2) | `config/dfs/presets.json`: 11 presets with objective + required models, all `unsupported` until P4 models exist; cash and GPP objectives are distinct by test |
| DFS-§6-04 | Explicit "Highest Projected Points" baseline | P1 | SLICE1 | `objective: projection_baseline` |
| DFS-§6-05 | Solver status vocabulary + provenance (hashes, seed, budget) | P1 | SLICE1 | `optimal/partial/timed_out_with_feasible_result/infeasible/timed_out/unavailable`; hashes stored |
| DFS-§6-06 | Lineup explanation + "why not this player?" | P3 | PARTIAL | Pts/$1K, salary left, team counts; constrained-alternative comparison pending |
| DFS-§6-07 | News invalidation marks old builds for review | P3 | LATER | Needs DFS-§11 event graph |
| DFS-§7-01 | Build exactly N or explicit shortfall | P1 | SLICE1 | `test_exactly_n_unique_lineups_or_explicit_shortfall` |
| DFS-§7-02 | Scoring vs assignment identity | P1 | SLICE1 | `scoringIdentity` / `assignmentIdentity` |
| DFS-§7-03 | Recommended entry count (budget, caps, marginal value, zero allowed) | P5 | PARTIAL (SLICE2) | Hard upper bound implemented (min of allowance, open capacity, explicit spend limit; free/ticket handled; zero allowed; budget never inferred). The recommendation itself stays BLOCKED on contest EV |
| DFS-§8-01 | Locks, excludes, salary min/max, team max | P1 | SLICE1 | Tests |
| DFS-§8-02 | Groups (at least/at most K) | C | SLICE4 | API (SLICE1) + keyboard-native rule builder on /dfs (at least / at most / exactly N) |
| DFS-§8-03 | Conditional rules (if-A-then-B), mutually exclusive groups | C | SLICE4 | if A then B / not B / at least N of group B: MILP big-M rows + independent validator + conflict isolation (`cond:i`), brute-force exact and proven to bind; mutually-exclusive = at most 1 of group |
| DFS-§8-04 | Stacks: primary/secondary, bring-back | P1 | SLICE1 (QB stack) | Portfolio stack distributions pending |
| DFS-§8-05 | Sport-specific stacks (NBA/NHL/MMA) | P2 | NEXT | |
| DFS-§8-06 | Exposure semantics + integer rounding shown | P1 | SLICE1 (max, floor) | Min exposure + scoped exposure pending (needs joint portfolio) |
| DFS-§8-07 | Minimal conflicting subset, no hidden relaxation | P1 | SLICE1 | Deletion filter over owner items |
| DFS-§8-08 | Editable forecasts vs preference boosts kept separate | C | SLICE4 | `projectionOverrides` = owner forecast (used in objective AND totals, marked 'yours', never written back, can supply a missing forecast); `boosts` = selection preference (objective only; reported totals stay unboosted). Both tested non-vacuously; per-row inputs on /dfs |
| DFS-§8-09 | Bulk edit, undo/redo, presets, scenario copies, diff | P2 | NEXT | |
| DFS-§8-10 | Natural-language control compiled to schema with preview | P5 | LATER | |
| DFS-§9-01 | Typed versioned entities (Source… AuditEvent) | P0–P7 | PARTIAL | Slate/athlete/ruleset/snapshot/build exist; rest per phase |
| DFS-§9-02 | Observation timestamps (event/publish/first-seen/retrieved/usable) | P3 | NEXT | Import time only today |
| DFS-§9-03 | Canonical athlete identity across providers | P3 | NEXT | Must extend `src/identity/`, not a DFS-local owner |
| DFS-§9-04 | Source-family independence / lineage | P3 | NEXT | Schema fields reserved in `source_seeds.json` |
| DFS-§10-01 | Register every supplied source/podcast with disposition | P0 | SLICE1 (registered) | 109 seeds, all `unverified` |
| DFS-§10-02 | Resolve identities, access, license, cost per source | P3 | NEXT | Time-boxed research batches |
| DFS-§10-03 | Connector framework (quotas, backoff, circuit breakers, quarantine) | P3 | NEXT | |
| DFS-§10-04 | No paywall/CAPTCHA/bot evasion; no billable trials without approval | all | SLICE1 | Honoured: 403s recorded as blockers, not bypassed |
| DFS-§11-01 | Event-driven freshness, dependency graph, rebuild recommendations | P3 | NEXT | Requires background jobs (DFS-§21-02) |
| DFS-§12-01 | Projection ensemble with held-out weights, horizons, selection-bias checks | P3/P4 | LATER | Owner imports only today |
| DFS-§13-01 | NFL outcome model | P4 | LATER | |
| DFS-§13-02 | NBA minutes/rotation model | P4 | LATER | |
| DFS-§13-03 | NHL line/PP/goalie model | P4 | LATER | |
| DFS-§13-04 | MMA joint fight model | P4 | LATER | |
| DFS-§14-01 | Sportsbook/prop intelligence, de-vig, consensus | P3/P4 | BLOCKED(licensed odds feed not identified) | |
| DFS-§15-01 | Podcast discovery → transcripts → claims → controlled use | D | PARTIAL (SLICE4 claim core) | `src/dfs/evidence.py`: schema + policy every extractor must pass — conditional inactive until resolved, preference/popularity cannot carry numbers, intervals are attributed ranges, post-lock/retrospective/promotion excluded, independence counted by primary source, retraction/supersession without deletion, no look-ahead, injection-inert; model use capped at shadow. Feed discovery research in progress; acquisition/transcription NEXT |
| DFS-§16-01 | Ownership / field / duplication models | P4 | LATER | |
| DFS-§17-01 | Deterministic MILP baseline with exact small-case agreement | P1 | SLICE1 | Brute-force parity tests (DK + FD rules) |
| DFS-§17-02 | Joint outcome simulation, exact payout/ties ($1,000/$100 → $550) | P4 | PARTIAL (SLICE2) | Exact rank payout + split-position ties in integer cents, fractional cents reported exactly, unknown tie rule → unavailable ($550 fixture green). Joint simulation still LATER |
| DFS-§18-01 | Joint portfolio selection + multi-contest allocation | P5 | LATER | |
| DFS-§19-01 | Salary / projection / template imports with mapping preview | P1 | PARTIAL | Import report today; interactive column mapping pending |
| DFS-§19-02 | Exports preserving IDs/headers/slots; round-trip vs official templates | P1 | BLOCKED(no official template fixture) | Re-validated at export; labelled unverified |
| DFS-§19-03 | Entry lifecycle (draft → submitted → settled) | P6 | LATER | `submitted: false` only |
| DFS-§19-04 | Late swap with locked slot immutability | P6 | LATER | |
| DFS-§20-01 | Live / rooting view | P6 | LATER | |
| DFS-§20-02 | Settlement reconciliation, calibration, replay, champion/challenger | P7 | LATER | |
| DFS-§21-01 | Typed APIs + structured error codes | P1 | SLICE1 | `RULESET_UNVERIFIED`, `INFEASIBLE` (as status), `CAPABILITY_UNAVAILABLE`, `LOCKED_PLAYER_UNPROJECTED`, … |
| DFS-§21-02 | Persistent background jobs (progress/cancel/restart) | P3 | NEXT | Builds are synchronous inside a ≤60 s solver budget today |
| DFS-§21-03 | Developer CLI on the same business logic | P2 | NEXT | |
| DFS-§22-01 | PSI Direction A, DS primitives, tokens only | P1 | SLICE1 | `.psi-editorial`, `components/ds`, no raw colours |
| DFS-§22-02 | Accessibility (keyboard, SR labels, non-colour status) + mobile | P1 | PARTIAL | Component tests; axe/E2E + production screenshots pending |
| DFS-§22-03 | Performance budgets measured | P1 | PARTIAL | `/dfs` skips the dynasty contract prefetch; bundle size + useful-state measurement pending |
| DFS-§23-01 | Auth on every route/job/export; cross-user tests | P1 | SLICE1 | |
| DFS-§23-02 | Untrusted-file defences (size, header, formula-safe IDs) | P1 | SLICE1 | XML/archives/audio N/A until those inputs exist |
| DFS-§23-03 | Spending ceilings, research-only mode, cost dashboard | P5 | PARTIAL | Research mode is the only mode that builds today |
| DFS-§24-xx | Test program items 1–52 | per phase | PARTIAL | Items 3 (captain once), 7 (duplicate names / captain rows), 2, 8, 9, 10, 11, 12, 13, 14, 15, 20, 21 (cash-line tie), 22, 23, 28 (bound), 29, 32, 43(partial), 44, 47, 51, 52 covered |
| DFS-§25-01 | Dependency-aware roadmap linked to Calculator Ideas | P0 | SLICE1 | `ROADMAP.md` |
| DFS-§26-01 | Lane 6 active every batch | all | SLICE1 | `/dfs` UI shipped with the foundation; UI ledger row |
| DFS-§27-01 | Documentation set + user guide | P0 | SLICE1 | This folder |
| DFS-§28-01..14 | Owner acceptance stories | P1–P8 | PARTIAL | Story 1 (partial: honest states for all four sports), 5 (partial), 6, 12 (partial), 13 (partial), 14 |

## Owner addendum 2026-09-30 — Platform / Slate / Contest integration

Additive; nothing above is superseded except the phase ORDER (see `ROADMAP.md`). Status vocabulary
as above; **SLICE3** = Phase A slice on `claude/dfs-contests`; **SLICE4** = NBA/NHL rule sets on `claude/dfs-multisport`.

| ID | Requirement (compressed) | Phase | Status | Evidence / next action |
|---|---|---|---|---|
| DFS-ADD-01 | No production dependency on unofficial DK/FD endpoints, scraping or account automation | all | SLICE1+ (holds) | No such code exists; ADR-DFS-009; official pages' 403s recorded, not bypassed |
| DFS-ADD-02 | Licensed slate feed (SportsDataIO) evaluated; per platform x sport x field capability matrix | A | PARTIAL (SLICE3) | `config/dfs/providers.json` from the published OpenAPI (NFL/NBA/NHL `DfsSlatesByDate`); every cell `documented`, none `verified` — BLOCKED(no key; paid) |
| DFS-ADD-03 | MMA via official/user-downloaded CSV until a licensed source is verified | A | SLICE3 | MMA files detected; roster rules still unencoded, so `UNSUPPORTED_FORMAT` names what was recognised |
| DFS-ADD-04 | First-class platform CSV import: detect platform/sport/format, IDs, names, salaries, eligibility, duplicates, unknown fields, useful errors, no guessing | A | PARTIAL (SLICE1 parse + SLICE3 detection + SLICE4 DK entry files) | DraftKings entry-file import (layout `assumed`; unknown IDs quarantine the entry, never name-matched). FanDuel entry files, late-swap and result files remain NEXT (G/H) |
| DFS-ADD-05 | First-class export: IDs, slot order, locks, entry IDs, validation, duplicates, limits, explicit support | A/C/G | PARTIAL (SLICE1 + SLICE4) | New-lineup export + DraftKings export INTO existing entry IDs (re-validated; unresolved entries never overwritten; surplus lineups/entries reported). Verified only with official templates |
| DFS-ADD-06 | Canonical DFS slate model; providers map into it; downstream never reads provider objects | A | SLICE3 | `src/dfs/slate.py` |
| DFS-ADD-07 | Slate != contest; canonical contest profile tied to a slate | B | PARTIAL (SLICE2 profile, SLICE3 link) | Contest family taxonomy (satellite/qualifier/league) NEXT |
| DFS-ADD-08 | Three contest-creation modes: quick (preset), exact (editor), import | B | PARTIAL (SLICE4: Quick + Exact in UI) | Exact = SLICE2; quick = presets exist (now incl. medium-field GPP, satellite, qualifier, custom — 15 total), UI selection NEXT; import BLOCKED(no verified contest-file layout) |
| DFS-ADD-09 | Payout editor shows totals, implied rake, cash %, first-place and top-1% concentration, curve chart, errors | B | SLICE4 | Top-1% concentration (needs capacity) + exact log-spaced payout curve drawn with the approved Sparkline primitive and a text summary; a full chart waits on the PSI chart decision (#1428) |
| DFS-ADD-10 | Contest-aware objective uses distributions/ownership/duplication/payouts; disclose fallbacks | F | BLOCKED(D+E) | `contest_ev` refuses; fallback disclosed |
| DFS-ADD-11 | Optimal Lineup knows platform/sport/slate/contest/field/payout/limits/model confidence; never silently median-maximizes | F | PARTIAL (SLICE4) | Builds record the contest version / preset they were made for, refuse a contest for another platform or slate, and carry explicit disclosures ("Contest-aware evaluation is unavailable… recorded for provenance only", "<preset> not available yet — built with the projection baseline") |
| DFS-ADD-12 | Fixed-N and recommended-count are separate | C/F | PARTIAL | = DFS-§7-01 (done) / §7-03 (bound done, recommendation blocked) |
| DFS-ADD-13 | Low-friction DFS home: sport -> platform -> slate -> contest -> strategy -> count -> build | A-F | PARTIAL | Context bar + import + contest exist; provider slate status SLICE3 (shows unavailable); strategy/count chips NEXT |
| DFS-ADD-14 | Full expert control incl. min exposure, boosts, projection/ownership overrides, notes/tags, salary-left, if-then groups, sport stacks, auto vs manual mode | C | PARTIAL | = DFS-§8 rows |
| DFS-ADD-15 | Visible freshness per information class | D | PARTIAL (SLICE3 strip) | Salary/projection from the snapshot; odds/ownership/news/podcast shown as unavailable until sources exist |
| DFS-ADD-16 | Sources separated by function; source != signal | D | PARTIAL | `source_seeds.json` categories + independence groups reserved |
| DFS-ADD-17 | Podcast pipeline remains part of the optimizer | D | NEXT | = DFS-§15-01 |
| DFS-ADD-18 | athlete <-> salary <-> game <-> sportsbook market join; market definitions preserved | D | NEXT | Canonical slate carries event IDs for the join |
| DFS-ADD-19 | Exact contest simulation (payout, cash/top-%/first probabilities, duplicates) with provenance | E/F | LATER | Exact payout/tie math already built |
| DFS-ADD-20 | Historical contest result import -> DFS field archive; post-lock data never used pre-lock | H | LATER | |
| DFS-ADD-21 | Result learning loop with champion/challenger | H | LATER | |
| DFS-ADD-22 | Live / rooting view | G | LATER | = DFS-§20-01 |
| DFS-ADD-23 | Source-cost registry; incremental value vs cost; no purchase without approval | D | PARTIAL (SLICE3) | `providers.json` cost fields (price unknown, never invented) |
| DFS-ADD-24 | Source failover; failure never becomes zero projections/ownership/empty salary | A/D | PARTIAL | CSV fallback always available; stale-snapshot policy NEXT |
| DFS-ADD-25 | PSI UI, dense tables, mobile parity for the core workflow | all | PARTIAL | = DFS-§22 rows |
| DFS-ADD-26 | No DFS contamination of dynasty valuation | all | SLICE1 (tested) | AST isolation test |
| DFS-ADD-27 | Roadmap reordered A-H; advanced work preserved | P0 | DONE | `ROADMAP.md` |
| DFS-ADD-28 | Named failure states (provider unavailable, quota, stale, payout incomplete, identity unresolved, unsupported slate/platform/format, CSV malformed/wrong platform, rules unverified, lock passed, export invalid, sim unavailable, no field data) | A-H | PARTIAL | Built: PROVIDER_UNAVAILABLE, SOURCE_PERMISSION_REQUIRED, PAYOUT_INCOMPLETE, identity quarantine, UNSUPPORTED_SLATE/FORMAT, HEADER_MISMATCH, CSV_WRONG_PLATFORM, RULESET_UNVERIFIED, LINEUP_INVALID_AT_EXPORT, CAPABILITY_UNAVAILABLE. Remaining: QUOTA_EXCEEDED (with the feed), STALE_CRITICAL_INPUT, LOCK_PASSED, NO_FIELD_DATA |
| DFS-ADD-29 | Fixtures for DK NFL Classic/Showdown/NBA/NHL/MMA and FD NFL/NBA/NHL/MMA; one true end-to-end fixture before calling the baseline operational | A/C | PARTIAL | Synthetic DK/FD NFL fixtures + e2e API test (import -> build -> export); synthetic detection fixtures for the rest (SLICE3). Real-template fixtures BLOCKED on the owner |
| DFS-ADD-30 | Owner core workflow (NFL DK Sunday Main -> exact contest -> 20-lineup optimal portfolio -> export) | P8 | LATER | Depends on A (feed or CSV) + B + D-F |
| DFS-ADD-31 | Continue from current state; concise update | P0 | DONE | This record |
