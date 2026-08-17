# C1-U6 D1 — the board is pricing 2029 picks at their 2028 price

**Status:** OPEN — live defect on `main`, present in every board built since
**2026-08-17 02:11 UTC**
**Class:** canonical value defect (pick valuation) + fabricated market evidence
**Found by:** `tests/api/test_pick_completeness_red.py::TestRed3UncalibratedCloneDiscountRetired::test_derived_2029_value_uses_measured_year_step`,
which is doing exactly its job and **must not be changed**
**Discovered:** 2026-08-17, while independently re-checking why that test reddens
every PR based on `main`

---

## 1. The finding

**Nine of eighteen `(tier, round)` cells price the 2029 pick at or above its 2028
equivalent**, and every 2029 row is stamped `pickValueProvenance: {"class":
"direct_market_blend"}` — a claim that a market priced it.

No market priced it. Every 2029 value is a **verbatim copy of the 2028 value**.

Measured on `main` @ `776cfa9`, from `exports/latest/dynasty_data_2026-08-17.json`
(reproduced identically from the newest complete archive
`dynasty_export_20260817_033535.zip`, so this is not a one-scrape artifact):

| cell | 2029 | 2028 | ratio |
|---|---:|---:|---:|
| Mid 4th | 1590 | 1536 | **1.0352** |
| Mid 5th | 1477 | 1427 | **1.0350** |
| Mid 6th | 1353 | 1307 | **1.0352** |
| Late 3rd | 2003 | 1991 | **1.0060** |
| Late 1st | 4132 | 4109 | **1.0056** |
| Early 5th | 1519 | 1512 | **1.0046** |
| Early 4th | 1635 | 1628 | **1.0043** |
| Early 6th | 1391 | 1385 | **1.0043** |
| Mid 2nd | 2997 | 2995 | **1.0007** |
| *(the other 9 cells)* | | | 0.964 – 0.999 |

Even the non-violating cells are wrong: the measured vendor one-year step is
**0.841** (`config/weights/pick_year_discount.json::derivedYearModel`, per-cell
range 0.71–0.90). Every cell here sits at ~1.00.

**Contrast the same board one scrape earlier** (`dynasty_export_20260816_225946.zip`,
which is the base C1-U5 is stacked on): 2029 was *derived*, provenance
`derived_year_step`, ratios **0.7044 – 0.9221**, **0 violations in 18 cells**. That
is the correct behaviour, and it is what C1-U6 shipped.

---

## 2. When it started, exactly

`2029 Early 1st` in the **raw** scraper payload, across the archive:

| archive | 2028 Early 1st | 2029 Early 1st |
|---|---|---|
| `20260817_033535` | `ktc=5198 idptc=5034` | `ktc=5198 idptc=5034` |
| `20260817_021149` | `ktc=5180 idptc=5034` | `ktc=5180 idptc=5034` |
| `20260816_225946` | `ktc=5168 idptc=5034` | **ABSENT** |
| …11 earlier archives… | *(varies)* | **ABSENT** |

The 2029 row appears for the first time at **2026-08-17 02:11 UTC** and is
byte-identical to its 2028 twin on every scrape since, for **both** pick families.

Both runs either side of the transition have the same health
(`overallStatus: partial`, `partialSources: [KTC_TradeDB, KTC_WaiverDB]`,
`completeSources: [IDPTradeCalc, KTC]`), so this is not a degraded scrape.

Two vendors independently publishing a 2029 board that is a byte-exact clone of
their 2028 board, on the same scrape, is not a plausible market event. It is our
pipeline.

Confirmed in `pickAnchorsRaw` — **all 12 of each family's new 2029 anchors equal
their 2028 twin, 0 differ**:

```
ktc          2029 Early 1st = 5180   |  2028 Early 1st = 5180
idpTradeCalc 2029 Early 1st = 5034   |  2028 Early 1st = 5034
```

---

## 3. Mechanism — a fabrication that authenticates itself

Two defects in series. Neither is sufficient alone, which is why this survived
until now.

### 3.1 Root: the anchor builder invents values for years no source published

`Dynasty Scraper.py::_build_site_pick_map` is asked for
`target_pick_years = [current, +1, +2, +3]` (`Dynasty Scraper.py:4934`) — so 2029
is *always* requested. When a source has no rows for the requested year,
`lookup_tier` falls through to a **nearest-year substitution**
(`Dynasty Scraper.py:4853-4862`, and again for slots at `:4896-4906`):

```python
years_with_tier = {y for (y, r, t) in tier_values if y is not None and r == round_num and t == tier}
near_year = _nearest_year(years_with_tier, year)      # _nearest_year: min(|y - target|)
if near_year is not None:
    vals = tier_values.get((near_year, round_num, tier), [])
    if vals:
        return _avg(vals)                              # 2028's number, emitted as 2029's
```

The returned value is written out under the **requested** year's name
(`:4915-4919`), unstepped and unmarked. Nothing downstream can tell it apart from
an observation.

This is the sibling of **MISSING IS NEVER ZERO**: *missing is not the nearest
neighbour's value either*. A year no vendor priced must stay unpriced at the
evidence layer, so that the owner of "years no vendor publishes" —
`_inject_far_future_pick_sources` — can do its job.

### 3.2 The regression that exposed it: the fabricated year authenticates itself

The scraper's pick-model rebuild used to hard-code `_future_pick_years = (2027, 2028)`.
C1-U6 replaced that literal with a data-derived value so it would self-roll
(`Dynasty Scraper.py:6196`):

```python
_legacy_pick_anchors = pick_anchors            # :6164 — the EARLY path's output
_anchor_keys = sorted({k for _s, _m in _legacy_pick_anchors.items() ... for k in _m})
_future_pick_years = tuple(derive_future_tier_years_from_names(_anchor_keys, _pick_model_year))
```

`pick_anchors` at that point is precisely the map §3.1 fabricated into. So the
derivation reads its own fabrication back as evidence that a vendor published
2029, and the rebuild then mints 2029 rows carrying 2028's per-source values
verbatim. Confirmed in the payload: `2029 Early 5th` exists in `players`, and
rounds 5–6 are only ever minted by the rebuild.

`derive_future_tier_years_from_names`'s own docstring records the measurement
taken when it landed — *"Data says `[2027, 2028]` today … byte-identical to the
retired literals"* — and that measurement is now stale. The literal had been
**masking** the fabrication; making it self-rolling let it roll onto a fabricated
year.

### 3.3 Why nothing downstream caught it

Each stage behaves correctly given what it was told:

1. `_inject_far_future_pick_sources` only derives years **no vendor publishes**. It
   is told a vendor published 2029, so it correctly declines.
2. Vendor-priced years take **no** year discount by design (T-3/C-2 — their prices
   already encode the term-structure premium), so nothing steps it.
3. `_apply_pick_year_discount_to_blend` has been stamp-only since C1-U6, so it
   multiplies nothing.

Net: a three-years-out pick publishes at its two-years-out price, with a
provenance stamp asserting a market priced it.

This is the **RED-4** class C1-U6 made unrepresentable — *"a clone presents the
template year's vendor numbers verbatim"* — re-entering through a door C1-U6 never
touched. The retired clone path is still gone; this is a different origin for the
same wrong number.

---

## 3.4 Four more safety rails are already firing — in the advisory lane

Added after the first CI run on this branch (run 31992373267). The hard gate fails on the
year-step test above; the **`livedata` lane fails four more times, all on the same nine
rows**, and it supplies a fact the archive analysis could not:

```
{'canonicalName': '2029 Early 1st', 'position': 'PICK', 'rank': 70,
 'matchedSources': ['idpTradeCalc'],
 'reason': 'matching_failure_other_sources_eligible'}
```

- `tests/api/test_launch_readiness.py::test_no_unexplained_1src_top400` — 9 rows
- `tests/api/test_picks_end_to_end.py::test_no_unexplained_single_source_with_picks`
- `tests/api/test_player_identity_regression.py::test_no_unannotated_single_source_in_top_board`
  — ranks **#70, #88, #98, #167, #185**
- `tests/api/test_source_monitoring.py::test_launch_readiness_gates_still_pass` (aggregate)

Two things this adds:

1. **Only ONE family votes on these rows.** `ktc` is present in `canonicalSiteValues` but is
   the scraper's own model composite, retired from voting in 2026-04-28 — so every 2029 row
   is a single-source row carrying the 30% single-source haircut, at ranks inside the top
   200.
2. **The pipeline itself classifies them as `matching_failure_other_sources_eligible`** —
   it believes other sources should have covered these rows and did not. That is exactly
   what a fabricated year looks like from the inside: the anchors assert 2029 exists, so
   every family becomes "eligible", while only the fabrication reaches the blend.

The board's own instrumentation caught this. It did not block because these four tests are
`livedata` (advisory), which is the correct classification for them — they *are* statements
about source coverage. The year-step test is the one that belongs in the hard gate, and it
is the one that fired there.

## 4. Blast radius

- **Every 2029 pick on the live board**, in the canonical `rankDerivedValue` — so
  in the trade calculator, trade suggestions, the arbitrage finder, angles, the
  simulator and draft capital.
- **Direction: over-valued.** A 2029 first is being priced ~19% above what the
  measured vendor step gives (5034 vs 3593 for Early 1st).
- **`canonicalSiteValues` too**, so market-anchor consumers read the undiscounted
  anchor — the asymmetry RED-4 named.
- Contained to pick rows. IDP player values shift ≲0.1% through the IDPTC
  cross-market backbone (the known, documented coupling).

---

## 5. Recommended repair — and what must NOT be done

**Fix at the root (§3.1).** Remove the nearest-year substitution from
`lookup_tier` and `lookup_slot` so a source contributes nothing for a year it did
not publish. `target_pick_years` requesting `current + 3` then becomes harmless,
`derive_future_tier_years_from_names` sees only genuinely published years, and
`_inject_far_future_pick_sources` resumes owning the far-future derivation — which
is the design C1-U6 shipped and which measured 0 violations in 18 cells.

Fixing §3.2 alone would be treating the symptom: the fabricated rows would still
sit in `pickAnchors` as unmarked evidence.

**Do not:**

- **Weaken or reclassify the test.** It is a correct assertion that found a real
  live defect. Marking it `livedata` would hide a canonical-value error; loosening
  the bound would encode the broken behaviour.
- **Special-case the year 2029.** The horizon self-rolls; a literal would break in
  May 2027.
- **Clamp 2029 to `2028 × 0.841` at the blend.** That reintroduces a
  post-hoc multiplier on a value already stamped as market-observed — the
  arrangement C1-U6 retired as audit V-12/C-11.

**Verification the repair must carry:** a full scrape (the anchors are baked into
the archive, so this cannot be measured by rebuilding an existing bundle), then
all 18 `(tier, round)` cells strictly below their 2028 equivalent with provenance
`derived_year_step`, and `scripts/board_diff.py` showing movement confined to pick
rows and the documented IDP coupling.

---

## 6. Evidence

- `exports/archive/dynasty_export_20260816_225946.zip` — last clean board
- `exports/archive/dynasty_export_20260817_021149.zip` — first affected board
- `exports/archive/dynasty_export_20260817_033535.zip` — current
- `Dynasty Scraper.py:4796` (`_nearest_year`), `:4807-4922` (`_build_site_pick_map`),
  `:4934` (`target_pick_years`), `:6164` (`_legacy_pick_anchors`), `:6196`
  (`_future_pick_years`), `:6596-6634` (the rebuild's future-year loop)
- `src/api/data_contract.py:4740` (`derive_future_tier_years_from_names`),
  `:4805` (`_inject_far_future_pick_sources`)
- `config/weights/pick_year_discount.json::derivedYearModel` — the measured step
  this board is not applying
