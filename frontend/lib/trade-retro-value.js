/**
 * trade-retro-value — value each side of a historical trade at the
 * date the trade went through, using rankHistory.
 *
 * The existing ``analyzeSleeperTradeHistory`` grades trades at
 * *current* values.  This helper layers in the at-trade snapshot so
 * the UI can show a trade's age — "you won this by 3,200 then; it's
 * now a 1,800 win because Player X faded."
 *
 * Inputs
 * ------
 *   trade           — the analyzed trade record from
 *                     analyzeSleeperTradeHistory (.sides[].items[].name)
 *   tradeTimestamp  — epoch ms of the trade
 *   historyLookup   — function (name) → [{date, rank}] from
 *                     buildHistoryLookup(history)
 *
 * Output
 * ------
 *   {
 *     atTradeBySide: [{ side: "got"|"gave", total, items: [...]}, ...],
 *     verdict:        "winner"|"loser"|"even"|"unknown"
 *     verdictDelta:   number — current_net - at_trade_net
 *   }
 *
 * verdict logic: positive verdictDelta means the team came out ahead
 * relative to expectations at the time of the trade.  A team that
 * looked even at the time but is now +3,000 ahead = winner.
 */
import { valueFromRank } from "@/lib/value-history";

/**
 * Find the rank-history point closest-before ``asOfMs``, or — when
 * the trade predates all coverage — the earliest available sample.
 * Returns the whole point so callers can read both ``rank`` and the
 * server-stamped ``val`` (canonical pipeline value at that snapshot).
 */
function pointAt(history, asOfMs) {
  if (!Array.isArray(history) || history.length === 0) return null;
  let best = null;
  let earliest = null;
  for (const point of history) {
    const t = Date.parse(point?.date);
    if (!Number.isFinite(t)) continue;
    const rank = Number(point?.rank);
    if (!Number.isFinite(rank) || rank <= 0) continue;
    if (!earliest || t < earliest.t) earliest = { t, point };
    if (t <= asOfMs) {
      if (!best || t > best.t) best = { t, point };
    }
  }
  // Prefer closest-before; fall back to earliest sample for trades
  // that predate the rank-history window (better than null when the
  // player's coverage starts shortly after the trade).
  return (best || earliest)?.point || null;
}

function valueFromPoint(point) {
  if (!point) return null;
  const stamped = Number(point.val);
  if (Number.isFinite(stamped) && stamped > 0) return stamped;
  // Defensive: if the server didn't stamp ``val`` for this point
  // (shouldn't happen with the new schema), fall back to the local
  // Hill-curve approximation.  Documented mismatch with backend
  // canonical curves — see value-history.js::valueFromRank.
  const r = Number(point.rank);
  if (!Number.isFinite(r) || r <= 0) return null;
  return valueFromRank(r);
}

export function valueSideAtTime(items, historyLookup, asOfMs) {
  if (!Array.isArray(items)) return { total: 0, items: [] };
  let total = 0;
  const out = [];
  for (const it of items) {
    if (!it) continue;
    if (it.isPick) {
      // Picks: lean on the current value.  Pick valuation history is
      // not stamped per-pick; using the current ``val`` is the
      // pragmatic baseline.  Slight optimism if pick markets have
      // moved since the trade — caller can detect this gap.
      const v = Number(it.val) || 0;
      out.push({ name: it.name, val: v, isPick: true, source: "current" });
      total += v;
      continue;
    }
    const history = historyLookup ? historyLookup(it.name) : null;
    const pointAtTrade = pointAt(history, asOfMs);
    const stamped = valueFromPoint(pointAtTrade);
    if (stamped != null) {
      out.push({ name: it.name, val: stamped, isPick: false, source: "rankHistory" });
      total += stamped;
    } else {
      const v = Number(it.val) || 0;
      out.push({ name: it.name, val: v, isPick: false, source: "current_fallback" });
      total += v;
    }
  }
  return { total: Math.round(total), items: out };
}

/**
 * Compute "got" minus "gave" deltas for both at-trade and current.
 * Returns the verdict + the magnitudes for one side of a 2-team trade.
 */
export function gradeRetro({ side, currentNet, asOfMs, historyLookup }) {
  if (!side) return null;
  const got = side.got || side.gotItems || [];
  const gave = side.gave || side.gaveItems || [];
  const atTradeGot = valueSideAtTime(got, historyLookup, asOfMs);
  const atTradeGave = valueSideAtTime(gave, historyLookup, asOfMs);
  const atTradeNet = atTradeGot.total - atTradeGave.total;
  const verdictDelta = Number.isFinite(currentNet)
    ? currentNet - atTradeNet
    : null;
  let verdict = "unknown";
  if (Number.isFinite(verdictDelta)) {
    if (verdictDelta > 200) verdict = "aged_well";
    else if (verdictDelta < -200) verdict = "aged_poorly";
    else verdict = "stable";
  }
  return {
    atTradeGot,
    atTradeGave,
    atTradeNet,
    currentNet,
    verdictDelta,
    verdict,
  };
}
