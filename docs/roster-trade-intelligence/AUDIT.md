# Roster & Trade Intelligence — Phase 1 Audit

Additive workstream (WS-J) layered on the League Intelligence Engine
(WS-E). Nothing here duplicates or replaces LI: valuation, exact scoring,
the best-ball optimizer, replacement levels and the value schema are
consumed as-is from `src/league_intel/`.

Status: audit in progress. Findings below are verified against code, not
assumed.

> **F-1 was DOWNGRADED to P3 after review, and its location was wrong.**
> Severity, remediation and reachability all corrected below — see
> "Review corrections". The new P1 is **F-3**: the trade finder is
> silently offense-only in an IDP league.

## F-1 (~~P1~~ → **P3**, undocumented assumption) — packages sum across markets

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

## Review corrections to F-1 (fresh-eyes pass, 2026-07-26)

Three things I got wrong. Recorded rather than silently edited, because
the workstream was scoped around them.

**1. Severity overstated.** I called the aggregation "an addition with no
defined meaning." It has one, and it is measurable: both boards cap at
9999, IDPTC prices the same 475 offensive players at effectively identical
values, and the implicit conversion factor is **~1.00** (median 1.000,
p10 0.888, p90 1.054). The pipeline's `raw / site_max × 9999` step is
therefore a **no-op between these two sources** — there is no units
mismatch. This is an undocumented, unpinned, unalarmed assumption (P3),
not a P1 live defect.

**2. Remediation was an over-correction — RESOLVED, and the resolution
beats both starting positions.** WS-E re-examined its own 15% suppression
bucket and it did not survive: all 25 packages contained an asset IDPTC
declines to price, max value **1,004**, overall KTC ranks ~445-477 (Josh
Oliver, Carson Wentz, Ray-Ray McCloud). IDPTC simply doesn't price the
tail. **Restricted to assets anyone would actually trade (value ≥ 1500),
100% of mixed packages resolve on the exact path** across 2-, 3- and
4-asset combinations — zero suppression, zero conversion. The original 15%
was an artifact of sampling players nobody trades.

The gate is now **materiality, not presence**: fringe assets convert at the
measured per-position ratio, and a package is withheld only when the
conversion's 80% uncertainty band (p10 0.886 / p90 1.054) exceeds a 5%
threshold — deliberately the same gate `angle.py` applies to
`market_gain_pct`, so the test is "could this uncertainty flip the caller's
decision," not "did a conversion happen." Measured: a fringe asset inside a
real package converts at ~1% band and stays rankable; the same asset
dominating a two-asset package still suppresses at ~10%.

WS-E's one temper on the review: ~1% is the *median*, and the p10/p90
spread is 0.886-1.054. That tail is why a gate remains at all — it now
fires on magnitude rather than existence.

**3. Location wrong.** I put the defect in the counter-side `combo`, which
requires `include_idp=True`. The frontend never sends `includeIdp`
(`frontend/app/angle/page.jsx:226-245`), so that path is unreachable from
the UI. The genuinely reachable shape is the **offer side**, which has no
IDP gate at all (`angle.py:378-388`, `:471-478`) — one IDPTC value in the
denominator against KTC values in the numerator at `:526`. Any fix must
also land in both near-duplicate `_make_candidate` implementations
(`:500` offer mode, `:913` acquire mode).

## F-3 (P1, LIVE) — `/api/trade/finder` is offense-only in an IDP league

`finder.py:274-283` builds `with_ktc = [a for a in pool if a.has_ktc]` and
drops everything outside the KTC top-150. `ktc_value` reads only
`ktcSfTep`/`ktc` (`:229-240`), and **KTC's board contains zero IDP
defenders** — Hutchinson, Parsons, Garrett, Carter, Verse, Campbell all
absent. `EXCLUDED_POSITIONS` (`:33`) is only `{K,PK,DST,DEF}`, so IDP
players enter the pool at `:259` and are then silently removed at `:283`.

No warning is emitted. In a league with 9 IDP starters, the arbitrage
finder returns offense and picks only.

**Downstream: an entire dead guard.** Because every survivor has KTC, the
IDP-dilution guard (`:353-355`), the partial-coverage branch (`:416-420`),
`PARTIAL_KTC_ARBITRAGE_CAP` (`:447`) and the partial-KTC demotion
(`:710-716`) are all unreachable, and `trade_has_idp` (`:421`) is always
False. That code was written for a world the filter silently removed.

## F-4 (P1) — `suggestions.py`'s "KTC filter" never reads KTC

`_assign_ktc_ranks` (`:508-524`) enumerates a pool already sorted by
`display_value` (`:293`), so `ktc_rank` is the **blended-board rank**. No
KTC value is consulted. The docstring claiming "players without KTC data
get `ktc_rank=None`" is false, the constant name is wrong, and
`metadata["ktcTopNFilter"]` (`:1519`) misreports what ran.

**CLAUDE.md is wrong about both engines**: it states both enforce "a KTC
top-150 quality filter". `finder.py` does and thereby excludes IDP;
`suggestions.py` does not and includes IDP. Same constant name, same field
name, opposite behaviour. A manager asking both engines about one
IDP-heavy roster gets IDP trades from one and none from the other.

## F-5 (P2) — single-source assets are discounted twice

`finder.py:29` applies `SINGLE_SOURCE_DISCOUNT = 0.88` to `_finalAdjusted`
at `:223-226`. But `_finalAdjusted` is **already** post-haircut —
`data_contract.py:6916` applies `_SINGLE_SOURCE_VALUE_RETENTION = 0.30`.
Effective retention ≈ **0.264**. The two also fire on different
populations: the pipeline counts post-Hampel survivors, finder counts raw
pre-Hampel `_sites` (`:222`). Two independently-chosen constants on two
non-identical populations.

## F-6 (P2) — six new vacuous-check instances

Including two test suites asserting **contradictory definitions of the
same field**: `test_trade_suggestions.py:2036` pins `ktc_rank` as
enumeration order, while `test_trade_finder.py:1489` asserts it is "based
on KTC value, not model value." Also a condition that can never be False
(`suggestions.py:537`), an assertion that cannot fail
(`test_trade_suggestions.py:2022`), and a fixture emitting only
`["QB","RB","WR","TE"]` (`:1996-2000`) that makes the entire
`TestKtcTopNFilter` class structurally incapable of observing IDP.

## F-7 (P2) — three IDP position sets, contradicting CLAUDE.md

`angle.py:34` (14 entries), `finder.py:50` (3), `monte_carlo.py:343` (5,
adds `CB`/`S`). Behaviourally equivalent only if `_norm_pos` ran first;
`finder.py` applies it (`:244`), the others carry defensive supersets.
CLAUDE.md claims `src/utils/name_clean.py` is the single source of truth
for position normalization — for IDP classification it is not.

## Verified clean

`monte_carlo.py`, `team_impact.py`, `correlation_matrix.py` read no
`canonicalSiteValues` and consume blended contract values already on the
common internal scale — no cross-market contamination. `_value_pair`'s
legacy `ktc` fallback is not a defect (both boards cap at 9999).

Not reached: frontend trade surfaces, and `suggestions.py`'s non-KTC
threshold surface.

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

1. ~~**Normalization evidence.**~~ **RESOLVED — and this question was
   posed wrongly.** I proposed league trades (12 managers) as the likely
   anchor and concluded sample size was binding. That was wrong, and the
   pessimism it produced was unfounded.

   **`idpTradeCalc` is a cross-market board: it prices offense too.** The
   two boards therefore price the same players, and the scale relation is
   directly observable rather than needing to be inferred from trades.
   Independently verified on live data (orchestrator, 2026-07-26):

   | | |
   |---|---|
   | players priced on **both** boards | **475** |
   | pooled median `IDPTC / ktcSfTep` | **1.0004** |
   | board maxima | 9999 / 9999 |

   WS-E measured the same thing at 476 and 0.9997 (Spearman 0.990), with
   per-position medians QB 1.020 / RB 0.994 / WR 1.012 / PICK 1.000 and
   **TE 0.895** — the sole material divergence, and it is the TE-premium
   question (`ktcSfTep` is a TE++ board), not a scale artifact.

   The boards are already on a common scale. See WS-E's ADR for the design
   consequence: because IDPTC spans both universes, the primary strategy is
   to value each package *entirely within one market* rather than convert
   between them — exact, with no fitted parameter. 85% of mixed packages
   resolve on that exact path; 15% suppress. A scalar fallback exists but
   is opt-in, half-confidence, and carries its measured error.

   **The load-bearing assumption that remains** (stamped
   `SHARED_SCALE_ASSUMPTION`, not buried): that IDPTC's internal
   offense↔IDP exchange rate is *correct*, not merely self-consistent.
   Nothing validates it — there is no ground truth for what an edge rusher
   is worth in WR points. The interleaving evidence establishes coherence,
   not accuracy.
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
