# Session resumption, remediation and continuous verification — owner directive, 2026-11-07

**Structured record** of the owner's chat directive "CHASE UPSIDE — MASTER SESSION RESUMPTION, REMEDIATION, AND
CONTINUOUS VERIFICATION DIRECTIVE" (2026-11-07; repository `jasonleetucker-code/riskittogetthebrisket`). Every
decision, requirement, limit and deliverable is kept; prose is condensed. It continues the two 2026-11-06 directives
(`SITEWIDE_REMEDIATION_DIRECTIVE_2026-11-06.md`, `CONTINUOUS_QA_DIRECTIVE_2026-11-06.md`) inside the same program and
inventory (CW-01 … CW-53) — **not** a second roadmap. Intake rows MD-56 … MD-64 in `docs/OWNER_REQUESTED_TODO.md`;
owner decisions in `docs/owner/OWNER_DECISION_REGISTER.md` (section "Session resumption directive (2026-11-07)");
authorization in `docs/EXECUTION_PLAN.md` (same date).

## 1. Mission and standing

- Resume from the latest verified repository state (#2104 merged; production `405bc35a` at that handoff — historical
  facts to re-verify, never assume). Execute, don't plan: implement authorized product decisions, re-audit unresolved
  findings, correct verified defects, strengthen permanent regression coverage, prepare methodology changes for
  controlled review. Parallel independent workstreams where safe; integrate through the existing gates.
- Keep five categories distinct: (1) verified defects fixable now; (2) the product decisions below; (3) mathematical /
  valuation changes needing more evidence; (4) changes needing separate owner approval before production activation;
  (5) box-operator tasks.
- Complete = intended behavior, mathematical correctness where applicable, integration and regression protection
  independently verified — never "a patch exists" or "a test passes".

## 2. Owner product decisions (implement the routine engineering portions)

| Decision | Finding | Decision text (condensed) | Acceptance |
|---|---|---|---|
| A | W12-F006 | Terminal signal takes precedence over BDVM when both detectors alert for the same player in the same sweep. Deterministic cross-detector coordination on canonical player id + user + sweep scope; Terminal is the user-facing notification; both detectors' results kept internally; contradictory directions retained for diagnostics; suppressing the BDVM email never suppresses BDVM computation, state or legitimate future alerts; cooldown / retry correctness kept; no cross-player / cross-user suppression; the separate custom-alert route is NOT changed without its own intended behavior and decision. Tests: duplicates, conflicting / same direction, separate players / users, missing identifiers, cooldowns, retries, failure recovery | At most one user-facing notification per canonical player, user and sweep, with no lost detector evidence |
| B | W20-F001 | `/rosters` is the primary frontend consumer of the Team Gameplan (`/api/gameplan`). On-demand panel / expandable section for the selected team; reuse the existing endpoint and canonical roster-intelligence calculations; load only when requested; respect auth and league access; show posture, strengths, weaknesses, competitive direction, strategic opportunities where the API supports them; freshness and unavailable states; no duplicate or contradictory team-ranking methodology; no new team-strength score; existing design patterns; understandable, not raw internals. Trace backend → API → frontend contract → presentation → interaction | A user opens `/rosters`, selects an eligible team and gets a coherent, tested gameplan without unnecessary network or computation |
| C | W10-F003 | Retire the legacy Next Best Targets methodology in favor of the Perfect Draft optimizer. Inventory unique functionality first; migrate only verified-correct, useful features into Perfect Draft; no conflicting recommenders; keep budget, availability, eligibility and draft context; test budgets, availability, roster construction, realistic auctions; remove dead code / navigation / docs / orphaned tests where safe; never report "no viable recommendations" merely because the old EV is zero | One authoritative Perfect Draft experience with independently verified recommendations and no contradictory legacy panel |
| PR #1938 | DD-11 | **Approved for promotion preparation, not immediate merge.** Review the branch; independently check the corrected cases (special-teams tackle subtraction, remaining tackle-assist problem, blocked kicks, defensive fumble-return TDs, non-IDP-listed defensive stats, FB/RB position discrepancy); rebase / update safely; targeted tests + independent scoring-parity reconciliation; a production-compatible BDVM snapshot through authorized access; current vs corrected values on identical snapshot inputs; affected players / positions; replacement levels, ranks, trade recommendations, alerts and other consumers; independent review and CI; release + rollback recommendation. **Do not merge or activate its valuation effects without an explicit subsequent owner approval after the impact evidence exists.** If production snapshots are inaccessible, record the blocker precisely and complete all offline validation | A reviewed promotion package or a precise blocker list |
| DD-14 | — | The DFS program stays paused for new development; the deployed DFS refresh timer is **not** disabled automatically | Preserve its existing operation unless the owner changes it |

## 3. Valuation and mathematical methodology gates (investigate; propose; never activate)

Authorized for investigation, correction proposals, independent testing and comparative evaluation — **not** for
changing production formulas, weights, thresholds or activation flags:

- **W13-F003 BDVM signal saturation** (570 STRONG_SELL of 676 market-anchored rows on pinned inputs): scale mismatch,
  calibration, replacement level, threshold design, distribution by position / asset class, liquidity, sensitivity to
  missing / stale data; candidates incl. scale-aware calibration and distribution-aware thresholds. Never pick a fix
  because the BUY/SELL split looks balanced — a one-sided market may warrant one-sided results; compare against the
  incumbent on frozen point-in-time data and independent benchmarks.
- **W27-F001 IDP edge consistency**: the correct long-term canonical benchmark; audit IDPTC's dependence as both a
  valuation input and a benchmark (double counting). Until approved: preserve calculations, make missing KTC coverage
  explicit, never treat missing as neutral, never fabricate an IDP market gap, never derive contradictory
  recommendations in multiple frontend components. Deliver a canonical contract proposal with evidence.
- **W27-F005 TE skew** (22 retail-premium vs 1 consensus-premium): genuine difference vs TE-premium scoring vs
  positional calibration vs replacement level vs market sources vs a wrong transformation vs methodology mismatch;
  compare actual league scoring and market-source behavior first; never force symmetry.
- **W30-F008 Hill denominator**: controlling requirement, implementation, prior evidence, proposed alternative;
  an independent mathematical oracle; historical comparison; edge cases, denominator behavior, numerical stability,
  downstream value changes. Keep production methodology until a replacement passes the owner and evaluation gates.
- **Every consequential proposal** carries: current formula and meaning; defect evidence; proposed correction;
  independently computed expected results; before/after player impacts; position and league-format impacts;
  historical predictive evaluation; confidence / calibration / uncertainty implications; downstream consumer
  effects; rollback and explicit activation status. Sophistication is not evidence. Preserve league scoring,
  Superflex, IDP rules, weighting principles and canonical value definitions unless an approved change overrides them.

## 4. CW-40 — re-audit the 59 outstanding P1 findings (principal priority)

41 `repro_rotted` + 18 `unsafe-to-rerun` from the 2026-11-06 recount are baselines, not verdicts. Per finding:
original claim → controlling requirement → code path → original repro still valid? → independent repro → test on
current code and realistic data → actual frontend / API behavior → still a defect? → evidence-supported status →
smallest repair → implement if routine and authorized → permanent regression coverage → re-run → central inventory
with evidence and commit references. Statuses: `CLOSED_VERIFIED`, `OPEN`, `PARTIAL`, `UNVERIFIABLE`,
`REQUIRES_OWNER_DECISION`. A stale repro is not a fix; a passing existing test is not intended behavior. Independent
technical groups (backend/API; frontend/workflows; math/scoring/valuation; data integrity/freshness/identity;
security/privacy/auth/ops) with clear file ownership; priority: security / privacy / irrecoverable data → wrong
calculations or misleading recommendations → real user-facing failures → missing / stale data presented as current →
reliability / performance / maintainability → cosmetic. A persistent progress ledger (finding id, classification,
evidence, remediation PR, verification status) that is never reset in a new session.

## 5. Additional dependency-ready work

CW-49 (FAAB anchor derivation, market layer, ROS/BDVM oracles; invariants, not just "returns a value"); CW-53
(slowest test files, shared-state constraints, `pytest-xdist --dist loadfile` and other safe parallelization — never
by reducing coverage, bypassing gates or adding flakiness); CW-48 (requirement → implementation → independent test →
observed evidence, incl. disabled / experimental / shadow / public features; things that work but miss the
requirement); CW-52 (dead code — remove only proven unused or safely superseded; keep intentionally disabled or
planned features); CW-37 (Dependabot PRs vs current CI and runtime; group safe updates; no major bumps without
regression evidence); W25-F003 presentation residual and W26-F003 `/draft` freshness — verify what recent merges
already addressed; never reimplement completed changes.

## 6. Production backup, restore and operational safety (box operator)

Per #2064 and the handoff: state-backup installation; a successful backup generation; group-level directory
visibility; backend backup-health observability; SQLite restore into an isolated scratch directory; SQLite integrity
checks; archive readability; inclusion or documented exclusion of important persistent stores; required timer status;
port 8000 not reachable externally. Backup creation is not sufficient — a restore must be verified. Never restore
into live databases; never delete backup history to clear a warning. Without box access: an exact operator runbook
(commands, validation criteria, expected evidence); never mark the box task complete.

## 7. Permanent regression and feature-intent verification

Every verified defect gets durable protection; tests check both "does it function" and "does it behave as intended"
(a number is not a correct number; a recommendation is not an optimal or valid one; a label is not a justified
signal; a finished scraper is not preserved identity; a rendered page is not working controls; a backup job is not a
recovery). Independent oracles, historical ground truth, property / differential / metamorphic / end-to-end tests.
Invariants: missing ≠ 0; stale ≠ current; evidence loss never unjustifiably raises confidence; real league settings;
no identity drift or duplication; no double counting; one canonical value definition; flags control reachability;
no private leakage through public APIs; recommendations respect real roster, eligibility and budget constraints;
frontend and backend never contradict. Record which tests are genuinely independent and which reproduce the
implementation.

## 8. Implementation, integration, release and reporting

Repository agent operating system, execution plan and release requirements apply. Known hazards: never a GitHub
closing keyword for an open PR one only references; pinned Python formatting; explicit UTF-8; local vs CI Node;
supported JSX/Vitest locations; never auto-overwrite audit or coercion baselines; no indiscriminate `git stash`; no
concurrent edits to one file; remove finished worktrees; preserve immutable receipts, historical evidence and frozen
snapshots. Every PR: intended change, exact defect / requirement, impacted systems, independent evidence, regression
tests, results and limitations, whether player values or rankings change, flags and rollback, independent review,
owner gates respected. Merge only routine authorized changes through the normal gates; never bypass red checks; never
merge owner-reserved valuation changes because they compile. Checkpoint reports: work completed, PRs opened / merged,
validation evidence, defects confirmed / corrected, findings closed / unresolved, production behavior changes, value
changes, blockers, owner decisions still required, next work. Update `docs/agent-operating-system/SESSION_HANDOFF.md`
at the end.

## 9. Final deliverables

(1) Terminal/BDVM alert reconciliation; (2) Team Gameplan on `/rosters`; (3) one consolidated Perfect Draft
experience; (4) fresh adjudication of as many of the 59 P1 findings as safely possible (goal: all 59); (5) repairs for
confirmed routine defects; (6) permanent regression tests; (7) evidence-backed methodology proposals without
activation; (8) a reviewed #1938 promotion package or precise blockers; (9) continued oracles and suite improvements;
(10) a backup/restore verification receipt with box access, otherwise an executable runbook; (11) updated inventory,
decision records and handoff; (12) a final report separating verified, partial, blocked and owner-gated work.
