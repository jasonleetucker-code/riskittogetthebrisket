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
| W1-02 | Archive | A canonical scheduled/operational caller captures Game Day state before weekly games lock; no duplicate archive owner. | VERIFIED |
| W1-03 | Archive | Production persistence/retention for captured Week 1 observations is durable and truthfully documented. | IMPLEMENTED_UNVERIFIED |
| W1-04 | Archive | At least one authentic Week 1 pre-kickoff production capture is harvested and verified before outcomes are known. | NOT STARTED |
| W1-05 | Public pregame | Canonical matchup preview engine exists and is live/wired for upcoming matchups. | VERIFIED |
| W1-06 | Public pregame | Canonical AI narrative preview/recap pipeline exists and is live/wired; no second article-generation owner. | VERIFIED |
| W1-07 | Public pregame | Public league contract exposes the canonical pregame/narrative outputs consumed by frontend surfaces. | VERIFIED |
| W1-08 | Public pregame | Canonical Week page renders the existing matchup preview path. | VERIFIED |
| W1-09 | Public pregame | Canonical articles route renders the existing narrative path. | VERIFIED |
| W1-10 | Public pregame | All six Week 1 league matchups are present with correct managers/teams/schedule and current, non-fabricated data inputs. | IN PROGRESS |
| W1-11 | Public pregame | All six Week 1 narratives/previews are generated and pass factual, freshness, repetition, and matchup-specific quality review. | NOT STARTED |
| W1-12 | Public pregame | Week 1 pregame surfaces pass mobile/navigation/link/degraded-state production verification. | NOT STARTED |
| W1-13 | Public pregame | Public/private leakage audit proves proprietary values, edges, targets, forecasts, or private decision intelligence are not exposed publicly. | NOT STARTED |
| W1-14 | Private pregame | Authenticated owner-facing Week 1 matchup-intelligence surface/section exists without duplicating public or canonical data owners. | NOT STARTED |
| W1-15 | Private pregame | Private matchup intelligence reuses canonical lineup, strength/weakness, power/playoff, and projection inputs with source/freshness lineage. | NOT STARTED |
| W1-16 | Private pregame | Owner's Week 1 private matchup-intelligence experience is deployed and production-verified for the selected team. | NOT STARTED |
| W1-17 | Game Day foundation | `docs/GAME_DAY_PROBABILITY_SPEC.md` is the authoritative approved product/methodology contract for CE-20 Game Day. | VERIFIED |
| W1-18 | Game Day backend | One canonical league-aware current-week scoring simulation owner is identified/implemented; no second matchup/median engine. | VERIFIED |
| W1-19 | Game Day backend | Simulation consumes the requested league's exact scoring, roster slots, eligibility, team count, and league settings without silent home-league fallback. | VERIFIED |
| W1-20 | Game Day backend | Best-ball simulation uses canonical optimal-lineup behavior and preserves still-eligible lineup displacement possibilities. | VERIFIED |
| W1-21 | Game Day backend | Completed, in-progress, not-started, inactive, and unavailable player/game states are handled without double projection or missing→zero coercion. | VERIFIED |
| W1-22 | Game Day probability | `Win Matchup %` is produced from the canonical weekly simulation with bounded, testable probability output. | VERIFIED |
| W1-23 | Game Day probability | `Beat League Median %` derives from the same league-wide simulation draws; median-disabled is NOT_APPLICABLE and tie semantics are host-faithful. | BLOCKED |
| W1-24 | Game Day truth | Game Day outputs preserve timestamp, model version, projection/source freshness, coverage, and truthful degraded/unavailable states. | VERIFIED |
| W1-25 | Game Day UI | Canonical Game Day route/section and navigation shell are integrated into the existing site design and selected-team context. | NOT STARTED |
| W1-26 | Game Day UI | SCHEDULED/PREGAME state is production-usable: matchup, projected state, headline probabilities when available, drivers, freshness, and archive timestamp. | NOT STARTED |
| W1-27 | Game Day UI | LIVE state is production-usable and updates actual scoring, best-ball state, remaining players, swing context, and probabilities truthfully. | NOT STARTED |
| W1-28 | Game Day UI | FINAL state is production-usable and preserves final optimal lineup/results plus clean transition/linkage to the canonical recap system. | NOT STARTED |
| W1-29 | Launch verification | Final Week 1 candidate passes the required backend, frontend, contract/invariant, lint/build, audit, and E2E exact-head gates. | NOT STARTED |
| W1-30 | Launch verification | Final Week 1 launch tree is deployed and production-verified for archive capture, all six pregames, private owner experience, and Game Day scheduled/live/final behavior as temporally applicable. | NOT STARTED |

## Mechanical tally

*Recounted 2026-09-05T13:10Z. The numerator is unchanged; only W1-10 moved, NOT STARTED -> IN PROGRESS.*

- VERIFIED: 14
- IMPLEMENTED_UNVERIFIED: 1
- IN PROGRESS: 1
- NOT STARTED: 13
- BLOCKED: 1
- DENOMINATOR: 30
- COMPLETION: **14/30 = 46.7%**

### Row movements, 2026-09-04

- **W1-02 → VERIFIED (production evidence, run `33904966161`).** The canonical scheduled caller is merged (#1240, `b60da42`) and production dry-run evidence proved the real production interpreter/data path, nonzero projection coverage, open pregame window, exact scoring fingerprint, and installed/enabled timer. W1-04 remains separate and cannot count until an authentic pre-kickoff observation is actually harvested.
- **W1-03 → IMPLEMENTED_UNVERIFIED.** `data/game_day/` is now in `deploy/backup/riskit-state-backup.sh`, pinned by `tests/deploy/test_state_backup_dir_archiving.py`, and documented in `docs/retention/RETENTION_REGISTER.md`. It is not VERIFIED because no backup generation containing `game_day.tar.gz` has yet been observed.
- **W1-18 → VERIFIED (#1244, merge `f922d0dafc00e8ab0bf0dc215ed20e50f57f0ee0`).** `src/ros/game_day_sim.py` is the canonical league-aware current-week simulation owner. Per-player variance remains owned by `sim_calibration.PointsModel`; best-ball assignment remains owned by the canonical lineup solver. The new module owns the week rather than duplicating either primitive. Exact-head PR Validation was green before merge; the PR reports the full hard gate at 10,636 passed / 54 skipped / 0 failures.
- **W1-19 → VERIFIED (#1244).** Tests pin per-league `best_ball`, `league_average_match`, scoring, roster positions/eligibility, team count, and requested-league rules. The implementation does not silently use the owner's home-league defaults.
- **W1-20 → VERIFIED (#1244).** Best-ball draws re-solve the canonical optimal assignment on every simulation draw, preserving lineup displacement. Managed leagues instead use submitted lineups; tests pin both behaviors including Superflex/FLEX/TE/IDP/hybrid eligibility.
- **W1-21 → VERIFIED (#1244).** Completed players are banked, in-progress players preserve banked points and draw only remainder, not-started players draw the full remaining distribution, inactive is a known zero, and unknown players remain unsimulable rather than being coerced to zero. These states are directly tested.
- **W1-22 → VERIFIED (#1244).** `Win Matchup %` is produced by the canonical joint weekly simulation, bounded/tested, and structurally reconciles to the same draw-level joint outcomes used by the median path.
- **W1-24 → VERIFIED (#1244).** Game Day result contracts carry generated/model/scoring metadata, coverage and unsimulable-player information, and explicit NOT_APPLICABLE / STANDINGS_RULE_UNVERIFIED / UNSIMULABLE / fallback notes instead of fabricated numeric certainty.
- **W1-23 → BLOCKED, not VERIFIED.** #1244 correctly derives the median-side probability from the same league-wide simulation draws and correctly represents median-disabled as NOT_APPLICABLE, but host-faithful threshold/tie semantics remain unverified. `threshold_semantics_verified` is deliberately hard-coded false. The repo's historical Sleeper data cannot safely answer the question because retrospective best-ball scoring no longer reproduces the host's recorded season totals. Exact smallest decision/evidence needed: inspect one completed Sleeper week in the host UI/API evidence available at the time and establish whether `league_average_match` uses median or average and what an exact threshold tie records as. Do not guess or flip the flag without that evidence.

### Row movements, 2026-09-05

- **W1-10 → IN PROGRESS (not VERIFIED).** A full field-by-field audit of
  production `GET /api/public/league/matchupPreview` against Sleeper ground
  truth passes every clause of the row except one:
  `docs/season-launch/W1_10_WEEK1_MATCHUP_AUDIT_2026-09-05.md`. All six Week 1
  matchups are present in `preview` mode with pairings, `ownerId`s and roster
  ids matching Sleeper exactly, 12 distinct owners, unplayed points as `null`
  rather than `0`, team names resolved through the documented Sleeper fallback
  ladder, and an H2H block that is correct including a two-week aggregated 2024
  playoff meeting.
  The defect: the two first-ever meetings (matchups 2 and 3 — Blaine and
  jstuedle joined for 2026) served `avgMargin: 0.0` / `biggestMargin: 0.0` for a
  series with zero meetings, which reads as "these two always play to a dead
  heat" and was copied verbatim into the narrative generator's prompt JSON. An
  average over an empty set is undefined, not zero. Repaired in
  `matchup_preview._h2h_summary` (and the brief's re-coercing `.get(key, 0.0)`
  defaults) with `None`; counts and sums correctly stay `0`.
  It is IN PROGRESS rather than VERIFIED because a code repair is not
  production evidence: the row moves when the fix is merged, deployed, and
  production serves `avgMargin: null` for those two matchups.

### Named blockers

- **W1-11:** `ANTHROPIC_API_KEY` is not configured. `weekly-narratives.yml` therefore skips generation after its key check while reporting a green workflow; there are zero 2026 Week 1 narrative files. This needs the repository secret to exist before the scheduled Week 1 generation path can produce and quality-review all six articles.
- **W1-23:** host threshold/tie semantics as described above. The simulation intentionally fails closed on the verification flag until real host evidence settles the rule.
- **W1-03 / W1-04 timing — OWNER DECISION 2026-09-05:** the owner explicitly authorizes a **one-time Week 1 production capture on Wednesday 2026-09-09 after waiver processing is confirmed complete and before any NFL scoring begins**. Do not wait for the normal Thursday timer for the first Week 1 observation. Do not capture before waivers settle, do not backdate, and do not synthesize evidence. Preserve the normal Thursday recurring timer for future cadence unless a separate operational change is justified. After the authentic Wednesday capture creates `data/game_day/`, immediately run the real retention backup/proof path and verify an observed generation containing `game_day.tar.gz`. This makes W1-03 and W1-04 legitimately reachable by the Wednesday deadline without weakening either acceptance criterion.

Whenever a row changes, update the row and the mechanical tally in the same bounded change. Never count prose claims or partial evidence as VERIFIED.

## Deadline operating targets

These are pacing targets, not permission to weaken acceptance:

- **Fri Sep 4:** archive caller/persistence on a safe path; Week 1 pregame audit underway.
- **Sat Sep 5:** all six public pregames content-complete; private pregame integration substantially underway.
- **Sun Sep 6:** canonical Game Day backend/state contract and scoring/best-ball integration substantially complete.
- **Mon Sep 7:** scheduled + live Game Day UI substantially complete.
- **Tue Sep 8:** final state, full test matrix, deployment candidate, production verification.
- **Wed Sep 9:** defect burn-down + **owner-authorized post-waiver Week 1 capture and immediate retention proof**; **target 30/30 VERIFIED before 23:59 CT** if W1-11 and W1-23 owner/external evidence is also resolved.

## Hourly check-in contract

Hourly status checks should:

1. read live `main` and this file;
2. mechanically recount literal `VERIFIED`;
3. report `X/30` and percentage;
4. identify rows newly VERIFIED since the prior check;
5. distinguish PR-open / CI-green / merged / deployed / production-verified;
6. surface exact blockers or methodology decisions without inventing them;
7. name the single highest-value next action toward 30/30 by Sep 9, including the owner-authorized Wednesday post-waiver capture/retention sequence when that window opens;
8. when evidence is already settled and repository control is safe, advance bounded work rather than only describing it.

When this reaches **30/30 VERIFIED**, report **WEEK 1 LAUNCH TRANCHE COMPLETE** and stop the hourly completion campaign.
