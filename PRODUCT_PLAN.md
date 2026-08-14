# Chase Upside — Product Planning Start Here

**Status:** CANONICAL ENTRYPOINT FOR PRODUCT / ROADMAP / FEATURE-DIRECTION WORK  
**Last synchronized:** 2026-08-14

For any material question about what Chase Upside should become, what a feature means, or what work may happen next, use this order:

1. **[`docs/MASTER_PRODUCT_PLAN.md`](docs/MASTER_PRODUCT_PLAN.md)** — canonical long-range product direction, durable product invariants, and document precedence.
2. **[`docs/EXECUTION_PLAN.md`](docs/EXECUTION_PLAN.md)** — the **only** record that authorizes the current implementation sequence / next phase.
3. **[`docs/PLANNING_DOCUMENT_STATUS.md`](docs/PLANNING_DOCUMENT_STATUS.md)** — authority/classification map for every planning, feature, roadmap, handoff, and historical direction document.
4. **[`docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md`](docs/PRODUCT_DIRECTION_SYNC_MANIFEST.md)** — synchronization receipt showing how the active and historical planning layers fit together.
5. Read the relevant detailed owner specification(s) named by the Master Product Plan and Planning Document Status before implementing a feature.

`CLAUDE.md` is the technical operating constitution. It does **not** authorize product work and must defer to the hierarchy above for product direction and sequencing.

## Post-B C-series rule

The eventual C-series is governed by [`docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md`](docs/C_SERIES_REPLAN_AND_COMPLETION_CONTRACT.md), but that contract does **not** authorize starting C early. After B11, Claude must stop, enter Plan Mode, build the exhaustive C Scope Manifest and dependency DAG from the actual post-B repository/product state, obtain owner approval, and only then begin C implementation.

## Historical records

Old TODOs, audit roadmaps, competitor plans, session handoffs, PR prose, and dated feature inventories remain valuable evidence/provenance. They are **not** independent implementation queues. Do not choose work from them merely because a feature or phase name appears there.

If a historical record contains a durable owner requirement that is missing from the active hierarchy, treat that as documentation drift: reconcile it into the active owner backlog/spec layer before implementation.
