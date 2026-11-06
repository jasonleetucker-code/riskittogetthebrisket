"""Build the 2026-11-06 sitewide remediation inventory (zero-loss reconciliation).

Regenerate rather than hand-edit:

    python docs/audits/remediation_2026-11-06/build_inventory.py          # write
    python docs/audits/remediation_2026-11-06/build_inventory.py --check  # verify committed outputs

Inputs are the repository's own records (no network):

* AMATH-S01..S63 — ``docs/research/amath/evidence/sitewide_opportunities_merged.json``
* research/promotion readiness — ``docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.json``
  (125 items + 39 findings)
* owner intake MD-1..MD-55 — ``docs/OWNER_REQUESTED_TODO.md`` (MD-47..MD-55: the 2026-11-06
  continuous-QA directive, work items CW-48..CW-53)
* open issues / PRs — ``github_snapshot.json`` (GitHub API, captured 2026-11-06T12:45Z)
* directive-enumerated findings — ``DIRECTIVE_FINDINGS`` below (the two 2026-11-06 audits
  exist only in the owner directive; every finding it names is a row here)
* master-site audit (431) — counted from ``docs/master-site-audit/closure.json`` with its
  generation date, because that ledger is three months stale; the live recount is a
  separate measurement recorded in ``INVENTORY.md``.

Every input row gets exactly one canonical work item (``cw``) or a terminal disposition.
The build FAILS if any input row is unmapped, if a ``cw`` is unknown, or if two canonical
work items share an id.  It decides nothing about product methodology: dispositions mirror
the owner decisions already recorded and the 2026-11-06 directive's Part 16 table.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT_JSON = HERE / "inventory.json"
OUT_MD = HERE / "INVENTORY_TABLES.md"

# ── canonical work items ─────────────────────────────────────────────────
# state vocabulary (directive §1.2): NOT_STARTED RESEARCH_ONLY IMPLEMENTING
# IMPLEMENTED_UNTESTED TESTED INDEPENDENTLY_REVIEWED MERGED DEPLOYED
# PRODUCTION_VERIFIED EVIDENCE_PENDING BLOCKED_EXTERNAL SUPERSEDED REJECTED OWNER_PAUSED
CW: list[dict] = [
    # wave A — production and evidence critical path
    {
        "id": "CW-01",
        "wave": "A",
        "priority": "P0",
        "title": "Deploy blocker: DLF-hold confidence invariant (Sonny Styles)",
        "owner": "tests/api/test_dlf_offense_only_vote.py",
        "state": "PRODUCTION_VERIFIED",
        "evidence": "#2061 merged inside release train #2072 (91b0965c); Deploy Production run 3734 succeeded 2026-11-06T18:48Z; live /api/status build.commit 91b0965c",
        "next": "none (closed)",
    },
    {
        "id": "CW-02",
        "wave": "A",
        "priority": "P0",
        "title": "Production scraper browser-launch outage + truthful health",
        "owner": "Dynasty Scraper.py launch, server.py reaper/status",
        "state": "MERGED",
        "evidence": "production recovered by the 3734 deploy restart: scrape success 2026-11-06T18:48:38Z (263 s), /api/health 200 (was 503); PR #2062 (pre/post cgroup-scoped reaper + public-safe box diagnostics) merged a9244b0a after one rerun of a load-sensitive timing test (DD-16)",
        "next": "after its deploy: read live /api/status box_resources and confirm scrapes keep succeeding",
    },
    {
        "id": "CW-03",
        "wave": "A",
        "priority": "P0",
        "title": "Pre-kickoff forecast capture: Week 10 freeze receipts, Week 9 scoring",
        "owner": "projection weekly archive + ROS / six-model receipts",
        "state": "MERGED",
        "evidence": "Week 10 receipts merged #2065; prospective evaluation runner merged #2077",
        "next": "box check of w9/w10 archive timestamps; run the Week 9 evaluation once final",
    },
    {
        "id": "CW-04",
        "wave": "A",
        "priority": "P0",
        "title": "2027 rookie-auction first-valid pre-auction snapshot",
        "owner": "scripts/backtest_perfect_draft.py --record-snapshot",
        "state": "MERGED",
        "evidence": "PR #2063 merged (640193f8): first-valid-wins pre-auction snapshot timer",
        "next": "deploy, then confirm the timer on the box; nit: import the 6 h budget from its owner",
    },
    {
        "id": "CW-05",
        "wave": "A",
        "priority": "P0",
        "title": "Backup coverage, restore verification, truthful backup health",
        "owner": "backup health + state backup writer",
        "state": "HUMAN_ACTION_REQUIRED",
        "evidence": "PR #2064 merged (bdc0cd5f); live backup_health still stateBackup unverifiable/permission_denied until the operator re-runs the installer",
        "next": "box operator: bash deploy/backup/install_state_backup.sh, then scripts/verify_state_backup_restore.py",
    },
    {
        "id": "CW-06",
        "wave": "A",
        "priority": "P1",
        "title": "Production network/security posture verification",
        "owner": "deploy/ nginx + bind configuration",
        "state": "EVIDENCE_PENDING",
        "evidence": "MD-27 headers verified 2026-11-01; re-verified live 2026-11-06 (HSTS, CSP frame-ancestors, XFO, nosniff, Referrer, Permissions; no version banner; /openapi.json 404)",
        "next": "direct :8000 exposure (MD-24) needs box-operator confirmation",
    },
    # wave B — correctness foundations
    {
        "id": "CW-07",
        "wave": "B",
        "priority": "P1",
        "title": "Auth/security defect family (redirect, XFF trust, login throttling, draft-capital boundary)",
        "owner": "frontend middleware/login + server.py auth/rate limiter",
        "state": "MERGED",
        "evidence": "#2075 merged (login next sanitizer, missing budget is unavailable not $0); #2087 merged: POST /api/ros/refresh admin gate admitted any signed-in user (truthy JSONResponse refusal) -- fixed, 6 private routes regression-tested, AST guard against the pattern; security review APPROVE",
        "next": "confirm deploy; owner policy question only: sharp audit routes are any-signed-in, not admin-only (documented, consistent with siblings)",
    },
    {
        "id": "CW-08",
        "wave": "B",
        "priority": "P1",
        "title": "Canonical scoring parity census + league-config propagation",
        "owner": "canonical league scorer + league-config resolver",
        "state": "MERGED",
        "evidence": "PR #2069 merged (280514bc): host-truth parity census",
        "next": "#1938 recommendation stays owner-reserved (DD-11)",
    },
    {
        "id": "CW-09",
        "wave": "B",
        "priority": "P1",
        "title": "Trade engine identity + mathematical correctness",
        "owner": "trade_decision / packages / pick identity",
        "state": "NOT_STARTED",
        "evidence": "W08-F003/F005/F007, #1415, #800, #841-#843",
        "next": "controlled-fixture monotonicity + pick-origin round-trip tests",
    },
    {
        "id": "CW-10",
        "wave": "B",
        "priority": "P1",
        "title": "FAAB correctness and recommendation integrity",
        "owner": "src/trade/faab_engine.py",
        "state": "MERGED",
        "evidence": "PR #2071 merged (cd555327): FAAB integrity fixtures + fail-closed config",
        "next": "follow-up in flight: apply the same config refusal to /api/waiver/advisor and /api/waiver/streaming",
    },
    # wave C — data quality and calibration
    {
        "id": "CW-11",
        "wave": "C",
        "priority": "P1",
        "title": "Source freshness/integrity monitoring (no false green)",
        "owner": "config/source_staleness.json + source health",
        "state": "MERGED",
        "evidence": "PR #2070 merged (4d374cf3): overdue rehabilitation plans re-reviewed",
        "next": "CW-26 note: the public snapshot layer itself has no staleness bound (memo layer bounded at 6 h by #2084)",
    },
    {
        "id": "CW-12",
        "wave": "C",
        "priority": "P1",
        "title": "Source independence/lineage + proprietary-identifier hygiene",
        "owner": "config/sources/source_lineage.json",
        "state": "NOT_STARTED",
        "evidence": "MD-21 IDPTC-IDP Show lineage; MD-23 Datawrapper ids; #804",
        "next": "record verified lineage; leave-one-family-out sensitivity",
    },
    {
        "id": "CW-13",
        "wave": "C",
        "priority": "P2",
        "title": "Unified source-methodology comparison (DLF IDP hold, freshness v2, outlier V2, #1938, Signals IDP)",
        "owner": "data_contract voting pipeline (research only)",
        "state": "RESEARCH_ONLY",
        "evidence": "#1884, #1938, MD-5; AMATH-S36",
        "next": "one board-diff + holdout comparison; incumbent kept unless gates pass",
    },
    {
        "id": "CW-14",
        "wave": "C",
        "priority": "P2",
        "title": "Historical source archives (KTC trade DB, variants, point-in-time injury/news)",
        "owner": "temporal ledger + collectors",
        "state": "NOT_STARTED",
        "evidence": "directive §5 W0-C historical capture extensions",
        "next": "inventory what is already archived before adding collectors",
    },
    {
        "id": "CW-15",
        "wave": "C",
        "priority": "P0",
        "title": "Forecast Calibration Ledger + size-controlled gates",
        "owner": "AL-3b scorecard / AL-4a Game Day calibration",
        "state": "INDEPENDENTLY_REVIEWED",
        "evidence": "PR #2076: AL-3b/AL-4a schedule; merge conflict with #2063 in the installer resolved by keeping both timers (f9049d11; deploy tests 1423 passed)",
        "next": "merge on green",
    },
    {
        "id": "CW-16",
        "wave": "C",
        "priority": "P1",
        "title": "Weekly IDP six-model prospective comparison",
        "owner": "MD-30 prereg + frozen fits",
        "state": "MERGED",
        "evidence": "PR #2077 merged (58c89c08): prospective evaluation runner",
        "next": "run Week 9 once final",
    },
    {
        "id": "CW-17",
        "wave": "C",
        "priority": "P1",
        "title": "Game Day / ROS calibration (shared latent factors, measured marginals)",
        "owner": "Game Day sim + ROS engine",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S03, S04, S30, S47; MD-4; master-audit W17-F001 residual (no preseason guard on ROS season selection) routed here by CW-40 / PR #2082",
        "next": "shadow challengers after CW-15; preseason guard for ROS season selection",
    },
    # wave D — decision improvements
    {
        "id": "CW-18",
        "wave": "D",
        "priority": "P1",
        "title": "Streaming recommendation quality + dynasty protection settings",
        "owner": "src/waivers/streaming*.py",
        "state": "RESEARCH_ONLY",
        "evidence": "MD-8, #2045; AMATH-S06 S09 S26",
        "next": "forecast-limited per #2045; budget 0, NO TRANSACTION, bounded-search disclosure",
    },
    {
        "id": "CW-19",
        "wave": "D",
        "priority": "P1",
        "title": "Analyze Trade unification + honest Monte Carlo framing",
        "owner": "trade_decision.decide()",
        "state": "INDEPENDENTLY_REVIEWED",
        "evidence": "PR #2067: synthetic Monte Carlo win rate hidden; 'Market Disagreement'; nav invariant test updated for the owner rename (ce2e969d, reviewed APPROVE)",
        "next": "merge on green (journeys re-run once: WebKit navigation flake)",
    },
    {
        "id": "CW-20",
        "wave": "D",
        "priority": "P2",
        "title": "Multi-team War Room validation (private)",
        "owner": "trade_ledger + analyze_trade_n",
        "state": "EVIDENCE_PENDING",
        "evidence": "flag trade_multi_team_analysis OFF in production",
        "next": "existing release criteria; private only",
    },
    {
        "id": "CW-21",
        "wave": "D",
        "priority": "P2",
        "title": "Trade Finder / Best Offers + calculator UI fixes",
        "owner": "finder.py / suggestions.py / trade page",
        "state": "INDEPENDENTLY_REVIEWED",
        "evidence": "PR #2067: arbitrage copy renamed Market Disagreement (URL, API, fields unchanged)",
        "next": "merge on green",
    },
    {
        "id": "CW-22",
        "wave": "D",
        "priority": "P2",
        "title": "Fairness bands OD-F4 protocol + market clearing evidence",
        "owner": "fairness_bands_v2 (research)",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S08, S14; #1873",
        "next": "executable protocol; no rewrite of fairness_bands_v2",
    },
    {
        "id": "CW-23",
        "wave": "D",
        "priority": "P2",
        "title": "Roster Construction integration + free-agent startability history",
        "owner": "src/roster_intel/construction.py",
        "state": "NOT_STARTED",
        "evidence": "V1 PRODUCTION_VERIFIED (MD-37); integrations outstanding",
        "next": "consume in Trade Desk / Waiver Advisor without touching rankDerivedValue",
    },
    {
        "id": "CW-24",
        "wave": "D",
        "priority": "P2",
        "title": "Universal Player File + global selected-team context",
        "owner": "canonical identity + profile route",
        "state": "NOT_STARTED",
        "evidence": "#1337, #1334",
        "next": "one profile destination for every player link",
    },
    {
        "id": "CW-25",
        "wave": "D",
        "priority": "P1",
        "title": "Perfect Waivers optimality-claim disclosure audit",
        "owner": "src/trade/perfect_waivers.py + PerfectWaiversPanel",
        "state": "NOT_STARTED",
        "evidence": "MD-36",
        "next": "state objective, horizon, constraints and search scope",
    },
    {
        "id": "CW-26",
        "wave": "D",
        "priority": "P1",
        "title": "Performance defects (draft contract size, BDVM latency, Team Strength, roster %, public league cold load, Activity)",
        "owner": "per-route",
        "state": "MERGED",
        "evidence": "#2079 /draft compact view (-60% raw, -56% gzip), #2081 Team Strength sign-in state, #2084 public-league stale-while-revalidate (bounded 6 h, one abandoned job max, B8 refresh honoured; adversarial review APPROVE) all merged",
        "next": "post-deploy public curl baseline for /overview; snapshot-layer staleness bound (CW-11 note)",
    },
    {
        "id": "CW-27",
        "wave": "D",
        "priority": "P2",
        "title": "Navigation / IA / accessibility remaining proposals",
        "owner": "frontend/lib/nav-model.js + shell",
        "state": "NOT_STARTED",
        "evidence": "UX audit #2051 merged; UX-P01-P10, UX-D07/08/09/11, A11Y-01/03 open",
        "next": "apply directive §12.2 decisions with stable URLs",
    },
    {
        "id": "CW-28",
        "wave": "D",
        "priority": "P2",
        "title": "Game Day UX overhaul",
        "owner": "Game Day page",
        "state": "NOT_STARTED",
        "evidence": "#1335, #789",
        "next": "first screen answers opponent / score / what matters",
    },
    # wave E — mathematical opportunities
    {
        "id": "CW-29",
        "wave": "E",
        "priority": "P0",
        "title": "Missing-as-zero defects + property-based invariant suite",
        "owner": "test-only + archetype owner",
        "state": "MERGED",
        "evidence": "PR #2068 merged (622ad85d): archetype missing feature is unknown, not 0",
        "next": "follow-up: infer_scoring_tags / compute_profile_features missing -> 0",
    },
    {
        "id": "CW-30",
        "wave": "E",
        "priority": "P1",
        "title": "Single-source x0.30 haircut challenger (shadow)",
        "owner": "data_contract single-source haircut",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S02 POC-A",
        "next": "preregistered outcome test; incumbent kept unless it passes",
    },
    {
        "id": "CW-31",
        "wave": "E",
        "priority": "P1",
        "title": "FAAB market refit (point-in-time, winner-censored) + budget shadow price",
        "owner": "faab_engine market layer (research)",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S05, S46",
        "next": "point-in-time refit; out-of-sample bid utility",
    },
    {
        "id": "CW-32",
        "wave": "E",
        "priority": "P1",
        "title": "Value uncertainty band, disagreement map, agreement self-inclusion, uncertainty grammar",
        "owner": "confidence owner + display grammar",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S07, S18, S22, S28, S29, S49",
        "next": "named alternate concept only; never a calibrated interval claim",
    },
    {
        "id": "CW-33",
        "wave": "E",
        "priority": "P2",
        "title": "Roster risk / team strength / posture models",
        "owner": "roster_intel + window",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S11, S32, S33, S37, S41, S43; master-audit W17-F002 residual (classify_team ignores strength for the label) routed here by PR #2082",
        "next": "shadow metrics on the exact lineup engine",
    },
    {
        "id": "CW-34",
        "wave": "E",
        "priority": "P2",
        "title": "Draft/rookie priors, pick-slot forecasts, year-step test, BDVM credibility/hazards",
        "owner": "BDVM + pick_market",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S19, S20, S24, S31, S39",
        "next": "hierarchical priors with knowledge cutoffs",
    },
    {
        "id": "CW-35",
        "wave": "E",
        "priority": "P2",
        "title": "Market / manager evidence: pooling, offer ledger, gates in band units, q identification, title-equity timing, regret layer",
        "owner": "sharp / market ledger / trade research",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S17, S23, S35, S44, S45, S48; #1852",
        "next": "partial pooling + sample-size disclosure",
    },
    {
        "id": "CW-36",
        "wave": "E",
        "priority": "P2",
        "title": "Board constants, Hill validation target, drift forecast, TE++ uplift, record linkage",
        "owner": "canonical board constants (research)",
        "state": "RESEARCH_ONLY",
        "evidence": "AMATH-S21, S34, S40, S42, S50, S56; #898, #1322; master-audit W12-F002 residual (TE SELL skew 0.742 vs target 0.137 in the top 250) routed here by PR #2082",
        "next": "independent validation target (S50) before any promotion; measure the TE++ uplift's role in the TE SELL skew",
    },
    # wave F — platform and remaining portfolio
    {
        "id": "CW-37",
        "wave": "F",
        "priority": "P1",
        "title": "Dependencies / toolchain / security advisories",
        "owner": "requirements*.txt, frontend/package.json, workflows",
        "state": "NOT_STARTED",
        "evidence": "#1467 Node 22; 13 dependabot PRs; #1485 scraper runtime",
        "next": "advisory census; one focused batch per runtime",
    },
    {
        "id": "CW-38",
        "wave": "F",
        "priority": "P2",
        "title": "Draft / auction 2027 readiness",
        "owner": "draft capital + auction room",
        "state": "MERGED",
        "evidence": "PR #2074 merged (5dea846f): MaxBid capped by remaining budget; audit C01 closed",
        "next": "board-level class-retirement gate (#1414)",
    },
    {
        "id": "CW-39",
        "wave": "F",
        "priority": "P3",
        "title": "Product backlog reconciliation (schedule intel, league hub, reports, feeds, portfolio)",
        "owner": "per feature contract",
        "state": "NOT_STARTED",
        "evidence": "#1530 #985 #829 #782-#785 #801 #803 #838-#840 #899 #854",
        "next": "dependency-ready units only; no competing systems",
    },
    {
        "id": "CW-40",
        "wave": "F",
        "priority": "P3",
        "title": "Governance / process / UI-lane records",
        "owner": "coordinator",
        "state": "IMPLEMENTING",
        "evidence": "PR #2082 merged (57611231): 7 unresolved P0 master-audit findings adjudicated on current main -- CLOSED_VERIFIED W03-F001, W07-F001, W08-F001, W10-F002; PARTIAL W12-F002 (-> CW-36), W17-F001 (-> CW-17), W17-F002 (-> CW-33); offline regression tests, adversarial review APPROVE",
        "next": "re-adjudicate the 7 recount-open P1 findings (MASTER-AUDIT-P1-OPEN rows; W20-F005 fix + 5-finding adjudication in flight); then the 71 unresolved P1 findings (41 rotted repros, 18 unsafe, 12 unadjudicated)",
    },
    {
        "id": "CW-41",
        "wave": "F",
        "priority": "P2",
        "title": "Production verification harness defects",
        "owner": "verify-deploy / authenticated verifier",
        "state": "NOT_STARTED",
        "evidence": "#1473 #1362 #1368 #1152 #1153 #1166 #1727",
        "next": "recheck each against current production",
    },
    {
        "id": "CW-42",
        "wave": "-",
        "priority": "-",
        "title": "Owner-paused programs (League Tycoon, DFS, paid analyst feed)",
        "owner": "owner",
        "state": "OWNER_PAUSED",
        "evidence": "MD-12; #1755; #788 cost-gated",
        "next": "none until a new owner decision",
    },
    {
        "id": "CW-43",
        "wave": "F",
        "priority": "P3",
        "title": "Awards / reporting validation (Manager of the Year)",
        "owner": "public_league awards",
        "state": "RESEARCH_ONLY",
        "evidence": "#1513 PARTIAL / NOT PROMOTED",
        "next": "verified formulas before promotion",
    },
    {
        "id": "CW-44",
        "wave": "-",
        "priority": "-",
        "title": "Rejected / blocked research (evidence-backed)",
        "owner": "-",
        "state": "REJECTED",
        "evidence": "AMATH-S51..S53 BLOCKED, S59..S63 REJECT",
        "next": "reconsider only on new evidence",
    },
    {
        "id": "CW-45",
        "wave": "-",
        "priority": "-",
        "title": "Preserve (KEEP) — exact solvers, Game Day state machine, host scorer, Hill family, rookie curve",
        "owner": "-",
        "state": "PRODUCTION_VERIFIED",
        "evidence": "AMATH-S54..S58",
        "next": "regression-protect; no rewrite",
    },
    {
        "id": "CW-46",
        "wave": "C",
        "priority": "P2",
        "title": "Collector operations (scheduled refresh units, box timers)",
        "owner": "scheduled-refresh.yml + deploy/systemd timers",
        "state": "NOT_STARTED",
        "evidence": "research-readiness COL/OPS items",
        "next": "map each collector to a health stamp (CW-11)",
    },
]

CW.append(
    {
        "id": "CW-47",
        "wave": "A",
        "priority": "P0",
        "title": "Confidence owner: withholding a source can CURE Hampel rejections and raise confidence (second deploy blocker)",
        "owner": "src/api/data_contract.py::_lost_evidence_seats + _family_evidence_for_row",
        "state": "PRODUCTION_VERIFIED",
        "evidence": "release train #2072 merged (91b0965c) and deployed (run 3734, 2026-11-06T18:48Z); live featureFlags confidence_cured_rejection_guard enabled/LIVE",
        "next": "none (closed); rollback RISKIT_FEATURE_CONFIDENCE_CURED_REJECTION_GUARD=0",
    }
)

# wave Q — continuous verification / QA directive (owner, 2026-11-06; record
# docs/owner/CONTINUOUS_QA_DIRECTIVE_2026-11-06.md; intake MD-47 .. MD-55).  Phase 6
# (security / data integrity) routes to the existing CW-07 with CW-05 / CW-11 / CW-37.
CW += [
    {
        "id": "CW-48",
        "wave": "Q",
        "priority": "P1",
        "title": "Feature-intent census: requirement -> code -> test -> evidence matrix and per-feature verification states",
        "owner": "docs/audits/remediation_2026-11-06/ (census tooling) + docs/OWNER_FEATURE_INVENTORY.md (intent)",
        "state": "MERGED",
        "evidence": "standard merged #2080; feature census merged #2085 (scripts/feature_census.py; 229 routes, 61 pages, 87 bridge routes, 67 flags, 52 jobs; 38 ranked gaps; review: 0 false negatives / 0 false positives on a 13-item check)",
        "next": "join each surface to its controlling owner requirement and record VERIFIED / PARTIAL / UNVERIFIED with evidence",
    },
    {
        "id": "CW-49",
        "wave": "Q",
        "priority": "P1",
        "title": "Independent mathematical oracles + invariants for consequential calculations; correctness kept separate from predictive skill",
        "owner": "the canonical owner of each calculation (confidence, blend, package model, lineup, FAAB, ROS, BDVM)",
        "state": "INDEPENDENTLY_REVIEWED",
        "evidence": "PR #2089: independent oracles for the package model (14 hand cases + exact-rational sweep, shared by Python and JS) and the weighted count-aware blend median (spec reference, n=1..9); production agrees; even-half rounding cases added after review",
        "next": "merge on green; next: confidence gate axes, lineup solver vs host truth, FAAB curve",
    },
    {
        "id": "CW-50",
        "wave": "Q",
        "priority": "P1",
        "title": "Permanent regression + end-to-end critical journeys (source -> API -> frontend -> action) across league / flag states",
        "owner": "tests/ + frontend/__tests__ + the Playwright regression suite (existing frameworks only)",
        "state": "MERGED",
        "evidence": "#2086 timer/service unit integrity over every deploy timer (264 cases; commented-out installer lines no longer count); #2087 private-route auth regressions; #2082 audit regression tests",
        "next": "critical user journeys from the census; weak-only census items next",
    },
    {
        "id": "CW-51",
        "wave": "Q",
        "priority": "P2",
        "title": "Bounded stress / resilience harness with retained baselines (non-production; explicit ceilings)",
        "owner": "docs/GLOBAL_PERFORMANCE_STANDARD.md budgets + a local / CI harness",
        "state": "NOT_STARTED",
        "evidence": "production read-only latency baseline perf_baseline_2026-11-06.json (CW-26)",
        "next": "isolated-backend concurrency + slow-upstream scenarios with stored baselines; never load production",
    },
    {
        "id": "CW-52",
        "wave": "Q",
        "priority": "P3",
        "title": "Evidence-classified dead code / duplicate logic (PROVEN_UNUSED / FLAGGED_OFF_RETAIN / SHADOW_RESEARCH / SUPERSEDED / UNKNOWN_CONSUMER)",
        "owner": "standard section 6; removal only in small reversible PRs inside file claims",
        "state": "NOT_STARTED",
        "evidence": "-",
        "next": "static + entrypoint + flag + job + dynamic-import census; remove PROVEN_UNUSED only",
    },
    {
        "id": "CW-53",
        "wave": "Q",
        "priority": "P1",
        "title": "Mechanized verification feedback loop: PR verification receipt, test selection, retained fixtures, cost-conscious scheduled checks",
        "owner": ".github/pull_request_template.md + scripts/ci_change_scope.py + docs/AGENT_OPERATING_SYSTEM.md section 3",
        "state": "IMPLEMENTING",
        "evidence": "standard + Agent OS section merged #2080; PR template verification receipt added with the intake reconciliation",
        "next": "assess scheduled deeper checks (drift, security scan, targeted mutation) within the existing scheduling framework",
    },
]

DISCOVERED = [
    (
        "NEW-01",
        "Confidence rises when a withheld vote cures other Hampel rejections (Mahomes)",
        "CW-47",
    ),
    (
        "NEW-02",
        "verify_closure.py 'open' never compares repro output to expected; 37% of repros rotted (fixtures/scripts gone)",
        "CW-40",
    ),
    (
        "NEW-03",
        "#2063 unit lacked SuccessExitStatus for the terminal skip (daily failed-unit alerts)",
        "CW-04",
    ),
    (
        "NEW-04",
        "#2062 service-cgroup sweep would match CI runner cgroups and the Playwright test runner; /proc probe on the event loop",
        "CW-02",
    ),
    ("NEW-05", "data/analyst_ledger.sqlite (INSERT-only) was not in the state backup set", "CW-05"),
    (
        "NEW-06",
        "Week 9 six-model prereg states first kickoff 'Thu 2026-11-05 ~00:15Z' (likely 01:15Z Nov 6); scorer uses per-player kickoff so unaffected",
        "CW-16",
    ),
    (
        "NEW-07",
        "No prospective-IDP evaluation runner exists yet (freeze/receipt/predict only)",
        "CW-16",
    ),
]

# Master-audit P1 findings the 2026-11-06 recount verified STILL OPEN (INVENTORY.md section 3).
# They were recorded in prose only; routed here so none is lost.  W00-F001 is DIR-12 (CW-07,
# public by design per DD-06).  Re-adjudication on current main: CW-40.
MASTER_AUDIT_OPEN_P1 = [
    (
        "W06-F001",
        "Split-identity ghost rows: one player on a resolved row and an unresolved ghost",
        "CW-36",
    ),
    (
        "W10-F003",
        "Rookie recommender panel empty at budget advantage 1.0-3.0 (per-player EV 0)",
        "CW-38",
    ),
    ("W13-F003", "BDVM signal layer saturates at STRONG_SELL (570 of 699 at recount)", "CW-34"),
    ("W20-F005", "Terminal portfolio prices current-year draft picks at zero", "CW-29"),
    (
        "W27-F001",
        "/rankings Edge column carries no IDP signal while /edge labels the same players",
        "CW-32",
    ),
    ("W30-F002", "Playoff odds publish 100%/0% with zero games played", "CW-17"),
    (
        "W30-F008",
        "Hill fit percentile denominator 400 vs serve 500 (same rank up to +25%)",
        "CW-36",
    ),
]


# ── AMATH routing (master audit's own ids and definitions) ───────────────
AMATH_CW = {
    "S01": "CW-15",
    "S02": "CW-30",
    "S03": "CW-17",
    "S04": "CW-17",
    "S05": "CW-31",
    "S06": "CW-18",
    "S07": "CW-32",
    "S08": "CW-22",
    "S09": "CW-18",
    "S10": "CW-21",
    "S11": "CW-33",
    "S12": "CW-19",
    "S13": "CW-04",
    "S14": "CW-22",
    "S15": "CW-29",
    "S16": "CW-17",
    "S17": "CW-35",
    "S18": "CW-32",
    "S19": "CW-34",
    "S20": "CW-34",
    "S21": "CW-36",
    "S22": "CW-32",
    "S23": "CW-35",
    "S24": "CW-34",
    "S25": "CW-17",
    "S26": "CW-18",
    "S27": "CW-10",
    "S28": "CW-32",
    "S29": "CW-32",
    "S30": "CW-17",
    "S31": "CW-34",
    "S32": "CW-33",
    "S33": "CW-33",
    "S34": "CW-36",
    "S35": "CW-35",
    "S36": "CW-13",
    "S37": "CW-33",
    "S38": "CW-29",
    "S39": "CW-34",
    "S40": "CW-36",
    "S41": "CW-33",
    "S42": "CW-36",
    "S43": "CW-33",
    "S44": "CW-35",
    "S45": "CW-35",
    "S46": "CW-31",
    "S47": "CW-17",
    "S48": "CW-35",
    "S49": "CW-32",
    "S50": "CW-36",
    "S51": "CW-44",
    "S52": "CW-44",
    "S53": "CW-44",
    "S54": "CW-45",
    "S55": "CW-45",
    "S56": "CW-45",
    "S57": "CW-45",
    "S58": "CW-45",
    "S59": "CW-44",
    "S60": "CW-44",
    "S61": "CW-44",
    "S62": "CW-44",
    "S63": "CW-44",
}

ISSUE_CW = {
    2060: "CW-02",
    2039: "CW-16",
    1842: "CW-08",
    1807: "CW-38",
    1727: "CW-41",
    1628: "CW-40",
    1622: "CW-26",
    1555: "CW-13",
    1530: "CW-39",
    1529: "CW-38",
    1485: "CW-37",
    1473: "CW-41",
    1467: "CW-37",
    1428: "CW-40",
    1423: "CW-11",
    1422: "CW-40",
    1421: "CW-40",
    1418: "CW-40",
    1415: "CW-09",
    1414: "CW-38",
    1412: "CW-40",
    1409: "CW-46",
    1368: "CW-41",
    1362: "CW-41",
    1340: "CW-26",
    1337: "CW-24",
    1336: "CW-40",
    1335: "CW-28",
    1334: "CW-24",
    1322: "CW-36",
    1214: "CW-40",
    1173: "CW-19",
    1166: "CW-41",
    1157: "CW-26",
    1153: "CW-41",
    1152: "CW-41",
    1065: "CW-11",
    1005: "CW-40",
    985: "CW-39",
    967: "CW-40",
    899: "CW-39",
    898: "CW-36",
    854: "CW-39",
    843: "CW-09",
    842: "CW-09",
    841: "CW-21",
    840: "CW-39",
    839: "CW-39",
    838: "CW-39",
    830: "CW-10",
    829: "CW-39",
    804: "CW-12",
    803: "CW-39",
    802: "CW-08",
    801: "CW-39",
    800: "CW-09",
    792: "CW-19",
    791: "CW-21",
    790: "CW-19",
    789: "CW-28",
    788: "CW-42",
    786: "CW-21",
    785: "CW-39",
    784: "CW-39",
    783: "CW-39",
    782: "CW-39",
    781: "CW-21",
    738: "CW-10",
}

PR_CW = {
    2056: ("CW-37", "needs Node 22 (#1467); rebase + full frontend gates"),
    2055: ("CW-37", "patch bump; rebase + frontend gates"),
    2034: ("CW-37", "actions bump; review pinned SHAs"),
    2033: ("CW-37", "e2e harness bump; E2E gates"),
    1938: (
        "CW-13",
        "value-changing (BDVM in-season); evidence + blast-radius gates before any merge",
    ),
    1920: ("CW-37", "setuptools bump; trivial after rebase"),
    1884: ("CW-13", "research; default OFF; part of the unified comparison"),
    1873: ("CW-22", "read-only on-box evaluation job; stacked on #1833"),
    1852: ("CW-35", "Chase Trade Market maturity; re-review against current main"),
    1755: (
        "CW-42",
        "League Tycoon parking docs; research already rescued to docs/owner/LEAGUE_TYCOON_DEFERRED_IDEAS_PRESERVED_2026-10-16.md — close as superseded once heading collisions are checked",
    ),
    1688: ("CW-37", "sharp bump"),
    1687: ("CW-37", "source-map-js bump"),
    1663: ("CW-37", "fastapi bump; backend gates"),
    1662: ("CW-37", "anthropic SDK bump; check call sites"),
    1661: ("CW-37", "numpy 2.5; numeric regression risk — board diff required"),
    1660: ("CW-37", "vitest 5; frontend gates"),
    1513: ("CW-43", "validation track, not promoted"),
    1508: ("CW-37", "uvicorn bump; server smoke"),
    1506: ("CW-37", "tzdata bump"),
}

# ── findings the 2026-11-06 directive names (both audits) ────────────────
DIRECTIVE_FINDINGS = [
    (
        "DIR-01",
        "Deploy blocked by test_no_confidence_rise_from_the_held_familys_silence (Sonny Styles)",
        "CW-01",
    ),
    (
        "DIR-02",
        "Production Playwright launch failures; KTC/IDPTC/ktcSfTep source failures; served data 33-60h stale",
        "CW-02",
    ),
    ("DIR-03", "/api/health 503 + watchdog failure (#2060)", "CW-02"),
    ("DIR-04", "Week 10 pre-kickoff forecast capture + Week 9 scoring", "CW-03"),
    ("DIR-05", "2027 rookie-auction pre-auction snapshot", "CW-04"),
    (
        "DIR-06",
        "Perishable evidence: KTC trade DB, unselected KTC variants, point-in-time injury/news, freeze receipts",
        "CW-14",
    ),
    ("DIR-07", "Backup root uncertainty, stale writer fallback, restore unproven", "CW-05"),
    ("DIR-08", "Security posture re-validation (loopback bind, ports, headers, banners)", "CW-06"),
    ("DIR-09", "W22-F001 open redirect via backslash in /login?next=", "CW-07"),
    ("DIR-10", "W22-F002 rate limiter trusts X-Forwarded-For", "CW-07"),
    ("DIR-11", "W22-F003 login lacks throttling/lockout", "CW-07"),
    ("DIR-12", "W00-F001 /api/draft-capital unauthenticated and slow", "CW-07"),
    (
        "DIR-13",
        "W18-F003 host vs realized scoring discrepancies (~36% player-weeks, July figure)",
        "CW-08",
    ),
    ("DIR-14", "W13-F001 BDVM missing reception-yardage bands", "CW-08"),
    ("DIR-15", "RPA-F-002 cross-league configuration propagation", "CW-08"),
    ("DIR-16", "RPA-F-003 stale league-scoring snapshot", "CW-08"),
    ("DIR-17", "RPA-F-008 nflverse/IDP scoring defects", "CW-08"),
    ("DIR-18", "IDP defensive-touchdown mapping (idp_def_td)", "CW-08"),
    ("DIR-19", "W08-F003 non-monotonic trade verdict", "CW-09"),
    ("DIR-20", "W08-F005 lost origin ownership on 53/216 picks", "CW-09"),
    ("DIR-21", "W08-F007 raw asset-mode incomparability", "CW-09"),
    (
        "DIR-22",
        "W10-F001 bids ignore remaining budget (the /draft auction MaxBid, not FAAB; DD-13)",
        "CW-38",
    ),
    ("DIR-23", "W11-F003 FAAB saturation", "CW-10"),
    ("DIR-24", "W11-F004 FAAB non-monotonic outputs", "CW-10"),
    ("DIR-25", "W11-F005 FAAB bids depend on UI/filter state", "CW-10"),
    ("DIR-26", "W11-F007 inconsistent FAAB dollar figures", "CW-10"),
    (
        "DIR-27",
        "Expired IDP Show combined acknowledgment + seven overdue rehabilitation reviews",
        "CW-11",
    ),
    ("DIR-28", "IDPTC pick board frozen ~27 days; stale FantasyPros IDP", "CW-11"),
    ("DIR-29", "ESPN injury parsing returns empty; Sharp transaction breaker", "CW-11"),
    ("DIR-30", "IDP Show-IDPTC source lineage (not independent)", "CW-12"),
    ("DIR-31", "Datawrapper/source identifiers in public artifacts", "CW-12"),
    (
        "DIR-32",
        "DLF IDP hold / freshness v2 / Outlier V2 / #1938 / #2006 / Signals IDP comparison",
        "CW-13",
    ),
    ("DIR-33", "Trade Monte Carlo synthetic +/-15% win rate (0/1093 real valueBand)", "CW-19"),
    ("DIR-34", "Finder 'arbitrage' label without convergence evidence", "CW-21"),
    ("DIR-35", "Perfect Waivers 'Proven optimal' wording scope", "CW-25"),
    (
        "DIR-36",
        "/draft ~11.95 MB contract; BDVM ~48 s; Team Strength stuck; roster % timeouts; public league ~44 s cold; Activity payload",
        "CW-26",
    ),
    ("DIR-37", "UX-P01..P10, UX-D07/D08/D09/D11, A11Y-01/A11Y-03", "CW-27"),
    ("DIR-38", "Security advisories (Oct: 111 alerts / 12 critical) — recount", "CW-37"),
    ("DIR-39", "Draft-order historical median-game rule", "CW-38"),
    ("DIR-40", "Rookie Auction Room security / money-correctness findings", "CW-38"),
    ("DIR-41", "Free-agent startability history source", "CW-23"),
    (
        "DIR-42",
        "Streaming gap (dynasty-safe +0.4 vs hindsight) and dynasty protection settings",
        "CW-18",
    ),
    ("DIR-43", "Multi-team War Room remaining validation", "CW-20"),
    ("DIR-44", "Public Trade Advisor launch gate (stays OFF)", "CW-06"),
]

RPA_CATEGORY_CW = {
    "COL": "CW-46",
    "DRF": "CW-38",
    "GOV": "CW-40",
    "LGI": "CW-08",
    "OPS": "CW-41",
    "SRC": "CW-11",
    "TRD": "CW-21",
    "VAL": "CW-13",
}
RPA_OVERRIDES = {"RPA-COL-001": "CW-02"}


def _amath_rows() -> list[dict]:
    path = ROOT / "docs/research/amath/evidence/sitewide_opportunities_merged.json"
    items = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for it in items:
        sid = it["id"].replace("AMATH-", "")
        rows.append(
            {
                "source": "AMATH",
                "id": it["id"],
                "title": it["title"],
                "category": it.get("category"),
                "horizon": it.get("horizon"),
                "cw": AMATH_CW.get(sid),
            }
        )
    return rows


def _rpa_rows() -> list[dict]:
    path = ROOT / "docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for it in d["items"]:
        cat = it["id"].split("-")[1]
        rows.append(
            {
                "source": "RPA-ITEM",
                "id": it["id"],
                "title": it["name"],
                "statusAtSource": f"{it.get('operationalStatus')} / {it.get('evidenceStatus')} (2026-10-25)",
                "cw": RPA_OVERRIDES.get(it["id"], RPA_CATEGORY_CW.get(cat)),
            }
        )
    by_item = {r["id"]: r["cw"] for r in rows}
    for f in d["findings"]:
        srcs = f.get("sourceItemIds") or []
        cw = next((by_item[s] for s in srcs if s in by_item), None)
        overrides = {"RPA-F-002": "CW-08", "RPA-F-003": "CW-08", "RPA-F-008": "CW-08"}
        rows.append(
            {
                "source": "RPA-FINDING",
                "id": f["id"],
                "title": f["title"],
                "severity": f.get("severity"),
                "statusAtSource": f"{f.get('status')} (2026-10-25)",
                "cw": overrides.get(f["id"], cw),
            }
        )
    return rows


def _md_rows() -> list[dict]:
    text = (ROOT / "docs/OWNER_REQUESTED_TODO.md").read_text(encoding="utf-8")
    rows = []
    route = {
        **dict.fromkeys(["MD-1", "MD-2", "MD-28", "MD-37"], "CW-23"),
        **dict.fromkeys(["MD-3", "MD-5", "MD-14", "MD-29"], "CW-13"),
        **dict.fromkeys(["MD-4"], "CW-17"),
        **dict.fromkeys(["MD-6", "MD-13", "MD-24", "MD-27"], "CW-06"),
        **dict.fromkeys(["MD-7", "MD-8", "MD-19", "MD-33"], "CW-18"),
        **dict.fromkeys(["MD-9", "MD-10", "MD-31", "MD-35"], "CW-27"),
        **dict.fromkeys(["MD-11"], "CW-32"),
        **dict.fromkeys(["MD-12"], "CW-42"),
        **dict.fromkeys(["MD-15", "MD-16", "MD-26", "MD-34"], "CW-40"),
        **dict.fromkeys(["MD-17", "MD-18", "MD-20", "MD-30"], "CW-16"),
        **dict.fromkeys(["MD-21", "MD-23"], "CW-12"),
        **dict.fromkeys(["MD-22"], "CW-03"),
        **dict.fromkeys(["MD-25"], "CW-41"),
        **dict.fromkeys(["MD-32"], "CW-36"),
        **dict.fromkeys(["MD-36"], "CW-25"),
        **dict.fromkeys(["MD-38", "MD-39", "MD-44", "MD-45"], "CW-40"),
        **dict.fromkeys(["MD-40"], "CW-01"),
        **dict.fromkeys(["MD-41"], "CW-02"),
        **dict.fromkeys(["MD-42"], "CW-03"),
        **dict.fromkeys(["MD-43"], "CW-05"),
        **dict.fromkeys(["MD-46"], "CW-47"),
        **dict.fromkeys(["MD-47", "MD-54"], "CW-53"),
        **dict.fromkeys(["MD-48", "MD-55"], "CW-48"),
        **dict.fromkeys(["MD-49"], "CW-49"),
        **dict.fromkeys(["MD-50"], "CW-50"),
        **dict.fromkeys(["MD-51"], "CW-51"),
        **dict.fromkeys(["MD-52"], "CW-07"),
        **dict.fromkeys(["MD-53"], "CW-52"),
    }
    for line in text.splitlines():
        m = re.match(r"^\| (MD-\d+) \|(.*)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        rows.append(
            {
                "source": "INTAKE",
                "id": cells[0],
                "title": re.sub(r"\*\*", "", cells[1])[:160],
                "statusAtSource": cells[-1][:160],
                "cw": route.get(cells[0]),
            }
        )
    return rows


def _github_rows() -> list[dict]:
    snap = json.loads((HERE / "github_snapshot.json").read_text(encoding="utf-8"))
    rows = [
        {
            "source": "ISSUE",
            "id": f"#{i['number']}",
            "title": i["title"],
            "cw": ISSUE_CW.get(i["number"]),
        }
        for i in snap["issues"]
    ]
    for p in snap["pulls"]:
        cw, note = PR_CW.get(p["number"], (None, ""))
        rows.append(
            {
                "source": "PR",
                "id": f"#{p['number']}",
                "title": p["title"],
                "cw": cw,
                "disposition": note,
            }
        )
    return rows


def _directive_rows() -> list[dict]:
    return (
        [
            {"source": "DIRECTIVE-2026-11-06", "id": i, "title": t, "cw": cw}
            for i, t, cw in DIRECTIVE_FINDINGS
        ]
        + [
            {"source": "DISCOVERED-2026-11-06", "id": i, "title": t, "cw": cw}
            for i, t, cw in DISCOVERED
        ]
        + [
            {"source": "MASTER-AUDIT-P1-OPEN", "id": i, "title": t, "cw": cw}
            for i, t, cw in MASTER_AUDIT_OPEN_P1
        ]
    )


def _master_audit_summary() -> dict:
    c = json.loads((ROOT / "docs/master-site-audit/closure.json").read_text(encoding="utf-8"))
    return {
        "ledgerGeneratedAt": c["generatedAt"],
        "byClosureAtLedgerDate": dict(Counter(r["closure"] for r in c["records"])),
        "note": "stale ledger; live recount recorded in INVENTORY.md section 3",
    }


def build() -> dict:
    ids = [c["id"] for c in CW]
    dupes = [k for k, v in Counter(ids).items() if v > 1]
    if dupes:
        raise SystemExit(f"duplicate canonical work item ids: {dupes}")
    known = set(ids)
    rows = _directive_rows() + _amath_rows() + _rpa_rows() + _md_rows() + _github_rows()
    unmapped = [r["id"] for r in rows if not r.get("cw")]
    unknown = [r["id"] for r in rows if r.get("cw") and r["cw"] not in known]
    if unmapped or unknown:
        raise SystemExit(f"unmapped={unmapped} unknownCw={unknown}")
    population = Counter(r["source"] for r in rows)
    expected = {"AMATH": 63, "RPA-ITEM": 125, "RPA-FINDING": 39, "ISSUE": 68, "PR": 19}
    for src, n in expected.items():
        if population[src] != n:
            raise SystemExit(f"population {src}: expected {n}, got {population[src]}")
    per_cw = Counter(r["cw"] for r in rows)
    for c in CW:
        c["sourceRowCount"] = per_cw.get(c["id"], 0)
    return {
        "generatedFrom": "repository records + github_snapshot.json (2026-11-06T12:45Z)",
        "population": dict(population),
        "canonicalWorkItems": CW,
        "rows": rows,
        "masterSiteAudit": _master_audit_summary(),
    }


def _cell(text: object) -> str:
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def render(inv: dict) -> str:
    out = [
        "# Remediation inventory — generated tables (2026-11-06)",
        "",
        "Generated by `build_inventory.py`; do not hand-edit. Prose, baseline and blockers: `INVENTORY.md`.",
        "",
        "## Population",
        "",
        "| source | rows |",
        "|---|---:|",
    ]
    out += [f"| {k} | {v} |" for k, v in inv["population"].items()]
    out += [f"| **total** | **{sum(inv['population'].values())}** |", ""]
    out += [
        "## Canonical work items (ranked portfolio)",
        "",
        "| id | wave | pri | state | title | owner | evidence | next | rows |",
        "|---|---|---|---|---|---|---|---|---:|",
    ]
    for c in inv["canonicalWorkItems"]:
        out.append(
            f"| {c['id']} | {c['wave']} | {c['priority']} | {c['state']} | {_cell(c['title'])} | "
            f"{_cell(c['owner'])} | {_cell(c['evidence'])} | {_cell(c['next'])} | {c['sourceRowCount']} |"
        )
    out.append("")
    by_source: dict[str, list[dict]] = {}
    for r in inv["rows"]:
        by_source.setdefault(r["source"], []).append(r)
    for src, rows in by_source.items():
        out += [
            f"## Traceability — {src} ({len(rows)})",
            "",
            "| id | title | cw | status at source / disposition |",
            "|---|---|---|---|",
        ]
        for r in rows:
            extra = r.get("statusAtSource") or r.get("disposition") or r.get("horizon") or ""
            if r.get("category") and src == "AMATH":
                extra = f"{r['category']} / {r.get('horizon')}"
            out.append(
                f"| {_cell(r['id'])} | {_cell(r['title'])[:140]} | {r['cw']} | {_cell(extra)[:120]} |"
            )
        out.append("")
    m = inv["masterSiteAudit"]
    out += [
        "## Master-site audit ledger (stale)",
        "",
        f"Ledger generated {m['ledgerGeneratedAt']}: "
        + ", ".join(f"{k} {v}" for k, v in m["byClosureAtLedgerDate"].items())
        + ". "
        + m["note"]
        + ".",
        "",
    ]
    return "\n".join(out)


def main() -> None:
    import sys

    inv = build()
    outputs = {
        OUT_JSON: json.dumps(inv, indent=1, ensure_ascii=False) + "\n",
        OUT_MD: render(inv),
    }
    if "--check" in sys.argv[1:]:
        stale = [
            p.name
            for p, text in outputs.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text
        ]
        if stale:
            raise SystemExit(f"stale generated outputs (re-run without --check): {stale}")
        print("generated outputs are current")
        return
    for path, text in outputs.items():
        path.write_text(text, encoding="utf-8")
    print(json.dumps(inv["population"]), f"cw={len(inv['canonicalWorkItems'])}")


if __name__ == "__main__":
    main()
