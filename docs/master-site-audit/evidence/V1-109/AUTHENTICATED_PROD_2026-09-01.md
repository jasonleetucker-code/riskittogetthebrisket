# V1-109 authenticated production evidence — 2026-09-01

## Scope

This artifact records the production-consumer evidence for V1-109 (mobile usability for roster-heavy views). It does **not** change the V1 denominator or the canonical ledger status by itself.

## Run

- Workflow: `V1 Authenticated Production Verification (ephemeral guest session)`
- Run: `33528409461` / run number `23`, attempt `1`
- Event: `workflow_dispatch`
- Workflow head: `b5fec9ba86a24b80d9c97c051437a51adfd0cb22`
- Started: `2026-09-01T15:52:23Z`
- Production origin was resolved successfully.
- An ephemeral production guest pass was minted through the canonical on-box implementation, login succeeded through the real auth path, and the pass was revoked after verification.

## V1-109 browser result

The dedicated production spec `tests/e2e/specs/prod-auth/v1-109-mobile-usability.spec.js` ran under the `prod-mobile` project (390x844, mobile/touch semantics) against the deployed production site. All five V1-109 mobile assertions passed:

1. `/trade` — sticky verdict tray and screenshot FAB do not overlap.
2. `/rankings` — at least three visible watchlist buttons are sampled and each button's **effective hit-tested** area is at least 24x24 px.
3. `/rankings` — more than 50 visible text-bearing elements are measured and none is below the 10 px defect floor.
4. `/rosters` — more than 50 visible text-bearing elements are measured and none is below the 10 px defect floor.
5. `/draft` — more than 50 visible text-bearing elements are measured and none is below the 10 px defect floor.

The same V1-109 cases are intentionally skipped in `prod-desktop`; the spec calls `mobileOnly` and is explicitly a 390x844 production-mobile proof. Those desktop skips are expected behavior, not missing V1-109 coverage.

## Non-vacuity / false-green review

The production spec contains explicit guards against the known false-green modes:

- `/trade` requires exactly one `.trade-sticky-tray` and one `.screenshot-fab` before overlap is evaluated, so an empty pinned-element population cannot pass.
- `/rankings` requires the real rankings board to render, requires at least three fully visible watchlist buttons, checks that each button's center hit-tests back to the button, then measures the effective hit area with `document.elementFromPoint`; a decorative CSS box that does not receive pointer hits cannot satisfy the assertion.
- The type-floor tests require the route's real table/board to render and require `checked > 50` visible text-bearing elements before accepting an empty offender list.
- Hidden/zero-size/`aria-hidden` elements are excluded rather than being counted as proof.
- Missing evidence is not converted to zero and a missing target population is asserted as failure.

## Overall workflow conclusion

The workflow's overall conclusion is `failure`, but **the Browser verification suite step completed successfully**. The job shows the API suite and Lane-4 remote suite as skipped, followed by a final aggregation step that failed the job on the combined API/lane4/browser verdicts. This artifact therefore does not relabel the whole run green. It records only the independently successful V1-109 browser consumer evidence.

That orchestration-level red conclusion must not be conflated with the V1-109 browser verdict, and conversely the V1-109 browser success must not be used as evidence for the skipped API/Lane-4 checks.

## Promotion implication

The canonical V1 contract currently leaves V1-109 at `IMPLEMENTED_UNVERIFIED` because its remaining stated requirement is L4 production-consumer evidence. This run supplies that specific production-browser evidence non-vacuously. Canonical promotion remains a separate ledger reconciliation step and must preserve `MERGED != DEPLOYED != VERIFIED`.
