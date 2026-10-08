/**
 * Manager Scout (C6-MGR-01) — display materializer for `/api/manager-scout`.
 *
 * The canonical owner is `src/intel/manager_scout.py`. This module only
 * reshapes and formats what the backend published; it computes no tendency,
 * no value and no label (the per-trade "today's value" figures are the
 * backend's `valueAtToday` block — canonical board, raw sum, not
 * VA-adjusted — passed through verbatim). It REPLACES `analyzeTradeTendencies`, which used to
 * live in `lib/league-analysis.js` and derived per-manager trade tendencies in
 * the browser from the contract's `sleeper.trades` — a second owner of a
 * private concept. That function is deleted, not deprecated; see
 * `__tests__/manager-scout.test.js` for the guard.
 *
 * MISSING IS NEVER ZERO. Every block arrives with a `state`
 * (`measured` / `insufficient_sample` / `unavailable` / `not_applicable` /
 * `not_measured`). A share is rendered only when `state === "measured"`;
 * otherwise the cell says why it is empty. A real count of zero over a
 * present ledger is rendered as 0.
 */

/** Classify a non-2xx answer into a renderable state. */
export function classifyManagerScoutFailure(status, body) {
  if (status >= 200 && status < 300) return null;
  const code = body && typeof body === "object" ? body.error : "";
  const message = (body && typeof body === "object" && (body.message || body.detail)) || "";
  if (status === 401) return { kind: "auth", message: "Sign in to see manager tendencies." };
  if (code === "unknown_league" || code === "inactive_league" || code === "no_leagues_configured") {
    return { kind: "league", message };
  }
  if (code === "data_not_ready") return { kind: "not_ready", message };
  if (code === "manager_scout_unavailable") return { kind: "unavailable", message };
  return { kind: "error", message: message || `HTTP ${status}` };
}

const STATE_TEXT = {
  insufficient_sample: "No sample",
  unavailable: "Unavailable",
  not_applicable: "N/A",
  not_measured: "Not measured",
};

/** Why a block has no number, in a few words. */
export function stateText(state) {
  return STATE_TEXT[state] || "—";
}

function finite(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function pct(share) {
  if (!share || share.state !== "measured") return null;
  const v = finite(share.value);
  return v === null ? null : Math.round(v * 100);
}

/** "WR 3 · RB 2" — the published counts, largest first, top `n`. */
export function topCounts(map, n = 2) {
  if (!map || typeof map !== "object") return "";
  return Object.entries(map)
    .filter(([, v]) => finite(v) !== null && v > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, n)
    .map(([k, v]) => `${k === "UNRESOLVED" ? "Unresolved" : k} ${v}`)
    .join(" · ");
}

/**
 * One display row per manager, in the backend's order.
 * Every field is either a published value or `null` with a `*State`.
 */
export function managerScoutRows(payload) {
  const managers = Array.isArray(payload?.managers) ? payload.managers : [];
  return managers.map((m) => {
    const t = m?.tradeTendencies || {};
    const w = m?.waiverTendencies || {};
    const f = m?.faabTendencies || {};
    const tradeMeasured = t.state === "measured";
    const topPartner = Array.isArray(t.partners) && t.partners.length ? t.partners[0] : null;
    const resolved = f.resolvedBids || {};
    const v = t.valueAtToday || {};
    const valueMeasured = v.state === "measured";
    return {
      id: String(m?.ownerId || ""),
      manager: m?.displayName || "Former manager",
      currentMember: Boolean(m?.currentMember),
      tradeState: t.state || "unavailable",
      trades: finite(t.tradeCount),
      tradeSample: finite(t.sampleSize),
      topPartner: topPartner
        ? `${topPartner.displayName || "Former manager"} (${topPartner.trades})`
        : null,
      picksIn: tradeMeasured ? finite(t.received?.picks) : null,
      picksOut: tradeMeasured ? finite(t.sent?.picks) : null,
      pickSharePct: pct(t.pickShareOfReceived),
      bought: tradeMeasured ? topCounts(t.received?.byPosition) || null : null,
      sold: tradeMeasured ? topCounts(t.sent?.byPosition) || null : null,
      consolidating: tradeMeasured ? finite(t.packageShape?.consolidating) : null,
      valueState: v.state || "unavailable",
      gotPerTrade: valueMeasured ? finite(v.receivedPerTrade) : null,
      gavePerTrade: valueMeasured ? finite(v.sentPerTrade) : null,
      netPerTrade: valueMeasured ? finite(v.netPerTrade) : null,
      unpricedAssets: valueMeasured ? finite(v.unpricedAssets) : null,
      waiverState: w.state || "unavailable",
      claims: finite(w.claims),
      faabState: resolved.state || f.state || "unavailable",
      faabSample: finite(resolved.sampleSize),
      faabMeanPct:
        resolved.state === "measured" ? finite(resolved.meanPctOfBudget) : null,
      faabRatio:
        resolved.state === "measured" ? finite(resolved.ratioToLeagueMeanBidPct) : null,
    };
  });
}

/** The sources line under the table: what the profile is built from. */
export function managerScoutCoverage(payload) {
  const s = payload?.sources || {};
  const seasons = s.trades?.window?.seasons || [];
  return {
    trades: s.trades?.state === "available" ? finite(s.trades?.trades) : null,
    claims: s.waivers?.state === "available" ? finite(s.waivers?.claims) : null,
    seasons: Array.isArray(seasons) ? seasons : [],
    faabAvailable: s.faab?.state === "available",
    lineupState: s.lineup?.state || null,
    ledgerState: s.trades?.state || null,
    boardState: s.board?.state || null,
    boardAsOf: s.board?.asOf || null,
  };
}
