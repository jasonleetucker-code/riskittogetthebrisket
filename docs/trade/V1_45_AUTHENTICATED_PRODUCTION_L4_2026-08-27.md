# V1-45 — Authenticated production L4 evidence (2026-08-27)

This packet preserves row-specific production evidence for **V1-45 — Trade calculator**. It records what the deployed application and authenticated browser actually proved; it does not change trade methodology, canonical ownership, authentication, V1 scope, or the completion tally by itself.

## Deployed application revision

PR #1150 merged the bounded `/trade` team-selector synchronization repair. GitHub Actions **Deploy Production** run **33066619784** completed successfully for exact application SHA:

`b194316f0f1cd76e5eca4e0d73b20031a1d5f6cb`

That repair did not add frontend trade math. The `/trade` surface continues to consume the canonical `POST /api/trade/simulate` response and its `finalRosterSimulation` block.

## Authenticated production verification

Authenticated production verification workflow run **32919648642**, attempt 6, produced artifact `v1-authenticated-report` (artifact id **9651177604**, created 2026-08-27T14:42:22Z).

The run used the repository's established ephemeral guest-pass path: canonical guest pass mint, real `/api/auth/login`, production reads/browser interactions, then pass revocation. The guest remained non-admin.

### API evidence

`v1-auth-report.json` records **V45A PASS**. The live `POST /api/trade/simulate` returned a populated `finalRosterSimulation` carrying canonical final-roster fields, including availability/cleanup and strength-before/after/delta state.

### Browser / L4 consumer evidence

`prod-auth-browser.txt` records PASS for:

`tests/e2e/specs/prod-auth/v1-45-trade-surface.spec.js`

The production `/trade` page drove the real UI, issued its **own** canonical `POST /api/trade/simulate`, and the rendered `SimulationPanel` matched the response's `finalRosterSimulation` field-for-field under the page's own formatting rules.

This closes the contract's demonstrated L4 consumer gap: the user-facing `/trade` surface consumes canonical final-roster simulation truth rather than recomputing it client-side.

## Evidence qualification

The workflow checkout for attempt 6 predates PR #1150, but the V1-45 browser spec itself predates the repair and targets the **live deployed production origin**. The deployed application revision exercised by that browser run is independently bound above by successful Deploy Production run 33066619784.

This packet must not be reused to claim V1-56, V1-61, or V1-131 passed. In the same production attempt those rows retained real failures/unmeasurable states and remain separate.

## Promotion posture

On re-reading the live V1 contract, V1-45 remains `IMPLEMENTED_UNVERIFIED` at **L4**, with promotion requiring the real `/trade` surface to consume the canonical implementation. The evidence above satisfies that named production-consumer requirement.

A separate contract reconciliation should promote V1-45 to `VERIFIED` only after this evidence packet is integrated and the repository's normal planning/contract validators pass on the exact promotion head.
