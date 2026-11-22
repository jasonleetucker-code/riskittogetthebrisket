# IDP evidence independence (shadow measurement) — 2026-11-22

**Status:** measurement and proposal only. Nothing here changes a vote, weight,
family, cap, registry, flag or value. Authority: owner dynasty directive
2026-11-21, intake DYN10, top-10 item #9, authorized by the 2026-11-21 section of
`docs/EXECUTION_PLAN.md`. Any change to a source weight, voting, a cap or
`_RANKING_SOURCES` stays OWNER-RESERVED.

Agent-OS-Receipt: 10446326945edabe023695675d78fa6aba382bc8

## Question

Is the IDP consensus real independent agreement, or one opinion counted several
times? The audit reported: 4 IDP voters, all on the idpTradeCalc ladder;
idpTradeCalc + IDP Show carrying 56% of IDP weight at Spearman .998; 0 of 429 IDP
rows reaching "high" confidence.

## Binding rule, and what it does to this question

`docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md` (owner directive 2026-10-19):
agreement between different providers is consensus, not duplication; **rank or
value similarity alone never merges, caps, excludes or haircuts a vote**; a
shared family or cap needs credible shared-DATA-lineage evidence (one feed
republishing another, a vendor-stated derivation, or identical raw values).

**A high Spearman is therefore not evidence for a cap.** Every correlation
below is reported as similarity. Only the items in "Lineage evidence" can count,
and none of them currently justifies one.

## Method (reproducible, read-only, no network)

Code: `src/sources/idp_independence.py` (pure functions),
`scripts/idp_evidence_independence.py` (CLI), tests
`tests/sources/test_idp_independence.py` (synthetic, hand-checked). It reads the
stamps the canonical pipeline already wrote (`sourceRankMeta.appliedWeight`,
`valueContribution`, `rawRank`, `effectiveRank`, `confidenceAxes` ...) plus the
lineage registry through `src/sources/source_census.py`. No second lineage system.

```
python scripts/idp_evidence_independence.py --board latest --cap-scenario
python scripts/idp_evidence_independence.py --board pinned --cap-scenario
```

* `latest`: `exports/latest/dynasty_data_2026-11-22.json` built against the
  committed `CSVs/site_raw` at main `191ae3cc28`. 429 IDP rows, 399 priced.
* `pinned`: the hermetic fixture `dynasty_export_20261115_095840` (426 IDP rows,
  397 priced) — the reproducible-on-any-machine cross-check.

Statistics are over priced IDP rows (`assetClass == "idp"`, `rankDerivedValue`
present). Numbers below are `latest`; `pinned` is in parentheses where it differs.

## Measured numbers

### The four voters and their families

`idpTradeCalc` (family `idpTradeCalc`), `idpShowCombined` (`idpShow`),
`fantasyProsIdp` (`fantasyPros`), `draftSharksIdp` (`draftSharks`): four B10
families, four recorded providers, no two sharing a provider. `dlfIdp` /
`dlfRookieIdp` are HELD on 180 / 31 rows (`held:owner_policy`), so they are not
voters. 

### Voting weight share (applied, from `sourceRankMeta.appliedWeight`)

| source | rows | pooled share | mean per-row share |
|---|---|---|---|
| idpTradeCalc | 377 | 29.0% | 32.8% |
| draftSharksIdp | 327 | 26.5% | 26.9% |
| idpShowCombined | 311 | 22.6% | 21.1% |
| fantasyProsIdp | 270 | 21.9% | 19.2% |

idpTradeCalc + idpShowCombined: **51.6% pooled / 54.0% per row** (the audit's 56%
is the same quantity within a few points; the pinned board gives 72% pooled
because FantasyPros and Draft Sharks are further down-weighted for staleness
there). It is a weight fact, not a lineage fact. The sources' weights are the
approved ones scaled by freshness; none is above its approved authority.

### Rank agreement — SIMILARITY ONLY

Spearman over co-covered priced IDP rows (`rawRank`; `effectiveRank` and the
pre-blend vote value give the same figures to 3 decimals):

| pair | n | Spearman |
|---|---|---|
| idpTradeCalc / idpShowCombined | 311 | **0.950** |
| idpTradeCalc / fantasyProsIdp | 262 | 0.732 |
| idpShowCombined / fantasyProsIdp | 242 | 0.724 |
| idpTradeCalc / draftSharksIdp | 307 | 0.603 |
| idpShowCombined / draftSharksIdp | 269 | 0.592 |
| draftSharksIdp / fantasyProsIdp | 251 | 0.546 |

Only one pair is near-identical. The audit's .998 is the lineage registry's
2026-10-01 figure against the non-voting IDP-only IDP Show board
(`idptc-idpshow-dependence`); against the VOTING combined board the same record
has +0.806 residual, and today's raw Spearman is 0.950. The other five pairs are
between 0.55 and 0.73, which is ordinary cross-provider disagreement, not one
opinion repeated.

### Identical raw values

0 of 311 co-covered idpTradeCalc / idpShowCombined rows carry equal canonical
values, and 0 across every other pair. **This is not evidence either way:** only
idpTradeCalc publishes a native 0-9999 value; the other three are rank-signal
sources whose canonical value is an encoding of rank, so a native-value equality
test is not defined for any IDP pair (`comparableEncoding: false` on all six).
No two IDP voters publish the same kind of number, so the "identical raw values"
route to a lineage finding is currently unavailable for IDP.

### Translation onto the idpTradeCalc ladder

Only **one** of four IDP voters is translated. The "all four on the idpTradeCalc
ladder" description is not what the stamps show:

| source | path | translated rows |
|---|---|---|
| idpTradeCalc | `value_direct`, `direct` | 0 of 377 (native) |
| idpShowCombined | `rank_hill`, `csv_combined_cross_market` (own combined pool) | 0 of 311 |
| draftSharksIdp | `rank_hill`, `ds_combined_cross_market` (own combined pool) | 0 of 327 |
| **fantasyProsIdp** | `rank_hill`, `exact`, shared-market ladder | **270 of 270** |

For fantasyProsIdp the translation is order-only (`effectiveRank` is a monotone
function of its own `rawRank` on every row, 0 descents): it contributes its ORDER
and takes its LEVEL from the ladder. The ladder is, today, **idpTradeCalc alone**:
`crossPositionBridges.ladder.contributors == ["idpTradeCalc"]`, ladder depth 377
and backbone depth 888 equal idpTradeCalc's own `idpValues` / `combinedDepth`,
and `multiBridgeLadderEnabled` is `false` (the flag `multi_bridge_ladder`,
default off). Draft Sharks is a usable second bridge but does not contribute.
At least 72% of FantasyPros' translated votes land exactly on an idpTradeCalc
board position (`ladderSetShare` 0.722, a lower bound: the ladder also holds
idpTradeCalc rows outside the priced IDP set).

So the "single IDP level anchor" concern is real in one specific place: a
FantasyPros IDP vote (about 20% of IDP weight) is priced at idpTradeCalc's level.
It is a **pipeline-structural** dependence created by our own translation, not
provider data lineage.

### What the confidence gate counts

Gate: `config/confidence/gate_v1.json`, `INDEPENDENCE_HIGH_FAMILIES = 5`, overall
confidence = weakest axis. On the 399 priced IDP rows:

* independent families per row: 1 → 40, 2 → 61, 3 → 106, **4 → 192**, 5+ → 0.
  The maximum on any IDP row is **4**, because four B10 families is every family
  that can currently vote on IDP.
* buckets: 168 low, 231 medium, **0 high**.
* independence axis: 298 medium, 101 low, 0 high. Other axes: applicability 399
  high, freshness 399 high, coverage 298 / 61 / 40 (high/med/low), agreement
  132 / 124 / 143.
* **115 rows have independence as their only sub-high axis**: they would be high
  but for the family count. 332 rows are bound by independence; 259 by agreement
  (axes can bind together).

**The "0 of 429 high" result is a population-size fact, not evidence of
duplication.** With four eligible families the independence axis cannot reach
"high" by construction. A fifth family (the held DLF IDP boards, or the
default-off Signals IDP) would be the way to change it, and both are owner-gated.
Merging idpTradeCalc and IDP Show into one family would lower the count to
three and push more rows down, not up.

## Lineage evidence vs similarity under the 2026-10-19 rule

| finding | counts as lineage evidence? |
|---|---|
| Spearman 0.950 idpTradeCalc / idpShowCombined (and 0.55-0.73 elsewhere) | **No** — similarity |
| 51.6% / 54.0% combined weight of idpTradeCalc + idpShowCombined | **No** — a weight fact |
| Registry `idptc-idpshow-dependence`: residual +0.992 vs the IDP-only board, 3 of 5 IDP Show publications followed within 1-6 h by near-identical IDPTC order | **No** — `MEASURED_DEPENDENCE`; it is about the non-voting IDP-only board and is order similarity |
| Registry `idptc-idpshow-suspected-ancestry` | **No** — `SUSPECTED`; no vendor statement |
| Identical raw values, any IDP pair | **Not testable** (no comparable encodings); 0 found |
| Same recorded provider among the four voters | **None** (four providers) |
| Any `PROVEN_COMMON_ANCESTRY` relation among the four voters | **None** (`pairLineage.countsAsLineageEvidence` false on all 6 pairs) |
| FantasyPros IDP priced on the idpTradeCalc-only ladder | **Structural, not provider lineage**: a documented consequence of our translation (order from FP, level from IDPTC). Not a basis for a cap under the rule; disclosed because it is a real coupling |

Conclusion: on the evidence the owner's rule admits, **there is no credible
shared-data lineage among the four IDP voters, so no cap is justified.** The one
near-identical pair is suspected, not proven, and is measured against a different
board than the one that votes.

## Proposal for the owner (not implemented)

**Recommended: no cap and no change.** Keep the four families as separate votes.
Optionally record, as documentation only, the fact that the shared IDP ladder is
idpTradeCalc-only and that FantasyPros IDP's level is borrowed from it.

If the owner wants to reconsider, a lineage-aware cap on idpTradeCalc +
idpShowCombined (their total held at one provider's authority) would be justified
only by one of:

1. a vendor-stated derivation (IDPTC publishing that its IDP board is built from
   IDP Show's);
2. identical raw values between the two feeds' native numbers, which needs both
   to publish comparable native IDP values (today IDP Show publishes ranks);
3. a feed shown republishing the other, established **for the voting
   `idpShowCombined` board**, not only the non-voting IDP-only board (the current
   lead-lag evidence is for the latter and covers 3 of 5 publications).

Proposed lineage RECORD, for the owner to approve — **not added**: if (1) or (3)
is obtained, add a `proven` relation (e.g. `idptc-idpshow-vendor-derivation`) on
`["idpTradeCalc", "idpShowCombined"]` to `config/sources/source_lineage.json`,
with the vendor statement or republish measurement as evidence, and promote
`pair-idptradecalc-idpshow` to `PROVEN_COMMON_ANCESTRY`. Until then it stays
`MEASURED_DEPENDENCE`.

The existing, already-owner-gated lever for the single level anchor is the
`multi_bridge_ladder` flag (off). It is a methodology change, not a cap.

### Board diff if adopted (read-only, in memory)

Via the existing override pipeline on the 2026-11-22 board
(`build_api_data_contract(..., source_overrides=...)`; the registry is untouched).
Both runs are proxies and are labelled as such.

| scenario | IDP rows moved | median / p90 / max abs change | bucket flips | consensus rank changes |
|---|---|---|---|---|
| Cap proxy: idpTradeCalc and idpShowCombined weight x0.5 | 277 of 399 | 1.39% / 10.35% / 20.95% | 28 | 319 |
| `multi_bridge_ladder` on (Draft Sharks joins the ladder), env `RISKIT_FEATURE_MULTI_BRIDGE_LADDER=1` | 260 of 399 | 0.91% / 1.90% / 14.16% | 25 | 287 |

The cap proxy is an upper bound: a real family cap scales only the amount over one
provider's authority and the applied weights are already freshness-discounted;
source overrides are also board-wide, so non-IDP rows moved too (486 of 615, median
0.32%, max 7.6%). The pinned board gives 284 IDP rows, median 2.21%, p90 9.77%,
max 16.0%, 35 flips for the cap proxy. The `multi_bridge_ladder` run moved 12
non-IDP values (max 2.3%) and 305 non-IDP rank positions through IDP interleaving.
The "not computed" cases: a true family cap (needs the cap code path, which this
unit does not touch) and any outcome-based evaluation of either change.

## Limits

* One board per run; no time-series. The lineage records' lead-lag measurements
  (2026-10-01) are the only temporal evidence and are not re-measured here.
* IDP-only IDP Show board is not a voter and is not in the stamps, so the .998
  figure cannot be reproduced from the contract. It is cited from the registry.
* Similarity numbers say nothing about whether the shared opinion is right.

## Follow-ups (not in this unit)

* Owner decision on whether to disclose the idpTradeCalc-only ladder in the
  source-voting documentation.
* Any fifth IDP family (DLF IDP restore, Signals IDP) remains owner-gated and
  would be the only way for the independence axis to reach "high".
