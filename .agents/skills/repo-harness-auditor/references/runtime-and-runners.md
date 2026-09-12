## Runtime-capability hygiene

When a model/runtime adds asynchronous tools, mid-turn steering, dynamic reasoning, or other long-running controls:

- verify the capability on the exact product/API surface before the harness depends on it;
- keep pending tool calls as explicit identified state, including timeout/cancel/failure outcomes;
- confirm steering preserves still-valid completed work instead of resetting the whole task;
- avoid rewriting accepted prompt/history prefixes merely to change reasoning effort when the runtime offers a scoped configuration update;
- record material reasoning/effort changes when they affect cost, latency, or reproducibility;
- test fallback behavior on runtimes that do not support the new capability;
- keep vendor-specific request syntax out of the model-agnostic Agent OS unless the repository actually owns that API integration.

## Continuous-stewardship readiness hygiene

When reviewing a proposed recurrent site steward or self-improvement runner, verify:

- the scheduler/event source is external to the model call;
- source discovery is separated from canonical source activation;
- candidate sources have explicit lifecycle states and cannot influence production merely because they were discovered;
- competitor/product research captures concepts and user outcomes rather than copying proprietary code/assets/text;
- media/analyst observations preserve provenance, time horizon, freshness, and correlation/source-family information;
- model/math work creates challengers and evidence but cannot self-promote across an approval boundary;
- low-risk repair/prototype work is separated from consequential product/methodology changes;
- persistent run state records last processed items, pending work, candidates, budgets, retries, unresolved decisions, and receipts;
- the design defines success metrics for the autonomous system itself, including false-completion/reviewer-rejection rate and owner interventions;
- the runner follows `docs/AUTONOMOUS_SITE_STEWARD_VISION.md` when that owner-approved long-term program is in scope.

## Autonomous-runner hygiene

When reviewing any unattended/recurrent agent runner, verify:

- committed contract and gitignored local overrides are separated;
- local overrides can tighten but cannot weaken committed safety boundaries;
- wall-clock, action/iteration, retry, parallel-width, and spend/token budgets are enforced outside prompt prose;
- destructive/out-of-scope actions have an explicit denylist or allowlist boundary;
- repo-owned model invocation has one auditable gateway rather than scattered hidden call sites;
- per-run receipts and traces are append-only;
- checkpoints contain enough state to resume but still force fresh preflight against current repo/PR/CI state;
- verification is executable where possible and independent grading is separate from authorship;
- a fail-closed external halt sentinel is checked before start and before consequential side effects;
- report-only, assisted, and autonomous modes are explicit rather than inferred;
- scheduled autonomy has an owner-approved activation decision and rollback path.

Do not deploy a new unattended runner merely because the harness audit describes how one should be governed.

