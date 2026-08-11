# Work Claims

**What you are about to work on, recorded before you start.**

One row per piece of work in flight. Add yours in your first commit; set it
`done` in your last. Check it before you begin:

```bash
python scripts/check_work_claims.py --files <paths you will change> --defect <ids>
```

That script also scans remote branches, because claims are voluntary and
branches are evidence.

---

## Open claims

| Claim | Paths | Defect ids | Branch | Status |
|---|---|---|---|---|
| Stage-A audit consolidation, now through B3: Phase A truth re-baseline + verified quick wins, the W30-F008 percentile-coordinate repair (fit/holdout/serving share one coordinate; **no production constant changed**), the /trade multi-team crash hotfix, and model-governance hardening (scope-specific promotion gate, snapshot pinning, complete input fingerprinting, appliedAt/measuredAt lifecycle, registry self-destruction fix), and the B2 curve-routing root cause (W02-F001: the Hill master is now chosen from the rank's coordinate pool, `src/canonical/rank_coordinates.py`, never from the source's registry declaration; **no Hill constant changed, nothing promoted or applied**), and the B3 market-corridor methodology repair (W02-F003: the arbitrary IDP 0.15 hard band cap removed so the corridor's board-derived per-bucket P90 decides again; three residuals tracked as W02-F015/F016/F017 rather than closed into the finding's narrative). Deliberately NOT claiming server.py, frontend/app/api/* bridge routes, or src/api/sleeper_overlay.py — those belong to the live `claude/bridge-timeout-root-cause` session (last push 2026-08-10 22:33Z); verified untouched by path intersection. **Overlap note:** `src/api/data_contract.py` is also touched by `origin/claude/league-intel-projections` and `origin/claude/league-intel-sim`; our change there is the `rank_to_percentile` consumption (~22 lines, B1) plus the B2 curve-routing repair (~120 lines in the Phase 1/1b/1c/1d translation passes and `_curve_for_rank`). Verified non-overlapping by diff: neither branch touches curve routing, the translation flags or the Hill constants — both are +43/-10 in unrelated regions. No shared defect. `frontend/__tests__/draft-logic.test.js` overlaps `origin/claude/rookie-draft-optimizer-386qyu` — same file, different defect (stale phantom imports). | docs/master-site-audit/ (claims-frozen file, re-baseline, W08+W30 evidence), docs/ARCHITECTURE_HANDOFF.md, docs/WORK_CLAIMS.md, docs/BRANCH_DISPOSITION_2026-08-11.md, docs/OWNER_FEATURE_INVENTORY.md, .github/workflows/refit-hill-curves.yml, src/canonical/player_valuation.py, src/canonical/rank_coordinates.py, src/api/data_contract.py (coordinate consumption + curve routing), src/model_registry/*, scripts/fit_hill_curve_percentile.py, tests/{canonical,model_registry,audit,api}/, frontend/__tests__/, frontend/components/waivers/ManualAddDrop.jsx, frontend/app/trade/page.jsx, frontend/lib/trade-logic.js | W31-F001, W11-F006, W08-F004, W30-F008 (coordinate half; challenger NOT promoted), W30-F023 (open, measured), W30-F024 (fixed), W02-F001 (fixed), W02-F001b (fixed), W02-F002 (resolved as a consequence; direction partially remains), W02-F003 (fixed in B3), W02-F015 / W02-F016 / W02-F017 (new, open) | claude/dynasty-audit-consolidation-e75vdy | open |
| Work-claim protocol | docs/WORK_CLAIMS.md, scripts/check_work_claims.py, ASSISTANT_COORDINATION.md | — | claude/work-claim-protocol | done |
| PR-backlog audit: repair of the /edge market-gap display half | frontend/app/edge/page.jsx, frontend/app/edge/edge-columns.jsx, frontend/lib/edge-helpers.js | C09 (S-3) | claude/fix-plan-uex7ug | done |

---

## Why this file exists

On 2026-08-05, five sessions independently solved the **same eight defects**
inside one working window, and in no case did anyone notice until a branch had
already merged:

| Defect | Solved in | And independently in |
|---|---|---|
| Market gap computed in rank space | #740 | #722 **and** #742 — three times |
| `tepMultiplier` default forces the override path | #740 | #722 |
| `_sanitize_next_path` accepts a backslash | #740 | #722 |
| FAAB budget-regime mixing | #740 | #707 |
| ROS absence coerced to 0.0 odds | #740 | #736 |
| Compact view drops `appliedWeight` | #740 | main |
| SSR streaming "duplicate" (#716) | #741 | #747 |

**Eight duplicated repairs across five sessions**, and the market-gap defect was
solved three separate times.

**#742 was pushed AFTER #740 merged.** Its branch does not contain `cef17703`, and
it touches the same three files the merged fix landed in. So this is not a tidy
retrospective about a bad afternoon — the collisions were still happening while
this document was being written.

Every individual collision was resolved sensibly — the better-documented
version was kept each time. The aggregate was not sensible: roughly a third
of a session's output was discarded, and **which version survived came down
to which branch happened to be mergeable first, not which was better.** In
at least one case nobody compared the two implementations at all.

`ASSISTANT_COORDINATION.md` already required branching, and already required
`git pull --ff-only origin main` before starting. Neither prevented any of
this, and it is worth being precise about why: **both rules are about where
your work goes, and none of them tells you what someone else is already
doing.** A branch you never listed is a branch you will duplicate.

So the missing step is not another rule about branching. It is a place to
look, and something worth looking at when you get there.

## The format, and why it is a markdown table

A markdown table is editable in the same commit as the work, readable in a
PR diff, and mergeable by hand. A JSON registry would conflict on every
concurrent claim — which is exactly the failure this is meant to reduce.

Columns:

- **Claim** — one line a human recognises. "FAAB budget regimes", not "fix bug".
- **Paths** — comma-separated files you expect to change. Approximate is fine;
  the point is overlap detection, not a manifest.
- **Defect ids** — `C12`, `W22-F001`, audit finding ids, `—` if none.
- **Branch** — where the work lives, so a collision has somewhere to go.
- **Status** — `open` while in flight, `done` once merged or abandoned.

## What to do when you hit an overlap

Not "stop". Overlap is often legitimate — two people fixing different bugs
in one large file collide on paths and not on meaning.

1. **Read the other branch.** `git diff origin/main..origin/<branch> -- <path>`.
2. **If it is the same defect:** do not write it again. Either take theirs and
   move on, or say concretely why yours should replace it — on the PR, before
   the work, not after.
3. **If it is a different defect in the same file:** carry on, and say so in
   your claim row so the next person does not have to re-derive it.

## Honest limits

- Nothing enforces this. `check_work_claims.py` exits 0 unless you pass
  `--strict`. A gate that cries wolf gets ignored, which is roughly how the
  previous coordination rules failed.
- It only helps if run *before* the work. Run afterwards it is a conflict
  report.
- A session that never fetches sees stale branches. The branch scan is only
  as current as your last `git fetch`.
