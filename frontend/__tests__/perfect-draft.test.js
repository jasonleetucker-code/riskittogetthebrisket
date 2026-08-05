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
  consumptionOrder,
  displacementCost,
  evaluateBid,
  logPriceDispersion,
  priceBand,
  PRICE_DISPERSION_PRIOR,
  planPositionBalance,
  positionalNeeds,
  contestedPrice,
  priceSigmaByTier,
  releaseCost,
  releaseCostForK,
  replacementCost,
  solveFrontier,
  strategyMultiplier,
  surplusOverReplacement,
  valueSigmas,
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

describe("per-player value uncertainty is real, not a flat constant", () => {
  // This block exists because the code READ `marketDispersionCV` and
  // `singleSource` from day one while nothing in the draft data path ever set
  // them. Every rookie silently took the same `defaultCv`, so the sigma term
  // was decorative. These assertions fail against that version.

  const plansWith = (...players) => [{ players, displacement: 0 }];

  it("uses the board's own dispersion where the board measured it", () => {
    const { sigmas } = valueSigmas(
      plansWith(
        { id: "a", marketDispersionCV: 0.02, surplus: 1, price: 1 },
        { id: "b", marketDispersionCV: 0.14, surplus: 1, price: 1 },
      ),
    );
    expect(sigmas.get("a")).toBe(0.02);
    expect(sigmas.get("b")).toBe(0.14);
  });

  it("treats an unmeasured rookie as the pessimistic end of the measured range", () => {
    // The trap this encodes: on the live board a missing CV means "covered by
    // one source", i.e. the LEAST trustworthy rows. Handing them a low sigma —
    // or the 0.0 the pipeline literally computes — would present them as the
    // most certain values on the board.
    const observed = [0.01, 0.02, 0.03, 0.04, 0.2];
    const { sigmas, unobservedCv } = valueSigmas(
      plansWith(
        ...observed.map((cv, i) => ({
          id: `obs-${i}`,
          marketDispersionCV: cv,
          surplus: 1,
          price: 1,
        })),
        { id: "thin", marketDispersionCV: null, surplus: 1, price: 1 },
      ),
    );
    expect(unobservedCv).toBe(0.2);
    expect(sigmas.get("thin")).toBe(0.2);
    expect(sigmas.get("thin")).toBeGreaterThan(sigmas.get("obs-0"));
  });

  it("falls back to the declared default when there is nothing to measure", () => {
    const { sigmas, unobservedCv, observedCount } = valueSigmas(
      plansWith({ id: "a", marketDispersionCV: null, surplus: 1, price: 1 }),
      { defaultCv: 0.08 },
    );
    expect(observedCount).toBe(0);
    expect(unobservedCv).toBe(0.08);
    expect(sigmas.get("a")).toBe(0.08);
  });

  it("floors a single-source rookie above its own reported dispersion", () => {
    const { sigmas } = valueSigmas(
      plansWith({ id: "a", marketDispersionCV: 0.02, singleSource: true, surplus: 1, price: 1 }),
    );
    expect(sigmas.get("a")).toBe(0.35);
  });

  it("changes the confidence when a single-source rookie enters the plan", () => {
    // The assertion that would have caught the unwired field. Against the
    // shipped version both branches return the same number, because
    // `singleSource` never reached the solver.
    const shared = {
      budget: 20,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
    };
    const trusted = optimizeDraft({
      ...shared,
      rookies: [rookie("p", 5200, 20, { marketDispersionCV: 0.02 }), rookie("q", 5000, 20)],
    });
    const shaky = optimizeDraft({
      ...shared,
      rookies: [
        rookie("p", 5200, 20, { marketDispersionCV: 0.02, singleSource: true }),
        rookie("q", 5000, 20),
      ],
    });
    expect(shaky.confidence).not.toBe(trusted.confidence);
    // And in the right direction: a wobblier favourite wins fewer scenarios.
    expect(shaky.confidence).toBeLessThan(trusted.confidence);
  });
});

describe("price dispersion is measured from this draft, not assumed", () => {
  it("is the declared prior before any pick has landed", () => {
    const s = priceSigmaByTier({ tierPriceRatios: { S: [], A: [] }, allPriceRatios: [] });
    expect(s.global).toBe(PRICE_DISPERSION_PRIOR);
    expect(s.S).toBe(PRICE_DISPERSION_PRIOR);
    expect(s.measured).toBe(false);
    expect(s.sampleCount).toBe(0);
  });

  it("learns a tight room and a loose room differently", () => {
    const tight = priceSigmaByTier({
      tierPriceRatios: { S: [1.01, 0.99, 1.0, 1.02, 0.98, 1.0] },
      allPriceRatios: [1.01, 0.99, 1.0, 1.02, 0.98, 1.0],
    });
    const loose = priceSigmaByTier({
      tierPriceRatios: { S: [1.8, 0.5, 1.4, 0.7, 2.1, 0.6] },
      allPriceRatios: [1.8, 0.5, 1.4, 0.7, 2.1, 0.6],
    });
    expect(tight.S).toBeLessThan(loose.S);
    expect(tight.S).toBeLessThan(PRICE_DISPERSION_PRIOR);
    expect(tight.measured).toBe(true);
  });

  it("gives a one-sale tier the board-wide number, not a spread of its own", () => {
    const calm = [1.0, 1.01, 0.99, 1.0, 1.02, 0.98];
    const s = priceSigmaByTier({
      tierPriceRatios: { S: calm, A: [1.4] },
      allPriceRatios: [...calm, 1.4],
    });
    // One observation has no spread; A inherits the board's exactly.
    expect(s.A).toBe(s.global);
    // And S, which has a real sample, is allowed to be tighter than the board.
    expect(s.S).toBeLessThan(s.global);
  });

  it("lands a thin-but-real tier sample between its own spread and the board's", () => {
    const calm = Array.from({ length: 12 }, (_, i) => 1 + (i % 2 ? 0.01 : -0.01));
    const wild = [1.9, 0.55];
    const s = priceSigmaByTier({
      tierPriceRatios: { S: calm, A: wild },
      allPriceRatios: [...calm, ...wild],
    });
    const aAlone = logPriceDispersion(wild, { globalPrior: 0, minSamples: 2 });
    expect(s.A).toBeLessThan(aAlone);
    expect(s.A).toBeGreaterThan(s.global);
  });

  it("drops giveaways and unpriced rows instead of clamping them", () => {
    // ln(paid/expected) is undefined at zero on either side; a $0 sale is not
    // an observation of price pressure.
    expect(logPriceDispersion([1.1, 0, -2, 1.3, null])).toBe(
      logPriceDispersion([1.1, 1.3]),
    );
  });
});

describe("price risk shows up as affordability risk", () => {
  const ceilingPlan = {
    budget: 100,
    openRosterSpots: 5,
    cutLadder: ladder(1, 1, 1, 1, 1),
    waiverValues: {},
    rookies: [rookie("p", 6000, 60), rookie("q", 5800, 40), rookie("r", 900, 5)],
  };

  it("reports how much the plan costs if bids run high", () => {
    const out = optimizeDraft({ ...ceilingPlan, priceSigmaFor: () => 0.3 });
    expect(out.meta.spendAtP75).toBeGreaterThan(out.plan.spend);
    expect(out.meta.budgetHeadroomAtP75).toBe(out.meta.budget - out.meta.spendAtP75);
  });

  it("says nothing rather than zero when no price sigma was supplied", () => {
    // "Not measured" and "no risk" must not render identically.
    const out = optimizeDraft(ceilingPlan);
    expect(out.meta.spendAtP75).toBeNull();
    expect(out.meta.budgetHeadroomAtP75).toBeNull();
  });

  it("finds a plan that is affordable at the median and short at p75", () => {
    const out = optimizeDraft({ ...ceilingPlan, priceSigmaFor: () => 0.4 });
    expect(out.plan.spend).toBeLessThanOrEqual(out.meta.budget);
    expect(out.meta.budgetHeadroomAtP75).toBeLessThan(0);
  });

  it("costs a budget-ceiling plan the confidence a cheap fallback keeps", () => {
    const calm = optimizeDraft(ceilingPlan);
    const stormy = optimizeDraft({ ...ceilingPlan, priceSigmaFor: () => 0.5 });
    expect(stormy.confidence).toBeLessThan(calm.confidence);
    // Nothing is ever infeasible here — the $5 rookie is always affordable, so
    // the favourite loses share to a cheaper plan rather than to nothing.
    // That IS the mechanism when a fallback exists.
    expect(stormy.meta.infeasibleDraws).toBe(0);
  });

  it("hands scenarios it cannot afford to the do-nothing plan", () => {
    // Both rookies sit against the ceiling, so in many draws neither is
    // buyable. The frontier already carries an empty k=0 plan, so "buy
    // nothing" competes as a plan rather than being an uncredited hole — and
    // the recommendation's confidence falls accordingly.
    const shared = {
      budget: 100,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      rookies: [rookie("p", 6000, 95), rookie("q", 5800, 92)],
    };
    const calm = optimizeDraft(shared);
    const stormy = optimizeDraft({ ...shared, priceSigmaFor: () => 0.5 });
    expect(stormy.confidence).toBeLessThan(calm.confidence);
    const doNothing = stormy.frontier.find((p) => p.k === 0);
    expect(doNothing).toBeTruthy();
  });

  it("counts the draws in which nothing at all was affordable", () => {
    // Only reachable when a caller assesses a hand-built list with no
    // do-nothing plan in it — which is why the counter exists rather than
    // being folded into the empty plan's win share.
    const plan = (id, price) => ({
      k: 1,
      players: [{ id, price, surplus: 1000 }],
      displacement: 0,
      spend: price,
      netValue: 1000,
    });
    const out = assessPlans([plan("p", 95), plan("q", 92)], {
      budget: 100,
      priceSigmaFor: () => 0.5,
      draws: 400,
    });
    expect(out.meta.infeasibleDraws).toBeGreaterThan(0);
    expect(out.plans.reduce((s, p) => s + p.winProbability, 0)).toBeLessThan(1);
  });

  it("leaves a plan with plenty of room alone", () => {
    const roomy = {
      budget: 400,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      rookies: [rookie("p", 6000, 20), rookie("q", 500, 5)],
    };
    const calm = optimizeDraft(roomy);
    const stormy = optimizeDraft({ ...roomy, priceSigmaFor: () => 0.5 });
    expect(stormy.confidence).toBe(calm.confidence);
    expect(stormy.meta.infeasibleDraws).toBe(0);
  });

  it("stays deterministic once price is in the draw", () => {
    const opts = { ...ceilingPlan, priceSigmaFor: () => 0.4 };
    expect(optimizeDraft(opts).confidence).toBe(optimizeDraft(opts).confidence);
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


describe("replacement level declines — W(k)", () => {
  // The shipped model charged every addition the SAME waiverValue(pos), which
  // quietly assumes you can sign the best free agent k times over. You cannot.

  it("accumulates the ladder rather than repeating its first rung", () => {
    const rungs = [2000, 1800, 1700, 1600];
    expect(replacementCost(0, rungs, 4)).toBe(0);
    expect(replacementCost(1, rungs, 1)).toBe(2000);
    expect(replacementCost(3, rungs, 3)).toBe(5500);
    // Not 3 x 2000 — that is the bug this replaces.
    expect(replacementCost(3, rungs, 3)).toBeLessThan(3 * rungs[0]);
  });

  it("charges the LAST free agents forgone, not the best ones", () => {
    // The subtlety that makes this a tail. An idle team fills all five open
    // spots off the wire, so buying one rookie costs the FIFTH-best free
    // agent — the top four are still signed.
    const rungs = [2000, 1800, 1700, 1600, 900];
    expect(replacementCost(1, rungs, 5)).toBe(900);
    expect(replacementCost(2, rungs, 5)).toBe(2500);
    // Once every open spot is used the charge saturates at the whole ladder.
    expect(replacementCost(5, rungs, 5)).toBe(8000);
    expect(replacementCost(9, rungs, 5)).toBe(8000);
  });

  it("charges nothing when the roster has more spots than the league has free agents", () => {
    // Five spots, three free agents: buying two rookies still leaves room to
    // sign all three. Nothing is given up.
    expect(replacementCost(2, [1500, 1400, 1300], 5)).toBe(0);
  });

  it("costs a release its whole value, not its value over waivers", () => {
    // ECC is measured over waiver level because the shipped model measured
    // rookie gain the same way and the two cancelled. Under a ladder they no
    // longer cancel, and ECC would take the waiver credit twice.
    const rung = { baseValue: 1500, effectiveCutCost: 0, scarcityMultiplier: 1 };
    expect(releaseCost(rung)).toBe(1500);
    // An unranked player is the case that mattered: ECC of exactly zero made
    // him a free cut, which is the failure ADR-010 set out to prevent.
    const unranked = {
      baseValue: 1400,
      effectiveCutCost: 0,
      valueBasis: "assumedWaiver",
      scarcityMultiplier: 1,
    };
    expect(releaseCost(unranked)).toBe(1400);
  });

  it("takes the cheapest cuts by release cost, not in ECC order", () => {
    // Exact, not a heuristic: the backend's rungs are jointly droppable, and
    // every subset of an independent set in a matroid is independent.
    const rungs = [
      { baseValue: 3000, effectiveCutCost: 0, scarcityMultiplier: 1 },
      { baseValue: 1000, effectiveCutCost: 500, scarcityMultiplier: 1 },
    ];
    expect(releaseCostForK(1, rungs, 0)).toBe(1000);
    expect(releaseCostForK(2, rungs, 0)).toBe(4000);
    expect(releaseCostForK(3, rungs, 0)).toBeNull();
  });

  it("treats a missing ladder as the previous flat model, not as zero cost", () => {
    const flat = optimizeDraft({
      budget: 50,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: { WR: 1500 },
      rookies: [rookie("a", 2000, 10), rookie("b", 1900, 10)],
    });
    expect(flat.plan.netValue).toBe(900);
    expect(flat.plan.replacement).toBe(0);
  });

  it("nets gross minus R(k) minus releases, and the rows add up to it", () => {
    const out = optimizeDraft({
      budget: 50,
      openRosterSpots: 2,
      cutLadder: ladder(1, 1, 1),
      waiverValues: { WR: 1500 },
      waiverLadder: [1500, 1400, 1300],
      rookies: [rookie("a", 2000, 10), rookie("b", 1900, 10)],
    });
    expect(out.plan.k).toBe(2);
    expect(out.plan.grossSurplus).toBe(3900);
    expect(out.plan.replacement).toBe(2900);
    expect(out.plan.displacement).toBe(0);
    expect(out.plan.netValue).toBe(1000);
    const forgone = out.plan.players.map((p) => p.replacementForgone).sort((x, y) => y - x);
    expect(forgone).toEqual([1500, 1400]);
    expect(forgone.reduce((s, v) => s + v, 0)).toBe(out.plan.replacement);
  });

  it("pairs the best rookie with the best free agent forgone", () => {
    const out = optimizeDraft({
      budget: 50,
      openRosterSpots: 2,
      cutLadder: ladder(1, 1, 1),
      waiverValues: {},
      waiverLadder: [1500, 1400, 1300],
      rookies: [rookie("big", 5000, 10), rookie("small", 2000, 10)],
    });
    expect(out.plan.players.find((p) => p.id === "big").replacementForgone).toBe(1500);
    expect(out.plan.players.find((p) => p.id === "small").replacementForgone).toBe(1400);
  });

  it("charges a concentrated plan MORE than the flat model did", () => {
    // The documented direction, checked rather than trusted: k additions at
    // one position paid k x that position's single best free agent, below the
    // top-k of the pool whenever other positions rank higher.
    const shared = {
      budget: 50,
      openRosterSpots: 3,
      cutLadder: ladder(1, 1, 1),
      waiverValues: { WR: 1400 },
      rookies: [rookie("a", 3000, 5), rookie("b", 2900, 5), rookie("c", 2800, 5)],
    };
    const flat = optimizeDraft(shared);
    const wk = optimizeDraft({ ...shared, waiverLadder: [1800, 1700, 1600] });
    expect(wk.plan.replacement).toBe(5100);
    expect(3 * shared.waiverValues.WR).toBe(4200);
    expect(wk.plan.k).toBe(flat.plan.k);
    expect(wk.plan.netValue).toBeLessThan(flat.plan.netValue);
  });

  it("can change WHICH plan wins, not just its score", () => {
    const shared = {
      budget: 30,
      openRosterSpots: 3,
      cutLadder: ladder(1, 1, 1),
      waiverValues: { WR: 100 },
      rookies: [
        rookie("stud", 5000, 30),
        rookie("x", 1800, 10),
        rookie("y", 1800, 10),
        rookie("z", 1800, 10),
      ],
    };
    const flat = optimizeDraft(shared);
    const wk = optimizeDraft({ ...shared, waiverLadder: [1600, 1600, 1600] });
    expect(flat.plan.players.map((p) => p.id).sort()).toEqual(["x", "y", "z"]);
    expect(wk.plan.players.map((p) => p.id)).toEqual(["stud"]);
  });

  it("stops filling the roster once releases cost what rookies are worth", () => {
    // The behaviour the ECC-of-zero bug suppressed: with 23 of 30 rungs free,
    // the model filled every spot with $1 rookies. Charging the release its
    // real value is what terminates it.
    const rungs = Array.from({ length: 5 }, () => ({
      playerId: "x",
      name: "Bench",
      position: "WR",
      baseValue: 1800,
      effectiveCutCost: 0,
      valueBasis: "assumedWaiver",
      scarcityMultiplier: 1,
    }));
    const rookies = Array.from({ length: 5 }, (_, i) => rookie(`r${i}`, 1700, 1));
    const out = optimizeDraft({
      budget: 20,
      openRosterSpots: 0,
      cutLadder: rungs,
      waiverValues: {},
      waiverLadder: [1600, 1600, 1600, 1600, 1600],
      rookies,
    });
    // Every rookie is worth less than the player he would replace.
    expect(out.plan.k).toBe(0);
  });

  it("leaves a spot open rather than displacing a genuinely good free agent", () => {
    // Six open spots and six free agents, one of whom is a star. Filling all
    // six means giving him up; filling five keeps him. The tail model sees
    // that, and a top-k charge could not: it would price every plan against
    // the star and recommend taking all six.
    const rookies = Array.from({ length: 6 }, (_, i) => rookie(`r${i}`, 1650, 5));
    const out = optimizeDraft({
      budget: 30,
      openRosterSpots: 6,
      cutLadder: [],
      waiverValues: {},
      waiverLadder: [5000, 100, 100, 100, 100, 100],
      rookies,
    });
    expect(out.plan.k).toBe(5);
    // 5 x 1650 gross, forgoing the five cheap free agents (5 x 100).
    expect(out.plan.netValue).toBe(5 * 1650 - 500);
    // Taking the sixth would cost the 5000-value star and lose 3350 of net.
    const six = out.frontier.find((p) => p.k === 6);
    expect(six.netValue).toBe(6 * 1650 - 5500);
    expect(six.netValue).toBeLessThan(out.plan.netValue);
  });

  it("keeps realized results on the same footing as the plan", () => {
    const stats = {
      enrichedPlayers: [
        { id: "a", name: "A", pos: "WR", boardValue: 2000, drafted: true, mine: true, pick: { amount: 10 } },
        { id: "b", name: "B", pos: "WR", boardValue: 1900, drafted: true, mine: true, pick: { amount: 8 } },
      ],
    };
    const out = realizedResults({
      stats,
      waiverValues: { WR: 1500 },
      waiverLadder: [1500, 1400, 1300],
      cutLadder: ladder(1, 1, 1),
      openRosterSpots: 2,
    });
    expect(out.grossSurplus).toBe(3900);
    expect(out.replacement).toBe(2900);
    expect(out.netValue).toBe(1000);
  });
});


describe("confidence scores the same objective the solver optimized", () => {
  it("subtracts R(k) in the bootstrap, not only in the frontier", () => {
    // The defect this pins: under the ladder model an item's `surplus` is the
    // RAW board value, so a bootstrap that nets only `displacement` leaves the
    // whole k-dependent waiver charge out — and systematically flatters the
    // largest plan, which is exactly the plan the charge exists to discipline.
    const plans = [
      // Smaller plan, genuinely better once R(k) is paid.
      { k: 1, players: [{ id: "a", surplus: 5000, price: 10 }], replacement: 100, displacement: 0 },
      // Bigger plan: more gross, but it forgoes far more on waivers.
      {
        k: 3,
        players: [
          { id: "b", surplus: 2000, price: 5 },
          { id: "c", surplus: 2000, price: 5 },
          { id: "d", surplus: 2000, price: 5 },
        ],
        replacement: 5000,
        displacement: 0,
      },
    ];
    // net: plan1 = 4900, plan2 = 1000. Plan 1 must win nearly every draw.
    const out = assessPlans(plans, { draws: 200 });
    expect(out.plans[0].winProbability).toBeGreaterThan(0.9);
    // Ignoring `replacement` would score them 5000 vs 6000 and flip the winner.
    expect(out.plans[1].winProbability).toBeLessThan(0.1);
  });

  it("agrees with the solver's own ranking on a real ladder solve", () => {
    const out = optimizeDraft({
      budget: 40,
      openRosterSpots: 4,
      cutLadder: ladder(1, 1, 1, 1),
      waiverValues: {},
      waiverLadder: [3000, 200, 200, 200],
      rookies: [
        rookie("big", 6000, 20),
        rookie("m1", 2500, 7),
        rookie("m2", 2500, 7),
        rookie("m3", 2500, 6),
      ],
    });
    // The recommendation is the solver's own best, and the bootstrap agrees
    // with its ordering rather than scoring a different objective. Confidence
    // itself is deliberately NOT asserted to be high: these plans are close,
    // and a low number there is the honest answer.
    const top = out.frontier[0];
    expect(out.plan.k).toBe(top.k);
    const ranked = [...out.frontier]
      .filter((p) => p.k > 0)
      .sort((a, b) => b.netValue - a.netValue);
    expect(ranked[0].k).toBe(out.plan.k);
    expect(out.confidence).toBeGreaterThan(0);
  });
});

describe("positional balance is reported, not optimized", () => {
  const ctx = {
    rosterByPosition: { QB: 5, RB: 1, WR: 9, TE: 7, DL: 9, LB: 7, DB: 10, K: 1 },
    startersByPosition: {
      QB: 1, RB: 2, WR: 3, TE: 2, K: 1, DL: 3, LB: 3, DB: 3,
      FLEX: 2, SUPER_FLEX: 1,
    },
  };

  it("measures need against the league's own starters, not a constant", () => {
    const { needs, requirements } = positionalNeeds(ctx);
    // One RB short of the two this league starts.
    expect(needs).toEqual({ RB: 1 });
    // FLEX slots are not a position anybody can be short of.
    expect(requirements.FLEX).toBeUndefined();
    expect(requirements.SUPER_FLEX).toBeUndefined();
  });

  it("says nothing is short when the roster already covers every slot", () => {
    const { needs } = positionalNeeds({
      rosterByPosition: { QB: 3, RB: 4 },
      startersByPosition: { QB: 1, RB: 2 },
    });
    expect(needs).toEqual({});
  });

  it("reports which needs a plan fills and which it leaves open", () => {
    const plan = { players: [rookie("a", 5000, 10), { ...rookie("b", 4000, 10), pos: "RB" }] };
    const out = planPositionBalance(plan, ctx);
    expect(out.filled).toEqual(["RB"]);
    expect(out.unmet).toEqual({});
  });

  it("does not pretend a plan filled a need it ignored", () => {
    const plan = { players: [rookie("a", 5000, 10)] }; // WR
    const out = planPositionBalance(plan, ctx);
    expect(out.filled).toEqual([]);
    expect(out.unmet).toEqual({ RB: 1 });
  });

  it("degrades to empty rather than guessing when the context is absent", () => {
    expect(positionalNeeds().needs).toEqual({});
    expect(planPositionBalance({ players: [] }, {}).unmet).toEqual({});
  });
});

describe("opponent-aware pricing", () => {
  it("leaves fair value alone by default", () => {
    expect(contestedPrice({ price: 40, bayesianTopCompetitor: 5 })).toBe(40);
    expect(contestedPrice({ price: 40, bayesianTopCompetitor: 5 }, "fair")).toBe(40);
  });

  it("caps the price at one dollar past the richest interested rival", () => {
    // The late-draft failure mode: the board still asks $40 for a rookie
    // nobody left can bid $10 on.
    expect(contestedPrice({ price: 40, bayesianTopCompetitor: 9 }, "contested")).toBe(10);
  });

  it("never raises a price above fair value", () => {
    expect(contestedPrice({ price: 12, bayesianTopCompetitor: 900 }, "contested")).toBe(12);
  });

  it("never goes below the auction minimum", () => {
    expect(contestedPrice({ price: 40, bayesianTopCompetitor: 0 }, "contested")).toBe(1);
  });

  it("falls back to fair value when no opponent estimate exists", () => {
    expect(contestedPrice({ price: 25 }, "contested")).toBe(25);
    expect(contestedPrice({ price: 25, bayesianTopCompetitor: null }, "contested")).toBe(25);
  });

  it("buys more of the board once rivals are broke", () => {
    const shared = {
      budget: 30,
      openRosterSpots: 5,
      cutLadder: ladder(1, 1, 1, 1, 1),
      waiverValues: {},
      waiverLadder: [100, 100, 100, 100, 100],
    };
    const raw = [
      { ...rookie("a", 5000, 25), bayesianTopCompetitor: 4 },
      { ...rookie("b", 4800, 25), bayesianTopCompetitor: 4 },
    ];
    const fair = optimizeDraft({ ...shared, rookies: raw });
    const contested = optimizeDraft({
      ...shared,
      rookies: raw.map((r) => ({ ...r, price: contestedPrice(r, "contested") })),
    });
    // At fair prices only one is affordable; against a broke room, both are.
    expect(fair.plan.k).toBe(1);
    expect(contested.plan.k).toBe(2);
  });
});

describe("live bidding", () => {
  const input = {
    budget: 60,
    openRosterSpots: 5,
    cutLadder: ladder(1, 1, 1, 1, 1),
    waiverValues: {},
    waiverLadder: [100, 100, 100, 100, 100],
    rookies: [rookie("star", 6000, 30), rookie("alt", 5800, 30), rookie("cheap", 900, 5)],
  };

  it("says keep bidding while the price is well under the max", () => {
    const out = evaluateBid(input, "star", 5);
    expect(out.verdict).toBe("go");
    expect(out.planMaxBid).toBeGreaterThan(5);
  });

  it("warns as the bidding approaches the indifference price", () => {
    const max = computeMaxBid(input, "star").planMaxBid;
    expect(evaluateBid(input, "star", max).verdict).toBe("limit");
    expect(evaluateBid(input, "star", Math.round(max * 0.95)).verdict).toBe("limit");
  });

  it("says let him go past the max", () => {
    const max = computeMaxBid(input, "star").planMaxBid;
    expect(evaluateBid(input, "star", max + 1).verdict).toBe("stop");
  });

  it("prices the CURRENT bid, not the expected price", () => {
    // The two diverge exactly when it matters: mid-auction with the bid
    // climbing past what the board assumed.
    const cheapBid = evaluateBid(input, "star", 5);
    const dearBid = evaluateBid(input, "star", 50);
    expect(cheapBid.netIfWon).toBeGreaterThan(dearBid.netIfWon);
  });

  it("names the fallback plan for when the bidding is lost", () => {
    const out = evaluateBid(input, "star", 999);
    expect(out.verdict).toBe("stop");
    expect(out.pivot.players.length).toBeGreaterThan(0);
    expect(out.pivot.players.some((p) => p.id === "star")).toBe(false);
  });

  it("reports the gain over walking away, negative when there is none", () => {
    const good = evaluateBid(input, "star", 5);
    expect(good.gain).toBeGreaterThan(0);
    // A bid above the budget leaves no buildable plan containing him.
    const impossible = evaluateBid(input, "star", 500);
    expect(impossible.netIfWon).toBeNull();
    expect(impossible.gain).toBeNull();
    expect(impossible.verdict).toBe("stop");
  });
});

describe("one consumption order, shared by every consumer", () => {
  // The backend ships rungs ascending by ECC (value OVER waiver level); the
  // ladder model charges the cheapest by releaseCost (the whole value). Those
  // orders are unrelated — a rung with ECC 0 can be the most expensive release
  // on the board. Anything that walks the ladder in the wrong one charges a
  // player twice and another never.
  const rungs = [
    // Backend order: ECC ascending. Release order is the REVERSE.
    { playerId: "A", name: "A", position: "WR", effectiveCutCost: 0, baseValue: 3000, scarcityMultiplier: 1 },
    { playerId: "B", name: "B", position: "WR", effectiveCutCost: 500, baseValue: 1000, scarcityMultiplier: 1 },
  ];
  const waiverLadder = [500, 400, 300, 200];

  it("orders cuts by release cost under the ladder, by ECC without it", () => {
    expect(consumptionOrder(rungs, waiverLadder).map((r) => r.playerId)).toEqual(["B", "A"]);
    expect(consumptionOrder(rungs, null).map((r) => r.playerId)).toEqual(["A", "B"]);
  });

  it("never re-offers a cut a purchase already consumed", () => {
    // Buy one rookie with no open spots: the plan charges B (cheapest release).
    const after = applyDraftProgress({
      openRosterSpots: 0,
      cutLadder: rungs,
      waiverLadder,
      rookiesBought: 1,
    });
    expect(after.rungsUsed).toBe(1);
    // B is gone — not A. Slicing the ECC head would leave B available and
    // charge him a second time on the next purchase.
    expect(after.cutLadder.map((r) => r.playerId)).toEqual(["A"]);
  });

  it("charges realized purchases exactly what the plan would have charged", () => {
    // The invariant that makes "bought so far" comparable to "the plan", which
    // is the entire stated purpose of realizedResults.
    const shared = {
      openRosterSpots: 0,
      cutLadder: rungs,
      waiverLadder,
      waiverValues: {},
    };
    const players = [
      { id: "r1", name: "R1", pos: "WR", boardValue: 5000 },
      { id: "r2", name: "R2", pos: "WR", boardValue: 4000 },
    ];
    const realized = realizedResults({
      ...shared,
      stats: {
        enrichedPlayers: players.map((p) => ({
          ...p,
          drafted: true,
          mine: true,
          pick: { amount: 5 },
        })),
      },
    });
    const planned = solveFrontier({
      ...shared,
      budget: 10,
      rookies: players.map((p) => ({ ...p, price: 5 })),
    }).frontier.find((f) => f.k === 2);

    expect(realized.grossSurplus).toBe(planned.grossSurplus);
    expect(realized.replacement).toBe(planned.replacement);
    // Taking ECC here (0 + 500) against the plan's releaseCost (1000 + 3000)
    // made the two incomparable by 3500 on this fixture, and by ~everything on
    // the live board where 23 of 30 rungs have an ECC of exactly 0.
    expect(realized.displacement).toBe(planned.displacement);
    expect(realized.netValue).toBe(planned.netValue);
  });

  it("leaves the flat model's ECC accounting untouched", () => {
    const realized = realizedResults({
      openRosterSpots: 0,
      cutLadder: rungs,
      waiverValues: { WR: 1000 },
      stats: {
        enrichedPlayers: [
          { id: "r1", name: "R1", pos: "WR", boardValue: 5000, drafted: true, mine: true, pick: { amount: 5 } },
        ],
      },
    });
    // No ladder supplied: ECC order, ECC cost, replacement folded into gross.
    expect(realized.replacement).toBe(0);
    expect(realized.displacement).toBe(0);
    expect(realized.grossSurplus).toBe(4000);
  });
});
