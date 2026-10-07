# DFS — dependency-aware roadmap

Linked from Calculator Ideas. **Reordered 2026-09-30 by the owner's Platform / Slate / Contest
integration addendum**: the platform/slate foundation now sits underneath everything, and the
contest profile is its own phase before contest-aware optimization. The earlier P0–P8 labels are
kept in the right-hand column so no requirement lost its home. Requirement IDs:
[`TRACEABILITY.md`](TRACEABILITY.md). UI (Lane 6) advances in every phase.

> **CURRENT STATUS (2026-10-07, CLEANUP-1):** every slice named below is MERGED to `main` (#1534,
> #1535, #1546, #1547–#1560, #1561 — all 2026-09-30) and its code is in the deployed production
> build. Branch names in the Position column are where each slice was built (historical). The
> evidence labels ("NO EVIDENCE", "WITHIN-MODEL ONLY", "NO DATA") remain true; production `/dfs`
> acceptance (P8) is not verified.

| Phase | Goal | Was | Position | Gate |
|---|---|---|---|---|
| **P0** Audit & contracts | Mandate + addendum registered, owners mapped, flags, ADRs, zero-loss map | P0 | **DONE** (#1534) | No duplicate engines; every requirement tracked |
| **AUTO** Automated data first (permanent owner requirement, 2026-09-30) | Zero manual CSV imports in the primary workflow: automatic slates, salaries, schedule, identity, status, projections, freshness; manual files under *Advanced* | new | **NFL DK+FD SLICE MERGED** #1561 (`519ee6159`; built on `claude/dfs-auto`, ADR-DFS-024, DFS-AUTO-01..24); NBA/NHL LATER, MMA + platform ids + odds BLOCKED | Owner opens `/dfs` on a Sunday and builds a DK NFL Main lineup with nothing downloaded or uploaded |
| **A** Platform / slate foundation | Canonical slate model; DraftKings + FanDuel adapters with auto-detection; licensed slate feed (SportsDataIO) adapter; CSV import + export; provider × platform × sport capability matrix; scoring/roster contracts | P1 + P2 (rules) | Slice 3 MERGED #1535 (`66026851f`); remaining slices NOW *(was "NOW — slice 3")* | A real slate loads (feed or official CSV) into ONE canonical model; unsupported/unverified combinations fail with named states |
| **B** Contest profile | Quick (preset), exact (editor + payout parser), imported contest; rake/overlay; field size / max entries; contest ↔ slate link | P2 (contests) | **SLICE MERGED** #1535 (built on `claude/dfs-contests`; quick/exact/import modes in #1546); import + slate link + quick-mode UI remain | Exact economics correct on fixtures; presets never pose as exact contests |
| **C** Base optimizer | Legal lineups, mean-projection baseline, locks/excludes/groups/stacks/exposures, fixed N, export | P1 | **BUILT** (#1534); min/max exposure, conditional rules, salary range, overrides/boosts and sport-neutral team/game stacks (NHL 3-2 / 4-3, NBA game stacks) MERGED #1546 (built on `claude/dfs-multisport`); NHL LINE stacks remain (need line data no licensed feed supplies yet) | Load slate → contest → projections → constraints → N lineups → validate → export, proven end to end |
| **D** Intelligence layer | Projections, distributions, ownership, sportsbook markets, news, podcast evidence, freshness, disagreement | P3 | **MODELS BUILT, NO EVIDENCE** — ownership baseline + ensemble (DFS-MOD-02), distributions + copula (MOD-03), correlation priors (MOD-04), first connected source: Daily Fantasy Fuel (MOD-12) — merged #1547–#1559; podcast/news extraction still LATER | Correct timing, identity, rights, controlled influence |
| **E** Field / contest models | Conditional ownership, opponent lineups, field strength, duplication, ties, exact payout engine (payout/tie math already built in B) | P4 | **MODELS BUILT, NO EVIDENCE** — field generator (MOD-05), duplication baseline + challenger (MOD-06), contest Monte Carlo with exact ties (MOD-07) — merged #1550/#1551/#1553; not compared with a real field yet | Calibration + field-fit reports; labels accurate |
| **F** Contest-aware optimization | Optimal Lineup on the strongest validated method, cash vs GPP, exact-contest EV, joint portfolio, recommended entry count | P5 | **BUILT, WITHIN-MODEL ONLY** — portfolio optimizer (MOD-08): sample-optimal candidates, EV / log-growth / downside objectives, conservative entry count, paired baseline comparison — merged #1554; no historical evidence it helps | Cash vs GPP genuinely differ; zero entries allowed; limitations disclosed |
| **G** Late swap / live | Entry import, locked-slot preservation, swap recommendations, repair, rooting view, updated exports | P6 | **FOUNDATION MERGED** #1546 (built on `claude/dfs-multisport`: DK entries, pins, swaps, export); live scoring, rooting view, cross-entry coordination remain | Locked slots never move |
| **H** Learning / validation | Contest result + field archive, replay, source evaluation, calibration, attribution, drift, champion/challenger | P7 | **HARNESS BUILT, NO DATA** — point-in-time ledger (MOD-01), chronological backtest with counterfactual payouts (MOD-09), scorecards (MOD-10), champion/challenger gates (MOD-11) — merged #1547/#1556; zero settled contests replayed | Leakage-resistant, reproducible; no self-promotion |
| **P8** Production acceptance | Security/rights, performance, restore, docs, rollout, the owner's core workflow proven in production | P8 | LATER | Owner scenario (addendum §30) passes on the deployed site |

Advanced work is never discarded when the order changes: the MILP, contest economics and
presets already built are reconnected to the canonical slate as Phase A lands (addendum §27).

## Latest slice — zero-upload NFL (phase AUTO) — merged #1561 (`519ee6159`, 2026-09-30); built on `claude/dfs-auto`

- `src/dfs/auto/`: schedule-derived NFL slates for DraftKings and FanDuel, DFF week-pool salaries,
  Sleeper/RotoWire stat lines rescored per platform + DFF as a second family, canonical identity,
  injury withholding, freshness states, time-to-lock cadence, `system:auto` snapshots + PIT ledger.
- `dynasty-dfs-auto-refresh` timer; `GET /api/dfs/auto/slates`, `POST /api/dfs/auto/slates/select`.
- UI: automatic slates first (Main opens by default); manual import under *Advanced*.
- Upload files refused on automatic slates (`PLATFORM_IDS_UNAVAILABLE`) until platform ids have a
  permitted source.

## Earlier slice (Phase A, slice 3) — merged #1535 (`66026851f`, 2026-09-30); built on `claude/dfs-contests`

- Canonical slate model (`src/dfs/slate.py`) that every downstream system reads.
- Platform-file adapters with **auto-detection** of platform, sport and format; explicit
  `CSV_WRONG_PLATFORM` / `UNSUPPORTED_SLATE` / `UNSUPPORTED_FORMAT` states; MMA and Showdown files
  recognised even while their rule sets are unencoded; unknown columns preserved.
- SportsDataIO `DfsSlatesByDate` adapter mapped from the published schema, gated behind a
  default-OFF flag and `SPORTSDATAIO_API_KEY` (not provisioned) — `PROVIDER_UNAVAILABLE` until then.
- Provider capability matrix + source-cost registry served to the UI.
- Contest ↔ slate link.
- UI: detection chip, provider status, and a data-freshness strip that shows unavailable inputs
  as unavailable.

## Blocked, with the exact unblock

| Item | Blocker | Unblock |
|---|---|---|
| Automatic slate loading | **NFL DK+FD now automatic without a feed** (DFS-AUTO); NBA/NHL need a per-sport schedule source; UPLOAD-READY automatic slates need platform ids, which no permitted free source publishes | NBA/NHL: next slice. Upload-ready: owner approves a SportsDataIO plan and sets `SPORTSDATAIO_API_KEY` (never committed) |
| MMA automatic slates | No documented licensed DK/FD MMA salary feed | Research continues; official CSV is the supported path |
| Money-ready builds | Rule sets unverified (official pages refuse automated access) | Owner confirms rules or supplies official salary + upload templates |
| Verified exports | No official upload template fixture | Templates in `tests/dfs/fixtures/templates/` |
| Entry-count recommendation | Needs contest EV (D+E+F) and an owner-entered budget | Build D–F; owner enters limits in-app |
| Sportsbook intelligence | No licensed odds feed identified | Research + owner approval of any paid feed |
