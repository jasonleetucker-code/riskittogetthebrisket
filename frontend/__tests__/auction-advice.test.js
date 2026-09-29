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
