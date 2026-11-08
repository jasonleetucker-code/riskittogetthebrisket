# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-11-08 ~13:10Z.** Agent-OS-Receipt `741230de`.

## Mode
- **Owner master implementation directive 2026-11-08 (backend campaign):** `docs/owner/BACKEND_MASTER_IMPLEMENTATION_DIRECTIVE_2026-11-08.md`, intake MD-97 … MD-115.
  - Acceptance matrix, current per priority: `docs/audits/remediation_2026-11-06/BACKEND_CAMPAIGN_LEDGER_2026-11-08.md`.
  - **ABSOLUTE FRONTEND EXCLUSION:** frontend needs go to `docs/ui/BACKEND_API_HANDOFF.md`.
  - At most 4 editing workers, including the coordinator.
- Earlier 2026-11-08 directive (league rules, MD-86 … MD-96) and the 2026-11-07 directives remain in force. Authorization: `docs/EXECUTION_PLAN.md`.
- Standing permission to merge anything ready (green CI and independent review); owner gates stay binding.

## Production
- `486b4da21`, verified: #2149 division odds live; deploy gate 34,701 tests, 10 skips, budget 10.
- A deploy of `73320356e` is pending (#2156, #2157, #2158, #2162). Deploys queue behind PR CI on GitHub Free's 20-job limit.

## Merged today in the campaign
| PR | What |
|---|---|
| #2155 | campaign records |
| #2156 | forced-drop sweeps run their full applicable draw targets |
| #2157 | receipt check flags protected methodology files |
| #2158 | division-title tiebreaker withheld (ties reported); draft-order basis provisional |
| #2162 | scoring-parity taxonomy + #1938 brief |

Earlier today: #2149 – #2154.

## Open campaign PRs (all independently reviewed, review fixes pushed, CI running)
| PR | State / next step |
|---|---|
| #2159 | ingestion contracts (W05-F003 / F004). The skip budget caught an 11th skip; the test was restored to assert the property (`dd7deaac2`). Merge when green. |
| #2160 | injury attribution (W21-F001) + FAAB unknown balance + publish-layer bid nulling. Merge when green, **before #2165**. |
| #2165 | waiver end-to-end tests. After #2160 merges: merge main into the branch, then flip W-1/W-2 (and W-3: an overspent balance is now known $0 in advisor / streaming) from strict xfail to plain tests. W-4 stays: streaming lists IDP in offense-only leagues, and needs a fix. |
| #2161 | team-points calibration evaluation; no challenger passes. Merge when green. |
| #2163 | BDVM signal diagnosis (no skill; scale mismatch); pbp guard fixed. Merge when green. |
| #2164 | vendor normalization (W10-F004). Merge when green. |
| #2166 | team semantics census + equity owner + concept stamps. Merge when green. |
| #2167 | trade decision-system tests (2 strict-xfail findings). Merge when green. |

Every open PR's worktree is `C:\Users\jason\code\rib-*` (ingest, injury, waivere2e, teamcal, bdvmsig, rookiemkt, teamsem, tradee2e).

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
1. Merge the open PRs in the order above; verify production after the next deploy (division tie fields; Terminal equity; injury discounts).
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
