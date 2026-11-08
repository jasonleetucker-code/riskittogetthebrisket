/**
 * The ONE owner of the uncalibrated-odds disclosure.
 *
 * Owner decision 9 (2026-11-01): wherever the site shows a playoff or
 * championship probability that the season simulator
 * (``src/ros/playoff_sim.py``) produced, and those odds have not been
 * calibrated against this league's historical outcomes, the surface says so
 * in exactly these words.  No calibrated odds exist today: the simulator's
 * points-model challengers did not pass their preregistered gates
 * (docs/league-intelligence/SIM_CALIBRATION_V3_RESULTS_2026-10-27.md,
 * ``V3_DOES_NOT_BEAT_FALLBACK``), and no league-outcome calibration of the
 * playoff/title odds has been run.
 *
 * Wording is owner-approved — change it only with a new owner decision.
 * Pinned by ``frontend/__tests__/components/odds-experimental-disclosure.test.jsx``.
 */
export const ODDS_EXPERIMENTAL_DISCLOSURE =
  "Experimental projection — not yet calibrated against this league's historical outcomes.";

/**
 * A simulated share (playoff, title, finals, division, draft-slot odds) as a
 * whole percent.  Owner directive 2026-11-08: a Monte Carlo estimate of exactly
 * 0 or 1 is not proof — the simulation ran a finite number of seasons — so it
 * reads "<1%" / ">99%" until the outcome is final.  Whole percents because the
 * simulator converges to about half a point of standard error: a tenth of a
 * percent is noise presented as precision.  Missing is a dash, never 0%.
 */
export function fmtSimulatedShare(p, { final = false } = {}) {
  if (typeof p !== "number" || !Number.isFinite(p)) return "—";
  const pct = Math.round(p * 100);
  if (!final) {
    if (pct <= 0) return "<1%";
    if (pct >= 100) return ">99%";
  }
  return `${pct}%`;
}
