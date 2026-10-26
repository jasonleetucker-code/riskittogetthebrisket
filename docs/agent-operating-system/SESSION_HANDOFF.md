# Session handoff (compact, current state only)

Read this instead of re-reading history. Overwrite it at each checkpoint. Verify every line against GitHub before
acting: a previous session's workers are NOT running in a new session.

**As of 2026-10-25 (coordinator session "Fantasy football website consolidation").** Agent-OS-Receipt `cb64f74c`.

## Merged this session
#1922 forced-drop box replay evidence + analysis (do not activate yet) · #1923 E2E safety-net fix (#1918) ·
#1924 RIT-001..088 reconciliation (`docs/owner/RIT_14DAY_AUDIT_RECONCILIATION_2026-10-25.md`) · #1927 LI-5 P3
dormant + deploy-gate locks for `replacement_level_li5_consolidation` and `forced_drop_cheapest_legal` ·
#1928 IDP directive + audit intake.

## Open PRs (next action)
| PR | what | state / next |
|---|---|---|
| #1925 | deploy D-3: skip push deploys for docs/tests-only | green; needs independent review, then merge |
| #1926 | box units: depth charts endpoint (events shadow-only), ledger memory 2G + OOMScoreAdjust, game-day false refusal | fixes pushed `7c3f7b76f`, green; needs re-review, then merge; after deploy check `32/32 OK`, ledger `peakRssMiB` |
| #1929 | D-2 conditional startup scrape (default OFF) | conflict resolved `90536f36c`; CI pending; needs review |
| #1931 | IDP Lane A: manifest + scorer reconciliation (host-native 3,710/3,710; nflverse path 4 defects IDPA-DEFECT-01..04 xfail) | import-guard fix pushed; also blocked by the main-red test fixed in #1933; needs review |
| #1933 | unblock CI: `test_pick_refinement` coverage shortfall from withheld sources | merge first; it unblocks every PR |

## Not finished (resume with at most two subagents, cheapest suitable model)
- IDP program lanes C (market baseline), B (replacement shadow), D (best-ball), E (scoring sensitivity), prereg,
  F/G (backtest), H. Workflow script: session dir `workflows/scripts/idp-valuation-accuracy-*.js` — do NOT relaunch
  as a fan-out; run one lane at a time. Lane A is #1931.
- Promotion-readiness audit: discovery + dedupe done, 19 of ~60 initiatives assessed (all lost to the usage limit);
  resume as ONE agent per category, not 150.
- Multi-team Lane E QA (4 test deliverables, spec `docs/trade/NTEAM_TRADE_ENGINE_SPEC.md` §7) — not started.
- #1842: reconcile #1843 (local unpushed merge in worktree `wf_f91b6085-7b3-1`) + propagation matrix.
- IDP source staleness (`idpShowCombined` withheld; 352 IDP rows freshness-low) — investigation started, no output.
- LI-5 review follow-ups F-A/F-B/F-C (see #1927 review) — not started.

## Owner decisions pending
Public Waiver Wire scope (A promote unlisted page / B + factual activity / C public recommendations — no record
authorizes any) · forced-drop activation (recommendation: not yet) · `SHARP_SMOKE_TOKEN` secret (#1727) · read-only
lineage census box run (window 09:30–13:30 UTC) · backend memory canary (numbers corrected in #1926).
