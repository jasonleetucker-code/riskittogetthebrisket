# CI checkout cost — separate track from corridor methodology

Tracked apart from the corridor pass deliberately. Nothing here is
changed by this PR; this is the investigation the owner asked for before
anyone touches checkout semantics.

## Measured

| run | when | checkout | job total | outcome |
|---|---|---|---|---|
| #798 final | 17:46 | **34 s** | 11m45s | success |
| #799 attempt 1 | 18:39 | 8m45s | 20m28s | **cancelled at cap** |
| #799 attempt 2 | 19:01 | 8m57s | 20m16s | **cancelled at cap** |
| #799 attempt 3 | 19:33 | 7m40s | 17m46s | success |
| #799 final | 21:45 | **29 s** | 10m47s | success |

`timeout-minutes: 20` (`.github/workflows/pr-validation.yml:58`),
`fetch-depth: 0` (`:65`). Repo is **549 MB** packed; every ~2h refresh
commits ~816 KB × several files plus a ~230 KB archive zip as new blobs,
permanently. 144 archives at time of writing.

**Corrected 2026-08-11.** This section previously read "checkout went 34 s
→ 7–9 min within one hour and stayed there across three consecutive
attempts, so it is not transient." The final run, on a *larger* repo two
hours later, checked out in **29 s** — so the slow window was **episodic,
not a permanent regression**, and three consecutive attempts inside one
hour were not enough to tell the difference. The original wording drew a
durable conclusion from a sample that could not support one.

What survives the correction, and what does not:

* **Survives:** the job has been observed at 20m28s and 20m16s against a
  20-minute cap, so the margin is genuinely thin and two attempts did die
  there. A 7–9 min checkout is reachable, whatever causes it.
* **Does not survive:** "it is not transient", and any planning that
  treats 7–9 min as the current baseline. Observed range is 29 s – 8m57s
  across five runs.
* **Unaffected either way:** the `fetch-depth` analysis below. It turns on
  which consumer needs the merge base, not on how long a clone takes.

The cause of the slow window is **not established** — cold vs. warm
runner cache, GitHub-side variance and repo growth are all consistent with
what was measured, and nothing here distinguishes them. Recording that as
unknown rather than naming a plausible culprit.

## Is `fetch-depth: 0` still justified? Partly — but not for the stated reason

The comment at `:63-64` says:

> Full history so the changed-files ruff gate can diff the PR against its
> base SHA.

**That justification is stale.** The ruff step is now whole-repo
(`python -m ruff check .`, `:136`), and `:112` records the change
explicitly: "Was changed-files-only, and that was right at the time".

But full history is **still load-bearing for a different consumer the
comment does not mention**: `scripts/check_decision_coercions.py:206-211`
runs

```
git diff --name-only {origin/BASE}...HEAD
```

to enforce the coercion ratchet on changed files only. A three-dot diff
needs the **merge base**, so a `fetch-depth: 1` checkout would break it —
and it fails toward *whole-tree enforcement* rather than silently passing
(`:200-205`), so the symptom would be a suddenly-failing gate, not a
silent hole.

So: do not set `fetch-depth: 1`. Do not keep `fetch-depth: 0` on the
strength of the comment either. The requirement is "enough history to
compute the merge base with the PR base", which is much less than "all
5,014 commits and every data blob ever committed".

## Options, evaluated

1. **Shallow checkout alone** — *rejected*. Breaks the coercion ratchet's
   merge-base diff.
2. **Shallow + targeted fetch of the base ref** — *recommended*.
   `fetch-depth: 1` plus an explicit
   `git fetch --depth=N origin ${{ github.base_ref }}` deepened until the
   merge base is reachable. Preserves the only genuine consumer and
   removes most of the clone cost. Needs one verification run against a
   stacked PR, since `:11-20` documents that stacked PRs are supported
   and their base is another work branch.
3. **Raise the timeout** — legitimate as *temporary resilience*, not as
   the fix. It masks growth that continues at ~1 MB/2h. The episodic
   finding above makes this *more* attractive as a stopgap, not less: if
   the slow window is external and recurring, a cap that only fails during
   it is a cap set too close to the worst case.
4. **Move generated/data artifacts out of ordinary history going
   forward** — the real long-term fix, and it collides with a documented
   constraint: W31-F001 records that `data/scrape_state/` and
   `data/sleeper_last_good.json` tracking is deliberate and load-bearing
   (the deploy dispatch keys on those commit subjects). Any proposal must
   preserve that, so the candidates are `exports/archive/*.zip` and the
   regenerated `exports/latest/*` blobs, not `data/`.
5. **Retention strategy** — note the corridor pass now depends on this
   history: `CSVs/site_raw/*` blobs are what made the historical replay
   possible at all. **Do not prune those.** A retention policy must keep
   per-source CSVs and may prune the derived `exports/` artifacts, which
   are reproducible from them.

## Not done

No history rewrite, no deletion of historical evidence — explicitly
out of bounds during the corridor investigation, and §5 above is why that
matters beyond hygiene.
