# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 ~21:50Z.** Agent-OS-Receipt `47a8b19f`. Concurrency limit: four workers, and the coordinator's own
coding counts toward the four (owner 2026-10-26).

## Authorization in force
The owner approved routine merges ("I approve these and all future merges", recorded in `docs/OWNER_REQUESTED_TODO.md`)
and confirmed it after the overnight build mode.

A PR merges only when all of these hold:
- its exact-head required checks are green;
- an independent review covers the exact head. The coordinator's own review does not count, a commit pushed after a
  review needs a delta review, and REQUEST_CHANGES needs a re-review;
- stacked dependencies have merged first;
- the change still holds on top of current `main`. If `main` gained class-B code since the PR's CI base, run the PR's
  tests on a local merge of the two.

Batch merges so each deploy finishes and production is verified. **#1938 is ON HOLD** until the owner approves it
separately, because it changes BDVM scoring. Owner-held flags, activations and methodology changes still need an
explicit owner decision.

## Production
- **Live:** `b3072d2ea`, deployed about 21:05Z and carrying every merge through #1974.
- **Verified on that build:**
  - `/api/health` returns 200 and ok.
  - `backup_health` is now `backup-health.v2` (#1970). `stateBackup` reports `unverifiable` / `permission_denied`,
    because the app user cannot read `/var/backups/riskit-state`. That honest answer is the intended result; the
    backup owner decision is below.
- **#1966 (the NFL Team filter on `/rankings`) is in the live build**, but nobody has looked at it in a signed-in
  browser yet. The built-in browser is not signed in, and agents do not enter passwords.
- **Next deploy:** run `184a9f756` was in progress at 21:50Z, carrying #1977 and #1972 (the earlier queued runs were
  superseded as expected).

## Merged on 2026-10-26 (48 PRs)
- #1925, #1926 (merged ~01:31Z, before this session's integration train)
- #1939, #1933, #1934, #1960, #1955, #1956, #1954, #1950, #1959
- #1929, #1931, #1936, #1940, #1941, #1943, #1944, #1947, #1843, #1935, #1946, #1949
- #1961, #1948, #1952, #1953, #1957, #1958, #1942, #1945
- #1966, #1969, #1965, #1937, #1963, #1968, #1951, #1964, #1962, #1967
- #1975, #1970, #1971, #1973, #1974, #1977, #1972

Superseded and closed: #1533 (by #1950), and #1855, #1895, #1896 (by #1955).

## Open PRs from this session's work
Independent reviews are posted as PR comments; the owner's account cannot approve its own PRs.

| PR | state | next step |
|---|---|---|
| #1981 | **ready**, independently approved | Hotfix for a flaky test on `main`. `tests/parity/test_multi_team_surface_parity_real_board.py` gets a 429 from the global public rate limiter on a fast runner (it failed #1979's CI). Merge it once Validate PR is green. |
| #1979 | draft, approved with nits | Hardens the forecast tripwire. It went red only because of the #1981 flake. After #1981 merges, merge `origin/main` into the branch to get a fresh run, then merge. |
| #1980 | draft, approved at `5a13f4f62`; fix commits since | The Consensus Edge summary no longer reports a crash, partial compare, missing measurement or lost `pipefail` as drift or success. A fix for a no-fresh-measurement false green is in flight, then a delta review. |
| #1976 | draft, approved | Pregame archive alert follow-ups. Its first CI run passed its unit tests but was cancelled at the 120-minute job limit. Re-run in progress. |
| #1978 | draft, stacked on #1976 | Pregame archive durability. Review rounds: round 1 (four lenses) found a non-fail-closed directory flush and a legacy-marker loop. Round 2 found the flush alert wording, the set-aside order, EINVAL and errseq. Round 3 was **blocked**: the errseq retry rebuilt the archive from inputs that can change. Round 4 (a byte-identical rewrite, never a rebuild) is in progress, followed by a fresh review. After #1976 merges, merge `origin/main` into it. |

Other open PRs exist (#1921 Codex MCP, #1884, #1873, #1852, #1755, #1513, Dependabot); this handoff does not cover them.

## Owner decisions pending
- **#1938** (BDVM nflverse scorer fixes). The review recommends shipping it WITH the special-teams de-dup, after a box
  before/after of `run_valuation` plus the alert sweep. There is no flag; it can only be reverted.
- **CI duration.** The hard pytest suite takes 57-95 minutes on most runners, but 117.6 minutes on #1976's run. That run
  was cancelled at the 120-minute limit after its tests passed. The deploy validate job peaked at 99 minutes, against
  the same limit. Decide between:
  - parallelising the suite (pytest-xdist or a split), which is the durable fix and not yet authorized;
  - a timeout raise, which is headroom only and weakens no gate.
- **Dependency vulnerabilities.** GitHub reports 11 on `main` (2 high). Several Dependabot PRs are open.
- **Best-ball sim calibration.** The production fallback runs about 109 points low on team totals (#1963). Neither v1
  nor v2 (#1972, merged as research) passes its gates, and the gates are near-unpassable at these sample sizes.
  Decide whether to caveat the affected surfaces, authorize a v3, and/or size-control the gates.
- **Activations into BDVM:**
  - injury events (#1952, shadow file only);
  - IDP Show projections (#1959, default OFF);
  - the ROS content clock (#1958).
- **Sharp smoke** (#1971):
  - provision `SHARP_SMOKE_TOKEN`;
  - decide whether a missing or rejected token should turn the run red;
  - disable the stale Temporary workflows.
- **Consensus Edge** (#1974):
  - commit a fresh measurement;
  - decide on alerting for red runs and missed days;
  - decide whether to preserve the red-run artifacts. Run 36708000268 **expires 2026-10-30T11:23Z**; 37617836143
    expires 2026-11-06.
- **LI1842 open defects:** 02 TE multiplier, 05, 07 roster cap (possibly taxi accounting), 08 POST leagueKey,
  12 trade_deadline, 13 auction provenance.
  - Also decide the `/api/intel/leads` 503 policy.
- **Backups** (#1970, now visible in prod as `unverifiable`):
  - a status file the app user can read;
  - an off-box mirror;
  - a restore proof that includes the temporal ledger;
  - the unknown dynasty writer to `/home/dynasty/backups/riskit-state`.
- **Earlier, still open:**
  - cut-ladder tie-break; forced-drop activation
  - Public Waiver Wire scope; IDP Show board swap
  - 2026 holdout; 17-game re-run
  - lineage census; memory canary
  - the DFS tick while DFS is paused; retiring the Codex OneDrive orchestrator

## Follow-ups (low)
- **#1970:** `newestBackupPath` exposes a filesystem path on the public health payload. Add a value-vocabulary test for
  backup health.
- **#1979 nit:** `_identity_bearing` treats interned strings as identity-bearing. It is latent, and the failure mode is a
  false red, not a false green.
- **#1981 nits:** the `_Unlimited` docstring names only the advisor limiter.

## Hazards
- **GitHub API quota is shared across every tool and agent.** Poll CI every 5 minutes, not every minute: a 60-second
  watcher over six PRs, plus agents, exhausted it briefly on 2026-10-26.
- **Reviewers who run tests need their own detached worktrees.** Concurrent runs in one shared worktree tripped the
  runtime-data-isolation detector.
- **Usage limits can cut an agent off mid-edit.** Before reusing an interrupted worktree, back up `git diff`, read the
  agent's last tool calls, and confirm no mutation-test revert was left in place.
- **Disk:** about 121 GB free. Many dirty or unpushed worktrees remain, some of them Codex's. Inspect before deleting.
- **Git:** never `git stash`. Commit explicit paths only. Never junction `node_modules`.
- **Squash merges** break PR-branch commit pins. Pin blob ids, not commit SHAs (see #1964).
- **Deploys:** only the newest pending run in the `production-deploy` group survives. Confirm what's live with
  `/api/status .build`.
