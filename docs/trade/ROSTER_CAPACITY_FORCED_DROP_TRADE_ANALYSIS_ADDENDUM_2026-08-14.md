# Roster Capacity / Forced-Drop Trade Analysis Addendum — 2026-08-14

**Owner-approved superseding/additive trade-generation requirement. Tracking: #843.**

When **Use Team Context = ON** (default; #842), Trade Calculator, Analyze Trade (#792), Trade Finder / Best Trade to Send Each Team (#841), and later Trade Desk workflows must evaluate the team's **actual final legal roster**, including open spots, existing over-limit status, and any forced cleanup caused by the trade.

## Canonical sequence

`before roster → apply trade → calculate capacity / overage → determine required legal cleanup → apply lowest-cost legal cleanup → rerun canonical roster intelligence → evaluate final post-cleanup result`

A required cut is a real consequence of the trade. The system must not pretend every incoming player survives when the roster has no room.

## Required capacity facts

For both sides, derive active roster limit/count, open spots, current overage, net player-count change, post-package count, required cleanup count, final post-cleanup count, and whether the trade resolves/improves/worsens an existing overage. Use taxi/IR only when actual rules and player eligibility make the move legal. Picks normally do not consume an immediate active-roster spot.

## Forced-drop cost

Use canonical dropability / roster utility to choose the lowest-cost legal cleanup path rather than simply dropping the lowest raw-value player. Show likely cut candidates and values for explainability, but rank/analyze on the true final post-cleanup roster impact.

## Generated-trade behavior

The `<=1` player-count topology remains unchanged, but roster capacity affects mutual-benefit ranking.

- A team with an open spot can absorb a 1-for-2 cleanly.
- A full team receiving the extra player must be evaluated with the resulting forced cut.
- A team already over the limit may rationally prefer a 2-for-1 consolidation because it reduces or resolves its overage.
- A package that looks favorable before cleanup may be downgraded or rejected if the forced cut destroys the advantage.

Capacity applies to **both teams** and does not override protection / LOCK / EXCLUDE or other hard package constraints.

## Analyze Trade behavior

With Team Context ON, roster-capacity / forced-drop impact is part of canonical roster marginal impact. Recompute Team Strength/Weakness, #839 Meaningful Roster Core, #838 Age-Value/Young Core, and season probabilities from the final post-cleanup roster when material.

## Team Context OFF

Asset-Only mode excludes roster-capacity/forced-drop effects from verdict and generated ranking. If capacity is displayed for convenience, label it as not included in Asset-Only analysis.

## Completion condition

A trade tool is not considered fully roster-aware if it cannot distinguish clean absorption, forced cuts, existing over-limit improvement, and over-limit worsening.