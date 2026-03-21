# Formula Authority Map (Live Runtime)

Last verified: 2026-03-20

## 1) Source-of-Truth Docs Found
- `docs/BLUEPRINT_EXECUTION.md` (`complete` for declaring intended valuation authority): [`docs/BLUEPRINT_EXECUTION.md:75`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/docs/BLUEPRINT_EXECUTION.md:75), [`docs/BLUEPRINT_EXECUTION.md:92`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/docs/BLUEPRINT_EXECUTION.md:92)
- `docs/REPO_INVENTORY.md` (`complete` for current runtime authority map): [`docs/REPO_INVENTORY.md:44`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/docs/REPO_INVENTORY.md:44)
- `docs/RUNTIME_ROUTE_AUTHORITY.md` (`complete` for static runtime route authority): [`docs/RUNTIME_ROUTE_AUTHORITY.md:10`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/docs/RUNTIME_ROUTE_AUTHORITY.md:10)

Primary blueprint for valuation authority is `docs/BLUEPRINT_EXECUTION.md` because it explicitly declares the value bundle contract and live authoritative path.

## 2) Active Formula Authority Path (Verified)
1. `Dynasty Scraper.py` (`complete`): source ingestion, identity merge, canonical transforms, weighting/blending, `_composite` creation, and league-adjusted precompute fields.
2. `src/api/data_contract.py` (`complete`): constructs backend-authoritative `valueBundle`, normalizes output contract, and writes compatibility aliases.
3. `server.py` (`complete`): builds and publishes `/api/data` from contract payload.
4. `Static/js/runtime/*` (`partial` fallback authority): consumes backend bundles for known assets; computes local fallback only when backend fields are absent/manual context.

## 3) Formula Authority Map (Input -> Transform -> Output)

| Stage | Status | Inputs | Transform authority | Output fields | Code |
| --- | --- | --- | --- | --- | --- |
| Raw source values + source key mapping | `complete` | Site payloads from scraper/CSV/API | Site-key normalization + source max setup | per-site fields (`ktc`, `idpTradeCalc`, etc.), `maxValues` | [`Dynasty Scraper.py:8759`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:8759), [`Dynasty Scraper.py:8781`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:8781) |
| Identity merge / canonical player resolution | `complete` | Raw names + Sleeper db + roster map | Deterministic candidate scoring/order + site-level match hierarchy | canonical player rows in `players_json` | [`Dynasty Scraper.py:9027`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:9027), [`Dynasty Scraper.py:9059`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:9059), [`Dynasty Scraper.py:8992`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:8992) |
| Position/site filtering (OFF vs IDP) | `complete` | canonical name + resolved position + source key | IDP-only/offense-only source filters | inclusion/exclusion of site values per player | [`Dynasty Scraper.py:9053`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:9053), [`Dynasty Scraper.py:9257`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:9257) |
| Rank/value normalization | `complete` | rank and value site inputs | Universe-specific rank->value calibration, IDP caps, TEP transforms | canonical site values | [`Dynasty Scraper.py:10482`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10482), [`Dynasty Scraper.py:10672`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10672), [`Dynasty Scraper.py:10696`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10696) |
| Weighting / blending / outlier controls | `complete` | canonicalized per-site values | weighted norm blend + adaptive trim + confidence-driven controls | `_composite`, `_sites`, `_marketConfidence`, `_marketDispersionCV` | [`Dynasty Scraper.py:10248`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10248), [`Dynasty Scraper.py:10726`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10726), [`Dynasty Scraper.py:10804`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10804), [`Dynasty Scraper.py:10817`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10817) |
| Rookie handling | `complete` | Sleeper years_exp + rookie lists + rookie-only DLF signals | rookie universe routing + rookie-only source quarantine + IDP rookie guardrail | composite eligibility + caps | [`Dynasty Scraper.py:10294`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10294), [`Dynasty Scraper.py:10257`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10257), [`Dynasty Scraper.py:10795`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10795) |
| IDP handling | `complete` | IDPTradeCalc + IDP rank/value sites + IDP positions | dynamic IDP anchor/backbone, IDP rank curve, IDP headroom/caps | IDP canonical values + IDP composite controls | [`Dynasty Scraper.py:10127`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10127), [`Dynasty Scraper.py:10221`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10221), [`Dynasty Scraper.py:10240`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10240), [`Dynasty Scraper.py:10778`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10778) |
| League/format adjustments | `complete` | `_composite` + LAM multipliers + per-player fit | league multiplier application + format-fit overlays | `_rawComposite`, `_leagueAdjusted`, scoring debug fields | [`Dynasty Scraper.py:11493`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:11493), [`Dynasty Scraper.py:11527`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:11527), [`Dynasty Scraper.py:11532`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:11532) |
| Authoritative value bundle shaping | `complete` | scraper output player rows | constructs raw/scoring/scarcity/best-ball/full layers + confidence + sourceCoverage | `valueBundle`, legacy aliases, `playersArray` values | [`src/api/data_contract.py:640`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:640), [`src/api/data_contract.py:816`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:816), [`src/api/data_contract.py:1188`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:1188) |
| API publication | `complete` | contract payload | `/api/data` full/runtime/startup views | final payload consumed by UI | [`server.py:1018`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/server.py:1018), [`server.py:1587`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/server.py:1587) |
| Frontend formula consumption (known assets) | `complete` after guardrail | backend `valueBundle` or legacy precomputed fields | resolve known-player bundle, prevent silent alternate-path recompute | displayed adjusted values + diagnostics | [`Static/js/runtime/00-core-shell.js:2358`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2358), [`Static/js/runtime/00-core-shell.js:2653`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2653), [`Static/js/runtime/40-runtime-features.js:1418`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/40-runtime-features.js:1418) |
| Frontend fallback formula engine (manual/unknown assets) | `partial` (intentional fallback) | user-entered/manual site values or missing backend players | canonical transform + local final-adjust compute fallback | fallback adjustment bundles for non-authoritative assets | [`Static/js/runtime/00-core-shell.js:2101`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2101), [`Static/js/runtime/00-core-shell.js:2189`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2189), [`Static/js/runtime/00-core-shell.js:3024`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:3024) |

## 4) Duplicate / Conflicting Logic Found

1. Frontend duplicate transform/composite engine exists (`partial`, intentional fallback but drift risk):
   - Local `getCanonicalSiteValueForSource` + `computeCanonicalCompositeFromSiteValues`
   - Backend already performs canonical transform/composite for known players.
   - Code: [`Static/js/runtime/00-core-shell.js:2101`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2101), [`Dynasty Scraper.py:10672`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10672)

2. Frontend duplicate final-adjust math exists (`partial`, intentional fallback):
   - `computeFinalAdjustedValueCore` can reproduce scoring/scarcity/final adjustments.
   - Backend already precomputes and publishes these layers in `valueBundle`.
   - Code: [`Static/js/runtime/00-core-shell.js:3024`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:3024), [`src/api/data_contract.py:640`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:640)

3. Constant drift risk between backend vs frontend fallback (`stale` risk, not authoritative for known assets):
   - Example: elite boost / rank-curve behavior differs between scraper and JS fallback constants.
   - Code: [`Dynasty Scraper.py:10234`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Dynasty%20Scraper.py:10234), [`Static/js/runtime/00-core-shell.js:46`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:46)

4. Legacy alias compatibility fields are still active (`partial`, deliberate compatibility layer):
   - Contract writes `_rawComposite`, `_leagueAdjusted`, `_finalAdjusted` aliases in addition to `valueBundle`.
   - Code: [`src/api/data_contract.py:816`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:816)

## 5) Consolidation Changes Applied

1. Added known-player authority resolver and passthrough guardrail:
   - `resolveKnownPlayerAdjustmentBundle` and `buildBackendRawPassthroughAdjustmentBundle`.
   - If known player lacks backend-adjusted layers, runtime now returns explicit backend-raw passthrough bundle instead of silently switching to alternate frontend formula math.
   - Code: [`Static/js/runtime/00-core-shell.js:2544`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2544), [`Static/js/runtime/00-core-shell.js:2653`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2653)

2. Wired rankings/trade known-player flows through the shared authority resolver:
   - Rankings table row adjustments now use shared known-player resolver first.
   - Trade-item resolver for known assets now uses shared known-player resolver first.
   - Code: [`Static/js/runtime/10-rankings-and-picks.js:321`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/10-rankings-and-picks.js:321), [`Static/js/runtime/10-rankings-and-picks.js:614`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/10-rankings-and-picks.js:614), [`Static/js/runtime/20-data-and-calculator.js:999`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/20-data-and-calculator.js:999), [`Static/js/runtime/20-data-and-calculator.js:1080`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/20-data-and-calculator.js:1080)

3. Updated final-adjust entrypoint to use shared known-player authority resolver:
   - `computeFinalAdjustedValue` now uses known-player resolver (including passthrough guardrail) before fallback core math.
   - Code: [`Static/js/runtime/40-runtime-features.js:1418`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/40-runtime-features.js:1418)

4. Added trust-first full-authority guardrails (`complete` for backend truth, `complete` for rankings/trade consumption):
   - Backend `valueBundle.guardrails` now publishes explicit final-authority status (`final_adjusted_authoritative`, `derived_without_final_adjusted`, `quarantined`) plus cap/quarantine reason codes.
   - Full authority no longer silently aliases `_leagueAdjusted` when `_finalAdjusted` is missing; derived full now uses explicit `derived_best_ball_final` source labeling.
   - Unresolved-position non-pick assets are quarantined from final authority and skipped in rankings/trade runtime paths.
   - Code: [`src/api/data_contract.py:662`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:662), [`src/api/data_contract.py:795`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/src/api/data_contract.py:795), [`Static/js/runtime/00-core-shell.js:2425`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/00-core-shell.js:2425), [`Static/js/runtime/10-rankings-and-picks.js:248`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/10-rankings-and-picks.js:248), [`Static/js/runtime/20-data-and-calculator.js:1000`](/C:/Users/jason/OneDrive/Desktop/Trade%20Calculator/Static/js/runtime/20-data-and-calculator.js:1000)

## 6) Open Business-Rule Questions (No formula change made here)

1. For known assets missing backend-adjusted layers, should runtime:
   - keep current new behavior (`backend_raw_passthrough_fallback`), or
   - hard-fail/flag those assets as invalid until scraper/contract is repaired?

2. Should frontend fallback constants be explicitly versioned to backend formulas for manual/unknown assets, or remain intentionally independent approximation logic?

3. Should contract compatibility aliases (`_leagueAdjusted`, `_finalAdjusted`, etc.) remain long-term, or be sunset after all active surfaces exclusively consume `valueBundle`?
