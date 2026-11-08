# Backend campaign acceptance matrix — owner master implementation directive, 2026-11-08

The one integrated implementation and verification ledger required by §29 of
`docs/owner/BACKEND_MASTER_IMPLEMENTATION_DIRECTIVE_2026-11-08.md`. It lives in the existing remediation folder and
reuses canonical IDs: the P1 ledger (`P1_LEDGER.md`) and the intake rows MD-97 … MD-115. It does not open a second
denominator. A row moves only on evidence. Verification states used below:
- implemented locally / tested locally;
- TESTED_IN_PR / reviewed;
- MERGED / DEPLOYED / VERIFIED_IN_PRODUCTION;
- RESEARCH_COMPLETE_NOT_PROMOTED.

**As of 2026-11-08 ~11:30Z** (campaign start; Phase 0 baseline). Workers active:
- A: team-points calibration evaluation (`claude/team-points-calibration-eval`);
- B: source-ingestion contracts (`claude/source-ingestion-contracts`);
- C: injury attribution and FAAB unknown balance (`claude/injury-attribution-faab-unknown`).

The coordinator handles records, forced-drop coverage, CI and the league-rule checks.

## Phase 0 baseline (verified 2026-11-08)
- **main and production:**
  - production `f8da14ef8` verified with #2149 live: `playoffOdds.divisionOdds` available, recorded rule stamped;
  - #2150 deployed (`923f7b4c8`);
  - #2152 deploy in progress (`464662bdf`);
  - #2151 merged (`486b4da21`, skip budget 10);
  - #2154 merged (`ab3672210`);
  - #2153 records merged (`336f81301`).
- **CI:** PR Validation ~18–20 min, 8 shards, completeness proof; 34,686 collected / 10 skipped / budget 10.
  - Ruleset `main-protection` has only `deletion` + `non_fast_forward` rules, so **no status check is required**.
- **P1 ledger:** 56 CLOSED_VERIFIED / 15 PARTIAL / 10 OPEN / 4 owner decisions (85). The campaign rows below cite their IDs.
- **Open PRs outside the campaign:**
  - #1884, #1873, #1852 and #1513 are conflicting and protected;
  - #1938 is owner-reserved;
  - #2132 and #2112 are frontend-owned and not touched;
  - #2116 and #1755 are docs;
  - there are also Dependabot PRs.

## Matrix
| P | Work item | Root cause (evidence) | Current state | Implementation / PR | Canonical owner | Authorization | Remaining blocker |
|---|---|---|---|---|---|---|---|
| 1 | MD-97 / RPA-LGI-008 | `fallback-constants` points model; simulated team means 117–524 vs realized 241–436, spread about 2.3× (MATH_AUDIT F2) | evaluation infrastructure in progress | worker A: pre-registration, point-in-time evaluation, gates; no served change | `src/ros/playoff_sim.py`, `src/league_intel/sim_calibration.py`, `src/ros_calibration/` | evaluation authorized; promotion gated | owner promotion decision only if a challenger passes |
| 2 | MD-98 / #1938 / IDP scorer parity | nflverse path matched ~91.8% of host player-weeks (~96.4% with #1938) | not started this campaign | taxonomy plus category tests; #1938 prepared for decision | `src/nfl_data/realized_points.py`, `src/league_intel/scorer.py` | research and tests authorized; #1938 merge owner-reserved | owner decision on #1938 |
| 3 | MD-99 / W05-F003, W05-F004 | header probe covers 4 sources; header-only CSV skipped silently; 9 / 27 sources lack a floor | in progress (worker B) | schema, header and population contracts; evidence-derived floors; source-health lane | `src/api/data_contract.py` validation, source CSV readers | authorized | — |
| 4 | MD-100 | no required status checks on main | verified; owner action prepared (`SESSION_HANDOFF.md`) | automated detections where missing | `.github/workflows/*`, `scripts/check_pr_verification_receipt.py`, `scripts/ci_test_shards.py` | detection authorized; rule change owner-only | owner adds required checks with scoped bypass |
| 5 | MD-101 / W24-F001 | 240 forced-drop draws reclassified, not exercised; 3 real-roster tests skip (33 MB cache absent) | skips 261 → 10, budget 10 (#2151 merged) | deterministic applicable draws (coordinator); trimmed real-roster fixture | `tests/trade/test_forced_drop_selection.py`, `scripts/ci_test_shards.py` | authorized | — |
| 6 | MD-102 | blanket division refusal (fixed) | #2149 VERIFIED_IN_PRODUCTION | verification of the remaining questions (median game in draft order, payout tiebreaker, Sleeper setting) | `src/public_league/playoff_structure.py`, `config/leagues/playoff_rules.json`, `src/public_league/draft_order.py` | authorized | owner answers on governance rules not provable from evidence |
| 7 | MD-103 | backup restore never proven (MASTER_CORRECTNESS MD-83) | not started this campaign | backup manifest / checksum validation and a scratch restore drill (needs box access for production) | `deploy/`, backup scripts | authorized; operator steps on the box owner-run | box / operator access |
| 8 | MD-104 | forecast families evaluated piecemeal | not started | extend the existing archives (`forecast_archive`, `game_day_archive`, `pick_forecast_snapshot`) with scorecards | `src/ros/forecast_archive.py` et al. | authorized | outcomes accrue over time |
| 9 | MD-105 | engine read an unknown own balance as the full budget (latent; routes guard) | in progress (worker C) | engine-level unknown state; end-to-end waiver workflow tests | `src/trade/faab_engine.py`, `src/trade/waiver.py`, `src/waivers/` | authorized | — |
| 10 | MD-106 / #1884 | outlier and voting evidence incomplete | not started | reproducible comparisons only | `src/api/data_contract.py` voting, #1884 branch (read-only) | research authorized; promotion gated | gates |
| 11 | MD-107 | fixed synthetic Monte Carlo band | not started | empirical candidates on held-out data, else unavailable | `src/trade/monte_carlo.py` | research authorized | — |
| 12 | MD-108 | vendor auction dollars normalized over different populations | not started | common normalization or an explicit non-comparable state | `src/draft/` | authorized | — |
| 13 | MD-109 | BDVM about 570 / 676 STRONG_SELL | not started | diagnosis plus challenger evaluation | `src/bdvm/market.py` | research authorized; promotion gated | gates |
| 14 | MD-110 / W21-F001 | contract headline classified as injury → 0.9616 discount | in progress (worker C) | classification and attribution only; methodology unchanged | `src/api/injury_impact.py` | authorized (classification) | — |
| 15 | MD-111 | competing team-direction classifiers (disagree on 9 / 12) | not started | canonical schemas; migrate consumers | `src/roster_intel/window.py` (posture owner), team strength owners | authorized | — |
| 16 | MD-112 | decision engines not one system | not started | end-to-end acceptance cases | `src/trade/*` | authorized; public advisor off | — |
| 17 | MD-113 | IDP / two-TE market gaps | not started | league-aware candidates; evidence for open methodology | `src/trade/finder.py`, `src/league_intel/te_premium.py` | authorized (no multipliers) | — |
| 18 | MD-114 | `/api/public/league` about 2.7 MB | not started this campaign | section-targeted additive contracts; authenticated measurements | `src/public_league/public_contract.py`, `server.py` routes | authorized | — |
| 19 | MD-115 | many stale worktrees and PRs | 43 worktrees removed (about 114 GB), 53 preserved; protected PRs untouched | PR dispositions; proven dead code | repo | authorized; protected PRs untouched | owner on protected PRs |

**Rollback (per row):** every PR is a squash commit, reverted with `git revert <sha>`. No campaign row changes
canonical values or activates a flag; any later row that does carries its own pinned before / after comparison.
