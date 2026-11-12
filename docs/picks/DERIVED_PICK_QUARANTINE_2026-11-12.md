# Derived and tethered picks were quarantined by an evidence check that could not see their basis

**Date:** 2026-11-12 · **Owner:** the `data_contract` pick pipeline (`src/api/data_contract.py`)
**Resolves:** `docs/trade/advisor_evidence/PARITY_REPORT.md` F1 (HIGH, deferred there as an owner question)
**Governing requirements:** `docs/TRADE_CALCULATOR_MARKET_EVIDENCE_EXPANSION_SPEC.md` TC-19 / TC-21,
`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §1

## What the user saw

A three-team trade on `/trade`: Side A and Side B "Withheld", with the reason
`2029 Mid 5th (received, quarantined)`, `2029 Mid 6th (received, quarantined)`,
and the headline "Preliminary — not determinable".

## Root cause (established)

1. `_complete_future_pick_values` prices the picks no vendor publishes by approved
   derivations: rounds 5-6 by the round step (`derived_round_step`,
   `2029 Mid 5th = 2029 Mid 4th × 0.929`, `Mid 6th = Mid 5th × 0.916`), generic
   rows `YYYY Round N` by the mean of the three tiers (`derived_uniform_tier_ev`).
   The rookie tether prices current-year slots from the rookie at that slot
   (`rookie_pool_tether`). Each stamps `pickValueProvenance` naming its basis.
   By construction such a row has **no positive per-source value of its own**.
2. `_validate_and_quarantine_rows` Check 5 flagged every row with a positive value
   and no positive `canonicalSiteValues` entry as `no_valid_source_values`, a
   quarantine-level flag. It predates C1-U6 and never read the provenance, so it
   quarantined every derived and tethered pick.
3. `trade_simulator` copies the row's `quarantined`; `trade_decision.asset_evidence_codes`
   raises `quarantined_values`; the team is `UNABLE`. The browser's preliminary
   meter reads the same stamp (`withheldValueState`). Both consumers were correct;
   the classification was wrong.

Measured (2026-11-12 local board, then the newest archive):

| class | rows quarantined | basis |
|---|---|---|
| 2028/2029 round-5/6 tier picks (`derived_round_step`) | 12 | 4th-round tier rows, 3 sources each, not quarantined |
| 2028/2029 generic `Round 1..6` (`derived_uniform_tier_ev`) | 12 | three tier rows each |
| 2027 slots 6.02-6.12 (`rookie_pool_tether`) | 11 | rookies with 3-17 sources, not quarantined |

2027 6.01 and the round-5 slots escaped only because an unrelated
`dlfRookieSf` key sat in their source map: the same evidence class, classified two
ways. Every basis chain ends in a source-backed, unquarantined row, so all of
them were false positives, not a legitimate quality failure.

The requirements already decided the methodology question F1 left open: TC-19
requires a finite canonical value for every active pick through 2029, including
generic future-round assets and the calculator's hypothetical generic picks;
TC-21 requires a documented method **with uncertainty**. C1-U6 §1 calls these
category A (tether) and B (explicitly PRIOR derivation) values for consumers.

## The fix

Check 5 now asks whether the value has valid evidence
(`_rows_without_valid_evidence`):

* any positive own source value: evidence-backed (unchanged);
* a pick whose provenance class is in `_PICK_BASIS_PRICED_CLASSES`
  (`rookie_pool_tether`, `derived_year_step`, `derived_round_step`,
  `derived_uniform_tier_ev`): evidence-backed exactly when every basis row
  resolves to ONE row with a positive finite value, no other quarantine-level
  flag, and evidence of its own, recursively;
* everything else (players, `direct_market_blend` picks, picks with no
  provenance): unchanged.

A missing, ambiguous, cyclic, valueless or quarantined basis keeps the
quarantine, so a derived number is never more trusted than what it came from.
The pass owns the flag (recomputed each run, never sticky). Uncertainty stays
visible: the rows keep `confidenceBucket: "low"` and their PRIOR provenance, and
the trade decision reports them in `lenses.evidence.detail.lowConfidenceAssets`
(`topUncertainty`: "Low-confidence canonical value for …") with the asset-evidence
confidence axis at MEDIUM.

## Effect (newest archive, `dynasty_export_20261112_102243`, old rule vs new)

* 35 rows change, all picks, only `quarantined` (true → false) and
  `anomalyFlags` (`no_valid_source_values` removed). 0 values, ranks, tiers or
  confidence buckets move; 0 player rows change.
* Board counts: quarantined 47 → 12, `no_valid_source_values` 46 → 11 (the 11
  left are players).
* `validate_api_data_contract`: ok both ways, 0 errors, same 5 warnings.
* Consensus Edge: 0 of 1,103 rows differ (picks carry no market price there).
* BDVM now lists these picks beside their vendor-priced siblings (it skips
  quarantined rows); it never reads or writes the canonical value.

## Tests

`tests/api/test_derived_pick_quarantine.py` (15 of its tests fail on the
previous code): the rule on hand-built rows (chains, generic rows, tether,
quarantined / missing / ambiguous / cyclic / valueless basis, players and
vendor-priced picks unchanged, small values, idempotence); the real archived
board (census, the round-step oracle for 2028/2029, players unchanged); the
reported three-team shape and a two-team trade on real rosters in all three
analysis modes (no `quarantined_values`, picks priced once, conservation,
uncertainty reported), and an injected real quarantine still withholds.
`frontend/__tests__/components/trade-withheld-values.test.jsx` pins that the
preliminary meter follows the backend stamp: the served rows give A and B a
reading, the pre-fix rows reproduce the reported text.

## Adjacent gap the quarantine was masking (not changed here)

For an owned future pick with an unknown slot, the browser's preliminary meter
prices the label it shows ("2029 Mid 5th (own)") at the **Mid tier** row, while
the engine (`market_resolution` → `unknown_slot`) prices it at the **generic**
row (`2029 Round 5`). Both rows were quarantined before this fix, so both
surfaces withheld and the difference never showed. Measured on the
2026-11-12 board:

| year | R1 | R2 | R3 | R4 | R5 | R6 |
|---|---|---|---|---|---|---|
| 2028 Mid vs generic | 4578 / 4693 (−2.5%) | 3022 / 3026 (−0.1%) | 2210 / 2219 (−0.4%) | 1760 / 1726 (+2.0%) | 1635 / 1603 (+2.0%) | 1498 / 1468 (+2.0%) |
| 2029 Mid vs generic | 4155 / 4131 (+0.6%) | 2746 / 2756 (−0.4%) | 2058 / 2070 (−0.6%) | 1583 / 1591 (−0.5%) | 1471 / 1478 (−0.5%) | 1347 / 1354 (−0.5%) |

The War Room's answer (engine, generic row) is the authoritative one; the
preliminary meter can differ by up to 2.5% on such picks. Owner of the fix: the
deferred frontend label-lookup migration onto identity-routed lookup
(`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §7, the C1-U3 deferral; TC-22).
Market tier picks added by name ("2029 Mid 5th") are the same row on both
surfaces and are unaffected.
