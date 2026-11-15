/**
 * pick-provenance-text — the plain-language sentence for each DERIVED pick
 * provenance class (C1-U6, ``src/api/data_contract.py::
 * _complete_future_pick_values``).  Companion of ``./pick-provenance.js``,
 * split out only so the /trade page chunk does not carry this prose (see
 * the note there).  One wording owner for the Player popup and the builder.
 */

/** Derived (no market row) provenance classes, with their plain-language meaning. */
export const DERIVED_PICK_DESCRIPTIONS = {
  derived_year_step:
    "No market prices this year yet; derived from the nearest priced year using the measured year-to-year step.",
  derived_round_step:
    "No market prices this round; derived from the same year's nearest priced round using the board's own round step.",
  derived_uniform_tier_ev:
    "A pick whose slot is not yet known; the average of that year and round's early, mid and late values.",
};

