# #948 — the smoke-commit reduction is an OBSERVATION, not a merge claim

**#948 merged `9e83509607736f0419dddf3ac00da4110b569f6b`, 2026-08-20 ~07:45 UTC.**
Integration record, opened at merge.

#948's design intent is that `verify-sharp-production.yml` writes
`data/ops/sharp-production-smoke.json` **on state change or day rollover** rather
than once per run, taking `main` from tens of bot commits a day to ≤ 1.

**That result is not claimed here, and merging did not establish it.** A design
that should reduce commits and a measured reduction are different statements, and
the PR itself said so ("Not claimed, pending a real run"). This file exists so the
later measurement has a fixed baseline to be measured against, instead of being
recalled approximately.

## Baseline — measured at merge, before any post-merge run

Window: **2026-08-19T07:45Z → 2026-08-20T07:45Z** (the 24 h ending at merge).
Counted on `origin/main` by commit subject `chore(ops): record Sharp production smoke`.

| quantity | value |
|---|---|
| smoke commits in the 24 h window | **48** |
| first / last in window | 2026-08-19T09:45:09Z / 2026-08-20T07:15:09Z |
| mean interval | ~27 min |
| design target after #948 | **≤ 1 / day** |

Reproduce exactly:

```bash
git log origin/main --since="2026-08-19T07:45:00Z" --until="2026-08-20T07:45:00Z" \
  --pretty='%cI %s' | grep -c "record Sharp production smoke"
```

(#948's own audit reported 42 of 66 bot commits over its 24 h window. The two
numbers are independent measurements over different windows and agree in
magnitude; neither supersedes the other.)

## What the follow-up must establish

Not "the number went down" — that is also what a **broken or disabled workflow**
looks like, and #948 deliberately made silence meaningful (0 commits is the signal
that the workflow stopped). So the observation needs both halves:

1. **Volume fell** — re-run the command above over a full post-merge 24 h window.
2. **The workflow still ran** — `verify-sharp-production.yml` runs are present and
   green across that window, and `lastObservedOn` in
   `data/ops/sharp-production-smoke.json` advanced even on days the file was not
   committed. Volume alone cannot distinguish success from the workflow dying.

Second half first if they disagree. A quiet workflow is not a fixed one — the same
distinction §7 of the #946 closure record draws between *unverifiable* and *passing*.

## Status

`OBSERVATION OPEN` — earliest meaningful read is **2026-08-21T07:45Z**.
Nothing about the ≤ 1/day result may be reported as achieved before then.
