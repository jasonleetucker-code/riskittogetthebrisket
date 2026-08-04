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
**Status:** accepted 2026-08-04.

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
