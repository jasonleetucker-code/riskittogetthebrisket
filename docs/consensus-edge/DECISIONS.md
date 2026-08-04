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
**IDP had no scale at all.** `idpTradeCalc` is the only source
registered `is_backbone`, and the backbone crosswalks a within-DL/LB/DB
rank into a combined-pool rank. Excluding it makes the pipeline take its
documented fallback — treat a position rank as a combined rank — so the
#1 DL is priced as the #1 asset in the league. Measured on the
2026-08-03 payload: **220 IDP rows, median leave-one-out/base ratio
1.224, range 0.45x to 3.48x**. Caleb Banks went 1183 → 4115 and was the
published #19 buy on that strength alone.
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
vote.** Not on cost — on the module's own premise. The backbone *defines
the scale*, so a fair value calibrated on it is still the anchor
measured against itself, which is the circularity the whole module
exists to avoid. There is no anchor-free IDP scale today because there
is exactly one IDP cross-market source.
**The guard is structural, not a key list.**
`data_contract.scale_integrity_lost` asks the registry which scale
dependencies the exclusion severed, so registering a second IDP
cross-market source lifts the refusal automatically instead of leaving a
hardcoded refusal behind. The rookie half is checked per row against the
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
