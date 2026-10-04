# AI-agent ecosystem implementation campaign

**Status:** IN PROGRESS — no unit is production verified by this record.
**Owner directive:** 2026-10-03 implementation request; research issue #1628 and research PR #1629.
**Agent-OS-Receipt:** `cdca1dca8385f70c0989302dece8d1bd4ce4843c`.

This is the campaign's dependency and evidence map, not a second product or
implementation authority. `docs/EXECUTION_PLAN.md` remains the canonical
repository authorization ledger. The owner's new directive authorizes the
bounded engineering capabilities below through normal claims, review, CI,
integration, deploy and production proof. It does not authorize paid services,
methodology promotion, source activation, autonomous merge/deploy, or broader
production permissions.

## Current-main reconciliation

- Base inspected: `f595c5a0bb106554e96cc7b26b53d1312f05a7dd`.
- Week 1 completion contract: 30/30 literal `VERIFIED` at session start.
- The research document is still on open PR #1629, not on `main`. Its findings
  are candidate evidence; live files and current claims decide each unit.
- PR #1627 owns `docs/OWNER_REQUESTED_TODO.md`; PR #1513 also changes that
  ledger and `docs/EXECUTION_PLAN.md`. The compact owner-intake pointer and
  execution-plan section are queued for reconciliation after those claims clear.
  Their absence here is **partial authority capture**, not a claim of completion.
- Open Dependabot PRs #1506 and #1508 change `requirements.txt`; their exact
  dependency changes must regenerate the locks before either can integrate.

## Dependency order and ownership

| Unit | Canonical owner to extend | State | Required proof |
|---|---|---|---|
| Exact Python dependency lock | `requirements.txt`, `requirements-dev.txt` | IN PROGRESS | Hash-checked lock, Windows/Linux install, CI/deploy parity, drift sabotage |
| Tested artifact and production identity | `deploy/`, `.github/workflows/deploy.yml`, `src/api/build_identity.py` | IN PROGRESS — CI package and draft frontend cutover; no production proof | CI digest, exact deploy, served fingerprint, rollback |
| Typed API pilot and frontend parity | `server.py`, `src/api/`, existing frontend client | IN PROGRESS — `/api/leagues` pilot plus generated parity; CI/production pending | Public/private schema tests, OpenAPI, deterministic type parity |
| Application trace and SLOs | Existing API/log/performance owners | IN PROGRESS — `/api/leagues` trace pilot; source spans and SLOs pending | Correlated route and source evidence, privacy, failure isolation |
| Steward spans, eval bridge, routing scorecards | `src/steward/`, `agent-evals/` | IN PROGRESS — draft span, receipt bridge, scorecard and trace-behavior PRs; context command budget counts in next unit; no integration proof | Real run artifact, exact-revision grading, challenger only |
| Optional typed decision advisor | Existing Steward router/evals | SHADOW PORT IN PROGRESS — offline task-profile comparison only; no provider, labeled corpus, calibration or active routing | Simple baseline, held-out task labels, per-family calibration and risk/coverage before any advisory use |
| Class-B executor and isolation | Existing Steward controller/contracts | PROBE IN PROGRESS — fixed-container boundary only; no worker or command policy | Denied path/command/network/credential tests; branch-only PR |
| Action receipt integrity | Existing Steward store/controller | RECOVERY IN PROGRESS — SQLite/JSONL mirror repair on retry; no independent cryptographic anchor | Append-failure recovery, conflict/truncation refusal, exact source mapping |
| Browser exploration and eval corpus | Existing Playwright and `agent-evals/` | PARTIAL — public browser spot check and two incident cases; no durable exploratory verifier | Structured findings plus deterministic assertions |
| Final reconciliation | Canonical docs, CI, deploy and production evidence | NOT STARTED | Exact merged and served identity; unresolved debt |

No new generic orchestration framework, vector memory, generic feature store,
MCP conversion, paid collector/sandbox, or self-promoting routing is planned.
Domain methodology and production permissions remain with their current owners.

On 2026-10-04 a read-only Playwright CLI spot check opened production `/league`
at desktop and 390×844 mobile widths. The Home data rendered, and selecting
Trades on mobile reached `/league?tab=activity` with a populated Trade activity
panel. The browser logged a `favicon.ico` 404 and a CSS preload warning. This
single visit is not a regression suite or proof for the unmerged campaign; the
existing production E2E workflow and deterministic journey assertions remain
the browser acceptance path. A full Trades accessibility snapshot was about
85,000 output tokens, reinforcing the need for targeted browser queries and
bounded evidence summaries rather than bulk DOM context.

## Engineering applicability

For the dependency unit: reproducible artifacts and supply-chain control are
`APPLY_NOW`; existing manifest and npm lock are `ALREADY_COVERED` foundations.
Typed API, tracing, evals and capability isolation are separate authorized units,
not implied changes to this lock PR. Product valuation, ranking, DFS and source
methodology changes are `NOT_RELEVANT` to the lock implementation.

## First unit evidence still needed

- Verify a clean Windows installation and an Ubuntu CI installation from the
  committed hashes.
- Reconcile all Python installing workflows, including `scheduled-refresh.yml`
  after PR #1627 releases it.
- Review exact package changes against current production environment.
- Merge through the normal exact-head gate, deploy, and inspect the served SHA.
  Build artifact identity remains a separate dependent unit.
