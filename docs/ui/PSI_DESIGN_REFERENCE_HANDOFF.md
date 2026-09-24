# Fresh-session handoff — #1422 /design PSI reference

Existing Lane 6 / C8-U2 + C8-U3, parent #1421.
Branch: `codex/psi-design-reference`, separate and stacked on the reviewable governance
head until Integration lands it. Initial reservation has advanced to implementation; inspect the current PR/evidence before resuming. Deployment and production proof remain separate gates.
Agent-OS-Receipt at audit: cdca1dca8385f70c0989302dece8d1bd4ce4843c; regenerate for the implementation session.

## Copyable prompt

```text
Repo jasonleetucker-code/riskittogetthebrisket, project Calculator. Implement #1422.
Read AI_INSTRUCTIONS, current Agent OS, Execution Plan/active completion contract,
WORK_CLAIMS and live open PR changed files. Read PSI North Star,
docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md, UI_PARALLEL_LEDGER.md and dated audit.
Recheck #1421 governance, #1346 performance and #1399; do not assume this audit is current.

Claim only frontend/app/design/DesignGallery.jsx, frontend/app/design/design.module.css,
frontend/app/design/page.jsx, frontend/__tests__/components/ds/psi-gallery.test.jsx,
tests/e2e/specs/psi-gallery.spec.js, bounded docs/ui evidence and WORK_CLAIMS updates.
Separate branch codex/psi-design-reference; stack on governance while it is unmerged.
No globals.css/tokens.css/ds.css/AppShell/nav-model/package.json/backend/math/deploy edits.

Audit Gallery/Modal/Drawer APIs. Apply existing psi-editorial scope, including portalled
examples. Demonstrate existing font-display; correct terminal/gold/historical contrast
labels. Explicitly label fixture values/actions as demonstrations, not live league data
or real offers. Preserve all useful examples and noindex/no-nav/private-request exemption.
Use current shared primitives, semantic tokens and canonical breakpoints. No new palette,
font, radius, type scale or visual language. A genuinely new visual decision is OWNER UI
DECISION REQUIRED for only that choice; continue other safe work.

Ensure desktop/phone access to controls, player identity and table detail. Test keyboard,
focus restoration, dialog/drawer and reduced motion. Add deterministic component and
Playwright/axe tests with meaningful readiness, not a sleep-only scan. Capture and inspect
desktop and phone screenshots plus overlays/states. Run current Vitest, build/bundle,
E2E/axe and L0 commands. Record failures, do not weaken checks. Shared primitive repairs
need a separate bounded claim rather than silent cross-lane editing.

Update ledger/claim with exact SHA/tests/evidence. Integration and actual production
verification remain separate required gates. Never call local/CI screenshots production
proof or self-merge. Route instability redirects UI work; it does not stop Lane 6.
```
