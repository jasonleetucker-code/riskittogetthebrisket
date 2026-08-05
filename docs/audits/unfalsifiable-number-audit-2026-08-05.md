# Unfalsifiable-number audit — findings not held by the 08-04 registry

**Date:** 2026-08-05
**Method:** find numbers that reach users where *nothing in the repository is capable of
disagreeing with them*, then give each one an adversary.
**Landed separately:** seven fixes in #725, each with a blocking guard and a mutation
that was run to prove the guard goes red.

## Why this file exists rather than a registry entry

`scripts/audit_status.py::_FINDINGS` is a **status overlay on a frozen artifact**, not an
open register. `_registry_criticals()` enumerates the Critical findings of
`decision-intelligence-audit-2026-08-04.registry.json` in order and mints `C01…C43` from
their positions; a curated entry is required for each and `rebuild()` raises if one is
missing. There is no mechanism to record a finding the frozen registry does not contain,
and `remediation-protocol.md` is explicit that the registry is "never regenerated".

So these are written down here instead. Everything below was checked against the 08-04
registry first: **four of nine sweep findings were already recorded there** (the
`model_registry.py validate` cross-snapshot comparison, the BDVM one-way sigma lane, the
Perfect Draft scarcity multiplier, and the finder's confidence baseline — all High, none
yet in a batch). Those are **not** repeated here. What follows is only what the registry
does not hold.

Measurements are against the pinned 2026-08-04 contract (1,093 `playersArray` rows) unless
stated. Counts were reproduced directly; where a number comes from a single pass and was
not independently re-derived, it says so.

---

## 1. `terminal._row_value` returns `0.0`, and both documented fallbacks are unreachable

`src/api/terminal.py:141-168` promises a three-step chain. Branch 2 reads
`values.get("full")`; branch 3 needs a rank with no value. Measured on the built snapshot
`audit/baseline/players_array.json` (1,069 rows):

```
values keys present: {overall, rawComposite, finalAdjusted, displayValue}   <- no 'full'
rows carrying values['full']:  0 / 1069
rows with rank but no value:   0 / 1069
```

`full` is minted **client-side** at `frontend/lib/dynasty-data.js:983`. This is a backend
function reading a frontend-only key. Both fallbacks are dead; everything reaches
`return 0.0`.

The 2026-07-29 scope-aware fix recorded as cutting IDP reconstruction RMSE from 826 to 79
was applied to branch 3 — which cannot execute. The comment's own justification
("dormant on live data — 0 of 740 ranked rows lack both value fields") is measured over
the wrong population: it counts only rows where branch 1 already returned.

**Effect (single pass, not re-derived):** 97 of 665 rostered players evaluate to exactly
`0.0`, almost all IDP. `src/api/trade_simulator.py:64-84` emits them as ordinary resolved
assets (`"value": 0`, `"tier": "depth"`) with `unresolvedIn`/`unresolvedOut` empty — so
nothing distinguishes "worth nothing" from "we have no price". `terminal.py:1551-1553`
already contains a comment describing this mechanism; no finding tracks it.

**Why the coercion gate misses it:** see §5.

**Fix:** delete the two dead branches, return `None` on a miss, have callers
exclude-and-count. `src/trade/finder.py` already does this correctly with
`metadata.assetsUnpricedByBoard`.

---

## 2. `/api/trade/simulate` resolves zero of a team's 288 draft picks

`src/api/trade_simulator.py:60` is a bare `row_index.get(str(name).strip().lower())` into
`terminal.py:263`'s index, which keys one name per row with **no alias handling**.

The two vocabularies never meet:

| producer | label |
|---|---|
| `src/api/sleeper_overlay.py:254-262` `_format_pick_label` | `"2027 1st"` (`_build_pick_ownership:322-330` always passes `slot=None`) |
| board rows (`data_contract.py:3912`) | `"2026 Pick 1.01"` / `"2026 Early 1st"` |

**0 of 288** owned pick labels resolve. `src/trade/team_impact.py:247` therefore computes
`pick_value` over an asset list containing no picks, so `pick_share` is structurally 0 in
the contend index.

The frontend already solves this — `frontend/lib/trade-logic.js:1184`
`resolvePickRow(rawLabel, rowLookup, pickAliases)` consults the contract's `pickAliases`
map. Python has no equivalent, and `src/api/public_activity_valuation.py:146` has a
resolver this path does not use.

**`trade_simulator.py:162-165` asserts the opposite** — "picks resolve the same way
through `row_index`" — which is what made this invisible.

**Effect (single pass):** recomputing `_classify_window` with picks restored flips **10 of
12** posture labels; six teams the panel calls "contender" are not. The same roster prices
at 90,092 in simulate and 135,917 on `/rosters` — 34% apart, two pages, one contract.

**Fix:** route `_resolve_asset` through the same `pickAliases` map. Guard: assert
`resolved == len(current_picks)` for a real team, and that simulate's `before.totalValue`
agrees with `/rosters` within tolerance.

---

## 3. FAAB recommends `$0` for every player when every rival is skipped

`src/trade/faab_engine.py:790-791`:

```python
if rival.faab_remaining is None:
    continue  # unverifiable — excluded by policy
```

With *all* rivals skipped, `rival_bid_cdf(0) = 1.0`, so `EV(b) = rawCeiling − b` is
maximised at `b = 0` and `:1047` returns 0 **by construction** — beside an objective
ceiling the same engine may price at $100 of a $100 budget.

This is reachable in production: `data/sleeper_last_good.json` carries
`faabRemaining: null` for all 12 teams whenever the live overlay fetch fails.

**It inverts a recorded Low.** The registry has *"FAAB rival contention is structurally
unreachable whenever the live Sleeper overlay fetch fails"*, but frames the consequence as
*"`max` reverts to the full league budget and the recommendation degrades to the pure
value formula"* — i.e. **bid too high**. That was true of the pre-#707 formula. The current
optimiser fails the opposite way, and `faab_engine.py` appears nowhere in the registry.

**Fix:** when no rival is priceable, the market layer has no distribution — say so
(`contention.notes` already exists for this) and fall back to the objective share rather
than reporting a $0 recommendation as if it were a bid.

---

## 4. Every board-health floor keys on `ktc`, retired from the blend

```
'ktc' registered in _RANKING_SOURCES:  False   (21 sources)
'ktcSfTep' registered:                 True

                                  ktc   ktcSfTep   registry sources w/ no floor
_DEFAULT_SOURCE_ROW_FLOORS       yes    NO          9 of 21
_DEFAULT_TOP50_COVERAGE_FLOORS   yes    NO         16 of 21
config/weights/source_row_floors.json      yes  NO  16 of 21
config/weights/top50_coverage_floors.json  yes  NO  16 of 21
```

Four separate floor sets. `ktc` is keyed in every one of them and is in **none** of the
21 registered sources; `ktcSfTep` is registered and is in **none** of the four.
`config/weights/source_row_floors.json:4` → `"ktc": 400`;
`config/weights/top50_coverage_floors.json:4` → `"ktc": 48`; same `"ktc"`-keyed defaults
inline at `src/api/data_contract.py:647` and `:775`, plus `Dynasty Scraper.py:7540`.
`config/sources/dlf_sources.template.json:33` records that `ktc` was **retired from the
blend vote on 2026-04-28** and that `ktcSfTep` is the active retail source.

`ktcSfTep` is one of two `_VALUE_BASED_SOURCES`, the
`_MARKET_ANCHOR_BY_ASSET_CLASS["offense"]`, the TE++ basis the board is anchored on, and
`finder.py`'s offense market board. It has **no floor of any kind**.

**Measured:** stripping `ktcSfTep` to 3 rows and re-running `validate_api_data_contract`
returns `ok=True, status=healthy, 0 new errors, 0 new warnings`. The same treatment of
`ktc` or `idpTradeCalc` returns `degraded` (~190–200 warnings).

`src/api/source_health_alerts.py:109-144` `resolve_threshold` handles the vendor-prefix
case correctly, so the two floor configs are the outlier, not the pattern.

No user sees a wrong number today — this is a **detection** gap. `contractHealth` is
stamped on every `/api/data` payload (`server.py:1849-1855`) and would report healthy
through an anchor collapse.

**Fix:** key the floors off `_RANKING_SOURCES` rather than a hand-maintained dict, and
invert `tests/api/test_source_floor_invariant.py:176` to iterate the registry and fail on
any source with no floor. It currently iterates `_DEFAULT_SOURCE_ROW_FLOORS.items()`, so
its headline claim is true only of a set that has drifted off the live source list.

---

## 5. Two structural blind spots in the coercion gate

`scripts/check_decision_coercions.py` + `config/coercion_baseline.json` (695 accepted
violations) is the mechanism meant to catch absent-as-zero. Two gaps explain why several
findings above survived it, and they matter more than any single finding because they are
a guard that cannot fail for a whole *shape* of defect.

**(a) Two directory trees are never scanned.** `_DECISION_ROOTS` (`:88-103`) omits
`src/draft/`, `scripts/`, `src/model_registry/`, `frontend/app/` and
`frontend/components/`. The `model_registry.py validate` finding — already in the registry
as a High — sits in a tree the gate does not look at.

**(b) Only infix forms match.** Both regexes (`:105-107`) require `or 0` / `?? 0` / `|| 0`
between two expressions:

```python
_PY_PATTERN = re.compile(r"\bor\s+(?:0\.0|0|1\.0|1|100|100\.0)\b(?!\s*[.\w])")
_JS_PATTERN = re.compile(r"(?:\|\||\?\?)\s*(?:0\.0|0|1\.0|1|100)\b(?!\s*[.\w])")
```

A **`return 0.0`** or **`return None`** fallback is invisible to both. That is exactly why
`terminal.py::_row_value` (§1) escapes while living in a file that already carries 18
baselined entries — the file is scanned, the defect shape is not.

**Deliberately not fixed here.** Widening `_DECISION_ROOTS` would surface new violations
across two trees, and `coercion_baseline.json` says in as many words: *"Each batch deletes
its findings' entries as it fixes them. Do not add to this file to make a build pass."*
Adding entries to absorb a widened scope is the batch owner's call, mid-pass, not a
drive-by. Recorded for whoever owns the next batch.

---

## Refuted — recorded so they are not re-raised

Each of these reproduced arithmetically and was dropped after measurement.

| claim | why it fails |
|---|---|
| `MIN_ACTIONABLE_VALUE = 2000` is a dead threshold | It removes **477 of 812** priced rows. It is the one actionability floor that works. |
| The corridor clamp's per-bucket band is dead code | Writing the guard refuted it — a narrower synthetic fixture yields `bandPct 0.0217, cappedByMaxBand False`. Live machinery dominated by today's wide IDP drift, not dead. |
| The live board fails `assert_ranking_coherence` (1,117 errors) | Rows were passed in payload order; the function requires rank-sorted input. Correctly sorted: **740 rows, 0 errors**. |
| `src/draft/rookie_pool.py::_row_value` sums an absent value as zero | It already abstains — returns `None`, and `select_rookie_rows:79-80` skips it. (Its `values.overall` branch *is* dead code, since `data_contract.py:9232` sets `values["overall"] = rdv`, but that is a tidiness issue, not a wrong number.) |
| `finder.py`'s `"Roster fit: fills  need."` string | The code defect is real and unfixed at `src/trade/finder.py:1097-1112`, but 0 of 1,093 rows are priced-without-a-position and no frontend reads `summary`. Not reachable. |

## Open modelling question, deliberately not resolved

The Monte Carlo band **width**. Measured against `marketDispersionCV` on 683 priced rows,
the flat ±15% is 4.8× the median implied disagreement, 1.4× at p90, and **0.4× at the
maximum** — 24 rows are genuinely under-banded. The defect is the *flatness*, not the 15,
and no backtest in this repository scores band width against realized outcomes. Recorded
as decision #4 in `docs/open-modeling-decisions.md`; picking a number without evidence
would swap one unjustified constant for another.
