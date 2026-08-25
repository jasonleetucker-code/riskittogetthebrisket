# V1-45 — L4 production verification recipe (`finalRosterSimulation` render)

**Row:** `V1-45` Trade calculator · inv 2.1 · **required level L4** · status
`IMPLEMENTED_UNVERIFIED` · owner note *"ALREADY COMPLETE — VERIFY ONLY"*.
**No V1 status column edited. This lane reaches L2; L4 needs a deployed SHA.**

> **Scope, and the canonical V1-45 recipe.** The broader V1-45 L4 recipe is
> **`docs/trade/V1_45_TRADE_CALCULATOR_L4_EVIDENCE_RECIPE.md`** (#1082, Trade Intelligence
> lane) — it covers all three canonical blocks `/api/trade/simulate` stamps plus the Analyze
> Trade surface, and it is the document to run for the row as a whole. **This file does not
> replace it and is not a second V1-45 recipe**; it is the verification for the ONE repair
> below, and it exists separately only because the repair shipped after that audit.
>
> The two agree on the measurement, independently: #1082 measured `finalRosterSimulation` at
> **0 frontend consumers, not rendered on `/trade`** against `main` @ `131abf9f`; this lane
> measured the same thing against `main` @ `b857d07c0`. #1082 is the **audit**; this is the
> **repair**. Whoever runs the L4 pass should run #1082's recipe and use §Recipe here for the
> final-roster block specifically.
>
> #1082 also records a gap this lane did **not** touch: `POST /api/trade/analyze` (V1-43) has
> zero frontend callers and no Next bridge route. Different row, different owner.

---

## What changed, and what it is not

`POST /api/trade/simulate` has published `finalRosterSimulation` since **V1-42**
(`VERIFIED`) — the lineup **re-solved** over the post-trade, post-cleanup roster, with Team
Strength before/after. Measured on `main` `b857d07c0`: **4** references in
`src/api/trade_simulator.py`, **0** anywhere in `frontend/`. The UI never asked.

This wires it into `SimulationPanel` as **pure display**. It is *not* a second copy of the
`rosterCapacity` block that V1-45's earlier pass (#1025) already renders:

| block | answers |
|---|---|
| `rosterCapacity` | **who must go** — forced releases, their cost, upper-bound flag |
| `finalRosterSimulation` | **what the roster becomes once they have** — who gets promoted into a vacated seat, which needs close *and* which open, the Team Strength delta |

Releasing the cheapest legal body can vacate a FLEX seat and promote a player the trade never
mentioned. That is the fact this block carries and nothing else on the page did.

## Four states, not three

| state | shape | renders as |
|---|---|---|
| **populated** | `available: true` + `strengthBefore/After`, `strengthDelta`, `promotions`, `displacements`, `needsFixed`, `needsCreated`, `cleanupApplied`, `cleanupIsUpperBound` | the "Final roster" section |
| **capacity_uncertain** | `{available: false, unavailableReason: "capacity_uncertain"}` | *"Not simulated — taxi occupancy is unknown… see Roster capacity above"* |
| **unavailable** | `{available: false, unavailableReason: "starter_slots_unresolved"}` **or** `{unavailable: "<ExcType>"}` (no `available` key) | *"Not simulated — …"* naming the reason |
| **absent** | key not on the response (no resolved team) | **nothing at all** |

The predicate is `available === true` — deliberately **stricter** than
`analyze_trade.py::_roster_impact_dimension`, which uses `.get("available", True)` and so
defaults a *missing* key to available. On the exception shape that backend predicate falls
through and later reports `team_strength_not_stamped` rather than the real exception: same
end state, imprecise reason. **Observed, recorded, not fixed here** — different file,
different (already `VERIFIED`) row, unchanged outcome.

## Recipe

Everything below runs against a **deployed SHA**. Record it first; a run against an unknown
build proves nothing.

1. **Record the deployed SHA.**
   `curl -s https://<host>/api/status | jq -r '.deployedSha // .version // .'`

2. **Absent renders nothing.** Load `/trade` signed in, build a trade **without** selecting a
   team, run the simulation. Expect the "Impact on …" panel **with no "Final roster" section
   and no "Not simulated" line**. Confirm the raw response has no `finalRosterSimulation` key:
   ```bash
   curl -s -b "<cookie>" -X POST https://<host>/api/trade/simulate \
     -H 'Content-Type: application/json' -d '<the same body the page sent>' | jq 'has("finalRosterSimulation")'
   ```
   Expect `false`. *(An absent block rendering an error would be the defect.)*

3. **Populated — the field-for-field check.** Select a team **at its roster cap** so the
   cleanup is non-empty (`dynasty_main` held six of twelve rosters at 58 on 2026-08-18, so
   this is reachable) and build a trade that forces a release. Then compare the rendered
   section against the raw response:
   ```bash
   curl -s -b "<cookie>" -X POST https://<host>/api/trade/simulate \
     -H 'Content-Type: application/json' -d '<body>' \
     | jq '.finalRosterSimulation | {available, strengthDelta,
            before: .strengthBefore.total, after: .strengthAfter.total,
            promotions: [.promotions[].name], displacements: [.displacements[].name],
            needsFixed, needsCreated, cleanup: (.cleanupApplied|length), cleanupIsUpperBound}'
   ```
   Every rendered number and name must match **exactly**. In particular:
   * **"Strength change" must equal the response's `strengthDelta`** — not
     `strengthAfter.total − strengthBefore.total` recomputed. They normally agree, which is
     why this is checked against the stamped field rather than by arithmetic.
   * the release **count** appears here; the **names** appear only in the Roster capacity
     block above (one fact, one surface).

4. **Upper bound.** If `cleanupIsUpperBound` is `true`, the page must say the final roster is
   **one of a range**, not a determined set.

5. **`capacity_uncertain`.** Repeat on a league with unknown taxi occupancy (`dynasty_new`
   carries 5 taxi slots and no source in this codebase says who occupies them), with a trade
   that pushes the roster to its cap. Expect `requiresDrops: null` on `rosterCapacity` and the
   *"taxi occupancy is unknown"* line — **distinct copy** from the generic unavailable, and it
   must point at the Roster capacity block.

6. **Missing is never zero.** If the response carries `unpricedIncoming` or
   `outgoingNotFound`, both must be disclosed on the page rather than silently dropped.

7. **Nothing else moved.** The existing Roster capacity block, the before/after/change tiles,
   the per-position grid, the roster-fit verdict and the equity line all render as before.

8. **Record** the SHA, both raw responses and the rendered comparison into
   `docs/master-site-audit/evidence/V1-45/`.

## Local evidence already recorded (L2)

* `frontend/__tests__/components/trade-simulation-panel-final-roster.test.jsx` — 15 tests
  across all four states, both refusal shapes, both need directions, upper bound, cleanup
  count, and the unpriced/not-found disclosures, plus a non-vacuity guard so "renders nothing"
  cannot pass because nothing rendered.
* **Mutation proof — three, each on a different load-bearing property:**

  | mutation | result |
  |---|---|
  | delete the render block (literal pre-fix state) | **14 of 15 RED** |
  | read `strengthAfter − strengthBefore` instead of the stamped `strengthDelta` | **1 RED** — the fixture stamps `before 100`, `after 500`, `strengthDelta 7`, so only a *reader* passes |
  | `available === true` → `available !== false` | **1 RED** — the `{unavailable: "ValueError"}` shape, which has no `available` key |

  All restored GREEN; `tests/…-roster-capacity.test.jsx` (the sibling block) unaffected at
  22/22 across both files.
* **Backend untouched**: no `.py` file in the diff.
