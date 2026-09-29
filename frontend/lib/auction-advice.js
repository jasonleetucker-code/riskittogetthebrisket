/**
 * Rookie auction room → Perfect Draft adapter (milestone C).
 *
 * A pure translation of the server's authorised room snapshot into the
 * EXISTING optimizer's input (`lib/perfect-draft.js::optimizeDraft`).  It
 * computes no player value and no new objective:
 *
 *  - budget   = the seat's `spendable` from the server's ledger (AUC-001:
 *               leading prices are already reserved) — the SAME number the
 *               room shows, never a client recomputation;
 *  - held     = lots this seat currently leads + lots it has won.  They are
 *               commitments/purchases, not candidates, and they occupy
 *               roster room via `applyDraftProgress`;
 *  - candidates = every other unsold rookie in the room's frozen pool:
 *      open lot   → expected price = max(estimate, public price + 1)
 *      unnominated → expected price = estimate
 *    where estimate = the player's share of the room's opening money by
 *    board value across the lots the room can sell (rounds × seats).  It is
 *    an ESTIMATE, labelled as one; it is never a legal minimum, and $0 stays
 *    $0.  A player with no board value is UNPRICED and left out.
 *
 * Runs in the manager's own browser from their own authorised view, so a
 * rival's maximum or strategy is never an input and never leaves the device.
 */

export const ESTIMATE_LABEL =
  "Expected prices are estimates: each rookie's share of this room's money by board value (open lots: at least one dollar over the current price). They are not bids and not a minimum.";

export function boardValueFor(pid, pool, boardValues) {
  const live = Number(boardValues?.[pid]);
  if (Number.isFinite(live) && live > 0) return live;
  const snap = Number(pool?.[pid]?.value);
  return Number.isFinite(snap) && snap > 0 ? snap : null;
}

export function buildAdviceInput({ view, pool, adviceCtx, strategy = "balanced", applyDraftProgress }) {
  const pub = view?.public;
  const me = view?.me?.private;
  const seat = view?.me?.seat;
  if (!pub || !me || !seat || !pool) return { input: null, reason: "no_seat" };
  if (me.spendable == null) return { input: null, reason: "budget_missing" };
  const ctx = adviceCtx?.context || null;
  if (!ctx) return { input: null, reason: adviceCtx?.reason || "no_roster_context" };

  const values = adviceCtx?.boardValues || {};
  const sellable = Math.max(1, (pub.rules?.rounds || 6) * (pub.seats?.length || 12));
  const valued = Object.keys(pool)
    .map((pid) => boardValueFor(pid, pool, values))
    .filter((v) => v !== null)
    .sort((a, b) => b - a)
    .slice(0, sellable);
  const denom = valued.reduce((s, v) => s + v, 0);
  const roomMoney = Math.max(0, Number(pub.total_opening_pool) || 0);
  const estimate = (v) => (denom > 0 ? Math.round((roomMoney * v) / denom) : null);

  const byPlayer = new Map(pub.auctions.map((a) => [a.player, a]));
  const held = [];
  const candidates = [];
  let unpriced = 0;
  for (const [pid, p] of Object.entries(pool)) {
    const a = byPlayer.get(pid);
    if (a && a.status === "closed") {
      if (a.winner === seat) held.push({ id: pid, name: p.name, price: a.price, state: "won" });
      continue;
    }
    if (a && a.status === "open" && a.leader === seat) {
      held.push({ id: pid, name: p.name, price: a.price, state: "leading" });
      continue;
    }
    const v = boardValueFor(pid, pool, values);
    const est = v === null ? null : estimate(v);
    if (v === null || est === null) {
      unpriced += 1;
      continue;
    }
    const price = a && a.status === "open" ? Math.max(est, a.price + 1) : est;
    candidates.push({
      id: pid,
      name: p.name,
      pos: p.pos || "",
      boardValue: v,
      price: Math.max(0, price),
      lot: a ? a.id : null,
      lotPrice: a ? a.price : null,
    });
  }

  const progress = applyDraftProgress({
    openRosterSpots: ctx.openRosterSpots || 0,
    cutLadder: ctx.cutLadder?.rungs || ctx.cutLadder || [],
    waiverLadder: ctx.waiverLadder || null,
    rookiesBought: held.length,
  });

  return {
    reason: null,
    held,
    unpriced,
    progress,
    input: {
      rookies: candidates,
      budget: Math.max(0, Number(me.spendable) || 0),
      cutLadder: progress.cutLadder,
      openRosterSpots: progress.openRosterSpots,
      waiverValues: ctx.waiverValues || {},
      waiverLadder: ctx.waiverLadder || null,
      strategy,
    },
  };
}
