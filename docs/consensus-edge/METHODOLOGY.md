# Consensus Edge — methodology

**Status:** built, wired end to end, and behind the `consensus_edge`
feature flag, which defaults **OFF**.

It was ON for part of 2026-08-04, on a top-20 study returning +3.59%
median cohort-excess. An independent audit then found that every IDP
fair value in that study came from a leave-one-out board with no IDP
backbone — numbers on no scale at all. With those rows refused and every
measurement re-run, the same pre-registered gate returns **−1.01%,
beating a random-20 draw in 0 of 6 folds**, so the flag went back OFF the
same day. See "What happens if you follow the board" below, and
ADR-021 / ADR-023.

Nothing here is broken and nothing was deleted: `RISKIT_FEATURE_CONSENSUS_EDGE=1`
plus a restart brings the page and endpoints back for evaluation. What
is withdrawn is the claim that the board tells a user something a coin
flip would not.

**No component has a positive out-of-sample result.** Market Mispricing
has a measured **null** (ρ +0.031 at 14d, beaten by a plain
"buy cheap players" benchmark in 5 of 6 folds) and is the only component
that moves a score. Opportunity has a null too, so its weight is zero.
Sharp Flow has no result and cannot get one until `src/sharp/` can
freeze its cohort as-of a date; its 0.3 is a declared prior. Every
payload stamps `experimental: true` plus per-component `validated` /
`measured` / `outcome` flags. Decisions and their reasoning live in
`DECISIONS.md` beside this file; this page is the short version, and
`AUDIT-2026-08-04.md` is the adversarial one — the status matrix, what
is excluded and why, and what is NOT VERIFIABLE from this repository.

## The problem

Six systems in this repo answer "is this player a buy?" — the Sharps
market signal, the `/edge` retail-vs-consensus rank gap, BDVM market
alpha, `frontend/lib/signal-engine.js`, `roster_intel/targets.py`, and a
never-wired `news/unified_signal_engine.py`. They measure different
things, disagree, and none had been checked against an outcome.

## Market Mispricing

The only component that carries weight.

**Fair value** is the 21-source blend recomputed with the market anchor
removed, through the same `_compute_unified_rankings` the live board
uses — not a second ranker. Offense and IDP get separate boards because
they have different anchors and dropping both leaves no cross-market
scale; each row takes its value from the board that excluded its own
anchor, and the provenance is stamped per row.

Three ways the anchor leaked back in, all measured and closed:
correlated sources (`fantasyNavigatorSf` is KTC-derived — 440 rows), the
KTC-built rookie ladder (already guarded upstream, now pinned), and the
market-corridor clamp (101 IDP rows, mean shift 552). See ADR-002/3/4.

**What the board refuses to price, and why.** Removing a source costs
evidence; removing the source that *defines the scale* changes what the
numbers mean, and the result still looks like an ordinary board. Two row
classes were affected (ADR-021):

- **IDP: no score at all.** `idpTradeCalc` — idptradecalculator.com — is
  both the IDP market anchor and the only source that can build the
  shared-market ladder, because it is the only registry key whose value
  column spans offense *and* IDP (529 positive offense + 258 positive
  IDP). Without it the three IDP-only boards (`dlfIdp`, `idpShow`,
  `fantasyProsIdp`) lose their within-class-to-combined crosswalk and
  vote as though IDP #1 were asset #1 — measured at 220 rows, median
  1.224x, up to 3.48x. All 281 IDP rows come back unpriced with
  `anchor_free_board_lost_idp_backbone`; their idptradecalculator.com
  MARKET value is unaffected and still stamped. This lifts when a source
  publishes offense and IDP in one value pool under one registry key —
  **not** when a flag is set: promoting the other cross-market IDP
  source yields an identity ladder and a bit-identical broken board
  (ADR-025).
- **Rookies whose ladder reference was the anchor: no score.** 75 rows,
  `anchor_free_board_lost_rookie_ladder`. Rookies the affected sources
  never ranked keep their score — the check is per row, against the
  row's own votes.
- **Picks: no score, permanently.** No retail source publishes a pick
  market, so there is no price to call wrong (144 rows).

Every wholly unscored class is counted in `assetClassCoverage` and named
in `caveats`, because an offense-only buy list looks identical whether
that is a decision or a broken join. What survives measures median
0.992, p95 1.015, max 1.173 against the default board — one set of
units.

**Scoring** is `log(fair / market)`, then a robust z against a cohort of
position family × value tier. A raw point gap cannot be ranked across a
board — 500 points is noise on an elite QB and a doubling on a deep LB —
and the measured cohort sigmas confirm it: elite RB/WR/TE 0.035 against
high IDP 0.547, a 16× spread a single board-wide z would have flattened.
MAD rather than SD, because a handful of extreme gaps is what we are
hunting and they would inflate an SD enough to hide themselves.

Cohorts below 12 members fall back to position family alone, stamped as
`cohortLevel: "family"`. Without that, elite QBs (11 rows) scored nothing
on a superflex board.

Sign convention: **positive means underpriced**, i.e. a buy.

## Validation

Replay the board over committed git history (110 as-of dates,
2026-04-16 → 2026-08-03), score mispricing at an origin date, correlate
against cohort-excess market return over the following horizon.
Non-overlapping folds only.

| horizon | usable folds | mean rho | folds positive | beat market-value |
|---|---|---|---|---|
| 7d | 12 | +0.040 | 8/12 | 3/12 |
| 14d | 6 | +0.031 | 4/6 | 1/6 |
| 30d | 2 | — | — | — |

~340 players per fold, offense only (see the refusals above). The script
calls both powered horizons **"no effect detected"** and refuses to call
a direction at 30d on 2 folds. The `marketValue` benchmark — rank the
board by price and buy the expensive end — returns ρ +0.090 and +0.116
against our +0.040 and +0.031: over this offseason panel, expensive
offense assets outperformed their cohort, and our buy list skews cheap
by construction.

An earlier run of this table read +0.089 / +0.126 / +0.111 with 23 of 24
folds beating the market-value benchmark. Those folds included ~350 IDP
rows per fold priced on a scale that does not exist; the edge did not
survive their removal. Attrition is now reported alongside: 0.77% of
scored rows had no measurable outcome at 14d.

Reproduce: `python scripts/run_consensus_edge_backtest.py --horizon-days 14`
(requires `git fetch --unshallow`; the script exits 2 on a shallow clone
rather than measuring a few days and calling it history). Raw
measurements are committed under `docs/measurements/`.

**What configuration this number describes.** The backtest applies no
league scoring fit; `service.build_board` does. Today that is a
distinction without a difference — the repo's Sleeper directory carries
no GSIS ids, so the fit is exactly 1.0 everywhere — but a real directory
in production would multiply served fair values by multipliers this
measurement never saw. The backtest cannot simply apply them: the
reception multipliers are fitted on a whole season and the panel cannot
reconstruct them as-of, so replaying them backwards would be look-ahead
leakage. Instead each measurement stamps its `configuration`, each board
stamps `validationScope`, and a mismatch becomes a caveat on the payload
and a note on the page. See `src/consensus_edge/validation_scope.py`.

## What happens if you follow the board

The ρ above is a statement about a number inside the engine. What a user
sees is a **list of twenty names**, and nothing scored that until
`scripts/validate_consensus_edge_board.py`. It replays the full labelled
board — `service.build_board` and `service.top_movers`, the shipped
functions, not a reimplementation — for every fold origin on the panel.
Its `decision` block is the ship gate, and it was written before the
numbers were.

**Headline: the top-20 buy list does not beat a random-20 draw from the
same priced universe. Not once, at either horizon.**

| horizon | folds | top-20 median excess | folds positive | beat random |
|---|---|---|---|---|
| 7d | 12 | **−0.55%** | 2/12 | **0/12** |
| 14d | 6 | **−1.01%** | 1/6 | **0/6** |

An earlier run of this same study returned +1.51% and +3.59%, beating
random in 11/15 and 6/7, and that is what turned the feature flag ON on
2026-08-04. The study did not change; its input did. Every IDP fair
value in that run came from a leave-one-out board built without the only
registered `is_backbone` source, so those rows carried no scale at all
(see "What the board refuses to price" above, and ADR-021). Refusing
them and re-running is what produced the table above, and it is why the
flag is OFF again — ADR-023.

**The median, not the mean, is the headline, and that is forced by the
data.** These are percentage returns on assets priced 152 to 9999. On one
real fold, four players priced 152–306 returned +327%, +268%, +210% and
+195%, pulling the top-20 mean to **+59.44%** while the median sat at
**+1.04%**. Reporting the mean would have manufactured an edge out of
four floor-priced rookies. Every bucket carries `topContributorShare` so
that dependence is visible rather than implicit.

**Survivorship is reported, not assumed away.** `forward_returns` gives
every row a reason rather than dropping it, but every consumer then
filters on `excessReturn is not None`, so the drop happened one layer
down and went unreported. It is not a random drop — a player leaves the
anchor board because the market let him go. Now measured per bucket:
**12.5% of top-20 buys (15 of 120) could not be scored at 14d**, 8.75%
at 7d, against **0%** for the tradeable-only slice. The rows that vanish
are the cheap ones, which is exactly where the old headline came from.

Labels are **not** monotone, and the best-labelled rows are the worst
(14d medians):

| label | median excess | folds positive | rows |
|---|---|---|---|
| Buy | +0.01% | 4/6 | 317 |
| Insufficient Evidence | +0.03% | 1/6 | 2774 |
| Neutral | −0.04% | 2/6 | 1343 |
| Buy *(demoted from Strong)* | −0.29% | 2/6 | 38 |
| Sell | −0.31% | 0/6 | 307 |
| Strong Sell | −0.28% | 2/6 | 24 |
| **Strong Buy** | **−1.10%** | 2/6 | 30 |

Four findings that matter more than the headline:

- **`Strong Buy` is the worst bucket on the board.** It was the best one
  before the scale repair (+8.83% at 6 of 6 folds), and it was the
  measurement that justified raising the confidence ceiling so those
  rows could be shown at all. Both statements were about rows priced off
  an IDP board with no backbone. On the repaired board the same bucket
  returns −1.10%. This is the single clearest illustration of how far
  the defect reached: it did not merely add noise, it produced the
  finding that changed the model.
- **The sell side is now the better-behaved half, and still is not
  validated.** Sell-labelled rows return −0.31% at 14d with 6 of 6 folds
  negative (−0.18%, 10 of 12, at 7d) — the correct direction, where
  before the repair they were the *wrong* sign. But no random benchmark
  was pre-registered for sells, and a third of a percent sits inside the
  noise the buy side fails in. `sellSideValidation` says exactly this on
  every payload.
- **The edge, such as it is, is not where the list points.** 78% of
  top-20 buys are priced under 2000 on the 0-9999 scale (median 1173).
  The mispricing score is a log ratio, easiest to make large on a
  floor-priced asset, so the list is a deep-sleeper list. Restricted to
  assets at or above 2000 the number turns slightly positive — +0.23%
  (4/6) at 14d, +0.13% (6/12) at 7d — which is the opposite of the
  pre-repair pattern and is still not a result anyone should trade on.
- **A plain "buy cheap players" rule beats us.** The `marketValue`
  benchmark went from ρ −0.020 to **+0.116** at 14d when the IDP rows
  left the universe: over this panel, expensive offense assets
  outperformed their cohort. Our buy list skews cheap by construction,
  so on the rows that survive we are on the wrong side of the only
  benchmark that matters. It beats us in 5 of 6 folds at 14d and 9 of 12
  at 7d.

Also measured, and previously an uncontrolled confound in ρ: **the panel
is not homogeneous.** `CSVs/site_raw/` holds 9 files on 2026-04-16 and 24
from 2026-06-01. The single negative 14-day fold is the thinnest one (9
sources, 184 scored rows). The edge is if anything *dragged down* by the
thin era rather than carried by it.

Reproduce: `python scripts/validate_consensus_edge_board.py --horizon-days 14`.

## What this does not establish

- **Market movement, not production.** The panel covers an offseason, so
  a realised-points target is unavailable rather than unmeasured. This
  signal predicts that a price will move — the right target for a trade,
  the wrong one for a start/sit call.
- **Today's model over past inputs.** Inputs cannot leak (every byte
  comes from a commit at or before the origin), but the pipeline is
  current. Valid for "would this have ranked players usefully?", not for
  "what did the site show that day?".
- **Modest effect.** rho ≈ 0.1 is a real edge, not a strong one.

## The composite

`L` is a weighted blend of the present components, squashed by `tanh` to
`[-100, 100]`. Weights are **0.50 mispricing / 0.30 sharp flow / 0.00
opportunity**, and each has a different provenance, recorded in
`config/consensus_edge/params_v1.json` under `_weightProvenance`:

| component | weight | provenance |
|---|---|---|
| mispricing | 0.50 | measured, **null** — see below |
| sharpFlow | 0.30 | declared prior — unvalidatable, and moot while the ledger is empty |
| opportunity | 0.00 | measured, **null** — see ADR-013 |

This table said "measured, positive" for mispricing until 2026-08-05,
and that was the single most misleading line in these docs: it was the
headline claim about the only component carrying real weight, and it
was backwards. `score.py::COMPONENT_VALIDATION` has said
`validated: False, outcome: "null"` since the scale repair, and
`params_v1.json` has said "measured NULL" beside the weight itself.
The measured result is rho **+0.031** over 6 non-overlapping 14-day
folds (+0.040 over 12 at 7d), with the market-value benchmark — a plain
"buy whatever is cheap" rule — beating it in **5 of 6** and 9 of 12.

The earlier +0.126 that justified the word "positive" was measured on a
board that priced every IDP row on a scale that does not exist (ADR-021).
The 0.50 is a prior like the others; mispricing carries the most weight
because it is the only component that computes at all in a reachable
environment, not because it is validated.

Five behaviours matter more than the arithmetic:

- **Absent components are dropped, not zeroed.** Weights renormalise over
  what is present. A player with no sharp data is not scored as though
  qualified managers had looked and shrugged.
- **A core component is required.** Opportunity alone describes a player
  without saying whether he is mispriced; calling that a Buy is a
  category error, so the score is `None`.
- **Conflict beats the arithmetic.** Strong opposing components force
  `Conflicted` regardless of where the average lands. `+0.8` against
  `−0.8` averages to zero and would otherwise render as Neutral, which is
  the opposite of what the evidence says.
- **Confidence is a conjunction.** A geometric mean over coverage,
  reliability and freshness, so one absent factor collapses the score
  rather than being hidden by three strong ones.
- **A zero-weight component is inert in every direction.** It is
  excluded from `componentsPresent` (so it cannot raise coverage, and
  therefore cannot raise confidence or unlock a label) and from conflict
  detection (so it cannot veto a directional call). Weight zero means
  "measured and not acted on"; a component that still steered the output
  through coverage or conflict would be acted on through a side door.

Labels: Strong Buy / Buy / Neutral / Sell / Strong Sell, plus
`Conflicted`, `Insufficient Evidence`, `No Market Price` and `Withheld`.
Strong labels additionally require high confidence, and the ceiling is a
function of how many **weighted** components are live:

`ceiling = 100 × ((live / weighted) × freshness) ^ ⅓`, and Strong needs
**70**. The denominator is the number of components carrying a non-zero
weight, which is **2** today — mispricing at 0.50 and sharpFlow at 0.30.
Opportunity is at 0.00 and is excluded from the denominator, not counted
as a missing third.

| live / weighted | freshness | ceiling | Strong reachable |
|---|---|---|---|
| 1 / 2 (today) | 1.00 (fresh) | 79.4 | yes |
| 1 / 2 (today) | 0.89 (8h stale) | 76.4 | yes |
| 1 / 2 (today) | 0.50 (staleness unknown) | 63.0 | **no** |
| 2 / 2 | 1.00 | 100.0 | yes |

**Strong labels are reachable today**, and whether they are depends on
freshness rather than on component count alone.

This section previously published a table with a denominator of 3
(1 → 69.3, 2 → 87.4, 3 → 100.0) and asserted "today no player can earn a
Strong Buy". Both were wrong, and the same file disproved them two
sections up: the measured-board table reports a **Strong Buy bucket with
30 rows**. The measurement was taken at `hoursStale: 8.0`, giving a
ceiling of 76.4 — comfortably over the threshold.

It is a *runtime* fact the board computes and publishes as
`confidenceCeiling` / `strongLabelsReachable`, so the payload was right
throughout; only this table was stale. That is exactly why the fields
exist, and why a reader should trust them over any table here.

## Opportunity — measured, and rejected

Two axes, both real, neither carrying weight:

- **`boardMomentumRisk`** — how far the board value has already moved
  over the 30-day rank-history window. Clamped `<= 0`: a rising price
  can temper a buy, never create one. (It previously scored a rising
  price *positively*, which is momentum-chasing; see ADR-013.)
- **`snapTrend`** — recent snap share against the season average, from
  `data/playerctx/snapshot.json`. Replayable but not yet measured; see
  "Components not yet validated" below for the distinction, which is
  not the one this section used to draw.

The momentum axis turned out to be backtestable after all. Board history
was assumed unrecoverable because `data/rank_history.jsonl` is untracked
and always has been — but the panel reconstructs each as-of date from
committed payloads and CSVs, and that yields exactly the value series
that file records. Measured that way:

| horizon | folds | composite rho | mispricing rho | delta | composite beat mispricing |
|---|---|---|---|---|---|
| 7d | 11 | +0.091 | +0.101 | **-0.010** | 3/11 |
| 14d | 5 | +0.119 | +0.129 | **-0.009** | 2/5 |
| 30d | 2 | — | — | — | underpowered |

The axis alone scored -0.072 (7d) and -0.068 (14d): negative on average
and inconsistent per fold. The bar was set before the number was known —
beat the validated component out of sample or carry no weight — so the
weight is zero.

It is still computed and still displayed per row, marked "not counted".
The evidence is real; only its authority is withdrawn. Reproduce:
`python scripts/backtest_consensus_edge_composite.py --horizon-days 7`.

## Components not yet validated

- **Sharp Flow** — the qualified-manager ledger lives in prod-only
  gitignored `data/intel/`, so it is unit-testable here and not
  empirically checkable. It is also not merely unmeasured but
  **unmeasurable by any historical route**, and for two reasons rather
  than the one recorded here until 2026-08-04.

  The recorded reason: the qualified cohort is recomputed live per
  request and `src/sharp/` has no as-of concept, so a historical value
  cannot be reconstructed however much ledger data accumulates. True,
  and a blocker.

  The reason that makes it terminal: **the movement corpus is itself
  conditioned on today's cohort.** `scripts/crawl_sharp_activity.py`
  crawls only managers who qualify *at crawl time* (the first 250,
  sorted by user-id string). A manager who qualified at date D but does
  not now had their movements **never collected**; one who qualified
  later carries only a ~30-day backfill stub. So the corpus is
  survivorship-biased on a proxy for the outcome, the bias is upstream
  of every filter, and an as-of cohort cannot recover data that was
  never gathered. `MOVEMENT_RETENTION_DAYS = 400` caps the rest.

  A historical Sharp Flow backtest is therefore unsound at any budget,
  and deliberately not attempted — a number produced that way would be
  plausible and wrong. The only sound route is forward-only:
  `component_sharp_flow` is snapshotted daily with forward-return
  labelling (`src/consensus_edge/snapshot.py`), which accrues one
  genuine observation per day and needs no reconstruction.

  Two defects that WERE fixable are fixed (2026-08-04). The cohort
  filter is now applied rather than claimed: `inputs.sharp_movements`
  queried `WHERE tx_type = 'trade'` and nothing else while its docstring
  said "qualified-manager", so the filtering was incidental — a property
  of what the crawler happened to collect, not of this code. And
  `managerQuality` is now supplied from the same `CohortMember` records
  the Sharp Tracker weights by; it was never passed, so every manager
  defaulted to 1.0 and the quality term in `aggregate_asset` was a
  constant. `STATUS_NO_COHORT` — declared and unreachable until the
  filter became real — now reaches the payload, so "a ledger exists but
  nobody qualifies" stops reading as "no ledger".

  Three further defects were listed here as known-and-unfixed. Verified
  against the code on 2026-08-05: **two were real and are now fixed; the
  third was overstated.**

  - **No per-manager or per-league contribution cap** — real, and fixed.
    `src/sharp/market.py::_aggregate_window` counted one movement as one
    unit, so a manager active in ten leagues contributed ten
    observations and `breadth_factor = m/(m+3)` saturated too fast to
    push back. It now applies the same share cap Consensus Edge already
    used, from one shared implementation.
  - **A dead `rosterQuality` term carrying 0.22 of the Sharp Score** —
    real, and fixed. Four `ManagerRecord` fields feed it and no builder
    populates any of them, so it was always exactly 0.0 and the total was
    never renormalized: 22 points of a 0-100 scale were unreachable and a
    production-shaped record scored 64.9 against a real maximum of 78.
  - **A quality-lookup key mismatch giving cross-platform managers
    quality 1.0** — **overstated.** The two-key divergence is real in the
    source (`market.py` dedups on `canonicalManagerKey` and looks up
    quality by raw `managerKey`), but the 1.0 default cannot fire:
    `query_movements` filters on the very key list the quality map is
    built from, so every returned row's key is present. The repo's own
    audit had already filed it as unreachable-but-latent; this text
    asserted it as an active defect. What WAS real next to it — an
    inverted default (1.0 is higher than any true cohort member) and a
    genuine cross-platform leak in the *cap* rather than the quality —
    is fixed; see ADR-028.
- **`snapTrend`** (the Opportunity axis above) — replayable since
  2026-08-04, and **not measured for a different reason than the one
  documented here until then**.

  The old reason: the playerctx snapshot is refreshed weekly and never
  committed, so there is no history to replay; unmeasurable until
  snapshots accrue. That was wrong, and wrong in a way that turned a
  missing function argument into a data-collection project. nflverse
  publishes `snap_counts_{season}.csv` as one row per player **per
  game** with a `week` column, and appends a dated snapshot to
  `depth_charts_{season}.csv` on every upstream scrape. The history was
  always upstream; `parse_snap_counts` was the thing discarding it.
  `src/playerctx/asof.py` now resolves a date to the weeks whose games
  had all finished before it (from the nflverse schedule), and
  `service.reconstruct_playerctx` replays the snapshot for that window.
  Verified: the week-22 replay of 2025 is byte-identical to the live
  unbounded read.

  The real reason it is still unmeasured: **the panel is entirely
  offseason.** It spans 2026-04-16 → 2026-08-04, and every one of those
  111 dates resolves to the same completed season and the same final
  week — so `snapTrend` is the identical per-player number on 16 April
  and on 3 August. Each fold yields a valid cross-sectional rho, but the
  folds share one signal snapshot, so averaging them would report N
  folds' confidence for one observation. The backtest's `snapTrend` arm
  measures it anyway and stamps `snapWindows` and
  `effectiveSignalObservations: 1` so the number cannot be read as more
  than it is.

  Retention would not have helped: weekly snapshots across this window
  would have captured ~16 byte-identical blocks. What resolves it is
  in-season dates entering the panel, which happens on its own.

  One residual bias, reported rather than assumed away: the replay joins
  through the **live** Sleeper directory — there is no historical
  edition — so a player out of the league by run time cannot join. The
  arm reports per-source join rates (80.7% for snap counts on the 2025
  season as of 2026-08-04).

## League scoring fit

Not a component. A multiplier applied to **fair value**, inside
`fair_value.py`, because scoring fit changes what a player is worth to
this league — it is not independent evidence that the market is wrong
about him. Adding it as a fourth additive term would count one effect
twice.

Two axes, each gated on what the evidence supports: IDP resolves at
**position** level (per-player IDP ratios measured as mostly noise), and
reception depth resolves **per player**. The reception axis is currently
dark and says so: its multipliers are keyed by GSIS id, contract rows
carry Sleeper ids, and the repo's checked-in Sleeper directory has no
GSIS ids at all. `identity_join.py` returns an empty map rather than
name-matching — a wrong multiplier on the right-looking player is
indistinguishable from a right one downstream.

Combining one measured component with unmeasured ones and reporting a
single number would launder the unmeasured through the measured, so
components are reported separately, each with its own standing.
