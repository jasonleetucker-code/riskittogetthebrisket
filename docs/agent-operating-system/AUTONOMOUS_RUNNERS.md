# Autonomous Runners

Canonical conditional policy routed from `docs/AGENT_OPERATING_SYSTEM.md`.

## 6. Autonomous-loop safety envelope

The rules below apply when this repository ever owns an **unattended, recurrent, or long-lived agent runner**. They do not by themselves authorize one.

A loop runner is an execution system, not a prompt. The scheduler/engine wakes the model; the model does not get to decide when it wakes itself.

### Contract split

Keep two layers distinct:

- **committed contract** — repository-tracked permissions, forbidden actions, required verification, receipt schema, and immutable safety boundaries;
- **local operator overrides** — machine/operator-specific settings such as tighter budgets, runtime windows, or local tool paths; ignored by git and unable to weaken committed safety boundaries.

A local override may make a run *more restrictive*. It must not silently grant authority the committed contract denies.

### Hard runtime limits

Every unattended loop must declare and enforce, outside model prose:

- wall-clock timeout;
- maximum actions/tool calls or iterations;
- spend/token budget when measurable;
- maximum parallel width;
- retry budget;
- allowed schedule window;
- explicit denylist for destructive or out-of-scope actions.

Exhausting a budget is a truthful stop condition, not a reason to quietly enlarge the budget.

### One execution gateway

For a bespoke repo-owned autonomous runner, keep model invocation behind one narrow gateway/call site so:

- model/provider swaps are centralized;
- budgets/timeouts are enforceable;
- receipts/traces capture every invocation;
- safety/denylist checks cannot be bypassed by a second hidden call path.

This rule does not require ordinary interactive Claude Code/Codex usage to route through a custom wrapper.

### Run state and resumability

An unattended run should externalize state rather than rely on model memory:

- **append-only run receipt** — one immutable record per run/shift;
- **append-only trace** — timestamped actions/results sufficient to reconstruct what happened;
- **checkpoint** — minimal resumable state for the next run;
- **budget ledger** — cumulative consumption for the current policy window.

A restart resumes from the last valid checkpoint only after re-running preflight against current repo state. Never assume yesterday's branch, PR, credentials, or acceptance state is still current.

### Verification and grading

Use the sequence:

`preflight -> act -> verify -> guard -> grade -> receipt`

- **verify** should prefer executable pass/fail evidence such as exit codes, tests, schemas, exact-head CI, or production probes;
- **guard** checks policy boundaries independently of task success;
- **grade** is performed by an independent reviewer/context when judgment is still required;
- **receipt** records the outcome, evidence, budgets consumed, stop reason, and next checkpoint.

A run that cannot produce its required receipt is incomplete.

### Emergency halt

Any repo-owned unattended scheduler must have a simple external **halt sentinel / kill switch** that is checked:

1. before a run starts;
2. before consequential side effects;
3. between bounded work units.

When HALT is present or unreadable in a fail-closed configuration, scheduled autonomous work refuses to start/continue. The model cannot remove or override the halt itself unless an owner-authorized recovery procedure explicitly grants that action.

### Report-only, assisted, and autonomous modes

Do not blur these modes:

- **report-only** — may inspect and recommend, no repository/product mutation;
- **assisted** — may make bounded reversible changes but stops at defined approval/consequence boundaries;
- **autonomous** — may execute the explicitly committed contract without synchronous approval.

Each scheduled loop declares its mode. Upgrading a loop to a more permissive mode is a product/operations decision and requires owner authorization.

### Long-term autonomous site-steward target

The owner-approved long-term direction is recorded in `docs/AUTONOMOUS_SITE_STEWARD_VISION.md`.

The target is a **bounded, recurrent fantasy-site steward** that can continuously discover evidence, monitor source health, research new public sources and product ideas, inspect permitted media/transcripts, detect defects/performance regressions, create challenger experiments, build prototypes, repair dependency-ready defects, and keep the site useful with minimal owner attention.

This is a destination and architecture contract, **not activation** and not permission to bypass existing product/methodology/source-promotion/deploy gates. Ordinary feature sessions should not preload the vision document; read it when designing or operating unattended/recurrent stewardship.

### Activation gate

This section is **design policy, not activation**.

Before deploying any new unattended repo-owned runner, require:
- explicit owner authorization for its contract and mode;
- tests proving budgets/timeouts/denylist/halt behavior;
- a dry run;
- receipt/trace inspection;
- rollback/removal path;
- confirmation it does not create a second canonical owner or bypass existing protected PR/deploy gates.

