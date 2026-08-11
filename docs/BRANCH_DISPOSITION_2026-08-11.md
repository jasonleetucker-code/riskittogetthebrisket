# Branch disposition — 2026-08-11

Scope: the six open frontend-performance PRs (#758–#763). All six branches predate the
2026-08-05 squash-merge of PR #722 and share **no merge base** with current `main`
(`git merge-base` fails; the branches sit ~4,660 commits from HEAD by ancestry). A naive
merge or wholesale cherry-pick would drag pre-squash history — including stale data
files — into main. **Every disposition below is therefore "re-derive on current HEAD",
never "merge as-is."** Measurements quoted in the PRs were taken pre-squash and must be
re-verified against the current tree before being cited as current.

Owner decision (2026-08-10, recorded during Stage-A planning): absorb only the minimal
#762 fix, and only after independently reproducing its claimed failure on current HEAD;
if the root cause does not reproduce, land the improved diagnostics and keep
investigating. #758–#761 and #763 stay untouched for now with the evidence-based
dispositions below.

| PR | Branch | What it actually contains (verified against the fetched refs) | Disposition |
|---|---|---|---|
| #758 | `claude/site-architecture-design-is7zi9` | Corroborates #747's SSR-duplication finding at 2,400 loads / 0 duplicates on Next 16.2.12; adds `ssr-duplication.spec.js` as a standing invariant; fixes a trade-coverage journey flake; corrects a `loading.jsx` claim. | Re-derive the invariant spec + journey fix as fresh commits during Phase G E2E work. The measurement conclusion (duplication dead) needs no port — it's a finding, not code. |
| #759 | `claude/no-player-data-routes` | Stops 6 non-data routes (incl. `/login`, which fetched a multi-MB contract to render a password box) from mounting the contract-fetching AppShell; keeps `NoPlayerDataAppShell` separate from the `PUBLIC_ONLY` privacy list; audited and rejected `/settings` + `/tools/trade-coverage`. | Re-derive in Phase G (real first-load win). Re-audit the route list against current HEAD first — routes have changed since the branch was cut. |
| #760 | `claude/rankings-board-windowing` | Harness + retraction only. The original FPS harness measured its own loop; the corrected CDP harness (`frontend/scripts/measure-board-fps.mjs`) shows windowing takes the board 22→59.5 FPS. **The windowing implementation itself was reverted uncommitted and exists nowhere.** | Cherry-pick equivalent: re-create the corrected harness script; treat the branch as the measurement mandate. The windowing implementation must be built fresh (Phase G3), using the branch's doc notes as design input. `freezeColumnWidths` (the prerequisite) already landed at HEAD. |
| #761 | `claude/first-load-instrument` | A checkable first-load-JS instrument measuring 641.7 KB raw / 202 KB gz always-loaded from prerendered HTML script tags; supersedes a retracted earlier instrument. | Re-derive the instrument in Phase G; re-measure on current HEAD before quoting any figure. |
| #762 | `claude/bridge-timeout-root-cause` | **ACTIVE — a session pushed 2026-08-10 22:33Z.** Root-cause claim for the rotating E2E flake: dynasty-data bridge 4s idle abort → unguarded disk fallback serves a structurally unstamped snapshot (verified: today's committed snapshot has 1,077 legacy rows, 0 rank stamps) → `buildRows` fail-fast → empty board, sticky 30s via the module-scope contract cache. Five code commits (unstamped-snapshot 503 guard; sleeper-overlay lock `max_wait`; overrides budget 15s→45s with `bridge_timeout` vs `backend_unreachable` labels; dynasty-data 4s→30s + auth 3s→15s + budgets test; missing `/api/health` bridge route) plus `msg.location().url` console capture. Every load-bearing element of the claim verifies against HEAD code; the fix is entirely unmerged. | Per owner decision: independently reproduce the mechanism on current HEAD (requires the running stack), then re-derive the **minimal** fix as fresh commits, coordinating through WORK_CLAIMS with the active session so nothing is overwritten. If reproduction fails, land only the diagnostics (console-capture URL + 503 labels) and continue investigating. Until then its file set (server.py, bridge routes, sleeper_overlay.py) is treated as claimed by that session. |
| #763 | `claude/appshell-palette-index` | Stacked on #761's branch (base ref is `claude/first-load-instrument`). Moves the palette ownership index into the palette: −6.6 KB raw / −2.3 KB gz on every route; `waiver-logic` preloaded by 2 routes instead of 35. | Re-derive after the #761 decision (it stacks on that work). Small, low-risk, real win. |

## Standing rules

1. Never `git merge` or bulk cherry-pick any pre-squash branch into post-squash main
   (ORCHESTRATION §2a three-dot check). Re-derive.
2. Any re-derived change re-runs its measurement on current HEAD; pre-squash figures are
   history, not current truth.
3. #762's caveat, recorded by its own tip commit: raising the dynasty-data budget 4s→30s
   removes CI's only accidental backend-slowness alarm. Any re-derivation must pair the
   budget raise with an explicit backend perf budget or note the regression-visibility loss.
