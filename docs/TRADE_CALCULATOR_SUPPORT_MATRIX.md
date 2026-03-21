# Trade Calculator Support Matrix

Last updated: 2026-03-20

Legend:
- `trustworthy`: backend-authoritative and covered by deterministic tests.
- `partial but disclosed`: allowed with explicit diagnostics/warnings; not silently authoritative.
- `unsupported`: not trusted for production decisions.

## Asset Types
| Scenario | Status | Evidence |
| --- | --- | --- |
| Known players | trustworthy | `tests/api/test_trade_scoring_matrix.py::test_trade_scoring_matrix_fixture_cases` (`known_1_for_1_dynasty_full`) |
| Picks | trustworthy | `pick_heavy_uneven_package` fixture case |
| IDP players | trustworthy | `idp_rookie_and_manual_override` fixture case (`Beta LB`, `assetClass=idp`) |
| TE-premium-relevant assets | trustworthy | `te_premium_relevant_scoring_basis` fixture case (`Gamma TE`, scoring basis) |
| Rookies | trustworthy | `idp_rookie_and_manual_override` fixture case (`Rookie WR`) |
| Manual override rows | partial but disclosed | `fallback_manual_override` resolution in matrix case; authority diagnostics expose fallback usage |
| Unknown/unresolved assets with fallback value | partial but disclosed | `unresolved_with_fallback_value` fixture case (`fallback_unresolved`) |
| Unknown/unresolved assets without fallback value | partial but disclosed | `quarantined_and_unresolved_exclusions` fixture case (`unresolvedExcluded`) |
| Quarantined assets | partial but disclosed | `quarantined_from_final_authority` unresolved reason; excluded from totals |

## League / Scoring Contexts
| Scenario | Status | Evidence |
| --- | --- | --- |
| Dynasty full value basis | trustworthy | matrix cases with `valueBasis=full` |
| Superflex-like QB premium packages | partial but disclosed | QB-heavy package behavior is covered indirectly; `/api/trade/score` has no explicit superflex toggle in request payload |
| TE premium/scoring basis | trustworthy | `te_premium_relevant_scoring_basis` case |
| IDP-enabled scoring | trustworthy | IDP assets resolved and scored via backend bundle |
| Best-ball true | trustworthy | matrix + `test_best_ball_toggle_changes_package_totals_for_same_inputs` |
| Best-ball false | trustworthy | same toggle test and matrix cases with `bestBallMode=false` |
| Best-ball missing and assumed | partial but disclosed | e2e `trade-authority-edge.spec.js` assumption warning check |

## Trade Structures
| Scenario | Status | Evidence |
| --- | --- | --- |
| 1-for-1 | trustworthy | `known_1_for_1_dynasty_full` |
| 2-for-1 | trustworthy | `pick_heavy_uneven_package` |
| 3-way package shapes | trustworthy | `three_way_uneven_shape` |
| Pick-heavy packages | trustworthy | `pick_heavy_uneven_package` |
| Player + pick mixes | trustworthy | `three_way_uneven_shape` |
| Uneven package sizes | trustworthy | `three_way_uneven_shape`, stress test |

## Runtime Behavior
| Scenario | Status | Evidence |
| --- | --- | --- |
| Backend healthy | trustworthy | existing parity gate + edge e2e checks |
| Backend healthy + incomplete side payload | partial but disclosed | e2e edge test requires `authority=backend_trade_scoring_invalid_payload`, `backendPayloadIssueCount>0`, and totals withheld |
| Stale async responses | trustworthy | e2e `trade-authority-edge.spec.js` stale-response test |
| Backend unavailable + fallback allowed | partial but disclosed | e2e warning test requires `level=warning` and fallback diagnostics |
| Backend unavailable + fallback disallowed | partial but disclosed | e2e test confirms totals withheld + hard error warning |
| Contract/version mismatch | partial but disclosed | e2e mismatch test requires hard error + contract diagnostics |

## User-Truth Risk Controls
| Risk | Status | Evidence |
| --- | --- | --- |
| Hidden exclusions | partial but disclosed | unresolved/quarantine counters + unresolved entries in backend response |
| Unsupported scenarios masquerading as supported | partial but disclosed | fallback disallow mode blocks totals and emits error |
| Low-confidence assets | partial but disclosed | confidence metadata preserved; not used to silently override authority |
| Unresolved-position rows | partial but disclosed | quarantined rows excluded with explicit unresolved reason |
| Authority marker visibility | trustworthy | `window.__tradeCalculatorPackageDiagnostics`, `window.__tradeCalculatorAuthorityState`, `window.__tradeCalculatorTruthState`, UI warning + truth-summary banners |
