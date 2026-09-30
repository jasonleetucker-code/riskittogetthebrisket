# DFS — dependency-aware roadmap

Linked from Calculator Ideas. **Reordered 2026-09-30 by the owner's Platform / Slate / Contest
integration addendum**: the platform/slate foundation now sits underneath everything, and the
contest profile is its own phase before contest-aware optimization. The earlier P0–P8 labels are
kept in the right-hand column so no requirement lost its home. Requirement IDs:
[`TRACEABILITY.md`](TRACEABILITY.md). UI (Lane 6) advances in every phase.

| Phase | Goal | Was | Position | Gate |
|---|---|---|---|---|
| **P0** Audit & contracts | Mandate + addendum registered, owners mapped, flags, ADRs, zero-loss map | P0 | **DONE** (#1534) | No duplicate engines; every requirement tracked |
| **A** Platform / slate foundation | Canonical slate model; DraftKings + FanDuel adapters with auto-detection; licensed slate feed (SportsDataIO) adapter; CSV import + export; provider × platform × sport capability matrix; scoring/roster contracts | P1 + P2 (rules) | **NOW** — slice 3 | A real slate loads (feed or official CSV) into ONE canonical model; unsupported/unverified combinations fail with named states |
| **B** Contest profile | Quick (preset), exact (editor + payout parser), imported contest; rake/overlay; field size / max entries; contest ↔ slate link | P2 (contests) | **SLICE BUILT** (`claude/dfs-contests`); import + slate link + quick-mode UI remain | Exact economics correct on fixtures; presets never pose as exact contests |
| **C** Base optimizer | Legal lineups, mean-projection baseline, locks/excludes/groups/stacks/exposures, fixed N, export | P1 | **BUILT** (#1534); min/max exposure, conditional rules, salary range, overrides/boosts and sport-neutral team/game stacks (NHL 3-2 / 4-3, NBA game stacks) built on `claude/dfs-multisport`; NHL LINE stacks remain (need line data no licensed feed supplies yet) | Load slate → contest → projections → constraints → N lineups → validate → export, proven end to end |
| **D** Intelligence layer | Projections, distributions, ownership, sportsbook markets, news, podcast evidence, freshness, disagreement | P3 | NEXT (research can run in parallel) | Correct timing, identity, rights, controlled influence |
| **E** Field / contest models | Conditional ownership, opponent lineups, field strength, duplication, ties, exact payout engine (payout/tie math already built in B) | P4 | LATER | Calibration + field-fit reports; labels accurate |
| **F** Contest-aware optimization | Optimal Lineup on the strongest validated method, cash vs GPP, exact-contest EV, joint portfolio, recommended entry count | P5 | LATER / BLOCKED on D+E | Cash vs GPP genuinely differ; zero entries allowed; limitations disclosed |
| **G** Late swap / live | Entry import, locked-slot preservation, swap recommendations, repair, rooting view, updated exports | P6 | **FOUNDATION BUILT** (`claude/dfs-multisport`: DK entries, pins, swaps, export); live scoring, rooting view, cross-entry coordination remain | Locked slots never move |
| **H** Learning / validation | Contest result + field archive, replay, source evaluation, calibration, attribution, drift, champion/challenger | P7 | LATER | Leakage-resistant, reproducible; no self-promotion |
| **P8** Production acceptance | Security/rights, performance, restore, docs, rollout, the owner's core workflow proven in production | P8 | LATER | Owner scenario (addendum §30) passes on the deployed site |

Advanced work is never discarded when the order changes: the MILP, contest economics and
presets already built are reconnected to the canonical slate as Phase A lands (addendum §27).

## Current slice (Phase A, slice 3) — on `claude/dfs-contests`

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
| Automatic slate loading (NFL/NBA/NHL) | No licensed feed key; price/licence unknown | Owner approves a SportsDataIO plan and sets `SPORTSDATAIO_API_KEY` (never committed) |
| MMA automatic slates | No documented licensed DK/FD MMA salary feed | Research continues; official CSV is the supported path |
| Money-ready builds | Rule sets unverified (official pages refuse automated access) | Owner confirms rules or supplies official salary + upload templates |
| Verified exports | No official upload template fixture | Templates in `tests/dfs/fixtures/templates/` |
| Entry-count recommendation | Needs contest EV (D+E+F) and an owner-entered budget | Build D–F; owner enters limits in-app |
| Sportsbook intelligence | No licensed odds feed identified | Research + owner approval of any paid feed |
