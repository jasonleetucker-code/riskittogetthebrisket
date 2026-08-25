# Dispatch records — current authority and historical provenance

**Owner correction, 2026-08-22:** there is **no active Claude 7 lane and no active Claude 7 dispatcher identity**.

The current owner map is the one stated by the owner and reflected by the active execution program:

- Claude 1 — Roster Intelligence
- Claude 2 — Trade Intelligence
- Claude 3 — Season / Scoring / BDVM
- Claude 4 — Market / FAAB / verification
- Claude 5 — Integration Authority / merge desk / V1 ledger / production verification
- Claude 6 — Premium UI / frontend
- Claude 8 — Source Acquisition + Cross-Position Bridge

The gap at number 7 is intentional. It is **not** an available product lane and must not be assigned work.

## What this directory is

`docs/claude-dispatch/` contains durable traffic-control history. Older snapshots were written when the coordination record called itself "Claude 7 (Lane Dispatcher)". That identity is **historical and superseded**. Those older strings are preserved only as provenance for decisions made at the time; they do not authorize a current lane, agent, owner, merge authority, or V1-status authority.

Current coordination records must describe themselves as an **independent traffic-control/dispatch record with no lane number and no Claude identity attached**. They may observe and route work, but they do not implement product code, merge, or promote V1 rows.

## Authority order

1. `docs/VERSION_1_COMPLETION_CONTRACT.md` owns the V1 numerator, denominator, status, and required verification level.
2. `docs/EXECUTION_PLAN.md` owns execution authorization and current lane ownership. Its later owner-authorized lane map stating that no Claude 7 lane is created supersedes the earlier historical explanation that treated "Claude 7" as a dispatcher identity.
3. `CLAUDE.md` and the product/owner records own canonical product semantics.
4. Files in this directory are derived coordination records. If they disagree with the records above, **this directory is wrong**.

## Retired live queue

`V1_CLOSABILITY_QUEUE.json` is now a small non-authoritative pointer rather than a stale second V1 queue. The last pre-correction snapshot is preserved at `history/V1_CLOSABILITY_QUEUE_2026-08-20.json` for audit provenance.

Historical references to "Claude 7", "Lane 7", or "Lane Dispatcher" may remain in dated evidence, old PR records, or archived snapshots only when read as historical/superseded text. They must never be used as a present-tense owner assignment.
