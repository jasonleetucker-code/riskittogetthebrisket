# Local Steward Runtime

This is the implementation guide for the report-only control plane in
`src/steward/`. It extends the canonical Agent OS and the existing Site
Steward architecture; it is not another product roadmap or an unattended runner.

## Authority and Entry

The owner's 2026-09-10 Astra consolidation directive authorizes this local
implementation and normal repository integration. It supersedes the earlier
sequencing deferral for this Agent OS work only. The Week 1 contract still
requires literal 30/30; product work follows `docs/EXECUTION_PLAN.md`.
No model/API dispatcher, scheduler, merge executor, source activator, or paid
inference loop is installed. Recommendations never grant action authority.

Run from the designated working copy after fetching current origin/main:

```sh
python -m src.steward brief --github --save --available-model gpt-6-astra
python -m src.steward context docs/EXECUTION_PLAN.md --max-chars 8000
python -m src.steward retrieve campaign
```

Supply only models actually available in the current harness. A catalog entry
is not availability. Without an observed available model the route is BLOCKED,
not an invented dispatch. Omit `--github` for offline inspection; remote
freshness/open-work coverage then stays UNKNOWN. Failures reading GitHub are
errors, not empty successful inventories. `--save` writes only ignored local
state. JSON output is available with `brief --json`.

## State and Knowledge

The sole mutable store is `.agent-runtime/steward/state.sqlite3`, schema
version 1 (`PRAGMA user_version`). It is private/local and is never served by
the site. Git retains canonical documents and their original revisions.
SQLite holds four tables:

- `state(name, revision, payload)`: current campaign/checkpoint and knowledge revision.
- `evidence(id, payload)`: immutable raw observations, with source, time,
  repository revision, original content, and full/excerpt coverage.
- `knowledge(id, layer, topic, payload, superseded_by)`: compact maintained
  knowledge, explicit provenance references, authority and supersession.
- `history(sequence, payload)`: immutable prior checkpoint revisions.

Working, episodic, semantic and owner knowledge remain separate layers.
Owner preferences are attributed owner records, not technical facts.
`remember` requires existing raw evidence and an expected knowledge revision;
a lower-authority record cannot supersede a higher-authority record.
Supersession is atomic and old evidence survives. Retrieval excludes superseded
records and returns omitted-count and revision information.

There is no second embedding/index service: retrieval queries the same SQLite
transaction snapshot as the knowledge revision. A stale consumer can compare
its retained retrieval revision to the new one. The CLI also reports knowledge
repository-revision mismatches; inspect source changes before trusting them.

```sh
python -m src.steward remember decision.json --evidence evidence.json --expected-revision 0
python -m src.steward checkpoint checkpoint.json --expected-revision 1
python -m src.steward backup /private/backup/steward-before-migration.sqlite3
```

Evidence input: `{"id": "...", "payload": {"source": "...", "at": "...",
"repo_head": "<40-char SHA>", "content": "...", "complete": true}}`.
Knowledge input: `id, layer, topic, summary, authority, evidence_ids,
repo_head, at`, with optional `supersedes`. Authorities are observation,
verified, repository and owner; they describe recorded evidence, not runtime
permissions.

Checkpoint input may update only `objective, partial, completed, blockers,
next_action, task_states`. Per-task updates contain `state` and `evidence`.
Verification requires matching acceptance criteria, passing evidence references
and an exact revision; production-required work also requires production
identity. These are evidence-recording guards, not a substitute for independent
verification of the referenced artifacts.

All writes use transactions; a saved brief commits evidence, checkpoint,
compiled knowledge and supersession together, with both revision checks.
Mutable writes require compare-and-swap revision
checks. Conflicts must be reread and reconciled, never blindly retried with a
new revision. Backup uses SQLite's online backup API and refuses to overwrite
an existing destination. Restore offline with the matching runtime; future
unknown schemas are refused. This first version has no destructive migration.
The unmerged #1318 store is historical evidence, not silently imported state.

## Planner

`repository.inventory` reads the canonical 163-row manifest through the
existing planning-integrity parser, the current launch rows, owner intake,
execution plan, claims, traceability and backlog records. It preserves raw
source rows and hashes. Narrative status is labeled SOURCE_CLAIM, not VERIFIED.

`phase_tasks` derives the ten existing replan groups rather than duplicating
the roadmap. `reconcile` associates long-tail manifest work with those owners,
retains excluded/baseline/final-closure buckets, and overlays later source
dispositions plus current GitHub issues. Closed PR is never interpreted as
merged. Unreviewed branches remain visible for inspection; nothing merges them.
New operational issues are observations requiring diagnosis, not automatically
new engineering work. Source or parser drift fails visibly.

`work_units` retains every manifest requirement or an explicit baseline/exclusion
disposition and imports actual launch/intake acceptance and row dependencies.
Missing acceptance stays blocked. `planner.plan` topologically orders dependency-ready work, favors shared
unlocks, and considers supplied context/CI cost estimates. It clusters only
compatible, same-authority and same-rollback work with a genuine shared touch.
High-risk work and serial dependencies remain separate. Every phase retains
per-item acceptance, tests, docs, production requirements, unresolved work and
rollback boundaries. WIP is bounded. Missing dependencies/cycles cannot turn
into READY. Shared acceptance may satisfy multiple tasks but never promotes
an untested sibling. Partial checkpoints survive replanning.

The plan is advisory sequencing. Broad product phases remain subject to launch
and owner authority. Phase 9's historical deferral is superseded for this
specific consolidation campaign; future unattended Steward activation is not.
The report does not count old manifest COMPLETE claims as newly tested work.
At phase selection, trace the live execution path and verify the referenced
evidence. Live inventory coverage is not a claim that the entire site was audited.

## Routing and Learning

`config/steward/routing.json` is configurable capability metadata, observed
from the current interactive harness. ROUTINE, STANDARD, COMPLEX and CRITICAL
select sufficient available configurations, with reasoning chosen separately.
Current defaults range from Luna/low through Terra/medium, Sol/high and
Astra/high. Claude, Gemini and Grok adapters can supply their own verified
metadata; they remain unconfigured rather than pretending availability.

The policy supports owner model/effort pins, provider prohibitions, minimum
profile, delegation disablement, usage ceilings and approval-before-escalation.
Unavailable pins fail closed. Other unavailable models fall back to a sufficient
permitted candidate. Failed acceptance raises capability; resolved mechanical
continuation can downgrade. Risk still wins over cheapness. The current CLI
recommends only. The lead may apply supported interactive subagent controls;
it cannot claim automatic switching of its own active model.

Route receipts preserve task, profile, reason, model, effort, context references,
acceptance and measurements. Unexposed token/cache/time/cost/allowance fields
stay null, never zero. Report generation is not model execution.
`retrospective` groups comparable task classes, exposes measurement coverage
and proposes challengers without promoting them. `diagnose_failures` records
specific rule references when repeated independent failures suggest an
instruction/specification problem. Investigate the spec, test and architecture
before repeating the same failing prompt.

## Moving Main and Generated Data

Fetch before major phases, expensive final validation and integration. The
Steward never fetches silently or treats a local ref as a fresh GitHub read.
`brief --github` independently compares the GitHub head to origin/main.

```sh
python -m src.steward check-integration --github --base <previous-main-sha> --surfaces src/steward config/steward docs
```

Optional `--proof proof.json` records exact reviewed paths, all intervening
commit IDs and workflow evidence. A bot author or commit prefix alone is
insufficient. UNKNOWN_REQUIRES_INSPECTION maps to the coordination policy's
conservative relevant handling. Changed workflows/config/governance or consumed
inputs are relevant. BENIGN_AUTOMATION_MOVE preserves unchanged implementation
evidence; release-tree evidence still needs the bounded composed-tree check.
Optional `--evidence evidence.json` evaluates reuse against the candidate SHA
and declared dependency coverage. No existing CI gate is bypassed.

The same preflight refuses overlapping branch/main changes to generated
`CSVs/`, `exports/`, `data/` and model-registry artifacts. Resolve through
canonical generators/source authority; never blindly select ours/theirs.
This guard reports conflicts and returns nonzero; the CLI does not perform
merges or enforce external Git commands it does not own.

A dirty candidate or unobserved/mismatched GitHub head also returns nonzero.
Verified work requires a full SHA matching its expected candidate, and
abandoned work never satisfies a prerequisite. Supersession needs a replacement
dependency rather than silently treating the old requirement as fulfilled.

Observed main-writing automation includes the two-hour production IDP Show
timer (`deploy/idpshow_fetch_and_push.sh`, minute 32 UTC), scheduled-refresh (two-hour source
refresh and freshness stamps), Hill refit evidence, weekly narratives and
Sharp production verification. Other schedules include public-league warmup,
production smoke, health checks and source audits. No workflow is changed by
this campaign. Workflow inventories and provenance must be refreshed when
classifying a real movement.

## Verification and Continuity

Run `python -m pytest tests/steward tests/docs -q`, then the repository Ruff
contract. Use fresh-process state tests plus independent fresh-context review.
A different model retrieves durable evidence; hidden model state is never
transferred. A compact handoff is generated by `brief`, and the next agent
must independently inspect current HEAD/main and acceptance gates.

Historical material reused: #1318's canonical runReceipt shape, unknown-cost
semantics and report-only principle. Its branch was not merged wholesale.
The current store/router have explicit concurrency, supersession, fallback
and dependency contracts absent from that prototype.
