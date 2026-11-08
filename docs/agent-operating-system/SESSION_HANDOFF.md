# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-08 ~11:00Z.** Agent-OS-Receipt `741230de`.

## Mode
- Owner directive 2026-11-08 (league rules, mathematical integrity, product honesty, regression, repository
  reliability): `docs/owner/LEAGUE_RULES_MATH_INTEGRITY_DIRECTIVE_2026-11-08.md`, intake MD-86 … MD-96. It sits
  on top of the four 2026-11-07 directives (MD-65 … MD-85), all inside the remediation program
  (`docs/audits/remediation_2026-11-06/`). Authorization: `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI and independent review); owner gates stay binding.

## Owner product decision recorded (binding)
- `dynasty_main`:
  - Qualifying and seeding: the 7 best OVERALL records qualify, seeded by record; standings ties of any size go to most points scored.
  - Divisions (3) decide the schedule and a separate champion payout only. No berth, no seeding advantage, no bye.
  - One owner: `config/leagues/playoff_rules.json` → `src/public_league/playoff_structure.py::league_playoff_rules`.
  - Host evidence: the 2025 bracket seeded a four-way 15-11 tie strictly by points for.
- **Live Sleeper fact:** `settings.divisions` is 0 today. It was 3 on 2026-10-26; rosters still carry division 1–3 and the league metadata names them. Sleeper's default qualifies division winners when that setting is on, which contradicts the league rule. Keeping it at 0 keeps the host bracket and this site's odds in agreement.

## Delivered this session (2026-11-08)
| PR | What | State |
|---|---|---|
| #2149 | Divisions per league; division-title odds (separate RNG stream, playoff numbers bit-identical); an unrecorded rule withholds qualifying only and keeps draft slots (`regularSeasonOdds`); public section and Power-tab table; "<1%"/">99%" on the chart; honest Power subtitle | MERGED `f8da14ef8`; deploy pending at writing |
| #2150 | Honest copy: market gap, Edge %, BUY · LARGE GAP, model share (uncalibrated), Hit % (prior), Monte Carlo "led in most simulations"; BDVM / Consensus Edge strong labels aligned | MERGED `923f7b4c8`; deploying |
| #2151 | Skipped-test audit: 11 skips resolved (10 now run, 1 obsolete removed), 240 forced-drop draws reclassified (coverage unchanged, precondition-guarded), skip reasons recorded in shard manifests | OPEN, CI running |
| #2152 | Season-simulator odds as whole-percent estimates on the Championship and Trade Deadline tabs (one formatter, `frontend/lib/odds-disclosure.js`) | OPEN, CI + review running |
| (records) | Directive record, MD-86 … MD-96, plan entry, `docs/engineering/MATH_AUDIT_2026-11-08.md`, regenerated feature census, this handoff | this PR |

## Math audit (`docs/engineering/MATH_AUDIT_2026-11-08.md`)
- **F2, the biggest open model issue (not changed):** the best-ball points model is uncalibrated at TEAM level.
  - Simulated weekly means run 117–524 against a realized 241–436. The spread between teams is about 2.3× the real one.
  - Odds therefore sit at 0/100 by Week 8, and projected PF is inflated (Brent: 6,632 projected vs a 6,105 pace).
  - It is RPA-LGI-008, covered by the pre-registered study `docs/league-intelligence/ROS_SCALE_CALIBRATION_*`, and changing the model is owner/gate reserved.
  - Recommendation: add team-level mean/sd checks to that study's gates.
- **Qualifying is robust to F2 today:** the median game doubles the record gap, and an independent realized-score simulation agrees.
- **Verified inert:** `src/waivers/advisor.py` `max(0, int(balance or 0))` changes nothing, because `season_option_value` never reads `faab_remaining`.

## CI (unchanged, nothing weakened)
- PR Validation ~18–20 min; shards 10–16 min each, 8 shards; deploy and RC sharded as recorded on 2026-11-08.
- **Receipt check is NOT enforced.** The `main-protection` ruleset has only `deletion` and `non_fast_forward` rules: no required status checks at all, not even `Validate PR`. Owner action:
  - Settings → Rules → Rulesets → `main-protection` → add **Require status checks to pass** with `Validate PR` and `Receipt check` (source GitHub Actions).
  - **Bypass needed:** automation pushes straight to `main` (github-actions[bot] via `GITHUB_TOKEN` in `scheduled-refresh.yml` and the refit/narratives/sharp workflows; the box deploy keys behind "DLF Fetch (prod)" and "IDP Show Fetch (prod)"). Add those as bypass actors.
  - Then confirm the next scheduled refresh still lands. Deploy dispatch keys on those commits (W31-F001).
- **Skip budget:** `max_skipped` is still 290. After #2151's shards report the real count (about 10), tighten it in `config/ci/test_shards.json`. That file is high-risk scope, so the change runs full CI.

## Machine (2026-11-08)
- **Worktrees:** 94 classified; 43 removed (~114 GB). Free space on C: went from 4.8 GB to 115 GB.
  - 39 were clean and fully pushed.
  - 4 had only local commits, proven already in main (`git merge-tree` against main is a no-op), with verified bundles in `C:\Dev\worktree-preservation-2026-11-08\bundles`.
  - 414 MB of ignored non-cache files (research caches, private census output, test databases) were copied to `C:\Dev\worktree-preservation-2026-11-08\`.
- **Kept (~48, ~135 GB):**
  - 21 with uncommitted or untracked work, incl. Codex `chase-performance` at 26 GB with 2 modified + 1 untracked file;
  - ~26 with commits that exist only locally, mostly squash-merged branches whose remote copies were deleted.
- **Next storage step (owner):** review the 21 dirty worktrees. For the local-commit ones, `git bundle create <file> HEAD --not --remotes` and then `git worktree remove` makes them safe.
- **Main checkout `frontend\node_modules` is empty:** it was wiped on 2026-10-26 (see the memory note on junction deletion). That is not needed unless you run the frontend from the main checkout; then run `cd frontend && npm ci` there. Each worktree runs its own `npm ci` (~20 s).

## Open PRs outside this session (untouched, verified 2026-11-08)
- **Earlier sessions:** #1884 (outlier integrity v2, default OFF), #1873 (package-model ledger, stacked on #1833), #1852 (Trade Market P1+P3) and #1513 (Manager of the Year, validation track) are all OPEN and CONFLICTING, and were not modified.
- **Owner-reserved and other:** #1938 is owner-reserved. #2132 and #2112 are Codex prototypes and docs; #2116 and #1755 are docs; there are also Dependabot PRs.

## Owner decisions pending
- Division-champion tiebreaker: it applies the league's standings rule (points for). Confirm, or name another.
- Keep the Sleeper `divisions` setting at 0 (see above)?
- Make `Validate PR` + `Receipt check` required, with automation bypass.
- Unchanged: #1938; the draft-order record basis (does the median game count? #1712); the F2 calibration path.

## Next dependency-ready units (ranked)
1. Merge #2151 and #2152 when green and reviewed; tighten `max_skipped`; verify production for #2149 / #2150 / #2152 (Power-tab division table, rosPlayoffOdds `divisionOdds`).
2. Forced-drop property coverage: at least N applicable draws per scenario, generated deterministically (#2151 follow-up 0).
3. Format-pair contamination test (one fixture, two leagues; acceptance in the math audit).
4. The remaining ~10 skips: read `skip_reasons` from #2151's shard manifests; three real-Sleeper-cache tests.
5. MD-78 (0.30 haircut challengers, evaluation only), MD-83 (security and backups), `/api/public/league` payload (archives 816 KB, activity 458 KB).

## Hazards
- A `game-day-capture.yml` dry run shares the `production-deploy` group: dispatch it only while no deploy is pending.
- New workflow steps need entries in `config/ci/release_gate_classification.json`.
- Sharding exposes order-dependent tests: fix the isolation, never re-serialize.
- Never "fixes #<open PR>"; never `git stash`; never `git commit -a`. Ruff only via `bash scripts/format_python_changes.sh`.
- Heredocs through the Bash tool can mangle escapes. Write edit scripts to the scratchpad with the Write tool.
