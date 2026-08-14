# Roster Capacity / Forced-Drop Trade Analysis Addendum — 2026-08-14

**Owner-approved C-series scope. Tracking: #843.**

This addendum is binding for the eventual Trade Calculator, Analyze Trade (#792), Trade Finder / Best Trade to Send Each Team (#841), Trade Desk, and the shared Use Team Context mode (#842).

## Core rule

When **Use Team Context = ON** (default), a proposed trade must be evaluated against the team's **actual roster capacity and final legal post-trade roster**, not only the assets displayed in the package.

Canonical flow:

`before roster → apply trade → calculate capacity / overage → determine any required legal cleanup → apply optimal legal cleanup → rerun canonical roster intelligence → evaluate final post-cleanup result`

Do not stop at the intermediate over-limit state.

## Required capacity state

For each side derive from canonical league/team state:

- active roster limit and current active count;
- open active roster spots;
- current over-limit count, including teams already over the limit before the proposed trade;
- incoming/outgoing player counts and net player-count change;
- post-package roster count before cleanup;
- number of cuts/moves required to return to legal status;
- final post-cleanup count;
- whether the trade resolves, improves, leaves unchanged, or worsens an existing overage;
- taxi / IR / other special-slot capacity only where actual league rules and player eligibility permit those moves.

Draft picks normally do not consume an immediate active roster spot and must not be counted as current players merely because they are included in the trade.

## Forced-drop cost

If the trade requires a cut or special-slot move, that consequence is part of the trade's real roster cost.

Do not model it solely as `package delta - lowest raw player value`.

Use canonical dropability / roster utility to determine the lowest-cost legal cleanup path, then recompute the final roster. Show likely cut candidates and canonical values for explainability, but use the true final roster marginal effect for the decision.

If multiple cleanup options are close, preserve uncertainty rather than pretending one drop is certain.

## Open roster spots

If the team has enough open space to absorb the incoming players, state that the trade fits cleanly and impose no forced-drop cost.

Do not invent an arbitrary numeric value for an open roster spot. Capacity is a feasibility / marginal-roster dimension unless a later separately validated option-value methodology is approved.

## Existing over-limit examples

- Team is 1 over; 2-for-1 returns it to legal size → meaningful practical benefit.
- Team is 3 over; 2-for-1 reduces overage to 2 → improvement, but still over limit.
- Team is 1 over; 1-for-2 increases overage to 2 → additional cleanup burden.

Do not manufacture a fake canonical-value bonus for becoming legal. Capture the benefit through avoided cuts, preserved assets, and final roster state.

## Trade Calculator

With Team Context ON, show inline before full Analyze Trade:

- open spots / over-limit state;
- net player-count change;
- whether cleanup is required;
- likely cut/move candidates where determinable;
- whether a consolidation trade resolves an existing overage.

The package calculator may still show raw package economics separately. The roster-aware layer must make clear when the effective roster outcome is worse because a cut is required.

## Analyze Trade (#792)

Roster Capacity / Forced-Drop Impact is part of canonical roster marginal impact.

The final MAKE / LEAN MAKE / TOO CLOSE / LEAN PASS / PASS recommendation may change because of:

- forced-drop cost;
- open capacity that absorbs a quantity package cleanly;
- consolidation that reduces/resolves an over-limit roster;
- final post-cleanup Team Strength / Weakness;
- final post-cleanup #839 Meaningful Roster Core;
- final post-cleanup #838 Age-Value / Young Core;
- final post-cleanup playoff/championship counterfactuals where supported.

The analyzer must not run season odds on an impossible over-limit roster when a required cleanup move materially changes the roster.

## Trade Finder / Best Trade to Send Each Team (#841)

With Team Context ON, capacity must be evaluated for **both teams** when generating/ranking packages.

A legal `<=1 player-count difference` package may still be poor if the side receiving the extra player has no open slot and the forced cut destroys the benefit. Conversely, a team with open spots may rationally accept quantity, and a team already over the limit may value consolidation.

Capacity affects ranking and mutual defensibility; it does not override LOCK / EXCLUDE / persistent protection or other hard constraints.

## Use Team Context (#842)

- **ON (default):** #843 affects trade display, full analysis, and generated-trade ranking.
- **OFF / Asset-Only:** roster capacity and forced-drop consequences do not affect verdict/ranking. If shown for convenience, mark them as not included in Asset-Only analysis.
- Missing capacity data must remain degraded/unknown; do not silently assume zero open spots, zero overage, no forced drop, or auto-switch to Asset-Only.

## Validation fixtures

At minimum cover:

1. full roster, 1-for-1 → no cut;
2. full roster, 1-for-2 → one cleanup move;
3. one open spot, 1-for-2 → clean fit;
4. currently 1 over, 2-for-1 → legal after trade;
5. currently 3 over, 2-for-1 → overage improves to 2;
6. currently 1 over, 1-for-2 → overage worsens to 2;
7. legal taxi/IR move versus an ineligible move;
8. forced cut candidate selected by lowest real marginal loss rather than raw value alone;
9. picks do not consume immediate active-roster capacity;
10. Team Context OFF excludes #843 from verdict/ranking;
11. generated-trade ranking changes when one side cannot absorb the extra player without an expensive cut.

## C-series zero-loss requirement

#843 must be mapped into the C Scope Manifest before the trade decision/generation stack is treated as complete. A Trade Calculator / Analyze Trade implementation that ignores roster limits, existing overages, or forced cleanup is **not** roster-aware completion.