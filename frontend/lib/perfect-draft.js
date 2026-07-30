/**
 * Perfect Draft — budget-constrained rookie-auction optimizer.
 *
 * Answers: *given this team's remaining draft dollars, its roster, the rookies
 * still available and their expected prices, which COMBINATION of rookies
 * produces the greatest total net increase in roster value?*  Not "which
 * rookies are best" — which SET a budget should buy.
 *
 * ── Why this runs on the client ────────────────────────────────────────────
 *
 * Every input that moves during a draft — team budgets, recorded picks, live
 * prices, the tier-inflation model — lives in this page's localStorage
 * workspace and never reaches the server (see `draft-logic.js`).  The solve is
 * single-digit milliseconds.  Round-tripping the whole workspace on every
 * recorded pick to run it server-side would be strictly worse.
 *
 * What the server does supply, because the client cannot compute it, is the
 * roster context: rosters joined to canonical `rankDerivedValue`, per-position
 * waiver levels, and the Effective Cut Cost ladder (`src/draft/context.py`).
 * Those are static for the whole draft.
 *
 * This is NOT a ranking engine.  It recomputes no player value; it consumes
 * backend stamps exactly as `draft-logic.js` already consumes `rookieKtcValue`.
 *
 * ── The model ──────────────────────────────────────────────────────────────
 *
 *   surplus(i)  = max(0, boardValue(i) - waiverValue(pos_i))
 *   D(k)        = sum of the (k - openRosterSpots) cheapest cut costs
 *   NetValue(S) = sum surplus(i) - D(|S|)
 *
 *   maximize NetValue(S)  subject to  sum price(i) <= budget
 *
 * Both sides are measured over replacement, and that symmetry is the whole
 * trick.  A rookie's gain is not his rating — it is his rating minus what you
 * could have streamed into that roster spot for free.  An empty roster spot is
 * worth waiver level, not zero.  Without this the objective is degenerate:
 * value-per-dollar rises ~30x down the rookie ladder (value and price both come
 * from the same convex Hill curve), so a raw `max sum(value)` just reads the
 * price curve back out and buys thirty $1 dart throws.
 *
 * ── Why D depends only on k ────────────────────────────────────────────────
 *
 * The cut ladder is cheapest-first and independent of WHICH rookies are bought,
 * so total displacement cost is a function of how many you buy. That is what
 * lets one dynamic program answer every cardinality at once — and it is exact,
 * not an approximation: legal cut-sets are the independent sets of the dual of
 * a transversal matroid, where greedy is optimal and successive minimum-weight
 * sets nest.  See `src/draft/displacement.py` for the full argument.
 *
 * There is no fixed-slot constraint anywhere in here, deliberately.  This
 * league sets no minimum or maximum on how many rookies a team may draft; `k`
 * is a free variable and the optimizer chooses it.
 */

/**
 * @typedef {Object} RookieCandidate
 * @property {string}  id          stable slug (`playerSlug` from draft-logic)
 * @property {string}  name
 * @property {string}  pos
 * @property {number}  boardValue  rankDerivedValue (0-9999), backend-stamped
 * @property {number}  price       expected winning price in whole dollars
 * @property {number} [priceSigma] log-space price dispersion, for confidence
 * @property {boolean}[drafted]    already sold — excluded from the pool
 */

/**
 * @typedef {Object} CutRung
 * @property {string} playerId
 * @property {string} name
 * @property {string} position
 * @property {number} effectiveCutCost
 * @property {string} valueBasis  "board" | "assumedWaiver"
 */

/**
 * @typedef {Object} PerfectDraftInput
 * @property {RookieCandidate[]} rookies
 * @property {number}   budget            remaining draft dollars
 * @property {CutRung[]} cutLadder        cheapest-first, from the backend
 * @property {number}   openRosterSpots   rookies addable before any cut
 * @property {Object<string,number>} waiverValues  position -> waiver level
 * @property {string}  [strategy]         "balanced" | "winNow" | "longTerm"
 */

/** Strategy tilts. @see applyStrategy */
export const STRATEGIES = ["balanced", "winNow", "longTerm"];

export const DEFAULT_STRATEGY = "balanced";

/**
 * Experience-based horizon tilt.
 *
 * Deliberately modest, and deliberately keyed on `yearsExp` rather than age:
 * `_age` is absent for 100% of contract rows while `_yearsExp` is present for
 * 84%.  Missing experience returns 1.0 rather than guessing.
 *
 * `balanced` is exactly 1.0 for everything — it IS the canonical board, not a
 * re-weighting of it.  The tilt is a heuristic and is labelled as one in the
 * UI: `rankDerivedValue` is already a dynasty value with age and longevity
 * priced in, so a large tilt would double-count. It is applied identically to
 * rookies and to roster players so the two sides stay comparable.
 */
export function strategyMultiplier(yearsExp, strategy = DEFAULT_STRATEGY) {
  if (strategy === "balanced" || !strategy) return 1;
  // `null` must read as "unknown", not as `Number(null) === 0` — which would
  // silently tilt every player missing `_yearsExp` (16% of the board) as if he
  // were a rookie.
  if (yearsExp === null || yearsExp === undefined || yearsExp === "") return 1;
  const ye = Number(yearsExp);
  if (!Number.isFinite(ye) || ye < 0) return 1;
  if (strategy === "winNow") {
    // Proven production is worth more; unproven rookies slightly less.
    if (ye === 0) return 0.92;
    if (ye <= 2) return 0.98;
    return 1.06;
  }
  if (strategy === "longTerm") {
    if (ye === 0) return 1.08;
    if (ye <= 2) return 1.03;
    return 0.94;
  }
  return 1;
}

/** Waiver level at a position, with the same fallback the backend uses. */
export function waiverValueFor(pos, waiverValues) {
  if (!waiverValues) return 0;
  const key = String(pos || "").trim().toUpperCase();
  if (Number.isFinite(waiverValues[key])) return waiverValues[key];
  const all = Object.values(waiverValues).filter(Number.isFinite);
  return all.length ? Math.min(...all) : 0;
}

/**
 * A rookie's real gain: his value over what the roster spot could hold anyway.
 * Clamped at 0 — a rookie below waiver level is not a negative asset, he is
 * simply not worth a roster spot, and the optimizer expresses that by not
 * selecting him.
 */
export function surplusOverReplacement(rookie, waiverValues, strategy = DEFAULT_STRATEGY) {
  const v = Number(rookie?.boardValue);
  if (!Number.isFinite(v) || v <= 0) return 0;
  // Passed through as-is: `?? 0` here would undo the unknown-experience guard
  // in strategyMultiplier and tilt every player missing yearsExp as a rookie.
  const tilt = strategyMultiplier(rookie?.yearsExp, strategy);
  return Math.max(0, v * tilt - waiverValueFor(rookie?.pos, waiverValues));
}

/**
 * Cumulative displacement cost of taking `k` rookies.
 * Returns `null` when `k` exceeds what the roster can actually absorb — the
 * caller must treat that as infeasible rather than as free.
 */
export function displacementCost(k, cutLadder, openRosterSpots) {
  const cuts = Math.max(0, k - Math.max(0, openRosterSpots || 0));
  if (cuts === 0) return 0;
  const ladder = cutLadder || [];
  if (cuts > ladder.length) return null;
  let total = 0;
  for (let i = 0; i < cuts; i++) total += Number(ladder[i]?.effectiveCutCost) || 0;
  return total;
}

/** Marginal cost of the k-th rookie (0 while open spots remain). */
function marginalCut(k, cutLadder, openRosterSpots) {
  const prev = displacementCost(k - 1, cutLadder, openRosterSpots);
  const cur = displacementCost(k, cutLadder, openRosterSpots);
  if (prev === null || cur === null) return Infinity;
  return cur - prev;
}

/**
 * Largest `k` worth considering.
 *
 * Exact, not a heuristic cap.  An exchange argument bounds the gain of the
 * k-th rookie by the k-th largest surplus in the pool, while its cost is at
 * least the k-th marginal cut.  Because the cut ladder is cheapest-first, that
 * marginal cost is non-decreasing, so once
 *   `surplusDesc[k-1] - marginalCut(k) <= 0`
 * it stays there and no larger k can ever win.
 */
export function maxUsefulK(surplusesDesc, cutLadder, openRosterSpots, budget, pricesAsc) {
  const nAffordable = (() => {
    let spent = 0;
    let n = 0;
    for (const p of pricesAsc) {
      if (spent + p > budget) break;
      spent += p;
      n++;
    }
    return n;
  })();
  const hardMax = Math.min(surplusesDesc.length, nAffordable);
  for (let k = 1; k <= hardMax; k++) {
    const m = marginalCut(k, cutLadder, openRosterSpots);
    if (!Number.isFinite(m) || surplusesDesc[k - 1] - m <= 0) return k - 1;
  }
  return hardMax;
}

/**
 * Exact cardinality-constrained 0/1 knapsack.
 *
 * `F[k][b]` = max total surplus using exactly `k` rookies at cost <= `b`.
 *
 * Alongside the value table it records a per-item decision bit,
 * `took[i][k][b]`, set when item `i` improved that cell at the moment it was
 * processed.  A single `choice[k][b] = i` pointer is NOT enough to walk a plan
 * back out, and getting that wrong is subtle: the values stay correct while
 * the reconstructed roster silently repeats a player.  The cell
 * `F[k-1][b - price_i]` that item `i` consumed can be improved again by a
 * LATER item, so a pointer read afterwards may name an item that was not on
 * the path — frequently `i` itself.  On real data that produced a plan
 * listing the same $1 rookie twelve times.
 *
 * The decision table fixes it because items are processed in increasing `i`:
 * walking `i` strictly downward and taking the first flagged item reproduces
 * exactly the state each step consumed.
 *
 * Sizing: <=72 rookies, budget a few hundred dollars, `kMax` in single digits
 * once surpluses are replacement-adjusted — a few hundred thousand cell
 * updates and under a megabyte of decision bits, single-digit milliseconds.
 */
function solveKnapsack(items, budget, kMax) {
  const B = Math.max(0, Math.floor(budget));
  const NEG = -Infinity;
  const F = Array.from({ length: kMax + 1 }, () => new Float64Array(B + 1).fill(NEG));
  const width = (kMax + 1) * (B + 1);
  const took = new Uint8Array(items.length * width);
  F[0].fill(0);

  for (let i = 0; i < items.length; i++) {
    const price = items[i].price;
    const gain = items[i].surplus;
    if (price > B) continue;
    const base = i * width;
    // Descend k so each item is used at most once.
    for (let k = Math.min(kMax, i + 1); k >= 1; k--) {
      const cur = F[k];
      const prior = F[k - 1];
      const rowBase = base + k * (B + 1);
      for (let b = B; b >= price; b--) {
        const cand = prior[b - price];
        if (cand === NEG) continue;
        const total = cand + gain;
        if (total > cur[b]) {
          cur[b] = total;
          took[rowBase + b] = 1;
        }
      }
    }
  }
  return { F, took, width, B, n: items.length };
}

function reconstruct(items, took, width, B, k, b) {
  const picked = [];
  let kk = k;
  let bb = b;
  for (let i = items.length - 1; i >= 0 && kk > 0; i--) {
    if (!took[i * width + kk * (B + 1) + bb]) continue;
    picked.push(items[i]);
    bb -= items[i].price;
    kk--;
  }
  return kk === 0 ? picked.reverse() : null;
}

/** Best cell at exactly `k` items within budget, scanning all spend levels. */
function bestAtK(F, k, B) {
  let best = -Infinity;
  let bestB = -1;
  for (let b = 0; b <= B; b++) {
    if (F[k][b] > best) {
      best = F[k][b];
      bestB = b;
    }
  }
  return { value: best, b: bestB };
}

/**
 * Solve the plan frontier: the best plan at every feasible cardinality.
 *
 * One solve yields the optimum AND the alternatives — star-focused plans are
 * simply the low-`k` end of this frontier and depth-focused the high-`k` end.
 * No second algorithm, and nothing is manufactured when the pool does not
 * support a genuine alternative.
 */
export function solveFrontier(input) {
  const {
    rookies = [],
    budget = 0,
    cutLadder = [],
    openRosterSpots = 0,
    waiverValues = {},
    strategy = DEFAULT_STRATEGY,
  } = input || {};

  const excluded = [];
  const pool = [];
  for (const r of rookies) {
    if (!r || r.drafted) continue;
    const price = Math.max(0, Math.round(Number(r.price)));
    if (!Number.isFinite(Number(r.boardValue)) || Number(r.boardValue) <= 0) {
      // Never silently priced at zero — reported, per the repo's
      // `assetsUnpricedByBoard` precedent.
      excluded.push({ id: r.id, name: r.name, reason: "no_board_value" });
      continue;
    }
    if (!Number.isFinite(Number(r.price))) {
      excluded.push({ id: r.id, name: r.name, reason: "no_expected_price" });
      continue;
    }
    pool.push({
      ...r,
      price,
      surplus: surplusOverReplacement(r, waiverValues, strategy),
    });
  }

  const B = Math.max(0, Math.floor(Number(budget) || 0));
  const affordable = pool.filter((r) => r.price <= B && r.surplus > 0);
  const surplusesDesc = affordable.map((r) => r.surplus).sort((a, b) => b - a);
  const pricesAsc = affordable.map((r) => r.price).sort((a, b) => a - b);

  const kMax = Math.max(
    0,
    maxUsefulK(surplusesDesc, cutLadder, openRosterSpots, B, pricesAsc),
  );

  const frontier = [];
  // k = 0 is always a legitimate candidate: the team is never required to
  // spend, and "no rookie creates positive value" must be expressible.
  frontier.push({ k: 0, players: [], grossSurplus: 0, displacement: 0, netValue: 0, spend: 0 });

  if (kMax > 0 && affordable.length > 0) {
    const { F, took, width, B: bb } = solveKnapsack(affordable, B, kMax);
    for (let k = 1; k <= kMax; k++) {
      const disp = displacementCost(k, cutLadder, openRosterSpots);
      if (disp === null) break;
      const { value, b } = bestAtK(F, k, bb);
      if (!Number.isFinite(value) || b < 0) continue;
      const players = reconstruct(affordable, took, width, bb, k, b);
      if (!players) continue;
      frontier.push({
        k,
        players,
        grossSurplus: value,
        displacement: disp,
        netValue: value - disp,
        spend: players.reduce((s, p) => s + p.price, 0),
      });
    }
  }

  frontier.sort((a, b) => b.netValue - a.netValue || a.spend - b.spend);
  return { frontier, excluded, kMax, budget: B, poolSize: affordable.length };
}

// ── Max bid, pivots, and uncertainty ───────────────────────────────────────

/**
 * Deterministic PRNG (mulberry32).
 *
 * The confidence bootstrap must be reproducible: an unseeded RNG would make
 * the displayed confidence flicker on every React re-render, which reads as
 * the model being unstable rather than the estimate being uncertain.
 */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Box-Muller, driven by a seeded uniform source. */
function gauss(rand) {
  let u = 0;
  let v = 0;
  while (u === 0) u = rand();
  while (v === 0) v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/**
 * Log-space dispersion of realized auction prices.
 *
 * Prices are multiplicative (a player goes for "1.4x his sheet value", not
 * "+$12"), so dispersion is measured on `ln(paid / preDraftAtPick)`.  Log space
 * also keeps the derived band strictly positive, which a symmetric linear band
 * would not at the cheap end of the ladder.
 *
 * Shrinks a thin tier sample toward the global sample on the same
 * `n / minSamples` weight the board's tier-heat model already uses, so the page
 * carries one confidence concept rather than two.
 */
export function logPriceDispersion(ratios, { globalPrior = 0.35, minSamples = 3 } = {}) {
  const xs = (ratios || [])
    .map((r) => Number(r))
    .filter((r) => Number.isFinite(r) && r > 0)
    .map((r) => Math.log(r));
  if (xs.length < 2) return globalPrior;
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length;
  const varr = xs.reduce((a, b) => a + (b - mean) ** 2, 0) / (xs.length - 1);
  const sd = Math.sqrt(Math.max(0, varr));
  const conf = Math.min(1, xs.length / Math.max(1, minSamples));
  return conf * sd + (1 - conf) * globalPrior;
}

/** Multiplicative price band from a log-space sigma. */
export function priceBand(price, sigma, z = 0.674) {
  const p = Math.max(0, Number(price) || 0);
  const s = Math.max(0, Number(sigma) || 0);
  return {
    low: Math.max(1, Math.round(p * Math.exp(-z * s))),
    expected: Math.round(p),
    high: Math.max(1, Math.round(p * Math.exp(z * s))),
  };
}

function poolFrom(input) {
  return solveFrontier(input);
}

function buildItems(input) {
  const { rookies = [], budget = 0, waiverValues = {}, strategy = DEFAULT_STRATEGY } = input || {};
  const B = Math.max(0, Math.floor(Number(budget) || 0));
  return rookies
    .filter((r) => r && !r.drafted)
    .map((r) => ({
      ...r,
      price: Math.max(0, Math.round(Number(r.price))),
      surplus: surplusOverReplacement(r, waiverValues, strategy),
    }))
    .filter((r) => Number.isFinite(r.price) && r.price <= B && r.surplus > 0);
}

/** Best achievable net value over a set of items, plus the winning plan. */
function bestNetOver(items, input, kCap) {
  const { budget = 0, cutLadder = [], openRosterSpots = 0 } = input || {};
  const B = Math.max(0, Math.floor(Number(budget) || 0));
  let best = { netValue: 0, players: [], k: 0, spend: 0 };
  if (!items.length || kCap <= 0) return best;
  const { F, took, width } = solveKnapsack(items, B, kCap);
  for (let k = 1; k <= kCap; k++) {
    const disp = displacementCost(k, cutLadder, openRosterSpots);
    if (disp === null) break;
    const { value, b } = bestAtK(F, k, B);
    if (!Number.isFinite(value) || b < 0) continue;
    const net = value - disp;
    if (net > best.netValue) {
      const players = reconstruct(items, took, width, B, k, b) || [];
      best = { netValue: net, players, k, spend: players.reduce((s, p) => s + p.price, 0) };
    }
  }
  return best;
}

/**
 * The price at which a rookie stops being worth having in the plan.
 *
 * `planMaxBid(i) = max{ q : bestNetWith(i at q) >= bestNetWithout(i) }`
 *
 * An indifference price, not a value-to-dollars conversion.  The tempting
 * formulation — `price + (netWith - netWithout)` — silently adds a
 * `rankDerivedValue` quantity to a dollar quantity and invents an exchange rate
 * the rest of this codebase deliberately refuses to invent.  Asking instead
 * "how far can the price rise before I'd rather run my best plan without him?"
 * needs no such rate, and by construction it already reflects net value added,
 * the rest of the available pool, the remaining budget, and the replacement
 * options — everything a max bid is supposed to price in.
 *
 * Named `planMaxBid` rather than `maxBid` because the board already shows five
 * distinct max-bid concepts; a sixth that quietly disagreed with the others
 * would be a UI failure, not a feature.
 *
 * Returns `{ planMaxBid, netWith, netWithout, pivot }` where `pivot` is the
 * best plan that does not contain this rookie — the "if you lose him, go here"
 * branch, free from the same solve.
 */
export function computeMaxBid(input, rookieId) {
  const items = buildItems(input);
  const target = items.find((r) => r.id === rookieId);
  const { cutLadder = [], openRosterSpots = 0 } = input || {};
  const B = Math.max(0, Math.floor(Number(input?.budget) || 0));
  const others = items.filter((r) => r.id !== rookieId);

  const kCapAll = Math.max(
    1,
    maxUsefulK(
      items.map((r) => r.surplus).sort((a, b) => b - a),
      cutLadder,
      openRosterSpots,
      B,
      items.map((r) => r.price).sort((a, b) => a - b),
    ),
  );

  const without = bestNetOver(others, input, kCapAll);
  if (!target) {
    return { planMaxBid: 0, netWith: null, netWithout: without.netValue, pivot: without };
  }

  // Phi(q): best net over plans containing the target priced at q.
  const { F } = solveKnapsack(others, B, Math.max(0, kCapAll - 1) + 1);
  const phi = (q) => {
    const rem = B - q;
    if (rem < 0) return -Infinity;
    let best = -Infinity;
    for (let k = 1; k <= kCapAll; k++) {
      const disp = displacementCost(k, cutLadder, openRosterSpots);
      if (disp === null) break;
      const { value } = bestAtK(F, k - 1, rem);
      if (!Number.isFinite(value)) continue;
      best = Math.max(best, value + target.surplus - disp);
    }
    return best;
  };

  let maxBid = 0;
  for (let q = B; q >= 0; q--) {
    if (phi(q) >= without.netValue) {
      maxBid = q;
      break;
    }
  }
  return {
    planMaxBid: maxBid,
    netWith: phi(target.price),
    netWithout: without.netValue,
    pivot: without,
  };
}

/**
 * Confidence that the recommended plan really is the best one.
 *
 * Re-scores the top candidate plans under joint draws of value and price
 * uncertainty — it does NOT re-solve, which would be both far slower and
 * wrong-headed (the question is "is plan 1 better than plan 2", not "what is
 * optimal in each scenario").
 *
 * Re-scoring shared plans also gets the correlation right: two plans that
 * differ by a single swap move together under a common value shock, so the
 * comparison stays tight even when both totals are individually noisy.  A flat
 * "within 2% of the best" rule gets exactly that backwards — 2% of a large
 * total is a big absolute number, and the threshold is arbitrary on an
 * arbitrary scale.
 *
 * Value sigma uses the board's own `marketDispersionCV`, with a floor for
 * single-source rows (they already carry the pipeline's 30% haircut, so their
 * remaining uncertainty is real and large).
 */
export function assessPlans(frontier, { draws = 200, seed = 12345, defaultCv = 0.08 } = {}) {
  const plans = (frontier || []).slice(0, 8);
  if (plans.length === 0) return { confidence: null, nearTies: [], plans: [] };
  if (plans.length === 1) {
    return { confidence: 1, nearTies: [], plans: [{ ...plans[0], winProbability: 1 }] };
  }

  const rand = mulberry32(seed);
  const wins = new Array(plans.length).fill(0);

  for (let d = 0; d < draws; d++) {
    // One shock per distinct player, shared across every plan containing him.
    const shocks = new Map();
    const shockFor = (p) => {
      if (!shocks.has(p.id)) {
        const cv = Number.isFinite(Number(p.marketDispersionCV))
          ? Math.max(Number(p.marketDispersionCV), p.singleSource ? 0.35 : 0)
          : p.singleSource
            ? 0.35
            : defaultCv;
        shocks.set(p.id, Math.exp(gauss(rand) * cv));
      }
      return shocks.get(p.id);
    };

    let bestIdx = 0;
    let bestVal = -Infinity;
    for (let i = 0; i < plans.length; i++) {
      const plan = plans[i];
      let gross = 0;
      for (const p of plan.players || []) gross += p.surplus * shockFor(p);
      const net = gross - (plan.displacement || 0);
      if (net > bestVal) {
        bestVal = net;
        bestIdx = i;
      }
    }
    wins[bestIdx]++;
  }

  const scored = plans.map((p, i) => ({ ...p, winProbability: wins[i] / draws }));
  const top = scored[0];
  // A rival plan winning a quarter of the scenarios is a genuine coin-flip,
  // and the UI says so rather than presenting a false single answer.
  const nearTies = scored.slice(1).filter((p) => p.winProbability >= 0.25);
  return { confidence: top.winProbability, nearTies, plans: scored };
}

// ── The entry point ────────────────────────────────────────────────────────

/** Stable identity for a plan, so alternatives can be de-duplicated. */
function planKey(plan) {
  return (plan?.players || [])
    .map((p) => p.id)
    .sort()
    .join("|");
}

/**
 * Full Perfect Draft answer: the plan, its alternatives, per-rookie max bids
 * and pivots, and how much to trust any of it.
 *
 * Alternatives come from two places, and both are needed:
 *
 *   * the **frontier** gives the best plan at each cardinality — that is what
 *     "star-focused" (fewer, pricier) and "depth-focused" (more, cheaper) mean,
 *     and it costs nothing extra because one solve produces every k;
 *   * the **pivots** give the best plan that excludes each recommended rookie.
 *     Without these, two genuinely tied plans of the SAME size are invisible,
 *     because the frontier only keeps the winner at each k — so the UI would
 *     confidently name one of two coin-flips. The pivots are also the live
 *     draft's fallback branches ("if you lose him, go here"), so the same solve
 *     answers both questions.
 */
export function optimizeDraft(input) {
  const { frontier, excluded, kMax, budget, poolSize } = solveFrontier(input);
  const bestPlan = frontier[0] || {
    k: 0,
    players: [],
    grossSurplus: 0,
    displacement: 0,
    netValue: 0,
    spend: 0,
  };

  const recommendations = (bestPlan.players || []).map((p) => {
    const { planMaxBid, pivot } = computeMaxBid(input, p.id);
    return {
      ...p,
      planMaxBid,
      pivot: {
        netValue: pivot.netValue,
        players: (pivot.players || []).map((q) => ({ id: q.id, name: q.name, price: q.price })),
      },
    };
  });

  const seen = new Set();
  const candidates = [];
  for (const plan of frontier) {
    const key = planKey(plan);
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(plan);
  }
  for (const rec of recommendations) {
    const players = (input.rookies || [])
      .filter((r) => rec.pivot.players.some((q) => q.id === r.id))
      .map((r) => ({
        ...r,
        price: Math.max(0, Math.round(Number(r.price))),
        surplus: surplusOverReplacement(r, input.waiverValues || {}, input.strategy),
      }));
    const plan = {
      k: players.length,
      players,
      displacement: displacementCost(players.length, input.cutLadder, input.openRosterSpots) || 0,
      spend: players.reduce((s, q) => s + q.price, 0),
    };
    plan.grossSurplus = players.reduce((s, q) => s + q.surplus, 0);
    plan.netValue = plan.grossSurplus - plan.displacement;
    const key = planKey(plan);
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(plan);
  }
  candidates.sort((a, b) => b.netValue - a.netValue || a.spend - b.spend);

  const assessed = assessPlans(candidates, {
    draws: input?.draws || 200,
    seed: input?.seed || 12345,
  });

  // Star- and depth-focused variants are read off the frontier, never
  // manufactured: if the pool supports only one shape, there is no alternative
  // to show and we say nothing rather than inventing one.
  const withPlayers = frontier.filter((p) => p.k > 0);
  const byK = [...withPlayers].sort((a, b) => a.k - b.k);
  const starFocused = byK.length > 1 ? byK[0] : null;
  const depthFocused = byK.length > 1 ? byK[byK.length - 1] : null;

  return {
    plan: { ...bestPlan, players: recommendations },
    frontier,
    alternatives: {
      starFocused: starFocused && planKey(starFocused) !== planKey(bestPlan) ? starFocused : null,
      depthFocused:
        depthFocused && planKey(depthFocused) !== planKey(bestPlan) ? depthFocused : null,
    },
    confidence: assessed.confidence,
    nearTies: assessed.nearTies,
    excluded,
    meta: {
      kMax,
      budget,
      poolSize,
      budgetRemaining: budget - (bestPlan.spend || 0),
      valueScale: "rankDerivedValue",
      strategy: input?.strategy || DEFAULT_STRATEGY,
    },
  };
}
