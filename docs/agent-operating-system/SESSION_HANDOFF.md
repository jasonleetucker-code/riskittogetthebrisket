# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-08 ~14:20Z.** Agent-OS-Receipt `741230de`.

## Mode
- **Owner master implementation directive 2026-11-08 (backend campaign):** `docs/owner/BACKEND_MASTER_IMPLEMENTATION_DIRECTIVE_2026-11-08.md`, intake MD-97 … MD-115.
  - Acceptance matrix, current per priority: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
  - **ABSOLUTE FRONTEND EXCLUSION:** frontend needs go to `docs/ui/BACKEND_API_HANDOFF.md`.
  - At most 4 editing workers, including the coordinator.
- Earlier 2026-11-08 directive (league rules, MD-86 … MD-96) and the 2026-11-07 directives remain in force. Authorization: `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI and independent review); owner gates stay binding.

## Production
- Production `73320356e`, verified at 14:16Z: division-tie fields live (`tiebreakerStatus: unconfirmed`; Brent 64% outright / 36% tied with Jason).
- In-flight deploys:
  - `b48ebe598`: #2159, #2160, #2161, #2163, #2164, #2167.
  - `54adf51bd`: #2165, #2166.
- Production verification of those two deploys is the next unit.

## Campaign PRs: all merged 2026-11-08 (independently reviewed; exact-tree CI green; skip budget 10 held)
| PR | SHA | What |
|---|---|---|
| #2155 | `3602f31f6` | campaign records |
| #2156 | `658ca7d17` | forced-drop sweeps at full applicable targets |
| #2157 | `e239245c0` | receipt check flags protected methodology files |
| #2158 | `b6878891e` | division-title tiebreaker withheld; draft basis provisional |
| #2159 | `4d3614901` | ingestion contracts, W05-F003 / F004 |
| #2160 | `683bcf8f0` | injury attribution W21-F001 + FAAB unknown balance + publish-layer nulling |
| #2161 | `367ce5da3` | team-points calibration evaluation (no challenger passes) |
| #2162 | `73320356e` | scoring-parity taxonomy + #1938 brief |
| #2163 | `bad5d61fd` | BDVM signal diagnosis (no skill; scale mismatch) |
| #2164 | `b48ebe598` | vendor normalization W10-F004 |
| #2165 | `06d535b81` | waiver end-to-end tests (W-1 … W-3 fixed; W-4 open) |
| #2166 | `54adf51bd` | team-semantics census + equity owner |
| #2167 | `5c4b12c20` | trade end-to-end tests (2 strict-xfail findings) |
| #2168 | `c022e58fa` | checkpoint records |

Per-priority state: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`. #2159, #2160, #2161, #2163, #2164 and #2166 are now MERGED.

## Owner decisions (cannot be resolved under delegated authority)
- **Best-ball playoff odds:** activate `playoff_ros_counted_once`, or approve a new pre-registered study; the incumbent is overconfident (#2161).
- **#1938:** merge decision; brief in `docs/league-intelligence/SCORING_PARITY_TAXONOMY_2026-11-08.md`.
- **Division payout tiebreaker:** what breaks a division-title tie? Until stated, ties are reported.
- **Draft order:** do median-game wins count (#1712)?
- **BDVM:** anchor and γ choice; real projection sources before any signal change (#2163).
- **Required checks:** make `Validate PR` + `Receipt check` required on `main-protection`, with bypass for github-actions[bot] and the box deploy keys ("DLF Fetch (prod)", "IDP Show Fetch (prod)"). Then confirm the next scheduled refresh still lands.
- **Team-direction vocabulary:** public naming before consolidation (#2166).
- **Local machine:** review 21 dirty and about 26 local-commit worktrees. Bundles and preserved files are in `C:\Dev\worktree-preservation-2026-11-08\`.

## Next dependency-ready units (ranked)
1. Verify production after deploys `b48ebe598` / `54adf51bd` land (Terminal equity block, injury discounts, vendor comparable fields, ingest health).
2. Fix PR for the #2167 findings: unpriced player `value: 0` in simulate / analyze asset records → null; suggestions publishes `metadata.pickGeneration`. Flip its xfails.
3. Fix W-4: streaming lists IDP in offense-only leagues.
4. MD-104 forecast scorecards; MD-106 outlier / voting comparisons (#1884 read-only); MD-107 trade uncertainty; MD-113 IDP / TE; MD-114 payload section contracts.
5. Trimmed real-roster fixture for the 3 remaining cache skips; surface the restore-proof result in `backup_health`.

## Hazards
- Strict xfails in tests-only PRs flip when the matching fix lands: merge the fix first, then flip the markers on the test PR.
- `config/weights/`, `src/api/data_contract.py`, `config/sources/` and others are protected. A receipt touching them needs a `Methodology authorization:` line.
- A worker's shell heredoc can turn `"\n"` into a line break (seen on #2159); check that changed files parse.
- A `game-day-capture.yml` dry run shares the `production-deploy` group.
- Never `git stash`; never `git commit -a`; Ruff only via `bash scripts/format_python_changes.sh`; never `--write-baseline` on the coercion gate.
