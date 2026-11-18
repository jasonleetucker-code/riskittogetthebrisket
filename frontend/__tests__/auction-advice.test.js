import { describe, expect, it } from "vitest";

import { buildAdviceInput } from "../lib/auction-advice.js";
import { applyDraftProgress, optimizeDraft } from "../lib/perfect-draft.js";

const pool = {
  a: { name: "Alpha", pos: "WR", value: 6000 },
  b: { name: "Bravo", pos: "RB", value: 3000 },
  c: { name: "Charlie", pos: "TE", value: 1000 },
  d: { name: "Delta", pos: "QB", value: null },
};

function view({ spendable = 5, auctions = [] } = {}) {
  return {
    public: {
      rules: { rounds: 1 },
      seats: [{ id: "S1" }, { id: "S2" }],
      total_opening_pool: 100,
      auctions,
    },
    me: { seat: "S1", private: { balance: 50, committed: 45, spendable } },
  };
}

const ctx = { context: { openRosterSpots: 3, cutLadder: { rungs: [] }, waiverValues: {}, waiverLadder: null }, boardValues: {} };

describe("buildAdviceInput", () => {
  it("uses the server's spendable (AUC-001: $50 balance, $45 lead → $5)", () => {
    const out = buildAdviceInput({
      view: view({ auctions: [{ id: "A1", player: "a", status: "open", price: 45, leader: "S1" }] }),
      pool,
      adviceCtx: ctx,
      applyDraftProgress,
    });
    expect(out.input.budget).toBe(5);
    expect(out.held).toEqual([{ id: "a", name: "Alpha", price: 45, state: "leading" }]);
    expect(out.input.rookies.map((r) => r.id)).not.toContain("a");
    expect(out.progress.openRosterSpots).toBe(2); // the lead occupies roster room
  });

  it("prices open lots at least $1 over the current price, and leaves unvalued rookies unpriced", () => {
    const out = buildAdviceInput({
      view: view({ auctions: [{ id: "A2", player: "c", status: "open", price: 30, leader: "S2" }] }),
      pool,
      adviceCtx: ctx,
      applyDraftProgress,
    });
    const c = out.input.rookies.find((r) => r.id === "c");
    expect(c.price).toBe(31);
    expect(out.unpriced).toBe(1);
    expect(out.input.rookies.find((r) => r.id === "d")).toBeUndefined();
  });

  it("a $0 room keeps $0 estimates (no $1 floor)", () => {
    const v = view();
    v.public.total_opening_pool = 0;
    const out = buildAdviceInput({ view: v, pool, adviceCtx: ctx, applyDraftProgress });
    expect(out.input.rookies.every((r) => r.price === 0)).toBe(true);
    const res = optimizeDraft({ ...out.input, budget: 0 });
    expect(res.plan.players.length).toBeGreaterThan(0); // a $0 win is a real acquisition
  });

  it("withholds advice without roster context rather than inventing one", () => {
    const out = buildAdviceInput({ view: view(), pool, adviceCtx: { context: null, reason: "board_is_for_another_league" }, applyDraftProgress });
    expect(out.input).toBeNull();
    expect(out.reason).toBe("board_is_for_another_league");
  });

  it("never needs a rival's maximum: only public prices and the seat's own view", () => {
    const out = buildAdviceInput({ view: view(), pool, adviceCtx: ctx, applyDraftProgress });
    expect(JSON.stringify(out.input)).not.toMatch(/max"/);
  });
});

describe("missing inputs withhold advice (never zero)", () => {
  it("unknown open roster spots", () => {
    const out = buildAdviceInput({ view: view(), pool, adviceCtx: { context: { cutLadder: { rungs: [] } }, boardValues: {} }, applyDraftProgress });
    expect(out.input).toBeNull();
    expect(out.reason).toBe("roster_context_incomplete");
  });
  it("unknown room pool", () => {
    const v = view();
    delete v.public.total_opening_pool;
    expect(buildAdviceInput({ view: v, pool, adviceCtx: ctx, applyDraftProgress }).reason).toBe("room_pool_unknown");
  });
  it("unknown budget", () => {
    const v = view();
    v.me.private.spendable = null;
    expect(buildAdviceInput({ view: v, pool, adviceCtx: ctx, applyDraftProgress }).reason).toBe("budget_missing");
  });
});

// 2026-11-16 verified sweep: won lots are counted by their CURRENT owner.
// An in-room trade moves a lot (engine.lot_owner → the public `owner`); the
// adapter used to read the original `winner`, so a traded-away rookie stayed
// on the seller's roster and a traded-for one never reached the buyer's.
describe("won lots follow the current owner, not the original winner", () => {
  const closed = (id, player, winner, owner, price) => ({ id, player, status: "closed", price, leader: null, winner, owner });

  it("a lot S1 won and traded to S2 is no longer S1's", () => {
    const out = buildAdviceInput({
      view: view({ auctions: [closed("A1", "a", "S1", "S2", 40)] }),
      pool,
      adviceCtx: ctx,
      applyDraftProgress,
    });
    expect(out.held).toEqual([]);
    expect(out.progress.openRosterSpots).toBe(3); // no roster room consumed
    expect(out.input.rookies.map((r) => r.id)).not.toContain("a"); // sold: not a candidate either
  });

  it("a lot S2 won and traded to S1 is S1's purchase and occupies its roster room", () => {
    const out = buildAdviceInput({
      view: view({ auctions: [closed("A2", "b", "S2", "S1", 20)] }),
      pool,
      adviceCtx: ctx,
      applyDraftProgress,
    });
    expect(out.held).toEqual([{ id: "b", name: "Bravo", price: 20, state: "won" }]);
    expect(out.progress.openRosterSpots).toBe(2);
  });

  it("an untraded win is still the winner's (owner === winner)", () => {
    const out = buildAdviceInput({
      view: view({ auctions: [closed("A3", "c", "S1", "S1", 5)] }),
      pool,
      adviceCtx: ctx,
      applyDraftProgress,
    });
    expect(out.held).toEqual([{ id: "c", name: "Charlie", price: 5, state: "won" }]);
  });

  it("withholds advice when a closed lot's owner is not stated (unknown roster room)", () => {
    const lot = { id: "A4", player: "a", status: "closed", price: 40, leader: null, winner: "S1" };
    const out = buildAdviceInput({ view: view({ auctions: [lot] }), pool, adviceCtx: ctx, applyDraftProgress });
    expect(out.input).toBeNull();
    expect(out.reason).toBe("lot_owner_unknown");
  });
});
