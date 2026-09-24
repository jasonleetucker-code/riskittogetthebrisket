# C1-U6-D2 — a draft class nobody slotted is priced as tiers, never tethered

**Status:** repaired on `claude/peaceful-goodall-3uqtyx` (PR #1411). Defect repair
inside the CLOSED unit C1-U6 (`docs/EXECUTION_PLAN.md` — "do not reopen"); it
restores C1-U6's own acceptance (every pick priced from its own evidence class)
and begins no C1-U7 work (no owned-pick forecasting, no slot distributions).

## 1. The defect (live since the 2026-09-24T07:57Z scrape)

After the 2026 rookie draft the pick markets dropped the 2026 class and priced
2027 as Early/Mid/Late **tiers**. Three things then combined:

1. `site_pick_map.build_site_pick_map` spread each vendor's 2027 tiers into
   slots — correctly stamped `derived_slot_from_tier`;
2. the scraper minted 72 `2027 Pick R.SS` rows valued from the `years_exp == 0`
   pool — the **2026** class, already in the NFL (`model_injected_composite`);
3. `derive_current_draft_year_from_names` saw slot labels for 2027, called it
   the active slot class, and the tether (`_anchor_current_year_picks_to_rookies`)
   priced `2027 Pick 1.01` off Jeremiyah Love (7677 vs KTC's own 8376) while
   `_suppress_generic_pick_tiers_when_slots_exist` set the vendor-priced 2027
   tiers to `None`.

So the one class every market DID price was hidden, and a class it did not slot
was valued from players already drafted.

## 2. Evidence — which signal marks "this class is the one being drafted"

Two tracked archives straddle the rollover:

| archive | 2026 slot provenance | 2027 slot provenance |
|---|---|---|
| `dynasty_export_20260924_005628.zip` | IDPTC `published_slot` ×48; KTC `model_injected_composite` | tiers only |
| `dynasty_export_20260924_075735.zip` | (class gone) | `derived_slot_from_tier` only |

A class's draft order is known exactly when a vendor **publishes its slots**
(`pickAnchorsProvenance` class `published_slot` or `unyeared_slot`). Nothing
else is evidence of an order:

* `derived_slot_from_tier` is our own spread of a tier — counting it would let
  the pick map manufacture the evidence that authorizes the tether (the D1
  self-authentication pattern).
* `model_injected_composite` is the scraper's rookie-pool mint — counting it is
  circular by construction.
* The rookie pool (`years_exp == 0`) says which players are in their first NFL
  season, not which class the picks buy.

**Decision:** `published_slot_years(pickAnchorsProvenance)` is the one rule.
Slot rows for any year it does not contain are dropped before the board decides
its current draft year, so `derive_current_draft_year_from_names` ignores derived
slots by never seeing them. A payload with no provenance at all (pre-D1 legacy)
is **unknown**, not "no evidence", and keeps its rows.

Self-rolling with no dates: the rule reads what vendors publish, so 2027 slots
tether when a market publishes the 2027 order, and 2028 the year after.

## 3. What changed

| where | change |
|---|---|
| `src/api/data_contract.py` | `published_slot_years`, `_drop_unpublished_slot_pick_rows` (runs before `set_observed_current_draft_year`); `_complete_future_pick_values` and the census now include an UNSLOTTED current year (rounds 5-6 by round step, a generic-grade row per round); `_pick_count_floor_for_board` — a tiers-only board has at most `(horizon+1) × 6 × 4 = 96` pick rows, so its floor is 80% of that (77) instead of the slotted-phase 100 |
| `src/api/pick_value_resolution.py` | a slot ref for an unslotted class resolves to that slot's tier row, basis `tier_of_unslotted_class` — the deterministic slot→tier map, not a fabricated slot |
| `src/api/trade_simulator.py` | same slot→tier retry when an exact-slot lookup misses |
| `src/api/draft_capital_fallback.py` | the current season prices through the generic-grade path too (`>=`), since its slots are no longer board rows |
| tests | `tests/api/test_unslotted_draft_class.py` (11, deterministic: synthetic + the two pinned archives); `test_pick_refinement.py` / `test_picks_end_to_end.py` (livedata) derive the slotted year instead of hard-coding 2026; `tests/archive_fixtures.has_published_slot_class` lets the tether-labelling tests pick a slotted-phase scrape |

## 4. Board diff (`scripts/board_diff.py`, same input export, before → after)

* rows 1012 → 946: the 72 `2027 Pick` rows removed, `2027 Round 1..6` added;
  picks 162 → 96; ranked 776 → 800.
* 2027 Early / Mid / Late 1st: `None` (suppressed) → 6784 / 5502 / 4918,
  `direct_market_blend` (KTC 6980, IDPTC 6909 for Early). `2027 Round 1` 5735.
* Contract validates clean: no structural and no source-health errors.
* **Player rows: zero offense values moved.** 241 IDP rows moved (p50 ≈ 0.2%,
  max Jamien Sherwood 2324 → 3261, +40.3%) plus Travis Hunter +0.2% (his value
  is max(WR, DB), so it follows the DB side).

"Zero player rows move" therefore does **not** hold, and the reason is the
documented IDP↔pick coupling (`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md` §8):
IDP rank sources translate onto the IDPTC cross-market backbone, which contains
pick rows. The 72 removed rows carried IDPTC 2027 "slot" values IDPTC never
published; with them out of the combined pool, IDP board positions improve
(Sherwood 272 → 164), which makes `draftSharksIdp` depth-eligible for those
rows. The large moves are IDP players who gained a real vote they were
previously denied, not a re-pricing of the same evidence.

## 5. Residual risk (named, not fixed here)

* **Pre-draft window.** When a vendor publishes next year's slots before
  Sleeper rolls `years_exp`, the tether pool could still be the prior class.
  The published-slot rule does not see the pool's class. It would be caught by
  a check that the pool's draft year equals the slot year. That needs the
  identity owner's draft-year field, so it is a separate unit.
* The scraper still mints the fabricated slot rows. The contract now drops
  them, and the scraper-side mint is harmless but redundant.
* 2027 derived rows (rounds 5-6, generic grades) are quarantined and
  low-confidence, the same treatment 2028 already had.
