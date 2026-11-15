/**
 * Reading the served board the way /trade does, for specs that build a trade
 * from the LIVE seeded contract (#1918).
 *
 * The seeded contract is the committed `exports/latest/` snapshot, which the
 * scheduled refresh rewrites every few hours.  Its rosters follow the real
 * league (a pick traded on Sleeper moves to another team in the next
 * refresh) and its evidence stamps follow the real sources (a family going
 * past its staleness budget turns rows' freshness axis `low`).  A spec that
 * hard-codes an asset, or takes "the first N rows" without asking whether
 * the page will price them, therefore fails on routine data drift with no
 * product change at all.  These helpers let a spec ask the board instead.
 */

/**
 * The data view /trade itself requests (`frontend/lib/device-profile.js::
 * preferredDataView` returns "compact" on /trade for every device), so a
 * spec reads exactly the rows the page materialises.
 */
const TRADE_DATA_VIEW = "compact";

/**
 * Why /trade WITHHOLDS a board row's value from a team result, or `null`.
 *
 * Mirrors `frontend/lib/trade-logic.js::withheldValueState` (that module is
 * ESM inside the Next app and is not importable from a CommonJS spec): the
 * pipeline's row-level quarantine stamp, then the confidence owner's
 * freshness axis reading `low`.  Read, never computed — the stamps are the
 * backend's.  Keep the two in lockstep.
 */
function withheldValueState(row) {
  if (!row || row.customValue != null) return null;
  if (row.quarantined === true || row.raw?.quarantined === true) return "quarantined";
  const freshness = row.confidenceAxes?.freshness ?? row.raw?.confidenceAxes?.freshness;
  if (freshness === "low") return "stale";
  return null;
}

/** The board row for a display name, from whichever encoding the view carries. */
function boardRow(contract, name) {
  const dict = contract?.players || {};
  if (dict[name]) return dict[name];
  return (contract?.playersArray || []).find((p) => p?.displayName === name || p?.canonicalName === name) || null;
}

/** A row the page will price on the meter: positive canonical value, not withheld. */
function isTradeableRow(row) {
  return Boolean(row) && Number(row.rankDerivedValue) > 0 && withheldValueState(row) == null;
}

module.exports = { TRADE_DATA_VIEW, withheldValueState, boardRow, isTradeableRow };
