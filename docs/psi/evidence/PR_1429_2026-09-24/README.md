# PR #1429 — PSI gallery evidence, 2026-09-24

**Code tested:** `49e7fcfd824ba3f2c7432a818d2f7f5fbc2d8121`. **Run:** 36021591253.
**Origin:** built local CI stack, `http://127.0.0.1:3000/design`, NOT production.
The evidence-only follow-up commit does not change tested frontend or E2E code.
Source artifact 10817595460 is checksummed in manifest.json. The ten exact PNGs
are preserved here so the evidence does not disappear when the artifact expires.
This is manual screenshot review plus automated behavior testing, not an approved
pixel-golden comparison or owner sign-off. Not deployed / PSI_VERIFIED / legacy-retired.

## Exact validation

| Gate | Actual result |
|---|---|
| Frontend Vitest | 168 files; 2,483 tests passed, including four gallery tests |
| Build / bundle | production build and all 14 existing route budgets passed |
| Own gallery JS chunk | 27,690 -> 28,881 bytes; +1,191 bytes; not total shared first-load JS |
| Desktop 1366x768 / phone 390x844 | four real-stack E2E passed, zero skipped; retries disabled |
| Axe | six populated/modal/drawer scans passed, WCAG A/AA; not a full chart-contrast certificate |
| Keyboard / responsive | opening/closure/focus restoration, reduced motion, table sort/density/detail access, one main and no document overflow passed |
| Page exceptions | no pageerror exceptions in the tested flows; not a claim of zero all-console/harness warnings |
| Governance | planning, product-plan, claim check, L0; docs 88 tests and 43 subtests passed |
| Production | not deployed, not measured, not verified |

Current commands were `npm --prefix frontend test`, `npm --prefix frontend run build`,
`npm run regression:preflight`, and `npx playwright test --config tests/e2e/playwright.config.js
tests/e2e/specs/psi-gallery.spec.js --project=desktop-1366 --project=mobile-chromium --retries=0`.
Focused coverage floor was four passes/zero skips; full-suite reporters and guards unchanged.
No separate frontend lint script existed. Logs remain in the original Actions artifact;
background harness startup/metadata warnings were not hidden or counted as production proof.

## Screenshots reviewed

| State | Desktop | Phone |
|---|---|---|
| reference-top | [desktop](desktop-reference-top.png) | [phone](phone-reference-top.png) |
| reference-full | [desktop](desktop-reference-full.png) | [phone](phone-reference-full.png) |
| table-secondary-fields | [desktop](desktop-table-secondary-fields.png) | [phone](phone-table-secondary-fields.png) |
| modal | [desktop](desktop-modal.png) | [phone](phone-modal.png) |
| drawer | [desktop](desktop-drawer.png) | [phone](phone-drawer.png) |

Inspection confirms editorial gallery scope and hierarchy, readable fixture/state labels,
accessible table detail, phone-safe modal and player-name/chart drawer layout. Full-page
and viewport/interaction captures complement each other; a full-page image alone cannot
certify sticky chrome behavior. Existing dark outer canvas and legacy Screenshot FAB
remain visible outside this bounded gallery claim. Record these as shell convergence
debt; do not silently restyle high-conflict shared files.

## Specific remaining visual decision — #1428

**OWNER UI DECISION REQUIRED** for categorical chart treatment unless an existing
approved compliant reference is established. The legacy fixed palette's recorded >=3:1
validation was on a dark panel, not every cream surface. Standard sRGB calculations:

| Token | Current value | PSI panel | PSI nested / alternate |
|---|---|---:|---:|
| --chart-1 | #c98500 | 2.85:1 | 2.32:1 |
| --chart-2 | #3987e5 | 3.37:1 | 2.75:1 |
| --chart-3 | #d55181 | 3.66:1 | 2.98:1 |
| --chart-4 | #9085e9 | 2.90:1 | 2.36:1 |
| --chart-5 | #199e70 | 3.16:1 | 2.57:1 |
| --chart-6 | #d95926 | 3.60:1 | 2.94:1 |

The actual amber drawer/table Sparkline illustrates the gap; axe does not clear it.
No colors, movement semantics, contrast threshold or design authority were changed.
Resolve only this decision under the owner/approved-reference hierarchy, with token-owner
and shared-primitive claims where needed. No gallery shipping/PSI completion claim yet.

## Integration and continuous UI

Parent governance PR #1426; separate UI PR #1429 remains draft. #1428 blocks only the
affected chart acceptance, not Lane 6. Next safe work is populated Rankings/Player File
accessibility/visual test coverage with checked disjoint test paths, alongside existing
performance/consumer work. Recheck current main/PR files/claims before dispatch.
Final production acceptance still requires real deployed desktop/phone flows, auth,
data/loading/error/focus/console/performance and owner-review evidence.
