# DFS — dependency-aware roadmap

Linked from Calculator Ideas. Phases are ordering, not permission to drop later scope; UI (Lane 6)
advances in every phase. Requirement IDs: [`TRACEABILITY.md`](TRACEABILITY.md).

| Phase | Goal | Position | Gate |
|---|---|---|---|
| **P0** Audit & contracts | Mandate registered, owners mapped, flags, ADRs, zero-loss map | **DONE on branch** | No duplicate engines; every requirement tracked |
| **P1** Real end-to-end baseline | `/dfs`, context, rules, owner file imports, player table, controls, MILP, saved builds, export | **NOW — slice built**, blocked on rule/template verification for money mode | Legal lineup + provenance + valid platform file, no fake data |
| **P2** Multi-sport / multi-platform construction | NBA, NHL, MMA classic; Showdown/MVP; contest & payout editor; conditional rules; presets; CLI | **NEXT** — NHL/NBA before their Oct openers | Per-combination rule/roster/export fixtures pass |
| **P3** Fresh information & evidence | Source research batches, connectors, background jobs, event-driven refresh, identity via `src/identity/`, podcast pipeline, evidence search | **NEXT** (research can start in parallel) | Correct timing, identity, rights, controlled influence |
| **P4** Joint models & field evaluation | Sport outcome models, ownership, fields, duplication, exact payouts/ties | LATER | Calibration + field-fit reports; labels accurate |
| **P5** Contest-aware one-click & portfolios | `contest_ev`, presets, joint portfolio, entry-count recommendation, budgets | LATER / BLOCKED on P4 | Cash vs GPP differ for real; zero entries allowed |
| **P6** Live & late swap | Entry import, lock-aware continuation, rooting view | LATER | Locked slots never move |
| **P7** Evaluation | Settlement, replay, ablations, champion/challenger | LATER | Leakage-resistant, reproducible |
| **P8** Production acceptance | Security/rights, performance, restore, docs, rollout | LATER | Proven on the real deployment |

## Next dependency-ready batch (after this PR merges)

- **FOUNDATION / BACKEND:** contest + payout-ladder owner (`src/dfs/contests.py`) with exact
  tie-splitting (DFS-§5-05, §17-02 fixture $1,000/$100 → $550); NHL + NBA DraftKings/FanDuel
  classic rule sets (unverified until evidence); background job table for builds (DFS-§21-02).
- **UI:** group/conditional-rule editor, per-player exposure caps, saved-builds list, mobile
  pass + axe E2E spec for `/dfs`.
- **RESEARCH (time-boxed):** first 20 source seeds resolved to canonical identity / access /
  license state (`SOURCES.md` §3); podcast feed resolution for the NFL titles.
- **INTEGRATION:** deploy, production verification of `/dfs` on chaseupside.com (401 anonymous,
  research build with a real owner-supplied salary file).

## Blocked, with the exact unblock

| Item | Blocker | Unblock |
|---|---|---|
| Money-ready NFL builds | Rules unverified (official pages 403 to automation) | Owner confirms rules or supplies official templates |
| Verified exports | No official upload template fixture | Owner drops blank templates into `tests/dfs/fixtures/templates/` |
| Entry-count recommendation | Needs contest EV (P4/P5) and an owner-entered budget | Build P4; owner enters limits in-app |
| Sportsbook intelligence | No licensed odds feed identified | Research + owner approval of any paid feed |
