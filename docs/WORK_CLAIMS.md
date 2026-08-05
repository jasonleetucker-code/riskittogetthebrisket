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
