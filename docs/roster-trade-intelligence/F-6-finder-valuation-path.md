# F-6 — the trade finder values assets off a parallel valuation path

**Status:** recorded, NOT actioned. Needs a dedicated investigation with
before/after numbers.

**Severity:** P1 architectural. It does not produce a visibly wrong
answer the way F-3 did, so it is not urgent — but it means the
arbitrage engine's core comparison is not the comparison the project
believes it is making.

**Do not fold this into a "while we're here" change.** It moves every
number `/api/trade/finder` emits.

---

## The claim

CLAUDE.md states, of the live value pipeline:

> The live ``/api/data`` contract is produced by
> ``src/api/data_contract.py::_compute_unified_rankings`` — the one and
> only code path that determines live player values ("Final Framework").

`src/trade/finder.py` does not use it.

## Evidence

Two engines, two different value sources:

| Engine | Reads | Which is |
|---|---|---|
| `src/trade/suggestions.py:456` | `row["rankDerivedValue"]` from `playersArray` | Final Framework output — Hill curves, count-aware blend, IDP calibration, pick tethering, **and** the 0.30 single-source retention |
| `src/trade/finder.py:275` | `players[name]["_finalAdjusted"]` | the raw scraper composite |

The `players` dict `finder.py` receives is a verbatim deep copy of the
raw scrape. `src/api/data_contract.py:8004-8022`:

```python
src_payload = raw_payload or {}
src_players = src_payload.get("players") ...
    # per-key shallow copy, no value recomputation
base["players"] = players_by_name
```

and `_finalAdjusted` is set in `Dynasty Scraper.py:6943-6947`:

```python
raw_comp = pdata.get("_composite")
pdata["_rawComposite"] = int(round(raw_comp))
pdata["_finalAdjusted"] = int(round(raw_comp))
```

`_compute_unified_rankings` writes its blended values onto
`playersArray[...]["rankDerivedValue"]` (and applies the single-source
retention at `data_contract.py:6915-6920`). It never writes back into
the `players` dict. So none of the Final Framework reaches `finder.py`.

`server.py:4948` confirms the endpoint passes that dict straight
through:

```python
players = latest_contract_data.get("players")
```

## Why it matters

The finder's premise is *board arbitrage*: our board says one thing,
the retail market says another, trade into the gap. If "our board" is
the raw scraper composite rather than the board the rest of the product
serves, then:

1. **The arbitrage is measured against the wrong baseline.** The values
   the user sees on `/rankings` and in the player popup are
   `rankDerivedValue`. The finder is arbitraging a board the user never
   sees, then presenting the result as an edge on ours.
2. **Every Final Framework correction is invisible here** — scope-aware
   Hill routing, hierarchical anchoring + α-shrinkage, the IDP
   calibration post-pass, the market corridor clamp, pick tethering and
   the future-year pick discount. Pick values in particular are
   tethered downstream of the scraper, so the finder is likely pricing
   picks on an untethered number.
3. **It forces a compensating local constant.** `SINGLE_SOURCE_DISCOUNT
   = 0.88` exists in `finder.py` only because the 0.30 retention never
   reaches it. Its comment claimed it "matched the frontend"; the
   frontend applies no single-source haircut today, so the constant is
   now unanchored and unvalidated. It is load-bearing anyway — see the
   correction note below.

## Correction to the original F-6

The first version of this finding claimed a **double** single-source
haircut: 0.88 stacked on 0.30 for ~0.264 effective. That was wrong.
The two discounts sit on two different pipelines, not stacked on one.
The "obvious" remediation — delete finder's 0.88 — would have left
single-source assets **undiscounted** in the arbitrage finder,
introducing a live value distortion via a fix.

`SINGLE_SOURCE_DISCOUNT` is therefore retained and pinned by
`tests/test_trade_finder.py::TestSingleSourceDiscount`. It should be
deleted only as part of the migration below, when the retention it
substitutes for actually arrives with the values.

## Proposed fix (not implemented)

Move `finder.py` onto the contract's blended values — read
`playersArray` / `rankDerivedValue` the way
`suggestions.py::build_asset_pool_from_contract` already does — and
delete `SINGLE_SOURCE_DISCOUNT` in the same change, since the retention
comes baked in.

This is not a mechanical swap. Required first:

- **Before/after evidence.** Every arbitrage score, ranking and
  threshold interaction changes. `MIN_ASSET_VALUE`, `MAX_BOARD_LOSS`,
  `JUNK_THRESHOLD`, `ELITE_THRESHOLD` and `MULTI_FOR_ONE_MIN_RATIO`
  were all tuned against composite-scale numbers and will need
  re-derivation, not just re-testing.
- **Confirm the two scales are comparable at all.** If the composite
  and `rankDerivedValue` differ materially in shape, the thresholds
  above are not portable and the change is a recalibration, not a
  migration.
- **A decision on picks.** The contract tethers current-year slot picks
  to the merged rookie pool and applies a multiplicative future-year
  discount. The composite does neither. Pick-inclusive trades will move
  the most.

## Scope note

Found while verifying the P2 haircut item on
`claude/ws-j-trade-engine-fixes`. Deliberately left unactioned there:
that branch carries independently-verifiable P1 fixes (F-3 per-market
gate, F-4/F-5 naming and vacuous checks) and folding a valuation-path
change in would make the diff unreviewable.
