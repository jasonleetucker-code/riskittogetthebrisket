# C1-U6 D1 — the board is pricing 2029 picks at their 2028 price

**Status:** REPAIRED AND DEPLOYED 2026-08-17 — see §7 and §8. Merged as
[#883](https://github.com/jasonleetucker-code/riskittogetthebrisket/pull/883)
(`a4007aec4`); Deploy Production run 32062696830 SUCCEEDED, the first success since
2026-08-17T00:35Z and the end of a 19.8-hour freeze across 12 failed runs.
**Was:** OPEN — live defect on `main`, present in every board built since
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

---

## 7. The repair, as shipped (2026-08-17)

### 7.1 What was actually wrong — one correction to §3

§3's diagnosis named three nearest-year substitution paths. There is a **fourth**,
independent of `_nearest_year` and untouched by any repair that only deletes it:

> `for y in (year, None)` — at `lookup_tier` (twice) and `lookup_slot` (once).

A vendor row whose label the parser resolved **without a year** (`"1ST EARLY"`,
`"1.06"`) landed in a `(None, round, tier)` bucket that was consulted for **every**
requested year, three of which have not happened. It is latent rather than live —
measured across 13 archives spanning 2026-07-14 to 2026-08-17, every pick-bearing
source, the un-yeared grammars match **zero** rows — which is exactly why it had to
be closed by rule rather than by inspection.

The substitution was also **unbounded in reach**, not a one-year overshoot:
`_nearest_year` had neither a distance cap nor a direction constraint, so asking
for 2031 emitted 2031 from rows published for 2028. Measured at the extracted
boundary.

### 7.2 The function had no test, and could not have one

`_build_site_pick_map` and its five helpers were closures inside a ~2,000-line
procedural function in `Dynasty Scraper.py`. There was **no test, no fixture and no
import seam** for them anywhere in the repository. That is not incidental to a
defect that survived three audits: a function nothing can call is a function
nothing can check.

They now live in `src/picks/site_pick_map.py`. `Dynasty Scraper.py` imports them
back and is an ADAPTER — the same arrangement `src/identity/name_primitives.py`
already had with that file.

**The extraction was proven behaviour-identical before anything else changed:** 36
source boards (live `exports/latest/site_raw/` + 11 sampled archives), 8,640
emitted keys, byte-identical output and byte-identical label parsing.

### 7.3 The repair

A source that did not publish the requested year contributes **MISSING**, and
missing is the key's **absence** — the representation the whole downstream chain
already handles correctly.

`_nearest_year` is **deleted, not capped**: a capped substitution is still
substitution. The un-yeared bucket now applies to the nearest requested year only.

**Kept deliberately**, because they aggregate the year's *own* observations rather
than substitute another year's: a tier answered from the same year's published
slots, and a slot spread from the same year's published tier. The latter is a
derivation and is now **stamped as one** (`derived_slot_from_tier`) instead of
being indistinguishable from a published slot.

Two adjacent repairs, both narrow and both in scope:

* **`pick_anchors_raw` is no longer overwritten** with `dict(rebuilt_pick_anchors)`.
  It promised raw vendor evidence and carried the model's own board, so no channel
  in the export distinguished an observation from a substitution. Raw now means raw,
  and `pickAnchorsProvenance` is stamped alongside it.
* **`_tier_for_slot` / `_slot_range_for_tier`** were hand-written 12-team duplicates
  of the pick-map owner's `slot_to_tier` / `slot_tier_ranges`, a few hundred lines
  below the anchors they describe. They agreed — which is why a second owner
  survives — so routing them through the owner is an exact identity at
  `league_size` 12.

### 7.4 Measured

**At the pick-map boundary**, on the real vendor rows:

| source | published years | keys | dropped | published-year values moved |
|---|---|---:|---:|---:|
| `ktc` | 2026/2027/2028 | 240 → 180 | 60 (all 2029) | **0** |
| `ktcSfTep` | 2026/2027/2028 | 240 → 180 | 60 (all 2029) | **0** |
| `idpTradeCalc` | 2026/2027/2028 | 240 → 180 | 60 (all 2029) | **96** |

Those 96 are **not collateral — they are a second instance of the same defect**.
`idpTradeCalc` publishes 2026 slots and 2026/2027/2028 tiers but no future slots,
so path 3 was serving `2027 1.01 = 8013`, which is 2026's published `1.01`
byte-for-byte. It is now 8462.4, derived from 2027's own published Early-1st tier.
Median |Δ| 11.0%, max 37.9%, every one a slot row on a year whose slots were
another year's.

**Confirmed against the live vendor**, not only the archive: KTC's page fetched
2026-08-17 publishes 36 pick rows covering **2026, 2027 and 2028 only**.

**The self-authentication loop is broken:** over the real anchors,
`derive_future_tier_years_from_names` goes `(2027, 2028, 2029)` → `(2027, 2028)`
while `_pick_model_year` stays `2026`, so `_inject_far_future_pick_sources` sees no
2029 and resumes ownership.

**All 18 `(tier, round)` cells** — the §5 verification requirement:

> **0 violations of 18.** Ratios 0.7030 – 0.9279, every cell strictly below its 2028
> equivalent, achieved **by derivation and never by an output clamp**. Rounds 1-4
> stamp `derived_year_step`; rounds 5-6 stamp `derived_round_step`. **No 2029 row
> stamps `direct_market_blend`.**

Per-source values are stepped with the model value, closing RED-4's anchor
asymmetry: `2029 Early 1st` sources go `{ktc 5188, idpTradeCalc 5034}` (2028's
numbers verbatim) → `{ktc 3703, idpTradeCalc 3593}`.

**Board blast radius** (`build_api_data_contract`, 1,110 rows, before → after):

| class | moved | p50 |Δ| | p90 | max |
|---|---:|---:|---:|---:|
| offense | 1 / 551 | 0.021% | 0.021% | 0.021% |
| IDP | 277 / 397 | 0.113% | 0.155% | **29.558%** |
| picks | 50 / 162 | 6.249% | 19.227% | 28.625% |

Ranks: 498 changed, only 20 by ≥ 5 places. Top-200 membership: `2029 Early 2nd` and
`2029 Mid 2nd` leave (they were priced as 2028 clones), `Derwin James` and
`Rueben Bain` enter. Confidence: 4 bucket changes. `structuralErrors` 0 → 0,
`sourceHealthErrors` 0 → 0.

**This is not board-inert and is not claimed to be.** The two ~29.5% IDP movers are
the documented coupling in `C1_U6_PICK_VALUE_COMPLETENESS.md` §8: re-arming the
derivation map re-enables the synthetic-rows-are-not-market-evidence backbone
filter, and IDP rank sources translate onto the IDPTC cross-market backbone, which
by design contains pick rows. Both movers were predicted before the measurement.

### 7.4a The advisory rails, measured

§3.4 recorded four safety rails firing in the advisory lane on the same nine rows.
Re-measured through the rails' own helper
(`data_contract.assert_no_unexplained_single_source`) on the repaired board:

| rank limit | before | after |
|---|---:|---:|
| top-400 (`test_no_unexplained_1src_top400`) | **9** | **0** |
| top-800 | **11** | **0** |

The mechanism is `_FAR_FUTURE_ALLOWLIST_REASON` (`data_contract.py:9229`): a row in
the per-build synthetic derivation map is allowlisted as explicitly synthetic. Under
the fabrication those rows were *not* in the map — they looked published — so they
read as unexplained single-source rows at ranks #70/#87/#98/#170/#186. 12 of the 24
2029 rows now carry the reason (the `derived_year_step` tiers); the remaining 12 are
the round-5/6 and generic-grade rows, which take a different derivation and are not
single-source rows to begin with.

### 7.5 Two boundaries, stated rather than papered over

* **No full browser scrape was run for this repair AT AUTHORING TIME — but two have
  run since, in production.** Browser egress is blocked in the authoring sandbox
  (`ERR_CONNECTION_RESET` through the agent proxy under every CA configuration
  tried), so `Dynasty Scraper.py`'s Playwright fetchers could not reach the vendors
  there; the one attempt produced a fully degraded board (`complete=0/4`) and its
  artifacts were discarded, not committed. What *was* exercised at authoring time is
  everything downstream of the fetch, on real vendor rows, plus a direct non-browser
  fetch of KTC's live page confirming the published-year set.

  **RESOLVED ON DEPLOY (2026-08-17).** Restarting the service runs a startup scrape,
  so the repaired scraper executed end to end against the live vendors on the
  production host **twice**: `20:10:21 → 20:14:02` and `20:21:56 → 20:25:29` UTC.
  Both completed cleanly — `/api/health` reports `status: ok`, `has_data: true`,
  `data_stale: false`, `scrape_stalled: false`, `data_age_hours: 0.0`. That is
  full-pipeline evidence from the real pipeline rather than a fixture.

  Still outstanding: the **repo's** `exports/latest` board. Production's scrape output
  lives on the box and is not committed back, so the tracked artifact stays pre-repair
  until the scheduled refresh runs the repaired scraper on CI and commits it — exactly
  the condition `test_the_shim_is_inert_once_the_scrape_itself_is_repaired` watches.
* **`exports/latest/dynasty_data_*.json` is git-tracked and still holds the
  pre-repair board.** The tests that detect this defect build from that artifact, so
  they were reporting a real defect that no change at their layer could fix — which
  is why they blocked Deploy Production for 17.5 hours across 12 runs. Their INPUT
  is now hardened (`tests/pick_board_fixture.py`) to the board a repaired scrape
  emits, measured from the bundle's own `site_raw/*.csv` through the canonical
  owner. **No assertion changed** and no value is edited. The shim self-retires:
  `test_the_shim_is_inert_once_the_scrape_itself_is_repaired` (livedata, advisory)
  passes once a repaired scrape lands, and then the shim is deleted.

### 7.6 A seam investigated and deliberately NOT changed

`_complete_future_pick_values` stamps `direct_market_blend` as a **pure
fallthrough** (`data_contract.py:7397`): finite value + none of the three
derivation branches claimed it ⇒ declared market-observed. It inspects no source
evidence.

Hardening it to assert real evidence was considered and rejected on measurement:
**every** `direct_market_blend` row on the real pre-repair board carries positive
`canonicalSiteValues` — including the fabricated 2029 rows, whose site values were
the cloned 2028 numbers. The check would have fired on **0 of 36** rows and, more
importantly, **would not have caught this defect**, because the fabrication enters
upstream of anything the contract can see. Adding an inert guard that cannot catch
the failure it appears to guard against would misrepresent the coverage. The
structural guarantee lives at the source-map owner instead, where the evidence is.

### 7.7 Tests

* `tests/picks/test_site_pick_map.py` — **40 tests, RED-authored**. Eight failed
  against the verbatim extraction before any behaviour changed, one per forcing
  path plus the estimate re-entry, a mid-sequence year gap, and a real-vendor-board
  sweep. Blocking lane, no live-board coupling.
* `tests/api/test_pick_completeness_red.py` — assertions untouched; input hardened;
  two new tests assert the shim is narrow and temporary.

---

## 8. The deploy unfreeze, measured

`docs/EXECUTION_PLAN.md` §0.3 records the freeze; this is its resolution.

| | before | after |
|---|---|---|
| last successful Deploy Production | `8d6930cd6`, 2026-08-17T00:35Z | **`a4007aec4`, 2026-08-17T20:22Z** |
| consecutive failures | **12** | 0 |
| `Validate Build Inputs` | failed at step 11 after **1m54s** (`-x` stopped at `test_derived_2029_value_uses_measured_year_step`) | **success** — full suite to completion in 11m55s |
| advisory livedata lane | 4 failures, all nine 2029 rows | **success** |
| FULL contract lane | passed (never the blocker) | passed |
| `Deploy To Production` | **`skipped`** (`needs: validate`) | **success** |

**Run 32062696830, attempt 1** shipped the code — `Run remote deploy script` succeeded at
20:10:45 — but its **post-deploy smoke test failed**, and the cause is worth recording because
it is a standing fragility rather than anything this unit changed:

* `/api/health` → 503, `/api/public/league` → 30s timeout; the other **25 of 27** checks passed
  (`/api/status` 200, `/api/data` 401, `/` and `/league` 200, all 21 `_next` chunks 200).
* A service restart triggers a **startup scrape**. `/api/status` puts that scrape at
  **20:10:21 → 20:14:02**; the smoke test ran **20:10:45 → 20:13:26** — entirely inside it, and
  its readiness loop spent 104 s on `/api/health` before giving up.
* For contrast, the last successful deploy's smoke test took **29 seconds** (00:55:08 →
  00:55:37) and never met a scrape.

So the smoke step is a **race the deploy design has always had**: every deploy restarts the
service, every restart scrapes, and whether the smoke test lands inside that window is timing.
The 00:55 run won it; attempt 1 lost it. Re-running the failed job after the scrape completed
gave `Post-deploy smoke test` **success in 22 s** and `Validate live data contract`
**success** — run 32062696830 attempt 2, both jobs green.

**Not fixed here, and named rather than folded in:** the readiness loop does not tolerate a
mid-scrape 503, so a future deploy can lose the same coin flip. Repairing it means changing
`.github/workflows/deploy.yml`'s wait semantics, which is a deploy-reliability change and not
a pick-valuation one. Recorded for its own unit.

**Production state after the green deploy** (probed directly, 20:26Z): `/api/health` 200
`status: ok`, `has_data: true`, `data_stale: false`, `scrape_stalled: false`,
`data_age_hours: 0.0`; `/api/status` 200; `/api/public/league` 200 in 6.6 s.
