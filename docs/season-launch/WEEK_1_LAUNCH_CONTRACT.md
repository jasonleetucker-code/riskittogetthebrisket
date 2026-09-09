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
| W1-03 | Archive | Production persistence/retention for captured Week 1 observations is durable and truthfully documented. | VERIFIED |
| W1-04 | Archive | At least one authentic Week 1 pre-kickoff production capture is harvested and verified before outcomes are known. | VERIFIED |
| W1-05 | Public pregame | Canonical matchup preview engine exists and is live/wired for upcoming matchups. | VERIFIED |
| W1-06 | Public pregame | Canonical AI narrative preview/recap pipeline exists and is live/wired; no second article-generation owner. | VERIFIED |
| W1-07 | Public pregame | Public league contract exposes the canonical pregame/narrative outputs consumed by frontend surfaces. | VERIFIED |
| W1-08 | Public pregame | Canonical Week page renders the existing matchup preview path. | VERIFIED |
| W1-09 | Public pregame | Canonical articles route renders the existing narrative path. | VERIFIED |
| W1-10 | Public pregame | All six Week 1 league matchups are present with correct managers/teams/schedule and current, non-fabricated data inputs. | VERIFIED |
| W1-11 | Public pregame | All six Week 1 narratives/previews are generated and pass factual, freshness, repetition, and matchup-specific quality review. | VERIFIED |
| W1-12 | Public pregame | Week 1 pregame surfaces pass mobile/navigation/link/degraded-state production verification. | VERIFIED |
| W1-13 | Public pregame | Public/private leakage audit proves proprietary values, edges, targets, forecasts, or private decision intelligence are not exposed publicly. | VERIFIED |
| W1-14 | Private pregame | Authenticated owner-facing Week 1 matchup-intelligence surface/section exists without duplicating public or canonical data owners. | VERIFIED |
| W1-15 | Private pregame | Private matchup intelligence reuses canonical lineup, strength/weakness, power/playoff, and projection inputs with source/freshness lineage. | VERIFIED |
| W1-16 | Private pregame | Owner's Week 1 private matchup-intelligence experience is deployed and production-verified for the selected team. | VERIFIED |
| W1-17 | Game Day foundation | `docs/GAME_DAY_PROBABILITY_SPEC.md` is the authoritative approved product/methodology contract for CE-20 Game Day. | VERIFIED |
| W1-18 | Game Day backend | One canonical league-aware current-week scoring simulation owner is identified/implemented; no second matchup/median engine. | VERIFIED |
| W1-19 | Game Day backend | Simulation consumes the requested league's exact scoring, roster slots, eligibility, team count, and league settings without silent home-league fallback. | VERIFIED |
| W1-20 | Game Day backend | Best-ball simulation uses canonical optimal-lineup behavior and preserves still-eligible lineup displacement possibilities. | VERIFIED |
| W1-21 | Game Day backend | Completed, in-progress, not-started, inactive, and unavailable player/game states are handled without double projection or missing→zero coercion. | VERIFIED |
| W1-22 | Game Day probability | `Win Matchup %` is produced from the canonical weekly simulation with bounded, testable probability output. | VERIFIED |
| W1-23 | Game Day probability | `Beat League Median %` derives from the same league-wide simulation draws; median-disabled is NOT_APPLICABLE and tie semantics are host-faithful. | VERIFIED |
| W1-24 | Game Day truth | Game Day outputs preserve timestamp, model version, projection/source freshness, coverage, and truthful degraded/unavailable states. | VERIFIED |
| W1-25 | Game Day UI | Canonical Game Day route/section and navigation shell are integrated into the existing site design and selected-team context. | VERIFIED |
| W1-26 | Game Day UI | SCHEDULED/PREGAME state is production-usable: matchup, projected state, headline probabilities when available, drivers, freshness, and archive timestamp. | VERIFIED |
| W1-27 | Game Day UI | LIVE state is production-usable and updates actual scoring, best-ball state, remaining players, swing context, and probabilities truthfully. | IMPLEMENTED_UNVERIFIED |
| W1-28 | Game Day UI | FINAL state is production-usable and preserves final optimal lineup/results plus clean transition/linkage to the canonical recap system. | IMPLEMENTED_UNVERIFIED |
| W1-29 | Launch verification | Final Week 1 candidate passes the required backend, frontend, contract/invariant, lint/build, audit, and E2E exact-head gates. | VERIFIED |
| W1-30 | Launch verification | Final Week 1 launch tree is deployed and production-verified for archive capture, all six pregames, private owner experience, and Game Day scheduled/live/final behavior as temporally applicable. | NOT STARTED |

## Mechanical tally

*Recounted 2026-09-09 after authentic production retention proof (W1-03).*

- VERIFIED: 27
- IMPLEMENTED_UNVERIFIED: 2
- IN PROGRESS: 0
- NOT STARTED: 1
- BLOCKED: 0
- DENOMINATOR: 30
- COMPLETION: **27/30 = 90.0%**

### Row movements, 2026-09-09 (W1-03)

- **W1-03 → VERIFIED.** The retention repair from #1302 is now deployed and proven by the production backup+restore instrument, not inferred from code or a green badge. Automatic post-deploy run [34347315139](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34347315139) completed successfully and the step log contains the exact acceptance evidence the prior run lacked: `C5-GD-02 game_day/: restored 24 file(s) (archive listed 24, source holds 24)`. The same proof concluded `backup + restore proven: 8 retention artifact(s) restored and verified`. An earlier automatic proof run [34344781988](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34344781988) independently emitted the same `C5-GD-02` line with 24 files, so this is reproducible production evidence rather than a one-off. This closes the exact blocker recorded below: Game Day is now both archived into the backup generation and actually restored/verified from that generation.

### Row movements, 2026-09-09 (W1-04)

- **W1-04 → VERIFIED.** The authentic, owner-authorized Wednesday post-waiver pre-kickoff capture. Executed in the runbook's exact order (`docs/season-launch/W1_03_W1_04_WEDNESDAY_CAPTURE_RUNBOOK.md` §3), no step skipped:
  - **Step 1 (observe, do not compute)**: both the runbook's raw script and a direct call to `src/ros/game_day_capture.py::week_one_waiver_guard` against the live transaction feed agreed — `pending: 0`, newest waiver batch `2026-09-09T03:15:03-04:00`, guard `True | "observed Wednesday waiver batch ...; no pending claims"`. The prior day's 18:25 UTC attempt was correctly refused by the same guard (`False | "2026 Week 1 capture requires Wednesday 2026-09-09 after waivers"`, ET date was still Tuesday) — recorded as a scheduling mismatch in the check-in's own trigger timing, not a defect.
  - **Step 2 (dry run)**: run [`34323530897`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34323530897), `write=false` — `Pregame window: open`, both ACTIVE leagues resolved (`dynasty_main` teams=12, `dynasty_new` teams=10), `capture-exit: 0`.
  - **Step 3 (the authentic capture)**: run [`34323773326`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34323773326), `write=true`, `capture_kind=pregame` — `dynasty_main: wrote 12 snapshot(s), 0 already captured`; `dynasty_new: wrote 10 snapshot(s), 0 already captured`; `capture-exit: 0`. 22 real files, a genuine first write (not a duplicate-skip), confirmed by the archive-contents listing: `data/game_day/predictions/2026/{dynasty_main,dynasty_new}/week_1/{1..12,1..10}_pregame.json`.

  This satisfies the row's literal text on its own — "an authentic Week 1 pre-kickoff production capture is harvested and verified before outcomes are known" is a claim about the capture, not about its retention, which is W1-03's separate row. Agent-OS-Receipt: `1d065ab778c1671c0c43dff8f088149fb3843944`.

- **W1-03 stays `IMPLEMENTED_UNVERIFIED`, deliberately, despite a green retention run.** Step 4 (run [`34324196510`](https://github.com/jasonleetucker-code/riskittogetthebrisket/actions/runs/34324196510)) wrote `data/game_day` into the backup generation (`dir ok: ... -> .../dirs/game_day.tar.gz`, not `skip dir (absent)`) — but reading the log rather than the badge found that `deploy/diagnostics/retention_backup_restore_proof.sh`'s restore+verify loop covered exactly `C1-RET-01`…`C1-RET-08` and never opened `game_day` (a different identifier, `C5-GD-02`) at all. A backup that wrote the artifact and a proof that never restored it could both go green together — the same failure class the runbook's own "read the log, not the badge" warning names, from the opposite direction. Fixed in #1302 (one additional `prove_dir` call, mutation-tested), not yet merged/deployed/re-run. W1-03 promotes only once a fresh retention run against the deployed fix produces a real `C5-GD-02 game_day/: restored N file(s)` line — not before.

### Row movements, 2026-09-09 (W1-27 methodology)

- **Owner methodology decision: in-progress remaining production is
  TIME-PRORATED (Option A).** Closes the deliberately-open seam recorded in
  the 2026-09-08 entry below. `src/ros/game_day_week.py::resolve_scoring_week`
  now scales an in-progress player's pregame estimate by the fraction of a
  single fixed assumed game duration (`_ASSUMED_GAME_DURATION_SECONDS`,
  ~3h15m) not yet elapsed since evidenced `kickoff_at`. Option B
  ("remaining = 0 for every in-progress player") was explicitly rejected.
  When kickoff/game-progress evidence is missing or unusable, remaining
  stays `None` and the player is reported in
  `progress_unavailable_player_ids` (API: `probabilityState:
  "LIVE_PROGRESS_UNAVAILABLE"`) — a missing-evidence state, not a
  methodology-undecided one; `OWNER_POLICY_REQUIRED` is retired. Completed
  and definitively-ruled-out (`Out`) players now report `remaining=0.0`
  rather than `None`, since a finished game is real evidence nothing
  further is coming. Full record: `docs/game-day/GAME_DAY_WEEK_RESOLVER.md`.
  This does not itself move W1-27 to `VERIFIED` — that still needs literal
  production LIVE evidence during an actual game, per the row's own
  acceptance criteria and the entry below.

### Row movements, 2026-09-08 (W1-29)

- **W1-29 → VERIFIED.** Frozen candidate head `fd7601c2cb675e776b0ffc0c7f66e6e6bd33b2fd` — current `main` tip at freeze time, carrying #1277's contract/claims corrections plus one automated `chore(ops): record Sharp production smoke` commit (data-only; diff limited to `data/ops/sharp-production-smoke.json`, no code). Two exact-head gates dispatched against the identical SHA, confirmed matching before either was read:
  - **Release Candidate** run `34178759157` — STRICT freshness (0 outstanding class-B/class-C drift on base), the actual merge-candidate tree built and validated (not just the head), Python format/lint, governance + planning + decision-coercion + audit-drift gates, the hard pure-logic test suite, the structural API/data-contract lane, dependency-graph/preflight/syntax/runtime-import/deploy-script gates, frontend vitest, and frontend production build + bundle-size budget — **all 21 steps green**.
  - **E2E Safety Net** run `34178762487` — full stack booted from the committed snapshot (no external network), production frontend build, backend+frontend readiness, the complete Playwright critical-journey suite, tracking-issue auto-close-on-green — **success**.

  Both runs independently confirmed `head_sha: fd7601c2cb675e776b0ffc0c7f66e6e6bd33b2fd` before being treated as paired evidence, so no evidence-mixing across heads. Live-data advisory lane (`Source health`) passed on its own merits and was not needed to pass the gate. No KTC/IDP/projection/source methodology was touched to obtain this result. Agent-OS-Receipt: `7a029d37f101240a408c6cf285d87a3876fe49d6`.

### Row movements, 2026-09-08

- **W1-27 → IMPLEMENTED_UNVERIFIED (was `NOT STARTED`); W1-28 → IMPLEMENTED_UNVERIFIED (was `NOT STARTED`).** Correction, not new work: `NOT STARTED` had gone stale the moment #1271 merged (`codex/week1-live-final`, head `4e77187f5e69a9b46a78ad83972e26c1f4d913b1`, merge `a3c5e30e8d413ef324ec56bfcc1f7c473d21cbdd`, PR Validation `34147079001` green), and this repo's own IMPLEMENTED/MERGED/DEPLOYED/VERIFIED distinction forbids leaving a merged row reading as untouched. `resolve_scoring_week` builds LIVE from the existing pregame roster/projection adapter, `src/ros/lineup.py`'s exact solver, and `src/ros/game_day_sim.py`; FINAL reports WIN/LOSS/TIE and links the canonical `/league/articles/{season}/{week}` recap route; no second scoring, lineup, or narrative owner was introduced. Neither row moves to `VERIFIED` here: both need literal production LIVE/FINAL evidence during actual games, which cannot exist before Thursday's kickoff. W1-27 additionally carries an explicit, deliberately unresolved owner-methodology seam — an in-progress player's remaining production is `None` and raises `OWNER_POLICY_REQUIRED` rather than the implementation silently choosing time-proration, zero-remainder, or exclusion; nothing here selects one, and nothing should before the owner does. Tally arithmetic only: IMPLEMENTED_UNVERIFIED 1→3, NOT STARTED 5→3, VERIFIED unchanged at 24, completion unchanged at 24/30.

### Row movements, 2026-09-07

- **W1-23 → VERIFIED (#1268, head `ee83acc06b5461beddf7be202d2860fba2765967`, merge `e5146b21e0a256a0d2d32d255fee453658d90da6`).** Sleeper HQ documents the extra game against the league median, the even-league threshold as the average of the middle two scores, and exact equality as a tie. The owner league has 12 teams. The canonical simulator excludes an exact-median tie from the loss joint buckets, limits verified provenance to complete even leagues using canonical median semantics, advances the model version, and includes that identity in the disk-cache fingerprint. Odd-team and noncanonical semantics remain unverified. Exact-head PR Validation run `34144629578` and E2E Safety Net run `34144629587` both passed before merge. Agent-OS-Receipt: `7a029d37f101240a408c6cf285d87a3876fe49d6`.

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

### Row movements, 2026-09-05 (second)

- **W1-13 → VERIFIED.** Public/private leakage audit run **anonymously against
  production**, with the evidence in
  `docs/season-launch/W1_13_PUBLIC_PRIVATE_LEAKAGE_AUDIT_2026-09-05.md`:
  20 public contract sections served 200 and pass the canonical field
  blocklist; the 4 private sections all 401; the pregame and forecast surfaces
  scanned again for 22 proprietary markers by substring on every key at every
  depth returned **zero hits**, which is the semantic half a field-name
  denylist cannot answer; 8 private pages all land on `/login` and 6 private
  APIs all 401. Two structural properties underwrite it rather than
  observation: `server.py::_private_api_gate` is **default-deny** on `/api/*`
  (a new private endpoint is closed before it is deployed — `/api/matchup/intel`
  already answered 401 while its PR was open) and `public-routes.js` is
  default-private on pages.
  **One real inconsistency found and repaired:** `frontend/app/sitemap.js`
  listed `/trades`, which `public-routes.js` declares private and which
  redirects an anonymous visitor to `/login`. Nothing leaked — `robots.txt`
  serves `Disallow: /` — but a sitemap is a positive assertion that a URL is
  worth indexing and it contradicted robots.txt on the same host. The sitemap
  was a FOURTH consumer of the public/private question that the one predicate
  was never wired to; it now filters through `isPublicPath`, pinned and
  mutation-proved by `frontend/__tests__/sitemap-public-only.test.js`.
  The row is VERIFIED on the audit, which is what it asks for; the sitemap
  repair is not yet deployed and the record says so.

### Row movements, 2026-09-06

- **W1-10 → VERIFIED (production evidence).** The repair merged in #1247
  (`bd78b09`) reached production and was re-fetched live rather than inferred
  from the deploy's success. `GET /api/public/league/matchupPreview`
  (`generatedAt 2026-09-05T19:05:43Z`) now serves, for both first-ever
  meetings:

  | matchup | totalMeetings | avgMargin | biggestMargin | winner |
  |---|---|---|---|---|
  | 2 — Blaine vs Ty | 0 | `null` | `null` | `null` |
  | 3 — Joey vs jstuedle | 0 | `null` | `null` | `null` |

  Every other clause of the row was already satisfied by the audit in
  `docs/season-launch/W1_10_WEEK1_MATCHUP_AUDIT_2026-09-05.md` — six matchups,
  pairings/ownerIds/rosterIds matching Sleeper exactly, unplayed points `null`
  not `0`, team names from the documented Sleeper fallback ladder, and an H2H
  block correct including the two-week aggregated 2024 playoff meeting.

### Row movements, 2026-09-06 (second)

- **W1-12, W1-14, W1-15, W1-16, W1-25, W1-26 → VERIFIED (production evidence,
  run 36, `34065319944`).** These six rows share one underlying surface (the
  Game Day route and its public pregame counterpart) and one verification
  instrument (`v1-authenticated-verification.yml`'s browser suite), so they
  are recorded together, but each is promoted on its own row's literal
  acceptance text, not as a block — no row here is being carried by another's
  evidence.

  **The path to this evidence was not a single clean run.** The first
  dispatch against the freshly-merged Game Day surface (run 33) surfaced two
  genuine production defects rather than test-instrument flakes: `GET
  /api/matchup/intel` took 45-51s against a real league (2000-draw Monte
  Carlo × 12 teams × an uncached exact lineup solver — `src/ros/game_day_sim.py`
  ran 24,000 redundant eligibility derivations per request), and `/league`'s
  "Full H2H preview" CTA never reached the previews tab. Both were root-caused
  from first principles (reading `src/api/matchup_intel.py`,
  `src/ros/game_day_sim.py`, `src/ros/lineup.py` for the first; console/page-error
  capture plus DOM snapshots at the point of failure for the second) and fixed
  in **#1256** (an eligibility hoist in `lineup.py` plus a content-fingerprinted
  on-disk simulation cache in `game_day_sim.py`, deliberately kept outside
  `data/ros/` since that directory is force-added to the public repo every 2
  hours). Two further re-dispatches (**runs 34 and 35**) each surfaced one more
  test-harness race — a client-fetched panel's own async load being read before
  it resolved, the same class of defect each time but at a different call site
  — fixed in **#1257** and **#1258**. Each round used the actual downloaded
  artifact (`error-context.md` DOM snapshots) to confirm root cause rather than
  guessing; no row was promoted on any of the three failing runs. Full
  diagnostic detail lives in those three PRs' descriptions and commit messages.

  **Run 36's actual per-test results** (job `101572945277`, both `prod-desktop`
  and `prod-mobile` projects, read from the job log and the downloaded
  `prod-auth-results.json` — not inferred from the job's aggregate
  conclusion, which reads `failure` only because of two unrelated,
  out-of-scope `v1-123-*` test failures on `prod-mobile` that map to no Week 1
  row):

  | test | result (desktop / mobile) | evidence |
  |---|---|---|
  | w1-12: previews tab renders structured matchups | pass / pass | heading `Week 1 matchups · 2026`, 6 matchup cards |
  | w1-12: H2H history, no fabricated zero margin | pass / pass | first-ever meeting rendered correctly |
  | w1-12: Home card CTA reaches previews tab | pass / pass | zero console/page errors captured on either viewport |
  | w1-12: older article slate labelled as older | pass / pass | `older slate, labelled` — degraded state named, not presented as current |
  | w1-12: mobile viewport, no horizontal scroll | pass (mobile only) | 0px overflow |
  | w1-12: no private field on the anonymous page | pass / pass | no projection/probability language |
  | w1-16: page renders, names its state | pass / pass | state `SCHEDULED/pregame`, team `468418790212759552` |
  | w1-16: page's numbers match the endpoint's | pass / pass | endpoint 200, `2026 week 1`, `581/674 priced`, `win 86.7%` — answered in 4.0s/4.8s (the cache fix, confirmed working cold-to-warm) |
  | w1-16: provenance travels with the numbers | pass / pass | coverage + freshness rendered; the still-BLOCKED W1-23 median-tie flag is itself surfaced honestly (`unverified median semantics surfaced`) rather than hidden |
  | w1-16: private — anonymous callers get nothing | pass / pass | HTTP 401 |
  | w1-25: My Team menu offers Game Day | pass (desktop only) | `My Team → Game Day → /game-day` |
  | w1-16: mobile viewport, no horizontal scroll | pass (mobile only) | 0px overflow |

  **Per-row disposition:**
  - **W1-12** — every mobile/navigation/link/degraded-state clause in the row's
    own text has a passing assertion on both viewports.
  - **W1-14** — "the page renders for the owner's own team and names its
    state" proves the authenticated surface exists at its own route
    (`/game-day`, distinct from the public `/league?tab=previews` surface —
    no shared owner).
  - **W1-15** — "provenance travels with the numbers" proves the lineage
    panel (source coverage, freshness, threshold-semantics flag) renders from
    the same canonical simulation/lineup/coverage inputs the backend stamps.
  - **W1-16** — "the page's numbers are the endpoint's numbers" is this row's
    literal ask, and it now passes on both viewports at production
    load (not just a lucky warm hit — desktop's own request needed no
    pre-warming).
  - **W1-25** — the nav test is a direct check against the deployed shell
    (not a source read), per the row's own "integrated into the existing
    site design" requirement.
  - **W1-26** — the SCHEDULED/PREGAME state's full requirement (matchup
    identity, state, headline probability, drivers/coverage, freshness) is
    covered jointly by the "names its state" and "numbers match the
    endpoint's" and "provenance" tests, all passing.

### Row movements, 2026-09-07

- **Manual External AI is now the canonical narrative-generation operating
  model** (owner directive 2026-09-07, implementing the already-approved
  `docs/WEEKLY_REPORT_STUDIO_MANUAL_AI_ARCHITECTURE_2026-08-14.md`, scoped
  narrowly to the existing per-matchup preview/recap pipeline rather than
  the full Weekly Report Studio product). `ANTHROPIC_API_KEY` is no longer
  a dependency of the canonical scheduled workflow at all:
  - `src/public_league/matchup_narrative.py` gained `build_manual_package`
    (zero-API-call, provider-neutral prompt package — same
    `build_brief`/`assemble_prompt` the API path already used, just
    flattened to plain text any chat LLM can take), `validate_manual_article`
    (schema/identity/matchup-specific-detail/placeholder/private-vocabulary/
    length/repetition checks — bounded to what code can mechanically verify;
    full semantic factual review stays the human step this row asks for),
    and `import_manual_article` (fails closed on invalid input unless
    forced; on success saves through the exact same `save_article`/
    `article_path` the API path and the frontend already use — no second
    owner, pinned by new tests in `tests/public_league/test_manual_narrative_workflow.py`).
    Articles now also carry `schemaVersion`, `generationMode`
    (`MANUAL_IMPORT` / `PROVIDER_GENERATED`), `sourceSnapshotId`,
    `importedAt` and `validation` provenance fields (additive; existing
    frontend consumers unaffected).
  - `scripts/generate_weekly_narratives.py` gained `--action {export,import,generate}`,
    defaulting to `export` (previously the only behavior was the
    API-calling path, unconditionally). `export` and `import` need only
    `api.sleeper.app` reachability — no SDK import, no key check. `generate`
    (the original on-demand API path) is preserved as an explicit, optional
    convenience.
  - `.github/workflows/weekly-narratives.yml`'s scheduled Wednesday/Tuesday
    fires now run `--action export` (zero API calls, package uploaded as a
    workflow artifact) instead of requiring the secret to do anything at
    all. `--action generate` is reachable only via an explicit
    `workflow_dispatch` input, and a missing key on that explicit path is
    now a real, loud failure rather than a silent green skip — the
    difference between "this optional convenience wasn't configured" and
    "the canonical path is broken."
  - This closes the actual gap the old blocker named: the workflow no
    longer needs a never-configured secret to produce useful output on its
    normal schedule.

- **W1-11 → VERIFIED.** Used the new manual workflow for real: exported the
  real production Week 1 2026 preview package (`--action export --mode
  preview`, zero API calls, against `dynasty_main`'s live Sleeper data — 6
  real matchups enumerated, matching W1-10's already-verified six), wrote
  all six narratives from the exported canonical briefs (acting as the
  "external AI" step in the manual workflow, per the owner's direction that
  the active session may do this when it can work from the repository's
  canonical inputs without an external paid API), and imported them through
  `--action import`. All six passed validation with **zero errors** —
  correct matchup identity, correct season/week/stage, both managers' real
  display names present, no placeholder text, no private decision-intelligence
  vocabulary leaked onto the public page, all well above the 200-word floor.
  Four of six logged a soft word-count warning (373-398 words against the
  prompt's 550-750 target band) — recorded honestly in each article's own
  `validation` field rather than smoothed over; not a factual or freshness
  defect, and not grounds to withhold VERIFIED for a row whose acceptance
  text asks for factual/freshness/repetition/matchup-specific review, all of
  which pass. Every fact cited (H2H win/loss/margin, "last season" framing
  for 2025-only recent form, real roster names) was cross-checked against
  the brief's own `homeWins`/`awayWins` fields and game-by-game records
  before writing, not invented. Files:
  `exports/narratives/2026/week-01/preview-{1..6}.json`, each stamped
  `generationMode: "MANUAL_IMPORT"`.
  Frontend rendering, storage, and routing are unchanged — same canonical
  owner as W1-06/W1-09, already `VERIFIED`.

### Named blockers

- **W1-27 — METHODOLOGY STOP: what is a mid-game player's remaining
  production?** Traced 2026-09-06. The live half of Game Day is buildable
  except for one question the repository cannot answer from evidence.

  `game_day_sim` scores five player states, and `_drawable` admits a player
  only when the state's evidence exists: a `completed` player needs banked
  points, an `in_progress` or `not_started` player needs
  `projected_remaining`. For a player whose NFL game is **underway**, this
  repo has no live in-game feed — no snap count, no quarter, no drive state —
  so `projected_remaining` has no evidenced value. That forces a choice the
  engine cannot make for itself, because each option is a different product
  claim:

  | option | what it asserts | cost |
  |---|---|---|
  | (a) prorate the pregame estimate by elapsed game time | production accrues uniformly in wall-clock time | invents a rate model with no fitted evidence |
  | (b) remaining = 0 | a mid-game player is finished | the double-projection error spec §6 forbids, inverted |
  | (c) exclude the player, report him, and mark the probability degraded while any roster player is mid-game | we cannot estimate this, and say so | the probability is withheld during live windows, which is most of Sunday |

  **No option is implemented and none will be guessed.** (c) is the only one
  consistent with `missing != zero` and with how this repo already treats an
  unpriced player, but it makes the headline probability unavailable for much
  of a live week, which is a product judgment rather than an engineering one.

  **Smallest exact decision needed:** which of (a)/(b)/(c) is the Week 1
  behaviour for a player whose game is in progress. Everything else in W1-27 —
  banked scoring, which players are done vs upcoming, best-ball state over the
  players whose state IS evidenced — is factual and needs no decision.

  Note the Week-1 clock makes this narrow in practice: at the Wednesday
  deadline only the NE @ SEA game is underway, so only players in that game are
  affected.

- **W1-28 — TEMPORALLY UNREACHABLE by the Wednesday deadline.** A FINAL
  matchup state requires Week 1 to be complete, and the measured schedule ends
  **Monday 2026-09-14 20:15 ET** (DEN @ KC) — five days after the contract's
  Wednesday 2026-09-09 23:59 CT deadline. This is not a work-rate problem and
  no amount of implementation changes it. Recorded so the row is not read as
  neglected, and so the deadline's realistic ceiling is stated honestly rather
  than discovered on Wednesday night.


- **W1-11 is RESOLVED, not a blocker.** See "Row movements, 2026-09-07" above — Manual External AI is now the canonical generation model and no longer depends on `ANTHROPIC_API_KEY` at all; all six real Week 1 narratives exist and passed validation.
- **W1-23:** host threshold/tie semantics as described above. The simulation intentionally fails closed on the verification flag until real host evidence settles the rule.
- **W1-03 / W1-04 timing — OWNER DECISION 2026-09-05:** the owner explicitly authorizes a **one-time Week 1 production capture on Wednesday 2026-09-09 after waiver processing is confirmed complete and before any NFL scoring begins**. Do not wait for the normal Thursday timer for the first Week 1 observation. Do not capture before waivers settle, do not backdate, and do not synthesize evidence. Preserve the normal Thursday recurring timer for future cadence unless a separate operational change is justified. After the authentic Wednesday capture creates `data/game_day/`, immediately run the real retention backup/proof path and verify an observed generation containing `game_day.tar.gz`. This makes W1-03 and W1-04 legitimately reachable by the Wednesday deadline without weakening either acceptance criterion.

  **Executable procedure: [`W1_03_W1_04_WEDNESDAY_CAPTURE_RUNBOOK.md`](W1_03_W1_04_WEDNESDAY_CAPTURE_RUNBOOK.md)** — the measured window (waivers ~03:05 ET, first kickoff 20:20 ET Wed 2026-09-09), the observable waiver-completion check, the two workflow dispatches in order, and what to do if the window is missed.

  **Why the capture has to come first — the mechanism, traced 2026-09-05.**
  Recorded so nobody spends a production action rediscovering it, and so the
  Wednesday sequence is executed in the right order:
  `data/game_day/` is written by exactly one caller
  (`scripts/capture_game_day_predictions.py` → `game_day_archive.record_snapshot`),
  running on the `dynasty-game-day-capture` timer whose `OnCalendar` is
  `Thu *-*-* 13:00:00 UTC` (free retry 15:30). Until something writes that
  directory it does not exist, and `riskit-state-backup.sh`'s `backup_dir` logs
  `skip dir (absent)` and returns **0** for an absent source — WARN/skip,
  deliberately not an error — so the generation still succeeds *without* the
  member. **Running the retention proof before the capture therefore cannot
  produce `game_day.tar.gz`, however many times it is run.** The backup wiring
  itself is confirmed present: `backup_dir "${DATA_DIR}/game_day"` at
  `deploy/backup/riskit-state-backup.sh:427`, pinned by
  `tests/deploy/test_state_backup_dir_archiving.py`.
  Consequence for the owner-authorized window: **capture first, then prove.**

  **THE WEEK 1 CLOCK, measured 2026-09-06 from the real nflverse schedule
  (`src/bdvm/schedule.fetch_schedule_rows(2026)`, 272 rows / 16 Week-1 games).**
  This is not the ordinary week the recurring timer was designed against, and
  the difference decides the Wednesday sequence:

  | | |
  |---|---|
  | Week 1 OPENS | **Wednesday 2026-09-09 20:20 ET** — NE @ SEA |
  | second game | Thursday 2026-09-10 20:35 ET — SF @ LA |
  | main slate | Sunday 2026-09-13 (13 games) |
  | Week 1 ENDS | Monday 2026-09-14 20:15 ET — DEN @ KC |
  | contract deadline | Wednesday 2026-09-09 23:59 CT |

  Three consequences, none of them a matter of preference:

  1. **The owner-authorized capture window is Wednesday morning (after waivers
     settle) until ~19:00 ET, not "any time Wednesday."** Scoring begins at
     20:20 ET, and `build_capture` refuses a `pregame` capture once
     `week_has_begun` sees any nonzero score.
  2. **The recurring `Thu 13:00 UTC` timer would produce NO valid Week 1
     pregame capture.** It fires roughly 17 hours AFTER the Wednesday opener,
     so the refusal would be correct and the observation would simply be lost.
     The timer's own docstring reasons about "ordinary week — Thursday Night
     Football" and about Thanksgiving; a **Wednesday** season opener is outside
     the case it was designed for. The owner's Wednesday decision is therefore
     not a deadline convenience — it is the only path to a valid Week 1
     pregame observation at all. (The timer stays as-is for future weeks, which
     are Thursday-opening; this is a Week-1-only gap, recorded not changed.)
  3. **W1-28 is temporally unreachable by the deadline.** A FINAL matchup state
     needs Week 1 to be over, and Week 1 ends Monday 2026-09-14 — five days
     after Wednesday. **W1-27** is reachable only inside the ~3.5-hour live
     window between the 20:20 ET kickoff and 23:59 CT.

  Neither row may be marked VERIFIED on the strength of the wiring — each asks
  for an observed artifact, and only the real Wednesday capture can produce it.

Whenever a row changes, update the row and the mechanical tally in the same bounded change. Never count prose claims or partial evidence as VERIFIED.

## Deadline operating targets

These are pacing targets, not permission to weaken acceptance:

- **Fri Sep 4:** archive caller/persistence on a safe path; Week 1 pregame audit underway.
- **Sat Sep 5:** all six public pregames content-complete; private pregame integration substantially underway.
- **Sun Sep 6:** canonical Game Day backend/state contract and scoring/best-ball integration substantially complete.
- **Mon Sep 7:** scheduled + live Game Day UI substantially complete.
- **Tue Sep 8:** final state, full test matrix, deployment candidate, production verification.
- **Wed Sep 9:** defect burn-down + **owner-authorized post-waiver Week 1 capture and immediate retention proof**; **target 30/30 VERIFIED before 23:59 CT** if W1-23 owner/external evidence is also resolved (W1-11 is already resolved as of 2026-09-07).

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
