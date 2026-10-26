# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 ~11:40Z.** Agent-OS-Receipt `cb64f74c`. Concurrency limit: four workers (owner 2026-10-26).

## Done this session
- **#1939 MERGED** (squash `6eddc569f`, 11:33Z), after an independent review (APPROVE_WITH_NITS) with green
  exact-head checks; main movement BENIGN_AUTOMATION_MOVE. It pins `scheduled-refresh.yml` to ubuntu-24.04.
  - Deploy Production run 40315867455 was in progress at 11:36Z.
  - **Still to verify** on the first scheduled refresh after the merge (about 12:42Z):
    - the job runs on the 24.04 image, with no Chromium warning;
    - the `_last_success` stamps for `ktc*`, `idpTradeCalc` and `draftSharks*` move past 2026-10-25T12:06Z;
    - separately, `lastContentChange` advances. It should NOT advance for IDPTC, whose vendor page still says 10/10.
- **#1950 (draft):** auction Phase 2 merged with main (branch `claude/auction-rehearsal-rebase`, head `d557f3f4b`).
  - Tests: 404 passed locally, 377 on the CI-pinned stack, 54 vitest.
  - The official gate stays OFF.
  - Supersedes #1533. Do not close #1533 until #1950 is reviewed.
- **#1951 (draft, stacked on #1948):** repairs LI1842 defects 01, 03, 04, 06, 09, 10 and 11 (head `24052113b`).
  - Tests: 607 passed + 6 xfail; 209 passed; 120 vitest.
  - Defects 02, 05, 07, 08, 12 and 13 stay strict xfail, pending owner or design decisions.
- **#1934:** concurrency limit raised to four workers in the Agent OS, `ASSISTANT_COORDINATION.md` and `EXECUTION_PLAN.md`.

## Running (subagents)
| task | where | output |
|---|---|---|
| Injury-feed parser fix, shadow-safe | own worktree, branch `claude/injury-feed-parser-fix` | draft PR |
| Audit OPS+GOV (20) | read-only | `_audit_inputs/assessed_OPS_GOV.json` |
| Audit SRC+VAL remainder (10) | read-only | `_audit_inputs/assessed_SRC_VAL.json` |
| Independent security review of #1950 | read-only | verdict |

The audit inputs live in `.claude/worktrees/_audit_inputs/`, which is local and untracked. Assessed so far: the 19
original items (in the `alreadyAssessed` lists of `cat_*.json`), TRD/DRF (19) and LGI (19). Still to do after the two
running batches: collectors (38, in two batches), then the synthesis writer, which produces
`docs/audits/RESEARCH_PROMOTION_READINESS_AUDIT_2026-10-25.md` + `.json`.

## Integration queue (all checks green unless noted; none reviewed)
- **Stand-alone, base main:** #1933, #1934 (CI pending after the push), #1929, #1931, #1936, #1940, #1941, #1943, #1945,
  #1944, #1947, #1843, #1950.
- **Stacked:**
  - #1942 on #1940
  - #1937 / #1946 / #1949 on #1935
  - #1938 on #1931 (needs an owner decision; it changes BDVM)
  - #1951 on #1948
- **Codex-owned:** #1921 (ChatGPT MCP), not touched here.

## Owner decisions pending
- **#1938 BDVM scorer fixes**, with or without the special-teams tackle de-duplication.
- **Injury events into BDVM.** Once the parser fix lands, events go to a shadow file only.
- **LI1842 open defects** 02 (TE multiplier), 05, 07 (roster cap), 08 (POST leagueKey), 12 (trade_deadline),
  13 (auction provenance).
- **Cut-ladder name tie-break**, and forced-drop activation (recommendation: not yet).
- **Public Waiver Wire scope**, options A/B/C.
- **IDP Show board swap**, the 2026 holdout, the 17-game re-run, `SHARP_SMOKE_TOKEN`, the lineage census box run,
  and the backend memory canary.

## Hazards
- **The local disk is full**, with about 1.9 GB free on C:. Agents have hit ENOSPC. Nearly 100 worktrees exist,
  including Codex ones. Do not delete any without inspecting them; that needs the owner's or the owning session's say.
- **Never `git stash`.** The stash stack is shared across worktrees. Commit explicit paths only.
