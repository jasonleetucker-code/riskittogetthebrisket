# Sitewide audit remediation, implementation and delivery directive — owner, 2026-11-06

**Status:** owner directive received 2026-11-06 (session `session_01BGLcxPv9489uMYWnm3GbTF`). This file is a
**structured record** of that directive, not a verbatim copy: every authorization, limit, decision, finding ID,
gate and deliverable it names is preserved below; prose was condensed. Where this record and a later explicit
owner instruction disagree, the later instruction wins.

Intake rows: `docs/OWNER_REQUESTED_TODO.md` MD-38 … MD-46. Execution section: top of `docs/EXECUTION_PLAN.md`.
Inventory, portfolio and traceability: `docs/audits/remediation_2026-11-06/`. Owner decisions (Part 16 table):
`docs/owner/OWNER_DECISION_REGISTER.md` → "Sitewide remediation directive (2026-11-06)". Decisions the agent made
under the delegated authority: `docs/audits/remediation_2026-11-06/DECISIONS.md`.

## 1. Mission

Convert every actionable finding from the two 2026-11-06 repository audits (a sitewide Top 20 and an engineering
Top 20 — these audits exist only in the directive; the findings it names are rows `DIR-01 … DIR-44` of the
inventory), the August master-site audit, the 2026-11-01 advanced-mathematics audit (AMATH-S01 … S63), the
research/promotion readiness audit (125 items, 39 findings), the product roadmap, the owner-decision registry and
relevant incomplete historical work into one coordinated, prioritized, actively executed program. **Authorization
to perform the work, not merely plan it.** Baseline: `origin/main` ≈ `e168b405`.

## 2. Authority delegated, and its limits

**Delegated now:** ordinary engineering, product, UX and evidence-based methodology decisions, chosen by
correctness → empirical predictive accuracy → decision usefulness → production safety → mathematical validity →
provenance/reproducibility → maintainability → performance → UX clarity → cost. Investigation, coding, regression
repair, bounded features, reversible UX decisions, testing, evidence-backed methodology *preparation*, and normal
reviewed PR integration and deployment under the existing CI and release requirements.

**Still not permitted:** using credentials the agent does not have; bypassing licensing, paywalls or provider terms;
spending money or activating billing; unauthorized root changes; exposing private routes, league data, credentials
or proprietary values; any Sleeper write; deleting or corrupting irreplaceable historical data; bypassing branch
protection, security controls or failing tests; promoting an unvalidated model; resuming DFS or League Tycoon;
launching the public Trade Advisor while privacy, security, licensing or production gates are open.

**Value-changing methodology:** research, benchmarking, challengers and evidence production are authorized now;
clearly corrective defects can be repaired through independent review and regression gates; consequential changes
to live canonical valuation, source voting, fairness, probabilities or public launch need independent outcome
evidence, a measured blast radius, a reproducible rollback and the documented activation conditions. Insufficient
evidence → keep the incumbent. No thresholds invented after seeing results.

## 3. Current-truth requirements (Part 1)

Reconstruct current truth before acting; directive observations are historical. Supersession corrections it
records: Roster Construction V1 is activated, nav-gated and production-verified (#2040, #2041, #2044, #2057, #2058;
84/84 comparable 2026 team-weeks) — do not rebuild; 2025 slots are never inferred for production; Waiver Advisor
and Weekly IDP Streaming are already active for signed-in users; #2006 merged; #2051 merged; #2054 merged and
superseded #2053. Lifecycle vocabulary: NOT_STARTED, RESEARCH_ONLY, IMPLEMENTING, IMPLEMENTED_UNTESTED, TESTED,
INDEPENDENTLY_REVIEWED, MERGED, DEPLOYED, PRODUCTION_VERIFIED, EVIDENCE_PENDING, BLOCKED_EXTERNAL, SUPERSEDED,
REJECTED, OWNER_PAUSED; MERGED ≠ DEPLOYED ≠ PRODUCTION_VERIFIED.

## 4. Governance and invariants (Part 2)

Canonical owners are preserved (lineup `src/ros/lineup.py`, scorer, `src/trade/roster_capacity.py`, drop
protection, `trade_decision.decide()`, valuation pipeline, temporal ledger, identity, league-config, pick
resolver, source-family voting, flags/auth). Domain invariants: missing ≠ 0; no unsafe fuzzy identity; weekly /
ROS / dynasty / FAAB units distinct; exact league rules; no cross-league bleed; no correlated double vote; no
future leakage; uncalibrated output is not a probability; bounded search never claims global optimality; NO
TRANSACTION is always compared; private ≠ redistributable; confidence never rises because evidence disappears;
challengers never silently replace champions; no incidental canonical value change; no Sleeper writes;
`geom_q078_v1` unchanged; no retired axes; no duplicate TE premium. `dynasty_main` 2026 rules preserved.

## 5. Zero-loss reconciliation (Part 3)

One canonical work item per underlying problem, each with ID, problem, finding IDs, issue/PR refs, status +
evidence date, root cause, owner, dependencies, authorization, parallel eligibility, plan, tests, acceptance,
rollback and disposition; a traceability matrix proving every finding, AMATH item, open issue and open PR has a
disposition. Implemented as `docs/audits/remediation_2026-11-06/build_inventory.py` (the build fails on any
unmapped row).

## 6. Execution strategy (Part 4) and waves (Parts 5–15, 17)

At most four concurrent implementation workers (including an editing coordinator), disjoint file ownership,
dependency-ordered, never sequential issue order. Priority: outages → deploy blockers → irrecoverable capture →
security/data loss → confirmed wrong outputs → multi-consumer defects → calibration infrastructure → feature
completion → performance/UX → speculative research.

| wave | content | inventory items |
|---|---|---|
| Zero / A | W0-A deploy blocker (Sonny Styles confidence test); W0-B production scraper outage + health (#2060); W0-C Week 10 pre-kickoff capture + 2027 pre-auction snapshot + perishable archives; W0-D backups, restore, security posture | CW-01 … CW-06 |
| B | auth/security family (W22-F001/F002/F003, W00-F001, CORS, docs, sessions, CSRF, limits); scoring parity + league config (W18-F003, W13-F001, RPA-F-002/003/008, #1842, #802, IDP categories); trade identity + math (W08-F003/F005/F007, picks, capacity, posture, equalizers); FAAB integrity (W10-F001, W11-F003/F004/F005/F007) | CW-07 … CW-10 |
| C | source freshness / independence / methodology comparison (DLF IDP hold, freshness v2, Outlier V2 #1884, #1938, #2006, Signals IDP); historical archives; Forecast Calibration Ledger; six-model IDP comparison; Game Day / ROS calibration | CW-11 … CW-17, CW-46 |
| D | streaming quality and dynasty protection; Analyze Trade; multi-team War Room; Finder / Best Offers / UI; fairness bands; Roster Construction integration; Player File + team context; Perfect Waivers claim; performance; navigation / a11y; Game Day UX | CW-18 … CW-28 |
| E | AMATH opportunities in evidence order | CW-29 … CW-36 |
| F | dependencies/toolchain; 2027 draft/auction; backlog reconciliation; governance; verification harness; awards | CW-37 … CW-43 |

Paused (CW-42), rejected/blocked (CW-44) and preserved systems (CW-45) are recorded, not worked.

## 7. Verification and promotion standards (Parts 18–20)

L0 reproduction + root cause + regression; L1 focused tests; L2 full hard gate + exact-head Validate PR (+ Vitest,
E2E, Chromium, WebKit, a11y, build where relevant); L3 independent review (delta re-review after any later change);
L4 integration on fresh main; L5 deployment (`/api/status` SHA, flags, honest health, auth gates, no unintended
value change, no new port); L6 production usefulness on a real authorized league/team. Model challengers: 20-step
champion/challenger protocol (target, metric, allowed data, frozen windows, no leakage, lineage, strata, simple
baselines, uncertainty, misses, decision utility, runtime, missing sources, reproducible result, independent review,
promote/reject/continue decision, incumbent kept when unproven, rollback + drift monitoring). Data safety: no
credentials, tokens, cookies, sessions, private PII, unlicensed data, internal addresses or secret paths committed.

## 8. Resolved decisions (Part 16) — recorded as owner decisions

Mirrored row-for-row in the owner decision register. Each applies only to its scope; contrary new evidence is
recorded and the safer evidence-supported behavior adopted, never a silent contract change.

| Subject | Decision |
|---|---|
| Roster Construction private activation | Already authorized and later verified; recheck current production, do not reactivate blindly |
| Historical 2025/2024 slots | Never infer as production fact; explicit unavailable state |
| Roster Construction navigation | Authenticated My Team with capability gating |
| Waiver streaming dynasty budget | Default zero net dynasty loss using canonical release-cost logic |
| Unpriced assets | Never treat a missing valuation as a free drop |
| Kickers | League-scored projected lineup contribution; no invented dynasty value |
| IDP defensive TDs | Canonical scorer and actual league settings only |
| Developmental edge-rusher protections | Evidence-based protection, not blanket position exemptions |
| Bounded optimization | Disclose search incompleteness; never claim optimality |
| Perfect Waivers optimality wording | State objective, horizon, constraints and search scope |
| Trade Monte Carlo synthetic win rate | Hide probability framing until real uncertainty bands exist |
| Finder arbitrage terminology | Use disagreement terminology until convergence is proven |
| Single-source valuation haircut | Independently validated shadow challenge; no auto-promotion |
| Fairness-band changes | OD-F4 evidence protocol before any methodology replacement |
| DLF IDP vote hold | Retain until release gates demonstrate justified improvement |
| Source freshness v2 | OFF until independent correctness and blast-radius tests pass |
| Outlier Integrity V2 | Research/validate; no unconditional activation |
| Public Trade Advisor | OFF until security, licensing, privacy and production gates pass |
| Multi-team private War Room | Finish validation; enable privately when its existing release criteria pass |
| Forecast models | Promote only through prospective, independent evidence |
| Game Day probabilities | Experimental until outcome-calibrated |
| Advanced DRO/CVaR streaming | Defer until forecast performance justifies the complexity |
| Historical trade acceptance probability | Never estimated from accepted-only observations |
| Rookie auction | Complete preparation; official launch is a distinct real-world event |
| Draft-order median rule | Verify an authoritative source; otherwise provisional/unknown |
| Homepage/mobile IA | Task-oriented navigation, in-season Game Day visibility, stable URLs |
| League Tycoon and DFS | Remain paused |
| External paid sources | No new spending |
| Source licensing | No automated/public use without legitimate permission |
| Private historical data | Keep private; anonymize public research artifacts |
| Live model changes | Measured independent benefit, gates, rollback and release evidence |

Navigation specifics (Part 12.2) the directive also settled: in-season My Team prioritizes the user's team and Game
Day; one coherent waiver workflow with stable URLs and no signed-out exposure of gated tools; draft preparation
under Draft & Strategy with contextual links; Trade Database cross-linked from trade analysis; league-wide posture
under League; a task-oriented Find Value landing that keeps disagreement / fit / consensus / upside distinct; Sharp
People only where capability, privacy and population permit; obvious playoff-odds destination; PWA shortcuts
without an unlaunched auction as default; in-season mobile tabs prioritize Game Day; grouped public League Hub tabs
with stable URLs; the listed accessibility work, with mobile scans extended to `/waiver-advisor`,
`/roster-construction` and `/draft`.

## 9. Deliverables (Part 22) and reporting (Part 23)

A current-state audit; B unified finding registry; C ranked portfolio (integrated, not a second roadmap); D
completed code and PRs; E production operational recovery evidence; F model/statistical research artifacts; G
product completion evidence; H decision register of delegated decisions; I closure / remaining-blocker report
(actively implementing, dependency blocked, awaiting evidence, external/owner action, paused, rejected/superseded);
J refreshed session handoff. Progress reports name exact PRs, commits, test counts and evidence paths, and never
say "should work", "fully tested", "optimal" or "validated" without the evidence those words require.

## 10. Final priority rules (Part 24)

Production health > new features; deploy blocker > cosmetics; irrecoverable capture > deferrable work; security and
scoring correctness > model novelty; calibrating a forecast > a more elaborate unvalidated optimizer; decision
improvement > agreement with an arbitrary expert rank; one canonical system > duplicates; clear UI > impressive
dashboard; truthful unavailable state > fabricated number; evidence-backed rejection > a bad feature; working,
reviewed, deployed code > another planning document.
