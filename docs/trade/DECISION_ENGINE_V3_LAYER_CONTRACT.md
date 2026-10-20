# Decision engine v3 — layer contract and model card (SHADOW challenger)

**Status:** batch 1 implemented as a pure library. **Not served.** No production
module imports it (pinned by `tests/trade/decision_engine/test_isolation.py`), so
`/api/trade/analyze` and the served decision receipts are byte-identical.
**Authority:** owner directive 2026-10-19 (evening), *League Intelligence & Trade
Decision Engine*, §10 "The mathematics of YES or NO" and §11 "Two-sided
evaluations". This record describes a challenger; it authorizes no promotion.

| | |
|---|---|
| Code | `src/trade/decision_engine/` (contracts, providers, terms, policy, confidence, reasons, engine, serialize) |
| Lineage registry | `src/evidence_lineage/registry.py` (the ONE derived-evidence registry; also read by `src/league_valuation`) |
| Parameters | `config/trade/decision_engine_v1.json` (every value a PRIOR; `paramSetId` = content hash of the RESOLVED parameters) |
| Payload schema | `tests/fixtures/decision_engine/two_sided_decision.schema.json` |
| Committed fixtures | `tests/fixtures/decision_engine/{both_gain,both_lose,insufficient,va_overlap,all_stub}.json` |
| Engine version | `decision_engine_v3_shadow` |
| Served champion | `src/trade/trade_decision.decide` (unchanged; the only producer of headline strings) |

## 1. What it answers, and what it never does

For ONE team: should this team make this trade? Output is a verdict **code**
(`YES` / `NO` / `INSUFFICIENT_EVIDENCE`), a `neutralTag`, a confidence **label**,
at most three reasons, key numbers, what would change the verdict, the missing
evidence, a double-count guard and a receipt. `evaluate_two_sided` runs the same
function once per team from that team's own layers and names the trade's shape
(`good_for_both` / `good_for_one` / `bad_for_both` / `insufficient`).

It never: emits a headline string; publishes a probability (`predictiveProbability`
is `None`, `isProbability` is `false`); defines an aggregate utility, a weight or
`P(advantage > 0)`; derives anything from a Monte-Carlo standard error except
precision; resolves a league; reads a file other than its own config and the two
numbers it borrows from `config/trade/analyze_trade.json`; writes anything;
executes anything (`executes` is always `false`, enforced in the dataclass).

## 2. Layers

Every layer carries `state` ∈ {`available`, `partial`, `stale`, `unavailable`} and
a reason. **Only `available` votes.** `partial` and `stale` are report-only for
every term; nothing missing contributes 0.

| term | lineage member | group | votes? | classification |
|---|---|---|---|---|
| A — market asset | `rank_derived_value` (VA = `package_va`, a transform) | `canonical_market` | yes | adjusted package gap READ from the packet (`vaGap`), net of the marginal forced-release charge (`roster_capacity.forced_drop_cost`), classified by `valuation_math.fairness_bands` (fair → neutral, slight → modest, unfair/lopsided → large) |
| C — current-season roster | `bestball_lineup_delta` | `league_scored_projection` | yes (default P term) | magnitude band `max(materialityPpg, zPrior × predictive_sd)`; `materialityPpg` alone while `predictive_basis` is `unavailable`. Precision gate `mc_standard_error ≤ band/2`; an *imprecise* or precision-unknown (`mc_standard_error` missing, or negative and therefore malformed) estimate is `partial` and does **not** vote (delta kept report-only) — missing evidence, never a neutral within-band vote |
| D1 — title delta | `playoff_presim` | `league_scored_projection` | only when promoted | `materialityDelta` PRIOR |
| D2 — multi-season lineup | `bestball_horizon` | `league_scored_projection` | only when promoted | `materialityPpg` PRIOR on the mean per-season delta |
| posture | `posture` | `team_strategy_context` | **never** | selects the strategy row; not a confidence axis |

`materialityPpg` and `largeMultiple` are owned by `config/trade/analyze_trade.json`
(the served roster lens) and read from there, so one number has one owner. The
band does **not** shrink with draws: more draws tighten precision but can never
turn a below-band delta into a distinguishable one (pinned by test). This is a
deliberate difference from the champion, whose band is `max(materialityPpg, 2·SE)`.

`PROMOTED_LAYER_FAMILIES` is an empty frozenset in batch 1 (pinned). A promoted,
available D1/D2 REPLACES C as the one `league_scored_projection` vote (precedence
`D1, D2, C`); precedence is earned by preregistered evidence, never availability.

## 3. Lineage rule (mechanical)

`evidence_lineage.assert_voting_terms_valid` runs on every team decision and
RAISES `LineageViolation` on: an undeclared member; a vote from a non-voting group;
two voting terms in one group. `canonical_market` and `league_scored_projection`
carry the declared partial overlap `current_season_production`: both may vote, but
their agreement caps the agreement axis at MEDIUM on every trade where both vote
and never upgrades a strategy tie-break.

Package overlap guard: VA crediting this team AND C favouring this team caps the
`overlap_guard` axis at MEDIUM (`va_roster_overlap`). Opposite directions produce
the context reason `va_structural_consolidation_premium` (an expected artifact of
the geometric VA), never evidence against the trade.

## 4. Policy table (no utility)

`policy` in the config: 3 strategies × 5 A-classes × 6 P-classes = 90 rows
(`F+`, `F`, `0`, `O`, `O+`, and `-` for "P does not vote"). Each row names a verdict
(`YES` / `NO` / `TIE`) and what decided it (`A` / `P` / `both` / `strategy` /
`none`). `TIE` → `NO` + `neutralTag` + LOW confidence with the reason
`advantage_indistinguishable_from_current_roster`.

Invariants pinned by test: the table is complete and monotone in both terms; a
single term that clears its band with the other neutral or absent is never vetoed.

Rows start from the owner's existing semantics (strategy breaks a disagreement)
and are a challenger, not copied code. Known differences from the champion's
`_rule`:

* LONG_TERM, A neutral, C favours modestly: champion NO — TOO CLOSE; challenger
  YES (a single clearing term is not vetoed).
* BALANCED, A and C opposed with equal magnitudes: champion NO; challenger NO with
  `neutralTag` (they cancel).

## 5. INSUFFICIENT_EVIDENCE

Missing items are listed by code; nothing is imputed:
`strategy_unknown`; A gated — the packet's own gate codes (`unpriced_assets`,
`off_board_assets`, `quarantined_values`, `stale_values`, `unheld_assets`,
`pick_ownership_unknown`, …), or `asset_term_<state>`; a forced-release cost that is
unknown (A does not vote: `asset_term_partial`, reason `forced_drop_cost_unknown`); `roster_term_<state>`
when P is essential (WIN_NOW, BALANCED) and does not vote — except the
not-applicable offseason reasons; `roster_unknown`; `roster_limit_unknown`
(`None` is unknown, never true).

## 6. Confidence

Weakest of: coverage, margin, agreement, asset_evidence, mc_precision,
predictive_basis (prior/proxy cap MEDIUM; unavailable caps MEDIUM for a roster-
decided verdict), freshness (unreported is MEDIUM, stale is LOW), overlap_guard.
`isProbability: false`.

## 7. Known champion biases (stamped on every receipt)

* `worsens_overage_no_release_charge` — `trade_decision._objective_value` charges the
  forced release only when `overLimitBefore == 0`; this engine reads the marginal
  `forced_drop_cost`.
* `roster_band_grows_with_standard_error` — the champion widens its band with SE.
* `agreement_counted_as_corroboration` — the champion rates market + roster
  agreement HIGH.

## 8. Evaluation and promotion

No superiority claim is possible before outcome labels exist. The batch-1 gate is
non-regression on deterministic invariants (two-sided independence, lineage
validity, no missing-as-zero, tie posture, determinism). Champion agreement over the
committed War Room fixtures is a DIAGNOSTIC (PR-2), re-baselined after train 12 and
the advisor lane, never an equality gate. The later seam adds a
`decisionEngineShadow` block only behind the integration-registered flag
`trade_decision_engine_shadow` (default OFF). At an owner-approved promotion,
`decide()` consumes the engine and deletes its own `_rule` in the same PR, so two
live rule tables never coexist.

## 9. Not in batch 1

`adapters.layers_from_analyze_packet` and the agreement diagnostic (PR-2);
provider adapters for scoring / bestball / valuation (batch 2); the
`trade_decision.py` shadow seam, `analyze_trade.py` lineage-declared lenses,
counterparty wiring through `analyze_service`, `team_impact.ageDelta` (later). Joint
contested-waiver allocation and `cost_assumption` live in the bestball provider and
reach this engine only through `TeamLineupDelta`.
