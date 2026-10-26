## Summary

Bounded outcome, authority, related issue and canonical owner.

## Implementation and integration state

- Implementation: IMPLEMENTING / IMPLEMENTED_UNVALIDATED / FEATURE_GREEN / READY_FOR_INTEGRATION
- Integration: NOT_READY / VALIDATING / INTEGRATION_GREEN / MERGED
- Exact-tree CI head + required status checks:
- Independent review, dependencies, file claims, conflict/freshness triage:
- Owner-only promotion/launch/security gates: N/A / PASSED / BLOCKED (explain)
- Integration Authority can merge automatically when *all required* gates are green; no routine owner "please merge" prompt is needed.
- Deployment and production VERIFIED status must be recorded separately.

## Validation and evidence

Exact commands, tested SHA, results and limitations. Separate local/CI from production.
Material agent work includes its `Agent-OS-Receipt`.

## UI impact (material product/UI changes only)

Tiny maintenance may explain none and omit irrelevant fields. Substantial batches
still include or reference active Lane 6 coverage.

- [ ] none — explain
- [ ] existing active UI lane covers it — issue / PR / work claim
- [ ] parallel UI work included — branch / claim
- [ ] route contract not stable — ledger dependency; name other active UI work

PSI reference used:
Mobile verified:
Accessibility verified:
Performance checked:
Visual evidence:

Details: `docs/ui/UI_IMPACT_TEMPLATE.md`,
`docs/ui/CALCULATOR_UI_IMPLEMENTATION_CONTRACT.md`, `docs/ui/UI_PARALLEL_LEDGER.md`.

## Integration / release

Dependencies, live-PR file overlap, rollout/rollback and outstanding production proof.
Do not equate code, tests, merge, deployment and verified acceptance.
