# DFS — decisions

ADR numbers are local to this file (cite as `docs/dfs/DECISIONS.md ADR-DFS-00N`).

## ADR-DFS-001 — MILP solver: HiGHS via `scipy.optimize.milp` (2026-09-30)

**Context.** The runtime had no numeric stack (no numpy/scipy/PuLP/OR-Tools). A DFS lineup is an
assignment problem with salary, team, game and user constraints; later phases (simulation) will
need numpy regardless.

**Options.** (a) hand-written branch-and-bound — exact only if proven, and dominance pruning is
unsound under team/game/uniqueness constraints; (b) PuLP + bundled CBC (EPL, ships a binary);
(c) SciPy's HiGHS interface (BSD/MIT, wheels for 3.9–3.13, maintained, `mip_rel_gap=0`
certifies optimality, time limits built in).

**Decision.** (c). Imported lazily inside the solver so server start-up is unaffected. Pins
`numpy~=2.0`, `scipy~=1.13`. Every solver answer is re-checked by an independent pure-Python
validator, and brute-force enumeration tests pin exact agreement on small pools.

**Consequence.** Adds ~60 MB of wheels to the venv. If the box cannot install them the API answers
`503 SOLVER_UNAVAILABLE`, never a fabricated lineup.

## ADR-DFS-002 — Readiness is per platform × sport × format × rule version

`not_implemented` → `research_only` (encoded, unverified) → `money_ready` (rules **and** export
verified with cited evidence). The loader refuses `verified` without evidence. `mode: "money"`
fails closed with `RULESET_UNVERIFIED`. A slate imported under a superseded version answers
`RULESET_SUPERSEDED` rather than being re-read under new rules.

## ADR-DFS-003 — Multi-lineup builds are sequential and say so

Lineup *k* maximizes projection subject to uniqueness vs 1..k-1 and exposure caps. That is a
construction method, not a jointly optimized portfolio (Phase 5). Exposure caps are
`floor(pct × N)`; locked players are exempt from the global cap. A shortfall returns the lineups
built plus the isolated conflict; nothing is relaxed to reach N.

## ADR-DFS-004 — Platform season average is opt-in and labelled

A salary file's average is a past observation, not a forecast. It is used only where the owner
ticks the box, stamped `projection_source: platform_season_average`, and shown with an "avg" mark.
DraftKings publishes no games-played count, so an average of exactly 0 is treated as missing.

## ADR-DFS-005 — DFS is its own nav group and skips the dynasty data prefetch

"DFS" is a separate product family; mixing it into Rankings/Trades would imply its numbers are
dynasty value. `/dfs` is on `NO_PLAYER_DATA_ROUTE_PREFIXES`, so the shell does not fetch the
multi-MB dynasty contract there. Future DFS surfaces join this group, not new top-level entries.
Adding a seventh top-level group is the owner's explicit instruction (§4 "available through the
application's normal navigation"); desktop top-bar fit needs visual verification at 1024 px.

## ADR-DFS-006 — Domain isolation is tested, not promised

`src/dfs/` may not import `src.api.data_contract`, `src.canonical`, `src.consensus_edge`,
`src.trade`, `src.bdvm`, `src.league_intel` or `src.model_registry` (AST test). Storage is
`data/dfs/` only. Seasonal/dynasty evidence may be shared later only through a typed contract.

## ADR-DFS-007 — Identity joins are exact within a slate

Projection rows join by platform ID, else by `name_clean.normalize_player_name` + team (+ position).
Ambiguous and disagreeing rows are quarantined. Cross-provider canonical identity (Phase 3) must
extend `src/identity/`, not create a DFS-local matcher.

## ADR-DFS-008 — Contests: separate dimensions, integer cents, nothing assumed (2026-09-30)

A contest's roster format, entry restriction (`maxEntriesPerUser`), guarantee status and payout
shape are independent fields; the shape (`head_to_head` / `fifty_fifty` / `double_up` /
`multiplier` / `tournament`) is DERIVED from the ladder and is descriptive only. Money is integer
cents end to end (Decimal at the edges, never float). The tie rule defaults to `unknown`, which
makes tied payouts unavailable rather than assuming split-positions; a non-whole-cent split is
returned as an exact fraction because the platform's rounding is unverified. An underfilled
contest is an `overlay` only when `guaranteed is True` and prizes exceed fees actually collected.
The entry cap is a hard constraint that needs an explicit spend limit; the recommended count is a
separate, still-unavailable answer. Contests are versioned per owner (append-only), so builds can
later cite the exact version they were evaluated against.

## ADR-DFS-009 — Slates come through adapters into one canonical model; no unofficial endpoints (2026-09-30, owner addendum)

`src/dfs/slate.py::CanonicalSlate` is the only slate shape downstream code reads. Adapters map
into it: official platform files (auto-detected from their own header, position set and roster
labels) and licensed feeds (`src/dfs/providers.py`). Unofficial DraftKings / FanDuel endpoints,
scraping and account automation are never a production dependency. A provider's schema being
PUBLISHED is recorded as `documented`, never `verified`; only observed data with evidence
promotes a cell. The SportsDataIO adapter reuses the repo's existing `SPORTSDATAIO_API_KEY`
header convention and is flag-gated OFF. Detection refuses rather than guesses: ambiguous
position sets are `UNSUPPORTED_SLATE`, a file for another platform is `CSV_WRONG_PLATFORM`, a
recognised-but-unencoded combination (MMA, Showdown, NBA, NHL today) is `UNSUPPORTED_FORMAT`
with what was recognised. The platform's own per-player roster slots are cross-checked against
the encoded rule set and any disagreement is shown, never auto-resolved — that is how an
unverified rule set accumulates evidence.

## ADR-DFS-010 — Showdown: platform rows, athlete identity, multiplier at the slot (2026-09-30)

DraftKings Showdown files list each athlete twice (CPT row with its own ID and 1.5× salary; FLEX
row). The rule set's `eligibilityBasis: platform_slots` makes each slot accept only rows the
platform labelled for it. Rows of one athlete share a `group_key`, and the optimizer and the
independent validator allow at most one row per group. A group is kept ONLY for a genuine
CPT + FLEX pair; any other name/team/position collision keeps separate identities so projection
joins stay quarantined. The captain multiplier lives in the rule set (`slotPointsMultipliers`)
and is applied once — in the objective and in the lineup payload's `slotProjection` — while the
stored projection is never changed. The platform-slot cross-check is `not_applicable` here
(comparing the file's labels with themselves would manufacture agreement).


## ADR-DFS-011 — Minimum exposure is latest-deadline sequential forcing (2026-09-30)

**Decision.** `playerMinExposure` converts to `ceil(pct × N)` appearances (never rounded down;
the mirror of the max's floor). While building lineup *k*, a player is forced in only when every
remaining lineup, this one included, must carry them to reach the minimum. A min above the max, a
min on an excluded player, and a min on an unprojected player are refused before solving.

**Why.** It keeps the first lineups the owner's best by projection and never forces a player the
optimizer picks on its own. It is a construction method, not a joint portfolio optimum, and the
build's `methodNote` says so. Front-loading or even pacing would not remove the failure it has
(two players competing for one slot both due at once). That failure is reported as an isolated
`min_exposure` conflict plus `minimumExposureUnmet`; nothing is relaxed. Joint portfolio
construction belongs to Phase F.

## ADR-DFS-012 — ARCHITECTURAL INVARIANT: every HiGHS solve runs on one pinned thread (2026-09-30)

**Context.** HiGHS (reached through `scipy.optimize.milp`) keeps native worker threads tied to the
thread that called it. The API ran builds through FastAPI's threadpool, so successive solves came
from different request threads. The Python process then died with a **Windows access violation in a
native thread with no Python frame** — about 1 run in 5 of `pytest tests/dfs`, and in production it
would take down the whole backend process, not one request. It looked like a random flake until the
faulthandler header was kept.

**Decision (invariant).** No code may call `milp` / HiGHS directly from a request, worker or
simulation thread. Every solve goes through `src/dfs/optimizer.py::_solver_pool()` — one
long-lived `dfs-highs` thread — which also serializes solves. Builds are time-budgeted, so
serialization is acceptable; parallelism, when needed, comes from **processes**, never threads.

**Enforced by.** `tests/dfs/test_optimizer.py::test_every_highs_call_runs_on_the_one_solver_thread`
(behaviour: solves launched from several threads all execute on `dfs-highs`) and
`tests/dfs/test_solver_invariant.py` (structure: the only `milp` call site under `src/` is the pool
submit in `optimizer.py`). Fixed on #1534 (`bb7046b9d`); 20/20 clean suite runs after the fix.

**Consequence.** Field and contest simulation (Monte Carlo) never call the MILP per sample; any
future solver-heavy job runs in a bounded background worker that still routes through the pool.

## ADR-DFS-013 — Point-in-time evidence: its own DFS ledger, as-of by what we HELD (2026-09-30)

**Context.** Evaluating ownership, field and portfolio models honestly requires reconstructing what
was knowable before lock, separately from what happened. `src/history` already owns as-of semantics
for dynasty values, but DFS data may never enter dynasty valuation (ADR-DFS-006).

**Decision.** `src/dfs/pit.py`, in the DFS SQLite file, borrowing `src/history`'s rules (a future
observation is never selectable; missing is stated). Observations are append-only and carry both
`observed_at` (source publish / export time) and `recorded_at` (when we stored it). `as_of(T)` takes
the latest value with BOTH ≤ T — what we actually held, which is the only honest input to a
historical replay. A pre-lock view past lock, or on a slate whose lock is unknown (any unknown start),
is refused. Owner imports are recorded at IMPORT time, never earlier. Truth (post-lock ownership,
points, standings, payouts) lives only in results records. Models are versioned with immutable params
per version, a code SHA, and promotion criteria fixed AT REGISTRATION; `promote()` refuses an
evaluation window that starts before registration, too few samples, or a failure to beat the
baseline by the predefined margin; promotions and rollbacks are append-only events. Decisions are
frozen with the as-of inputs digest and labelled `pre_lock` only when made before a known lock.

**Consequence.** Every later model (ownership, field, duplication, contest simulation, portfolio)
reads inputs through `as_of` and writes decisions/evaluations here, so a backtest can prove it saw
no post-lock information.

## ADR-DFS-014 — Ownership: structural baseline + source ensemble, scored per component (2026-09-30)

**Context.** Ownership drives field simulation and duplication. Third-party projections vary in
quality, update times, and availability; averaging them blindly hides a stale or poor source, and
with no data at all there must still be a baseline to beat.

**Decision.** `src/dfs/ownership.py`. (1) A structural baseline that needs no external data: each
roster slot's 100% spread over eligible players by `exp(bv·z(pts/$1K) + bp·z(projection))`, capped at
100%, totalling exactly 100% × slots; `bv = bp = 1` are declared UNCALIBRATED priors;
`fit_structural` refits them only on settled slates (training error is labelled as such). (2) A
source ensemble over values held as-of T: equal weights until a source has ≥ 60 scored players,
then inverse historical MAE; values older than 24 h at T are flagged stale and not used as current.
(3) Owner overrides, labelled. Every player row names its method. Results imports score each
source, the ensemble and the baseline against realized %Drafted, each forecast as of LOCK, and store
the scorecards (MAE, RMSE, bias, Spearman, bucket calibration, top-10 overlap, bootstrap CI, n) in
`pit` scoped by sport / platform / format / slate size.

**Evidence standard.** Nothing here is shown to be accurate yet: there is no settled historical data.
A challenger (a refitted baseline or a new source mix) is promoted only through `pit.promote` with
≥ 150 holdout players and an MAE at least 0.25 points better than the incumbent, on a window after
registration.

## ADR-DFS-015 — Joint outcomes by Gaussian copula over each player's own marginal (2026-09-30)

**Context.** GPP value lives in the tails and in how players move together; a mean projection and
independent sampling both miss it. The data available per player differ (an imported StDev,
imported percentiles, or nothing), and the correlations are sport-specific.

**Decision.** `src/dfs/distributions.py`: a canonical `PlayerDistribution` (mean used, sd,
quantiles, family, basis, uncalibrated flag) with marginals `normal` (imported sd), `quantile`
(piecewise-linear inverse CDF through imported percentiles, tails extended at most one outer-segment
width) and `prior` (sport/position coefficient-of-variation priors — only when explicitly allowed,
always flagged; none for MMA, which is bimodal). No range → no distribution. Joint sampling is a
Gaussian copula: correlated normals (matrix repaired to the nearest valid correlation, repair
reported) → uniforms → each player's own inverse CDF, so marginals are exact and dependence comes only
from `src/dfs/correlation.py`. Rows of one athlete (Showdown CPT/FLEX) share a draw. Seeded, bounded
(`MAX_SIMS` 20k, `MAX_PLAYERS` 1k), numpy/scipy.special only — never the MILP (ADR-DFS-012).
`correlation.py` has one module per sport behind `pairs()`, all declared conservative PRIORS
(`correlation.priors@1.0.0`) — directions from DFS game logic, magnitudes shrunk; a fitted model
replaces a module through the registry, never by editing constants in place.

**Evidence standard.** A normal-copula dependence is a modelling assumption (tail dependence is
understated). Whether correlated sampling improves contest-outcome calibration over independent
sampling is exactly what the backtest harness must show before it is claimed.

## ADR-DFS-016 — Field model: ownership-weighted random-order sampling, raked, fit reported (2026-09-30)

**Context.** Contest value depends on what the OTHER entries look like. Opponents do not optimize
our projections, so "run our optimizer many times" is the wrong field.

**Decision.** `src/dfs/field.py` (`field.sequential_raked@1.0.0`): each opponent lineup fills slots
in a RANDOM order, drawing among eligible, unused (identity-aware), budget-feasible players in
proportion to their weight; positively correlated partners of a pick are boosted by
`1 + stack_strength·rho` (the correlation priors); the lineup must pass the independent validator
and use ≥ 97% of the cap (prior). Weights are raked `w *= (target/realized)^0.8` toward the target
ownership, and the residual gap, salary-used quantiles, stack shapes and in-sample duplication are
reported as `fieldFit`. The field is a weighted sample of ≤ 20,000 lineups.

**Measured on the synthetic DK NFL fixture (2,000-lineup fields, seed 2):**
- A FIXED slot order (QB…DST) left the last slot only its cheapest player: the $1,000 DST was drafted
  97.5% vs a 3.3% target, and raking could not help (weights are moot when one player is affordable).
  Random order fixed it (sample duplication 16% → ~1%).
- The structural ownership baseline had a real bug (capped surplus redistributed across positions;
  QB total 116%) — fixed in PR B with a regression test.
- Even corrected, structural targets are **salary-infeasible**: an irreducible ~5.4-point MAE gap
  that raking does not close (5.38 → 5.40 over 1→6 rounds). Against a FEASIBLE target (another
  field's frequencies) raking works: 1.14 → 0.44 points (sampling noise at this size).
- Hence `field.implied_ownership` — ownership read off a generated field — is feasible by
  construction and is registered as the ownership CHALLENGER to the structural baseline. Whether it
  predicts real ownership better is unknown until settled contests are scored.

## ADR-DFS-017 — Duplication: naive baseline kept; zero-truncated log-linear challenger (2026-09-30)

**Context.** A GPP win shared with ten identical lineups pays a tenth. The textbook estimate
(`N × Π ownership`) ignores that fields crowd onto max-salary builds and that ownership forecasts are
noisy, but it is the benchmark anything better must beat.

**Decision.** `src/dfs/duplication.py`. Naive `N·Π own` is always reported. The challenger
`E = N·exp(a)·Π own^b·exp(c·salary_left_$1K)` nests the naive model (`a=0, b=1, c=0`) and is fitted
by **zero-truncated Poisson** MLE (a results file lists only lineups someone entered, so treating
absent lineups as zeros would bias every parameter), with bounded parameters and inverse-rate
weights for sampled singletons. Results imports now keep a compact duplication fit sample (every
repeated lineup + a seeded 2,000 singleton sample) and score the naive baseline against observed
copies with the AS-OF-LOCK ownership forecast (never realized ownership), storing log-likelihood and
calibration bands in `pit`.

**Evidence.** Synthetic recovery only: from 60k simulated lineups (truncated to those that appear)
the fit recovers `b`, `c` within ±0.08 and beats naive on a separate holdout. No real contest has
been scored yet; the fitted model stays a challenger until `pit.promote` sees a holdout win.

## ADR-DFS-018 — Contest Monte Carlo on one joint draw; field and ours scored together (2026-09-30)

**Context.** Contest value is rank-dependent: it is set by where our lineup lands against a field
that shares the same player outcomes, how many identical lineups split the place, and the exact
ladder. Scoring our lineups against independent draws, or the field independently, erases exactly
the leverage a GPP strategy is about.

**Decision.** `src/dfs/contestsim.py` (`contest.montecarlo@1.0.0`) + `src/dfs/pipeline.py`. Draw
all players once per simulation (copula + correlation priors); score the field sample and our
lineups on that draw; rank by binary search in each simulation's sorted field, scaled M → N; copies
of our lineup are the field-sample entries that tie it exactly if present, else Poisson draws from
the duplication model — never both; tied places are split by averaging the prize-by-rank table;
our entries rank JOINTLY (a portfolio cannot take first twice). Unknown tie rule → split assumed and
disclosed; non-cash places excluded from cash EV and disclosed. Outputs carry Monte Carlo standard
errors. `pipeline.prepare` builds every input from what was HELD pre-lock (`pit.as_of`) and refuses
missing outcome ranges unless flagged priors are explicitly allowed. `POST /api/dfs/simulate` is
bounded (≤ 2,000 sims, ≤ 3,000 field sample; ~2 s on the fixture).

**Verified exactly / statistically:** a lineup that always wins collects exactly first prize; a
guaranteed 4-way tie splits places 1–4 exactly; two dominant entries collect 1st + 2nd, never 1st
twice; in a symmetric 8-entry contest P(win) = 1/8 ± 0.02 and EV = pool/8 within 3 SE.

**What it is NOT.** A model output under stated assumptions (priors for spreads and correlations,
modelled ownership and field). It is not evidence of profitability; that needs the backtest harness
and, beyond it, forward results.

## ADR-DFS-019 — Portfolio: sample-optimal candidates, greedy on simulated payouts, conservative entry count (2026-09-30)

**Context.** Entries in one contest share outcomes, so a portfolio's value is not the sum of its
lineups' rankings. The objective is a choice (profit vs bankroll growth vs downside), and the EV
estimates are themselves uncertain.

**Decision.** `src/dfs/portfolio_opt.py`. Candidates = projected-points baseline builds + MILP
solutions on sampled joint outcome draws ("sample-optimal", serial through the pinned solver
thread), capped at 80. Each is simulated alone against the SAME field and draws, then chosen
greedily under `ev`, `log_growth` (requires a bankroll larger than the fees) or `mean_downside`,
honouring exposure caps and the contest's entry ceiling (`contests.entry_upper_bound`). The
recommended entry count stops at the first entry whose marginal expected profit has a lower 90%
bound ≤ 0 — never more than requested or allowed. No Kelly sizing. The chosen set is re-simulated
jointly; a PAIRED comparison with the same-size projected-points portfolio (same draws) reports the
difference and its SE; the decision (selected, rejected with reasons, objective, inputs digest,
timing) is frozen in `pit`. `POST /api/dfs/portfolio`, bounded; nothing is entered or submitted.

**Known approximation.** Greedy selection scores each candidate alone (ignoring rank interaction
with our other entries); the final numbers come from the joint re-simulation. The baseline
comparison is WITHIN the model: it shows the optimizer does what the model rewards, not that the
model is right — that is the backtest's job.

## ADR-DFS-020 — Backtest: chronological, pre-lock only, truth after forecasts, counterfactual payouts (2026-09-30)

**Context.** A backtest that can see post-lock ownership, late news, actual points or later
projection updates proves nothing. A replayed portfolio also needs a realized outcome that does not
depend on the simulator it is testing.

**Decision.** `src/dfs/backtest.py` + `POST /api/dfs/backtest`. Settled contests are replayed OLDEST
LOCK FIRST; a slate with an unknown lock is skipped (named). At T = lock every input comes from
`pit.as_of(T, pre_lock)`; the inputs digest is taken before the result record is opened and re-checked
after the replay (an explicit error, not an assert). Forecasts: ownership structural prior, field-
implied challenger, source ensemble; each projection source as held. Optional portfolio replay uses
the same `portfolio_opt` code as the live endpoint. Scoring after reveal: ownership + projection
scorecards; replayed optimizer AND same-size projected-points portfolios get COUNTERFACTUAL realized
payouts — realized lineup points ranked in the contest's real full-field score distribution with
exact ties (our entries joined in); a lineup with an unscored player is `unscorable`, never 0 points.
Realized profit is reported per arm with n and a 95% CI (none for n = 1), plus the PAIRED difference;
predicted EV vs realized payout feeds contest-model calibration. Summaries are stored as `backtest`
evaluations with the window, for `pit.promote`; nothing is promoted here. Replayed decisions are
made after the fact: historical evidence, never forward evidence.

**Test that matters.** A "late" ownership source recorded after lock and matching the truth exactly
is invisible to the replay: the ensemble's MAE stays > 0.5, and the source never appears.
