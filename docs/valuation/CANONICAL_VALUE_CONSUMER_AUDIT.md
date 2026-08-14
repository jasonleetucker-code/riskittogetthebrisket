# Canonical player value — producer / consumer audit

**As of PR #822** (canonical value uniformity). Purpose: prove the
mobile/desktop defect class is closed, not just its two known instances.

The defect had one shape — **a device-local setting selected a
non-canonical methodology, and that methodology wrote the canonical
field**. Three mechanisms had to line up. This audit checks that no
fourth path exists.

## Producers

There is exactly one.

| module | role |
|---|---|
| `src/api/data_contract.py::_compute_unified_rankings` | **THE canonical producer.** Rank → percentile → Hill, plus value-direct voting for `ktcSfTep` / `idpTradeCalc`. Emits `rankDerivedValue`. |
| `src/league_intel/overlay.py` | writes `rankDerivedValue` **only on a private scratch list** that never leaves the function, so the existing ranker can sort the experimental board. Returned rows carry canonical untouched. |

Enforced by `tests/api/test_canonical_ownership_protections.py::test_only_approved_modules_assign_the_canonical_value_field`,
which scans all shipped `.py`/`.js`/`.jsx` and fails on any other writer.

## Canonical field contract

Measured on the live 1,092-row contract:

| field | relationship | status |
|---|---|---|
| `rankDerivedValue` | the canonical value | **CANONICAL** |
| `values.overall` | exact alias, 1092/1092 | **CANONICAL** (pinned) |
| `values.finalAdjusted` | exact alias, 1092/1092 | **CANONICAL** (pinned) |
| `values.displayValue` | exact alias, 1092/1092 | **CANONICAL** (pinned) |
| `values.rawComposite` | differs on 1080/1092 | **RAW SOURCE** — legacy scraper composite, honestly named |
| `experimentalLeagueAdjustedValue` | `canonical × scarcity factor` | **EXPERIMENTAL** |

The alias equality is **intentional and now pinned**. The server overlay
used to scale `rankDerivedValue` and leave `values.*` at market —
publishing a row that disagreed with itself — which is why this is
asserted rather than assumed.

## Consumers

Every surface below takes its value from the canonical contract
(`useDynastyData` → `fetchDynastyData` → `buildRows`) or from a
server-side engine reading `latest_contract_data`. **No surface computes
or rescales a value of its own** — the no-frontend-ranking-engine rule.

| surface | source | field | was `valuationMode` reachable? | was `siteWeights` reachable? | experimental reachable? | status |
|---|---|---|---|---|---|---|
| Rankings | canonical contract → `buildRows` | `rankDerivedValue` | **yes (fixed)** | **yes (fixed)** | no | CANONICAL |
| PlayerPopup | contract row / terminal | `rankDerivedValue` | yes (fixed) | yes (fixed) | no | CANONICAL |
| Trade Calculator | canonical contract + `/api/trade/*` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Trade Suggestions | `latest_contract_data` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Finder / Arbitrage | `latest_contract_data` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Angle | `latest_contract_data` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Waivers / FAAB | `latest_contract_data` → `faab_engine` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Simulator | request body + contract | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Terminal | `/api/terminal` | `rankDerivedValue` | yes (fixed) | no | no | CANONICAL |
| Draft / Perfect Draft | `/api/draft/*` + contract | `rankDerivedValue` | no | no | no | CANONICAL |
| Public `/league` | `/api/public/league` | fantasy-points records | no | no | no | RAW SOURCE (carries no dynasty value) |
| `/api/data` compact view | same atomic swap as array | `rankDerivedValue` | n/a | n/a | no | CANONICAL |
| `/api/data` array view | same atomic swap as compact | `rankDerivedValue` | n/a | n/a | no | CANONICAL |
| exports (`exports/latest`) | scraper composite | `_finalAdjusted` | no | no | no | RAW SOURCE — legacy composite, ~1.131× canonical |
| `board_history` writer | refresh-path contract | `rank_derived_value` | no | no | no | CANONICAL |
| `rank_history` writer | refresh-path contract | `rankDerivedValue` | no | no | no | CANONICAL |
| `/api/valuation/league-adjusted` | `publish.py` | factors + experimental ranks | n/a | n/a | **yes, by design** | EXPERIMENTAL |

**Ambiguous active consumers after #822: zero.**

## Device-local settings — full sweep

All 24 keys in `next_settings_v2` were enumerated and classified. Four
could change canonical value; all four are closed.

| setting | effect on canonical value | disposition |
|---|---|---|
| `valuationMode` | selected a whole methodology | **closed** — `readValuationMode()` always answers `market` |
| `siteWeights` | recomputed the board through the canonical pipeline | **closed** at the authority (`normalize_source_overrides`) |
| `tepMultiplier` | same override path | **closed** — same gate |
| `tepNativeMultiplier` | same override path | **closed** — same gate |
| `rosSourceOverrides` | **none — no consumer anywhere** | dead setting, recorded |
| `rosTepBoost` | **none — no reference anywhere** | dead setting, recorded |
| `leagueFormat` | **none — no consumer anywhere** | dead setting, recorded |
| `faabRiskPosture` | shifts the bid TARGET, never the objective value | presentation/advice |
| `rankingsSortBasis`, `hiddenSiteCols`, `showSiteCols`, `showRosTags`, `ktcSuggestionTopN` | ordering / column visibility / filtering | presentation |
| `rosEnabled`, `useRosPowerRankings`, `useRosPlayoffOdds`, `showRosTradePanel`, `rosSimulationCount` | ROS subsystem (`rosValue`, a 0-100 log-rank index — a separately named concept) | presentation |
| `selectedTeam*`, `tradeHistoryWindowDays`, `tepAutoRestored` | scope / context | presentation |

Three dead settings (`rosSourceOverrides`, `rosTepBoost`, `leagueFormat`)
were found and are recorded rather than removed — deleting persisted keys
is a migration question, and they cannot affect value.

## Enforced invariants

| # | invariant | where |
|---|---|---|
| A | only approved producers write canonical value | `test_canonical_ownership_protections.py` |
| B | experimental overlay leaves canonical unchanged | `test_canonical_value_invariance.py` |
| C | user source weighting cannot write canonical value | `test_canonical_ownership_protections.py` |
| D | device-local settings cannot change canonical value (6-client matrix) | `test_canonical_ownership_protections.py` |
| E | canonical aliases stay coherent | `test_canonical_ownership_protections.py` |
| F | compact and array views price identically | `test_canonical_value_invariance.py` |
| G | canonical history records canonical output only | `test_canonical_ownership_protections.py` |
| H | canonical API projections preserve the value | `test_canonical_ownership_protections.py` |

## Deferred (deliberately outside #822)

- `board_history` `league_key` + scoring fingerprint columns — the
  recorder is real and healthy; this is future evidence enrichment.
- Build/revision diagnostics.
- The manual `CACHE_VERSION` service-worker hole.
- A future outcome-validated league-aware canonical methodology.
- Custom Mix reintroduction as an explicitly non-canonical analytical
  board with separate field semantics.
