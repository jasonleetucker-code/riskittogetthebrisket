// Draft-capital AUCTION BUDGETS — available or unavailable, never $0.
//
// `/api/draft-capital`'s `teamTotals[].auctionDollars` are the upcoming
// class's per-team dollars: the auction-budget basis /draft, the auction room,
// the /league simulator and the /trade stack read.  The Sleeper-derived
// fallback publishes them as UNAVAILABLE (`teamTotalsState: "unavailable"`,
// every `auctionDollars: null`, `teamTotalsReason` named) when the upcoming
// class is unpriced or cannot be proven (src/api/draft_capital_classes.py).
// MISSING IS NEVER ZERO: every consumer asks this module first and renders
// the unavailable state instead of coercing null to $0.

export const TEAM_TOTALS_UNAVAILABLE = "unavailable";

const REASON_TEXT = {
  upcoming_class_unpriced: "the upcoming draft class has no priced picks",
  upcoming_draft_year_unverified: "the league's upcoming draft year could not be verified",
};

/**
 * The reason the payload's auction budgets cannot be used, or null when they
 * can.  A payload that predates the field is read as available (its budgets
 * are numbers), unless every row's `auctionDollars` is non-numeric.
 */
export function draftCapitalBudgetsUnavailableReason(data) {
  if (!data || typeof data !== "object") return null;
  if (data.teamTotalsState === TEAM_TOTALS_UNAVAILABLE) {
    return data.teamTotalsReason || "unavailable";
  }
  const rows = Array.isArray(data.teamTotals) ? data.teamTotals : [];
  if (
    rows.length > 0 &&
    rows.every((r) => typeof r?.auctionDollars !== "number" || !Number.isFinite(r.auctionDollars))
  ) {
    return "no_team_budgets";
  }
  return null;
}

/** Human-readable sentence for an unavailable-budget reason. */
export function draftCapitalBudgetsUnavailableText(reason) {
  const why = REASON_TEXT[reason] || "the budgets could not be determined";
  return `Auction budgets unavailable: ${why}. Not shown as $0.`;
}

/**
 * The `teamTotals` rows a budget consumer may load (the /draft workspace),
 * or a thrown Error naming why there are none.  Never returns rows whose
 * budgets are unavailable — the caller would coerce their nulls to $0.
 */
export function draftCapitalBudgetRows(data) {
  const reason = draftCapitalBudgetsUnavailableReason(data);
  if (reason) throw new Error(draftCapitalBudgetsUnavailableText(reason));
  const rows = Array.isArray(data?.teamTotals) ? data.teamTotals : [];
  if (rows.length === 0) throw new Error("Draft capital feed had no team totals.");
  return rows;
}
