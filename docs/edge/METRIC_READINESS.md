# Consensus Edge — metric readiness inventory

Foundation-first: every candidate input audited before the composite was written. Seven families,
each audited against live code and then adversarially verified (default verdict REFUTED unless the
verifier personally read the code).

| family | readiness | can it drive a user-facing buy/sell today? |
|---|---|---|
| Market value (anchors) | usable after repair | yes, as the price side |
| Internal fair value / circularity | usable after repair | yes, via leave-one-out |
| Sharp Flow | **incomplete → now has data** | not yet — unvalidatable |
| BDVM fundamental value | usable after repair | **no** — excluded, see below |
| Scoring configuration / scoring-fit | usable after repair | **no** — excluded, double-count risk |
| Refresh / staleness | usable after repair | partially |
| Existing buy/sell surfaces | duplicated | n/a — the map Consensus Edge must not add to |

---

## What Consensus Edge actually uses, and what it refuses to use

**Uses:** market anchor (`ktcSfTep` offense / `idpTradeCalc` IDP), leave-one-out expert consensus,
Sharp Flow (displayed, unvalidated), trailing momentum (context only), data quality.

**Deliberately excluded, each for a reason found in the audit:**

- **BDVM.** *Confirmed:* trade values are anchored to the maximum fundamental value of the
  population priced in **that run**, so every value shifts when the population changes; `STRONG_BUY`
  can never fire because the only production caller omits `gap_persisted_days`; and no BDVM
  valuation is ever persisted, so there is no as-of series to backtest against. A component that
  cannot be reproduced historically cannot earn a weight.
- **Scoring-fit as a separate component.** *Confirmed:* league scoring effects are **already**
  multiplied into the league-adjusted board at both position and player level, and the market board
  already contains one scoring-driven repricing (the TE base→tepp conversion). Adding a scoring-fit
  component on top would double count. It belongs inside fair value as a decomposition, which is
  where it already is.
- **The existing retail-vs-consensus `marketGapDirection`.** *Confirmed:* `"none"` never means "the
  market and experts agree" — every `"none"` row is a row with no computable gap; all 398 IDP rows
  are stamped `"none"`; and the backend stamp disagrees with the frontend `marketAction` the
  /rankings page renders on **294 of 553** rows. Unusable as a base.

---

## Blockers found, and what happened to each

### Fixed in this work

| finding | status |
|---|---|
| The v2 migration wiped movements but left `sharp_league_fetch`, making the wipe permanent | **fixed** + 2 regression tests |
| Live `_fair_value` averaged `canonicalSiteValues`, which for 17 rank-signal sources holds a synthetic `999900 − rank×100` encoding | **fixed** — now rank→percentile→Hill |
| The live path computed `log_gap` from a different quantity than the backtest validated | **fixed** — identical construction, pinned by test |
| `market_is_stale=False` / `market_age_days=0` hardcoded, making every staleness guard dead code live | **fixed** — reads the contract's freshness block |
| Un-normalized fallback produced *larger* magnitudes than normalized rows and filled the sell list | **fixed** — shrunk, pinned by test |
| Absent `data_quality` folded in as 1.0 and geometric-meaned, **inflating** confidence 0.50 → 0.71 | **fixed** — caught by this package's own invariant |
| Degenerate cohorts (MAD ≈ 0.01) produced z ≈ 10 from hundredth-of-a-log differences | **fixed** — MAD floor |
| Sharp Flow had **zero** movement data | **fixed** — see below |

### Open, and documented rather than silently inherited

- **IDP `rankDerivedValue` is hard-clamped to ±15% of `idpTradeCalc`, with 43% of ranked IDP rows
  sitting exactly on the boundary.** *Confirmed.* For those rows the board is the anchor, so a
  board-vs-anchor gap is structurally near-zero. Consensus Edge does not use `rankDerivedValue` as
  its fair value, which sidesteps this — but any future IDP work must not reintroduce it.
- **`dataFreshness` reports `idpTradeCalc` fresh from a fetch-SUCCESS stamp while its content moves
  every ~6 days.** *Confirmed.* Freshness measures the fetch, not the data.
- **Sharp Score's activity component reads the same `asset_movements` table the signal aggregates,
  and feeds `manager_quality`** — a closed feedback loop. *Confirmed.*
- **`signal_strength` has no per-(manager, asset) dedup and no league-diversity term**, so one
  prolific manager can outrank several distinct ones. *Confirmed.* Consensus Edge's own
  `sharp_flow_component` does not inherit this: it takes `unique_managers` **and** `unique_leagues`
  and applies a concentration penalty. The underlying Sharp Tracker formula still has it.
- **Neither scoring card is persisted immutably** — only a 12-character hash survives, so
  scoring-derived history is not reproducible. *Confirmed.*

---

## Sharp Flow: from empty to populated

The audit's headline blocker was that there was **no sharp movement data at all** — 0 movements,
0 transactions, 0 crawl cursors — while the cohort and discovery graph were populated. A Consensus
Edge blending Sharp Flow would have weighted it at zero and looked like it was working.

Resolved during this work:

1. Fixed the cursor bug that would have made any future wipe permanent.
2. Promoted one curated industry sharp (`jjzachariason`) through the **review queue** — an audited
   `explicit_admin_review` decision recorded in `sharp_review_decisions`, not a stamp — and seeded
   his public username into the discovery graph.
3. Ran discovery and the transaction crawl.

| | before | after |
|---|---|---|
| observed users | 356 | **12,756** |
| observed leagues | 688 | **1,705** |
| sharp-eligible leagues | 344 | **825** |
| trades | 0 | **418** |
| trade movements | 0 | **3,278** |
| unique managers | 0 | **535** |
| unique leagues | 0 | **191** |
| Super Sharps | 0 | 1 |

Sharp Flow now has real data. It still **cannot be backtested**: the ledger stores no as-of
snapshots, so there is no way to reconstruct what the cohort believed on a past date. It ships
computed, displayed, and labelled `unvalidated_component`.

---

## Refresh and staleness

Jobs feeding Consensus Edge inputs, all writing to gitignored `data/` (so they exist on prod only)
except the market CSVs, which are committed — the property that made the entire historical panel
possible:

| job | schedule | writes |
|---|---|---|
| `scheduled-refresh` | every 2h | `CSVs/site_raw/*.csv` (**committed** — this is the time series) |
| `discover_sharp_graph` | daily 04:20 | discovery graph |
| `crawl_sharp_records` | daily 04:50 | manager seasons |
| `crawl_sharp_transactions` | every 6h | `asset_movements` |
| `refresh_curated_sharps` | daily 06:20 | curated identities |

Staleness ceilings exist (`STALENESS_MAX_AGE_S`: rosters 24h, leagueAnalytics 7d, trending 3h,
intel 48h) and Consensus Edge now reads the contract's freshness block rather than asserting fresh.
The known gap is that freshness measures *fetch success*, not *content change* — an unchanged
upstream file reads as fresh indefinitely.
