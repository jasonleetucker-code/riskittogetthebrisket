# Graph Workflows

Canonical conditional policy routed from `docs/AGENT_OPERATING_SYSTEM.md`.

### Graph construction rules

Use a graph only when the work is genuinely wide. A graph buys concurrency and breadth; it does not create better judgment by itself.

**Node contracts**
- one bounded job per node;
- explicit inputs passed in rather than assumed;
- a fixed/validated output shape whenever another node consumes the result;
- explicit failure/unknown states instead of free-text ambiguity.

**Fake-edge test**
For every proposed dependency, ask: *does the downstream node actually consume the upstream result, or do they share a mutable/rate-limited resource that requires ordering?* If neither is true, the edge is fake and the jobs should usually run in parallel.

**Routable failure states**
Treat failure as structured data when a graph must continue safely.

- define named outcomes that downstream routing can branch on instead of relying on an agent to interpret free-form error prose;
- distinguish at minimum success, retryable failure, terminal failure, blocked/external dependency, and unknown when those states materially change routing;
- preserve the evidence/error payload alongside the named state;
- route only on states the producing node is actually authorized and able to establish;
- do not convert an exception, missing result, or timeout into success merely so the graph can continue.

A graph is more resilient when a failed node can be bypassed, retried, or escalated explicitly rather than crashing the whole workflow or being silently omitted.

**Graph specification contract**

Before implementing a nontrivial graph, write the graph contract in structured form. At minimum declare:

- `GOAL` — what must exist when the graph succeeds;
- `INPUT_STATE` — structured state entering the graph;
- `PARALLEL_WORK` — units proven independent enough to fan out;
- `CRITICAL_PATH` — longest unavoidable dependency chain;
- `VERIFIER` — who/what can reject;
- `FAILURE_DOMAIN` — blast radius when each important node fails;
- `HUMAN_GATE` — consequential transitions requiring human approval;
- `FROZEN_RULES` — constraints no optimizer/agent may rewrite;
- `OBSERVABILITY` — metrics/receipts required to understand the run;
- `STOPPING_RULE` — explicit convergence/budget exit condition.

The graph contract should be easier to audit than a collection of prompts. Prompts optimize nodes; the graph specification controls the system.

**Transition contracts and approval guards**

Edges are not merely arrows. A meaningful transition should identify the data/state that crosses it and, when needed, the guard that must be true before the transition is reachable.

- Put machine-checkable schemas at important handoff boundaries.
- For irreversible/consequential actions, model human approval as a **guard on the transition**, not as a conversational request inside a worker prompt.
- If the approval record is absent, the protected transition is unreachable.
- Do not allow a worker to rewrite, summarize away, or self-satisfy its own approval guard.
- Keep approval evidence durable enough for later audit.

**Quorum-aware fan-in**

The default fan-in contract is **all required upstream results must arrive**.

A graph may continue with fewer only when the graph specification explicitly defines a quorum/partial-coverage rule in advance. When quorum is allowed:
- record expected count, received count, and missing identities;
- preserve the coverage limitation in the downstream artifact;
- never reinterpret silent worker loss as intentional quorum;
- never call a partial result complete unless the contract explicitly defines that state as complete.

**Critical-path and graph observability**

Optimize wall-clock time by the critical path, not by raw node count.

For material graphs, measure the graph rather than only reading chat transcripts. Useful metrics include:
- critical-path latency;
- per-node latency and failure rate;
- retry/escalation counts;
- verifier rejection rate;
- expected-vs-received fan-in coverage;
- reducer/compression ratio before synthesis;
- tool/model cost where measurable;
- halt/budget stop reasons.

Observability should make it possible to tell whether added parallelism improved independent coverage or merely added coordination cost.

**Default wide-work pattern: fan out -> reduce -> verify -> synthesize**
- fan out only independent work;
- reduce deterministically with ordinary code for dedupe/count/sort/schema checks where possible;
- verify findings with an independent fresh context;
- synthesize only what survived verification.

**Verifier independence**
A worker must not grade its own work through the same accumulated context. Give the reviewer the artifact/evidence it needs, not the worker's persuasive history. Use different lenses when useful: correctness, freshness, provenance/source reality, auth/privacy, or acceptance-contract compliance.

**Hidden edges**
Prompt independence is not enough. Two nodes are not independent if they:
- edit the same file/branch/worktree;
- mutate the same database/state/artifact;
- compete for a rate-limited external API;
- depend on the same exclusive credential/session;
- otherwise share a resource whose concurrent use changes correctness.

Treat shared-resource conflicts as real edges or isolate the workers.

**Fan-in completeness and context safety**
Every merge node must know how many upstream results it expected. Missing outputs make the merged result incomplete; never silently synthesize a partial set and call it complete. For very large fan-in, aggregate in layers while preserving provenance and coverage instead of dumping all raw outputs into one context.

**Anchors**
Graphs must terminate in evidence that agents cannot talk themselves around: tests that actually ran, exact-head CI, production probes, authoritative source data, fixed contract counts, real artifacts, or owner-approved methodology. Do not let an optimizer weaken the anchor just to make the graph green.

**Cost and width controls**
Start with a bounded fan-out, explicit caps, and measurable stop conditions. Expand only when the first scoped run proves useful. A discovery graph should have a convergence rule (for example, no new verified findings across successive rounds) plus a hard total-agent/action cap.

**When not to graph**
Prefer one agent/loop for small fixes, tightly sequential work, high-coupling edits, or early exploration where the problem shape is not yet known. If the fake-edge test finds no independent jobs, there is no useful graph to build.

