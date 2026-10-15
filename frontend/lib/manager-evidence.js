/**
 * Generated-trade card evidence — display materializer for the backend's
 * `managerEvidence` block (owner `src/intel/manager_scout.py::offer_evidence`).
 *
 * Kept apart from `lib/manager-scout.js` so the /arbitrage cards do not grow
 * the /trades bundle (which renders the full Manager Scout table). Reshapes
 * published counts only: no tendency, label, fit grade or likelihood.
 */

const STATE_TEXT = {
  insufficient_sample: "not enough history",
  unavailable: "not available",
};

function finite(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

const OFFER_EVIDENCE_REASONS = {
  manager_scout_unavailable: "manager history could not be read",
  opponent_owner_unresolved: "this team's manager could not be identified",
  opponent_profile_missing: "no history recorded for this manager",
  no_completed_trades_observed: "no completed trades on record",
  acquisition_store_missing: "trade history is not collected on this server",
};

/**
 * One offer's `managerEvidence` block (backend
 * `manager_scout.offer_evidence`) as plain sentences. Counts with their
 * samples only; never a label, a fit grade or a likelihood.
 *
 * Returns `{ available, lines, note }`. When the block is not measured,
 * `lines` is empty and `note` says why.
 */
export function offerEvidenceLines(ev) {
  if (!ev || typeof ev !== "object") {
    return {
      available: false,
      lines: [],
      note: "Manager history not available.",
    };
  }
  if (ev.state !== "measured") {
    const why =
      OFFER_EVIDENCE_REASONS[ev.reason] ||
      STATE_TEXT[ev.state] ||
      "not available";
    return { available: false, lines: [], note: `Manager history: ${why}.` };
  }
  const n = ev.tradeCount;
  const plural = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
  const lines = [];
  for (const p of ev.positionsTheyWouldReceive || []) {
    if (p.receivedBefore == null) continue;
    lines.push(
      `Received ${p.receivedBefore} ${p.position} of ${plural(p.ofPlayersReceived, "player")} acquired by trade`,
    );
  }
  const picks = ev.picksTheyWouldReceive;
  if (picks) {
    lines.push(
      `Received ${plural(picks.receivedBefore, "pick")} of ${plural(picks.ofAssetsReceived, "asset")} acquired by trade`,
    );
  }
  if (ev.offerShapeForThem) {
    lines.push(
      `${ev.sameShapeBefore} of ${plural(n, "trade")} had this shape for them (${ev.offerShapeForThem})`,
    );
  }
  if (ev.tradesWithRequester != null) {
    lines.push(`${plural(ev.tradesWithRequester, "trade")} completed with you`);
  }
  const unresolved = finite(ev.unresolvedPositionReceived);
  const note =
    unresolved !== null && unresolved > 0
      ? `From ${plural(n, "completed trade")}; ${unresolved} received player${unresolved === 1 ? "" : "s"} had no resolvable position, so position counts are a floor. History, not a prediction.`
      : `From ${plural(n, "completed trade")}. History, not a prediction.`;
  return { available: true, lines, note };
}
