/**
 * Perfect Draft optimizer — the budget solve.
 *
 * These tests pin the properties that make the recommendation trustworthy
 * rather than merely plausible:
 *
 *   * it optimizes the COMBINATION, not each rookie independently (there is an
 *     explicit instance below where greedy value-per-dollar loses to the exact
 *     solve — that is the whole reason this is a knapsack and not a sort);
 *   * each recommended rookie consumes a DISTINCT roster cut, and no cut is
 *     ever counted twice;
 *   * it is free to recommend nothing, to leave money unspent, and to pick any
 *     number of rookies, because this league caps none of those.
 *
 * A note on why the objective subtracts replacement level on both sides: a
 * naive `max sum(boardValue)` is degenerate on real data, because value and
 * price both derive from the same convex Hill curve and value-per-dollar
 * therefore rises ~30x down the rookie ladder. The optimizer would just read
 * the price curve back out and buy dart throws. `surplusOverReplacement` is
 * what makes the objective mean something.
 */

import { describe, expect, it } from "vitest";

import {
  applyDraftProgress,
  assessPlans,
  draftPhase,
  optimizeDraft,
  realizedResults,
  computeMaxBid,
  displacementCost,
  logPriceDispersion,
  priceBand,
  solveFrontier,
  strategyMultiplier,
  surplusOverReplacement,
} from "@/lib/perfect-draft";

/** Cut ladder helper: ascending effective cut costs. */
const ladder = (...costs) =>
  costs.map((c, i) => ({
    playerId: `cut-${i}`,
    name: `Cut ${i}`,
    position: "WR",
    effectiveCutCost: c,
    valueBasis: "board",
  }));

const rookie = (id, boardValue, price, extra = {}) => ({
  id,
  name: id,
  pos: "WR",
  boardValue,
  price,
  ...extra,
});

/** The optimizer's own answer, as the UI would read it. */
const best = (input) => solveFrontier(input).frontier[0];

describe("the objective", () => {
  it("measures a rookie's gain over what the roster spot could hold anyway", () => {
    const waiverValues = { WR: 1200 };
    // A 1721-value rookie is not a 1721-value addition when a 1200-value WR is
    // sitting on waivers for free.
    expect(surplusOverReplacement(rookie("a", 1721, 1), waiverValues)).toBe(521);
  });

  it("treats a rookie below waiver level as worth zero, not negative", () => {
    expect(surplusOverReplacement(rookie("a", 900, 1), { WR: 1200 })).toBe(0);
  });

  it("charges nothing for rookies that fit in open roster spots", () => {
    expect(displacementCost(3, ladder(500, 700, 900), 3)).toBe(0);
    // The 4th rookie is the first that costs a cut.
    expect(displacementCost(4, ladder(500, 700, 900), 3)).toBe(500);
  });

  it("reports infeasible rather than free when the cut ladder runs out", () => {
    expect(displacementCost(5, ladder(500, 700), 0)).toBeNull();
  });
});

describe("the combination is optimized, not each rookie independently", () => {
  it("beats greedy value-per-dollar on an instance where greedy is wrong", () => {
    // Budget $10.  A has the best value-per-dollar (7/6 = 1.17) but taking it
    // strands $4.  B+C together spend the budget exactly for 10.
    const input = {
      budget: 10,
      openRosterSpots: 5,
      cutLadder: ladder(999, 999, 999, 999, 999),
      waiverValues: {},
      rookies: [rookie("A", 7, 6), rookie("B", 5, 5), rookie("C", 5, 5)],
    };

    // What a greedy "best value per dollar, take it if affordable" pass does.
    const greedy = [...input.rookies]
      .sort((x, y) => y.boardValue / y.price - x.boardValue / x.price)
      .reduce(
        (acc, r) =>
          acc.spend + r.price <= input.budget
            ? { spend: acc.spend + r.price, value: acc.value + r.boardValue }
            : acc,
        { spend: 0, value: 0 },
      );
    expect(greedy.value).toBe(7);

    const plan = best(input);
    expect(plan.netValue).toBe(10);
    expect(plan.players.map((p) => p.id).sort()).toEqual(["B", "C"]);
    expect(plan.netValue).toBeGreaterThan(greedy.value);
  });

  it("takes one elite rookie when the budget only reaches that far", () => {
    const plan = best({
      budget: 40,
      openRosterSpots: 5,
      cutLadder: ladder(100, 100, 100, 100, 100),
      waiverValues: {},
      rookies: [rookie("elite", 7500, 38), rookie("cheap", 400, 2)],
    });
    expect(plan.players.map((p) => p.id)).toContain("elite");
    expect(plan.netValue).toBeGreaterThan(7000);
  });

  it("prefers several inexpensive rookies when that is genuinely better", () => {
    const plan = best({
      budget: 30,
      openRosterSpots: 5,
      cutLadder: ladder(10, 10, 10, 10, 10),
      waiverValues: {},
      rookies: [
        rookie("pricey", 3000, 30),
        rookie("a", 1800, 10),
        rookie("b", 1800, 10),
        rookie("c", 1800, 10),
      ],
    });
    expect(plan.players).toHaveLength(3);
    expect(plan.netValue).toBeGreaterThan(3000 - 10);
  });
});

describe("spending is never forced", () => {
  it("leaves money unspent when the last rookie is not worth its cut", () => {
    // One open spot; the second rookie would cost a 5000-value cut to add a
    // 1500-value body.
    const plan = best({
      budget: 100,
      openRosterSpots: 1,
      cutLadder: ladder(5000, 6000),
      waiverValues: {},
      rookies: [rookie("good", 6000, 20), rookie("filler", 1500, 5)],
    });
    expect(plan.players.map((p) => p.id)).toEqual(["good"]);
    expect(plan.spend).toBeLessThan(100);
  });

  it("recommends nothing when no rookie clears replacement level", () => {
    const plan = best({
      budget: 100,
      openRosterSpots: 5,
      cutLadder: ladder(10, 10, 10, 10, 10),
      waiverValues: { WR: 4000 },
      rookies: [rookie("meh", 1000, 5), rookie("worse", 800, 3)],
    });
    expect(plan.players).toEqual([]);
    expect(plan.netValue).toBe(0);
    expect(plan.spend).toBe(0);
  });

  it("handles a team with $0 remaining", () => {
    const out = solveFrontier({
      budget: 0,
      openRosterSpots: 3,
      cutLadder: ladder(100, 200, 300),
      waiverValues: {},
      rookies: [rookie("a", 5000, 20)],
    });
    expect(out.frontier[0].players).toEqual([]);
    expect(out.frontier[0].netValue).toBe(0);
  });
});

describe("displacement is per-rookie and never double-counted", () => {
  it("charges a distinct, escalating cut for each rookie past the open spots", () => {
    const cuts = ladder(500, 900, 1500);
    // Zero open spots: three rookies must cost 500 + 900 + 1500.
    expect(displacementCost(3, cuts, 0)).toBe(2900);
    // Not 3 x 500 — the same cheapest cut reused would be the classic bug.
    expect(displacementCost(3, cuts, 0)).not.toBe(1500);
  });

  it("nets each rookie against a different roster player", () => {
    const cuts = ladder(500, 900, 1500);
    const plan = best({
      budget: 100,
      openRosterSpots: 0,
      cutLadder: cuts,
      waiverValues: {},
      rookies: [rookie("a", 4000, 30), rookie("b", 3800, 30), rookie("c", 3600, 30)],
    });
    expect(plan.players).toHaveLength(3);
    // gross 11400 - (500 + 900 + 1500)
    expect(plan.displacement).toBe(2900);
    expect(plan.netValue).toBe(11400 - 2900);
  });

  it("stops adding rookies once the next cut costs more than the next rookie", () => {
    const plan = best({
      budget: 100,
      openRosterSpots: 0,
      cutLadder: ladder(100, 9000),
      waiverValues: {},
      rookies: [rookie("a", 5000, 10), rookie("b", 4000, 10)],
    });
    expect(plan.players.map((p) => p.id)).toEqual(["a"]);
  });
});

describe("taxi / roster-exemption behaviour", () => {
  it("more exempt spots never lowers the recommended net value", () => {
    const shared = {
      budget: 60,
      cutLadder: ladder(1000, 2000, 3000),
      waiverValues: {},
      rookies: [rookie("a", 4000, 20), rookie("b", 3500, 20), rookie("c", 3000, 20)],
    };
    const none = best({ ...shared, openRosterSpots: 0 });
    const some = best({ ...shared, openRosterSpots: 2 });
    expect(some.netValue).toBeGreaterThanOrEqual(none.netValue);
    // With two exempt spots the first two rookies are free of cut cost.
    expect(some.displacement).toBeLessThan(none.displacement);
  });
});

describe("live draft updates", () => {
  const base = {
    budget: 50,
    openRosterSpots: 3,
    cutLadder: ladder(100, 200, 300),
    waiverValues: {},
    rookies: [rookie("a", 5000, 25), rookie("b", 4000, 25), rookie("c", 3000, 25)],
  };

  it("drops a rookie from the pool once another team drafts him", () => {
    const before = best(base);
    expect(before.players.map((p) => p.id)).toContain("a");

    const after = best({
      ...base,
      rookies: base.rookies.map((r) => (r.id === "a" ? { ...r, drafted: true } : r)),
    });
    expect(after.players.map((p) => p.id)).not.toContain("a");
  });

  it("shrinks the plan when a completed purchase reduces the budget", () => {
    const after = best({ ...base, budget: 25 });
    expect(after.players).toHaveLength(1);
    expect(after.spend).toBeLessThanOrEqual(25);
  });

  it("drops a rookie whose live price has passed what he is worth to the plan", () => {
    const cheap = best({ ...base, rookies: [rookie("a", 5000, 25), rookie("b", 4800, 25)] });
    expect(cheap.players).toHaveLength(2);

    // 'a' gets bid up past the budget's ability to carry both.
    const bidUp = best({
      ...base,
      rookies: [rookie("a", 5000, 45), rookie("b", 4800, 25)],
    });
    expect(bidUp.players.map((p) => p.id)).toEqual(["a"]);
  });
});

describe("missing data is handled, never invented", () => {
  it("excludes and reports rookies with no board value", () => {
    const out = solveFrontier({
      budget: 50,
      openRosterSpots: 3,
      cutLadder: ladder(1, 1, 1),
      waiverValues: {},
      rookies: [rookie("ok", 4000, 10), { id: "ghost", name: "Ghost", pos: "WR", price: 10 }],
    });
    expect(out.frontier[0].players.map((p) => p.id)).toEqual(["ok"]);
    expect(out.excluded).toEqual([
      { id: "ghost", name: "Ghost", reason: "no_board_value" },
    ]);
  });

  it("excludes and reports rookies with no expected price", () => {
    const out = solveFrontier({
      budget: 50,
      openRosterSpots: 3,
      cutLadder: ladder(1, 1, 1),
      waiverValues: {},
      rookies: [rookie("ok", 4000, 10), { id: "np", name: "NoPrice", pos: "WR", boardValue: 900 }],
    });
    expect(out.excluded.map((e) => e.reason)).toEqual(["no_expected_price"]);
  });

  it("survives an empty rookie pool", () => {
    const out = solveFrontier({
      budget: 50,
      openRosterSpots: 3,
      cutLadder: [],
      waiverValues: {},
      rookies: [],
    });
    expect(out.frontier[0].netValue).toBe(0);
  });
});

describe("max bid is an indifference price", () => {
  const input = {
    budget: 40,
    openRosterSpots: 5,
    cutLadder: ladder(1, 1, 1, 1, 1),
    waiverValues: {},
    rookies: [rookie("star", 5000, 20), rookie("alt", 4600, 20), rookie("filler", 300, 5)],
  };

  it("prices the star above his expected cost but below the whole budget", () => {
    const { planMaxBid } = computeMaxBid(input, "star");
    expect(planMaxBid).toBeGreaterThan(20);
    expect(planMaxBid).toBeLessThanOrEqual(40);
  });

  it("returns a dollar figure, not a value-scale number", () => {
    // The bug this guards: `price + (netWith - netWithout)` adds a
    // rankDerivedValue quantity to dollars and yields absurd bids like $4135.
    const { planMaxBid } = computeMaxBid(input, "star");
    expect(planMaxBid).toBeLessThanOrEqual(input.budget);
  });

  it("offers the best plan without him as the pivot", () => {
    const { pivot } = computeMaxBid(input, "star");
    expect(pivot.players.map((p) => p.id)).not.toContain("star");
    expect(pivot.netValue).toBeGreaterThan(0);
  });

  it("gives near-substitutes modest max bids, because the other one exists", () => {
    // Budget $30. x and y are near-identical at $20; z is a useful $10 add-on.
    // Best plan without x is y + z = 6990. Paying $21 for x strands the $9 that
    // would have bought z, dropping to 5000 — so $20 is exactly the ceiling.
    const twins = {
      ...input,
      budget: 30,
      rookies: [rookie("x", 5000, 20), rookie("y", 4990, 20), rookie("z", 2000, 10)],
    };
    const { planMaxBid } = computeMaxBid(twins, "x");
    expect(planMaxBid).toBe(20);
  });

  it("spends the whole budget on him when nothing else is worth saving for", () => {
    // The mirror case, and the reason the ceiling above is not a fixed haircut:
    // with no third option the saved dollars buy nothing, so x is worth the
    // entire budget rather than a premium over his expected price.
    const twins = {
      ...input,
      budget: 25,
      rookies: [rookie("x", 5000, 20), rookie("y", 4990, 20)],
    };
    expect(computeMaxBid(twins, "x").planMaxBid).toBe(25);
  });
});

describe("uncertainty is expressed, not hidden", () => {
  it("derives a multiplicative price band that stays positive at the cheap end", () => {
    const band = priceBand(2, 0.5);
    expect(band.low).toBeGreaterThanOrEqual(1);
    expect(band.low).toBeLessThan(band.expected + 1);
    expect(band.high).toBeGreaterThan(band.expected);
  });

  it("shrinks a thin tier sample toward the global prior", () => {
    const thin = logPriceDispersion([1.1, 1.2], { globalPrior: 0.4, minSamples: 6 });
    const rich = logPriceDispersion([1.1, 1.2, 1.15, 1.12, 1.18, 1.14], {
      globalPrior: 0.4,
      minSamples: 6,
    });
    expect(thin).toBeGreaterThan(rich);
  });

  it("flags two nearly tied plans instead of presenting one as the answer", () => {
    // Two near-identical rookies, only one affordable. They are the same SIZE
    // of plan, so the cardinality frontier alone cannot see the tie — it keeps
    // one winner per k. optimizeDraft adds the pivot plans, which is what makes
    // this coin-flip visible instead of being reported as a single answer.
    const out = optimizeDraft({
      budget: 20,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      rookies: [rookie("p", 5000, 20), rookie("q", 4995, 20)],
    });
    expect(out.confidence).toBeLessThan(0.9);
    expect(out.nearTies.length).toBeGreaterThan(0);
  });

  it("is confident when the best plan is not close", () => {
    const out = optimizeDraft({
      budget: 20,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      rookies: [rookie("p", 8000, 20), rookie("q", 500, 20)],
    });
    expect(out.confidence).toBeGreaterThan(0.9);
    expect(out.nearTies).toEqual([]);
  });

  it("is deterministic across runs so the displayed confidence does not flicker", () => {
    const out = solveFrontier({
      budget: 20,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      rookies: [rookie("p", 5000, 20), rookie("q", 4900, 20)],
    });
    const a = assessPlans(out.frontier, { draws: 200 });
    const b = assessPlans(out.frontier, { draws: 200 });
    expect(a.confidence).toBe(b.confidence);
  });
});

describe("strategy modes", () => {
  it("leaves the canonical board untouched in balanced mode", () => {
    expect(strategyMultiplier(0, "balanced")).toBe(1);
    expect(strategyMultiplier(8, "balanced")).toBe(1);
  });

  it("tilts toward rookies for long-term and away for win-now", () => {
    expect(strategyMultiplier(0, "longTerm")).toBeGreaterThan(1);
    expect(strategyMultiplier(0, "winNow")).toBeLessThan(1);
  });

  it("stays neutral when years of experience are unknown", () => {
    expect(strategyMultiplier(undefined, "longTerm")).toBe(1);
    expect(strategyMultiplier(null, "winNow")).toBe(1);
  });
});

describe("the frontier supplies real alternatives", () => {
  it("exposes a plan at each feasible cardinality, best first", () => {
    const out = solveFrontier({
      budget: 60,
      openRosterSpots: 4,
      cutLadder: ladder(10, 10, 10, 10),
      waiverValues: {},
      rookies: [
        rookie("a", 5000, 30),
        rookie("b", 3000, 20),
        rookie("c", 2500, 10),
        rookie("d", 1000, 10),
      ],
    });
    const ks = out.frontier.map((p) => p.k);
    expect(new Set(ks).size).toBe(ks.length); // one plan per cardinality
    for (let i = 1; i < out.frontier.length; i++) {
      expect(out.frontier[i - 1].netValue).toBeGreaterThanOrEqual(out.frontier[i].netValue);
    }
  });

  it("never invents alternatives the pool cannot support", () => {
    const out = solveFrontier({
      budget: 10,
      openRosterSpots: 2,
      cutLadder: ladder(10, 10),
      waiverValues: {},
      rookies: [rookie("only", 3000, 10)],
    });
    expect(out.frontier.filter((p) => p.k > 0)).toHaveLength(1);
  });
});

describe("monotonicity properties", () => {
  const shared = {
    openRosterSpots: 2,
    cutLadder: ladder(100, 200, 300, 400),
    waiverValues: {},
    rookies: [
      rookie("a", 5000, 30),
      rookie("b", 4000, 25),
      rookie("c", 3000, 15),
      rookie("d", 2000, 10),
    ],
  };

  it("more budget never lowers the recommended net value", () => {
    let prev = -Infinity;
    for (const budget of [0, 10, 25, 40, 60, 80, 100]) {
      const net = best({ ...shared, budget }).netValue;
      expect(net).toBeGreaterThanOrEqual(prev);
      prev = net;
    }
  });

  it("more open roster spots never lowers the recommended net value", () => {
    let prev = -Infinity;
    for (const openRosterSpots of [0, 1, 2, 3, 4]) {
      const net = best({ ...shared, budget: 80, openRosterSpots }).netValue;
      expect(net).toBeGreaterThanOrEqual(prev);
      prev = net;
    }
  });
});

describe("plan invariants", () => {
  // These exist because a subtly wrong reconstruction can leave the DP's
  // VALUES correct while the returned roster repeats a player.  On real data
  // that produced a plan listing the same $1 rookie twelve times, with a
  // net-value figure that looked entirely plausible.  Unit-sized fixtures did
  // not reproduce it; these assert the invariants directly.
  const shared = {
    budget: 60,
    openRosterSpots: 3,
    cutLadder: ladder(100, 200, 300, 400, 500, 600),
    waiverValues: {},
  };

  function assertConsistent(plan) {
    const ids = plan.players.map((p) => p.id);
    expect(new Set(ids).size, `duplicate rookie in plan: ${ids}`).toBe(ids.length);
    expect(plan.players).toHaveLength(plan.k);
    const spend = plan.players.reduce((s, p) => s + p.price, 0);
    expect(spend).toBe(plan.spend);
    const gross = plan.players.reduce((s, p) => s + p.surplus, 0);
    expect(gross).toBeCloseTo(plan.grossSurplus, 6);
    expect(plan.netValue).toBeCloseTo(gross - plan.displacement, 6);
  }

  it("never selects the same rookie twice, at any cardinality", () => {
    // Many equal-priced, equal-value items is the shape that breaks a
    // single-pointer reconstruction.
    const rookies = Array.from({ length: 14 }, (_, i) =>
      rookie(`r${i}`, 2000 + (i % 3), 4),
    );
    const out = solveFrontier({ ...shared, rookies });
    for (const plan of out.frontier) assertConsistent(plan);
  });

  it("keeps spend, gross and net internally consistent on every frontier plan", () => {
    const rookies = [
      rookie("a", 5000, 30),
      rookie("b", 4000, 25),
      rookie("c", 3000, 15),
      rookie("d", 2500, 10),
      rookie("e", 2000, 5),
      rookie("f", 1800, 1),
      rookie("g", 1700, 1),
    ];
    const out = solveFrontier({ ...shared, rookies });
    for (const plan of out.frontier) assertConsistent(plan);
  });

  it("respects the budget on every frontier plan", () => {
    const rookies = Array.from({ length: 20 }, (_, i) => rookie(`r${i}`, 3000 - i * 10, 1 + i));
    const out = solveFrontier({ ...shared, rookies });
    for (const plan of out.frontier) expect(plan.spend).toBeLessThanOrEqual(shared.budget);
  });

  it("returns a consistent plan through the full entry point", () => {
    const rookies = Array.from({ length: 12 }, (_, i) => rookie(`r${i}`, 2500 + i, 3));
    const out = optimizeDraft({ ...shared, rookies });
    const ids = out.plan.players.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(out.plan.spend).toBeLessThanOrEqual(shared.budget);
  });
});

describe("live draft progress", () => {
  // The gap these pin: the roster context is a PRE-DRAFT snapshot. Its open
  // spots and cut ladder do not move when a rookie sells, so they have to be
  // advanced past what has already been bought. Without that, roster room is
  // double-counted and the ladder re-offers cuts already consumed — i.e. it
  // recommends releasing the same player twice.
  const cuts = ladder(100, 400, 900, 1600);

  it("fills open spots before it starts consuming cuts", () => {
    const p = applyDraftProgress({ openRosterSpots: 2, cutLadder: cuts, rookiesBought: 2 });
    expect(p.spotsUsed).toBe(2);
    expect(p.rungsUsed).toBe(0);
    expect(p.openRosterSpots).toBe(0);
    expect(p.cutLadder).toHaveLength(4);
  });

  it("advances the ladder once the open spots are gone", () => {
    const p = applyDraftProgress({ openRosterSpots: 1, cutLadder: cuts, rookiesBought: 3 });
    expect(p.spotsUsed).toBe(1);
    expect(p.rungsUsed).toBe(2);
    expect(p.openRosterSpots).toBe(0);
    // The two cheapest rungs are spent; the next cut costs 900, not 100.
    expect(p.cutLadder.map((r) => r.effectiveCutCost)).toEqual([900, 1600]);
  });

  it("never re-offers a consumed rung", () => {
    const before = applyDraftProgress({ openRosterSpots: 0, cutLadder: cuts, rookiesBought: 0 });
    const after = applyDraftProgress({ openRosterSpots: 0, cutLadder: cuts, rookiesBought: 1 });
    expect(before.cutLadder[0].playerId).toBe("cut-0");
    expect(after.cutLadder[0].playerId).not.toBe("cut-0");
  });

  it("reports an exhausted ladder rather than silently pricing nothing", () => {
    const p = applyDraftProgress({ openRosterSpots: 1, cutLadder: cuts, rookiesBought: 9 });
    expect(p.cutLadder).toEqual([]);
    expect(p.ladderExhausted).toBe(true);
    // Clamped, not negative.
    expect(p.openRosterSpots).toBe(0);
    expect(p.rungsUsed).toBe(4);
  });

  it("is inert before anything is bought", () => {
    const p = applyDraftProgress({ openRosterSpots: 3, cutLadder: cuts, rookiesBought: 0 });
    expect(p).toMatchObject({ openRosterSpots: 3, spotsUsed: 0, rungsUsed: 0 });
    expect(p.ladderExhausted).toBe(false);
  });

  it("makes each successive purchase more expensive to accommodate", () => {
    // The whole point of advancing the ladder: the marginal cost of the next
    // rookie rises as cheap cuts are used up. A stale ladder would quote 100
    // every time.
    const costs = [0, 1, 2, 3].map((bought) => {
      const p = applyDraftProgress({ openRosterSpots: 0, cutLadder: cuts, rookiesBought: bought });
      return displacementCost(1, p.cutLadder, p.openRosterSpots);
    });
    expect(costs).toEqual([100, 400, 900, 1600]);
  });

  it("shrinks the remaining plan as the draft proceeds", () => {
    const rookies = [
      rookie("a", 6000, 20),
      rookie("b", 5000, 20),
      rookie("c", 4000, 20),
    ];
    const base = { waiverValues: {}, budget: 60 };

    const opening = applyDraftProgress({ openRosterSpots: 3, cutLadder: cuts, rookiesBought: 0 });
    const openingPlan = solveFrontier({ ...base, ...opening, rookies }).frontier[0];
    expect(openingPlan.k).toBe(3);
    expect(openingPlan.displacement).toBe(0);

    // Two bought: budget down to $20, one open spot left, ladder untouched.
    const later = applyDraftProgress({ openRosterSpots: 3, cutLadder: cuts, rookiesBought: 2 });
    const laterPlan = solveFrontier({
      ...base,
      ...later,
      budget: 20,
      rookies: rookies.map((r) => (r.id === "a" || r.id === "b" ? { ...r, drafted: true } : r)),
    }).frontier[0];
    expect(laterPlan.players.map((p) => p.id)).toEqual(["c"]);
    expect(laterPlan.displacement).toBe(0); // still one open spot
  });

  it("classifies the phase from picks recorded against the pool", () => {
    expect(draftPhase({ totalPicksMade: 0, rookiePoolSize: 72 })).toBe("pre");
    expect(draftPhase({ totalPicksMade: 5, rookiePoolSize: 72 })).toBe("live");
    expect(draftPhase({ totalPicksMade: 72, rookiePoolSize: 72 })).toBe("complete");
    // No pool size known yet — a recorded pick still means the draft is live.
    expect(draftPhase({ totalPicksMade: 1, rookiePoolSize: 0 })).toBe("live");
    expect(draftPhase(undefined)).toBe("pre");
  });

  it("values what was actually bought the same way it values the plan", () => {
    const stats = {
      enrichedPlayers: [
        { id: "a", name: "A", pos: "WR", boardValue: 6000, drafted: true, mine: true, pick: { amount: 30 } },
        { id: "b", name: "B", pos: "WR", boardValue: 5000, drafted: true, mine: false, pick: { amount: 25 } },
        { id: "c", name: "C", pos: "WR", boardValue: 4000, drafted: false },
      ],
    };
    const out = realizedResults({
      stats,
      waiverValues: { WR: 1000 },
      cutLadder: cuts,
      openRosterSpots: 0,
    });
    // Only MY purchase counts; surplus is over replacement, cost is the rung
    // that purchase consumed.
    expect(out.count).toBe(1);
    expect(out.spend).toBe(30);
    expect(out.grossSurplus).toBe(5000);
    expect(out.displacement).toBe(100);
    expect(out.netValue).toBe(4900);
  });

  it("reports nothing bought before the draft starts", () => {
    const out = realizedResults({
      stats: { enrichedPlayers: [{ id: "a", boardValue: 6000, drafted: false }] },
      waiverValues: {},
      cutLadder: cuts,
      openRosterSpots: 1,
    });
    expect(out).toMatchObject({ count: 0, spend: 0, netValue: 0 });
  });
});
