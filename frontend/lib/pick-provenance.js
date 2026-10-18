/**
 * pick-provenance — display wording for a pick row's ``pickValueProvenance``.
 *
 * The backend owner is ``src/api/data_contract.py::_complete_future_pick_values``
 * (C1-U6): every pick row carries the evidence class its value rests on.  The
 * classes below are DERIVED values — no market priced that row — and they are
 * declared PRIORs, not fitted.  This module only words them; it never prices,
 * re-derives or re-classifies anything.
 *
 * One wording owner shared by the Player popup and the Trade Calculator
 * builder (TC-B / TCM-B04), so the two can never describe the same row
 * differently.
 */

/** Short builder labels — the class, never a number.  Keyed by exactly the
 * classes ``./pick-provenance-text.js`` describes (pinned by test). */
const DERIVED_PICK_LABELS = {
  derived_year_step: "Derived year",
  derived_round_step: "Derived round",
  derived_uniform_tier_ev: "Generic: tier average",
};

/** The provenance object a materialized row carries, or null. */
export function pickProvenanceOf(row) {
  const p = row?.raw?.pickValueProvenance || row?.pickValueProvenance || null;
  return p && typeof p === "object" ? p : null;
}

/**
 * The derived-pick disclosure for one row, or null for a market-priced (or
 * non-pick) row: ``{ cls, label, basis, isPrior }``.  ``basis`` is the
 * backend's own list of rows the value was derived from, joined for display.
 * The long sentence for a class lives in ``./pick-provenance-text.js``
 * (``DERIVED_PICK_DESCRIPTIONS``), a separate module so the /trade page
 * chunk carries only the short label: an export used anywhere is kept in
 * every chunk that imports its module, and /trade's budget has no room for
 * the prose the Player popup shows.  A
 * row with no provenance is NOT assumed to be market-priced by this
 * function's callers — it simply has nothing derived to disclose.
 */
export function derivedPickDisclosure(row) {
  const p = pickProvenanceOf(row);
  const label = p && DERIVED_PICK_LABELS[p.class];
  if (!label) return null;
  const basis = Array.isArray(p.basis) ? p.basis.join(", ") : p.basis || "";
  return {
    cls: p.class,
    label,
    basis,
    // Every derived class is a declared prior today (C1-U6); the backend
    // stamps it on the uniform-tier class and the others are documented so.
    isPrior: p.classification ? p.classification === "PRIOR" : true,
  };
}
