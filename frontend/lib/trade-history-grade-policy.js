/**
 * trade-history-grade-policy — the ONE frontend definition of the trade
 * HISTORY grade's lowest tier: its threshold, its word and the sentence that
 * states what it measures.  Dependency-free, so both the private /trades page
 * (via lib/league-analysis.js) and the public /league timeline can read it.
 *
 * Owner of the criterion: src/public_league/trade_grading.py::HISTORY_EVEN_PCT /
 * HISTORY_EVEN_LABEL.  This file mirrors it, pinned by
 * tests/public_league/test_history_grade_relabel_no_change.py (which reads the
 * two exports below) and by the shared parity fixture
 * tests/fixtures/trade_grade_parity_cases.json.  Change both together.
 *
 * OD-F6 option A (owner, 2026-10-21): the tier used to read "Fair trade", the
 * same word as the market-fairness verdict (FAIR TRADE / NOT FAIR,
 * fairness_bands_v2: 3.5% of the larger package utility or under a 250-point
 * floor).  Those are different predicates, so the history tier was renamed
 * with no grade change.  The grade measures VALUE BALANCE — the
 * package-adjusted board values each side gave and got, on a stated date —
 * not realized results, which is why the word is "Evenly valued" and not
 * "Even outcome".  Record: docs/trade/HISTORY_GRADE_RELABEL_OD_F6_2026-10-21.md.
 */

/** |pctGap| strictly below this is the evenly-valued tier (a PRIOR cut point). */
export const HISTORY_EVEN_PCT = 3;

/** The tier-0 word.  Never the advisor's "FAIR" phrase. */
export const HISTORY_EVEN_LABEL = "Evenly valued";

/**
 * What every history grade measures, in one sentence the page can show.
 * Applies to both the "When traded" and the "Today" grade; only the date of
 * the values differs.
 */
export function historyGradeBasisText() {
  return (
    "Trade grades compare the value each side gave and got (board value plus the " +
    "package adjustment), as a share of the larger side. \"When traded\" uses the " +
    "latest values recorded before the trade; \"Today\" uses today's values. " +
    `"${HISTORY_EVEN_LABEL}" means the gap is under ${HISTORY_EVEN_PCT}% of the larger side. ` +
    "It measures how the values balanced, not how the players went on to perform, " +
    "and it is not the FAIR / NOT FAIR market-fairness verdict of the trade " +
    "calculator and advisor."
  );
}
