# AL-2a — target-format evidence census (report-only)

**Status:** implemented, report-only. Authorized by `docs/EXECUTION_PLAN.md` ("Adaptive
Learning" table, AL-2a). Plan: `docs/research/ADAPTIVE_LEARNING_2026-09-26.md` §21.2.
Ledger it reads: #1586 (`src/trade/market_trade_*`). Spec:
`docs/MARKET_TRADE_LEDGER_ACTIONABILITY_SPEC.md` §4 and §19.

## Why it exists

The owner directive of 2026-10-01: before fitting any target-market model, measure what
evidence the completed-trade ledger actually holds against `dynasty_main`'s real format.
That measurement decides whether the first useful IDP latent-price model (AL-2c) should be
exact-format only, close-format hierarchical, or exact plus validated transformed evidence.
This unit decides none of those. It writes no value, no disposition and no ledger row, and
it never treats a mismatched league as comparable to inflate a sample.

## Where it lives

* Owner: `src/trade/market_trade_report.py`, beside `coverage_report`.
  `target_format_census(result)` is the raw form. `build_target_format_census(result)` is
  the publishable, suppressed form. `census_markdown(census)` renders it.
* CLI: `python scripts/market_trade_ledger.py --census [--out DIR]`. It is read-only: it
  builds the ledger in memory and writes `target_format_census_<UTC date>.json` and `.md`.
  The default output directory is `data/market_trades/reports/census/`, which is
  gitignored and stays on the box. It neither rebuilds `underlying_trades.sqlite` nor
  writes the coverage report. `--archive-path`, `--intel-ledger-path`,
  `--acquisition-path` and `--lanes` point it at other stores, such as synthetic fixtures.
* Tests: `tests/trade/test_market_trade_census.py`.

## What is consumed rather than rebuilt

| Quantity | Owner |
|---|---|
| raw observations, lanes | `market_trade_normalize.build_observations` (via `build_ledger`) |
| underlying trades, dedupe states, volume bounds | `market_trade_groups.group_observations`. The census reads `grouping.volume` and the groups' own `dedupeState`; there is no second dedupe |
| cross-source / possible / unresolved counts | `coverage_report` |
| per-axis comparability (13 axes), dispositions | `market_trade_format.compare_formats` / `disposition` |
| roster demand, IDP slot tokens | `src.ros.lineup` via `TradeMarketFormat` |
| factual scoring identity | `scoring_fingerprint` (`TradeMarketFormat.card_hash`) |
| TE scoring edge | `te_premium.measure_te_demand(None, card).has_scoring_edge` |
| IDP trade | `market_trade_eval.classify_topology` flag `includes_idp_player` |
| position family | `src.ros.lineup.lineup_position` |

Formats come from each league's ACTUAL settings and scoring card, never from a label. A
KTC-only row has no scoring card, so every scoring dimension of that row is UNKNOWN.

## The measured quantities

The owner's list, each with the census section that answers it:

* **Raw KTC observations** (`rawObservations.ktc`): archive revisions, distinct KTC trade
  ids, normalized observations, rows with and without a host league id, host platform, and
  rows upgraded to a host-captured format.
* **Raw Sharp/Sleeper observations:** `rawObservations.sharpDiscoverySleeper`, with
  `ownLeagueSleeper` beside it.
* **Confirmed underlying trades** (`dedupe`): the point estimate and lower/upper bounds,
  groups by state, and confirmed groups (unique plus duplicate).
* **Cross-source duplicates:** `dedupe.crossSourceDuplicates`, confirmed and probable.
* **Unresolved overlaps:** `dedupe.unresolvedOverlaps`, which counts POSSIBLE_OVERLAP and
  UNRESOLVED groups.
* **IDP trades** (`idp`):
  * `tradesWithAnIdpPlayer`, split by league IDP state, by disposition and by dedupe state;
  * `tradesInIdpLeagues`.
* **Leagues with IDP:** `idp.leaguesWithIdp` and `leagues.idpEnabled`.
* **Leagues with metadata sufficient for comparison** (`leagues.metadataSufficiency`):
  * "Sufficient" means all 13 axes against the target are known (MATCH or DIFFERENT);
  * the section also counts leagues with a scoring card, with roster demand, and known
    leagues per axis.
* **Exact and near matches to `dynasty_main`** (`matchToTarget`): reported for trades and
  for leagues, plus NATIVE_COMPARABLE and exact/near IDP trades.
* **1QB versus SF populations** (`qbPopulations`): trades, trades by source mix, leagues,
  and the QB (min,max) demand distribution.
* **TE starter and scoring distributions** (`te`):
  * TE (min,max) starter demand;
  * the TE scoring edge;
  * per-TE-key value distributions;
  * KTC's vendor TEP level, kept separate and never translated.
* **IDP starter-count distributions** (`idp.starterStructure`): IDP starters, per-family
  DL/LB/DB (min,max) demand, and IDP_FLEX slots.
* **IDP scoring similarity:** see `idp.scoringSimilarity` below.

`idp.scoringSimilarity` reports, for each IDP key in `IDP_SCORING_CATEGORIES` plus any
other `idp_*` key on the target card:

* the relation distribution: `equal`, `higherInSource`, `lowerInSource`,
  `absentInSource`, `absentInTarget`, `bothAbsent`;
* the median nonzero source value, published only when n ≥ 5.

It also gives one declared summary distribution: the share of the target's nonzero IDP
keys that a league matches exactly, bucketed. It is a distribution, not a similarity score.

The AL-2a acceptance in the plan adds a few more sections:

* per-axis state counts (`axisStates`);
* trades by month × disposition;
* trades containing each position family;
* `translatorSupportSingleDifferingAxisTrades`: trades that differ from the target on
  exactly one axis with no unknown axis. This is the most direct evidence a future
  translator (AL-2b) could be validated against.

## Declared definitions (published verbatim in every census)

* **Exact** (`EXACT_RULE`) requires three things:
  * verified dynasty state: the ledger's own `dynastyState` axis is MATCH (both sides
    verified dynasty);
  * factual scoring identity: equal `scoring_fingerprint` of the actual cards;
  * starting-lineup identity: per-family (min,max) demand, total starters, IDP slot tokens.

  Team count, roster depth and best-ball are not part of it. NATIVE_COMPARABLE, which
  requires all 13 axes to MATCH, is reported beside it. If a component is known to differ
  the result is not exact. If a component is unknowable the result is UNKNOWN.
* **Not dynasty** (`NOT_DYNASTY`): a league whose game type is VERIFIED as not dynasty
  (Sleeper `type` 0 = redraft, 1 = keeper). It is never EXACT or NEAR, however closely its
  lineup and card match. A league whose type is unstated is UNKNOWN, never dynasty: the
  dynasty lane fails closed.
* **Near** (`NEAR_RULE`) is **descriptive only and authorizes nothing**. A league is near
  when it is not exact and all of the following hold:
  * `dynastyState`, `qbDemand`, `idpEnabled` and `teRosterDemand` all MATCH;
  * team count, total starters and IDP starters are each within ±2;
  * the TE scoring edge is equal;
  * both sides have a scoring card.

  A dimension known to differ makes the result NOT_NEAR. Otherwise any unknown dimension
  makes it UNKNOWN, never NOT_NEAR.
* **Stale target scoring.** Only fresh scoring evidence authorizes reuse. When the census
  runs with `--allow-stale-target-scoring` and the target's card is not fresh, the census
  publishes `inputs.staleScoringAcceptedForResearch: true` and refuses EXACT and NEAR
  (`matchToTarget.staleTargetScoringRefusal`). Those comparisons become UNKNOWN. The
  descriptive IDP scoring comparison is labelled `degraded`.
* **IDP trade** means at least one player in the trade is DL/LB/DB.
* **League unit** is a distinct (host, host league id). Own registered leagues that lack a
  host id are keyed by registry key. Trades with no league identity are counted but not
  attributed to a league.

## Unknown stays unknown

Every distribution carries an explicit `UNKNOWN` cell, and nothing unknown is folded into a
known bucket or into `OTHER_SMALL_CELLS`. A league whose format was never captured (a
`discovery_row_partial`) appears as UNKNOWN on superflex, IDP and TE. Its comparisons are
UNKNOWN, never "no match". If the target's own scoring card is unknown (stale or missing
evidence), the IDP scoring comparison refuses with `target_scoring_card_unknown`.
Leagues whose IDP state is unknown are left out of that comparison and counted in
`leaguesExcludedIdpEnabledUnknown`. Unavailable lane counts are `null`, not `0`.

## Privacy (hard rule)

The repository is public. The committed census is **aggregate only**:

* It contains no league id or name, manager or user id, transaction id, underlying-trade
  id, roster or per-trade package. `underlyingTradeSetSha256` is a one-way reproducibility
  pin over the whole sorted id set and reveals no individual id.
* Every count in `sections` from 1 to 4 publishes as `"<5"`.
* Value-keyed distributions (scoring values, starter counts, (min,max) demand) fold a known
  value into `OTHER_SMALL_CELLS` when fewer than 5 **distinct leagues** contribute it. This
  applies to trade-level distributions too: the fold counts leagues, never trades. One
  league with many trades therefore cannot publish its own rare value. A trade with no
  league identity contributes no league.
* A TE scoring key that fewer than 5 leagues use is not named. It is counted in
  `teScoringKeysFoldedBelowMinLeagues`.
* Medians need n ≥ 5.
* Known limitation: a suppressed cell can sometimes be bounded by subtracting its siblings
  from a published total (complementary disclosure). Every cell is a format count, never
  an identity.
* The raw stores and the default output directory are under `data/`, which is gitignored.
  `tests/trade/test_market_trade_census.py` seeds realistic id shapes and greps the JSON and
  the markdown for every one of them verbatim. The shapes are 18-19 digit Sleeper league,
  user and transaction ids, KTC trade ids, and `ktc:<id>`-style composite keys.

## BROAD_CONTEXT reconciliation

The owner's hierarchy names four states: NATIVE_COMPARABLE, VALIDATED_TRANSFORMABLE,
BROAD_CONTEXT and TARGET_UNSUPPORTED. #1586 implements three. Spec §4's BROAD MARKET
CONTEXT and UNSUPPORTED / UNVERIFIED both land in TARGET_UNSUPPORTED, so **the current
dispositions cannot express BROAD_CONTEXT**. This unit does not change #1586's semantics.

What it publishes instead (`broadContextReconciliation`) is a descriptive partition of
TARGET_UNSUPPORTED under the declared `BROAD_CONTEXT_RULE`:

* **Candidate broad context.** The trade's dynasty state is verified (`dynastyState`
  MATCH). Candidates are split two ways:
  * by whether at least one axis is DIFFERENT (`KnownMismatch`) or only UNKNOWN axes
    remain (`UnknownOnly`);
  * by dynasty basis. A KTC row's dynasty state is a source-level claim, not a host
    setting.
* **Unsupported / unverified.** The dynasty state is not verified. The dynasty lane fails
  closed, so these trades can never be context.

**Follow-up (not done here):** a fourth disposition in `market_trade_format.disposition`
needs an owner-approved definition of BROAD_CONTEXT. The descriptive rule above is not that
definition.

## Running it on the box

The orchestrating session runs this after merge and deploy, then commits the aggregate
evidence:

```
python scripts/market_trade_ledger.py --census --out <dir>
```

Agents do not run it against production data themselves.
