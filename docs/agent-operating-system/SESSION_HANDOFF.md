# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-26 ~19:00Z.** Agent-OS-Receipt `cb64f74c`. Concurrency limit: four workers (owner 2026-10-26).

## Authorization in force
The owner approved routine merges ("I approve these and all future merges", recorded in `docs/OWNER_REQUESTED_TODO.md`)
and confirmed it after the overnight build mode.

A PR merges only when all of these hold:
- its exact-head required checks are green;
- an independent review is satisfied; the coordinator's own review does not count, and a REQUEST_CHANGES verdict needs a
  re-review;
- stacked dependencies have merged first.

Batch merges so each deploy finishes and production is verified. **#1938 is ON HOLD** until the owner approves it
separately, because it changes BDVM scoring. Owner-held flags, activations and methodology changes still need an
explicit owner decision.

## Production
- **Live:** `6dcb80df0`, deployed 18:25Z, carrying every merge through #1945.
- **Verified after that deploy:**
  - `/api/health` returns 200 and ok;
  - the DLF session reads its true age (0 days, not 96.6), from #1956;
  - waiver-compare returns `charset=utf-8`, from #1954;
  - owner-held flags are OFF, and `conditional_startup_scrape` is OFF.
- **#1939, the refresh pinned to ubuntu-24.04:** verified by run 40325142841. KTC, IDPTC and DraftSharks fetch again,
  and KTC and DraftSharks IDP content changed. IDPTC content is still dated 2026-10-10, which is vendor staleness.
- **Next deploy:** `fa3ee5ea7` was in progress at 18:42Z, carrying #1966 (the NFL Team filter) and later merges.

## Merged on 2026-10-26 (41 PRs)
- #1925, #1926 (merged ~01:31Z, before this session's integration train)
- #1939, #1933, #1934, #1960, #1955, #1956, #1954, #1950, #1959
- #1929, #1931, #1936, #1940, #1941, #1943, #1944, #1947, #1843, #1935, #1946, #1949
- #1961, #1948, #1952, #1953, #1957, #1958, #1942, #1945
- #1966, #1969, #1965, #1937, #1963, #1968, #1951, #1964, #1962, #1967

Superseded and closed: #1533 (by #1950), and #1855, #1895, #1896 (by #1955).

## Open PRs from this session's work (independently reviewed and approved; still drafts, so mark ready, then merge once CI is green)

Independent reviews are posted as PR comments, not formal GitHub approvals: every PR here is authored from the owner's account, which cannot approve its own PR. Other open PRs exist (for example #1921, #1884, #1873, #1852, #1755, #1513 and Dependabot); they are not covered here.

| PR | what |
|---|---|
| #1970 | `/api/health` backup_health reports the state-backup dir honestly; public payload is an allow-list |
| #1971 | Sharp smoke says UNVERIFIABLE loudly; stops committing unchanged records; fixes a gate NameError (12 false reds) |
| #1972 | sim calibration v2 challenger: research and shadow only; failed its gates; LF-safe hashing |
| #1973 | behavioural tripwire: the forecast simulators never read the dynasty contract |
| #1974 | Consensus Edge revalidation: the summary no longer misreports a crashed or skipped run as drift |

## Owner decisions pending
- **#1938** (BDVM nflverse scorer fixes). The review recommends shipping it WITH the special-teams de-dup, after a box
  before/after of `run_valuation` plus the alert sweep. There is no flag; it can only be reverted.
- **Best-ball sim calibration.** The production fallback runs about 109 points low on team totals (#1963). Neither v1
  nor v2 passes its gates (#1972), and the gates are near-unpassable at these sample sizes. Decide whether to caveat the
  affected surfaces, authorize a v3 methodology change, and/or size-control the gates.
- **Activations into BDVM:**
  - injury events (#1952 writes only to a shadow file);
  - IDP Show projections (#1959 switch, default OFF);
  - a ROS content-clock freshness multiplier (#1958).
- **Sharp smoke** (#1971):
  - provision `SHARP_SMOKE_TOKEN` (repo secret plus prod `.env`, then restart);
  - decide whether a missing or rejected token should turn the run red;
  - disable the stale Temporary workflows listed in the PR.
- **Consensus Edge** (#1974):
  - commit a fresh measurement (the current one is from 2026-08-04);
  - decide on alerting for red scheduled runs and missed snapshot days;
  - decide whether to preserve the red-run artifacts. Run 36708000268 expires 10-30; run 37617836143 expires 11-06.
- **LI1842 open defects:** 02 TE multiplier, 05, 07 roster cap (possibly taxi accounting: 24 + 3 = 27), 08 POST
  leagueKey, 12 trade_deadline, 13 auction provenance.
  - Also decide whether `/api/intel/leads` should return 503 for a non-loaded league, or abstain only on fit/value.
- **Backups** (#1970):
  - have the state-backup unit write a readable status file;
  - set up an off-box mirror;
  - run a restore proof that includes the temporal ledger;
  - investigate why a dynasty-run process also writes `/home/dynasty/backups/riskit-state`.
- **Earlier, still open:**
  - cut-ladder tie-break (#1945 X2); forced-drop activation (not yet)
  - Public Waiver Wire scope; IDP Show board swap
  - 2026 holdout; 17-game re-run
  - lineage census box run; backend memory canary
  - the DFS tick while DFS is paused; retiring the Codex OneDrive orchestrator

## Follow-ups
- **Actionable now (#1967 merged):** orphan-marker alert text; wrap the two `unlink` calls; behavioural wiring test. A follow-up PR is in progress.
- **Actionable now (#1962 merged):** use the `STOPPED_COMPLETED` constant; decide whether `unknown` belongs in `STOPPED_SHORT`.

Queued until the parent PR merges:
- **#1973:** trap every `latest_*` host attribute; match aliases by identity.

## Hazards
- **Disk:** about 121 GB free. 44 dirty or unpushed worktrees remain, some of them Codex's. Inspect before deleting.
- **Git:** never `git stash`. Commit explicit paths only. Never junction `node_modules`.
- **Squash merges** break PR-branch commit pins. Pin blob ids, not commit SHAs (see #1964).
- **Deploys:** only the newest pending run in the `production-deploy` group survives. Confirm what's live with
  `/api/status .build`.
