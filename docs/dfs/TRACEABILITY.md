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
| DFS-§5-03 | Showdown / single-game / captain / MVP | P2 | NEXT | DFS-RULES-02 |
| DFS-§5-04 | NBA, NHL, MMA rule sets | P2 | NEXT | DFS-RULES-03/04/05 (NHL/NBA seasons start in October) |
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
| DFS-§8-02 | Groups (at least/at most K) | P1 | SLICE1 (API) | UI editor pending |
| DFS-§8-03 | Conditional rules (if-A-then-B), mutually exclusive groups | P2 | NEXT | |
| DFS-§8-04 | Stacks: primary/secondary, bring-back | P1 | SLICE1 (QB stack) | Portfolio stack distributions pending |
| DFS-§8-05 | Sport-specific stacks (NBA/NHL/MMA) | P2 | NEXT | |
| DFS-§8-06 | Exposure semantics + integer rounding shown | P1 | SLICE1 (max, floor) | Min exposure + scoped exposure pending (needs joint portfolio) |
| DFS-§8-07 | Minimal conflicting subset, no hidden relaxation | P1 | SLICE1 | Deletion filter over owner items |
| DFS-§8-08 | Editable forecasts vs preference boosts kept separate | P2 | NEXT | |
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
| DFS-§15-01 | Podcast discovery → transcripts → claims → controlled use | P3 | NEXT | 29 seeds registered |
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
| DFS-§24-xx | Test program items 1–52 | per phase | PARTIAL | Items 2, 8, 9, 10, 11, 12, 13, 14, 15, 20, 21 (cash-line tie), 22, 23, 28 (bound), 29, 32, 43(partial), 44, 47, 51, 52 covered |
| DFS-§25-01 | Dependency-aware roadmap linked to Calculator Ideas | P0 | SLICE1 | `ROADMAP.md` |
| DFS-§26-01 | Lane 6 active every batch | all | SLICE1 | `/dfs` UI shipped with the foundation; UI ledger row |
| DFS-§27-01 | Documentation set + user guide | P0 | SLICE1 | This folder |
| DFS-§28-01..14 | Owner acceptance stories | P1–P8 | PARTIAL | Story 1 (partial: honest states for all four sports), 5 (partial), 6, 12 (partial), 13 (partial), 14 |
