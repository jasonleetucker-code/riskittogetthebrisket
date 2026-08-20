# Cross-Position Source, Bridge Architecture & IDP Ceiling Audit

**Date:** 2026-08-20
**Status:** RESEARCH ONLY — no production ranking behaviour was changed.
**Code pin:** `c4431ccba3bedc2f4b511f7ca93fad03e4b6286f`
**Board pin:** `exports/latest/dynasty_data_2026-08-20.json`
(sha256 `4dcf3ed04a121288…`, 972,624 B) + 24 hashed `CSVs/site_raw/*.csv`
**Harness:** `scripts/simulate_idp_bridge_policies.py`
**Evidence:** `docs/sources/evidence/IDP_BRIDGE_2026-08-20/policy_simulation.json`

> **CORRECTION, 2026-08-20 (owner traffic-control on #950).** One verdict in
> this document is stale **in interpretation**: §15's conclusion that Dynasty
> Dealer "cannot serve as a cross-position bridge, because it publishes no IDP
> players at all." The measurement behind it reproduces and is preserved
> unchanged — both acquisition paths tried here really do return zero IDP rows
> — but the conclusion drawn from it was wrong. Dynasty Dealer exposes cardinal
> IDP values behind an undocumented parameter this audit did not try. See §15a.
> The implementation lane that carries this forward is **Claude 8 / Lane 8**.
> Bridge eligibility is now **PENDING** a same-basis and freshness
> qualification against the offensive `current_value` basis. **No production
> weighting or voting is authorized by this correction.**

Every number below was produced by rebuilding the real contract (1,109 rows,
all 21 registered sources) in-process. Nothing is quoted from prior documents
without re-verification; where a canonical document is stale, that is recorded
in §27 rather than repeated.

---

## 1. Executive Summary

**The question was: can an IDP-only source turn its rank #1 into something
approaching the overall market maximum, having no offense comparison?**

**On the live board, no.** The repository already contains a cross-position
bridge, and it works. An IDP-only source's #1 contributes **5,943** — 59.6% of
the board maximum and 92.2% of the highest IDP Trade Calculator IDP. Nothing is
near 9,999.

**Under one specific failure, yes — completely.** If `idpTradeCalc` leaves the
blend, the shared-market ladder empties, `translate_position_rank` falls back to
the untranslated rank, and IDP #1 votes as asset #1. Measured: **661 votes cast
on untranslated ranks**, 310 rows flagged, 19 IDP-only votes at or above 9,000,
and the top IDP published at **9,999 — the entire market maximum**. Aidan
Hutchinson receives 9,999 from all three IDP-only sources simultaneously.

That is the real defect, and it is a **single-source dependency**, not a
scaling-policy defect. `is_backbone` is a label; only `idpTradeCalc` can
actually seed a ladder.

**The owner's candidate ceiling does not solve it.** An IDP Trade Calculator
top-IDP ceiling changes **0 values, 0 ranks** on the live board — it is inert.
Under backbone loss it caps the peak number but leaves the board's composition
untouched: IDPs in the top 100 stay at **29** against a healthy **8**. It also
moves 12 rows *upward*, because capping a wild vote makes it survive the Hampel
outlier filter that had been discarding it.

**A bridge-derived monotonic mapping does solve it.** Candidate D restores the
board almost exactly: IDPs in the top 100 go **24 → 8**, matching the healthy
value, and the top IDP lands at 6,375 rather than 9,999. It is also nearly a
no-op when the backbone is healthy (median absolute change 3 points).

**Draft Sharks is a genuine cardinal bridge that the pipeline currently
discards.** Its offense and IDP boards come from one league-scored session
(league 995704, "Risk It To Get The Brisket") and share one `3D Value +` scale —
proven, not assumed: the rate at which projection surplus converts into
`3D Value +` is **0.09610 on offense and 0.09586 on IDP, a ratio of 0.998**,
with the spread *within* each pool larger than the difference *between* them.
Draft Sharks is therefore making a cross-position statement we already possess
and throw away by converting it to an ordinal.

**The two bridges disagree substantially, and that disagreement is real
signal.** On DL1 Aidan Hutchinson, IDPTC contributes 6,444 while Draft Sharks
contributes 2,116. On LB1 Carson Schwesinger, Draft Sharks contributes 6,485
against IDPTC's 5,667 — Draft Sharks already exceeds the proposed IDPTC ceiling
by 0.6%, which is precisely the case a naive ceiling must never touch.

**Acquisition verdicts:** Draft Sharks is already acquired and league-specific.
Dynasty Dealer needs no paid tier; the acquisition paths tried here returned
**zero IDP players**, but that was a limitation of those paths, not of the
source — see the correction in §15a, where it becomes a **PENDING** bridge
candidate. Dynasty Nerds' public IDP Top-275 is freely available but
carries ranks only, so it is a specialist, not a bridge, and Premium is not
justified. The IDP Show Combined board is paywalled and unproven from here.

---

## 2. Current Production Clamp Inventory

Every guardrail that can touch a published player value. **Recommendations
only — nothing here was changed.**

| # | Guardrail | File : symbol | Stage | Purpose | Current value | IDP-specific | Rows affected | Recommendation |
|---|---|---|---|---|---|---|---|---|
| 1 | Tail saturation | `canonical/tail_policy.py:130` `TAIL_SATURATION_RANK` | rank→percentile | Bound extrapolation past the observed rank domain | `904` | **No** (no position/scope branch) | 245 values / 402 ranks at activation; 254 rows, 233 of them DL/LB/DB *by incidence* | **KEEP.** Out of scope — see §4 |
| 2 | Percentile reference | `player_valuation.py:150` `PERCENTILE_REFERENCE_N` | rank→percentile | One coordinate universe for fit, holdout and serve | `500` | No | all rank-signal votes | KEEP |
| 3 | Curve routing refusal | `rank_coordinates.py:138` `curve_for_pool` | percentile→value | Raises rather than defaulting on an unknown pool | n/a | No | 0 (never fires) | KEEP |
| 4 | Hampel outlier filter | `data_contract.py:7767` | pre-blend | Drop contributions > K·MAD from the median | `K=2.75`, `min_n=4`, floor `1000.0` | No | varies | KEEP — but see §7, it interacts with any ceiling |
| 5 | Count-aware mean-median blend | `data_contract.py:7828` | blend | Trim one extreme per side at n≥5 | structural | No | all | KEEP |
| 6 | α-shrinkage to cross-market anchor | `data_contract.py:6087` `_ALPHA_SHRINKAGE` | blend | IDP/pick rows keep 10% of their subgroup's deviation | `0.10` | **Yes** (IDP + picks take the hierarchical path) | 383 IDP rows stamped `0.1` | **KEEP — this is already a bridge.** See §9 |
| 7 | MAD volatility penalty | `data_contract.py:6121` | post-blend | Retired | `λ = 0.0`, strict no-op | No | 0 | KEEP retired |
| 8 | Single-source haircut | `data_contract.py:6135` | post-blend | Uncorroborated rows keep 30% | `0.30` (picks exempt) | No | varies | KEEP |
| 9 | Blend-hull integrity detector | `data_contract.py:5411` | post-blend | Flags a value outside its own contributions' range; **abstains, alters nothing** | `ε = 1e-9` | No | **0 under every candidate measured** | KEEP |
| 10 | Quarantine flags | `data_contract.py:333` | validation | Row present but not consumable | 5 flags | No | 1 pre-existing | KEEP |
| 11 | Near-name collision guard | `data_contract.py:304` | identity | Entity-resolution confusion | ratio `3.0` | No | — | KEEP |
| 12 | Two-way player boost | `data_contract.py:5731` | post-blend override | Recovers IDP coverage for single-class players | `{"Travis Hunter": "DB"}` | **Yes** | 1 | KEEP |
| 13 | TE lift soft knee | `data_contract.py:6845` | TE basis | Strictly-increasing bound preserving vote distinctness | knee `9900` | No | TEs | KEEP |
| 14 | TE basis conversion refusal | `league_intel/te_premium.py:355` | TE basis | Refuses unmeasured basis pairs | base↔tepp only | No | — | KEEP |
| 15 | TEP derived multiplier clamp | `data_contract.py:6696` | TEP derivation | Bounds a misconfigured league bonus | `[1.0, 2.0]` | No | — | KEEP |
| 16 | Blanket TE multipliers | `data_contract.py:6791` | blend | Align non-KTC TEs to the TE++ baseline | `1.15` / `1.10` | No | TEs | KEEP |
| 17 | Declared-range value check (D-1) | `data_contract.py:6235` | value ingest | Drops out-of-range rows; suppresses a rescaled source | `ktcSfTep`/`idpTradeCalc` = 9999; 2% / 50 rows | No | 0 today | KEEP |
| 18 | Pick year discount | `data_contract.py:7197` | Phase 5, picks | Measured vendor year-step | per-cell `0.714`–`0.895` | No (picks only) | future picks | KEEP |
| 19 | `OVERALL_RANK_LIMIT` | `data_contract.py:127` | board cut | Publishes 800 ranks | `800` | No | tail | KEEP |
| 20 | Confidence gate | `api/confidence.py` + `config/confidence/gate_v1.json` | labelling | Five-axis bucket, weakest axis wins | 5/3 families, 0.75/0.5, 0.15 | No | all | KEEP |
| 21 | Display scale clamp | `player_valuation.py:393, :500` | curve output | Hard 1–9999 | `1` / `9999` | No | all | KEEP — but see §5, it is the mechanism that produces the 9,999 |
| 22 | Tier-gap detection | `player_valuation.py:285` | tiering | Rank-gap tier breaks | 7 / 2.0 / 3 | No | — | KEEP (not valuation) |
| 23 | Normalization validator | `canonical/normalization_validator.py` | contract check | Invariant reporting; touches no value | — | No | — | KEEP |
| 24 | Legacy calibration knees | `canonical/calibration.py` | **not on the live path** | Retired offline pipeline | IDP knee `0.80`, `idp_vet` scale `5500` | **Yes** | **0 — fenced** | **RECONSIDER for deletion.** Zero production callers for `calibrate_canonical_values`; it raises on canonical-pipeline assets and refuses picks. Only `to_display_value` is imported live (`trade/suggestions.py:26`), so removal means splitting that helper out — not a straight delete |

**No guardrail in this table is a cross-position IDP value ceiling.** Number 6
is the closest thing that exists, and it is an *anchor*, not a cap.

---

## 3. Historical Market-Corridor Status

**GONE. Confirmed absent from executable production code.**

A token-level scan of every `.py` under `src/`, `scripts/` and `server.py` —
tokenizing and discarding `COMMENT` tokens and leading-position docstrings, then
matching identifiers against surviving executable tokens — returns:

```
_apply_market_corridor_clamp:    0
_market_anchor_for_row:          0
_market_anchor_value_for_row:    0
_MARKET_ANCHOR_BY_ASSET_CLASS:   0
_MARKET_ANCHOR_FALLBACKS:        0
_MARKET_CORRIDOR (any suffix):   0
```

Seven `corridor` tokens survive in executable code and **none is the
mechanism**: the kwarg `suppress_market_corridor_clamp`
(`data_contract.py:7965`, `:9893`, `:10579`, `:10829`, and its single caller
`consensus_edge/fair_value.py:186`), which now gates only the *diagnostic stamp*
of the blend-integrity detector; plus two string literals in the offline
`scripts/measure_engine_value_divergence.py`.

The historical measurement the owner recalled is confirmed by
`docs/master-site-audit/evidence/W02/B3_MARKET_CORRIDOR_EVIDENCE.md`: 183 of 329
ranked IDP rows clamped (**55.6%**), 160 down / 23 up, `idpTradeCalc` the anchor
on **183 of 183** and also a voter in **183 of 183** of those same blends. Its
safety ordering was inverted (high-confidence rows clamped at 63.9% against
medium's 45.8%), and its stated purpose — containing the IDP calibration
post-pass — had been dead since #251 on 2026-04-23, two days after the corridor
was built.

**The IDP calibration post-pass is also fully retired**: no function, no
`config/idp_calibration.json`, no `src/idp_calibration/`, pinned absent by
`tests/api/test_valuation_pipeline_stages.py:612` and
`tests/docs/test_pipeline_trace_matches_tree.py:196`.

**Nothing in this audit recommends restoring either.**

---

## 4. The Tail Policy Is Not an IDP Value Ceiling

Stated explicitly because the two are easy to conflate and the owner asked for
the distinction to be kept.

`TAIL_SATURATION_RANK = 904` (`canonical/tail_policy.py:130`) answers **"how far
into rank space are we willing to extrapolate?"**. `max_percentile` and
`clamp_percentile` take exactly one argument, `reference_n`. There is no
position branch, no scope branch, no source branch, and no asset-class branch
anywhere in the module. It is IDP-*concentrated* only by incidence — deep ranks
are where IDP lives, so 233 of the 254 rows it touches are DL/LB/DB — and every
value-direct source contributes zero rows to it.

The question this audit asks is different: **"what is IDP1 worth against QB1?"**
That is a cross-position *value* question and the tail policy cannot answer it,
because saturating rank 904 says nothing about what rank 34 is worth.

**The tail policy was not modified and no recommendation here touches it.**

---

## 5. Current IDP-Only Scaling Behaviour

There are six IDP-bearing feeds. They reach the common 1–9999 scale by four
different routes.

| Source | Signal | Route to the common scale | Coordinate pool → curve | Family |
|---|---|---|---|---|
| `idpTradeCalc` | **value** | value-direct, `raw / site_max × 9999`, where `site_max` is the max over its own **combined offense+IDP** board | GLOBAL (fallback only) | `idpTradeCalc` |
| `draftSharksIdp` | value (exempt from `_VALUE_BASED_SOURCES` via `ds_combined_rank_partner`) | Phase 1b merges both DS CSVs into **one combined ordinal** on raw `3D Value +`, then rank→Hill | GLOBAL | `draftSharks` |
| `idpShow` | rank | shared-market crosswalk via the IDP backbone ladder, then rank→Hill | GLOBAL | `idpShow` |
| `dlfIdp` | rank | shared-market crosswalk | GLOBAL | `dlf` |
| `fantasyProsIdp` | rank | shared-market crosswalk | GLOBAL | `fantasyPros` |
| `dlfRookieIdp` | rank | rookie ladder against `idpTradeCalc`'s own ranks for *its* best IDP rookies | GLOBAL | `dlf` |

### How the crosswalk works

Sources flagged `needs_shared_market_translation` rank within the IDP class
only. `idp_backbone.build_backbone_from_rows` builds a *shared-market ladder*
whose i-th entry is the combined-pool rank of the (i+1)-th best IDP in the
backbone source. `translate_position_rank` then lifts the within-IDP ordinal
into combined rank space, the coordinate pool becomes `RANK_POOL_SHARED_MARKET`,
and the GLOBAL master prices it.

Only `idpTradeCalc` can seed that ladder, because
`build_backbone_from_rows` needs a source whose own value column spans both
pools. `draftSharksIdp` is registered `is_cross_market` but carries 0 positive
offense values under its own key (its offense half lives under `draftSharks`),
so flagging it `is_backbone` produces the identity ladder `[1,2,3,…]` — which
is exactly the fallback.

Measured on today's board: **ladder[0] = 34**. The first IDP in
`idpTradeCalc`'s combined pool sits at combined rank 34, behind 33 offensive
assets.

### A note on `fantasyProsIdp.csv`

That CSV ships a `normalizedValue` column whose rank-1 value is literally
**9999** (rank 2 = 9849). It is stored on the row as the diagnostic
`fantasyProsIdpNormalizedValue` and lands in `sourceNativeValues`. **It does not
feed the blend** — the vote travels rank → translated rank → Hill, confirmed by
the measured contribution of 5,943 rather than 9,999. The column is nonetheless
a loaded gun: a future consumer reading it as a value would reproduce the exact
defect this audit was commissioned to find. Recommend it be renamed or dropped
at the fetcher.

---

## 6. The IDP1 Problem — Explicit Answer

> **Can an IDP-only source currently turn its rank #1 into something
> approaching the overall market maximum, despite having no offense
> comparison?**

### Steady state (backbone healthy): **NO**

| Source | raw rank | effective rank | method | contribution | % of board max (9,979) | % of IDPTC ceiling (6,444) |
|---|---|---|---|---|---|---|
| `dlfIdp` | 1 | 34 | `exact` | **5,943** | 59.6% | 92.2% |
| `idpShow` | 1 | 34 | `exact` | **5,943** | 59.6% | 92.2% |
| `fantasyProsIdp` | 1 | 34 | `exact` | **5,943** | 59.6% | 92.2% |
| `draftSharksIdp` | 1 | 25 | `ds_combined_cross_market` | 6,485 | 65.0% | 100.6% |
| `dlfRookieIdp` | 1 | 69 | `rookie_ladder_translation_via_idpTradeCalc` | 4,645 | 46.5% | 72.1% |
| `idpTradeCalc` | 1 | 1 | `direct` | 9,999 | 100.2% | — (rank 1 is Bijan Robinson, an RB) |

Deeper probes for the IDP-only sources: rank 2 → 5,603 · rank 3 → 5,352 ·
rank 5 → 4,783 · rank 10 → 3,766 · rank 20 → 3,283.

Corroborating whole-board measurements:
`shared_market_crosswalk_failed(rows)` = `{}`; `idpBackboneFallback` on **0**
rows; IDP-only votes at or above 9,000 = **0**; highest published IDP value
**6,393**; IDPs in the top 50/100/200/400 = **3 / 8 / 42 / 118**.

### Backbone lost (`idpTradeCalc` excluded): **YES, completely**

| measurement | healthy | backbone lost |
|---|---|---|
| votes on untranslated ranks | 0 | **661** (`idpShow` 308, `fantasyProsIdp` 185, `dlfIdp` 168) |
| rows flagged `idpBackboneFallback` | 0 | **310** |
| IDP-only votes ≥ 9,000 | 0 | **19** |
| highest published IDP value | 6,393 | **9,999** |
| IDPs in top 50 / 100 | 3 / 8 | **13 / 29** |

Aidan Hutchinson receives a contribution of **9,999 from `dlfIdp`, `idpShow`
and `fantasyProsIdp` simultaneously**; Will Anderson receives 9,841 from two of
them. The mechanism is exact and structural: with an empty ladder
`translate_position_rank` returns the raw rank stamped `TRANSLATION_FALLBACK`,
the coordinate pool stays `RANK_POOL_IDP`, `p = 0`, and
`percentile_to_value` short-circuits to `DISPLAY_SCALE_MAX`
(`player_valuation.py:497-498`).

### Classification

This is **not** a source-domain scaling defect in the steady state — the
translation layer already does the right thing. It is a **single-point-of-
failure defect**: one source is load-bearing for the meaning of every IDP
number on the board, and its loss is not a degradation but a silent
re-denomination. The board still looks like an ordinary board.

---

## 7. IDP Trade Calculator Ceiling Test

> **Would using the current highest IDP Trade Calculator IDP value as the
> ceiling for IDP-only source contributions improve the architecture?**

# **VERDICT: BETTER ALTERNATIVE EXISTS.**

Ceiling under test: **6,444** (Aidan Hutchinson, native IDPTC). Applied at the
translation layer to the three `needs_shared_market_translation` sources only;
`idpTradeCalc`, `draftSharks` and `draftSharksIdp` exempt by construction.

### Measured effect

| scenario | values changed | ranks changed | IDP top-50 | IDP top-100 | max IDP value |
|---|---|---|---|---|---|
| live — control | — | — | 3 | 8 | 6,393 |
| live — **candidate B** | **0** | **0** | 3 | 8 | 6,393 |
| backbone lost — control | — | — | 13 | 29 | 9,999 |
| backbone lost — **candidate B** | 67 (40 IDP) | — | **13** | **29** | 6,473 |

**Three findings against it.**

1. **It is inert when the board is healthy.** Zero values, zero ranks. The
   crosswalk already places every IDP-only vote below the ceiling — the binding
   constraint would be 6,444 and the actual contribution is 5,943.
2. **It caps the number without repairing the board.** Under backbone loss it
   pulls the peak from 9,999 to 6,473, but the top-50 and top-100 IDP counts do
   not move at all (13 and 29, against a healthy 3 and 8). The board is still
   wrong; only its largest number looks right.
3. **It moves 12 rows *upward*, and the mechanism is instructive.** Micah
   Parsons goes 2,327 → 6,215; Nik Bonitto 2,422 → 6,177; Laiatu Latu 2,310 →
   5,955. Under the uncapped fallback their IDP-only votes were so extreme that
   the **Hampel filter discarded them**, leaving the rows resting on thin
   surviving evidence. Capping the votes makes them plausible, so they survive
   the filter and the rows rise. A ceiling therefore interacts with the outlier
   filter in a way that is not visible from the policy statement alone — "a
   ceiling only lowers values" is false here, measured.

### What it does get right

Applying it at the **translation layer** rather than post-consensus is correct
and must be preserved by whatever replaces it. It constrains what an IDP-only
source may *claim*, never what the consensus may *conclude*, so it cannot
recreate the retired corridor's vote-then-veto structure.

---

## 8. Bridge-Derived Ceiling Test

Candidate C derives the ceiling from all bridge families rather than one
provider. Three bridge readings exist today:

| bridge | reading | top-IDP value on the canonical scale |
|---|---|---|
| `idpTradeCalc` | native cardinal, combined board | **6,444** (Aidan Hutchinson) |
| `draftSharksIdp` | combined **ordinal** — what production derives today | **6,485** (Carson Schwesinger) |
| `draftSharksIdp` | native **cardinal** — 53/100 ratio × board max | **5,289** |

Estimators: median **6,444** · mean/trimmed mean **6,073** · min 5,289 ·
max 6,485 · **spread 19.7%**.

With the median estimator, candidate C is **numerically identical to candidate
B** on this board (6,444 either way) and therefore shares every one of B's
measured outcomes: 0 changes live, 67 changes and unchanged board composition
under backbone loss.

**C is nonetheless architecturally better than B even at an identical number**,
for a reason that does not show up in the diff: it removes the single-provider
arbiter. Under B, `idpTradeCalc` would set the bound on the very sources it
already outvotes. Under C, losing one bridge degrades the estimate instead of
destroying it — which is the exact failure this audit found.

**The 19.7% spread is the important result, not the median.** The bridges
genuinely disagree, and §11 requires that disagreement be preserved rather than
averaged into a single authority. Any ceiling collapses it to one number by
construction.

---

## 9. Full Bridge Mapping and the Hybrid

### Candidate D — monotonic bridge mapping

A specialist source says where a player sits **among IDPs**; the bridges say
what that position is **worth against offense**. D learns a monotone
within-IDP-quantile → cross-position-value map from the bridge families
(median across bridges at each of 21 knots, forced non-increasing) and replaces
the ladder translation with it.

| scenario | values changed | up / down | median abs | max abs | IDP top-50 | IDP top-100 | max IDP |
|---|---|---|---|---|---|---|---|
| live — control | — | — | — | — | 3 | 8 | 6,393 |
| live — **D** | 295 (273 IDP, 1 offense, 21 pick) | 154 / 141 | **3.0** | 1,756 | 4 | 10 | 6,441 |
| backbone lost — control | — | — | — | — | 13 | 29 | 9,999 |
| backbone lost — **D** | 350 (278 IDP, 1 offense, 71 pick) | 0 / 350 | 151.5 | 6,425 | **4** | **8** | **6,375** |

**This is the result that decides the audit.** Under backbone loss D returns the
top-100 IDP count to **8** — the healthy board's value — and the top-50 count to
4 against a healthy 3. The ceiling policies leave those at 13 and 29. D repairs
the board; a ceiling repairs one number.

D is also close to a no-op when the backbone is healthy: median absolute change
**3 points**, and its changes are symmetric (154 up, 141 down) rather than a
systematic deflation. By IDP band, live:

| band | n | changed | mean change | max abs |
|---|---|---|---|---|
| IDP 1–10 | 10 | 10 | +135.3 | 657 |
| IDP 10–25 | 15 | 15 | −3.5 | 1,756 |
| IDP 25–75 | 50 | 50 | +34.3 | 989 |
| IDP 75+ | 221 | 198 | +2.7 | 703 |

Under backbone loss the same bands show the scale of the repair: IDP 1–10 mean
**−4,602**, IDP 10–25 mean −3,048, IDP 25–75 mean −1,038, IDP 75+ mean −132 —
i.e. the correction is concentrated exactly where the fabricated cross-position
claim was largest, and is nearly absent in the deep tail.

Second-order effects are real and expected: 21 pick rows move live, 71 under
backbone loss, via the rookie-pool tether. Offense moves 1 row in both. Contract
health stays `ok: True` and **blend-integrity violations remain 0** under every
candidate and both scenarios.

### Candidate E — mapping plus bridge-derived ceiling

**E is byte-identical to D in every scenario measured.** The mapping never
produces a value above the bridge-derived ceiling, so the bound never binds.
That is a meaningful negative result: once a bridge mapping is in place, a
ceiling is redundant rather than defensive.

### The bridge that already exists

Two mechanisms already perform bridge duty and should be recognised as such
before anything new is designed:

1. **α-shrinkage** (`_ALPHA_SHRINKAGE = 0.10`). IDP and pick rows blend as
   `anchor + 0.10 × (subgroup − anchor)`, so every IDP-only board together can
   move an IDP value only 10% off the cross-market anchor.
2. **The anchor set is already multi-bridge.** Measured over 297 anchored IDP
   rows: the anchor set is `{draftSharksIdp, idpTradeCalc}` on **273** rows,
   `idpTradeCalc` alone on **23**, `draftSharksIdp` alone on **1**.

This is why the live board is healthy despite having no explicit ceiling, and
it is why a ceiling adds nothing: the containment is already there, in a better
form. What is missing is that both mechanisms depend on the *ladder*, and the
ladder depends on one source.

---

## 10. Critical Rule Check — Genuine Combined Evidence Is Not Clamped

The audit's own measurements produced a live instance of the case §11 of the
brief warns about.

**On LB1 Carson Schwesinger, `draftSharksIdp` contributes 6,485 — 100.6% of the
proposed IDPTC ceiling of 6,444.** Draft Sharks is expressing genuine
cross-position information and it lands *above* the bound. Under candidates B, C
and E it is exempt by construction, and that exemption is load-bearing rather
than cosmetic.

The bridges disagree far more than the top-of-board number suggests:

| player | pos | canonical | `idpTradeCalc` | `draftSharksIdp` | ratio |
|---|---|---|---|---|---|
| Aidan Hutchinson | DL | 6,393 | **6,444** | **2,116** | 3.05× |
| Micah Parsons | DL | 5,318 | 5,409 | 1,643 | 3.29× |
| Carson Schwesinger | LB | 5,954 | 5,667 | **6,485** | 0.87× |
| Jihaad Campbell | LB | 3,417 | 3,458 | 4,309 | 0.80× |
| Nick Emmanwori | DB | 3,550 | 3,598 | 4,671 | 0.77× |

The two bridges do not merely differ in magnitude — they disagree about **which
position family is valuable**. IDPTC prices elite DL far above elite LB; Draft
Sharks does the reverse. That is a substantive market disagreement about IDP
scoring structure, and any architecture that resolves it by appointing one
bridge as the arbiter is discarding evidence.

**Consequence for the recommendation:** the bridge layer must aggregate bridges
and publish their dispersion, never select one.

---

## 11. Source-Type Taxonomy

Mapped onto the flags the registry **already** carries, rather than inventing a
parallel vocabulary.

| Type | Definition | Existing flags | Members today | Candidates |
|---|---|---|---|---|
| **1 — native combined CARDINAL** | Values offense and IDP together on one numeric scale | `is_cross_market` + native value + `extra_scopes` spanning both pools | `idpTradeCalc` (backbone-capable); `draftSharks` + `draftSharksIdp` (**cardinal, but consumed as ordinal**) | Footballguys combined (unproven) |
| **2 — combined overall RANK** | Ranks offense and IDP together, no values | `is_cross_market`, rank signal | *none today* | IDP Show Combined |
| **3 — IDP-only numeric** | Publishes numbers, but the scale is internal to IDP | — | *none today* | — |
| **4 — IDP-only RANK (specialist)** | Orders IDPs only; cannot place them against offense | `needs_shared_market_translation`, `scope: overall_idp` | `dlfIdp`, `idpShow`, `fantasyProsIdp` | Dynasty Nerds IDP (public Top-275) |

Two gaps the current flags cannot express, and both matter:

- **`is_backbone` is a label, not a capability.** Setting it on any of the five
  other IDP sources empties the `scale_integrity_lost` guard while leaving the
  board exactly as broken. Only "the source's own value column spans both
  pools" is a real test, and only `idpTradeCalc` passes it. Measured on the
  pinned board:

  | source | positive offense values | positive IDP values | can seed a ladder |
  |---|---|---|---|
  | `idpTradeCalc` | **434** | **370** | **yes** |
  | `ktcSfTep` | 463 | 0 | no |
  | `draftSharks` | 389 | 0 | no |
  | `draftSharksIdp` | **0** | 143 | no |

  The registry should carry a *derived* capability, not a hand-set flag.
- **Nothing distinguishes cardinal from ordinal cross-position evidence.**
  `draftSharksIdp` and a future IDP Show Combined would both be
  `is_cross_market`, but one states a ratio and the other states an order. The
  first can seed a value mapping; the second can only seed a ladder.

---

## 12. Draft Sharks — Cardinal Bridge Analysis

### Acquisition status: **already acquired, and league-specific**

`scripts/fetch_draftsharks.py` drives a real browser against
`draftsharks.com/dynasty-rankings/te-premium-superflex`, selects
**`LEAGUE_ID = "995704"` ("Risk It To Get The Brisket")** through the page's
Alpine.js dropdown (`_activate_league:506`), waits for the WebAssembly scoring
worker to settle, and reads the `3D Value +` column. Draft Sharks applies league
scoring **client-side**, so the server never returns a league-scored board — the
browser drive is not an implementation preference, it is the only access path.

Offense and IDP come from **one session and one pass**, split only by the
vendor page's own `fantasyPosition` filter across QB/RB/WR/TE/DL/LB/DB. League
match is by ID with an exact normalized-name fallback (never substring, to avoid
a cloned league). The board is refreshed on the `scheduled-refresh.yml` cron
every 2 hours.

### Is `3D Value +` one scale across offense and IDP? **YES — proven**

Reading the top of each board is not sufficient evidence; a vendor could publish
two separately normalised boards of identical shape. The test uses `3yr. Proj`,
which both boards carry.

`3D Value +` behaves as value-over-replacement — each position family crosses
zero at its own projection level, which is correct VOR behaviour and *not*
evidence of separate scales. What must be shared for cross-position validity is
the **conversion rate**: one point of projection surplus must be worth the same
amount of `3D Value +` regardless of position.

Regressing `3D Value +` on `3yr. Proj` within each family:

| pos | n | slope (3D per proj point) | R² | implied replacement proj | top |
|---|---|---|---|---|---|
| QB | 51 | 0.07404 | 0.825 | 193 | Josh Allen **100** |
| RB | 115 | 0.09061 | 0.984 | 37 | Bijan Robinson 72 |
| WR | 185 | 0.09344 | 0.983 | 59 | Ja'Marr Chase 64 |
| TE | 88 | 0.12630 | 0.973 | 108 | Brock Bowers 59 |
| DL | 159 | 0.05799 | 0.862 | 219 | Aidan Hutchinson **11** |
| LB | 89 | 0.09915 | 0.987 | 247 | Carson Schwesinger **53** |
| DB | 162 | 0.13044 | 0.993 | 282 | Nick Emmanwori 36 |

**Offense slope mean 0.09610 · IDP slope mean 0.09586 · ratio 0.9976.**

The spread *within* offense (0.074 QB → 0.126 TE) and *within* IDP (0.058 DL →
0.130 DB) both exceed the difference *between* the pools. There is no systematic
offense-versus-IDP conversion gap. **The two boards are one scale.**

### What that means, and what the pipeline does with it

Draft Sharks is stating that the best IDP is worth **53% of the best offensive
player** in surplus terms. Phase 1b (`data_contract.py:8544-8597`) merges both
CSVs into a single combined **ordinal** and prices that through the Hill curve —
so the pipeline learns "DS's best IDP is the 25th-best asset" (contribution
6,485) and discards "DS's best IDP is worth 53% of DS's best QB" (which projects
to **5,289** against today's board max).

Those two readings differ by **19.7%** on the same source, in the same build.
The ordinal reading is the one that ships.

**Recommendation: preserve the cardinal reading as a second bridge input.** Not
as a replacement — the ordinal path feeds the anchor set correctly today, and DS
is one of only two anchors on 273 IDP rows. The gain is that the cardinal
reading is available to the bridge mapping without a second scrape, and it is a
genuinely independent statement of the offense↔IDP relationship.

### On the current two-key split

`draftSharks` / `draftSharksIdp` are two registry keys in **one** family, and
the split is correct for family accounting. It does **not** destroy the native
relationship — Phase 1b reunites them on the raw `3D Value +` before
ordinalizing. What loses the relationship is the ordinalization, not the split.

One player (`Justin Jefferson`) appears on both CSVs; the union is keyed on the
vendor's own `data-key`, and the repair record reports 660 overlaps with 0
conflicts.

---

## 13. The IDP Show — Verdict

**Combined board acquisition: PENDING AUTHENTICATED ACCESS.**

- **What we ingest today.** `scripts/fetch_idpshow.py` pulls the **IDP-only**
  dynasty board from `theidpshow.com/p/idp-dynasty-rankings` via Datawrapper's
  CDN (`dwcdn.net/{chart_id}/{version}/dataset.csv`, resolved by walking up to
  20 version redirects). Output is `name,position,rank` — 350 ranked players.
  Registered `scope: overall_idp`, family `idpShow` (singleton), 24h freshness
  budget, and the **only** source flagged `soft` in
  `config/source_staleness.json` because its session is hand-minted.
- **Auth.** A cookie jar at `<repo>/idpshow_session.json` (`connect.sid`,
  `AWSALBTG`, `AWSALBTGCORS`), pasted manually from DevTools, ~90-day rolling
  expiry, plus `curl_cffi` chrome131 impersonation for Cloudflare. In CI the
  same JSON is the `IDPSHOW_SESSION_JSON` secret; without it CI skips and the
  prod `dynasty-idpshow-fetch` timer is the only producer.
- **Is there a Combined board?** **No evidence in the repository, and none
  visible anonymously.** Every `combined` match in the tree is *combined
  tackles* (`src/bdvm/idpshow_projections.py:38, :74-75, :252`), a defensive
  stat split, unrelated. An anonymous fetch of the dynasty-rankings page
  returns 200 with paywall/subscriber markers present and **no Datawrapper
  chart ids exposed**. The Combined board's existence, size and shape cannot be
  established from here.
- **Lineage warning that must travel with any acquisition.** The IDP Show's
  offense component is FantasyPros ECR. A Combined board must therefore join
  the **`fantasyPros` family**, not vote as an independent source — otherwise
  the same FantasyPros opinion reaches the consensus three times
  (`fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice` are already one
  family) and the confidence gate's independence axis is inflated.
- **Its real value to this project is Type 2 cross-position placement**, not
  its offense half. If the Combined board publishes overall ranks spanning both
  pools, it becomes the **second ladder-capable source** — which is precisely
  the single-point-of-failure identified in §6.

**Future role of the existing IDP-only `idpShow` feed — recommendation:**
**retain as a specialist**, do not replace. It is a distinct family from
FantasyPros, so retiring it in favour of a FantasyPros-derived Combined board
would *reduce* independent evidence while appearing to add a source. If the
Combined board is acquired, it should be registered as a new key in the
`fantasyPros` family alongside the retained `idpShow`.

---

## 14. Draft Sharks — Verdict

**Is the Risk It To Get The Brisket-specific 3D+ board accessible? YES — it is
already being ingested.**

**Is it genuinely cross-position? YES — proven by measurement**, ratio 0.9976
(§12).

**Is the current split destroying the native relationship?** Partly. The two-key
split is fine; the **ordinalization** discards a cardinal cross-position claim
worth 19.7% against the ordinal reading.

Remaining limitation, recorded rather than resolved: the `Team` column has been
blank since 2026-07-26, and the vendor `data-key` is used for the in-memory
union but **not persisted** to the CSV, so a downstream identity join cannot use
it.

---

## 15. Dynasty Dealer — Verdict

# **DYNASTY DEALER PRO REQUIRED: NO**

But the access question is not the deciding one.

**Evidence.** Dynasty Dealer is a React SPA backed by Supabase
(`wjdntulndyhgjwfpommx.supabase.co`) with an `anon`-role JWT published in
`static/js/main.501ffcea.js`. The values live in a `players` table, queried by
the app as
`select("player_id, name, position, team, current_value, sleeper_id, age")`.
A public read of that endpoint returns HTTP 200 with no account of any kind.

Full schema: `player_id, name, team, position, current_value, sleeper_id,
mfl_id, espn_id, is_rookie, image_url, age, birthday, height, weight, college,
years_exp, updated_at, created_at, rating, votes, previous_rating`.

**Measured contents (2026-08-20):**

| metric | value |
|---|---|
| rows returned | **723** |
| positions | RB 161 · WR 264 · QB 103 · TE 126 · **PICK 69** |
| **IDP rows (DL/LB/DB/DE/DT/CB/S/EDGE)** | **0** |
| top of board | Bijan Robinson 10,000 · Jahmyr Gibbs 9,781 · Ja'Marr Chase 9,730 · Josh Allen 9,495 |
| rows carrying `sleeper_id` | 709 of 723 (98.1%) |
| freshest `updated_at` | 2026-08-20T02:08:07Z |
| rows with `current_value == 0` | **158** |

Probes for `idp_players`, `idp_values`, `rankings` and `player_values` all
return **404** — no IDP table exists.

**Verdict on usefulness** — ~~Dynasty Dealer cannot serve as a cross-position
bridge, because it publishes no IDP players at all.~~ **SUPERSEDED by §15a:
that conclusion was drawn from the acquisition paths tried above, and a third
path does publish cardinal IDP values.** The access question is
moot. It is a viable *offense + pick* source on one native 0–10,000 scale with
excellent Sleeper-ID coverage, and `rating` / `votes` / `previous_rating` show
it is a crowd-voted market (a distinct population from KTC's crowd, so plausibly
an independent family) — but that is a different proposal from the one this
audit was asked about.

Two cautions if it is ever ingested:

- **158 of 723 rows carry `current_value == 0`.** Under MISSING IS NEVER ZERO
  those must be treated as unpriced, not as zero-valued, at the fetcher.
- Attribution and terms of use were not reviewed and must be settled before any
  scheduled ingestion.


---

## 15a. Dynasty Dealer — CORRECTION (2026-08-20)

**The measurement in §15 stands. Its interpretation does not.**

§15 tried two acquisition paths and both genuinely return zero IDP rows: the
Supabase `/rest/v1/players` table (723 rows) and the default
`/api/player-values` (1,000 rows). Neither was wrong. What was wrong was
concluding from them that the *source* lacks defensive cardinal values.

The IDP data sits behind an **undocumented query parameter**, recovered from
the vendor's own JavaScript bundle:

```
GET /api/player-values?includeIdp=true&limit=5000   →  1,338 rows
WR 414 · RB 241 · TE 181 · QB 128 · DB 126 · LB 117 · DL 95 · PICK 36
```

**338 IDP rows**, carrying `current_value` on the same field as offense. The
top four match the owner-supplied figures exactly: **Myles Garrett 5,121 ·
Will Anderson 4,601 · Jack Campbell 4,599 · Aidan Hutchinson 4,584.**

The durable record is therefore:

> The previously inspected Dynasty Dealer acquisition paths returned zero IDP
> rows because they omitted `includeIdp=true`. That was an **acquisition-path
> limitation, not proof that the source lacks defensive cardinal values.**
> Bridge eligibility now depends on demonstrating that those defensive values
> share the same valuation basis as the offensive `current_value` API.

### The same-basis gate does NOT pass — two measured blockers

**(a) The format flags are echo-only.** `scoringSettings` in the response
reflects the *request*, not the data. `isSuperflex=true&isTePremium=true`
changes **0 of 1,338 values**. An adapter trusting that field would believe it
held a Superflex/TE-premium board while holding one unlabelled board — the same
class of error as W18-F001, a label deciding a factual question. Corroborating
evidence that the board is 1QB basis: QB1 Josh Allen 9,495 sits *below* RB1
Bijan Robinson 10,000. This league is Superflex + TEP.

**(b) Offense and IDP are not the same quantity in time.**

| | offense | IDP |
|---|---|---|
| distinct `updated_at` | **33**, through 2026-08-20 | **1** — all 2026-07-15 |
| rows carrying votes | 445 / 964 (46.2%) | **0 / 338 (0.0%)** |
| `base_value` vs `current_value` | diverge | identical on every row |
| range | max 10,000 · p50 16 · **min 0** | max 5,121 · p50 1,476 · min 73 |

Live, crowd-vote-adjusted offense against a static 36-day-old un-voted IDP
snapshot. The vendor's IDP page also offers tackle-heavy / balanced / big-play
variants and the payload declares none, so the scoring variant is **UNKNOWN**.

**Bridge status: `PENDING`. It does not vote.** Qualification needs the format
basis proven independently of the echoed flags, the IDP scoring variant
identified, and an owner decision on whether a static IDP snapshot may bridge
against live offense values.

### Why it is worth qualifying

Dynasty Dealer is the most consensus-central of the three candidate bridges.
Joined to 290 board IDP rows by normalized name: Spearman **IDPTC↔DD 0.773**,
against IDPTC↔DS 0.609 and DS↔DD 0.597. It sits *between* the incumbent pair on
exactly the disagreement §10 identified as the hardest:

| player | IDPTC | Draft Sharks | Dynasty Dealer |
|---|---|---|---|
| Aidan Hutchinson (DL) | 6,444 | 2,116 | **4,584** |
| Myles Garrett (DL) | 5,414 | 1,924 | **5,121** |
| Carson Schwesinger (LB) | 5,667 | 6,485 | **4,062** |

Note also `min = 0` on the offense side: under MISSING IS NEVER ZERO those rows
must be treated as unpriced at the adapter, never as zero-valued.

Full working record: `docs/sources/C8_PR_A_BRIDGE_FOUNDATION.md` §7a
(implementation lane **Claude 8 / Lane 8**, per the owner's designation of
2026-08-20).

---

## 16. Dynasty Nerds — Verdict

# **DYNASTY NERDS PREMIUM REQUIRED: NO**

**For the IDP board that exists, Premium buys nothing this project needs.**

**The offense feed we already ingest is fully public.**
`scripts/fetch_dynasty_nerds.py` reads `window.DR_DATA.SFLEXTEP` out of static
HTML at `dynastynerds.com/dynasty-rankings/sf-tep/` — no JS execution, no auth,
no paywall bypass. `DR_DATA` carries four keys (`PPR`, `SFLEX`, `STD`,
`SFLEXTEP`), **all offense**, and **no IDP key**.

**The public IDP board.** `dynastynerds.com/idp/dynasty-idp-rankings-tiers/`
returns 200 anonymously and renders the board as 10 tiered HTML tables:

| metric | value |
|---|---|
| ranked rows | **275** |
| by position | DL 100 · LB 100 · DB 75 |
| columns | Rank · Player · Position · Age · Team · 2026 IDP Rank (positional) |
| **numeric value column** | **none** |
| tiers | yes — 10 tables = 10 tiers |
| top | 1 Aidan Hutchinson (DL1) · 2 Travis Hunter (DB1) · 3 Will Anderson Jr. (DL2) · 4 Carson Schwesinger (LB1) |

**So the public IDP board is a TYPE 4 specialist**: ranks, positional ranks,
tiers and age, with no cross-position information whatsoever.

**Does Premium change that? UNPROVEN, and the burden is not met.** `app.dynasty
nerds.com` is gated and was not probed. But the decision does not turn on it:
Premium would only be worth buying if it supplied a genuine **offense↔IDP
bridge**, and nothing in the public surface suggests one exists — the public
rankings host publishes eight offense format paths and no IDP path, and the IDP
product is delivered as editorial tiers rather than as a valued board.

> **DO NOT BUY DYNASTY NERDS PREMIUM FOR THIS PURPOSE.**

**If the public IDP board is ingested**, propose it as `dynastyNerdsIdp` in the
**same `dynastyNerds` family** as the offense feed. It is **not** new
independent family evidence, and registering it as a singleton would inflate the
confidence gate's independence axis on exactly the rows that need it most.

---

## 17. Footballguys — Status

# **PENDING AUTHENTICATED ACCESS**

The prior integration (`footballGuys` / `footballGuysSf` / `footballGuysIdp`) is
**RETIRED**: no registry entry, no CSV, no fetcher, no consumer, and the
orphaned `_last_success` stamps were removed under census item S-5. It formerly
served as a cross-market combined-rank anchor alongside DraftSharks SF+IDP —
i.e. it was a **Type 1/2 bridge**, which is exactly what this audit finds the
platform short of.

**Do not revive it blindly.** Treat any future work as a fresh 2026 adapter.
Pending research slot, to be filled once authenticated access exists:

- dynasty overall board; IDP board; mixed offense/IDP expert boards
- league-specific rankings (does it support a league sync like Draft Sharks?)
- **numerical values, and whether one scale spans offense and IDP** — the
  deciding question for bridge eligibility
- delivery mechanism: export, API, or app payload
- family assignment and any derivative relationship to existing sources

**One live defect found in passing, reported not fixed:**
`frontend/app/edge/page.jsx:401` still renders user-facing copy reading
`"Consensus = DLF IDP, IDP Show, FantasyPros IDP, FootballGuys IDP, DraftSharks
IDP."` — naming a source that has not existed for roughly 85 days.
`frontend/lib/display-helpers.js:392` and
`frontend/__tests__/idp-consensus-keys-parity.test.js:18` both already document
that the name is not a key in either registry, so the comment was corrected and
the rendered string was not.

---

## 18. Provider-Family Map

### Current — 21 sources, 13 families (census `SOURCE_CENSUS_2026-08-18.md` re-verified member-for-member)

| Family | Members | Bridge? |
|---|---|---|
| `ktc` | `ktcSfTep`, `fantasyNavigatorSf` | offense anchor |
| `dlf` | `dlfSf`, `dlfRookieSf`, `dlfIdp`, `dlfRookieIdp` | no |
| `fantasyPros` | `fantasyProsSf`, `fantasyProsIdp`, `fantasyProsFitzmaurice` | no |
| `flockFantasy` | `flockFantasySf`, `flockFantasySfRookies` | no |
| `draftSharks` | `draftSharks`, `draftSharksIdp` | **YES — cardinal (consumed as ordinal)** |
| `idpTradeCalc` | `idpTradeCalc` | **YES — cardinal, and the only ladder-capable source** |
| `idpShow` | `idpShow` | no (specialist) |
| `dynastyNerdsSfTep` | `dynastyNerdsSfTep` | no |
| `fantasyCalc` | `fantasyCalc` | no |
| `otcffbSf` | `otcffbSf` | no |
| `pfkDynasty` | `pfkDynasty` | no |
| `dynastyDaddySf` | `dynastyDaddySf` | no |
| `yahooBoone` | `yahooBoone` | no |

### Proposed

| Proposed source | Family | Type | Independent family? | Gate |
|---|---|---|---|---|
| IDP Show Combined | **`fantasyPros`** (offense half is FantasyPros ECR) | 2 | **No** | authenticated access |
| `dynastyNerdsIdp` | **`dynastyNerds`** (with the existing offense feed) | 4 | **No** | none — public today |
| Dynasty Dealer | new singleton `dynastyDealer` | 1 (offense + IDP + picks) | Yes | **PENDING same-basis qualification** (§15a) |
| Footballguys 2026 | new singleton `footballguys` | 1 or 2, unproven | Yes | authenticated access |
| Draft Sharks **cardinal** reading | `draftSharks` (existing) | 1 | **No — same family** | none; reads a column we already fetch |

Only **two** of these would add independent family evidence, and only one of
those (Footballguys) could add a *bridge*.

---

## 19. Candidate Policy Comparison

All figures against the same pinned board. Contract health `ok: True` and
**0 blend-integrity violations under every candidate and both scenarios.**

### Live board (backbone healthy)

| candidate | values changed | up/down | median abs | P90 abs | max abs | IDP top-50/100/200/400 | max IDP |
|---|---|---|---|---|---|---|---|
| **A** control | — | — | — | — | — | 3 / 8 / 42 / 118 | 6,393 |
| **B** IDPTC ceiling | **0** | 0/0 | 0 | 0 | 0 | 3 / 8 / 42 / 118 | 6,393 |
| **C** bridge ceiling | **0** | 0/0 | 0 | 0 | 0 | 3 / 8 / 42 / 118 | 6,393 |
| **D** bridge mapping | 295 | 154/141 | 3.0 | — | 1,756 | 4 / 10 / 42 / 118 | 6,441 |
| **E** hybrid | 295 | 154/141 | 3.0 | — | 1,756 | 4 / 10 / 42 / 118 | 6,441 |

### Backbone lost (`idpTradeCalc` excluded)

| candidate | values changed | up/down | median abs | max abs | IDP top-50/100/200/400 | max IDP | untranslated votes |
|---|---|---|---|---|---|---|---|
| **A** control | — | — | — | — | 13 / 29 / 54 / 129 | **9,999** | **661** |
| **B** IDPTC ceiling | 67 | 12/55 | 173 | 4,225 | 13 / 29 / 54 / 129 | 6,473 | 661 |
| **C** bridge ceiling | 67 | 12/55 | 173 | 4,225 | 13 / 29 / 54 / 129 | 6,473 | 661 |
| **D** bridge mapping | 350 | **0/350** | 151.5 | 6,425 | **4 / 8 / 22 / 97** | **6,375** | 661 |
| **E** hybrid | 350 | 0/350 | 151.5 | 6,425 | 4 / 8 / 22 / 97 | 6,375 | 661 |

**Reading the table.** Healthy top-50/100 is 3/8. Backbone loss inflates it to
13/29. B and C leave it at 13/29. **D and E return it to 4/8.**

Note that D and E do not reduce the *untranslated vote count* — they do not
repair the ladder, they make the vote sane despite it. Repairing the ladder is a
separate and complementary fix (§20).

---

## 20. Cross-Position Bridge Recommendation

The architecture should separate two questions that are currently entangled in
one ladder:

> **Specialist information** answers *who is better within this domain?*
> **Bridge information** answers *what is that domain position worth against
> the overall dynasty market?*

### Recommended future architecture

1. **A named bridge layer with an explicit, multi-source population.** Bridge
   families are those that publish cross-position evidence — today
   `idpTradeCalc` (cardinal) and `draftSharks` (cardinal, currently read as
   ordinal); tomorrow potentially IDP Show Combined (ordinal) and Footballguys.
   The layer **aggregates and publishes dispersion; it never selects an
   arbiter.** The measured 19.7% bridge spread, and the 3× disagreement on
   elite DL, are the reason.

2. **`is_backbone` replaced by a derived capability.** "This source's own value
   column spans both pools" is testable and is the property that actually
   matters. A hand-set label that can be moved to a source which cannot seed a
   ladder is a guard that reports success while the board is broken.

3. **A monotone quantile→value bridge mapping replaces the ladder as the
   translation for Type 4 sources** (candidate D). It restores the board under
   backbone loss (top-100 IDP 24 → 8) and is near-inert when the backbone is
   healthy (median change 3). Crucially it degrades gracefully: losing one
   bridge changes the median at each knot rather than emptying the mechanism.

4. **No ceiling.** Candidate E proved the bound never binds once the mapping is
   in place, and candidates B and C proved a ceiling is inert when healthy and
   insufficient when not. Adding one would be a mechanism with no measured
   effect and a demonstrated interaction with the Hampel filter.

5. **Placement stays at the translation layer, never post-consensus.** This is
   the one thing the retired corridor got wrong and it must not be repeated: a
   bridge constrains what an IDP-only source may *claim*, never what the
   consensus may *conclude*. Type 1 and Type 2 sources bypass the layer
   entirely, by construction rather than by an editable exemption list.

6. **Preserve Draft Sharks' cardinal reading** as a bridge input alongside its
   existing ordinal contribution — it is a genuinely independent statement of
   the offense↔IDP relationship, already in the repository, currently discarded.

7. **Fail-closed reporting.** A row whose bridge evidence is missing or whose
   bridges disagree beyond a declared threshold should be stamped and its
   confidence degraded — not silently priced. The existing quarantine and
   confidence machinery already supports this; nothing new is needed.

### What this does NOT do

It does not stop IDPs being valuable. Under D the healthy board's top-50 IDP
count goes 3 → 4 and the top IDP rises 6,393 → 6,441. The mechanism is a
*translation*, not a deflation, and its live effect is symmetric (154 up, 141
down).

---

## 21. Representative Cross-Source Table

Live board. Slots chosen by positional rank on the canonical board (reproducible
rather than hand-picked). Figures are the **contribution that enters
aggregation** for rank-signal sources and the native value for value sources.
`—` means the source does not cover that asset.

| slot | player | pos | canonical | `ktcSfTep` | `idpTradeCalc` | `draftSharks` | `draftSharksIdp` | `idpShow` | `dlfIdp` | `fantasyProsIdp` | `dynastyNerdsSfTep` |
|---|---|---|---|---|---|---|---|---|---|---|---|
| QB1 | Josh Allen | QB | 9,979 | 9,985 | 9,983 | 9,999 | — | — | — | — | 9,999 |
| QB12 | Bo Nix | QB | 6,537 | 5,977 | 6,034 | 5,891 | — | — | — | — | 6,077 |
| QB24 | Bryce Young | QB | 3,778 | 3,809 | 4,366 | 4,050 | — | — | — | — | 3,369 |
| RB1 | Bijan Robinson | RB | 9,805 | 9,998 | 9,999 | 8,184 | — | — | — | — | 9,883 |
| RB12 | Quinshon Judkins | RB | 5,329 | 5,325 | 5,501 | 5,391 | — | — | — | — | 5,802 |
| RB24 | Bhayshul Tuten | RB | 3,859 | 4,278 | 4,032 | 3,541 | — | — | — | — | 3,809 |
| WR1 | Ja'Marr Chase | WR | 9,620 | 9,954 | 9,978 | 7,898 | — | — | — | — | 9,481 |
| WR12 | Nico Collins | WR | 6,027 | 5,653 | 5,595 | 6,052 | — | — | — | — | 5,737 |
| WR24 | Makai Lemon | WR | 4,771 | 4,939 | 5,056 | 4,754 | — | — | — | — | 4,753 |
| WR36 | Alec Pierce | WR | 3,565 | 3,676 | 4,032 | 3,706 | — | — | — | — | 3,719 |
| TE1 | Brock Bowers | TE | 9,970 | 9,999 | 9,872 | 7,940 | — | — | — | — | 9,989 |
| TE12 | Oronde Gadsden | TE | 4,086 | 3,968 | 4,511 | 4,558 | — | — | — | — | 3,935 |
| **DL1 / IDP1** | Aidan Hutchinson | DL | 6,393 | — | **6,444** | — | **2,116** | 5,943 | 5,943 | 5,943 | — |
| DL2 | Will Anderson | DL | 5,926 | — | 5,963 | — | 2,013 | 5,603 | 5,603 | 5,603 | — |
| DL5 | Myles Garrett | DL | 5,317 | — | 5,414 | — | 1,924 | 4,726 | 4,726 | 3,077 | — |
| DL10 | Nik Bonitto | DL | 3,558 | — | 3,593 | — | 1,962 | 3,231 | 3,751 | 2,826 | — |
| **LB1** | Carson Schwesinger | LB | 5,954 | — | 5,667 | — | **6,485** | 5,352 | 4,783 | 4,698 | — |
| LB2 | Sonny Styles | LB | 5,252 | — | 5,399 | — | 5,238 | 4,645 | 4,671 | 2,603 | — |
| LB5 | Arvell Reese | LB | 3,946 | — | 4,173 | — | 3,812 | 3,766 | 3,294 | 2,557 | — |
| LB10 | Jihaad Campbell | LB | 3,417 | — | 3,458 | — | 4,309 | 3,104 | 3,181 | 2,749 | — |
| **DB1** | Nick Emmanwori | DB | 3,550 | — | 3,598 | — | 4,671 | 3,262 | 3,050 | 3,104 | — |
| DB2 | Kevin Winston | DB | 3,272 | — | 2,971 | — | 3,860 | 2,585 | 1,753 | 1,892 | — |
| DB5 | Dillon Thieneman | DB | 3,129 | — | 3,111 | — | 3,383 | 2,749 | 1,950 | 1,889 | — |
| DB10 | Xavier Watts | DB | 2,046 | — | 1,970 | — | 2,163 | 1,908 | 1,585 | 2,007 | — |
| IDP5 | Micah Parsons | DL | 5,318 | — | 5,409 | — | 1,643 | 4,698 | 5,352 | 2,878 | — |
| IDP25 | Rueben Bain | DL | 3,336 | — | 3,396 | — | 1,755 | 3,050 | 2,557 | — | — |
| IDP50 | Alex Highsmith | DL | 2,477 | — | 3,264 | — | 1,660 | 2,901 | 2,742 | 1,813 | — |
| IDP100 | Jalyx Hunt | DL | 1,838 | — | 1,923 | — | 1,766 | 1,820 | 1,751 | — | — |

**Candidate-mapped contributions** are not reproduced per-player here because
candidates B and C change **nothing** on this board (§7) and D's live median
change is 3 points (§9). The full per-candidate row-level diff, including the
25 largest movers per scenario, is in the evidence JSON.

Two things the table makes visible at a glance: no IDP-only source's
contribution is anywhere near the 9,979 board maximum, and `draftSharksIdp`
disagrees with `idpTradeCalc` about DL by roughly 3× while agreeing closely
about deep DB.

---

## 22. Raw Data Preservation — Gap Analysis

Any future ingestion must preserve source-native information before
transformation. **Today it largely does not.**

`src/source_archive/store.py` exists and is well designed — append-only SQLite,
identity `(provider, endpoint, format_key, run_id, captured_date)`, native units
kept verbatim, identical re-ingest a no-op, conflicting re-ingest surfaced never
applied, fail-closed on non-`DYNASTY` game type. **It is inert**:
`archive_board` has zero production callers, `data/source_archive/` does not
exist, and `PRODUCTION_ELIGIBLE` is deliberately empty.

In practice `CSVs/site_raw/*.csv` is overwritten in place on every fetch and no
per-run version of any board survives.

| Required field | live `site_raw` | `source_archive` | `RawAssetRecord` |
|---|---|---|---|
| provider | filename only | yes | yes |
| product / feed | filename only | `format_key` | yes |
| source URL / endpoint | **missing** | yes | yes |
| fetch time | mtime + `_last_success` proxy | yes | yes |
| source update time | **missing** | `source_as_of` (unused) | **missing** |
| player source id | **missing** (DS `data-key` not persisted) | **missing** | field exists, hardcoded `""` |
| Sleeper id | 2 of 24 CSVs | **missing** | **missing** |
| name | yes | yes | yes |
| NFL team | some CSVs (DS blank since 2026-07-26) | **missing** | yes |
| position | some CSVs | **missing** | yes |
| overall rank | rank-signal CSVs | collapses to one float | yes |
| **positional rank** | **missing** | **missing** | **missing** |
| **tier** | **missing** | **missing** | field exists, never populated |
| native value | value-signal CSVs | yes (never normalized) | yes |
| scoring format | **missing** | `format_key` | yes |
| **league configuration** | **missing** (DS league is a hardcoded constant) | **missing** | free text only |
| source type | **missing** | **missing** | `ingest_type` |
| **auth class** | **missing** | **missing** | **missing** |
| provenance / hash | **missing** | `content_hash`, `run_id` | yes |
| game type | **missing** | yes (fail-closed) | **missing** |

**Structural blocker:** `ArchivedBoard.rows` is typed `dict[str, float]` — a
name→number map. It **cannot** express sleeper id, team, position, positional
rank or tier. Wiring the archive is therefore a schema extension, not a
call-site change. This matters immediately: the Dynasty Nerds IDP board's value
is entirely in its positional ranks and tiers, and the archive cannot hold
either.

**Rule to carry forward:** native values must never be overwritten with our
mapped values in raw storage. The one live violation of that spirit found in
this audit is `pickAnchorsRaw`, already repaired under C1-U6-D1.

---

## 23. Player Identity QA — Capability and Gap

For each proposed feed the brief requires ten metrics. **Seven are available
today; three are not.**

| Metric | Available | Where |
|---|---|---|
| total records | yes | `audit_sources` → `csvRows` / `parsedRows`; `record_count` |
| unique players | yes | `matchedKeys`; `master_player_count` |
| Sleeper-ID matches | yes | `idOnlyMatchedRows` |
| exact-name matches | **partial** | split exists as `v2Method` in `resolution.py` but is not surfaced per feed |
| normalized-name matches | **partial** | same |
| unresolved | yes | `unmatchedRows`; `unresolved_count` |
| ambiguous | **partial** | `v2Reason: "ambiguous"` in the dual-read tally only |
| duplicates | yes | `alias_collision_delta`; `duplicate_alias_count` |
| **team conflicts** | **NOT IMPLEMENTED** | `identity/matcher.py:70` sets `team` first-write-wins and never compares |
| position conflicts | yes | `build_master_players:84-86` |

Reusable owners: `scripts/audit_identity_matches.py::audit_sources` (per-feed
join audit, wired to a daily workflow) and
`src/identity/matcher.py::build_identity_resolution` (corpus-level).

**Team conflicts must be reported as not-implemented, never as zero.** Adding
them is a natural extension — `seen_positions` already demonstrates the pattern.

Identity readiness of the two feeds that could actually be ingested from public
surfaces today:

| feed | records | Sleeper id | notes |
|---|---|---|---|
| Dynasty Dealer `players` | 723 | **709 (98.1%)** | also `mfl_id`, `espn_id`; excellent join quality |
| Dynasty Nerds IDP Top-275 | 275 | **none** | name + team + position only; join is name-based, and 275 IDP names across DL/LB/DB is exactly the population where first-name variants bite |

---

## 24. Recommended Implementation Order

**Nothing below was implemented.** Ordered by measured value per unit of risk.

1. **Register a second ladder-capable bridge.** This is the highest-value item
   and it is not a policy change at all — it removes the single-source
   dependency that makes §6's answer "yes". Requires either the IDP Show
   Combined board or a Footballguys combined board.
2. **Replace `is_backbone` with a derived capability test.** Small, purely
   defensive, and prevents a future edit from silently satisfying the guard
   while leaving the board broken.
3. **Preserve Draft Sharks' cardinal reading** as bridge evidence. No new
   scrape — the column is already fetched. Publishes a second independent
   offense↔IDP statement.
4. **Build the bridge layer as reporting only**, publishing per-bridge top-IDP
   equivalents and their dispersion on the contract, changing no value. Lets the
   19.7% spread be monitored before anything consumes it.
5. **Adopt candidate D as the Type 4 translation**, behind a feature flag, with
   the harness re-run before and after. Only after 1–4.
6. **Do not implement a ceiling** (candidates B, C, E) — measured inert.
7. Separately and independently of the above: fix the `frontend/app/edge`
   FootballGuys string, rename or drop `fantasyProsIdp.csv::normalizedValue`,
   and correct the stale documentation in §27.

---

## 25. Exact Files a Future Implementation Would Touch

| File | Change |
|---|---|
| `src/canonical/idp_backbone.py` | the bridge mapping alongside `translate_position_rank`; ladder-capability test in `build_backbone_from_rows` |
| `src/api/data_contract.py` | `_RANKING_SOURCES` (new keys, derived capability); Phase 1 translation call site `:8467-8504`; Phase 1b DS merge `:8544-8597` for the cardinal reading; `scale_integrity_lost:2744` |
| `src/canonical/rank_coordinates.py` | only if a new coordinate pool is introduced (not expected) |
| `src/api/confidence.py` + `config/confidence/gate_v1.json` | bridge-dispersion as a confidence input, if adopted |
| `frontend/lib/dynasty-data.js` | `RANKING_SOURCES` mirror, `SOURCE_VENDORS`, `SOURCE_VENDOR_LABELS` |
| `tests/api/test_source_registry_parity.py` | parity for any new key |
| `tests/api/test_curve_routing_coordinate_pool.py`, `tests/consensus_edge/test_fair_value.py` | translation/scale-integrity invariants |
| `scripts/fetch_idpshow.py` (or a new `fetch_idpshow_combined.py`) | Combined board acquisition |
| `scripts/fetch_dynasty_nerds_idp.py` (new) | public IDP Top-275 |
| `config/source_staleness.json`, `.github/workflows/scheduled-refresh.yml`, `scripts/validate_scrape_sanity.py` | freshness + row floors for any new feed |
| `src/source_archive/store.py`, `src/data_models/contracts.py` | row schema extension (§22) |
| `src/identity/matcher.py` | team-conflict detection (§23) |
| `frontend/app/edge/page.jsx:401` | stale FootballGuys string |

---

## 26. Owner Actions Required

Only actions that cannot be performed from this session.

1. **Paste a current IDP Show session** into `idpshow_session.json` (or update
   the `IDPSHOW_SESSION_JSON` secret) **and confirm whether a Combined
   offense+IDP dynasty board exists** on the subscriber side. This is the single
   highest-value unknown in the audit — it is the likeliest second ladder-capable
   bridge.
2. **Confirm Footballguys reactivation** and supply credentials, then say
   whether its dynasty product publishes numeric values spanning offense and
   IDP.
3. **Decide on Dynasty Dealer.** It is publicly readable and needs no paid tier,
   but publishes **no IDP**. Confirm whether an offense+picks crowd source is
   wanted on its own merits — that is a different proposal from this audit's.
   Attribution / terms of use need a decision before any scheduled fetch.
4. **Confirm Dynasty Nerds Premium is not to be purchased** for this purpose,
   and whether the public IDP Top-275 should be ingested as a `dynastyNerds`
   family member.
5. **Authorize (or not) any implementation.** Nothing in §24 is authorized by
   this document; `docs/EXECUTION_PLAN.md` remains the record of what may be
   built.

---

## 27. Stale Documentation Found In Passing

Reported, not fixed.

| Location | Problem |
|---|---|
| `docs/master-site-audit/VALUE_FLOW_MAP.md:46`, `:128` | lists the market corridor clamp as live pipeline **stage 8** |
| `docs/master-site-audit/FORMULA_INVENTORY.md:144` | `F-026` market corridor clamp, status **OK** |
| `src/canonical/player_valuation.py:69`, `:440` | list "the corridor clamp" among live post-blend stages |
| `src/canonical/player_valuation.py:465-467` | `percentile_to_value` docstring says ranks past 500 clamp to `p=1.0`, contradicting the `clamp_percentile` call at `:496` |
| `src/api/compact_view.py:39` | retains contract field `marketCorridorClamp`, which nothing in `src/` writes |
| `src/api/data_contract.py:1191-1200` | registry weight-policy comment says "All six sources"; there are 21 |
| `frontend/app/edge/page.jsx:401` | user-facing copy names "FootballGuys IDP", retired ~85 days |
| `_SOURCE_MAX_AGE_HOURS` (`data_contract.py:745-800`) | `fantasyProsSf`, `dlfRookieSf`, `dlfRookieIdp` fall to the 6h default by omission while their DLF siblings carry 24h — likely unintended |

---

## 28. Proposed Follow-Up Implementation Prompt

**Not executed.** Provided for the owner to issue if and when §24 is authorized.

> **CLAUDE — SECOND BRIDGE REGISTRATION & TYPE-4 TRANSLATION HARDENING**
>
> Repo: `jasonleetucker-code/riskittogetthebrisket`.
>
> Authorized scope is items 1–4 of §24 in
> `docs/sources/CROSS_POSITION_SOURCE_AND_IDP_CEILING_AUDIT_2026-08-20.md`
> **only**. Item 5 (adopting candidate D) is **not** authorized by this prompt
> and must not be implemented.
>
> 1. Replace the `is_backbone` label with a **derived ladder capability**: a
>    source can seed a shared-market ladder iff its own value column carries
>    positive values in both the offense and IDP pools. `scale_integrity_lost`
>    and `build_backbone_from_rows` must both consult the derived test.
>    A test must fail if setting `is_backbone=True` on a source that cannot
>    seed a ladder lifts the guard.
> 2. Add the Draft Sharks **cardinal** reading as bridge evidence alongside its
>    existing ordinal contribution. Do not change any published value. Prove
>    with `scripts/board_diff.py --expect-no-value-change`.
> 3. Add a **bridge layer that reports only**: per-bridge top-IDP equivalents,
>    the aggregate estimators, and the dispersion between them, stamped on the
>    contract. It must aggregate, never select an arbiter, and must change no
>    value.
> 4. If and only if the owner has supplied IDP Show Combined or Footballguys
>    access: register it, assigning IDP Show Combined to the **`fantasyPros`**
>    family (its offense half is FantasyPros ECR), with `game_type_evidence`
>    proven per endpoint. Full registration checklist: registry entry, family,
>    frontend mirror, parity test, row floors (both), workflow cadence,
>    staleness config, identity audit.
>
> Constraints: do not implement any ceiling; do not modify
> `TAIL_SATURATION_RANK`, `_ALPHA_SHRINKAGE`, any Hill constant, or any source
> weight; do not re-thread `valuation_mode`. Re-run
> `scripts/simulate_idp_bridge_policies.py` before and after and attach the
> diff. Any change to a published value must be justified against the audit's
> pinned board and stated explicitly.

---

## 29. Success Criteria — Answers

| # | Question | Answer |
|---|---|---|
| 1 | Does any legacy IDP clamp still affect production? | **No.** The corridor and the IDP calibration post-pass are both gone; `calibration.py`'s IDP knees are fenced with zero production callers |
| 2 | Is the market-corridor clamp completely removed? | **Yes** — 0 executable references to all six identifiers |
| 3 | Which safety boundaries are unrelated to IDP cross-position valuation? | All 24 in §2. The tail policy (§4) is a rank-domain bound, not a value ceiling |
| 4 | Can IDP-only rank #1 be mapped near market maximum? | **No in steady state** (5,943 = 59.6% of max). **Yes under backbone loss** (9,999) |
| 5 | How is every IDP-only source translated? | §5 — shared-market crosswalk via a ladder seeded only by `idpTradeCalc`; rookie ladder for `dlfRookieIdp`; DS on its own combined ordinal |
| 6 | Would an IDPTC-top-IDP ceiling solve it? | **No.** 0 changes live; caps the number but not the board under backbone loss; moves 12 rows up via the Hampel interaction |
| 7 | Is a multi-bridge ceiling/mapping superior? | **The mapping is; the ceiling is not.** D returns top-100 IDP to the healthy 8; C is numerically identical to B today |
| 8 | Can genuine combined sources remain unconstrained? | **Yes, structurally** — Type 1/2 sources never enter the translation seam. Live proof: `draftSharksIdp` contributes 6,485, above the proposed ceiling |
| 9 | Can IDP Show Combined be acquired? | **Unproven** — paywalled, no repo evidence it exists. Owner action |
| 10 | Can synced Draft Sharks 3D+ be acquired? | **Already acquired**, league 995704, and proven cross-position (ratio 0.9976) |
| 11 | Are Dynasty Dealer IDP values available without Pro? | **Yes — no Pro needed.** Corrected in §15a: `?includeIdp=true` returns 338 cardinal IDP rows. Bridge status **PENDING** on two measured same-basis blockers |
| 12 | Is Dynasty Nerds Premium necessary? | **No.** Public IDP Top-275 is ranks/tiers only; Premium unproven and unjustified |
| 13 | How should specialists and bridges interact? | §20 — specialists order within domain, bridges price the domain, bridge layer aggregates and never selects |
| 14 | What is the exact implementation plan? | §24 order, §25 files, §28 prompt. **Nothing authorized by this document** |
