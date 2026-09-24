# Gated gallery integration evidence

Code: `30a853691c13c65cfa7d7680cf024c7185447da2`; base: `af199bacb29a4b0df80c7f0df84f7ae9c5f47c32`.

Run: 36055955615. Full frontend unit suite, build and all existing bundle budgets passed. Four real-stack desktop/phone E2E tests passed with zero skips/retries; six axe state scans, keyboard/focus, table access and page-overflow checks passed. Ten original PNGs are checksummed in manifest.json; Playwright attachment copies are not counted twice.

The focused run uses the canonical coverage reporter with E2E_MIN_PASSED=4 and E2E_MAX_SKIPPED=0 because its selected suite is two tests on two projects; no full-suite defaults or shipping tests are weakened. The earlier helper run 36055160060 passed its four tests but correctly failed its incorrectly inherited full-suite floor of 120; that failed run is not claimed green.

These screenshots show the fail-closed chart preview state, not approved chart treatment. Original parent-directory screenshots are historical pre-gate evidence. No palette, token, DS primitive, business logic or product chart was changed. #1428 and final /design PSI acceptance remain OPEN. This is CI evidence, not production verification or owner visual approval.
