# Calculator — UI Parallel Ledger

**Program:** existing Lane 6 / C8-U1, C8-U2, C8-U3.
**Contract:** `docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`.
**Source audit:** 2026-09-24 main `a3c29639aeb61c2af4fd169b75ccb9429011109b`.
**Evidence:** `docs/ui/UI_AUDIT_2026-09-24.md`.
Recheck current main, live PR files and `docs/WORK_CLAIMS.md` before dispatch.

## Status mapping and evidence limits

This is a UI dimension of Calculator Ideas, not a second backlog or denominator.
Planning remains NOW/NEXT/LATER/BLOCKED; concurrency remains SAFE_PARALLEL /
SERIAL_CANONICAL_OWNER / INTEGRATION_ONLY / DEPENDENCY_BLOCKED. Preserve existing
FEATURE_GREEN / READY_FOR_INTEGRATION / INTEGRATION_GREEN evidence standards.
Owner migration labels may refine this dimension: NOT_AUDITED, AUDITED,
FOUNDATION_READY, CONTRACT_BLOCKED, READY_TO_MIGRATE, MIGRATING, FEATURE_GREEN,
DEPLOYED, PSI_VERIFIED, LEGACY_RETIRED. They never auto-promote a completion-contract row.

Initial rows are AUDITED at source level. PSI-scoped means code consumes the scope,
not that behavior or production screenshots were re-certified. NV = not freshly
verified; NM = no current measurement from this audit. Existing axe is instrumentation,
not a passing populated-state scan for each listed route. Historical proof stays labelled.

## Active program / dispatch

#1346 `codex/performance-serving` is existing draft performance work (audit head
47b90cd412eeed8c8429487de8109823d82baac0), not a visual-completion or activation claim.
#1399 `codex/league-comparison-2026-live` is frontend consumer work. #1421 owns bounded
governance. #1422 `codex/psi-design-reference` is now an implementation branch for the bounded
reference unit, PR #1429 in integration with chart previews explicitly gated. #1428 holds only chart-treatment acceptance; no deployment or continuously running worker is claimed.
Exact dispatch is `docs/ui/PSI_DESIGN_REFERENCE_HANDOFF.md`. #1294 merged September 9;
its old open claim is not an active writer, but independent live overlaps still matter.

## Major surface inventory

| Route / surface | Family | Canonical owner | Contract stability | PSI state | Desktop | Mobile | Accessibility | Performance | Legacy CSS | Visual proof | Claim / PR | Hard dependency | Next action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `/design` | C8-U2/U3 | Static gallery / ds/token-contract.js; no private API | STABLE foundation; chart acceptance #1428 | MIGRATING — incremental non-chart foundation; charts explicitly gated | 1366x768 gated-state tests/screens | 390x844 gated-state tests/screens | Six gated-state axe scans, keyboard and responsive checks PASS; #1428 OPEN | Full build and existing budgets PASS; production NM | Gallery terminal copy retired; outer shell/FAB debt remains | Ten fresh PNGs in PR_1429_2026-09-24/gated-integration; earlier PNGs historical; NO production proof | #1422 / PR #1429 integration | #1428 for chart previews only, not other UI | Normal PR integration/deploy gates; keep chart decision and final production acceptance open |
| `tokens / ds primitives` | C8-U2/U3 | tokens.css + components/ds/* | STABLE styling API; extensions separately claimed | AUDITED — Editorial tokens/shared behaviors exist | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | No new primitive writer confirmed | Preserve owner values and actual surface contrasts | Reconcile gallery/docs and state examples; legacy aliases remain debt |
| `shell / nav / command` | C8-U2/U3 | AppShell, AppShellWrapper, nav-model, auth owner | Existing shared IA; serving files overlap | AUDITED — Top/mobile chrome PSI-scoped | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 | One IA; auth and public/private boundaries | Re-certify focus/search/mobile parity; separately claim shared fixes |
| `/rankings` | C8-U2 reference | useApp/useDynastyData -> canonical /api/data | Existing consumer; #1411/#1346 upstream changes | AUDITED — PSI reference code exists | Code inspected; NV | Parity NV | Populated axe WCAG A/AA 0 violations, table semantics, keyboard sort/focus, reduced motion: `tests/e2e/specs/psi-rankings-player-a11y.spec.js` (#1438 merged `56efc9202`, CI journeys green); production NV | NM | Retirement not re-certified | No fresh production screenshots | #1438 merged; #1346 overlap (line-local, coordinated #1346 comment 5825392001) | Stable consumer boundary; no valuation duplication | Production re-certification (deployed screenshots, perf) — fixture/CI evidence is not production |
| `/players/[playerId]` | C8-U2 reference | Canonical AppShell rows / player identity + player-file-model | Existing contract; next feature boundary needs audit | AUDITED — PSI reference code exists | Code inspected; NV | Parity NV | Populated axe 0 violations on all five tabs + deep link, tab keyboard wiring, unpriced shows 'not priced' (#1438 merged; first Player File component test); production NV | NM | Retirement not re-certified | No fresh production screenshots | #1438 merged; #1346 overlap | One player experience; preserve identity | Mobile depth + production re-certification |
| `/trade` | C3 + C8-U2 | Existing trade-logic + /api/trade/* canonical owners | CONDITIONAL: #1414/#1415 lifecycle/quantity/analysis | AUDITED — PSI code; #1294 merged September 9 | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1441 merged `53109028c` (asset identity/quantity); #1439 merged `439d03850` (NFL exposure section, context-only); #1442 pick lifecycle open | Per-unit canonical asset/analysis contract | Analyze Trade wiring (C3-CALC-01 end state) + production screenshots; exposure/quantity UI not production-verified |
| `/finder / /arbitrage / /trades` | C3 + C8-U2 | Existing finder/package/history owners; trace each endpoint | NOT re-certified | AUDITED — Mixed DS/legacy and redirects | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | C3 package/identity/decision substrate | Audit destinations and reuse shared asset/result primitives |
| `/market/* / Sharp / Insider` | C4 + C8-U2 | Existing market/Sharp canonical endpoints | Existing consumers; freshness semantics changed | AUDITED — Partial DS/PSI family migration | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | Source/market separation; no frontend verdict engine | Reference fidelity, honest coverage and mobile proof |
| `/rosters` | C2 + C8-U2 | /api/roster/intelligence -> src/roster_intel/strength.py | Existing consumer; serving overlap | AUDITED — DS-backed; not PSI-certified | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 | Canonical strength/league state | Shared table/identity and roster-context parity |
| `/phases` | C2 + C8-U2 | Existing canonical competitive-posture consumers | NOT re-certified | AUDITED — Partial DS/PSI work present | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | Canonical posture owner | Presentation/mobile evidence; no posture recalculation |
| `/waivers` | C4 + C8-U2 | /api/waiver/suggestions + canonical FAAB/roster owners | Existing consumer; exact boundaries need audit | AUDITED — DS-backed partial migration | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 | Canonical add/drop/FAAB/league context | Coordinated desktop panes; deliberate mobile stack/tabs and results |
| `/draft` | C1/C5 + C8-U2 | /api/draft-capital + canonical pick lifecycle | CONDITIONAL: #1414 and pick pipeline | AUDITED — DS-backed partial migration | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 / #1411 | Canonical active-pick lifecycle, not local calendar filter | Safe controls/mobile first; integrate retired classes when stable |
| `/gameday` | C9 + C8-U2 | GameDayPanel / canonical matchup and season contracts | CONDITIONAL by feature | IN PROGRESS — PSI hierarchy implemented in #1446 (scoreboard → What matters now → slate → collapsed details/Data info) | Code inspected; NV | Parity NV | Local axe WCAG A/AA 0 violations, 7 states × desktop/390px; committed `tests/e2e/specs/game-day.spec.js` 16/16 locally (webkit NV); production NV | NM | Retirement not re-certified | No fresh production screenshots | #1446 (UI, stacked) on #1445 (backend) — active Lane 6 writer; carries #1346 refresh-in-place hunk with attribution | Selected team / exact best-ball projection | Exact-head CI, deploy, live-game production verification, WebKit, owner visual review |
| `/league and public subroutes` | C9 + C8-U2 | src/public_league/* / public semantic boundary | Existing public contracts; route-specific evolution | AUDITED — Mixed DS / legacy | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1381 power/card overlap | Never expose private intelligence publicly | Audit hubs/franchise/articles/history per route and preserve parity |
| `/league-comparison` | C9 + C8-U2 | Existing LeagueComparison client/API owner | CHANGING in #1399 | AUDITED — Existing UI; no PSI completion proof | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1399 active | Coordinate live consumer files/contract | Avoid restyling claimed files; select another safe unit |
| `/news / /trending` | C4 + C8-U2 | Existing factual news/trending owners | NOT re-certified | AUDITED — DS-backed partial | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | Distinguish factual news and inference | Audit prose/display, freshness and mobile identity |
| `/consensus-edge / /edge / /bdvm / /angle` | C1/C4 + C8-U2 | Existing canonical edge/BDVM/angle owners | NOT re-certified | AUDITED — Mixed DS/legacy | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | No UI model recomputation | Hierarchy/explainability and missing-source semantics |
| `/login / home` | C8-U2 / auth | Existing auth owner and public-safe shell | Existing auth mechanics | AUDITED — PSI-scoped code | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | No new writer confirmed | Auth/gating and focus remain intact | Re-certify error/keyboard/mobile; no new marketing hero |
| `/settings / /more` | C8-U2 / context | Settings/League providers + nav-model | Existing consumers | AUDITED — DS-backed partial | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | Clear canonical ON/OFF and selected league/team | Verify one IA/context across workflows |
| `/admin / sharp-identities` | C8-U2 / operations | Existing authenticated admin/identity owners | NOT re-certified | AUDITED — Mixed DS/legacy | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap on some files | Sensitive auth/write controls | Audit actions/failure states without public leakage |
| `/tools/source-health / ros-data-health / trade-coverage` | C8-U2 / diagnostics | Existing source/ROS/trade coverage owners | NOT re-certified; source semantics changed | AUDITED — Mixed DS/legacy | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | #1346 overlap | Fetch freshness is not content freshness | Shared honest states; preserve exempt-route request policy |
| `/players/compare / residual routes / aliases` | C8-U2 | Existing comparison/final destination owners | NOT re-certified | AUDITED — Residual legacy/details unclassified | Code inspected; NV | Parity NV | Existing suite; route NV | NM | Retirement not re-certified | No fresh production screenshots | No new writer confirmed | Inventory actual consumers before CSS deletion | Audit final destinations; aliases are not separate products |

## Updating a unit / safe sequence

Record exact claim/PR/head, stable contract boundary, viewports, keyboard/axe result,
performance command/measurements, screenshot paths/run, deployment SHA/URL/time,
unresolved defects and retired legacy selectors. A blocked route names the next safe
UI task. Local/CI images do not establish production verification.

First #1422 fixes the living /design reference without trade/backend dependencies.
Next complete the populated Rankings/Player File accessibility/visual matrix with
#1346/shared-test-owner coordination; then advance agreed Trade asset identity/quantity
presentation while final lifecycle/Analyze Trade wiring waits only on its own contract.
Continue high-value stable routes and verified legacy retirement, reprioritizing each
batch rather than waiting for every backend feature to finish.

## Measured checkpoint — PR #1429

Code `49e7fcfd824ba3f2c7432a818d2f7f5fbc2d8121`; actual proof and limitations in
`docs/psi/evidence/PR_1429_2026-09-24/README.md`. Axe green does not close #1428.
The next safe UI unit remains populated Rankings/Player File test coverage after
live claim checks; no whole-program blocker or route-completion promotion.
