# Current-HEAD Monte Carlo Findings — 2026-08-11

A read-only trace of current `main` before a dedicated implementation audit.

- The live trade UI centers Monte Carlo on `effectiveValue(...)`, the same value used by the trade builder, so upstream canonical value changes already baked into `row.values.full` flow into the simulation center.
- The frontend currently requests `applyConsolidationAdjustment: true`; the backend Monte Carlo implementation supports KTC-style package/consolidation adjustment.
- The simulation is not a holistic trade-decision model. It samples side asset values and does not itself incorporate the separate roster-impact/Team Strength/Weakness/Second Opinions systems.
- When a row has no real `valueBand`, the current frontend synthesizes a flat ±15% band and stamps it as synthetic. Current repository documentation records that no live contract rows had stamped value bands in the measured baseline. Therefore the uncertainty spread should be treated as an assumption until revalidated.
- The Monte Carlo core uses broad hard-coded positive correlation factors (`same_team_rho=.25`, `same_pos_group_rho=.10`). A richer correlation-matrix module exists but repository search does not show it as a production consumer; its coefficients are also assumptions.
- Because both sides are centered on their effective values with broadly similar uncertainty shapes, the side with the higher adjusted center should usually win more Monte Carlo draws. This is expected behavior, not by itself evidence that the simulation is wrong.
- The current source contains historical repair comments/tests around elite-band truncation and provenance, but a fresh current-HEAD reproduction is still required before declaring Monte Carlo closed/correct.

See `TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md` for the required audit and future decision-synthesis architecture.
