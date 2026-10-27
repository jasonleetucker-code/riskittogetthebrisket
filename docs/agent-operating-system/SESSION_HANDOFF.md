# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-27 ~03:50Z.** Agent-OS-Receipt `47a8b19f`. Concurrency limit: four workers. The coordinator's own coding
counts toward the four (`docs/EXECUTION_PLAN.md`, Agent OS §3 "Usage efficiency").

## Authorization in force
**Merges.** Routine merges are approved: "I approve these and all future merges" (`docs/OWNER_REQUESTED_TODO.md`). A PR
merges only when all of these hold:
- its exact-head required checks are green;
- an independent review covers the exact head (the coordinator's own review does not count);
- a commit pushed after a review gets a delta review, and a REQUEST_CHANGES gets a re-review;
- stacked dependencies have merged first;
- the change still holds on current `main` (when `main` gained class-B code since the PR's CI base, run the PR's tests
  on a local merge).

**Holds.** **#1938 is ON HOLD** (it changes BDVM scoring). Owner-held flags, activations and methodology changes still
need an explicit owner decision.

**IDP market directive (owner 2026-10-26).**
- Recorded verbatim in `docs/owner/IDP_MARKET_ACQUISITION_DIRECTIVE_2026-10-26.md` and tracked as intake rows
  IDPM-1..11.
- Authorized in `EXECUTION_PLAN.md` for read-only collection, diagnostics and shadow research only; its §15 list is
  owner-reserved.
- Owner answers: the census comes from the public Sleeper API, and trades before 2026-07-14 get an archive survey only
  (no ingestion without approval, no paid data).

## Production
- **Live:** `a9b0ac920`, carrying every merge through #1980; `/api/health` returns 200 and ok.
- **In flight:** deploy run `bf8eb5ffc` (it includes #1983; running since 01:43Z, so check it is not stuck), with
  `0c4a6f0aa` (#1978) queued behind it.
- **To verify:**
  - once `bf8eb5ffc` or later is live: `/api/health` and `/api/status` `backup_health` are `backup-health.v3`, with `filesystemPaths: "withheld"` and no
    path-like value;
  - once `0c4a6f0aa` or later is live: the pregame-archive alerts behave as #1978 describes.
- **NFL Team filter (#1966):** in the live build, not yet seen in a signed-in browser.

## Merged 2026-10-26..27 (56 PRs)
- #1925, #1926 (~01:31Z, before this session's integration train)
- #1939, #1933, #1934, #1960, #1955, #1956, #1954, #1950, #1959
- #1929, #1931, #1936, #1940, #1941, #1943, #1944, #1947, #1843, #1935, #1946, #1949
- #1961, #1948, #1952, #1953, #1957, #1958, #1942, #1945
- #1966, #1969, #1965, #1937, #1963, #1968, #1951, #1964, #1962, #1967
- #1975, #1970, #1971, #1973, #1974, #1977, #1972, #1981, #1976, #1980, #1979, #1983, #1984, #1986, #1978

Superseded and closed: #1533 (by #1950), and #1855, #1895, #1896 (by #1955).

## Open PRs from this session's work
| PR | state | next step |
|---|---|---|
| #1985 | draft; independently approved at `785bb4a9b` after REQUEST_CHANGES, re-review and delta review | Own-league trade and draft census (IDPM-2). Merge by **squash only** once Validate PR is green (see Hazards). |
| #1982 | draft; this handoff | Delta check, then merge. |

Other open PRs exist (#1921 Codex MCP, #1884, #1873, #1852, #1755, #1513, Dependabot); this handoff does not cover them.

## Census and survey results (IDP market directive, Phase 1)
**#1985 census:**
- **Seasons:** 3, all from public Sleeper: 2024 and 2025 with 10 teams, 2026 with 12. 2024 and 2025 differ from today's
  format on 9 format axes.
- **Trades:**
  - 233 completed (29 / 124 / 80); 54 involve IDP (DL 23, LB 34, DB 24 — a trade can involve several);
  - 26 offense-for-IDP and 8 IDP-for-IDP;
  - 145 include picks; 11 are multi-team; 52 are one-for-one.
- **Priced sample:**
  - only **17** trades are fully priced at trade time by IDP Trade Calculator, and **0** by the canonical value (its
    history is box-only);
  - **0** IDP one-for-one swaps are priced;
  - traded picks are unpriced, because Sleeper records them only by season and round.
- **Reading:** H7 ("sample insufficient") is a real possibility.
- **Drafts:** IDP share is 27.5% in the 2024 startup, 34% in the 2024 rookie draft, 28.6% in the 2025 rookie draft and
  48.8% of picks in the 2026 auction (by dollars: $242 of the $1,131 spent, 21.4%; $1,129 excluding kickers).
- **Pick mismatches:**
  - 2024: 0 after the per-draft replay fix.
  - 2025 round 2 and the round-6/7 pairs: "unexplained by the data fetched" (possibly draft-round or order edits).

**#1986 archive survey (merged):**
- The repo's own git history holds dated vendor snapshots from **2026-03-09**, four months before the floor. That
  includes 19 days of IDPTC, which exists nowhere else.
- Every price archive is blocked by its terms or by cost. The only open dataset (DynastyProcess, GPL-3.0) holds expert
  ranks, not trade prices, and its upstream FantasyPros terms are unreviewed.
- The survey's probes against no-automation terms (KTC, Dynasty Daddy, FantasyCalc) are disclosed in it.

## Owner decisions pending
- **Survey decisions D1–D6** (`docs/market_trades/HISTORICAL_PRICE_ARCHIVE_SURVEY_2026-10-27.md` §5):
  - D1: backfill pre-floor vendor history from git history;
  - D2: how to grade pre-floor trades;
  - D3: whether to ask vendors for permission;
  - D4: IDP before March;
  - D5: the DynastyProcess id map;
  - D6: Wayback as private research data.
  - FantasyCalc's current terms bear on the live pipeline's posture; the survey takes no position on compliance. Decide
    D1 alongside that question.
- **#1985 history.** Commit `c95390a98` holds a re-identifiable per-team table and stays reachable through
  `refs/pull/1985/head` in this public repo. Removing it needs an owner-approved history rewrite.
- **Phase 2 (IDPM-4).** The preregistration for H1–H7 is to be drafted from the census numbers. No model is fitted
  before it is frozen.
- **The rest of W22-F005.** `/api/health` (`startupChecks`) and `/api/status` (`data_runtime`, `rankHistoryCoverage`,
  `playerctxHistoryCoverage`) still serve host paths anonymously. Deploy verification reads those payloads.
- **CI duration.** The hard suite took 57–95 min on most runs. One run (40382459009) took 117.6 min and was cancelled at
  the 120-minute limit after passing; the deploy validate job peaked at 99.2 min. Options: parallelize the suite
  (durable), or raise the timeout (headroom).
- **Dependency vulnerabilities:** 11 on `main` (2 high); Dependabot PRs are open.
- **#1938** (BDVM nflverse scorer fixes): the review recommends shipping it with the special-teams de-dup, after a box
  before/after.
- **Sim calibration (#1963, #1972):** the fallback runs about 109 points low, and neither v1 nor v2 passes. Decide on
  caveat / v3 / gate sizing. Championship probability is uncalibrated, so it may not justify acquisition premiums
  (IDPM-10).
- **Activations into BDVM:** injury events (#1952), IDP Show (#1959), ROS content clock (#1958).
- **Sharp smoke (#1971):** provision `SHARP_SMOKE_TOKEN`; decide whether a missing token should turn the run red.
- **Consensus Edge:** a fresh measurement, alerting, and red-run artifacts. Run 36708000268 **expires 2026-10-30T11:23Z**.
- **LI1842 open defects** 02, 05, 07, 08, 12, 13, plus the `/api/intel/leads` 503 policy.
- **Backups (#1970):**
  - production reports `stateBackup` as unverifiable / permission_denied;
  - decide on a readable status file, an off-box mirror, a restore proof, and who the unknown dynasty writer is.
- **Earlier, still open:** cut-ladder tie-break; forced-drop activation; Public Waiver Wire scope; IDP Show board swap;
  2026 holdout; 17-game re-run; lineage census; memory canary; DFS tick; retiring the Codex OneDrive orchestrator.

## Follow-ups (low)
- **#1978:**
  - Out of season the stale alert ranks "marker not updating" ahead of "collector not running".
  - Two guards are unpinned: the stamp unlink retried every pass, and the future-mtime guard.
  - An EROFS or immutable stamp warns every tick and is not in the list of disclosed limits.
- **#1985:**
  - The disclosure refusal misses integer-keyed maps under non-participant keys (`rosterTrades: {"1": 3}`).
  - It also misses the `o<rid>` pick grammar.
- **#1980:**
  - The §4 paragraph lists two result lines, not three.
  - The drift message omits a no-fresh horizon.
  - `continue-on-error` on the compare step is unpinned.
- **#1979:** `_identity_bearing` treats interned strings as identity-bearing; this is latent and fails closed.
- **#1981:** the `_Unlimited` docstring names only the advisor limiter.

## Hazards
- **GitHub API quota is shared.** Poll CI every 5 minutes with one batched `gh pr list`, never per-PR every minute.
- **Reviewers who run tests need their own detached worktrees.** `git worktree remove` on Windows can leave an empty
  directory; check that it is empty, then delete it.
- **Usage limits and plan mode can stop an agent mid-edit.**
  - Before reusing a worktree, back up `git diff` and read the agent's last tool calls.
  - Check that no mutation revert is left behind.
  - Commit the preserved work only after re-running the gates.
- **Squash merges only for #1985.** The repo also allows merge-commit and rebase merges, either of which would put
  `c95390a98` into `main`. The merge helper uses `--squash`.
- **Flaky public-endpoint tests.** Any test making many public calls must patch `rate_limit.should_rate_limit`
  (pattern in `tests/parity/surface_harness.py`).
- **Disk:** about 93 GB free (81% of 476 GB), after the 2026-10-26 cleanup of merged, clean, pushed worktrees.
- **Git:** never `git stash`; commit explicit paths only; never junction `node_modules`.
- **Squash merges break PR-branch commit pins.** Pin blob ids, not commit SHAs (see #1964).
- **Deploys:** only the newest pending run in the `production-deploy` group survives. Confirm what is live with
  `/api/status .build`.
