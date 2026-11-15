# League rules correction, mathematical integrity, product honesty, regression coverage and repository reliability — owner directive, 2026-11-08

**Structured record** of the owner's chat directive "CHASE UPSIDE — NEXT ENGINEERING DIRECTIVE" (2026-11-08;
repository `jasonleetucker-code/riskittogetthebrisket`; production https://chaseupside.com). It is an
implementation directive running inside the existing remediation program (`docs/audits/remediation_2026-11-06/`,
CW-01 … CW-53) and the 2026-11-07 directives (MD-65 … MD-85). It is not a second roadmap. Intake rows MD-86 … MD-96
are in `docs/OWNER_REQUESTED_TODO.md`; authorization is in `docs/EXECUTION_PLAN.md` (same date).

## Owner product decision — `dynasty_main` league rules (durable)

| Setting | Rule |
|---|---|
| Teams | 12 |
| Divisions | 3 |
| Regular season | Weeks 1–14 |
| Playoff teams | 7 |
| Qualification | Seven best teams by OVERALL record |
| Seeding | Best overall record, seeds 1–7 |
| Standings tiebreaker | Most points scored |
| Division champions | A separate financial payout |
| Division playoff advantages | None — no automatic berth, no division-based seeding, no bye |

**What divisions do:** they decide the schedule and the division-champion payout only.

**Required:**
- **A. Playoff odds** come from actual overall records, the remaining schedule, standings and the points-for tiebreaker, with exactly 7 qualifiers. Divisions affect the schedule only.
- **B. Seeding** is by overall record, with points for as the tiebreaker. No head-to-head, division-record or division-champion tiebreakers. Multi-team ties are handled faithfully, and no rule is invented.
- **C. Division-championship odds** are a separate probability from playoff odds. A champion can miss the playoffs and a non-champion can qualify.
- **D. Draft-slot odds** are restored where data and rules permit. Divisions alone never disable them, and the league's actual draft-order settings are checked.
- **E. Not universal:** league-format detection follows each league's configured rules. Where data cannot establish a rule, the limitation is explained.

**Acceptance:** `dynasty_main` calculates legitimate playoff and draft-slot odds despite three divisions, without any nonexistent division advantage.

**Implemented:**
- PR #2149: `config/leagues/playoff_rules.json` is the one owner of these rules, read by `src/public_league/playoff_structure.py::league_playoff_rules`.
- Host evidence: the 2025 winners bracket seeded a four-way 15-11 tie strictly by points for.

## Parts

| Part | Requirement (condensed) | Intake |
|---|---|---|
| 1 Context first | Read the handoff, instructions, architecture, roadmap and testing standards. Inspect PRs #2123–#2148 and the code; trust no handoff line without checking. Confirm CI and verification requirements. Do not repeat completed work. Update existing documents rather than create duplicates. | MD-86 |
| 2 Divisions correction | The rules table above, A–E. | MD-87 |
| 3 Mathematical audit | For every significant quantitative feature: inputs, source, formula or algorithm, assumptions, meaning, edge cases, and an INDEPENDENT verification method; hand-computable scenarios. Priorities: playoffs, divisions, draft slots, Game Day, waivers, FAAB, valuations, trades, Superflex / TEP, IDP, roster construction, market comparisons, Monte Carlo, confidence / calibration, forecast capture. Investigate wrong assumptions, unsupported multipliers, double counting, normalization, weighting, missing or stale data, probability leakage, bad fallbacks, format differences, false precision, and plausible-looking results built on insufficient data. Add sophistication only with clear reason; document unverifiable assumptions. | MD-88 |
| 4 Misleading product language | Review "Market overvalues", "Edge", "STRONG BUY", "61% confidence", "Hit %" and Monte Carlo "clear winner": where each appears, what it measures, whether it is defensible, then fix it and add tests. Keep compelling terminology where justified ("Edge" as a defined model-estimated difference); no relative rank shown as a calibrated probability; no "confidence" without calibration; simulation frequencies are not certainty; no unearned optimality. Use concise labels, not disclaimer walls. | MD-89 |
| 5 Regression coverage | A systematic inventory of major frontend and backend capabilities: intended behavior, inputs and outputs, dependencies, valid failure behavior, coverage and gaps, invariants, user scenarios. Add risk-based integration tests. Cover league-format combinations (Superflex vs standard, TEP, IDP vs offense-only, divisions vs none, playoff formats, missing FAAB, roster sizes, full / incomplete rosters, missing / stale / contradictory data) with no cross-format contamination. No superficial tests. | MD-90 |
| 6 Skipped tests (261) | Classify by reason. Find skips that hide risk. Restore what can safely be restored; remove only truly obsolete or superseded tests. Never raise the skip threshold; keep or strengthen the completeness checks. Report the counts and the remaining high-risk skips. Prioritized by risk, without blocking urgent fixes. | MD-91 |
| 7 Preserve CI improvements | Keep the 8 shards, the completeness proof, run-exactly-once, skip enforcement, serial fallback, release-candidate freshness and receipts. Weaken nothing. Investigate any speed regression. Verify whether the receipt check is ENFORCED by the ruleset; if not, give the owner the exact check name and instructions. Never claim it is enabled without verifying. | MD-92 |
| 8 Local disk without losing work | Inspect every worktree: path, branch, uncommitted and untracked files, unique, unpushed and remote commits, PR state. Classify each as safe / unique / investigate. Remove only what is proven safe; preserve anything potentially valuable. Recommend next storage steps. Explain the empty `frontend/node_modules` in the main checkout without needless installs. | MD-93 |
| 9 Four older PRs | #1884, #1873, #1852, #1513: verify status. Do not close, merge, force-update or overwrite them. Document findings. Distinguish historical PRs from this session's; never report "no open PRs" without a scope. | MD-94 |
| 10 Roadmap | Update existing roadmap and agent documents with discovered bugs, debt and limitations, classified as correctness / regression / performance / reliability / data quality / UX / future. Separate implemented work from ideas. Leave an acceptance test for anything not completed. | MD-95 |
| 11–12 Delivery and handoff | P0 critical correctness → P1 misleading outputs → P2 regression reliability → P3 hygiene. Per change: reproduce, root cause, smallest robust fix, regression tests, full CI, receipt, merge and deploy when safe, verify production. No failing merges, hidden failures, excessive mocking or new skips. Final handoff with sections A–G; `SESSION_HANDOFF.md` updated. | MD-96 |

**Limits carried forward:**
- no owner-reserved methodology or activation changes;
- no spending;
- no security bypasses;
- no branch-protection or required-check changes by agents;
- no unapproved Sleeper writes;
- missing is never zero;
- DFS and League Tycoon stay paused;
- #1938 stays reserved.
