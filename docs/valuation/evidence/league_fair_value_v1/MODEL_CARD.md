# Model card — Brisket League Fair Value (`league_fair_value_v1_shadow`)

**Status: SHADOW CHALLENGER. Not served, not promoted, not shown anywhere.**
Code: `src/league_valuation/`. Parameters: `config/league_valuation/fair_value_v1.json`.
Preregistration: `PREREGISTRATION.md` (thresholds TO-FREEZE).

## What it is

A separately named, league-scoped estimate of what a player is worth under our
league's rules, on the canonical 1–9999 scale. It is **market-anchored**: it
starts from the canonical market value (`rankDerivedValue`) and moves a player
only where the league-utility ORDER disagrees with the market ORDER.

Relation to BDVM (one concept, one owner): BDVM owns projection-driven
fundamental value (zero market input, its own 0–10000 scale). League fair value
is a different, market-anchored concept whose only utility evidence is BDVM's
own output — balanced-strategy discounted DV, with BDVM's signed `fpg − R`
(its ReplacementEngine level) breaking ties. No third projection-to-value path
exists. In `src.evidence_lineage` it is member `league_fair_value`, a
descendant of `bdvm_fundamental` inside correlation group
`league_scored_projection`.

## Method (per scope population)

Scopes: OFFENSE = QB/RB/WR/TE; IDP = DL/LB/DB. K and picks are out of scope.

1. **Eligibility.** Excluded with a named reason, and `fairValue ==
   marketValue` exactly: picks, unsupported positions, unkeyable or colliding
   identities, no market value, quarantined, blend-integrity violations,
   single-source haircut rows, two-way override rows, off-cap value-only rows,
   and rows whose utility evidence is missing, proxy-only, stale or of the other
   scope. TE rows stay in, labelled `te_basis_tepp`.
2. **Utility order.** `u_i = (balanced DV, signed points over replacement)`,
   midranks for exact ties. Below replacement stays ordered and distinct from
   missing.
3. **Quantile matching.** `m_i` = the canonical value at utility rank(i) among
   the same population's canonical values; a tie block takes the log-mean of
   its value block.
4. **Interpolation.** `fair_i = exp((1 − k_i) ln v_i + k_i ln m_i)`.
5. **Shrinkage.** `k_i = kMax · q_i`; `q_i` from the utility evidence only
   (projection families, proxy, staleness). Never from the market row's
   confidence. `kMax = 0.25` and the q map are PRIORs.
6. **IDP gate.** The IDP disagreement must pass `scoring_fit`'s depth fan-out
   test (p90/p10 spread of `m/v` across `DEPTH_PROBES`, drift ≤
   `MAX_DEPTH_DRIFT`, every position ≥ `MIN_COHORT_SIZE` with two probes);
   otherwise `k = 0` for the whole IDP scope. On realistic shuffled synthetic
   boards it fails, as the 2026-07-27 IDP scoring-fit measurement predicts.
7. **No ranks or tiers.** The one ranker (`data_contract.compact_ranks_and_tiers`)
   sorts on the canonical value field, and a shadow challenger may never write
   that field, not even on a local copy
   (`tests/api/test_canonical_ownership_protections.py`). A second ranker is
   equally forbidden, so `diagnostics.ranks` is `unavailable` with that reason.
   Ranks wait for an owner-approved serving seam.

## Properties that hold by construction (test-pinned)

| property | test |
|---|---|
| identical orders → exact no-op | `test_identical_orders_are_an_exact_no_op` |
| uniform (or positive-scaled) utility shift → zero movement | `test_uniform_utility_shift_moves_nothing` |
| `k = 1` everywhere → population log-value multiset preserved | `test_k_one_preserves_population_log_value_multiset` |
| fair between `v_i` and `m_i`, inside [1, 9999] (adversarial) | `test_fair_is_bounded_between_own_and_matched_and_inside_scale` |
| stale / missing / proxy / excluded → market exactly | `test_stale_or_missing_evidence_returns_market_exactly` |
| scopes never mix | `test_scopes_never_mix` |
| no canonical field written, inputs untouched | `test_no_canonical_field_is_written_anywhere` |
| market confidence never amplifies `k` | `test_market_confidence_never_amplifies_shrinkage` |

With row-varying `k` the population's level drifts; that drift is reported in
`diagnostics.scopes.<scope>.logDrift` / `valueDrift` and is never claimed zero.
Value-space drift is negative under uniform `k` (geometric interpolation —
Jensen), while log-space drift is zero.

## Answers to the seven rejection defects

1. *Current rosters* — replacement is BDVM's pool-based ReplacementEngine
   (projection pool, durable league format); today's rosters never set it.
2. *Ordinal driver* — the order comes from league-scored points through BDVM's
   exact scorer, never `rosValue`.
3. *0.5 reference* — none exists; centring is structural (a permutation).
4. *Position-wide scalars* — every shift is per player; within-position order
   can change.
5. *Scale* — bounded by construction; no factor clamp.
6. *Staleness* — fresh / stale / missing per input; anything not fresh gives
   `k = 0` (excluded).
7. *Double counting* — only order DISAGREEMENT moves a row; Superflex and TE
   premium already in the market order cannot be re-added.

## Known limitations

* BDVM's balanced DV is truncated at zero by its risk penalty; the signed
  season-0 `fpg − R` orders that block. That tie-break is a declared choice.
* BDVM's `unpriced` entries carry no platform id; they are matched by name ONLY
  to name the exclusion reason, never to supply utility.
* The 2026 rookie class has no BDVM projection (`no_projection`) and keeps its
  market value.
* No validation evidence exists (see the preregistration's expected outcome).
  `kMax` is a prior, not a fitted quantity.

## Production safety

Shadow only. No route, contract field, cache, engine or frontend imports
`src.league_valuation` (`tests/league_valuation/test_isolation.py`). The
withdrawn-lens seam (`server._valuation_scoped_contract`) and
`src/league_intel/{overlay,adjustment,publish}.py` are untouched.
