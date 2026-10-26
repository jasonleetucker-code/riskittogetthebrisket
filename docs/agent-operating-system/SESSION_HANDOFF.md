# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 overnight (BUILD MODE: no merges, no deploys).** Agent-OS-Receipt `cb64f74c`.

## P0 — do first in the morning
**#1939** pins `scheduled-refresh.yml` to `ubuntu-24.04`. Since 2026-10-25 ~12:00Z the runner image moved to
ubuntu-26.04, where the pinned Python Playwright 1.58.0 cannot launch Chromium. KTC, IDPTC and DraftSharks have
not refreshed while runs report success. Merging restores fresh market values. Other Playwright workflows
(npm Playwright) are unaffected.

## Merged before build mode
#1922 forced-drop replay evidence · #1923 E2E fix · #1924 RIT reconciliation · #1925 docs/tests-only deploy skip ·
#1926 box unit repairs · #1927 LI-5 P3 dormant + deploy-gate locks · #1928 IDP + audit intake.

## Integration queue (recommended order)
| order | PR | what | state |
|---|---|---|---|
| 1 | #1939 | scheduled refresh runner pin (P0) + IDP staleness report | FEATURE_GREEN; needs review |
| 2 | #1933 | unblock CI: pick-refinement withheld-source coverage | approved; CI pending |
| 3 | #1934 | Agent OS usage-efficiency policy + this handoff | approved |
| 4 | #1929 | conditional startup scrape (default OFF) | approved; CI re-run after flag-count fix |
| 5 | #1931 | IDP Lane A scoring manifest + reconciliation | approved |
| 6 | #1936 #1940 #1941 #1943 | IDP Lanes C, B, D, E (research) | FEATURE_GREEN; need review |
| 7 | #1942 | preregistered backtest (stacked on #1940); no candidate advances | FEATURE_GREEN |
| 8 | #1945 | IDP recommendations (Deliverable H) | FEATURE_GREEN |
| 9 | #1935 → #1937 | multi-team invariant tests → defect fixes (stacked) | #1937 IMPLEMENTED_UNVALIDATED |
| 10 | #1944 | LI-5 review follow-ups F-A/F-B/F-C | FEATURE_GREEN |
| owner | #1938 | nflverse scorer fixes (changes BDVM in-season values) | needs owner decision |

## Owner decisions pending
- **Public Waiver Wire scope.** Nothing in the repo authorizes it. Options: (A) promote the unlisted page,
  (B) A plus factual league waiver activity, (C) public recommendations, which crosses the public/private boundary.
- **#1938 BDVM scorer fixes**, with or without the special-teams tackle de-duplication.
- **Cut-ladder name tie-break** (costs up to 12.19 lineup pts/wk), which interacts with `forced_drop_cheapest_legal`.
- **Forced-drop activation.** Recommendation: not yet.
- **IDP Show board swap**, combined board → IDP-only board.
- **2026 as a clean holdout** for `league_fair_value_v1`.
- **17-game re-run.**
- **`SHARP_SMOKE_TOKEN`** (#1727).
- **Lineage census box run.**
- **Backend memory canary** (numbers in `docs/ops/BACKEND_MEMORY_POLICY_2026-10-21.md`).

## Not finished
- **#1842:** propagation matrix + #1843 reconcile (agent running when this was written).
- **Lane E parity/privacy tests:** agent running when this was written.
- **Lane E measure script:** not started.
- **Promotion-readiness audit.** Inputs in `.claude/worktrees/_audit_inputs/` (local, untracked). Assessed so far: the
  19 original + TRD/DRF (19) + LGI (19). Remaining: OPS+GOV (agent running), SRC 7 + VAL 3, collectors 38, then the
  report writer (`docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.md` + `.json`). ONE agent per batch.
- **Injury feed parses 0 of 800 (LGI-016).** ESPN dropped `athlete.id`, so `_parse_espn_payload` skips every entry
  while the shape check passes. A fix must divert derived events to a shadow file and seed the prior silently
  (~274 events would otherwise hit the BDVM events file), the same trap #1926 closed for depth charts.
- **ChatGPT MCP (#1921):** owned by the Codex session; not touched here.
