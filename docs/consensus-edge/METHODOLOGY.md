# Consensus Edge — methodology

**Status:** shipped behind the `consensus_edge` feature flag, which
defaults **ON** as of 2026-08-04 — on evidence, not on time passing.
The flag was held off while the composite rested on one measured
component and two declared priors; what changed is that the other two
were measured (one returned a null and was zeroed) and the board a user
actually sees was scored, not just the ranking inside it. See "What
happens if you follow the board" below, and ADR-013 / ADR-017.

Market Mispricing has a positive out-of-sample result and is the only
component that moves a score.
Opportunity has an out-of-sample result too — a **null**, so its weight
is zero. Sharp Flow has none and cannot get one until `src/sharp/` can
freeze its cohort as-of a date. Every payload stamps `experimental:
true` plus per-component `validated` / `measured` / `outcome` flags.
Decisions and their reasoning live in `DECISIONS.md` beside this file;
this page is the short version.

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
| 7d | 14 | +0.089 | 12/14 | 13/14 |
| 14d | 7 | +0.126 | 7/7 | 7/7 |
| 30d | 3 | +0.111 | 3/3 | 3/3 |

~680 players per fold. Beats the market-value benchmark in 23 of 24 folds
and a seeded random benchmark in 22 of 24.

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

**Headline: the top-20 buy list beats a random-20 draw from the same
priced universe.**

| horizon | folds | top-20 median excess | folds positive | beat random |
|---|---|---|---|---|
| 7d | 15 | +1.51% | 11/15 | 11/15 |
| 14d | 7 | +3.59% | 6/7 | 6/7 |

Those figures are **after** two fixes the first run of this study
motivated, both measured before adoption:

- **The list is ranked by conviction — score shrunk by its own
  confidence — not by score alone.** A score is a point estimate and
  confidence is its precision; ranking on the estimate threw the
  precision away, and it showed. Measured over 7 fold origins, the old
  top-20 had a median reliability of **0.75** against **1.00** for the
  board: the highest scores were coming from the *least-sourced*
  players, because fewer sources means a wider spread against the anchor
  and a bigger z. Shrinking by confidence took 14d from +1.57% to
  **+3.59%** and 7d from +0.92% to **+1.51%**, replicating at both
  horizons. Chosen over a confidence threshold (which scored similarly)
  because a threshold is a tuned constant and this is not.
- **Coverage counts only components that can contribute.** Zero-weight
  components were excluded from the numerator but left in the
  denominator, so every row carried a deficit no data could ever close.
  That pinned the ceiling at 69.34 against a Strong threshold of 70 —
  and the rows it suppressed turned out to be the best group on the
  board (see below).

**The median, not the mean, is the headline, and that is forced by the
data.** These are percentage returns on assets priced 152 to 9999. On one
real fold, four players priced 152–306 returned +327%, +268%, +210% and
+195%, pulling the top-20 mean to **+59.44%** while the median sat at
**+1.04%**. Reporting the mean would have manufactured an edge out of
four floor-priced rookies. Every bucket carries `topContributorShare` so
that dependence is visible rather than implicit.

Labels come out monotone in the right order on the buy side (14d medians):

| label | median excess | folds positive | rows |
|---|---|---|---|
| **Strong Buy** | **+8.83%** | **6/6** | 69 |
| Buy *(demoted from Strong)* | +0.62% | 2/6 | 67 |
| Buy | +0.07% | 2/7 | 568 |
| Neutral | −0.00% | 1/7 | 2837 |
| Sell | −0.04% | 0/7 | 682 |
| Insufficient Evidence | −0.23% | 0/7 | 877 |

Three findings that matter more than the headline:

- **The label the board used to refuse to show is by far the best one.**
  Before the coverage fix, every would-be Strong Buy was demoted into
  `Buy` and that demoted bucket was the only consistently positive group
  on the board. Once the ceiling stopped counting a zero-weight
  component against every row, those rows could say what they were:
  **Strong Buy returns +8.83% at 6 of 6 folds** (+3.39% at 10 of 12 for
  7d). Note the direction of the reasoning — the measurement came first,
  and the ceiling was changed because it was suppressing a signal that
  demonstrably worked, not to make a nicer-looking label appear.
- **The sell side has no edge at all**, and `Strong Sell` is no
  exception. Sell: 0 of 7 folds correct at 14d, 0 of 15 at 7d. Strong
  Sell: +0.12% and +0.02% — the *wrong sign* for a sell. Conviction
  ranking did not help. Every payload now carries `sellSideValidation`
  and the sells view says so before a user acts on it.
- **The edge is concentrated in assets too cheap to trade for, and this
  is the most consequential finding.** **127 of 140** top-20 buys across
  the 14-day folds — **91%** — are priced under 2000 on the 0-9999
  scale, with a median top-20 market value of **1026**. Restricted to
  assets at or above 2000, the edge falls to +0.10% (4/7 folds) at 14d
  and +0.07% (6/15) at 7d: essentially nothing. The mispricing score is
  a log ratio, which is easiest to make large on a floor-priced asset,
  so `top_movers` — which ranks on score alone — surfaces a deep-sleeper
  list rather than a trade-calculator list. The signal is real; what it
  is a signal *about* is not what the page implies.

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
| mispricing | 0.50 | measured, positive |
| sharpFlow | 0.30 | declared prior — unvalidatable, and moot while the ledger is empty |
| opportunity | 0.00 | measured, **null** — see ADR-013 |

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

| live weighted components | ceiling | Strong reachable |
|---|---|---|
| 1 (today) | 69.3 | no |
| 2 | 87.4 | yes |
| 3 | 100.0 | yes |

So today no player can earn a Strong Buy. That is the design working,
not a gap to be tuned away — and note it is now a *runtime* fact the
board computes and publishes as `confidenceCeiling` /
`strongLabelsReachable`, not a constant. Opportunity briefly made it two
before its weight went to zero.

## Opportunity — measured, and rejected

Two axes, both real, neither carrying weight:

- **`boardMomentumRisk`** — how far the board value has already moved
  over the 30-day rank-history window. Clamped `<= 0`: a rising price
  can temper a buy, never create one. (It previously scored a rising
  price *positively*, which is momentum-chasing; see ADR-013.)
- **`snapTrend`** — recent snap share against the season average, from
  `data/playerctx/snapshot.json`. Production-only, so unreplayable and
  unmeasured.

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
  **unmeasurable** as the code stands: the qualified cohort is
  recomputed live per request and `src/sharp/` has no as-of concept at
  all, so a historical value cannot be reconstructed however much ledger
  data accumulates. Other known defects on `main` documented in the
  audit: no per-manager or per-league contribution cap, a dead
  `rosterQuality` term carrying 0.22 of the Sharp Score, and a
  quality-lookup key mismatch that silently gives cross-platform
  managers quality 1.0.
- **`snapTrend`** (the Opportunity axis above) — the playerctx snapshot
  is refreshed weekly and never committed, so there is no history to
  replay. Unmeasurable until snapshots accrue.

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
