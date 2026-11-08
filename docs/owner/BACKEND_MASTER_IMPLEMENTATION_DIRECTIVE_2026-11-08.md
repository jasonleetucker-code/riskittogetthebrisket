# Master implementation directive — complete backend, mathematics, model accuracy, decision intelligence, reliability and technical debt campaign (owner, 2026-11-08)

**Structured record** of the owner's chat directive "MASTER IMPLEMENTATION DIRECTIVE — CHASE UPSIDE / RISK IT TO
GET THE BRISKET" (2026-11-08, received ~11:20Z; repository `jasonleetucker-code/riskittogetthebrisket`;
production https://chaseupside.com). It is an implementation authorization for work already permitted under owner
directives. It runs inside the existing remediation program (`docs/audits/remediation_2026-11-06/`, CW-01 … CW-53;
P1 ledger) and the 2026-11-07 / 2026-11-08 directives (MD-65 … MD-96). It is not a second roadmap.
- Intake: MD-97 … MD-115 in `docs/OWNER_REQUESTED_TODO.md`.
- Acceptance matrix: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
- Frontend handoff: `docs/ui/BACKEND_API_HANDOFF.md`.
- Authorization: `docs/EXECUTION_PLAN.md` (same date).

## Binding scope rules
- **Absolute frontend exclusion (§2).** Under this directive, nothing under `frontend/` changes: no page, layout, style, component, navigation, visualization, copy, Sports Network prototype (#2132, #2112) or framework migration.
  - **Allowed:** backend APIs and calculations, additive versioned response fields, API-contract tests, synthetic fixtures, and backend-cause investigation of frontend defects.
  - **Frontend portions** go to `docs/ui/BACKEND_API_HANDOFF.md`: route, existing behavior, intended behavior, contract, examples, compatibility, regression scenarios, remaining frontend work.
- **Delegated:** ordinary engineering and reversible product choices (§4, §26).
- **Owner-reserved, unchanged:**
  - valuation-methodology activation and canonical value, weight, voting or parameter changes without evidence and approval;
  - #1938;
  - protected flags;
  - the public Trade Advisor;
  - DFS and League Tycoon;
  - Sleeper writes;
  - spending;
  - licensing bypass;
  - weakening CI;
  - repository rule changes;
  - root-level infrastructure;
  - discarding unverified historical data;
  - exposing private data;
  - inventing evidence;
  - calling a deterministic model "calibrated".
- **Execution:** at most 4 concurrent editing workers including the coordinator, in four workstreams:
  - A: mathematics and predictive accuracy;
  - B: data integrity, security, reliability;
  - C: decision engines;
  - D: backend performance and maintenance.
- **Order:** phases 0–5 (§27); a logically grouped PR sequence with the 15-point description (§28); a status distinction from implemented through production-verified.

## Priorities (§6–§24) → intake
| # | Priority (condensed) | Intake |
|---|---|---|
| 1 | Best-ball team-points calibration: diagnose the fallback's scale and spread error; a point-in-time team-level evaluation pipeline (means, sd, ordering, matchup quality, PF, expected wins, downstream playoff / title); baselines; pre-registered gates; no silent replacement | MD-97 |
| 2 | Exact league scoring and IDP scorer parity: a discrepancy taxonomy for the remaining nflverse vs host mismatch; hand-computable category tests; impact on BDVM / ROS / team intel / trades; prepare #1938 for decision, never merge it | MD-98 |
| 3 | Silent source-ingestion failures (W05-F003 / W05-F004): schema, header, identity, timestamp, empty / truncated / population checks; previous-valid-snapshot preservation; evidence-derived row floors; quarantine, never fabricate | MD-99 |
| 4 | Enforceable CI without losing speed: verify which checks are required; owner-controlled enforcement plan accounting for automation that writes to main (no broad bypasses); automated detection of receipt, skip, shard, classification, dependency and methodology-change gaps | MD-100 |
| 5 | Skipped-test, regression and feature-intent audit: every skip mechanism enumerated and justified; forced-drop properties executing enough applicable draws; real-roster tests restored or replaced; budgets tightened; the permanent 12-step verification standard | MD-101 |
| 6 | League-specific playoff, division and draft-order correctness: verify #2149 end to end (rules, assignment history, ties, 7 qualifiers, byes, bracket, re-seeding, draft slots, median-game treatment, historical vs current settings, Sleeper conflicts); fail closed on unknown rules; owner-facing explanation for unproven governance rules | MD-102 |
| 7 | Backup recovery, security validation and production reliability: proven restorable backups (checksums, manifests, scratch restore drills, retention, alerts); auth / admin / cross-league / session / CSRF / CORS / limits / error leakage / bindings audit | MD-103 |
| 8 | Permanent prediction-accuracy and calibration system: preserved prediction, inputs, versions, SHA, outcome and horizon per forecast family; task-appropriate metrics; reproducible champion vs challenger; no auto-promotion | MD-104 |
| 9 | Waiver Advisor, FAAB and IDP Streaming as decision systems: the 16-step end-to-end workflow and 10 invariants (unknown ≠ 0, known 0 = 0, ≤ verified FAAB, no free drops, legal moves only, …); every reachable path incl. dormant helpers | MD-105 |
| 10 | Source independence, outlier integrity and IDP voting evidence: reproducible comparisons (incumbent vs Outlier Integrity V2 #1884, withheld / restored sources, haircut and independence candidates, freshness, populations); measured movement, exclusions and downstream effects; no promotion | MD-106 |
| 11 | Empirically justified trade uncertainty: replace the fixed synthetic band only with held-out-validated estimates, else an explicit unavailable state; simulation frequency ≠ acceptance probability; keep `geom_q078_v1` | MD-107 |
| 12 | Rookie-draft market normalization and pick evidence: comparable vendor populations, direct vs derived quotes, no false advantages from incomplete lists, pick identity / ownership preserved, provider independence, freshness | MD-108 |
| 13 | BDVM directional-signal saturation (~570 / 676 STRONG_SELL): trace and diagnose, evaluate alternatives on independent evidence; no threshold tuning for looks; incumbent kept until gates pass | MD-109 |
| 14 | Injury-news attribution (W21-F001): classification and identity rules separating injury from contract, transaction, rumor, negation, …; no fabricated assessments; methodology adjustments stay gated | MD-110 |
| 15 | Unify team strength, posture and portfolio semantics: canonical distinct concepts with schemas; picks handled explicitly; contradictory classifiers retired only with consumer migration; no value changes from refactoring | MD-111 |
| 16 | Trade Finder, Suggestions and Analyze Trade as one decision system: package shapes, picks incl. same-archetype generics, capacity, needs, posture, evidence, fairness, counteroffers, multi-team, NO TRANSACTION; equity kept separate from VA / package / fit; the public advisor stays off | MD-112 |
| 17 | IDP and two-TE market intelligence without invented multipliers: coverage, independence, baselines, replacement, scarcity; two-TE starters ≠ TE premium; league-aware candidates without global value changes; the A / B / C format study stays research-only | MD-113 |
| 18 | Backend and API performance: remaining `/api/public/league` payload (~2.7 MB), section-targeted reads, caches, blocking I/O; real authenticated measurements (cold / warm, p50 / p95, payload, freshness); semantic parity required | MD-114 |
| 19 | Repository cleanup, technical debt, dependencies and documentation convergence: PR dispositions (#1884, #1873, #1852, #1513 and #1938 protected), proven dead code only, worktree preservation, one canonical item per requirement | MD-115 |

**Cross-cutting (§25):**
- one canonical owner per concept;
- missing is never zero;
- no correlated double counting;
- no hindsight leakage;
- no unsupported optimality claims;
- regression tests that prove intended behavior;
- quantitative concepts kept separate.

**Reporting (§32), sections A–K:**
- A completed implementation;
- B production state;
- C mathematical findings;
- D model evidence;
- E data reliability;
- F test coverage;
- G performance;
- H security and recoverability;
- I remaining work;
- J owner decisions;
- K frontend handoff.

**Permanent standard (§34):** intent → canonical ownership → implementation → independent expected results → regression tests → integration verification → empirical evaluation → independent review → exact-tree CI → authorized deployment → production verification → monitoring.
