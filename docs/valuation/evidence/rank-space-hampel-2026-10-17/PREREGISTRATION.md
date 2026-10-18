# Rank-space Hampel challenger: preregistration

Owner master package 2026-10-17, Workstream H.  Source & valuation audit 2026-10-13, finding F1:
at the top of the board the incumbent per-player Hampel filter rejects the value-direct market
sources (KTC Crowd, KTC Trades, IDP Trade Calculator).  The rank-signal sources convert through
the Hill curve into values compressed against the 9,999 ceiling, so their median absolute deviation
is tiny, and a market vote ~1,000–1,300 points lower reads as an outlier (Puka Nacua, 2026-10-13:
6 of 15 sources dropped).  The question is whether outlier detection should run in the coordinate
system the evidence was produced in.

This document is committed **before** any outcome, disagreement count or replay of the challenger
has been computed.  Nothing about the challenger has been run.  If any definition changes after
results are seen, the change is reported as a deviation beside the original.

Agent-OS-Receipt: cdca1dca8385f70c0989302dece8d1bd4ce4843c

## 1. Champion and challenger

* **Champion** — the served per-player Hampel filter (`data_contract._hampel_filter_per_player`,
  K = 2.75, n ≥ 4, MAD > 0, ≥ 2 survivors, 1,000-point absolute floor), unchanged.
* **Challenger `rank-space-hampel-v1`** — the same filter, same K, same guards, computed on
  percentile coordinates instead of values:
  1. Each voting observation's value v (its stamped `valueContribution`) maps to u = H⁻¹(v),
     where H is the row's own scope master Hill curve (`src/canonical/player_valuation.py`, the
     curve that produced the rank-signal votes).  Rank-signal votes therefore map back to the
     percentile they came from; value-direct votes map to the percentile they imply.
  2. Median and MAD are taken over u; an observation is an outlier when |u − median| > K · MAD.
  3. The absolute floor is the incumbent's 1,000 Hill points carried into percentile space at
     the row's median: floor_u = H⁻¹(H(u_med) + 500) − H⁻¹(H(u_med) − 500), clamped to the
     curve's domain.  A disagreement the incumbent's floor protects at that level stays protected.
     No constant is tuned.
  4. Pick rows skip the filter, as today.
* Exactly one challenger.  The joint robust filter (`joint-robust-v2`, its own preregistration) is
  a separate, weighting-based challenger and is not modified or re-evaluated here.

## 2. Evaluation (inherited, unchanged)

Inputs, pins, units of analysis, outcomes, metrics, horizons, uncertainty, minimum sample and the
decision table are **exactly** those of
`docs/valuation/evidence/joint-filter-shadow-2026-10-01/PREREGISTRATION.md` §§2–6 (leave-family-out
consensus target; P1 = Δ mean consensus-lead share K vs X at h = 7; G1 published-value guard; date-
block bootstrap, 4,000 resamples; PROMOTION-ELIGIBLE / NOT BETTER / INCONCLUSIVE), with "challenger"
read as `rank-space-hampel-v1`.  The bootstrap seed is 17 (not 1571) so the two evaluations are not
mistaken for one another.

Board span: every archive in `exports/archive/` complete under the contract's own source-health rule
at evaluation time (the archive now runs through 2026-10-17).  S1–S6 as in the inherited §6.

## 3. F1 diagnostics (report; they do not decide)

* D1 — share of value-direct market observations rejected, by consensus-rank band (1–24, 25–50,
  51–100, 101–200, 201–400, 401–800), champion vs challenger.
* D2 — rows where at least one market observation is rejected, same bands.
* D3 — published-value movement (median / p90 relative) and top-24 / top-100 / top-200 membership
  changes, offense and IDP separately.
* D4 — family balance: rows where the filter removes every observation of one family.
* D5 — the median model value vs KTC Market (normalised) per band, the F1 table, champion vs
  challenger.  KTC Market is a benchmark, never a vote; **this diagnostic is not a target** — the
  owner directive is that values are not tuned toward KTC Market.

## 4. Decision

PROMOTION-ELIGIBLE requires the inherited §5 rule **and** an independent fresh-context review **and**
owner approval.  Nothing here flips a flag.  A NOT BETTER or INCONCLUSIVE result keeps the champion;
a challenger that reduces F1 rejections but does not pass P1/G1 is recorded as such.

## 5. Known limitations, stated in advance

* H⁻¹ is the inverse of a curve fitted on value-based observations; for a value-direct source the
  implied percentile is only as good as that fit at its level.
* The leave-family-out consensus target is formed from the same pool of sources; it measures
  agreement with later independent evidence, not truth.
* Daily boards are strongly dependent; the bootstrap blocks and S2 address part of that.
