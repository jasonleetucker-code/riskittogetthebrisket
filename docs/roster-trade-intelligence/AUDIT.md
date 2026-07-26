# Roster & Trade Intelligence — Phase 1 Audit

Additive workstream (WS-J) layered on the League Intelligence Engine
(WS-E). Nothing here duplicates or replaces LI: valuation, exact scoring,
the best-ball optimizer, replacement levels and the value schema are
consumed as-is from `src/league_intel/`.

Status: audit in progress. Findings below are verified against code, not
assumed.

## F-1 (P1, LIVE DEFECT) — multi-asset packages sum incompatible markets

**Per-player routing is correct.** `src/trade/angle.py::_market_source_for`
sends IDP positions to `idpTradeCalc` and everything else (offense, picks,
K) to `ktcSfTep`, with a documented legacy `ktc` fallback for older
fixtures. Requirements "KTC is the offensive anchor" and "IDPTC is the
defensive anchor" are already satisfied at the player level.

**Package-level aggregation is not.** In `_make_candidate`:

```python
counter_market_values = [p["market_value"] for p in combo]
... _adjusted_pair_totals(counter_market_values, offer_market_values)
market_sum = sum(counter_market_values)
```

`combo` is not constrained to a single market. When a package mixes
offense and IDP, KTC points and IDPTC points are added directly, and the
resulting `market_gain_pct` gates whether the candidate is shown as
externally fair.

**There is no cross-market normalization anywhere in the repository.** A
repo-wide search for market normalization returns only two unrelated
name-collision comments in `data_contract.py`.

So mixed offense↔IDP packages on `/angle` are currently described as
market-fair on the basis of an addition that has no defined meaning. This
is live today, not a gap in the new work.

**Consequence for this workstream:** requirement 9 (mixed trades use
validated normalization) cannot be met by wiring existing values together.
Normalization has to be built and validated first, and it is the gating
dependency for the Trade Package Generator and the Market-Fair/Model-Positive
feature. Until it exists, mixed-market packages must be either suppressed
or labelled as un-normalized — **not** silently ranked.

## F-2 — value-adjustment curve is applied to both scales identically

`_adjusted_pair_totals` applies a KTC-style value adjustment to package
totals. It is applied to the IDPTC-sourced totals with the same curve. The
curve was derived from KTC's consolidation behaviour; whether IDPTC's
value distribution warrants the same shape is unverified. Flagged, not
changed — it needs the same paired evidence the normalization does.

## What already exists and must be reused, not rebuilt

| Capability | Location | Reuse |
|---|---|---|
| Exact scoring (141 keys, golden-validated) | `src/league_intel/scorer.py` | as-is |
| Exact best-ball optimizer + `fantasy_positions` | `src/ros/lineup.py` | as-is |
| Replacement levels, endogenous starters, scarcity | `src/league_intel/replacement.py` | as-is |
| Value schema + `get_active_value` selector | `src/league_intel/values.py` | as-is |
| Guardrails, evidence tiers, confidence | `src/league_intel/adjustment.py` | extend |
| ROS aggregation + team strength | `src/ros/` | as-is |
| Trade suggestions (sell-high/buy-low/consolidation) | `src/trade/suggestions.py` | extend |
| KTC arbitrage finder | `src/trade/finder.py` | extend |
| Counter-package builder | `src/trade/angle.py` | extend (after F-1) |
| Monte Carlo trade sim | `src/trade/monte_carlo.py` | reuse for deltas |
| Playoff/championship sim | `src/ros/playoff_sim.py` | reuse for deltas |
| Player identity | `src/identity/` | as-is |

Two trade engines already exist (`suggestions.py`, `finder.py`) plus
`angle.py`. The directive's Trade Opportunity / Package / Partner engines
extend these; a fourth parallel implementation would violate the repo's
one-live-path rule.

## Open questions before implementation

1. **Normalization evidence.** What anchors a common scale? Candidates:
   players with values on both boards, actual league trades (12 managers,
   thin), pick equivalents, replacement-level anchoring. Sample size is the
   binding constraint and the answer may be "no defensible normalization
   yet" — in which case mixed packages stay suppressed and that is the
   honest outcome.
2. **Acceptance model.** 12 managers with limited trade history. Strong
   shrinkage is mandatory; a manager-specific term likely never earns its
   keep. Plan for a plausibility prior + market fairness + need alignment,
   with manager effects gated behind an evidence threshold.
3. **Projection source.** `categories_rescored` requires raw per-category
   projections. Draft Sharks currently gives a point total computed under
   *their* scoring, which cannot qualify. Blocks the ROS half of several
   requirements until resolved.

## Deliberate scope calls

- No new valuation path. League-adjusted values come from WS-E only.
- No self-modifying production code; champion–challenger with explicit
  promotion, per the directive and ADR-003's precedent.
- Nothing user-visible ships without confidence stamps and the no-op
  default, matching the LI Phase-3 rule already in force.
