// Board pick-class lifecycle — the client's ONE reader of "which rookie-draft
// pick classes are still active on the shared board".
//
// The rule is decided server-side (src/identity/pick_lifecycle.py, stamped as
// the contract's ``pickClassLifecycle``; owner requirement #1414).  This module
// only READS that stamp.  It never derives a draft year, and it fails OPEN: no
// stamp means "retire nothing" (missing is never retired).

/** First still-active pick class on the board, or null when the contract does not say. */
export function boardFirstActivePickYear(contract) {
  const stamped = Number(contract?.pickClassLifecycle?.firstActiveClass);
  if (Number.isFinite(stamped) && stamped > 2000) return stamped;
  const fromContract = Number(contract?.currentDraftYear);
  return Number.isFinite(fromContract) && fromContract > 2000 ? fromContract : null;
}

/** True when a pick row belongs to a class the board has retired. */
export function isRetiredPickClassRow(row, firstActiveYear) {
  if (!row || row.assetClass !== "pick") return false;
  if (!Number.isFinite(firstActiveYear)) return false;
  const m = /^(\d{4})\b/.exec(String(row.name || ""));
  return m ? Number(m[1]) < firstActiveYear : false;
}
