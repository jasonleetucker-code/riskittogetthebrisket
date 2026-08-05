# Consensus Edge — Architecture Decision Records

## ADR-001: fair value is a leave-one-out board, not BDVM
**Original spec idea:** compare the market against BDVM's fundamental
value, which is computed with zero market inputs and is therefore the
cleanest possible independent estimate.
**Finding:** BDVM returns nothing. `data/bdvm/` does not exist on the
serving box and `run_valuation` answers `status="no_projection_snapshot"`.
Building the snapshot would produce the §8.3 reconstructed baseline —
realized *prior-season* PPG — and `src/bdvm/projections.py:1-17` states
plainly that "the platform currently has **zero** forward-looking
statistical projection sources". A fundamental value built from last
season's points is a lagging indicator: it buys post-breakout players
whose price already moved and sells post-injury players who are often the
real buys. `config/bdvm/params_v1.json` additionally labels every one of
its constants as a starting prior, "NOT backtested truth".
**Decision:** fair value is the existing 21-source blend recomputed with
the market anchor (and everything correlated with it) removed — via
`build_api_data_contract(source_overrides=...)`, the pipeline that
already exists. It prices 699 of 973 rows today versus BDVM's 0, and its
accuracy can actually be measured.
**Status:** accepted 2026-08-04. BDVM remains the better basis once a
real projection feed exists; revisit then.

## ADR-002: correlated sources leave the blend together
**The defect.** `fantasyNavigatorSf` republishes KTC-derived values —
every row carries a `ktc_player_id` and the site credits KeepTradeCut as
a source. The registry documented this in a prose comment and did
nothing about it, so excluding `ktcSfTep` to build a KTC-free board still
left **440 rows** carrying a KTC-derived vote.
**Why a comment could not fix it.** The blend tolerates correlation (the
count-aware aggregation and per-player Hampel filter are robust to it),
so nothing was broken on the default board and nothing ever would be.
The failure only appears in the one operation that must not contain KTC.
**The mechanism chosen:** a `correlation_group` field on the registry,
exported through `get_ranking_source_registry()`, mirrored in the
frontend registry, and enforced by `expand_correlation_groups`. Sources
with no declared group are singletons named after themselves, so the
expansion is total and no caller special-cases the undeclared majority.
**Inertness is the load-bearing property.** The default board must not
move because we added metadata. Verified by hash across stash/unstash
and pinned by a test that strips the field at runtime and asserts the
board is identical.
**Status:** accepted 2026-08-04.

## ADR-003: the fair-value board suppresses the market-corridor clamp
**The defect.** `_market_anchor_value_for_row` reads the anchor out of
`canonicalSiteValues` — the scraped number — not out of the blend vote.
So dropping a source from the blend does **not** stop the clamp pulling
values back toward it. Measured with `idpTradeCalc` excluded: 101 IDP
rows were still clamped toward idpTradeCalc, mean shift 552 points.
**Why that is fatal here and harmless elsewhere.** On the live board the
clamp does real work against blend drift. On a fair-value board it pulls
the estimate toward the exact price the estimate is about to be compared
against, shrinking every gap toward zero — worst precisely where the
signal claims most confidence.
**Decision:** `suppress_market_corridor_clamp`, default False. One
caller sets it. The live board is unchanged.
**Status:** accepted 2026-08-04.

## ADR-004: the rookie ladder needed no fix, and needed a test
The rookie boards inherit KTC's *scale* by crosswalking through a ladder
built from KTC's live rookie ranks — a third leak. It turned out already
closed: the ladder pass guards on `ref_key not in active_keys`, so
excluding KTC skips the translation (verified: 0 of 25 surviving ladder
translations route through `ktcSfTep`). Nothing pinned that guard, and it
is now load-bearing for a correctness property in a different module.
**Decision:** no code change; a test asserts it stays closed.
**Status:** accepted 2026-08-04.

## ADR-005: the historical panel comes from git, not from waiting
**Original spec idea:** stand up a snapshot writer and accumulate a panel
over the coming months, shipping shadow-only until then.
**Finding:** the panel already existed. The discovery pass measured a
shallow clone (51 commits, all one day) and concluded there were 21 days
of three-source history. `scheduled-refresh.yml` commits
`CSVs/site_raw/` and `exports/latest/` with `git add -f` every two hours;
after `git fetch --unshallow` the real figure is **110 usable as-of
dates across 24 sources**, 2026-04-16 to 2026-08-03.
**Decision:** reconstruct as-of boards with `git show` rather than
waiting for calendar time. `panel.py` materialises a date's CSVs into a
temporary tree and runs today's pipeline over that date's payload.
**The caveat is in the data, not the prose.** `PanelDay.model_is_current`
is always True: inputs cannot leak, but the model is current, so the
panel answers "would this signal have ranked players usefully?" and not
"what did the site show that day?".
**Status:** accepted 2026-08-04.

## ADR-006: a replay that does not redirect the CSV read is contaminated
**The defect.** The pipeline enriches `canonicalSiteValues` from
`CSVs/site_raw` on disk, which is always current. A historical replay
that passed only the historical *payload* silently mixed today's source
values into a past board. Measured on 2026-05-01: **682 of 692** priced
rows differed. The result looks like a valid board, and every metric
computed from it would be inflated by data from the future.
**Decision:** `csv_root` on `_enrich_from_source_csvs` and
`build_api_data_contract` (default None → live path byte-identical), and
`fair_value_index` requires it for any historical call. Pinned by a test
that fails if the redirect ever stops making a difference — because at
that point the suite would be proving nothing.
**Status:** accepted 2026-08-04.

## ADR-007: outcomes are cohort-excess returns over non-overlapping folds
**Excess, not raw.** If the board drifts up 3%, a player who rose 3% has
told us nothing. Raw return scores every player in a rising market as a
successful buy call and makes any signal look predictive exactly in the
periods it was least useful. The peer group is fixed at the **origin**
price, so a player cannot be judged against a cohort he joined because of
the move being measured.
**Non-overlapping folds.** A 14-day horizon over 110 days offers 96
origin dates but only 7 independent observations. Adjacent origins share
almost their entire holding period; treating them as independent would
shrink the error bars roughly fourfold and manufacture significance from
nothing. The summary reports the fold count beside the mean, because
rho +0.126 over 7 folds and over 700 are different claims.
**Benchmarks are mandatory.** Every fold scores the candidate against the
market value itself (is this just "cheap players bounce"?) and a seeded
random series (what does zero skill look like at this n?), on the same
intersection of players so no benchmark is measured on an easier subset.
**Status:** accepted 2026-08-04.

## ADR-008: the mispricing component earned its place; the composite has not
Measured 2026-08-04 against cohort-excess market return:

| horizon | usable folds | mean rho | folds positive | beat market-value |
|---|---|---|---|---|
| 7d | 14 | +0.089 | 12/14 | 13/14 |
| 14d | 7 | +0.126 | 7/7 | 7/7 |
| 30d | 3 | +0.111 | 3/3 | 3/3 |

24 independent folds at ~680 players each, beating the market-value
benchmark in 23 and a random benchmark in 22. Modest, consistent, and
replicated across three horizons.

**What that does and does not license.** It licenses shipping *market
mispricing* as a measured signal. It does not license a composite: Sharp
Flow cannot be validated in any environment that lacks the prod-only
`data/intel/` ledger, and an Opportunity/Risk component has no
forward-projection feed to rest on. Combining a measured component with
two unmeasured ones and reporting one number would launder the
unmeasured through the measured.
**Decision:** components are scored and reported separately. The
composite ships behind a flag, default OFF, with weights labelled
provisional, and does not claim validation the parts do not have.
**Status:** accepted 2026-08-04. **Partly superseded by ADR-013 the same
day:** the claim that Opportunity "has no forward-projection feed to
rest on" was wrong twice over — it rests on board history and playerctx,
not projections, and its momentum axis turned out to be measurable after
all. It was measured, the result was a null, and its weight is now zero.
The reasoning about Sharp Flow, and the general rule against laundering
unmeasured components through measured ones, stand unchanged.

## ADR-009: the measured target is market movement, and the docs say so
The panel covers the 2026 offseason. No games were played in it, so a
production target — realised points under this league's scoring — is
**unavailable**, not merely unmeasured. A signal validated against market
movement predicts that the price will move, which is the right target for
a trade recommendation and the wrong one for a start/sit decision.
**Decision:** every payload and every measurement states its target
explicitly. When an in-season panel exists, production outcomes get their
own evaluation and their own verdict rather than being folded into this
one.
**Status:** accepted 2026-08-04.

## ADR-010: the mispricing score saturates smoothly rather than clamping
**The defect.** The z-score was hard-clamped at ±3 sigma. Compressing the
tail is right — it is populated by identity errors and stale rows as well
as genuine mispricing, and an 8-sigma row should not dominate a ranking.
But a clamp discards ORDER, not just magnitude. Measured on the live
board: 23 of 699 scored rows sat exactly on the clip, and among the
clipped buys the underlying gaps ran from +20% to +229%, every one scored
identically. The published "Top 20 Buys" was an arbitrary tie-break over
eleven players, ordered by whatever sequence they happened to be in — at
precisely the point of the product a user reads first.
**Decision:** `score = tanh(z / 3)`. Same compression, still bounded,
strictly monotone everywhere, so ordering survives into the tail. The raw
`z` is reported unsaturated so two extreme rows remain comparable.
**Verified not to change the measurement:** Spearman is rank-based and
tanh is monotone, so the backtest returns exactly +0.126 over 7/7 folds
as before. Re-run rather than assumed.
**Status:** accepted 2026-08-04.

## ADR-011: Sharp Flow bounds any single contributor
**The defect on main.** There is no per-manager or per-league cap
anywhere in the signal. One qualified manager active in ten leagues
contributes ten observations to an asset, and `breadth_factor`
(`m/(m+3)`) saturates too quickly to push back.
**Decision:** cap each manager's and each league's SHARE of one asset's
evidence, applied as a scaling factor on the observations so buys and
sells shrink together and capping can never flip a direction. Capping
shares rather than counts keeps it scale-free — ten managers at 10% each
are untouched; one at 80% is cut.
**Also decided here:** a beta-binomial posterior replaces the
multiply-everything heuristic, so direction and certainty travel
separately; evidence decays on a declared half-life; and below a minimum
effective sample the answer is `None` with a reason, because "we do not
know" and "the market is neutral" are different claims. The incumbent
formula is retained as `legacy_signal_strength` for benchmarking.
**Unfixable here, and stamped rather than hidden:** the ledger stores no
consideration, so an acquisition is direction and never evidence of a
good price. `priceAware: false` rides on every payload.
**Status:** accepted 2026-08-04. Not validated — no ledger exists outside
production, so none of this has been checked against an outcome.

## ADR-012: the feature flag defaults OFF, and /methodology ignores it
Two of the three components have never been validated. A composite of
one measured and two unmeasured components is defensible as a labelled
experiment and not as advice, so `consensus_edge` defaults OFF and every
payload carries `experimental: true` plus a per-component `validated`
flag sourced from `COMPONENT_VALIDATION` — a property of the data, so the
UI cannot drift from the truth by restating it.
**The one exception:** `/api/consensus-edge/methodology` answers even
when the flag is off. A user who cannot see the board should still be
able to read what it is and what it does not claim.
**Status:** accepted 2026-08-04.

## ADR-013: the momentum axis was measurable, and it did not earn a weight
**The defect.** `opportunity.rank_momentum_axis` scored a *rising* board
value POSITIVELY while its own docstring said momentum was used only as
a risk check. That is momentum-chasing — "the price went up" as evidence
the price should go up — worth up to 20% of the composite pushed toward
Buy. It also never ran: the service looked up rank history by bare
`displayName` while the log files players under `{name}::{assetClass}`,
and the axis read `rankDerivedValue` where the producer writes `val`.
Measured on a live 973-row board, the lookup matched **zero** rows, in
every environment including production. Both are shape errors, and the
unit test built its fixture in a shape the producer never emits, so the
test agreed with the code and both were wrong together.

**The assumption that was wrong.** With the axis fixed and live, the
composite became 80% validated instead of 100% — a dark component
contributes nothing, a live unvalidated one moves scores. Validating it
looked impossible: `data/rank_history.jsonl` is untracked and always has
been, so board history cannot be read out of git. But the history file
is not the only route to past board values. `panel.panel_day()` already
reconstructs each of the 110 as-of dates from committed payloads and
source CSVs, and `build_api_data_contract` on that payload yields
exactly the value series that file records. The axis was backtestable
the whole time.

**The measurement.** Candidate: the composite as `score.composite`
computes it, mispricing plus momentum. Benchmark: mispricing alone, on
the same folds and the same player intersection, so the comparison is
like-for-like rather than two numbers from two studies. The 30-day
production lookback is replayed as-is; a shorter window would measure a
different signal under the shipping signal's name.

| horizon | folds | composite | mispricing | delta | composite beat it |
|---|---|---|---|---|---|
| 7d | 11 | +0.091 | +0.101 | -0.010 | 3/11 |
| 14d | 5 | +0.119 | +0.129 | -0.009 | 2/5 |

The axis alone: -0.072 and -0.068, inconsistent per fold. Both powered
horizons agree that adding it makes the ranking slightly worse.

**Decision:** the momentum weight is zero. The bar — beat the validated
component out of sample or carry no weight — was set before the number
was known, and a validated null is a result, not a failure. The axis is
still computed and still shown per row, marked "not counted": the
evidence is real, only its authority is withdrawn.

**Three consequences that had to be handled, not just noted.** A weight
of zero stops a component reaching the score and nothing else, so a
rejected signal would have kept steering the output through two side
doors. `score.composite` now excludes zero-weight components from
`componentsPresent` (they were inflating coverage, and therefore
confidence, and therefore which labels were reachable);
`detect_conflict` now ignores them (conflict suppresses directional
calls, so a rejected signal could veto a call it was not allowed to
contribute to); and `component_availability` no longer counts them as
live, which returns the confidence ceiling to 69.3 and puts Strong
labels out of reach again. That last is not a regression — it is the
board declining to make a strong call on one component's evidence.

**Status:** accepted 2026-08-04. Supersedes the Opportunity half of
ADR-008.

## ADR-014: the measurement stamps its configuration, and the board stamps its scope
**The defect.** `COMPONENT_VALIDATION["mispricing"]` claims rho +0.126
and cites the file that produced it. That file came from a path calling
`fair_value_index` with **no** `scoring_fit_board`; `service.build_board`
passes one. The two agree today only because the repo's Sleeper
directory is a 15-row stub with zero `gsis_id`s, so the join is empty and
the fit is exactly 1.0 — an accident of the fixture, not a property of
the code. A real directory in production would multiply served fair
values by per-player multipliers the measurement never saw, and every
payload would go on citing the same rho. Nothing would break; the number
would just quietly stop being about the thing it is quoted about.

**Why the backtest is not simply taught to apply the fit.** It cannot,
honestly. The reception multipliers are measured from a season of weekly
rows and a reception-depth payload, neither of which the panel
reconstructs as-of. Applying today's multipliers to a board from three
months ago would be look-ahead leakage — they were fitted on data from
*after* the origin date — dressed as a fix.

**Decision:** make the gap a reported fact on both sides rather than
making the two identical. Each measurement stamps the `configuration` it
was produced under; each board stamps `validationScope` comparing itself
against it; a mismatch becomes a caveat on the payload and a note on the
page. A test asserts the backtest really does run inert, so the day
someone teaches it otherwise they must also update the recorded
configuration alongside a re-run.
**Status:** accepted 2026-08-04.

## ADR-015: market movement is the right target, and points is another product's bar
For three sessions the docs listed "validated against realized fantasy
points" as an outstanding gate and dated it to September. That was a
category error. Consensus Edge answers "should I trade for this player" —
if the board says buy, you acquire at 5000, and the market reprices to
6000, the call was right whatever he scored. Points answer a *start/sit*
question. Holding a trade tool to a start/sit bar deferred a decision
that the market-movement evidence could already inform.
**The mechanism was also stated wrongly**, which sent the reasoning
somewhere useless. It is not "no games are played until September":
`fetch_weekly_stats([2025])` returns 18,539 regular-season rows today,
they are already cached on disk, and `nflverse_direct` explicitly
refuses to gate on `current_nfl_season` because a finished season's data
is served all offseason. What is missing is the *other* half of the
correlation — board history from a period when games were played. The
repository's first commit is 2026-03-09 and the 2025 season ended in
January 2026. We have the answer key and not the exam papers.
**Decision:** market movement is the validation target of record. Points
validation is recorded as a future *extension*, not an outstanding gate,
and requires in-season board history that will exist from September
onward. Anyone reaching for the 2025 points should be told the boards,
not the points, are what is missing.
**Status:** accepted 2026-08-04.

## ADR-016: the offseason panel is a stated limit with a scheduled re-run
The whole 110-day panel sits between the 2026 draft and the season.
Offseason repricing is driven by rookie hype and ADP drift; in-season
repricing by injuries and usage. A signal measured only on the former
may not transfer.
Two options were live: withhold the feature until in-season dates
accrue, or ship with the limit stated. Withholding forgoes evidence we
already have to buy evidence we will get anyway, and the re-run costs
nothing new — it is the same `run_consensus_edge_backtest.py` and the
same `validate_consensus_edge_board.py` against a panel that by then
includes in-season dates, directly comparable to today's numbers.
**Decision:** ship with the limit stated. `service._caveats` carries it
on every payload, every measurement stamps `panelStart`/`panelEnd`, and
the re-run is scheduled rather than hoped for.
**Also recorded so nobody re-derives it:** the panel *could* reach back
to 2026-03-22 (`data/legacy_data_2026-03-22.json` and the March payloads
embed 15 sources directly, and there is a second tracked CSV tree at
`exports/latest/site_raw/` that `available_dates` never consults). It is
not worth doing: seven of the fifteen March source keys have no modern
registry entry, `ktc` stopped voting on 2026-04-28, and `ktcSfTep` — the
offense market anchor — did not exist in March, so a naive extension
produces exactly the "looks like a real board, scores like a broken one"
failure the intersection guard was written to prevent. And 2026-03-22 is
still ten weeks after the last 2025 game, so it buys offseason days, not
the in-season ones that motivated looking.
**Status:** accepted 2026-08-04.

## ADR-017: the top-20 list is scored, and the median decides
`run_consensus_edge_backtest.py` measures a number inside the engine.
Users see a list of twenty names and a label per player, and nothing
scored either until `validate_consensus_edge_board.py`. It replays
`service.build_board` and `service.top_movers` — the shipped functions,
not a reimplementation — so the thing measured is the thing served.
**The median is the headline and the mean is a diagnostic.** These are
percentage returns on assets priced 152 to 9999. On one real fold, four
players priced 152-306 returned +327%, +268%, +210% and +195%, dragging
the top-20 mean to +59.44% against a median of +1.04%. A 60-point move
on a floor-priced rookie is noise wearing a large percentage. Every
bucket also reports `topContributorShare` so single-row dependence is
visible rather than inferred.
**The bar was set before the numbers:** positive median AND beat a
random-20 draw in a majority of folds AND the edge is not confined to
one asset class. Result: +1.57% over 7 folds at 14d (6/7 positive, beat
random 6/7) and +0.92% over 15 at 7d (11/15, 12/15). It passes.
**Three findings the headline hides, all now in the payload and the
docs:** the demoted-from-Strong bucket is the only consistently positive
label (6/6 and 11/14 folds) — the confidence ceiling is suppressing the
board's best signal; the sell side is positive in 0 of 7 and 0 of 15
folds and is therefore unvalidated; and restricted to assets worth
≥ 2000 the edge falls to +0.10%, so it lives mostly in players too cheap
to trade for.
**Status:** accepted 2026-08-04.

## ADR-018: the top list ranks by conviction, not by score
**The defect.** `top_movers` sorted on score alone. A score is a point
estimate and confidence is its precision, and ranking on the estimate
discards the precision the board already computed. That is not
theoretical: measured over 7 fold origins, the published top-20 buys had
a median reliability of **0.75** against **1.00** for the board as a
whole. The highest scores were coming from the *least-sourced* players,
because fewer sources means a wider spread against the market anchor and
therefore a bigger z. The list was mining thin evidence.
**The fix and its measurement.** Rank by `score x (confidence/100)`.

| horizon | score (old) | score x confidence |
|---|---|---|
| 7d, 15 folds | +0.92% | **+1.51%** |
| 14d, 7 folds | +1.57% | **+3.59%** |

Chosen over a confidence *threshold* — `conf >= 65` and
`reliability == 1` both scored comparably (+3.15%, 6/6) — because a
threshold is a tuned constant, shrinkage introduces no new number, and
it degrades smoothly rather than falling off a cliff at an arbitrary
line. Four variants were tried on one fold set, which is a
multiple-comparisons trap, so the winner was re-checked on the other
horizon before adoption; it replicated.
**Status:** accepted 2026-08-04.

## ADR-019: coverage counts only components that can contribute
**The inconsistency.** ADR-013 excluded zero-weight components from
`componentsPresent` so a rejected signal could not raise confidence. It
left them in the DENOMINATOR. So every row carried a coverage deficit
for a component we had measured and deliberately removed — a shortfall
no amount of data could ever close, which is not information about the
player. Coverage read 1/3, the ceiling sat at 69.34, and the Strong
threshold is 70.
**What that was costing.** The rows this suppressed were not marginal.
Every would-be Strong Buy was demoted into `Buy` carrying a
`labelReason`, and that demoted bucket was measured as the only
consistently positive group on the board (+2.53%, 6 of 6 folds) — the
model was producing its best signal and then refusing to say so.
**Decision:** exclude zero-weight components from both sides. Coverage
becomes 1/2, the ceiling 79.37, and Strong labels are reachable.
Verified after the change rather than assumed: **Strong Buy returns
+8.83% cohort-excess at 6 of 6 folds (14d) and +3.39% at 10 of 12 (7d)**
— the strongest group measured. The ordering of the reasoning matters
and is recorded deliberately: the suppressed population was measured
first, and the ceiling was changed because it was hiding something that
worked. Changing it to make a nicer label appear would be tuning away a
refusal, which this file has argued against twice.
**A second bug found while testing it.** `confidence_ceiling` assumed
freshness 1.0. Freshness is board-wide and KNOWN — pinned at 0.5 when
staleness is unknown — so the published ceiling advertised 79.37 on
boards where every row was capped at 62.996 and none could earn a Strong
label. Reliability varies per player and is still assumed at best case,
which keeps this an upper bound; freshness is now passed in.
**Status:** accepted 2026-08-04.

## ADR-020: the flag defaults ON, and what that does not claim
Held OFF since 2026-08-04 morning on the grounds that a composite of one
measured component and two declared priors is a labelled experiment, not
advice. Both premises changed by that afternoon: Opportunity was
measured and zeroed (ADR-013), and the artifact users actually see — a
list of twenty names — was scored for the first time (ADR-017), then
improved twice on measurement (ADR-018, ADR-019).
**Decision:** `consensus_edge` defaults **True**. Rollback is
`RISKIT_FEATURE_CONSENSUS_EDGE=0` plus a restart, since flag reads are
process-cached.
**Shipping ON is not shipping unqualified.** Four things remain
unclaimed and each rides on the payload rather than on this file:
`experimental: true` is still stamped; the target is market movement and
not fantasy points (ADR-015); the panel is entirely offseason with a
scheduled re-run (ADR-016); and **the sell side has no measured edge at
all**, which `sellSideValidation` states on every response and the sells
view renders before a user can act on it.
**One product fact worth stating plainly**, because it is not a defect
to be fixed but a property to be understood: 91% of the top-20 sits
under a market value of 2000, and above that floor the measured edge is
+0.10%. The board finds underpriced *deep* assets well and has little to
say about the players a big trade is built around. The row now shows
market value so a user can see which they are looking at.
**Status:** accepted 2026-08-04.

## ADR-021: a leave-one-out board must keep its units, not just lose the anchor
The three leaks this package documents (correlated sources, the rookie
ladder, the corridor clamp) all ask *does the anchor's opinion still
reach the result?* An independent audit found a second question nobody
had asked: *is the result still denominated in the same units?* For two
row classes the answer was no, and both were being published as buys.
**IDP had no scale at all.** Three IDP-only expert boards — `dlfIdp`,
`idpShow` and `fantasyProsIdp`, all flagged
`needs_shared_market_translation` — rank players within the IDP class
only. The backbone's shared-market ladder lifts that ordinal into the
combined offense+IDP rank space, and `idpTradeCalc` is what builds the
ladder. Excluding it empties the ladder, so those votes fall back to the
untranslated rank and IDP #1 scores as asset #1. Measured on the
2026-08-03 payload: the three sources flip method `exact` → `fallback`
on 159 / 235 / 177 rows, and the values move by **220 IDP rows, median
leave-one-out/base ratio 1.224, range 0.45x to 3.48x**. Caleb Banks went
1183 → 4115 and was the published #19 buy on that strength alone.
**CORRECTED 2026-08-04 (same day):** this paragraph originally said
`position_idp` sources lose a within-DL/LB/DB crosswalk. That branch is
dead — no registered source carries the `position_idp` scope and no row
on the live board carries that stamp. The measurement was right; the
mechanism named was not, and it had been copied into five other files.
See ADR-025.
**Rookies lost their ladder.** Closing leak #2 means skipping the
translation, and skipping it is what breaks the scale: the untranslated
vote says rookie #1 is asset #1. Non-rookie offense is sound (400 rows,
median 0.992, max 1.17x — one vote leaving, which is the point) while
**87 rookie rows reached 2.44x**.
**Decision:** affected rows are returned **unpriced** with
`anchor_free_board_lost_idp_backbone` /
`anchor_free_board_lost_rookie_ladder`, never with a substituted number.
The board stamps `assetClassCoverage` and a derived caveat so a wholly
unscored class is a legible refusal rather than an offense-only list.
Surviving rows measure median 0.992, p95 1.015, max 1.173 — one board,
one set of units.
**Rejected: keep `idpTradeCalc` as the backbone while dropping its
vote.** The backbone *defines the scale*, so a fair value calibrated on
it is still the anchor measured against itself. ADR-025 re-tested this
option properly and it fails on measurement as well as on premise —
read that ADR before reopening it, because the argument here alone is
not what settles it.
**Why no other source can supply the scale.** Not "there is exactly one
IDP cross-market source" — there are two registered `is_cross_market`
with scope `overall_idp`. The constraint is narrower:
`build_backbone_from_rows` seeds its ladder from ONE registry key, so a
backbone needs a source whose own value column spans both pools.
`idpTradeCalc` is the only key that does (529 positive offense + 258
positive IDP).
**The guard is a MEASUREMENT, not a registry flag.** This ADR originally
claimed `scale_integrity_lost` was structural, so "registering a second
IDP cross-market source lifts the refusal automatically instead of
leaving a hardcoded refusal behind". That was the hazard described as a
feature, and ADR-025 documents the one-line edit it invites. The
deciding gate is now `data_contract.shared_market_crosswalk_failed`,
which reads the translation stamps off the board and cannot be satisfied
by editing the registry. The rookie half is checked per row against the
row's own votes, so a rookie the broken source never ranked keeps his
score.
**Status:** accepted 2026-08-04.

## ADR-022: the list that is served is the list that was measured
ADR-018 moved the top list from raw score to conviction (score shrunk by
its own confidence) because ranking on the point estimate alone threw
away the precision the board already computes, and doing so more than
doubled the measured edge. That change reached `top_movers`. It did not
reach `build_board`, which kept sorting `players` by raw score — and
`/api/consensus-edge/players` is the **only** endpoint the page fetches.
So the study that justified turning the flag on measured an ordering no
user ever saw, and `TestConvictionRanking` passed on two-row synthetic
boards while the shipped page ignored conviction entirely.
**Decision:** `build_board` stamps `conviction` on every row and sorts
`players` by it. The top of the served board is now literally the head
of the measured list. `test_served_order_is_the_measured_order` asserts
that equality against the running API rather than against a fixture, so
the two orderings cannot drift apart again silently.
**The client reads the stamp; it does not recompute it.** The sells view
reverses the same key and `positionLeaders` ranks on it, both via
`lib/consensus-edge.js::rankKey`. A missing stamp falls back to `0`, not
to `score` — that leaves the backend's own array order (already
conviction order) intact instead of quietly reinstating the ranking the
measurements do not describe.
**Status:** accepted 2026-08-04.

## ADR-023: the flag goes back OFF, on the gate that turned it on
Supersedes ADR-020. Nothing about the reasoning in ADR-020 was wrong;
the board it reasoned about was. Every measurement it cited — the
top-20's +3.59%, `Strong Buy`'s +8.83%, mispricing's ρ +0.126 — was
produced on a board whose IDP fair values came from a leave-one-out
build with no IDP backbone, and were therefore not on any scale
(ADR-021).
**Re-run against the repaired board, the same pre-registered gate
fails.** `validate_consensus_edge_board.py` is unchanged; only its input
is:

| measurement | before repair | after repair |
|---|---|---|
| top-20 buys, 14d | +3.59%, beat random 6/7 | **−1.01%**, beat random **0/6** |
| top-20 buys, 7d | +1.51%, beat random 11/15 | **−0.55%**, beat random **0/12** |
| mispricing ρ, 14d | +0.126, 7/7 folds positive | **+0.031**, 4/6 |
| mispricing ρ, 7d | +0.089, 12/14 | **+0.040**, 8/12 |
| vs market-value benchmark, 14d | we beat it 7/7 | **it beats us 5/6** |

The benchmark line is the one to read twice. `marketValue` — a plain
"buy cheap players" rule — went from ρ −0.020 to **+0.116**, and our
buy list skews cheap by construction. On the offense rows that survive,
the board is on the wrong side of the only benchmark that matters.
**Decision:** `consensus_edge` defaults **False**. It is not removed and
nothing is deleted: the endpoints, the page, the refusal states and the
snapshot timer all work, and `RISKIT_FEATURE_CONSENSUS_EDGE=1` plus a
restart brings them back for evaluation. What is withdrawn is the claim
that this board tells a user something a coin flip would not.
**`test_feature_flags.py` moves it from `safe_on` to `off_only`**, so
flipping the default back is a code change that has to name the
measurement that changed. The bar is the gate passing on a re-run — not
a judgement that the panel was unlucky.
**What this does not say.** It does not say the model is wrong in
principle, and it does not say the panel is decisive: 6 usable 14-day
folds over an offseason is a small sample, the sell side actually
improved on repair (−0.31% at 14d, right sign, where it had been
+0.02%), and the tradeable-only slice is roughly flat (+0.23%) rather
than negative. Those are reasons to keep measuring, not reasons to ship.
**Status:** accepted 2026-08-04.

## ADR-024: what Consensus Edge does not have, and why none of it is coming soon
Recorded because "not implemented" and "implemented badly" are different
states and the brief asks for the difference to be legible. Each of these
is absent at every layer — no endpoint, no field, no partial UI — rather
than stubbed:

- **Liquidity.** Would need a measure of how easily an asset trades. The
  repo has trade *records* (`src/intel/ledger`) but no as-of cohort, the
  same gap that makes Sharp Flow unvalidatable, so a liquidity number
  would be unmeasurable in exactly the way a liquidity number must not
  be.
- **A risk component.** Distinct from confidence, which is about our
  evidence; risk is about the asset. It needs a dispersion of outcomes
  per player, which is BDVM's territory (`src/bdvm/`) and would be a
  second value concept smuggled into a market-value board.
- **Contender / balanced / rebuilder views.** Roster-derived, therefore
  `leagueKey`-scoped, and this board is scoring-profile scoped. Building
  it means a per-league cache first — see ADR-023's note on `leagueKey`.
- **A historical-signal chart.** The store now records what is needed
  (`snapshot.history_for_player` returns it). There is no UI.
- **A player-detail route.** `GET /api/consensus-edge/player/{key}`
  exists and works; nothing calls it and there is no bridge route.
- **Machine learning.** There is none, and there never was. The honest
  classification is a **deterministic valuation model**: log-ratio
  mispricing, a robust z against a cohort, a beta-binomial posterior,
  and a weighted mean. No model is trained, no parameters are fitted.
  `params_v1.json` calls its weights priors for exactly this reason and
  `weightsAreFitted: false` rides on every methodology payload.
- **`Conflicted` is structurally unreachable.** It needs two opposing
  components that both carry weight; one is live. This is reported by
  the board (`componentAvailability`, `confidenceCeiling`) rather than
  hidden, and it resolves by itself if Sharp Flow ever earns its weight.
**Status:** accepted 2026-08-04.

## ADR-025: idptradecalculator.com is the IDP market, and it cannot also be the IDP scale
Raised by the user: *"We're supposed to be using idptradecalculator.com
values for market IDP."* Correct, and we are — 258 of 281 IDP rows carry
an `idpTradeCalc` market value and that path was never touched. What
ADR-021 removed is the OTHER number: the anchor-free fair value the
market price is compared against. The question this ADR answers is
whether that half is recoverable.

**The mechanism ADR-021 gave was wrong.** No registered source carries
the `position_idp` scope; a census of every `sourceRankMeta` stamp on
the 973-row live board returns `overall_offense: 5772`,
`overall_idp: 965`, and **zero** `position_idp`. The per-position ladders
are still built and never read. The live path is the shared-market
crosswalk used by `dlfIdp` / `idpShow` / `fantasyProsIdp`, which flip
method `exact` → `fallback` on 159 / 235 / 177 rows when `idpTradeCalc`
leaves. Corrected in six files.

**Rejected: promote `draftSharksIdp` to a second backbone.** It looks
like the obvious candidate — registered `is_cross_market`, and it does
*not* need the crosswalk. It cannot work.
`build_backbone_from_rows` seeds its ladder from ONE registry key, and
`draftSharksIdp` carries **0 positive offense values** under its key
(its offense half is the separate `draftSharks` key). `idpTradeCalc` is
the only key spanning both pools: 529 positive offense + 258 positive
IDP. Promoting `draftSharksIdp` yields the identity ladder `[1, 2, 3, …]`
— which is exactly the fallback — so the refusal lifts and the board
stays **bit-for-bit broken**: median 1.224, max 3.478, Caleb Banks still
3.48x. Verified directly, and pinned by
`TestTheGuardIsACapabilityNotAFlag`.

**This is why the guard became a measurement.** `is_backbone` is a
label, and four shipped documents recommended granting it as the way
forward. `data_contract.shared_market_crosswalk_failed` reads the
translation stamps off the board instead; a registry edit cannot satisfy
it. Note also that ladder *depth* is not a usable capability test —
`dlfIdp` (163 > 162) and `idpShow` (247 > 245) both clear a depth
comparison while producing identity ladders. Only "the ladder does not
start at 1" separates them (`idpTradeCalc` starts at 30).

**Rejected: keep the ladder, drop the vote.** The strongest option and
the one the user's framing implies — if IDPTC is the *market*, it should
supply the coordinate system and the price but cast no vote. It is
implementable, and it does repair the headline case (Caleb Banks
1183 → 594, a sell). It still fails, twice over. Measured max
leave-one-out/base is **2.270** against the 1.35 the shipped test pins —
68% over. And the circularity ADR-021 asserted turns up as an artefact:
`_PERCENTILE_REFERENCE_N` is 500 while the ladder runs to combined rank
784, so **45 of 243 priced IDP rows land on the identical fair value
1587** and their "mispricing" is `1587 / market price` — an inverted
ranking of the anchor's own price (Spearman 0.53 against 0.13 on the
offense control).

**That saturation is a third reason the design fails, NOT a pipeline
defect to fix first.** An earlier draft of this ADR closed with "worth
reopening only with that saturation fixed", which points a reader at
`_PERCENTILE_REFERENCE_N` — a site-wide top-500-board decision
(`CLAUDE.md`, live pipeline step 2) that reprices everything. Do not
change it on the strength of this ADR. The clamp is **inert on the live
board**, because `idpTradeCalc` sits in `_VALUE_BASED_SOURCES`
(`data_contract.py:5381`) and votes `raw / site_max × 9999`, never
entering the rank → percentile → clamp path at all. Measured on the
default board:

```
IDP rows priced: 225   distinct values: 196   largest tie block: 5 rows
deepest 85 rows:  64 distinct values spanning 773..1394
                  84 of 85 carry a value-direct idpTradeCalc vote
```

No collapse anywhere. The tie block appears only once the value-direct
vote is removed, which is precisely what this design does — and doing so
exposes the 46% of the IDP ladder (118 of 258 entries) that sits past
combined rank 500 to a clamp production never reaches. The design
creates the condition; the constant is not at fault.

**Rejected: narrow the class-wide IDP refusal to per-row**, mirroring
the rookie guard. Of 220 valued IDP rows, 211 carry a surviving
crosswalk-dependent or rookie vote; all 191 rows moving above 1.0 do.
The 9 rescued rows are single-source `draftSharksIdp` rows moving
0.58–0.66x under the single-source haircut, so narrowing would publish
nine thinly-evidenced sells to close a stylistic inconsistency.

**Decision:** keep the refusal. There is no anchor-free IDP scale today,
for a narrower and harder reason than ADR-021 stated. IDP returns to the
board when a source publishes offense and IDP in one value pool under
one registry key — not when a flag is set.
**Status:** accepted 2026-08-04.

---

## ADR-026: `snapTrend` was never unmeasurable — the panel was the wrong season

**Context.** Four places in this repo attributed the `snapTrend` axis's
lack of validation to the same cause: `data/playerctx/snapshot.json` is
refreshed weekly and overwritten in place, so "there is no history to
replay" and the axis is "unmeasurable until snapshots accrue"
(`score.py`, `backtest_consensus_edge_composite.py`, `METHODOLOGY.md`
twice). The implied fix was a retention project — start committing
snapshots and wait.

**The attribution was wrong.** nflverse publishes
`snap_counts_{season}.csv` as one row per player **per game**, carrying
`season`, `game_type` and `week`; `depth_charts_{season}.csv` appends a
full dated snapshot on every upstream scrape. The history was always in
the files. `parse_snap_counts` was the thing discarding it — a
newest-season filter with no week cutoff — and `parse_depth_charts` kept
only the newest `dt`. As-of reconstruction was a missing function
argument, not a missing dataset.

**But retention would not have helped either**, and this is the part
that decides the work. The panel runs 2026-04-16 → 2026-08-04, entirely
between the draft and kickoff. Every one of those 111 dates resolves to
the same completed season and the same final week, so `snapTrend` is the
identical per-player number on 16 April and on 3 August. Weekly
retention across that window would have captured ~16 byte-identical
blocks. Every "fold" would be a resampling of one observation.

Both halves were verified, not reasoned about:

```
2026-04-16 → AsOf(season=2025, through_week=22)
2026-06-01 → AsOf(season=2025, through_week=22)
2026-08-04 → AsOf(season=2025, through_week=22)

week-22 replay of 2025 == unbounded live read:  True  (1,766 players)
week-10 replay:  1,592 players with snaps, mean trend +0.39
week-4  replay:  1,400 players with snaps, mean trend +0.21
```

The first block is the finding; the second confirms the replay path is
faithful to what production reads; the third confirms the signal
actually moves with the cutoff, which is the property a backtest needs
and the one an offseason panel cannot supply.

**Decision.**

1. `parse_snap_counts` takes `season` / `through_week`;
   `parse_depth_charts` takes `as_of`. Both default to the previous
   unbounded behaviour, test-pinned as byte-identical.
2. `src/playerctx/asof.py` resolves a date to the window observable on
   it, from the nflverse schedule already fetched for BDVM's ROS. A week
   counts only when all its games are done, and same-day games do not
   count — snaps publish after the game.
3. `service.reconstruct_playerctx` replays the snapshot in memory. It is
   **not** a parameter on `refresh_playerctx`: that would leave a
   historical replay one default argument away from overwriting the file
   production serves live.
4. The composite backtest grows a `snapTrend` arm that measures the axis
   anyway and stamps `snapWindows` + `effectiveSignalObservations: 1`,
   so the number cannot be read as more than one cross-section. First
   run: mean rho +0.037 over 5 folds, 4/5 positive, beating the
   market-value benchmark in 0/5 — "no effect detected", from one frozen
   observation.

**Two bugs the new parameters exposed**, both of the class this audit
keeps finding — code that works until you use it:

- The parse loop bound its row-season local to the name `season`,
  shadowing the new parameter. The caller's argument was destroyed on
  the first row and the filter silently used the newest season.
- `parse_depth_charts` compared `dt > as_of` on whole strings. `dt` is a
  full timestamp, so the natural bound `"2025-11-09"` dropped that
  entire day and fell back to the previous snapshot — an off-by-one-day
  that still returns a plausible depth chart. Fixed with a same-length
  prefix compare; verified the two covering tests fail without it.

**Residual bias, reported not assumed away.** The join anchor is the
live-only Sleeper directory, so a player out of the league by run time
cannot join. `reconstruct_playerctx` returns per-source join rates
(80.7% for the 2025 snap counts as of 2026-08-04) rather than an
unqualified player list.

**What this does not claim.** The axis is measurable, not measured. It
becomes a real multi-fold measurement when in-season dates enter the
panel — automatically, with no further work.

**Deferred, and the reason changed: retaining the joined snapshot as
dated git-tracked files.** This was planned alongside the as-of
parameters, on the argument that reconstruction recovers the *inputs*
while retention preserves the *artifact production actually served*.
That argument is now much weaker than when it was made. The week-22
replay of 2025 is byte-identical to the live unbounded read, so the
joined artifact IS reproducible from upstream given the same Sleeper
pool — and the pool is the only thing retention would add, worth the
80.7% → 100% join rate and nothing else.

Against that: the mechanism is a production push (dedicated clone,
`git add -f`, push retry, per `deploy/dlf_fetch_and_push.sh`), and it
commits generated data by design. This session produced a live
demonstration of the hazard — a `git add -A` swept two scheduled-refresh
timestamp files into a commit and that alone put the PR into merge
conflict with `main`.

So it is not built here. If the survivorship term turns out to matter
once in-season folds exist, the measurement will say so — the join rate
is stamped on every replay — and that is a better trigger for a prod
deployment change than a prior.

**Status:** accepted 2026-08-04. **Overturned 2026-08-05 — see below.**

### Amendment (2026-08-05): retention is built, by direction

The deferral above was overturned by an explicit instruction to build
it. Recording that plainly rather than retrofitting a technical
justification, because **the evidence has not changed**: the week-22
replay is still byte-identical to the live read, retention still buys
only the 80.7% → 100% join rate, and the ~16 byte-identical blocks a
weekly cadence would have captured across this offseason are still
byte-identical. Nothing above became wrong; it was outvoted.

Two things in the deferral WERE wrong, and both were mine:

- **"Replayed by `panel._commit_before` with zero new replay code."**
  False. `available_dates` intersects two hardcoded pathspecs and
  `PanelDay` had no field for a snapshot. The real cost was
  `PLAYERCTX_REL`, a `playerctx_asof` mirroring `payload_asof`, three
  `PanelDay` fields and their tests.
- **"The mechanism is a production push per `dlf_fetch_and_push.sh`."**
  That pattern does not transfer. Both existing pushers work inside a
  dedicated clone because nothing reads their output locally; playerctx
  cannot, since the API reads the snapshot out of the live deploy
  directory that `deploy.sh` force-resets. `deploy/playerctx_history_push.sh`
  splits it: the refresh writes the live path, the push copies the dated
  file into a dedicated clone.

Four decisions worth knowing:

1. **Retention does NOT join `available_dates`' intersection.** If it
   did, the panel would collapse from 111 dates to zero and grow back
   one per week — trading every existing measurement for a feature with
   no data yet. A day without a snapshot yields `PanelDay.playerctx =
   None`, which is the normal case today and must stay legible as "not
   retained" rather than "nobody played". Pinned.
2. **Snaps-only projection**, ~320 KB against ~1.1 MB. `snapTrend` is
   the axis retention exists for; the contract block is the largest and
   its upstream churns weekly.
3. **No `.gitignore` negation**, and that is the safe choice rather than
   an omission. A negation cannot work under the bare `data/` — git does
   not descend into an excluded directory — which I verified in a clean
   repo, and which also means the `!data/ros/…` block above rescues
   nothing (those 4,600 files are tracked purely because a workflow
   force-added them). Retention uses `git add -f` with an explicit file
   list, which is strictly stronger: with everything ignored by default,
   committing the 38 MB depth-chart CSV sitting in the same directory
   takes naming it, and no directory-level add can reach it.
4. **`retain_history` defaults off** and production opts in via
   `--retain-history`. Retention runs after the live write and cannot
   fail it — losing a refresh to a full disk in the history directory
   would trade the artifact the API serves for the optional one.

`data/playerctx/history` is added to `retention._protected_paths`; the
sibling raw cache deliberately is not, because that one IS a cache.
Coverage mirrors `rank_history.coverage` (`missingDays` / `staleDays`)
so a stalled timer is visible before a study needs the data.

**Enabled in production 2026-08-05, on explicit sign-off.** The push
installs a new timer and starts committing generated data on a schedule,
so it was built and tested first and held for approval rather than
taken unilaterally; approval was then given. Repo-side wiring:

- `dynasty-playerctx-refresh.service.template` gains `--retain-history`,
  so the producer writes the dated file at all.
- `dynasty-playerctx-history.{service,timer}.template` run
  `deploy/playerctx_history_push.sh` weekly at **Tue 06:45 UTC** — 40
  minutes after the refresh's worst-case finish (05:40 + 600s randomized
  delay + 900s timeout ≈ 06:05), and off the three minutes already
  spoken for by prod→main pushers (`:27` DLF, `:32` IDP Show, `:42` CI).
- Installed **unconditionally** by `deploy/install-systemd-service.sh`,
  with the deploy-key check inside the script. It was first gated on the
  key here, by analogy with the DLF / IDP Show pushers, and the
  2026-08-05 deploy measured that as wrong twice over — see the
  correction below.
- The timer carries **no `Requires=`** (diverging from the sibling
  refresh timer, following `dynasty-reception-depth`): `Requires=` in a
  timer's `[Unit]` pulls the service in whenever the timer starts, which
  would fire a push on deploy day for a file that does not exist yet,
  and again on every reboot.

One thing this exposed, fixed rather than worked around: the installer
gated reinstallation on *"does the timer already exist"*, so a template
edit on an already-provisioned box was silently ignored until someone
remembered `FORCE_SERVICE_INSTALL`. Adding `--retain-history` to an
existing unit is exactly that case — the repo would say retention is on
and the box would keep running the old `ExecStart`. Both playerctx
blocks now render the unit first and compare content, the way the
backup-unit loop at the bottom of the same function already did.

Wiring is pinned by `tests/deploy/test_playerctx_history_timer_is_wired.py`,
including the one that makes the rest pointless if it regresses:
`--retain-history` must be on the refresh `ExecStart`, or the push runs
weekly, exits clean, and retains nothing.

### Correction (2026-08-05, same day): "enabled in production" was half true

The first deploy carrying this work (run 2158, `8252379e0`) settled it,
and only one of the two halves landed:

```
[deploy][WARN] Timer units missing from this host: …-playerctx-history.timer. Running installer to add them.
[systemd-bootstrap] Player-context unit files changed; rewriting …-playerctx-refresh.service + timer.
[systemd-bootstrap] Player-context retention timer skipped: /home/…/.ssh/github_deploy_key missing - no deploy key to push with.
```

**The producer is on.** `--retain-history` reached the box, and only
because of the content-compare fix above — the old "does the timer
exist" gate would have left prod running the previous `ExecStart` while
this document claimed retention was live. That is the failure this ADR
predicted, caught in the act, one line up.

**The pusher was not installed**, so the paragraph above overstated
what shipped. Two distinct causes, both now fixed:

1. **The key test ran as the wrong user.** The installer runs as the
   *deploy* user, whose sudo is scoped to specific commands, so it can
   neither `sudo test -f` nor stat another user's `~/.ssh`. It reported
   the key missing while the DLF pusher was committing to `main` with
   one every two hours — so this was very likely a false negative about
   a working key, not a real absence. Only the service user can answer
   the question, so the check moved into
   `deploy/playerctx_history_push.sh`, which runs under
   `User=__APP_USER__`.
2. **A conditionally-installed timer breaks `deploy.sh`.** Its presence
   check globs `*.timer.template` and warns for anything not installed
   AND enabled, then runs the installer to close the gap — so a
   permanently-skipped timer means a warning plus a pointless installer
   run on **every deploy, forever**. That is precisely the loop #729
   closed for three other timers, reintroduced here hours later.
   `deploy.sh` carries a `case` exempting the alert timers; adding a
   fourth exemption would have spread the pattern instead of fixing it.
   The unit is now installed unconditionally.

The original rationale — *"a timer that fails weekly is worse than one
never installed"* — was answering a real concern with the wrong
mechanism. It is answered instead by the script exiting **0** with the
missing path named: nothing is half-done at that point, and the push
globs EVERY dated snapshot rather than the newest, so supplying the key
later backfills every missed week on the next run. A stalled retention
is meant to surface through `store.history_coverage()`'s `missingDays`,
the same way `rank_history` reports its own gaps — not through a red
timer nobody reads.

**Still unobserved:** no snapshot has been retained yet. The first
evidence is a `chore(playerctx): retain snapshot …` commit on `main`
after a Tuesday 06:45 UTC run, and that cannot happen before a deploy
carries this correction.

**Status:** superseded by the amendment; retention accepted 2026-08-05.
Producer enabled in production 2026-08-05; pusher pending the deploy
carrying this correction.

---

## ADR-027: Sharp Flow's filter is now applied, and it still cannot be backtested

**Context.** `inputs.sharp_movements` documented itself as
"Qualified-manager trade movements" and `sharp_flow.py`'s module
docstring opens with "Qualified-manager acquisition direction". The
query was:

```sql
SELECT asset_id, action, user_id, league_id, ts
  FROM asset_movements
 WHERE tx_type = 'trade'
```

No cohort filter. The claim was nevertheless *true* in production,
because `scripts/crawl_sharp_activity.py` only visits managers who
qualify at crawl time — so the corpus arrived pre-conditioned and the
component behaved as advertised. The filtering was incidental, a
property of what the crawler happened to collect rather than of this
code, and it would fail silently and flatteringly the day anything else
wrote to the ledger.

Two more of the same shape, found alongside it:

- **`managerQuality` was never supplied.** `movements_from_ledger_rows`
  reads it off the row and defaults to 1.0, so every manager weighed the
  same and the quality term in `aggregate_asset` was a constant.
  `src/sharp/market.py` computes a real one per `CohortMember` and
  Consensus Edge simply never received it.
- **`STATUS_NO_COHORT` was declared and unreachable.** A status naming a
  check no code performed. Everything collapsed to `no_ledger`,
  including "a ledger exists but nobody qualifies" — a different
  situation with a different fix.
- **The query read the per-platform raw columns.** After the additive
  platform migration, `asset_id` / `user_id` keep the SOURCE ids while
  `canonical_asset_id` / `manager_key` carry canonical identity. On a
  multi-platform ledger the same player would arrive under two asset
  keys and no manager would match a cohort key.

**Decision.** Apply the filter rather than restate the docstring. The
cohort comes from `src.sharp.market.cohort_members` — the one definition
of who qualifies — rather than a second set of criteria; quality is
stamped per movement from the same records; the canonical columns are
preferred with a `PRAGMA table_info` check rather than a try/except that
would make a schema mismatch look like an empty ledger; and
`STATUS_NO_COHORT` reaches the payload.

**What none of that fixes, and it is the larger problem.** The corpus is
conditioned on TODAY's cohort, not the cohort at the time of each trade.
`crawl_sharp_activity.py` crawls the first 250 currently-qualified
managers sorted by user-id string, so a manager qualified at date D but
not now had their movements **never collected**, and one who qualified
later carries only a ~30-day backfill stub. That is survivorship on a
proxy for the outcome, it is upstream of every filter, and no as-of
cohort can recover data that was never gathered.
`MOVEMENT_RETENTION_DAYS = 400` caps the rest.

So the reason recorded in `METHODOLOGY.md` and `params_v1.json` —
"unvalidatable until `src/sharp/` gains an as-of cohort" — was necessary
but **not sufficient**, and stating it alone implied a fix that would
not have worked. Both files now say so.

**Explicitly rejected: a historical Sharp Flow backtest.** It is unsound
at any budget, and a number produced that way would be exactly the
plausible-but-wrong result this audit spent its time removing.

**Adopted instead: the forward-only path that already existed.**
`snapshot.write_board` has been storing `component_sharp_flow` per
player per day, and `label_outcomes` fills cohort-excess forward returns
once the horizon has elapsed. Signal and outcome are written weeks apart
by two different code paths, so there is no window to leak through and
nothing to reconstruct. `scripts/validate_components_forward.py` reads
it — for every stored component and the served ranking key, so a Sharp
Flow number has something to be judged against.

It accrues one observation per day from the day the board runs, and it
reports `labelledRows` per series so an empty component column reads as
"no ledger" rather than "no signal". Origins are correlated separately
and averaged, never pooled, and the output states plainly that
consecutive daily origins overlap and are therefore a count of
cross-sections, not of independent observations.

**Status:** accepted 2026-08-04.

---

## ADR-028: the three Sharp Score defects — two real, one overstated

**Context.** `METHODOLOGY.md` carried a line naming three known-and-unfixed
defects in the Sharp scoring stack. They were inherited from an audit and
never verified against the code. Verified 2026-08-05: **two are real and
are now fixed; the third is overstated and its claim was the thing that
needed correcting.**

### 1. No per-manager or per-league contribution cap — CONFIRMED

`src/sharp/market.py::_aggregate_window` counted one movement as one
unit with no bound, and the only pushback was
`breadth_factor = m/(m+3)` (`src/intel/signals.py`), which saturates
fast. `src/sharp/roster_percentage.py` calls the same function and
inherited it. Consensus Edge has capped this since ADR-011, so the two
boards aggregated the same movements from the same cohort under
different rules — "the sharps are buying him" meant two different things
on two pages.

Fixed by promoting `_apply_share_cap` to `src/utils/share_cap.py` and
calling it from both. Neutral home because the dependency has to point
somewhere neither package owns: `consensus_edge` is a feature package
and must not be imported by `src/sharp`, and `sharp_flow` deliberately
imports nothing from `src/sharp`.

**Raw counts stay raw.** Capping produces fractional weights, and
`volume` / `tradeCount` / `uniqueManagers` are descriptions of what
happened — a capped number in those fields would misreport the record.
The weights are reported beside them as `weightedBuys` / `weightedSells`
/ `weightedNet` / `weightedVolume`, plus a `concentrationCapped` flag,
and `signal_strength` reads the weighted pair. Buys and sells scale by
the same per-contributor factor, so a cap can shrink a lean and can
never flip it — pinned.

**What a share cap cannot do**, stated because the obvious test asserts
it wrongly: it bounds one contributor's share OF A TOTAL, so a single
contributor's share is 100% by construction and capping it is
meaningless. One manager with ten observations and no peers is bounded
by `breadth_factor` (0.25), not by this. Measured on the case the cap is
actually for — 8 observations against two managers' 1 each — the
dominant manager goes from 80% of the evidence to 34%, and weighted
volume from 10.0 to 3.03.

### 2. A dead `rosterQuality` term carrying 0.22 — CONFIRMED, and reproduced

`_roster_quality_component` reads four `ManagerRecord` fields that **no
builder populates** (`platform_records.py`, `records.py`), returned
`0.0` for that, and the total applied the declared 0.22 weight
unconditionally with no renormalization. 22 points of a 0-100 scale were
unreachable: a production-shaped record scored **64.9** against a real
maximum of 78. `docs/intel/SHARP_SCORE.md` documented the term as live.

It stayed invisible because every test fixture sets
`roster_value_ratios` — the suite exercised the one branch production
never reaches. The new tests use the production shape.

Fixed by returning `None` for absent evidence and renormalizing over the
components that have any, the same posture
`consensus_edge.score.composite` takes. `components.weightsApplied` is
stamped per manager so the renormalization is auditable rather than
assumed. Same record now scores **78.0**.

**Why this is safe for the cohort, asserted rather than argued.**
Qualification is `minScorePercentile` — a percentile of the evaluable
population, not an absolute bar — and the absent set is identical for
every manager, so every score scales by the same factor and the ranking
is unchanged. `tests/sharp/test_sharp_gates.py` computes the old
arithmetic inline and asserts both the full ordering and the qualified
set are identical.

**The impact could not be measured here.** The ledger file exists but
`cohort_members()` returns 0 members in this checkout, so there is no
live cohort to take a before/after against. The invariance is proved on
synthetic records; the prod-side observation is a separate step and is
not claimed as done.

`methodologyVersion` moves to `sharp-v2.1`, per the rule
`scoring_v2.json` states about itself. That rule was previously
unenforced — the test asserted the literal `"sharp-v2"`, so a weight edit
without a version bump PASSED and a version bump without a weight edit
FAILED, exactly backwards. It now pins a content hash of the
scoring-relevant config against the version that produced it, the same
way `paramSetId` works for `consensus_edge` and `bdvm`.

### 3. A quality-lookup key mismatch giving cross-platform managers 1.0 — OVERSTATED

The two-key divergence is real in the source: `market.py` dedups breadth
on `canonicalManagerKey` and looked up quality by the raw `managerKey`.
But the `1.0` default **cannot fire**. `market_payload` passes the same
`manager_keys` list into `platform_ledger.query_movements`, whose
`WHERE m.manager_key IN (...)` guarantees every returned row's key is
present in the quality map, and both are derived from one deduped
`members` list. The repo's own audit had already filed it under "minor
items not raised as findings" as unreachable-but-latent; `METHODOLOGY.md`
asserted it as an active defect anyway.

Three things done instead of "fixing" a bug that cannot occur:

- **The claim is corrected** to latent/unreachable, matching the audit.
- **The default is inverted.** `1.0` is *higher* than any real cohort
  member (automated members are `score/100`), so an unmatched manager
  outranked every genuine sharp. Now `UNMATCHED_MANAGER_QUALITY = 0.0`,
  the floor, in both `market.py` and `sharp_flow.py`. The lookup also
  tries the canonical key first, so the two keys stop disagreeing.
- **The real cross-platform leak is fixed, and it is in the CAP, not the
  quality.** `sharp_flow._apply_share_cap` groups by
  `Movement.manager_key`, and `inputs.sharp_movements` never emitted
  `canonicalManagerKey` — so one human's linked Sleeper and FFPC
  accounts arrived as two groups and each got its own 0.34 bucket,
  evading the bound they were supposed to share. The query now resolves
  the canonical key through `platform_managers` exactly as
  `query_movements` does, and degrades to per-account grouping rather
  than raising when the identity table is absent.

**Status:** accepted 2026-08-05.

---

## ADR-029: the v2.1 cohort before/after is unrecoverable, so verify the invariant instead

**Context.** ADR-028 shipped `sharp-v2.1` with a safety claim: the
renormalization raises every score, but the ORDER and therefore the
percentile-selected cohort are unchanged. It was asserted on synthetic
records in `tests/sharp/test_score.py` and explicitly **not** measured
against the live population, because the dev ledger yields zero cohort
members. It was recorded as "owed, not done", and
`scripts/sharp_cohort_snapshot.py` was added to make paying it a single
command on prod.

That debt cannot be paid in the form it was written. **v2.1 is already
live**, and nobody captured the pre-v2.1 cohort — the "before" does not
exist anywhere, on any box, in any commit. A before/after is not
pending; it is impossible. Carrying it on the owed list indefinitely
would be carrying a measurement that will never be taken, which is the
same dishonesty as claiming it was.

**Decision.** Verify the invariant the claim rests on, which needs no
baseline at all.

The argument is:

> the absent component set is identical for every manager
> → every score scales by the same factor
> → the order cannot move
> → and qualification is a percentile of the population, so the cohort
>   cannot change.

Every clause after the first *follows from* the first, and the first is
a property of ONE population at ONE instant. If every evaluable
manager's `components.weightsApplied` map is identical, the
renormalization multiplied every score by the same constant. That is
checkable on prod today.

`scripts/sharp_cohort_snapshot.py --verify-invariant` does exactly that:
it groups the population by `weightsApplied` and reports the distinct
maps found. One map and no unstamped managers → the claim holds, and it
holds as a proof rather than an argument. More than one → renormalization
scaled managers by DIFFERENT factors, could have reordered them, and the
shipped claim is false on that population.

Three details that decide whether the check is worth trusting:

- **An empty population exits 2, not 0.** "Every manager in an empty set
  shares one weight map" is vacuously true and proves nothing, so a dev
  box must not be able to report a pass. Same posture as
  `scripts/backtest_perfect_draft.py`.
- **An unstamped manager fails the check** rather than being skipped.
  Treating "no `weightsApplied`" as "same as everyone else" would let the
  check pass by ignoring precisely the rows it cannot see.
- **Weights are compared at the precision they are stamped at** (6dp,
  rounded at the source). Comparing raw floats would report a spurious
  violation from representation noise instead of a real difference in
  the absent set.

**And a baseline now accumulates**, so the next scoring change does not
repeat this. `dynasty-sharp-cohort-snapshot` writes
`data/sharp/cohort/snapshot_<date>.json` daily at 05:10 UTC — after the
04:50 records crawl that makes managers scoreable and before the 05:50
roster pass. Snapshotting before records would capture a cohort built
from yesterday's evidence and quietly date every baseline by a day.

The script owns its own filename via `--daily` rather than taking a
date-stamped path in the unit's `ExecStart`: that avoids a `/bin/sh -c`
wrapper and systemd `%` escaping, and keeps every path in an ExecStart
resolving to a file that exists — the rule
`tests/deploy/test_all_timers_are_wired.py` enforces across all units,
which caught the first attempt.

**Status:** accepted 2026-08-05. Supersedes the "live cohort before/after"
item owed by ADR-028; that item is closed as unrecoverable, not done.
