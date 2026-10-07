# Product Plan — Start Here

The canonical product/roadmap front door for **Risk It To Get The Brisket** is:

**[`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md)**

For current authorized execution order — **the only record that says what may be built right now** — read:

**[`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md)**

---

## Current position, in one line

**The current authorization is exactly the set of dated owner directives in `docs/EXECUTION_PLAN.md`
§0 — read it; that file is the only record that authorizes implementation.** As of 2026-10-07 that set
leads with the repository stabilization / truth-reconciliation campaign and otherwise covers the
Calculator completion campaign with the always-parallel Premium UI lane, Schedule Intelligence, DFS, the
Rookie Auction Room (mock-first), Adaptive Learning / Valuation Trust, Signals and performance work.

*Historical (kept for traceability):* the B-Series is complete and the B→C gate was CLEARED by explicit
owner approval; C1A units 1–6 are closed (C1-U6 closed at its owner checkpoint 2026-08-16; C1-U5 merged
as #876 on 2026-08-17). This line previously read "today: `C1-U6`, with `C1-U5` deliberately deferred".

## The canonical set, in reading order

| Question | Record |
|---|---|
| What are we building, and which record wins? | [`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md) |
| What is the completion standard for the C-Series? | [`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`](docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md) |
| **What is in scope, who owns it, what phase, what proves it done?** | [`docs/C_SERIES_SCOPE_MANIFEST.md`](docs/C_SERIES_SCOPE_MANIFEST.md) |
| Where did a given requirement go? | [`docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md`](docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md) |
| Does a feature exist / is it defective? | [`docs/OWNER_FEATURE_INVENTORY.md`](docs/OWNER_FEATURE_INVENTORY.md) |
| What is the detailed behaviour? | [`docs/OWNER_PRODUCT_BACKLOG_SPEC.md`](docs/OWNER_PRODUCT_BACKLOG_SPEC.md) + the feature specs |
| **What am I authorized to implement right now?** | [`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md) |
| What does a CE identifier mean? | [`docs/CE_REGISTRY.md`](docs/CE_REGISTRY.md) |
| Which records are active, supporting, historical or superseded? | [`docs/PLANNING_DOCUMENT_STATUS.md`](docs/PLANNING_DOCUMENT_STATUS.md) |
| Where does a new owner instruction go? | [`docs/OWNER_REQUESTED_TODO.md`](docs/OWNER_REQUESTED_TODO.md) — the live intake ledger |
| Why is the plan shaped this way? | [`docs/POST_B_RECONCILIATION_2026-08-14.md`](docs/POST_B_RECONCILIATION_2026-08-14.md) |

---

Do not select implementation work directly from old TODOs, addenda, competitor research,
`UNIMPLEMENTED_BACKLOG.md`, `docs/ROADMAP-competitor-parity.md`, `docs/status/*`, or
`docs/master-site-audit/NEXT_STEPS.md` / `REPAIR_ROADMAP.md`. Their durable requirements are preserved and mapped
in the Scope Manifest; the documents themselves are subordinate to the hierarchy defined in the Master Product
Plan.

**Being listed in the Scope Manifest is not authorization either.** Scope and authorization are separate records
on purpose.
