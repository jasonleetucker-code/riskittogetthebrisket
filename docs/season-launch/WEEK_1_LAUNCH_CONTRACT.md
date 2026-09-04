# Week 1 Launch Completion Contract — 2026

**Owner deadline:** Wednesday, 2026-09-09, 23:59 America/Chicago  
**Scope:** Post-V1 / pre-V2 season-launch tranche: Week 1 pregames + Game Day Command Center  
**Canonical denominator:** **30 rows**  
**Counting rule:** **Only literal `VERIFIED` counts in the numerator.**  
**Initial audited tally (2026-09-04):** **7/30 VERIFIED = 23.3%**

This is the canonical completion scoreboard for the owner's immediate Week 1 launch tranche. It is intentionally stricter than a rough "percent of reusable foundations already built" estimate: a row counts only when its declared acceptance evidence is actually satisfied.

## Status vocabulary

- `NOT STARTED` — required work/evidence does not yet exist.
- `IN PROGRESS` — active work exists, but acceptance is not yet met.
- `IMPLEMENTED_UNVERIFIED` — code may be merged/implemented, but required deployment/production evidence is incomplete.
- `VERIFIED` — the row's acceptance criterion is satisfied by repository/CI/production evidence.
- `BLOCKED` — a specific external or owner/methodology decision prevents completion; blocker must be named.

Do not collapse IMPLEMENTED, MERGED, DEPLOYED, and VERIFIED. Missing != zero. Stale != current. Unknown != false. Preserve ONE CONCEPT / ONE CANONICAL OWNER and all canonical identity, value, scoring, lineup, auth, provenance, and public/private boundaries.

The denominator is frozen at 30 for this launch tranche. Do not add/remove rows merely to improve the percentage. Any scope change requires an explicit owner decision recorded durably.

## Contract

| ID | Area | Requirement / acceptance | Status |
|---|---|---|---|
| W1-01 | Archive | Canonical append-only Game Day prediction archive exists, is merged, and its core refusal/identity behavior is tested. | VERIFIED |
| W1-02 | Archive | A canonical scheduled/operational caller captures Game Day state before weekly games lock; no duplicate archive owner. | NOT STARTED |
| W1-03 | Archive | Production persistence/retention for captured Week 1 observations is durable and truthfully documented. | NOT STARTED |
| W1-04 | Archive | At least one authentic Week 1 pre-kickoff production capture is harvested and verified before outcomes are known. | NOT STARTED |
| W1-05 | Public pregame | Canonical matchup preview engine exists and is live/wired for upcoming matchups. | VERIFIED |
| W1-06 | Public pregame | Canonical AI narrative preview/recap pipeline exists and is live/wired; no second article-generation owner. | VERIFIED |
| W1-07 | Public pregame | Public league contract exposes the canonical pregame/narrative outputs consumed by frontend surfaces. | VERIFIED |
| W1-08 | Public pregame | Canonical Week page renders the existing matchup preview path. | VERIFIED |
| W1-09 | Public pregame | Canonical articles route renders the existing narrative path. | VERIFIED |
| W1-10 | Public pregame | All six Week 1 league matchups are present with correct managers/teams/schedule and current, non-fabricated data inputs. | NOT STARTED |
| W1-11 | Public pregame | All six Week 1 narratives/previews are generated and pass factual, freshness, repetition, and matchup-specific quality review. | NOT STARTED |
| W1-12 | Public pregame | Week 1 pregame surfaces pass mobile/navigation/link/degraded-state production verification. | NOT STARTED |
| W1-13 | Public pregame | Public/private leakage audit proves proprietary values, edges, targets, forecasts, or private decision intelligence are not exposed publicly. | NOT STARTED |
| W1-14 | Private pregame | Authenticated owner-facing Week 1 matchup-intelligence surface/section exists without duplicating public or canonical data owners. | NOT STARTED |
| W1-15 | Private pregame | Private matchup intelligence reuses canonical lineup, strength/weakness, power/playoff, and projection inputs with source/freshness lineage. | NOT STARTED |
| W1-16 | Private pregame | Owner's Week 1 private matchup-intelligence experience is deployed and production-verified for the selected team. | NOT STARTED |
| W1-17 | Game Day foundation | `docs/GAME_DAY_PROBABILITY_SPEC.md` is the authoritative approved product/methodology contract for CE-20 Game Day. | VERIFIED |
| W1-18 | Game Day backend | One canonical league-aware current-week scoring simulation owner is identified/implemented; no second matchup/median engine. | NOT STARTED |
| W1-19 | Game Day backend | Simulation consumes the requested league's exact scoring, roster slots, eligibility, team count, and league settings without silent home-league fallback. | NOT STARTED |
| W1-20 | Game Day backend | Best-ball simulation uses canonical optimal-lineup behavior and preserves still-eligible lineup displacement possibilities. | NOT STARTED |
| W1-21 | Game Day backend | Completed, in-progress, not-started, inactive, and unavailable player/game states are handled without double projection or missing→zero coercion. | NOT STARTED |
| W1-22 | Game Day probability | `Win Matchup %` is produced from the canonical weekly simulation with bounded, testable probability output. | NOT STARTED |
| W1-23 | Game Day probability | `Beat League Median %` derives from the same league-wide simulation draws; median-disabled is NOT_APPLICABLE and tie semantics are host-faithful. | NOT STARTED |
| W1-24 | Game Day truth | Game Day outputs preserve timestamp, model version, projection/source freshness, coverage, and truthful degraded/unavailable states. | NOT STARTED |
| W1-25 | Game Day UI | Canonical Game Day route/section and navigation shell are integrated into the existing site design and selected-team context. | NOT STARTED |
| W1-26 | Game Day UI | SCHEDULED/PREGAME state is production-usable: matchup, projected state, headline probabilities when available, drivers, freshness, and archive timestamp. | NOT STARTED |
| W1-27 | Game Day UI | LIVE state is production-usable and updates actual scoring, best-ball state, remaining players, swing context, and probabilities truthfully. | NOT STARTED |
| W1-28 | Game Day UI | FINAL state is production-usable and preserves final optimal lineup/results plus clean transition/linkage to the canonical recap system. | NOT STARTED |
| W1-29 | Launch verification | Final Week 1 candidate passes the required backend, frontend, contract/invariant, lint/build, audit, and E2E exact-head gates. | NOT STARTED |
| W1-30 | Launch verification | Final Week 1 launch tree is deployed and production-verified for archive capture, all six pregames, private owner experience, and Game Day scheduled/live/final behavior as temporally applicable. | NOT STARTED |

## Mechanical tally

- VERIFIED: 7
- IMPLEMENTED_UNVERIFIED: 0
- IN PROGRESS: 0
- NOT STARTED: 23
- BLOCKED: 0
- DENOMINATOR: 30
- COMPLETION: **7/30 = 23.3%**

Whenever a row changes, update the row and the mechanical tally in the same bounded change. Never count prose claims or partial evidence as VERIFIED.

## Deadline operating targets

These are pacing targets, not permission to weaken acceptance:

- **Fri Sep 4:** archive caller/persistence on a safe path; Week 1 pregame audit underway.
- **Sat Sep 5:** all six public pregames content-complete; private pregame integration substantially underway.
- **Sun Sep 6:** canonical Game Day backend/state contract and scoring/best-ball integration substantially complete.
- **Mon Sep 7:** scheduled + live Game Day UI substantially complete.
- **Tue Sep 8:** final state, full test matrix, deployment candidate, production verification.
- **Wed Sep 9:** defect burn-down only; **target 30/30 VERIFIED before 23:59 CT**.

## Hourly check-in contract

Hourly status checks should:

1. read live `main` and this file;
2. mechanically recount literal `VERIFIED`;
3. report `X/30` and percentage;
4. identify rows newly VERIFIED since the prior check;
5. distinguish PR-open / CI-green / merged / deployed / production-verified;
6. surface exact blockers or methodology decisions without inventing them;
7. name the single highest-value next action toward 30/30 by Sep 9;
8. when evidence is already settled and repository control is safe, advance bounded work rather than only describing it.

When this reaches **30/30 VERIFIED**, report **WEEK 1 LAUNCH TRANCHE COMPLETE** and stop the hourly completion campaign.
