# Runtime Controls

Canonical conditional policy routed from `docs/AGENT_OPERATING_SYSTEM.md`.

### Runtime steering, pending work, and capability negotiation

When the active model/runtime supports long-running or asynchronous execution, treat those capabilities as explicit orchestration primitives rather than pretending every tool call is blocking.

**Capability negotiation**
- Establish the actual runtime/model capabilities before depending on them.
- Do not assume a capability exists merely because another model, API surface, or recent release supports it.
- If a capability is unavailable, degrade to the simpler supported path instead of inventing a compatibility shim that changes semantics.

**Pending asynchronous work**
- Give every pending tool/subtask a stable identity and explicit state.
- Continue only work that is genuinely independent of the pending result.
- Rejoin the dependency by identity when the result arrives; never guess which result belongs to which call.
- A pending result that times out, fails, or is cancelled becomes a normal routable failure state, not a silent omission.

**Mid-run steering**
- Treat a steering message as an amendment to the active goal/constraints, not automatically as a brand-new task.
- Preserve completed work that still satisfies the amended goal.
- Cancel or reroute only branches invalidated by the new instruction.
- Re-run affected acceptance checks when a steering message changes the criteria for success.

**Dynamic reasoning effort**
- When the runtime supports changing reasoning effort without rebuilding the prompt/history prefix, prefer that mechanism over rewriting earlier accepted context.
- Increase effort for a newly difficult subproblem and reduce it again for routine follow-ups when justified.
- Record a material effort change in the run trace when it affects cost/latency or explains a routing decision.

The durable rule is **preserve state, steer narrowly, and make pending dependencies explicit**. Do not copy vendor-specific API syntax into the core operating system.

