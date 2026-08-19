# Trade lane (L2) — V1 rows ranked by distance to `VERIFIED`

> **Speed-run audit, 2026-08-19.** Read-only. Nothing here marks a row
> `VERIFIED` — only Integration does that, and the denominator is untouched.
> Measured against `main e3b387c` (which carries #914) with #922 `1f6a877`
> and #913 `c2153eb` still open.
>
> The contract's own bar is the one applied throughout:
> *"Is the intended production consumer actually using the canonical
> implementation, with truthful data semantics?"* Code existing, a PR existing,
> a PR merging, unit tests passing and CI being green are **each explicitly
> not verification.**

Verification levels, for reference: **L1** RED→GREEN at exact head + green CI
on the merge tree · **L2** L1 plus a measured statement of the effect on the
live board/contract · **L3** L1 plus the named checklist against the deployed
SHA · **L4** L3 plus proof the user-facing surface consumes it.

---

## The ranking

### Tier 1 — merge-gated. Zero further Trade work. **5 rows.**

Every one is implemented, tested RED→GREEN, mutation-proven, and sitting in a
PR that is green and frozen. The hours are already spent; the only thing
between them and `VERIFIED` is Integration merging two PRs.

| row | level | carrier | evidence already in hand |
|---|---|---|---|
| **V1-39** roster capacity / forced drops | L1 | #913 | 58 tests (`test_roster_capacity` 44 + `test_capacity_wiring` 14); unknown cap stays UNKNOWN; unpriced drop stays `null` and is counted separately |
| **V1-44** equalizers rank on the post-VA gap | L1 | #913 | 24 tests; mutations 3/5/7 RED; 4,000 seeded trades — 1,360 misses and 701 lead-flips → **0**, mean residual 1,007 → 50 |
| **V1-37** ONE Value Adjustment, parity proven | L2 | #913 | `ktc_va.py` scores **0 / 40,000** against the JS reference; three duplicate implementations deleted; **board byte-identical** — the L2 measurement is the 0 |
| **V1-36** ONE shared package generator | L2 | #913 | `src/packages/construction.py`; 42 tests; L2 measurement is recorded — the finder's asymmetric search went value-ordered, **20 of the returned top 40 changed**, candidates 8,010 → 10,490 |
| **V1-130** one recommendation-constraint owner | L2 | #929 | same suite; 8/8 mutations RED; **canonical board byte-identical, 1111 rows, 0 moved** — the L2 measurement |

> **CORRECTED 2026-08-19 after owner review on #929.** This tier originally
> listed **V1-34** as a sixth merge-gated row. That was wrong, and the error was
> mine — #929's own docstring already said so.
>
> `V1-34` is *"Untouchable / excluded-player control"* — an operable **user
> control**. #929 delivers the **owner**, not the control:
> `tradeConstraintsByLeague` is READ from `user_kv` at `server.py:7951` and
> **written nowhere** — verified, one read and zero writes across the entire
> repository. So every real user resolves to "nothing configured", which is a
> legitimate answer and not a failure, but it is also not a capability anyone
> can use. Under the contract's own false-green test there is no production
> consumer, because there is no path by which a user configures a protection.
>
> `V1-130` is a different claim — that ONE canonical recommendation-constraint
> owner exists and every generated-trade surface routes through it — and #929
> does discharge that, with the board-inert measurement its L2 bar needs. The
> two rows must stay separated through V1 reconciliation.
>
> The writer seam is `C3-CON-02` / `C3-CON-03`, separate rows, and both are
> explicitly out of scope under the current speed-run rule.

**Rows per hour: unbounded — the numerator is 5 and the remaining Trade
denominator is 0 hours.** Nothing else in this lane comes close, which is why
the dependency train is the whole priority.

### Tier 2 — one reconciliation pass unlocks a **seventh**, and only Trade can

| row | level | finding |
|---|---|---|
| **V1-42** exact before→apply→re-solve→after | L2 | see below |

`C2-SIM-01` is **merged** — `src/roster_intel/simulation.py` landed on `main`
with #914. Its status still reads `NOT STARTED`, which is wrong about the code
and right about the thing that counts:

> **`simulate_roster_change` has ZERO consumers on `main` today.**
> `git grep` finds it in exactly two files — its own module and the package
> `__init__` that re-exports it. It is reachable from **no HTTP route, no
> engine, no surface.**

So it cannot be `VERIFIED` under the false-green test however green its own
tests are — it is the exact precedent the contract cites first ("the exact
lineup solver existed while the normal overlay discarded its output").

What gives it a consumer is **W3 of #913's reconciliation** —
`simulate_final_legal_roster`, which calls it and hangs off
`/api/trade/simulate`, `/api/trade/finder`, `/api/trade/suggestions` and both
`/api/angle/*`. A Roster-lane row that only the Trade lane can close, in the
same pass that closes the six above.

### Tier 3 — Roster-gated, not Trade-gated

| row | level | gate |
|---|---|---|
| **V1-40** droppability / cut-candidate consolidation | L2 | #922. `pool_cut_ladder` is the consolidation and #922's F8 fixed the auction-rookie leak (measured `WR 2036 → 1519`, −25.4%); defaults now agree 12/12 with the draft surface on both `waiverValues` and `cutLadder` |

### Tier 4 — real implementation remains

| row | level | what is actually missing |
|---|---|---|
| **V1-34** untouchable / excluded-player control | L1 | the storage / control seam. The owner is in #929; nothing writes `tradeConstraintsByLeague`, so no user can configure a protection. `C3-CON-02` / `C3-CON-03` |
| **V1-41** "Use Team Context" toggle, ON by default | L1 | everything. `#842`'s contract exists as a spec; no `teamContext` field is parsed anywhere |
| **V1-43** Analyze Trade canonical recommendation | L1 | everything but the design. The contract is drafted (`docs/trade/V1_43_ANALYZE_TRADE_REHEARSAL_CONTRACT.md`) and names three dimensions that have no canonical owner yet, so its honest V1 ceiling is `confidence: medium` |

V1-41 should precede V1-43: §6 of the Analyze Trade contract is `#842`'s mode
contract applied, and writing V1-43 first would mint a second copy of it.

### Tier 5 — blocked on evidence this environment cannot produce

| row | level | blocker |
|---|---|---|
| **V1-97** historical trade replay leaks no hindsight | L2 | the repair is **in #913** (four hindsight paths closed, 17 frontend tests rewritten), but its L2 measured statement — how many `/trades` rows move from "Stable" to "Aging unknown" — needs the league's real trade list plus rank history. Neither exists outside prod: no `data/temporal_ledger.sqlite`, no `rank_history.jsonl`, no `data/retention/`. Same `BLOCKED-EXTERNAL` class as V1-15 / V1-16. **Merging #913 gets this to L1; the L2 statement needs a deployed run.** |
| **V1-45** Trade calculator | **L4** | L4 is the most expensive bar in the contract — production-consumer proof against a deployed SHA. Merged and shipped; unreachable from here |

---

## Consolidated answer

**Five rows convert on merge alone. A sixth converts on the one
reconciliation pass. Two more are Roster-gated. Only two need real building,
and two are evidence-blocked.**

The fastest path to V1 VERIFIED throughput in this lane is therefore not to
build anything:

```
#922 merges → #913 reconciled ONCE → #913 merges → #929 rebased → #929 merges
   ↓                ↓                     ↓                          ↓
  V1-40           V1-42               V1-36/37/39/44            V1-130
                                       (+V1-97 at L1)
```

Eight rows move on that sequence. `V1-34`, `V1-41` and `V1-43` are the Trade
rows where writing code is the bottleneck, and all three are correctly behind
it — `V1-34` needs only the storage / control seam, since #929 already supplies
the owner it would write to.
