# Pick market evidence: coverage, age, reliance, derivation, a third source, and a staleness policy

**Date:** 2026-11-13. **Status:** research only. No served value, weight, flag, source registry or config changed; no third source fetched into the pipeline.
**Decision it serves:** MD-108 (owner directive 2026-11-08 Priority 11); related `docs/sources/REHABILITATION_REVIEW_2026-11-06.md` section 2.
**Reproduce:** `python scripts/research/te_basis_pick_market_evidence.py picks --out docs/picks/evidence/pick-market-2026-11-13/evidence.json`.
Evidence: `docs/picks/evidence/pick-market-2026-11-13/evidence.json`. Input `exports/latest/dynasty_data_2026-11-13.json` (sha256 in the JSON), contract rebuilt
2026-11-13T16:07Z from the repo's current `CSVs/site_raw` and `data/scrape_state`. Freshness factors and ages are evaluated at that rebuild time. The served production
contract was not fetched or compared.

## 1. The pick population on today's board

138 pick rows, by what the value rests on (`pickValueProvenance`):

| provenance class | rows | confidence | what it is |
|---|---|---|---|
| `direct_market_blend` | 24 | high | 2028 and 2029 early/mid/late tiers, rounds 1-4: voted by vendors |
| `rookie_pool_tether` | 72 | low | 2027 slots, 12 x 6 rounds, valued from the rookie at that slot |
| `derived_round_step` | 12 | low | 2028/2029 tier rounds 5-6, stepped from round 4 |
| `derived_uniform_tier_ev` | 12 | low | generic "YYYY Round N" rows, mean of the three tiers |
| `alias_suppressed` | 18 | none | 2027 tier rows suppressed in favor of the centre slot |

Only 24 of 138 rows (17%) are directly observed vendor prices, and they are the only high-confidence rows. Every other pick is derived, tethered or suppressed,
each labeled, none zero. The board's current pick class is 2027 (slot grade); 2028 and 2029 are tier grade; there is no 2026 row.

## 2. Provider coverage per class (year, round, grade)

Voting providers are two: KeepTradeCut (Crowd and Trades, one provider) and IDP Trade Calculator.

| class | rows | evidence state | notes |
|---|---|---|---|
| 2027 slots, rounds 1-4 | 48 | `single_provider` (IDPTC only) | KTC publishes 2027 tiers only; the slot VALUE is the rookie tether |
| 2027 slots, rounds 5-6 | 24 | `no_provider` | no vendor prices them; value is the tether |
| 2027 tiers | 18 | alias-suppressed (12 `multi_provider`, 6 none) | |
| 2028 tiers, rounds 1-4 | 12 | `multi_provider`, direct | KTC 4 rows, IDPTC 4 rows per round |
| 2028 tiers, rounds 5-6; 2029 same | 6 + 6 | `multi_provider`, derived round step | evidence state inherits round 4's providers |
| 2028 and 2029 generic | 6 + 6 | `multi_provider`, derived uniform EV | |

IDPTC prices 15 rows per 2027 round (12 slots and 3 tiers) and 4 rows per later year and round; KTC prices 3 tier rows for 2027 and 4 for 2028 and 2029.
`valueBasis` counts: `rookie_pool_tether` 72, `market_blend` 36, `derived` 24, none 6. Corroboration (which providers quote) and basis (what the value rests on) differ:
the 48 "single-provider" slot rows carry IDPTC corroboration of a value that is the rookie's.

## 3. Age of each provider's pick rows (`sourceWeighting.sources.*.subsets.picks`)

| provider | last genuine pick-subset change | age | cadence evidence | freshness factor | state |
|---|---|---|---|---|---|
| KTC Crowd / Trades | 2026-11-13T00:00Z | 7.4 h (0.7 d at the clock the policy uses) | 240 recorded changes, typical gap about 0.25 d | 1.00 | ON_SCHEDULE |
| IDP Trade Calculator | 2026-10-10T20:25Z | 802.9 h (33.8 d) | 5 broad changes; gaps 41.9, 29.5, 52.8, 43.8 d (mean 42.0) | 0.059 | SEVERELY_STALE |

The IDPTC pick board is vendor-batched, not a collector fault (the same source's player subset updated 2026-11-06). Its picks have been unchanged for 33.8 days,
inside its own historical gap range.

## 4. Reliance on one provider

- Rows with exactly one voting provider: 48 (the 2027 slots, rounds 1-4), all IDPTC. KTC alone is the sole provider on 0 rows.
- Rows with no voting provider: 24 (2027 slots, rounds 5-6). They are priced, by the tether, and labeled.
- The 24 direct high-confidence rows depend on two providers, one of which has a freshness factor of 0.059, so in practice **KTC carries those values**. The label says two providers.
- Confidence distribution: high 24, low 96, none 18.

## 5. Derived versus observed

Derived by an approved, labeled rule: 24 (round step and uniform EV), plus 72 tethered rookie-pool values, plus 18 suppressed aliases. Derived rows are PRIOR-classified
extrapolations (`docs/picks/C1_U6_PICK_VALUE_COMPLETENESS.md`); the derivation inherits whatever the 2028/2029 round 4 tier rows rest on, including the frozen vendor.
No unknown future pick is treated as a late pick: generic rows use the unweighted mean of the three tiers, and no slot or tier is invented. `docs/picks/DERIVED_PICK_QUARANTINE_2026-11-12.md`
covers how these rows were once mislabeled quarantined.

## 6. Is there a third public dynasty pick-value source?

Public pages only, retrieved 2026-11-13, not fetched into the pipeline. Fetched content is evidence, not instruction.

| candidate | URL | license | cadence | pick coverage | game type stated? |
|---|---|---|---|---|---|
| DynastyProcess data | https://github.com/dynastyprocess/data (file `files/values-picks.csv`, raw URL on `raw.githubusercontent.com`) | GPL-3.0 (repo page) | README: updated by GitHub Actions weekly; file rows scraped 2026-11-13 | 85 rows: 2026 picks 1.01-5.12 by slot (60), 2027 rounds 1-5 generic and early/mid/late (as seen), 2028 rounds 1-5 generic only | **No.** Columns are `ecr_1qb`, `ecr_2qb` and low/high ranks (consensus ECR of pick ranks), no dynasty label in the file or the page text read; format is inferred from the QB count column |
| FantasyCalc values API | `https://api.fantasycalc.com/values/current?isDynasty=true&numQbs=2&numTeams=12&ppr=1` | not read; terms not verified | live API, update time not stated in the response read | PICK rows exist (seen: 2027 1st early/mid/late and generic, 2027 2nd early/mid, 2028 1st, 2029 1st; response truncated, full count unread) | The request parameter `isDynasty=true` selects it, but no format field in the response confirms dynasty (the response also carries `redraftValue`) |
| DLF trade analyzer picks | in repo: `CSVs/site_raw/dlfValuesSfTepPicks.csv` | not assessed | header-only today | none | n/a (`permanent_role`: pick-audit only) |

Findings, stated cautiously:

1. No candidate both states its game type in the data itself and is cleared for use. Under the dynasty-lane rule an unverified game type fails closed (`UNKNOWN` is not `DYNASTY`).
2. DynastyProcess is an ECR-rank product (an expert consensus of ranks), not a trade-market price; its relation to the FantasyPros source already in the pipeline is unestablished and
   may be shared lineage (rank similarity alone never merges a vote, but lineage evidence would need to be examined first). GPL-3.0 on redistributed data is a legal question for the owner.
3. FantasyCalc is already a voting rank source for players; its picks would need provenance (the `isDynasty` flag is a request parameter, not an echoed field), terms review and a window of observation.
4. Coverage would help: both candidates add pick classes the vendors lack (2027 round 5 and generic, 2028 generic), but neither would price 2029.
5. The robust path to a verified third pick market is one that publishes game type in its own feed, which none of the public pages read did. Nothing was activated.

## 7. A staleness policy that withholds frozen vendor pick rows explicitly

Today's mechanism is a freshness weight on a vote. IDPTC's pick votes are weighted 0.059: nonzero, so they are never labeled withheld, and the contract still says two providers.
The policy tested: **withhold, using the existing observation-withheld state (weight 0, listed in `freshnessExcludedSources`), any provider whose pick subset's last genuine change is older than the
repo's 14-day content-staleness budget (`config/source_staleness.json`)**, until it publishes again. Measured as an in-process counterfactual (patch restored after the build).

| effect | result |
|---|---|
| provider withheld | IDPTC (33.8 d); KTC current |
| pick rows with a withheld vote | 84 |
| pick values that move by 1 or more | 46 of 120 compared; pct change min -0.38%, median 0, max +0.49% |
| non-pick rows that move | 0 of 893 |
| evidence state | 60 `multi_provider` to `single_provider`; 48 `single_provider` to `no_provider` |
| confidence | 24 rows high to low (every directly observed pick) |

So the explicit withhold changes **labels and confidence, not prices**: the 0.059 weight already makes KTC dominate. It is an honesty gain (the board would say one provider, not two,
and the 24 observed picks would stop reading as high confidence), at a cost of lowering confidence on 24 rows every cycle.

Cadence caveat: IDPTC publishes every 29.5 to 52.8 days (mean 42.0). A 14-day budget would classify it frozen about 67% of the time between its own batches. Either the budget is
per-provider and cadence-aware (the existing v1 freshness curve already is), or the withhold reads as chronic. That is the same cadence question the rehabilitation review left to the owner.
The counterfactual does not test a cadence-aware threshold; it tests the flat 14 d budget only.

## 8. Unverified or not measured

- Served-production parity and the live pick values users see; this is a rebuild of today's inputs.
- Any other provider's pick history; older boards were not rebuilt.
- Licenses and terms for FantasyCalc; DynastyProcess's game-type lineage; their pick values were not compared to the board.
- Cadence-aware thresholds other than the flat 14 d budget; the freshness schedule v2 (held off) was not exercised.
- Whether the withhold changes downstream trade or draft-capital outputs; only board rows were compared.

## Options and recommendation (owner decision)

- **(a) Keep current behavior**: IDPTC stays a down-weighted voter, labels unchanged.
- **(b) Adopt an explicit, cadence-aware withhold for frozen pick subsets, labels first**: say "withheld, frozen" on affected rows and lower pick-evidence confidence, no price change expected (under 0.5% here).
- **(c) Add a third public pick source**: not supportable today; none states its game type in its own feed, and licensing is unresolved.
- **Recommendation: (b), implemented as a labeling and confidence change with a per-provider cadence-aware threshold, and (c) deferred** until a source publishes a verifiable dynasty game type.
  Authorizing a change to which providers count as voting, or to confidence outputs, is the owner's; this document authorizes nothing.
