# Overnight tier ledger — started 2026-07-27 ~12:15 UTC

Operator asleep. Work Tiers 1-remnant → 2 → 3 → 4 in order, one PR per
tier, do NOT merge anything. Update this file after every unit of work.

## Standing rules for this run

- One branch + one PR per tier. Never merge. The operator reviews in the
  morning.
- Before every push: `ruff format --check .` AND `ruff check` over the
  changed .py set (CI runs both; the second one bit me twice).
- Hard gate = `pytest tests/ -x -q -m "not livedata"`. The livedata step
  is `continue-on-error` and is ALREADY red on main — do not treat it as
  my signal, but do fix it in Tier 4 (it is item T4-5).
- Anything that moves live valuation numbers goes behind a flag. Default
  ON only where the operator explicitly directed it (TE basis was
  directed; nothing in Tier 2 is yet).
- §6.15 discipline: every guard must be observed failing pre-fix.

## Status

### Tier 0 — DONE, in PR #591
### Tier 1 — **COMPLETE**, in PR #591
- [x] LI-9 endpoint tests (17)
- [x] hydration flash
- [x] TE curve wired into base blend (Axis A) + rule-4 downstream sweep
- [x] **T1-d server-side composition** — DONE, a59d83be. `valuation_mode`
      on POST /api/rankings/overrides?view=delta. Key insight: asking for
      the lens NARROWS the endpoint to one league (503 on mismatch),
      because scarcity is roster-derived. meta.valuationMode discloses
      which board you got. 11 new tests, 4 observed failing pre-fix.
- [x] **T1-e honesty pass** — DONE, 615b7082. Three distinct problems,
      not one: Movers is a genuine market-only divergence (no adjusted
      rank history exists, so it is disclosed rather than fixed);
      exports gained a Value Basis COLUMN (they outlive the app);
      /draft //rosters //edge //waivers got `ValueBasisNote`, which
      renders nothing on market by design. Also fixed a bug T1-d
      introduced: server-composed boards carried no `valuationOverlay`
      so /trade's banner would have gone silent on them.
      KEY RULE ESTABLISHED: read `valuationBasisOf(contract)`, never
      `settings.valuationMode`. The setting is the request; the
      contract is the result; they diverge on overlay-fetch failure,
      version-pin refusal, and missing roster snapshot.

### Tier 2 — **COMPLETE**, PR #592. Measured live 2026-07-27.

Fetched both leagues' `scoring_settings` straight from Sleeper
(mine 1312736351547850752, baseline 1328545898812170240).

**Correction to ORCHESTRATION.md:41** — it says "91 of 146 keys differ".
Measured today: **95 of 146** differ (mine carries 141 keys, baseline
146). Not a contradiction worth chasing; scoring settings drift and the
doc's figure is from an earlier read. Use the live number, and re-measure
rather than trusting either.

**RECEPTION BANDS — confirmed, and this is the edge.**
Per-catch total = `rec` + the band key. Mine `rec: 0.08`; baseline is
flat `rec: 0.75` with every band 0.0.

    band      mine   baseline   ratio
    0-4 yd    0.25     0.75     0.33x
    5-9 yd    0.50     0.75     0.67x
    10-19 yd  0.75     0.75     1.00x   <- calibration point
    20-29 yd  1.00     0.75     1.33x
    30-39 yd  1.25     0.75     1.67x
    40+ yd    2.00     0.75     2.67x

8.0x spread within my league (0.25 -> 2.00), and the MEAN sits exactly
on 0.75 — which is why every source prices it as flat PPR and every
source is wrong at both ends. A checkdown back is worth a THIRD of what
the market says here; a deep threat nearly 2.7x.

**IDP INVERSION — confirmed, and it is not only sacks.**

    idp_pass_def   2.11 -> 5.32   2.52x  UP
    idp_tkl_loss   2.06 -> 4.25   2.06x  UP
    idp_qb_hit     1.08 -> 2.13   1.97x  UP
    idp_blk_kick   3.80 -> 5.32   1.40x  UP
    idp_ff         3.70 -> 4.25   1.15x  UP
    idp_sack       4.55 -> 2.92   0.64x  DOWN
    idp_int        6.20 -> 5.32   0.86x  DOWN
    idp_fum_rec    3.70 -> 3.19   0.86x  DOWN

Read: coverage + disruption are paid; finishing plays are discounted.
The market prices IDP on sacks and INTs, i.e. exactly the two biggest
DOWN keys.

**THE BLOCKING DEPENDENCY, and it is a Tier 0 gap I created.**
Exploiting the reception bands needs a per-player histogram of
reception depth in Sleeper's exact bands (0-4/5-9/10-19/20-29/30-39/40+).

  * The weekly actuals I persisted DO NOT carry it. WeeklyStatRow keeps
    totals only.
  * The unified nflverse weekly file has `receiving_10/16/20/40`, but
    those are CUMULATIVE thresholds at the wrong boundaries — they
    cannot reconstruct 0-4 or 5-9 at all. Do not try; it will look
    close and be wrong at exactly the band that matters most (0-4 is
    the 0.33x band).
  * The exact source is PLAY-BY-PLAY: `nflverse_direct.fetch_pbp`
    already exists and is UNWIRED. Per completed pass, `yards_gained`
    gives the exact band. ~50k rows per season, so aggregate on ingest
    and persist the histogram, never the raw plays.

**SHIPPED — PR #592, branch claude/tier2-scoring-engine-idp, stacked on #591.**

The IDP half landed and the measurement CHANGED THE DESIGN. Per-player
scoring fit is NOISE, not signal:

    p90/p10 of cohort-normalised per-player ratio, by pool depth
    DL   top24 1.109  top36 1.116  top60 1.115  top120 1.132  all 1.215
    LB   top24 1.113  top36 1.095  top60 1.100  top120 1.099  all 1.144
    DB   top24 1.071  top36 1.075  top60 1.083  top120 1.113  all 1.144

~5% among rosterable players and it GROWS with depth = small-sample
noise. Top "mispriced" names were Kemon Hall / Cory Durden / Jack
Cochrane, i.e. bench bodies near the floor. Position-level median is
stable instead (DL 1.089/1.089/1.088/1.087 across 5x the pool), so the
edge is POSITIONAL: DL +7%, LB +3% relative to DB.

Shipped: `src/league_intel/scoring_fit.py`, a `scoringFit` axis in
adjustment.py, new `SCORING_MEASURED` evidence tier, threaded through
publish.py + gameplan.py. Flag `idp_scoring_fit` defaults OFF. 16 tests,
depth-drift guard observed firing (0.278 vs 0.05).

**RECEPTION-DEPTH INGESTION — SHIPPED ac383b62.**
`src/nfl_data/reception_depth.py` streams pbp (5s, 475 players, 11,217
receptions 2025) into per-player band histograms. 28 tests. Wrote
`data/nfl_data/actuals/reception_depth_2025.jsonl`.

**AND THE PER-PLAYER SIGNAL IS REAL THIS TIME — unlike IDP.**
Measured per-catch ratio (mine/baseline) dispersion by pool depth:

    top24  p90/p10=1.389    top60  1.432    top292 1.554
    top36           1.474   top120 1.515

Compare IDP's 1.07-1.12. This is ~5x the spread AND it is present at
top24 already (IDP's was all tail noise). Extremes are coherent real
players:
    UNDER (deep threats): A.Pierce 1.46 (11% of catches 40+, 0% in 0-4),
                          C.Watson 1.32, T.McLaurin 1.23, G.Pickens 1.21
    OVER  (checkdown RBs): R.White 0.66, C.Brown 0.68, T.Spears 0.71,
                          A.Jeanty 0.73  (47-63% of catches in 0-4)
Median is 0.844 — the typical receiver is worth 16% LESS per catch here
than flat PPR implies, because catch distributions skew short.

**COMPOSED AND WIRED — 09963cb1 + c04fe762. TIER 2 COMPLETE.**

CRITICAL CORRECTION to the roadmap's framing. ORCHESTRATION.md calls
this "the largest unexploited edge identified to date" off the 8x
per-catch spread. The 8x is real; the VALUE impact is not. Receptions
are only a minority of points (RB 0.166 / WR 0.304 / TE 0.330 measured),
so composed multiplier = 1 + share*(ratio-1) lands at:

    min 0.750  p05 0.881  median 0.954  p95 1.001  max 1.048

i.e. ~+/-8%, not +/-120%. Anyone sizing a trade off "8x" is wrong by an
order of magnitude. Operator should re-prioritise Tier 2 vs 3/4 knowing
this.

Kept anyway because dispersion is FLAT across depth (1.072/1.078/1.069/
1.087/1.106) unlike the IDP per-player attempt which fanned out. Median
0.954 is KEPT not normalised (both cards price the same catches, so a
shared shift is a real fact — unlike IDP where the level was rate-card
generosity). Refusal is TOTAL not per-player when dispersion drifts.

Wired as `reception_fit_axis` — the model's only per-player axis.
Joins on `resolve_canonical_name`. Own flag `reception_scoring_fit`
(NOT shared with idp_scoring_fit — that name would become a lie).
Verified end-to-end: 200 players, Pierce 5000->5240, Ford 5000->3750.

### Tier 3 — competitor parity leftovers
- best-ball ADP ingestion
- contracts / snap-share data
- stats tab on player popup

### Tier 4 — **PARTIAL**, PR #593 (stacked on #592)

- [x] **T4-5** FP IDP monotone tests — DONE but landed on the TIER 2
      branch (#592), because it was making that PR's own CI unreadable.
      Tests asserted STRICT monotonicity on int(round(interpolate())) —
      ties are structural. Zero inversions ever measured. Relaxed to
      non-decreasing + added a tie-degeneracy bound. livedata suite is
      now GREEN (302 passed) for the first time.
- [x] **T4-3** KTC tep=3 vs tepp — DONE. Payload identical across
      tep=0/2/3 (MEASURED), so ktcSfTep was always fine. But the
      last-resort DOM fallback reads RENDERED values into the base `ktc`
      source, so tep=3 wrote TE+++ there: 9999 vs 8167 for Bowers, +22%
      on every TE, silently. Fixed to tep=0. 5 tests, AST-sliced so they
      run in 0.18s instead of 241s (importing the scraper EXECUTES it).
- [x] **T4-2** finder mixed-market disclosure — DONE. marketsUsed /
      mixedMarket per trade, mixedMarketTrades in metadata. Not a
      correctness fix (boards are comparable, median ratio 1.000) but
      p10-p90 is 0.888-1.054 so a small mixed delta is not
      distinguishable from board disagreement. 6 tests.
- [x] **T4-1** source-family confidence — MEASURED AND REFUTED.
      CLAIM_REGISTRY said "measure, don't assume from names". Measured:
      publisher name does NOT predict shared opinion.
        raw rho: same 0.951 vs cross 0.952 — cannot discriminate at all
        residual rho: same n=4 median +0.199, cross n=142 median -0.040
        BUT the four same-publisher pairs are +0.609 / +0.245 / +0.154 /
        **-0.664** (fantasyProsFitzmaurice vs fantasyProsSf, ANTI-
        correlated — one analyst departing from his employer's
        consensus). Name-based clustering would DISCARD that signal.
        Strongest residual pairs are all CROSS-publisher, led by
        ktc/otcffbSf +0.891 — tighter than any same-publisher pair.
      Shipped `scripts/audit/measure_source_correlation.py` + 7 tests as
      an INSTRUMENT. Did NOT change confidence buckets: 4 pairs cannot
      justify moving a user-visible field on every player.
- [x] **T4-4** API-stall investigation — DONE, 8b615da1. Found a real
      defect: `_reconcile_orphaned_running_state` set hung/stalled=True
      and BOTH were dead assignments — `_scrape_status_payload` calls the
      reconciler then immediately recomputes `_is_scrape_stalled()`,
      whose else-branch resets both 3 lines later. A worker that died
      mid-run reported `status_summary: 'idle'`, every flag false, no
      error. /api/health's scrape_stalled stayed false so StaleDataBanner
      never fired. Fixed with a durable `interrupted` verdict (property
      of the LAST RUN, not the current moment), cleared by
      _start_scrape_run. New /api/health `scrape_interrupted` + banner
      placed ABOVE the !hasData guard. 6 py + 5 fe tests, observed
      failing pre-fix with assert 'idle' == 'interrupted'.
      GOTCHA for future work: scrape_run_lock is an asyncio.Lock —
      plain .acquire() returns an un-awaited coroutine and the
      reconciler then treats a real run as orphaned. Mis-measured once
      this way.
- [ ] ~9 more the operator inventoried earlier — the inventory itself
      was never located. Ask the operator where it lives.

### Tier 3 — **MOSTLY ALREADY SHIPPED. ROADMAP IS STALE.**

*** MY MISTAKE, RECORDED SO IT IS NOT REPEATED ***
I built `src/nfl_data/snap_share.py` and opened PR #594 WITHOUT first
grepping for existing snap handling. `src/playerctx/` already ingests
the SAME nflverse snap URL, aggregates per player, joins to Sleeper ids,
serves /api/playerctx/player, and renders via PlayerContextSection.
It also does things mine did not: picks the dominant unit (off/def/ST)
so a kicker with one offensive snap is not misfiled, carries recentPct
and a `trend` (recent-minus-season = exactly the "becoming a starter"
signal I claimed was unique to my weekly series), and has collapse
floors. PR #594 CLOSED, branch deleted locally.
LESSON: grep src/ for the capability BEFORE writing a module. CLAUDE.md
rule 2. The trigger for me was "fetch_snap_counts is unwired for MY
store" — which was true and completely beside the point.
NOTE: the remote branch claude/tier3-snap-share could NOT be deleted
(the git proxy rejects branch deletion). Harmless — PR is closed — but
the operator may want to delete it in the GitHub UI.

- [x] **contracts / snap-share data** — ALREADY SHIPPED via playerctx
      (#539). The roadmap item is stale; correct the backlog.
- ~~snap-share (mine)~~ WITHDRAWN, see above.
      THE JOIN WAS THE PROBLEM: snap counts key on pfr_player_id, this
      repo keys on GSIS. fetch_id_map is the cross-walk (22,554 of
      25,035 rows carry both ids). Live 2025: 26,612 rows, 54
      unjoinable across 8 players = **99.80% join rate**, and those 54
      are COUNTED not dropped. Empty cross-walk writes nothing.
      Season mean + weekly series; offense/defense kept separate;
      zero-snap weeks recorded but excluded from the mean;
      meanIsReliable flags <3 games. 10 tests.
- [ ] **best-ball ADP ingestion** — NOT STARTED. Needs a new external
      source; no existing fetcher.
- [ ] **stats tab on player popup** — NOT STARTED. PARTLY EXISTS:
      `GET /api/player/{sleeper_id}/realized` is already implemented and
      the flag `realized_points_api` defaults **ON**. But it had a bug
      (fixed 22f9426d, on the TIER 4 branch): it filtered on
      `player_id_gsis`, the DATACLASS field name, while raw nflverse
      rows key on `player_id` — 0 rows matched vs 17 correct. It
      returned an empty weeks list for every player, always. Invisible
      because NOTHING CALLS IT (the endpoint docstring also falsely
      claimed the flag defaults OFF).
- [x] **stats tab / realized points** — DONE, 4c552a8d (on the TIER 4
      branch, since the endpoint fix was there). `RealizedPointsSection`
      in PlayerPopup now calls the endpoint: total, avg/wk, best+worst
      week. Renders NOTHING unless there are weeks — 200-with-empty is
      the common legitimate case (no stats, unmapped, offseason) plus
      503 flag-off and 401 signed-out. 7 tests, 4 of them on the empty
      paths. Label says "scored on your league's settings" because the
      same stat line is worth different totals per league.
      TEST GOTCHA: the section memoises by sleeper id for 30 min, so the
      first test's payload satisfied every later one and the empty-state
      tests passed WITHOUT fetching. Fixed with a distinct id per test
      rather than exporting a cache-reset helper (which would be
      production API surface added to make tests pass).
      All three data sets are persisted:
        data/nfl_data/actuals/player_week_2025.jsonl   (weekly actuals)
        data/nfl_data/actuals/reception_depth_2025.jsonl
        data/nfl_data/actuals/snap_share_2025.jsonl
      Needs an API endpoint + the popup tab. This is the highest-value
      remaining Tier 3 item — the data exists and nothing surfaces it.
NOTE: operator should re-prioritise Tier 3 vs Tier 2 given the Tier 2
magnitude correction (+/-8%, not +/-120%).

## Log

- 12:15 PR #591 pushed 3f5e852d (ruff fix). Two CI lessons, both cost a
  round trip: CI runs `ruff format --check .` AND a separate
  `ruff check` over changed .py files, and the second exits 123 BEFORE
  the unit-test step. Run both locally every time.
- 12:35 T1-d pushed a59d83be. Hard gate 4246 passed locally.
- 12:42 T1-e pushed 615b7082. TIER 1 COMPLETE. Gates: py 4246, fe 1293,
  ruff x2 clean, bundles under budget.
- 13:0x LAM answered (see below) — hygiene, not suppression. Tier 2 unblocked.
- 13:2x Tier 2 IDP half shipped, PR #592 opened (stacked on #591).
- NEXT: Tier 2 reception-distance half (PBP), then Tier 3.
  Hourly trigger trig_015VpaJK6tAC4b5TL2rdCRQV.

## LAM — ANSWERED 2026-07-27, and it does NOT gate Tier 2

**What it was.** LAM = League Adjustment *Multiplier* (HANDOFF.md:397 —
note `src/league/README.md` calls it "Model", the glossary calls it
"Multiplier"; the glossary is the accurate one). "A position-based value
multiplier; deleted along with positional scarcity."

**Why removed** (`src/league/README.md`, audit F2 / commit 81529e6d):
the upstream sources already price the operator's SF / TEP / IDP config
via their own scoring profiles, and the per-league delta LAM produced
was "small and noisy".

**"Actively stripped from responses"** = `_strip_legacy_lam_fields`
(`src/api/data_contract.py:8243`, called at :8426). Deletes `_lam*`,
`_rawLeague*`, `_shrunkLeague*`, `_leagueAdjusted`,
`_effectiveMultiplier` and top-level `empiricalLAM` from EVERY response.

**This is hygiene, not suppression.** Data files on disk predate the
removal and still carry those fields; without the strip the API would
serve stale LAM numbers computed by code that no longer exists. It is a
good pattern, and it is not hiding a signal anyone should want back.

**Therefore Tier 2 is UNBLOCKED.** LAM was about league adjustment, not
about scoring keys. The scoring-engine divergence is a separate
question and nothing about LAM's removal argues against investigating
it. Note also that league-aware valuation already came back, properly
scoped, as `src/league_intel/` — so the "LAM was deleted" history is
not a precedent against league adjustment per se, only against doing it
as a post-blend position multiplier on a shared board.

**Latent trap found and guarded** (test_single_authority.py): the
stripper matches by PREFIX, and today's `leagueAdjustedDynastyValue`
survives only because it has no leading underscore. A future
`_rawLeagueAdjusted` would silently vanish from every response.

## TIER 3 — REPRIORITISED ON OPERATOR INSTRUCTION, 2026-07-27

Operator asked "what's wrong with tier 3?", then said "Yes. Reprioritize
tier 3." Branch `claude/tier3-usage-signals`, stacked on the Tier 4
branch (the Tier 3 code work had already leaked there via 4c552a8d).

**The roadmap item was stale and three of its four candidates were
already decided elsewhere.** ROADMAP-competitor-parity.md:112 (Phase 7)
still listed them as open; competitor-gap-analysis.md §6 had already
recommended DROP/DEMOTE months of work earlier. Recorded the
dispositions in a table under Phase 7 rather than rewriting history:

  - best-ball ADP  -> DROP (§6). Redraft signal; informs no trade,
    waiver or FAAB decision in a dynasty SF IDP auction league. Plus a
    commercial-platform dependency on unverified terms.
  - player contracts -> DEMOTE (§6). Weak vs snap/target share.
  - snap-share      -> ALREADY SHIPPED via src/playerctx/ (#539).
  - stats tab       -> SHIPPED 22f9426d + 4c552a8d.

**PROMOTED IN THEIR PLACE: the other half of B-5.** 511 lines of built,
tested, ZERO-CALLER Python (opportunity_stats 313, usage_windows 198)
plus usage_signals.py and unified_signal_engine.py — while
feature_flags reported `usage_signals: True` asserting it "fires via
unified_signal_engine". §4.2 of the gap analysis.

### T3-1 snap join — SHIPPED. 99.82% on live data.
`build_snap_index` + `snaps` block + `usage_stat_rows` adapter in
actuals_store. Live 2025: 26,612 snap rows, 22,554 cross-walk pairs,
26,556 indexed, 56 unjoinable across 8 players; 16,964 of 16,995
player-weeks carry snaps. Schema v1 -> v2 (additive).

  THE TRAP, measured not reasoned: the stats release spells playoffs
  `POST`; the snap release spells them `WC`/`DIV`/`CON`/`SB`. A raw
  equality join matches all 18 REG weeks and NO playoff week — 882 of
  19,421 rows — silently. `_normalize_season_type` collapses non-REG
  to POST. Guard observed failing against the naive join.

  None (not fetched) vs 0.0 (measured zero) kept structurally distinct
  all the way to the flat rows. That was PR #591's stated objection to
  joining snaps at all, and it is answered rather than ignored.

  BUG I INTRODUCED AND CAUGHT LIVE: `--refresh` evicted only the
  weekly_stats keys, so the first live run was served my own unit-test
  fixture from the default TTL cache (snapRowsFetched: 1). Now evicts
  snap_counts:{season} and id_map:v1 too.

  TEST-ISOLATION REGRESSION I INTRODUCED AND FIXED: with_snaps
  defaults True, so all 21 existing actuals tests started doing live
  network I/O (33s -> 0.11s after adding explicit _NO_SNAPS seams).

### T3-2 usage-signal engine — MEASURED AND **NOT WIRED**.

Same shape as T4-1: the premise did not survive measurement.

  mean weekly alert rate 17.8% of ACTIVE players, weeks 6-18:
    wk6 16.9  wk8 22.1  wk10 15.4  wk14 19.3  wk18 24.5
  ~150 alerts/week league-wide. One in six players, every week.

  Threshold tuning does NOT rescue it:
    - sd floor makes it WORSE (19% -> 32%) — a floor admits every
      sd==0 window the divide-guard currently skips
    - plain absolute-move rule at 30 PERCENTAGE POINTS still fires 21%
  So the problem is the statistic, not the constants: a 4-observation
  z-score on a bounded 0-1 share does not discriminate, because real
  NFL snap share genuinely moves that much week to week.

  FIRST MEASUREMENT WAS WRONG AND I CORRECTED IT: I first scored
  `latest_window_per_player`, i.e. each player's TERMINAL week, which
  is disproportionately an injury exit. Re-measured at fixed mid-season
  weeks. Conclusion held (17.8% vs 19%) but the method was unsound.

  Shipped instead of a wiring: flag -> default OFF, registry comment
  corrected (it claimed behaviour that had no live path),
  scripts/audit/measure_usage_signal_rate.py, and a wiring guard that
  fails if flag and consumer ever disagree in EITHER direction.
  Guard observed failing under RISKIT_FEATURE_USAGE_SIGNALS=1.

  NOTE the SELL gate could never fire before this branch: it requires
  snap_pct_mean >= 0.50 and snap_pct was always None -> 0.0. Live now:
  722 players clear it. So the snap join is what made the engine even
  measurable — a guard that could not fire, §6.15.

  STILL UNWIRED AND LEFT THAT WAY: opportunity_stats.py (313 lines).
  Wiring it has the same calibration question and no answer yet.

### Tier 3 remaining: NOTHING. best-ball ADP is dropped, not deferred.

## T4-6 — THE FEATURE-FLAG REGISTRY LIED, AND NOT ONLY WHERE THE DOC SAID

Branch `claude/tier4-flag-registry`, stacked ABOVE the Tier 3 branch
(#595) rather than on the Tier 4 branch (#593). Reason: the guard it
adds only passes with #595's usage_signals fix in place, so putting it
on #593 would have needed a duplicate fix and a conflicting rebase.
Recorded as a deliberate deviation from one-PR-per-tier.

MEASURED by walking imports transitively from server.py (123 modules
reachable), then AST-scanning every is_enabled("literal") call:

  of 13 registered flags, 7 CANNOT AFFECT A REQUEST

    LIVE (6)         nfl_data_ingest, realized_points_api,
                     monte_carlo_trade, te_basis_conversion,
                     idp_scoring_fit, reception_scoring_fit
    UNREACHABLE (2)  espn_injury_feed, usage_signals
                     (real gate, module nothing imports)
    SCRIPT_ONLY (1)  depth_chart_validation
                     (gate real; only scripts/refresh_depth_charts.py)
    NO_GATE (4)      value_confidence_intervals, positional_tiers,
                     unified_id_mapper, dynamic_source_weights
                     (no is_enabled call ANYWHERE — only docstrings)

FIVE defaulted True while their comments asserted live behaviour.
Gap-analysis 4.2 named four of them; I found TWO MORE it missed
(unified_id_mapper, dynamic_source_weights), and its
depth_chart_validation entry was imprecise — src/playerctx/ DOES do
depth charts, live and ungated, but that is a DIFFERENT module from
src/nfl_data/depth_charts.py. Conflating them reads as "depth charts
work, so the flag must be live."

positional_tiers is the sharpest one: comment said "Frontend
TierDivider renders when tierId set." TierDivider renders only on
/draft, off a LOCALLY COMPUTED p.tier. The backend never stamps
tierId at all. Two identifiers for two different things — the same
name/predicate gap as tep=3-vs-tepp (T4-3) and the realized-points
player_id_gsis-vs-player_id bug.

WHY THE OBVIOUS GUARD WOULD NOT HAVE CAUGHT IT: "every flag must have
an is_enabled call site" PASSES for espn_injury_feed — it has one,
inside a module nothing imports. Existence-of-a-call-site is a proxy
for reachability the way a substring is a proxy for identity. So the
guard computes the import graph instead.

SHIPPED:
  - _GATE_STATUS as DATA in feature_flags.py (a comment cannot be
    checked; that is how four went wrong at once)
  - tests/api/test_feature_flag_reachability.py re-derives it from the
    real graph every run; 4 guards observed failing pre-fix
  - rule: only a LIVE flag may default True
  - two guards-on-the-guard (import walk must find >50 modules; gate
    scan must find >=5 flags) — without them a broken scan would mark
    EVERY flag unreachable and produce a spectacular false report
  - test_no_flag_is_read_through_a_variable pins the scan's own blind
    spot; it FIRED on feature_flags.py's own snapshot()/effective_flags()
    comprehensions, which I then excluded BY IDENTITY not by pattern
  - /api/status now reports {enabled, gateStatus} via effective_flags()

DOWNSTREAM EFFECT I ALMOST SHIPPED (CLAUDE.md rule 4): changing the
/api/status shape from {name: bool} to {name: {...}} would have made
frontend/app/admin/page.jsx render EVERY FLAG "● ON" — an object is
unconditionally truthy, and that table's entire job is telling the
operator what is running. Caught by grepping consumers before
committing. Admin page now has a Gate column and handles both shapes.

ALSO DELETED A VACUOUS TEST OF MY OWN: the first admin render test
asserted queryAllByText(/Gate/i).length >= 0, true of every possible
DOM. Removed rather than fixed, with the reason recorded in the file.

## TRIGGER FIRED AGAIN 18:3x — ALL FOUR TIERS ALREADY DONE

No tier work outstanding. Every named item across Tiers 0-4 is shipped:
T4-1..T4-6 plus Tiers 0/1/2/3. Summary already posted to the operator.
Did NOT re-do any of it.

Could not delete the trigger: the MCP delete_trigger call requires
operator approval (trig_015VpaJK6tAC4b5TL2rdCRQV). Third attempt.

### DID find real work: the stack had gone un-mergeable

main advanced 13 commits (ALL automated data refreshes, no code).
Test-merged every branch:

    591 chase-upside-persist-actuals   CLEAN
    592 tier2-scoring-engine-idp       CLEAN
    593 tier4-defect-backlog           CONFLICT
    595 tier3-usage-signals            CONFLICT
    596 tier4-flag-registry            CONFLICT
    598 pick-projector                 CLEAN

Conflicts were entirely in generated state:
    data/scrape_state/sleeper_last_success
    data/sleeper_last_good.json

MY FAULT, and worth remembering: a `git add -A` in c3066946 (the KTC
tep=3 commit) swept both files in. They are pipeline output that main's
refresh cron rewrites every ~2h, so my branches and main were both
editing a timestamp — a guaranteed conflict on files no reviewer would
ever read.

FIX: restored both to their merge-base content on all three branches,
so those branches no longer diverge from main on those paths and the
3-way merge takes main's side cleanly. No rebases, no force-pushes,
stacked PRs stay valid. All six branches now CLEAN.

GOTCHA: `git add` REFUSES these paths (.gitignore lists `data/`) but
`git checkout <ref> -- <path>` stages directly, so the commit still
landed. Verified the result rather than trusting the add's error.

LATENT ISSUE LEFT ALONE ON PURPOSE: these two files are TRACKED despite
`.gitignore` having `data/` — the entries predate the ignore rule, so
`add -A` keeps picking up their churn and this will recur. Untracking
them is the real fix; not doing it inside a stack that is waiting on
review. Flagged to the operator.

## THE INVENTORY ARRIVED — UNIMPLEMENTED_BACKLOG.md (this is PR #597's doc)

The "~14 defects" I could never locate. It is §9, and it is 18 rows.
Mapped against what is shipped:

  DONE  #2  test_anchor_curve_extrapolation_monotone  -> T4-5, PR #592
  DONE  #7  "5 dead feature flags"                    -> T4-6, PR #596
            (measured SEVEN, not five, and 2 of them the doc missed)
  DONE  §8.1 source-family confidence -> T4-1 (REFUTED)
  DONE  §8.2 tep=3 vs tepp            -> T4-3
  DONE  §8.3 mixed-market disclosure  -> T4-2
  DONE  §1.x LI-9 gaps, §2.1 TE basis, §4.2 persist actuals, §3 scoring
  DONE  #15 #16 #18                   -> PR #599 (this unit)

  OPEN 13 of 18: #1 #3 #4 #5 #6 #8 #9 #10 #11 #12 #13 #14 #17

### PR #599 — branch claude/tier4-backlog-sweep, off MAIN (not the stack)

**#18 was the real one.** compute_team_strength joined the ROS aggregate
to rosters on an EXACT STRING, and neither side is canonical:
aggregate.py copies each parser's canonical_name verbatim and never
imports resolve_canonical_name (16 of 1087 rows non-lowercase); the
roster side falls back to displayName.

  live: 36 unmapped, 8 RECOVER once both sides resolve
    kam curl->kamren curl, chig okonkwo->chigoziem okonkwo,
    greg rousseau->gregory rousseau, mike evans->michael evans,
    + casing-only: cj gardner johnson, sauce gardner, dax hill,
      pat surtain
  remaining 28 are genuinely unranked — the state `unmapped` reports

NOT COSMETIC: unmapped => ZERO contribution to teamRosStrength =>
biases the projected reverse-standings order behind the Pick Projector
I shipped in #598. Eight phantom zeroes in the draft order.

.lower() would fix 14 of 16 and SILENTLY LEAVE 2 (Greg Rousseau, Chig
Okonkwo need the alias map). Test pins exactly those two.

Fixed at the JOIN not the writer: canonicalName doubles as a DISPLAY
fallback (displayName or canonicalName) in terminal.py + 3 frontend
modules, so normalising the written value would render "cam skattebo".
One field, two jobs, two normalisations.

### THE DOC IS RELIABLE IN KIND, NOT IN NUMBER — verify each claim
  "6 duplicate player rows"       -> 0 today
  "40 of 666 fail to match"       -> 36 unmapped
  "16 non-lowercase canonicalName"-> 16, exact
  "5 dead feature flags"          -> 7
Do not take a row's figures on faith; the direction has been right
every time, the counts have not.

#15 measure_te_demand_actuals.py pinned to a DELETED agent worktree —
every run since has failed. #16 measure_engine_value_divergence.py
defaulted to a dated export that the exporter replaces daily; correct
for exactly one day.

Gates 4185 passed, both ruff clean, 3 guards observed failing pre-fix
(incl. 10.0 > 10.0 — recovered players mapped but contributed nothing).

## PR #599 round 2 — #9, #12, #10 (branch claude/tier4-backlog-sweep)

CONFLICTS: re-verified ALL 7 branches, both against main AND against
each PR's own base. All CLEAN. GitHub agrees (mergeable_state clean on
#593/#595/#596). The earlier scrape-state fix held.

### #9 — the "43 unreachable" number was never re-derivable
scripts/audit/measure_module_reachability.py. Same import walk as the
feature-flag guard, so there are not two answers to one question.

  212 modules / 77,349 lines
  SERVER 117 / 55,062     SCRIPT 14 / 3,376
  TEST    65 / 16,867     ORPHAN 16 / 2,044

The doc's "43 / ~12,571" matches nothing. The single number collapsed
THREE different situations — script-only tooling is not a defect,
test-only is the usage_signals shape, orphan is the real thing.

8 of 16 orphans are dynamic-dispatch (ros/sources, news/providers) —
scrape.py:449 importlib.import_module(src_meta["scraper"]) over
ROS_SOURCES. VERIFIED that call exists before annotating. Annotated,
not accused: the difference between a report someone acts on and one
that gets a working scraper deleted.
Remaining 8 include src.api.chat (351) + src.scoring.archetype_model —
independently corroborates backlog #5 and §6.

### #12 — found them, and my first detector was wrong
FIRST SCAN SAID 1147 CANDIDATES = instrument broken, not the suite.
It only counted bare `assert` and missed every `self.assertEqual`.
Fixed -> 14, then inspection -> most delegate to _assert_*/_check_*
helpers that DO assert. The genuine two:

  gameplan:663  `x == [] or len(x) >= 0`  — TAUTOLOGY. The one
    assertion about rejected targets asserted nothing about them.
    Measured the real invariant (15/15 rejected have empty
    corroborating) and asserted THAT + non-vacuity.
  usage_signals:115 `out == [] or out[0].signal == "BUY"` on a test
    named ..._blocks_current_week. Accepts both outcomes. Its own
    comment admits the guard reads TODAY'S WEEKDAY so the result
    varied by run-day, and the author disabled the assertion instead
    of pinning the clock. Pinned freshness._nfl_now; split into two
    deterministic tests, both branches asserted.

### #10 — worse than the doc said
_pick_value_from_contract falls through to a HARDCODED table
(7000/4000/2000/1200 by round). No contract => 200 with a COMPLETE
board of invented numbers indistinguishable from Hill-curve values.

*** I OVERREACHED AND BACKED OUT ***
My first guard ALSO 503'd on league MISMATCH -> broke
test_league_isolation_invariants.py, which pins today's behaviour
DELIBERATELY and says so: that is Defect D-2 in
docs/python-coverage-audit.md, an OPEN decision (503 per CLAUDE.md's
table vs keep the fallback and fix the doc). The prior author
explicitly declined to pick a side. I picked one without reading that.
Backed out to no-contract-only; added a test that makes an accidental
D-2 resolution loud. OPERATOR DECISION, surfaced not taken.

LESSON: a test whose docstring says "rather than pick a side" is a
deferred decision, not an untested gap. Read the test before changing
the behaviour it pins.

ALSO: my #10 tests initially SKIPPED in CI (registry has no non-default
league) — a guard that skips is not a guard. Built a 2-league registry
fixture so all 6 actually run.

Gates 4199 passed, both ruff clean.
### §9 now: 8 of 18 done. OPEN: #1 #3 #4 #5 #6 #8 #11 #13 #14 #17

## PR #599 round 3 — §9 #11 (conflicts re-verified CLEAN on all 7 branches)

### #11 "pick tethering untested" — WRONG DIAGNOSIS, WORSE REALITY
It IS tested: 15 tests in test_pick_rookie_anchor.py, good ones.
NONE OF THEM RUN IN CI.

    pytest tests/api/test_pick_rookie_anchor.py -m "not livedata"
    -> 15 deselected, 0 run

conftest._LIVEDATA_MODULES marks the WHOLE MODULE livedata (advisory,
non-blocking). Correct for TestAnchorEndToEnd (reads exports/latest/).
WRONG for TestAnchorPassCore, whose own docstring says "Synthetic
playersArray exercises — no live data required" and which guards
PIPELINE STEP 11 (tethers all 72 slot picks' rankDerivedValue).

Same shape as #2 (test_anchor_curve_extrapolation_monotone): a real
test that cannot fail a PR is a test nobody is running.

FIX: split -> test_pick_rookie_anchor_core.py (9 blocking) +
test_pick_rookie_anchor.py (6 advisory). Suite went
4199 passed/325 deselected -> 4212/316. The arithmetic IS the proof:
+9 moved into the gate, +4 new policy guards.

The module-granularity POLICY is sound and unchanged — documented as
deliberate (one central reviewable list vs editing 16 files). Only the
placement of these two classes was wrong.

ALSO FOUND: "test_footballguys_source.py" listed in _LIVEDATA_MODULES
and THE FILE DOES NOT EXIST. A dead exemption that reads as
load-bearing. Removed.

NEW GUARD tests/test_livedata_policy.py — every entry must name a real
file; the rescued module must stay rescued. Both observed failing
against pre-fix conftest.

### FLAGGED NOT FIXED (deliberate scope discipline)
test_dlf_source.py::TestDlfCsvEnrichment builds a TEMP CSV explicitly
"without touching the real CSVs/site_raw tree" — same pure-logic half
in a live-data module. Same move, wants its own change, not smuggled
into a pick-tethering commit.

### §9: 9 of 18 done. OPEN: #1 #3 #4 #5 #6 #8 #13 #14 #17
Pattern worth naming: THREE of the defects so far (#2, #7, #11) were
"the guard exists and cannot fire", and #12 was "the assertion exists
and cannot fail". The doc's descriptions keep understating: it says
untested/dead when the truth is tested-but-never-run.

---

## 2026-07-28 — idp_scoring_fit ON, and the last six §9 rows

### idp_scoring_fit (PR #606, merged)

Operator asked to re-measure properly and turn it on. Re-measuring
surfaced a data defect that had corrupted the original measurement.

`SAF` — nflverse's own spelling for a safety — was in neither
POSITION_ALIASES nor scoring_engine's IDP collapse table, so EVERY
SAFETY was dropped from every scoring comparison. 1,468 of 18,539
persisted 2025 regular-season rows; third-largest defensive group after
LB and CB. Silent by construction: the only trace was an
`unknown_positions_dropped` line that also lists K/P/OL/C/G, so a real
gap looked exactly like intended behaviour. `S`/`FS`/`SS` WERE mapped,
which is why the hole was invisible — safeties appeared handled.

Effect: DB cohort 288 -> 188, DB multiplier 1.0366 -> 1.0594. With the
gap closed the direction is the REVERSE of what #592 recorded:

    DB 1.0366 (n=288)   DL 1.0001 (n=213)   LB 0.9633 (n=203)

Two checks made it a correction rather than a drift. Settings unchanged
(all 8 IDP keys byte-identical to #592's record). And the rate card
mechanically predicts the new order: idp_pass_def 2.52x UP (DB stat,
biggest move on the card), idp_sack 0.64x DOWN (DL signature),
idp_tkl_solo 0.92x DOWN (LB volume).

Blast radius on the live board: 280 IDP rows move (DB +3.66%, DL +0.01%,
LB -3.67%), ZERO non-IDP values change, 544 rows shift rank (median 4,
p90 35) of which 279 move only because IDP passed them.

### The last six §9 rows (PR #608)

#1 REPRODUCED. Mechanism is the FAILURE path. fetched_at advances only
on success, so the post-lock re-check is unsatisfiable while the vendor
is down and every waiter re-attempts serially — each holding an AnyIO
token from the process-wide limiter. 8 callers -> 8 attempts, 18.02
thread-seconds, unbounded in N. Cooldown + wait ceiling -> 1 attempt,
4.00 thread-seconds.

#3 MEASURED, framing wrong. NOT a cold-start cost: warm 6.449/6.643/
6.484s, cold 6.418s. build_public_contract runs every request, 7.26s
alone. player_position called 514,020 times per build. Memoized ->
build ~2.3s, endpoint 2.24-2.53s.

#5 Three layers dead. Removed the dead proxy (a live route that could
only 404). Kept src/api/chat.py. Shipping chat stays a product call.

#6 DESCRIPTION WRONG. /finder does no arbitrage at all — the word came
from a stale header comment. No phantom "two implementations", so no
product decision was ever needed. Engine still has no UI caller; that is
a feature, not a defect.

#14 REPRODUCED, and the earlier "not visible by inspection" explained:
`bottom` existed, but only inside @media (max-width: 768px). Correct on
phones, unanchored everywhere wider.

#17 Kept unwired, now with a tripwire. Its `nginx -t` guard cannot catch
the case that matters — a config reverting certbot's edits is still
VALID nginx.

### THE MEASUREMENT LESSON, worth more than any single fix

My first check of whether the #3 memo changed output said DIFFERENT.
Taken at face value that reverts a correct 2.7x fix. The contract embeds
wall-clock stamps, so two runs of the SAME code never match either.

What caught it: comparing an implementation against ITSELF before
comparing it against the alternative. A differential test without that
control cannot distinguish "my change broke it" from "this was never
deterministic".

Corollary to §12's three cheap checks, and the same shape as the
"measured the instrument and described the vendor" error in §12:
BEFORE concluding a diff means your change is wrong, confirm the
baseline is stable.

### §9: 18 of 18 worked. 14 fixed, 2 standing policy, 2 open as FEATURES
(#6 wiring the arbitrage engine to a UI; #5 shipping chat). Both are
product calls with the defect half already closed.
