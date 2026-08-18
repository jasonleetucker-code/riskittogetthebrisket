# Owner Feature Addendum — FLEX Starter Assignment Before Team Strength Reserve Depth

**Date:** 2026-08-18  
**Status:** BINDING OWNER DECISION / TRACKING SPEC  
**GitHub tracking:** #899  
**Scope:** Team Strength, meaningful-roster selection, roster-value breakdowns  
**Authorization note:** This records the requirement while the post-merge audit freeze is active. It does **not** by itself authorize forward C2 implementation.

---

## 1. Supersession

This addendum supersedes any wording that selects a multiplied dedicated positional core first and only afterward fills FLEX from the leftovers.

The correct order is:

> **actual starter assignment first, including FLEX/SF; reserve/depth selection second.**

FLEX is a real starting slot and must influence which players belong to the meaningful roster/value pool.

FLEX does **not** need to become a separate sortable Team Strength position or UI column.

---

## 2. Binding selection order

For a league with meaningful-core multiplier `M`:

1. Read the league's actual lineup configuration.
2. Solve the actual starting lineup using the canonical legality-aware assignment machinery.
3. Fill dedicated starter slots first (QB/RB/WR/TE and IDP dedicated slots as applicable).
4. Fill ordinary offensive FLEX starter slots from the highest-valued remaining legally eligible players.
5. Fill Superflex using its actual legal eligibility; do not treat SF as ordinary RB/WR/TE FLEX and do not double-count its assigned player.
6. Fill IDP FLEX starter slots from the highest-valued remaining legally eligible defenders when the league has them.
7. Remove **all actual starters**, including FLEX/SF/IDP FLEX starters, from the remaining player pools.
8. Only then select reserve/depth players.
9. Every player may contribute to the meaningful roster **at most once**.

A player who is the third running back or fourth wide receiver by native-position rank may therefore be a FLEX starter rather than positional depth. If that player is consumed by FLEX, the next remaining player at that native position becomes the first reserve candidate.

---

## 3. Reserve demand

The currently intended V1 multiplier remains `M = 1.5` as a **PRIOR/champion under validation**, unless later calibration or owner direction supersedes it.

For a dedicated position `p`:

```text
reserve_demand(p) = ceil(M × dedicated_starter_slots(p)) - dedicated_starter_slots(p)
```

This reserve demand is applied **after** actual starter assignment.

For ordinary offensive FLEX:

```text
flex_reserve_demand = ceil(M × offensive_flex_starter_slots) - offensive_flex_starter_slots
```

Those reserve FLEX players are selected from the highest-valued remaining legally FLEX-eligible players after dedicated starters, actual FLEX starters, SF starters, and already-selected dedicated reserves are accounted for in the canonical assignment/selection procedure.

IDP FLEX uses the analogous rule within its legal defensive eligibility pool.

The implementation must use global legality-aware selection rather than independent greedy lists that can assign the same player twice.

---

## 4. Example

League lineup:

```text
2 RB
3 WR
2 TE
2 FLEX
```

with `M = 1.5`.

### Actual starters first

```text
RB: RB1, RB2
WR: WR1, WR2, WR3
TE: TE1, TE2
```

Now compare the best remaining FLEX-eligible players. If the top two are:

```text
RB3
WR4
```

then:

```text
FLEX1 = RB3
FLEX2 = WR4
```

RB3 and WR4 are starters. They are removed from their native-position reserve pools.

### Then reserves

```text
RB reserve demand = ceil(1.5 × 2) - 2 = 1
WR reserve demand = ceil(1.5 × 3) - 3 = 2
TE reserve demand = ceil(1.5 × 2) - 2 = 1
FLEX reserve demand = ceil(1.5 × 2) - 2 = 1
```

The first RB reserve is therefore the best remaining RB after RB1, RB2, and FLEX-assigned RB3 have been removed; that player may be raw-position RB4.

Likewise, WR4 has already been consumed by FLEX, so the two WR reserves come from the next remaining wide receivers.

---

## 5. Team Strength / UI behavior

FLEX changes the **meaningful-roster population and overall team value**.

It does not have to create a new displayed/sortable Team Strength position.

The normal positional views may remain:

```text
QB | RB | WR | TE | DL/EDGE | LB | DB
```

The fact that a player was selected through FLEX is an internal assignment/diagnostic fact. The value of that starter still belongs to the team and must be included in the overall meaningful-roster Team Strength calculation.

If a later diagnostic view exposes slot assignment, FLEX may be shown there, but this addendum does not require a separate FLEX strength ranking.

---

## 6. Canonical implementation flow

```text
league configuration
→ canonical exact actual-starter assignment
   (dedicated + FLEX + SF + IDP FLEX)
→ remove every assigned starter
→ legality-aware reserve/depth demand
   (dedicated reserve + reserve FLEX)
→ unique meaningful-roster player set
→ meaningful-roster canonical value
→ Team Strength / roster-value breakdown consumers
```

Do not implement page-local or per-position alternatives.

The canonical lineup/assignment machinery established by C2-U1 should be reused rather than rebuilding a greedy selector.

---

## 7. Acceptance criteria

The future implementation is not complete until tests prove:

1. FLEX starters are assigned before reserve/depth selection.
2. A FLEX-assigned RB/WR/TE cannot simultaneously count as native-position depth.
3. Consuming RB3 at FLEX causes the next remaining RB to become the first RB reserve candidate.
4. Consuming WR4 at FLEX analogously shifts the WR reserve pool.
5. `0`, `1`, `2`, and `3+` ordinary FLEX-slot league configurations derive from league settings rather than hard-coded assumptions.
6. Superflex does not double-count a player in ordinary FLEX or QB reserve calculations.
7. IDP FLEX follows the same assignment-before-reserve architecture where configured.
8. Every meaningful-roster player is unique.
9. Selection is deterministic/permutation-invariant for the same inputs and tie-breaking contract.
10. Missing/unpriced values remain explicit and are not coerced to zero merely to complete assignment.
11. FLEX participation affects overall meaningful-roster/team value.
12. FLEX is **not required** to appear as a separate sortable Team Strength category.

---

## 8. Required master-record reconciliation

Issue #899 tracks the required mirrors. Before the Team Strength unit is allowed to close, this decision must be reconciled into the canonical planning/control records, at minimum:

- `docs/MASTER_PRODUCT_PLAN.md` §4.1 Team Strength;
- `docs/OWNER_REQUESTED_TODO.md` as a new binding owner decision;
- `docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md` / T-NEW-19 successor wording;
- `docs/OWNER_FEATURE_INVENTORY.md` Team Strength row 1.7;
- `docs/C_SERIES_SCOPE_MANIFEST.md` Team Strength / `C2-CORE-01` mapping;
- `docs/C_SERIES_ZERO_LOSS_TRACEABILITY.md` Team Strength mapping;
- `docs/C_SERIES_DIRECTIVE_RECONCILIATION_2026-08-17.md` via explicit 2026-08-18 supersession note, or a newer reconciliation record;
- `docs/EXECUTION_PLAN.md` C2 Team Strength acceptance criteria when forward C-Series execution resumes.

The newest explicit owner instruction remains highest authority while those mirrors are being reconciled.
