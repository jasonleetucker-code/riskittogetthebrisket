# Backend → frontend API handoff

**Owner:** backend campaign (owner master implementation directive 2026-11-08, §2 and §31). This records ONLY the
backend changes the separate frontend developer needs to know about. It is not a frontend roadmap: frontend work is
theirs, and no backend change here requires editing a frontend file. Every entry is additive and versioned unless it
says otherwise.

| Endpoint | Change | Deployed | Frontend action |
|---|---|---|---|
| `GET /api/public/league/playoffOdds` | Added top-level `divisionOdds` (see below). Owner rows gain `division`, `divisionName` and `divisionChampionProbability` when division odds are available. `playoffStructure` gains `divisionRule` and `leagueRules`. | yes (#2149, production `f8da14ef8`) | Optional. The Power tab already renders a division table (added before the frontend exclusion, #2149). The redesign may restyle or move it, and should keep division-title odds and playoff odds as separate numbers. |
| `GET /api/public/league/rosPlayoffOdds`, `rosChampionship` (canonical forecast) | Rows gain `division`, `divisionName`, `divisionChampionOdds` and `divisionChampionOddsCi` when available. For a league with divisions ON and no recorded rule: `playoffOdds: []` plus `unsimulable.scope: "qualification"`, and a new `regularSeasonOdds` list (`ownerId`, `displayName`, `expectedWins`, `draftSlotDistribution`, `finalWins`, `finalPointsFor`, division fields). | yes (#2149) | Required only if the redesign shows draft slots or division titles for such a league. Read `regularSeasonOdds` when `unsimulable.scope === "qualification"`. No live league is in that state today. |
| `GET /api/draft-capital` (default league, private) | Added per-pick `rookieKtcComparableDollar` / `rookieIdpComparableDollar` (null when not comparable) and top-level `vendorComparison` (`vc_v1`: per-vendor `state`, `reason`, `listed`, `covered`, `common`, `coverageShare`, `staleObservations`, `quoteKind`, `method`). Both pick fields are redacted for public callers. Legacy `rookieKtcDollar` / `rookieIdpDollar` are UNCHANGED and still wrong for partial vendor lists (stretched over each vendor's own list, W10-F004). | no (PR pending) | Recommended: the /draft "vendor minus pre-draft" gap should read the `*ComparableDollar` fields and, when `vendorComparison.vendors.<id>.state !== "comparable"`, show the `reason` instead of a number (never $0). Label the figure "derived from the vendor's ORDER over rookies both lists cover", not a vendor quote. It is an ORDER comparison: the same order with very different magnitudes reads as a 0 gap, so never describe it as "agrees on price". `vendorComparison` is counts and labels only (no player names or values), so it is public-safe and not redacted. Vendor ids: `ktc`, `idpTradeCalc`. |
| `GET /api/draft-capital`, `GET /api/public/league/franchise` | No field changes. Anonymous `?refresh=` on draft capital is now ignored (cache is read); `franchise` reuses the memoized awards section (byte-identical). Owner-id exposure evidence and the pseudonymization design (not implemented) are in `docs/security/PUBLIC_SURFACE_CENSUS_2026-11-15.md`. | no (PR pending) | None now. If the owner approves pseudonymized owner ids, the frontend work is listed in that document §4 (private-to-public joins, raw-id displays, old-link redirects). |
| `POST /api/trade/analyze`, `POST /api/trade/analyze-multi` (private) | Added `analysis.statusQuo` (`status_quo_v1`, see below): NO TRANSACTION as a named comparator for the team's own decision. Every existing field, including `analysis.decision`, is byte-identical (the 14 War Room fixtures gained only this block). The public Trade Advisor does not carry it (`analysis` and `decision` are blocklisted there). | no (PR pending) | Optional. If shown, show `text` and the margin per component; never sum the two margins, and never present `preferred: null` as either answer. |

## `divisionOdds` contract (v1, 2026-11-08)
```json
{
  "state": "available | unavailable | not_applicable",
  "reason": "" ,
  "count": 3,
  "names": {"1": "The Pit", "2": "Sweet Pepper Bacon", "3": "Barbacoa"},
  "championRule": {
    "rule": "best_overall_record_in_division",
    "tiebreakers": ["points_for"],
    "recordBasis": "host_standings_record",
    "affectsPlayoffs": false
  }
}
```

**Unavailable reasons:**
- `division_champion_rule_unrecorded`
- `division_count_conflicts_with_host_setting`
- `roster_division_missing_or_out_of_range`
- `division_has_no_teams`
- `roster_owner_unresolved`
- `division_teams_differ_from_simulated_teams`

`not_applicable` means `no_divisions`.

**Missing is not 0:** when `state` is not `available`, rows carry no division fields. Render nothing, or the reason; never 0%.

**Display semantics:** these are simulated estimates. A simulated 0 or 1 is not a clinch until the season is final, so `frontend/lib/odds-disclosure.js::fmtSimulatedShare` renders "<1%" / ">99%".

**Suggested frontend acceptance tests:**
- a division champion that misses the playoffs shows both numbers;
- `unavailable` renders no 0%;
- `regularSeasonOdds` feeds draft-slot views when qualifying is withheld.

Synthetic fixtures: `tests/public_league/test_playoff_odds_divisions.py`, `tests/ros/test_league_division_rules.py`.

## Team equity and direction concept stamps (2026-11-08)

Backend additions (no values changed); frontend migration is not done.

- `/api/terminal` `teamAggregates` and `portfolio` now carry `valueScope: "players_only"` and `equity`: `{playerValue, pickValue, pricedPickValue, pickCount, pricedPickCount, unpricedPickCount, pickValueState (complete|partial_unpriced|unavailable), pickValueReason, totalAssetValue, totalAssetValueLowerBound}`. `totalValue` is unchanged and still excludes picks.
- **Needed:** any "Total value / portfolio total" display should show `equity.totalAssetValue`, or label `totalValue` as "Players". When `totalAssetValue` is `null`, show `totalAssetValueLowerBound` as "at least" with the reason; never render a missing pick value as 0.
- `/api/bdvm/roster` `meta.directionConcept = "fundamental_horizon_mix"` and `rosTradeDeadline.concept = "deadline_buy_sell_stance"` are NOT the canonical posture (PUSH/HOLD/RETOOL/REBUILD, `/api/gameplan`). Do not present them under the same heading.
- Schema: `docs/roster_intel/TEAM_SEMANTICS_2026-11-08.md`.

## `vendorComparison` contract (vc_v1, 2026-11-08)
Rule `intersection_budget_reallocation`: over the rookies BOTH the vendor lists (fresh, positive) and our canonical ladder prices, pair the vendor's order with OUR dollars over those same rookies. Vendor total equals our total over the common set; a vendor that orders them as we do has a gap of exactly 0; ties share the mean. States: `comparable`, `no_vendor_observations` (reason `vendor_lists_no_rookies` or `stale`), `insufficient_coverage` (common < 12 or < 50% of the pool; declared priors), `our_dollars_unavailable`, `ambiguous_identity`. Synthetic fixtures: `tests/draft/test_vendor_comparison.py`.

## Division-title ties (#2158, deployed with production after `73320356e`)

`dynasty_main`'s division-payout tiebreaker is **unconfirmed** (owner directive 2026-11-08 §26), so a record tie at the top of a division is reported as a tie and never resolved.

| Field | Where | Meaning |
|---|---|---|
| `divisionOdds.championRule.tiebreakerStatus` | `playoffOdds`, `rosPlayoffOdds` | `"unconfirmed"` (dynasty_main) or `"confirmed"` |
| `divisionTitleBasis` | rows | `"outright_only"` (tiebreaker unconfirmed) or `"tiebreaker_applied"` |
| `divisionChampionOdds` / `divisionChampionProbability` | rows | with `outright_only`: the share of seasons the team wins its division **outright** |
| `divisionTitleTieOdds` / `divisionTitleTieProbability` | rows (unconfirmed only) | the share of seasons the team **ties** for its division's best record. In a 3-way tie, all 3 teams count it. |

**Frontend action:** required, to avoid a misleading display.
- The current Power-tab division table sorts on and shows `divisionChampionProbability`, which is now outright-only.
- A team tied for the lead can show a low or 0% title chance, with no tie indicator.
- Show the tie share beside it, e.g. "Div title 41% · tied 18%".
- Never sum outright and tie shares across a 4-team division; they don't add to 100%.

**Suggested acceptance tests:**
- finished-season tie: both teams show 0% outright and 100% tied;
- unconfirmed vs confirmed rendering.

## Unpriced on-board player in trade simulate/analyze asset records (MD-105, 2026-11-08)

`POST /api/trade/simulate` and `POST /api/trade/analyze` (`sending[]` / `receiving[]`, and the before/after roster assets the simulator resolves): an on-board player the pipeline did not price now has `value: null`, `tier: null`, and `valueState: "unpriced"` (previously `value: 0`, `tier: "depth"`). A row that states a numeric zero keeps `value: 0` with no `valueState`. Priced assets are byte-identical.

- **Frontend action:** none known required. Read-only audit found no reader of these asset `value`s that breaks on null (`trade-simulation-panel.jsx` already renders null as "unpriced"; `MultiTeamWarRoom.jsx` keys on `valueState`). If any asset list renders `value`, show "unpriced" for `valueState === "unpriced"`, never 0.
- `POST /api/trade/suggestions` `metadata.pickGeneration` = `{applied: false, reason: "suggestions_have_no_pick_generator", pickInclusiveReturned: <measured count>}`. Disclosure only: no pick generator runs here, so point to the finder for pick trades. A pick already in the value pool can still appear, and is counted; do not state that suggestions never include picks.
- `POST /api/waiver/streaming` `streamingBoard` no longer lists free agents who can fill none of the league's started slots (e.g. DL/LB/DB in an offense-only league). An empty board in that league is expected: show "no started IDP slot in this league", not an error.

## Trade Monte Carlo `valueUncertainty` unavailable state (2026-11-08, owner Priority 12)

Route: `POST /api/trade/simulate-mc` (and the underlying `SimResult.to_dict()` / symmetrized payload). New additive field `valueUncertainty`; every existing field and number is unchanged.

```json
"valueUncertainty": {
  "state": "unavailable",
  "reason": "no_empirically_calibrated_band",
  "bandBasis": "assumed_flat_15pct",
  "horizonDays": null,
  "calibratedIntervals": null,
  "replayCheckOfAssumedBand": {"nominalCoverage": 0.8, "observedCoverage7d": 0.992, "observedCoverage14d": 0.976, "coverageIsUpperBound": true, "basis": "board_self_consistency_replay_2026-04-16_to_2026-11-08"},
  "evidence": "docs/valuation/TRADE_UNCERTAINTY_STUDY_2026-11-08.md"
}
```

`bandBasis` is `assumed_flat_15pct` when any asset used the synthesized band, `stamped_value_band_uncalibrated` when only stamped bands, else `unknown`. `POST /api/trade/analyze` `unavailableDimensions[]` for `valueUncertainty` now has the same `reason` (previously `unaudited_model`) and an `evidence` path.

**Frontend action (frontend developer):**
- Present the 10th/90th `deltaRange` as illustrative (assumed band), not measured; show the unavailable state from `valueUncertainty`.
- `winProbA`/`winPct` stay a simulation fraction (`labelHint`), never an acceptance probability.
- `TradeWarRoom.jsx` `DIMENSION_REASON_WORDS` has no entry for `no_empirically_calibrated_band` (falls back to a humanized key); add copy, and drop `unaudited_model` once no fixture needs it.

## `statusQuo` on trade analyses (status_quo_v1, MD-112 Part 9A, 2026-11-15)

Every Analyze body (`/api/trade/analyze`, and each `teams[].analysis` in `/api/trade/analyze-multi`) carries
`analysis.statusQuo`, beside `analysis.decision`. It states by name the comparison the decision already makes:
both decision components are measured against doing nothing (component A, the adjusted package gap net of forced
releases, is "trade minus nothing"; component B, best-ball points per week, is "after minus before"), so NO
TRANSACTION is the zero of each. No threshold, weight or utility is new. At N = 2 the record is identical on both
routes (pinned by test).

| Field | Meaning |
|---|---|
| `option` | always `"NO_TRANSACTION"` |
| `state` | `trade_beats_status_quo` / `status_quo_preferred` / `insufficient_evidence` |
| `preferred` | is declining preferred? `false` only when `decision.headline` is YES; `true` for NO and NO — TOO CLOSE; `null` when evidence is insufficient (unknown, not either answer) |
| `preferredOption` | `"TRADE"` / `"NO_TRANSACTION"` / `null` |
| `actionSupported` | `true` only for YES |
| `reason` | `clears_decision_thresholds`; `near_tie` (every evaluated component inside its band); `strategy_declines` (one component favours the trade, but the team's strategy does not count that gain as enough: NO or NO — TOO CLOSE decided by `strategy`); `decision_rule_prefers_status_quo`; `trade_not_executable` (no legal cleanup); `missing_evidence`; `decision_unrecognized` (malformed decision, e.g. a headline without a decided-path `deciding`: `preferred: null`, fails closed) |
| `text` | fixed user-facing sentence for `reason` |
| `derivedFrom` | `{headline, deciding}` of the decision it projects |
| `baseline` | `{objectiveValue: 0, rosterBenefitPpg: 0, forcedReleaseCost: 0, definition}` — what declining reads as |
| `evidence.objectiveValue` | the decision's component A (`direction`, `magnitude`, `bandLevel`, `vaAdjustedGap`, `forcedReleaseCost`, `netGap`) or `{evaluated: false, reason}` |
| `evidence.rosterBenefit` | component B (`direction`, `magnitude`, `ppg`, `neutralBandPpg`) or `{evaluated: false, state, reason}` |
| `evidence.forcedRelease` | `state` (feasibility state, `excluded_by_mode` or `unavailable`), `chargedToTrade`, `chargedToStatusQuo` (always 0: declining adds no cut; a release owed before the trade is charged to neither), `forcedDrops` (names) |
| `evidence.posture` | `strategyUsed`, `strategySource`, `postureLabel`, `windowFit`; role `selects_strategy_never_votes`; `{state: "excluded_by_mode"}` in asset-only |
| `evidence.missingEvidence` | the decision's missing-evidence codes |
| `margin.objectiveValue` / `margin.rosterBenefit` | per component, in its own units: `value`, `neutralBandHalfWidth` (fairness band: `max(250, 3.5% x larger package utility)`; roster: the lens's `neutralBandPpg`), `tradeClearance = value - halfWidth`, `statusQuoClearance = -value - halfWidth`, `direction`, `insideBand`. **`insideBand` decides** (it is the component's own classification, `direction === "neutral"`); the clearances are rounded display numbers with no signed zero, so a net a hair inside the band can show a clearance of `0.0` while `insideBand` is `true`. `null` when the component was not evaluated. |
| `margin.crossComponent` | always `null` (`crossComponentReason: "components_are_never_combined"`) |
| `opportunityCost` | `{state: "unavailable", reason: "no_owner_approved_alternative_ranking", coverageExclusionReason: "not_wired", comparedAlternatives: ["NO_TRANSACTION"], text}` |

**Frontend action:** none required. If the War Room shows it: render `text`; show the two margins separately with
their units and read inside / outside the band from `insideBand`, never from the clearance's sign; when `preferred` is `null`, say the evidence is insufficient (never "keep" or "trade"). The decision's
coverage record still reads `opportunity_cost: unavailable / not_wired` (label unchanged).

**Not done, owner decision needed (opportunity cost):** comparing a trade with the best DIFFERENT trade needs an
ordering over (package value, lineup points) pairs. The decision is a goal-keyed rule table with no scalar utility,
and the only generator of alternatives for the same team (the Trade Finder) ranks by its own arbitrage score, not by
this decision. The owner would have to choose how two YES trades are ranked (for example value-first within a
strategy, or an exchange rate between package value and best-ball ppg), and whether Analyze may run a bounded finder
search per request (latency). Until then `opportunityCost` stays unavailable.

Synthetic fixtures: `tests/trade/test_trade_status_quo.py` (hand-worked oracle), route parity in
`tests/trade/test_trade_decision_system_e2e.py`.
