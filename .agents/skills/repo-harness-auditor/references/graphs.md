## Graph-spec and transition-guard hygiene

For any nontrivial graph, verify that the workflow has an explicit structured spec covering goal, input state, parallel work, critical path, verifier, failure domains, human gates, frozen rules, observability, and stopping rule.

Also verify:
- important edges have explicit data/state contracts;
- consequential approval is enforced as a transition guard, not only requested in prompt prose;
- protected transitions are unreachable without durable approval evidence;
- default fan-in requires all required outputs unless an explicit quorum was defined in advance;
- quorum runs preserve expected/received/missing coverage in downstream artifacts;
- graph-level observability includes critical-path latency and verifier/failure/coverage metrics;
- adding agents actually reduces critical path or increases independent coverage enough to justify coordination cost.

## Graph-orchestration hygiene

When the harness or a workflow uses parallel agents, audit the topology rather than assuming "parallel" means efficient or safe:

- every node has a bounded input/output contract;
- every edge passes a real dependency or protects a shared mutable/rate-limited resource;
- fake edges are removed;
- hidden edges (same file, worktree, state store, credential/session, API budget) are made explicit or isolated;
- verifier nodes use fresh context and can reject the worker;
- deterministic reduce steps use code rather than model judgment where practical;
- fan-in counts expected vs received inputs and reports partial coverage truthfully;
- large fan-in is layered to avoid context collapse while retaining provenance;
- the graph terminates in external anchors, not agent self-consistency;
- fan-out/agent/cost budgets and stop conditions are bounded;
- the task is actually wide enough to justify a graph.

