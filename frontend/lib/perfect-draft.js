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
 *   R(k)        = waiver value the plan gives up (the free-agent ladder's TAIL)
 *   D(k)        = release cost of the (k - openRosterSpots) cheapest cuts
 *   NetValue(S) = sum boardValue(i) - R(|S|) - D(|S|)
 *
 *   maximize NetValue(S)  subject to  sum price(i) <= budget
 *
 * Every roster spot is priced against what it could hold instead, and that
 * symmetry is the whole trick.  A rookie's gain is not his rating — it is his
 * rating minus what you could have streamed into that spot for free.  Without
 * it the objective is degenerate: value-per-dollar rises ~30x down the rookie
 * ladder (value and price both come from the same convex Hill curve), so a raw
 * `max sum(value)` just reads the price curve back out and buys $1 dart throws.
 *
 * ── Why replacement is a LADDER, and why it is the tail ────────────────────
 *
 * The obvious version — charge every addition the best free agent at its
 * position — quietly assumes you can sign him k times.  You cannot.  So the
 * charge comes off a ladder of the freely-available values in order.
 *
 * Which rungs, though, is the part that is easy to get backwards.  The baseline
 * is "buy nothing", and an idle team does not sit with empty roster spots — it
 * fills them off the wire.  A plan that uses `k` of those spots therefore
 * forgoes the LAST k free agents it would have signed, not the first: with five
 * open spots, buying one rookie costs you the fifth-best free agent, because
 * you still sign the top four.  Once `k` reaches `open` the charge saturates —
 * every spot is spoken for, and further rookies displace rostered players
 * instead.
 *
 * The ladder also has to EXCLUDE the rookies in this very auction, which the
 * shipped version did not: on the 2026-08-04 board five of the six best "free
 * agents" were lots in the auction being optimized, so the model was advising
 * you not to bid for a rookie tight end because you could have that same
 * rookie tight end for nothing.  See `src/draft/rookie_pool.py`.
 *
 * ── Why the cut side changed with it ───────────────────────────────────────
 *
 * `effectiveCutCost` is measured OVER waiver level.  That was consistent while
 * a rookie's gain was measured over waiver level too — the two terms cancelled.
 * Under a ladder they no longer cancel, and keeping ECC on the cost side takes
 * the waiver credit twice.  It is not a rounding difference: 23 of 30 rungs on
 * the live board have an ECC of exactly zero, so the model believed releasing
 * 23 rostered players was free.  `releaseCost` charges the whole value instead.
 *
 * ── Why R and D depend only on k ───────────────────────────────────────────
 *
 * The cut ladder is cheapest-first and independent of WHICH rookies are bought,
 * so total displacement cost is a function of how many you buy. That is what
 * lets one dynamic program answer every cardinality at once — and it is exact,
 * not an approximation: legal cut-sets are the independent sets of the dual of
 * a transversal matroid, where greedy is optimal and successive minimum-weight
 * sets nest.  See `src/draft/displacement.py` for the full argument.  `W(k)` is
 * a cardinality function for the same reason and composes with it.
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

/** Tilt-adjusted board value — the item value when a waiver ladder is in play. */
export function tiltedBoardValue(rookie, strategy = DEFAULT_STRATEGY) {
  const v = Number(rookie?.boardValue);
  if (!Number.isFinite(v) || v <= 0) return 0;
  return v * strategyMultiplier(rookie?.yearsExp, strategy);
}

/** Cumulative sum of the first `n` ladder rungs. */
function ladderPrefix(waiverLadder, n) {
  const ladder = Array.isArray(waiverLadder) ? waiverLadder : [];
  const count = Math.max(0, Math.min(Math.floor(Number(n) || 0), ladder.length));
  let total = 0;
  for (let i = 0; i < count; i++) {
    const v = Number(ladder[i]);
    if (Number.isFinite(v) && v > 0) total += v;
  }
  return total;
}

/**
 * `R(k)` — the waiver value a k-rookie plan actually gives up.
 *
 * Not simply the top k rungs, and the difference is the whole subtlety.  The
 * baseline this is measured against is "buy nothing", which does NOT leave the
 * roster short: an idle team fills its `open` spots off the wire.  So a plan
 * that uses `k` of those spots forgoes the LAST k of the free agents it would
 * otherwise have signed — the worst ones — not the best.  With five open spots,
 * buying one rookie costs you the fifth-best free agent, because you still sign
 * the top four.
 *
 * Once `k` reaches `open` there is nothing left to give up: every spot is
 * spoken for and the charge saturates at `W(open)`.  Rookies past that point
 * displace rostered players instead, which is what `displacementCost` prices.
 *
 * Running off the end of the ladder means the league has fewer free agents than
 * the roster has spots.  Those spots are then genuinely free — there is nobody
 * left to stream — so exhausted rungs contribute 0 rather than repeating the
 * last value, which would invent players.
 */
export function replacementCost(k, waiverLadder, openRosterSpots = Infinity) {
  const n = Math.max(0, Math.floor(Number(k) || 0));
  if (n === 0) return 0;
  const open = Number.isFinite(Number(openRosterSpots))
    ? Math.max(0, Math.floor(Number(openRosterSpots)))
    : n;
  const used = Math.min(n, open);
  return ladderPrefix(waiverLadder, open) - ladderPrefix(waiverLadder, open - used);
}

/**
 * What releasing a rostered player really costs, in board-value units.
 *
 * NOT `effectiveCutCost`, and the distinction matters more than it looks.  ECC
 * is measured *over waiver level* — `(value - waiver) x scarcity` — because the
 * shipped model also measured a rookie's gain over waiver level, so the two
 * waiver terms cancelled and the accounting was consistent by construction.
 *
 * Once replacement is a ladder that cancellation is gone, and keeping ECC on
 * the cost side would take the waiver credit twice: once by discounting the
 * release, once by charging `R(k)`.  Measured on the 2026-08-04 board that is
 * not a rounding difference — **23 of 30 cut rungs have an ECC of exactly
 * zero**, so the model believed releasing 23 rostered players was free and
 * would fill the roster to capacity with $1 rookies every time.  Twelve of
 * those rungs are unranked players whose ECC is `max(0, waiver - waiver) = 0`,
 * which is precisely the free-cut-on-an-identity-join-miss failure ADR-010 set
 * out to prevent and did not.
 *
 * So the ladder model charges the player's whole value.  `baseValue` already
 * carries the unranked fallback (waiver level stands in), so an identity-join
 * miss costs a full waiver level to release rather than nothing.
 */
export function releaseCost(rung) {
  const base = Number(rung?.baseValue);
  if (!Number.isFinite(base) || base <= 0) {
    // No base shipped (older payload): fall back to ECC, which understates but
    // never invents a number.
    const ecc = Number(rung?.effectiveCutCost);
    return Number.isFinite(ecc) && ecc > 0 ? ecc : 0;
  }
  const mult = Number(rung?.scarcityMultiplier);
  return base * (Number.isFinite(mult) && mult > 0 ? mult : 1);
}

/**
 * The order cuts are actually consumed in, under whichever model is live.
 *
 * The backend ships rungs ascending by ECC.  The ladder model charges the
 * cheapest by `releaseCost`, which is a different quantity and therefore a
 * different order.  Every consumer that walks the ladder — the charge table,
 * mid-draft progress, realized results, the panel's cut column — must walk it
 * the same way, or one player is charged twice and another never.
 *
 * Legal because the backend's greedy built its rungs as a nested sequence of
 * legal cut-sets: all of them are jointly droppable, so any subset is too.
 */
export function consumptionOrder(cutLadder, waiverLadder) {
  const rungs = Array.isArray(cutLadder) ? cutLadder : [];
  const ladder = Array.isArray(waiverLadder) && waiverLadder.length ? waiverLadder : null;
  if (!ladder) return rungs;
  return [...rungs].sort((a, b) => releaseCost(a) - releaseCost(b));
}

/**
 * Cumulative release cost of the cuts a k-rookie plan forces.
 *
 * Takes the CHEAPEST cuts by release cost rather than in ladder order, which is
 * exact rather than a heuristic: the backend's greedy built its rungs as a
 * nested sequence of legal cut-sets, so all of them are jointly droppable, and
 * every subset of an independent set in a matroid is independent.  The `j`
 * cheapest of the 30 are therefore themselves a legal cut-set — and the
 * minimum-weight one of that size.
 *
 * Returns `null` when the roster cannot absorb `k`, which the caller must treat
 * as infeasible rather than free.
 */
export function releaseCostForK(k, cutLadder, openRosterSpots) {
  const cuts = Math.max(0, Math.floor(Number(k) || 0) - Math.max(0, openRosterSpots || 0));
  if (cuts === 0) return 0;
  const ladder = Array.isArray(cutLadder) ? cutLadder : [];
  if (cuts > ladder.length) return null;
  const costs = ladder.map(releaseCost).sort((a, b) => a - b);
  let total = 0;
  for (let i = 0; i < cuts; i++) total += costs[i];
  return total;
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
 * Sound, not a heuristic cap: it bounds `net(k)` from above and keeps only the
 * cardinalities whose bound is positive.  Taking the `k` largest item values
 * over-states the gain, and `W(k) + D(k)` is exact, so
 *
 *   `UB(k) = sum(valuesDesc[0..k-1]) - W(k) - D(k)`
 *
 * is an upper bound on the best achievable net at that cardinality.  Any `k`
 * with `UB(k) <= 0` loses to the empty plan and can be skipped.
 *
 * Deliberately scans the whole range rather than stopping at the first
 * failure.  The previous early-exit relied on the marginal cost being
 * non-decreasing, which held while the only cost was the cheapest-first cut
 * ladder — but `W(k)`'s marginal term DECLINES (the free-agent ladder gets
 * worse the deeper you go), so the sum is no longer monotone and a first
 * failure no longer implies every later one.  The scan is O(n) against a
 * dynamic program that is O(n·k·B), so the rigour is free.
 */
export function maxUsefulK(
  valuesDesc,
  cutLadder,
  openRosterSpots,
  budget,
  pricesAsc,
  waiverLadder = null,
) {
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
  const hardMax = Math.min(valuesDesc.length, nAffordable);
  const ladder = Array.isArray(waiverLadder) && waiverLadder.length ? waiverLadder : null;

  if (!ladder) {
    // No ladder: the only marginal cost is the cheapest-first cut, which is
    // non-decreasing, while the marginal gain is non-increasing.  So the
    // difference is non-increasing and the first failure IS the last — a
    // strictly tighter stop than the scan below, and still exact.
    for (let k = 1; k <= hardMax; k++) {
      const m = marginalCut(k, cutLadder, openRosterSpots);
      if (!Number.isFinite(m) || valuesDesc[k - 1] - m <= 0) return k - 1;
    }
    return hardMax;
  }

  const table = buildChargeTable({ cutLadder, openRosterSpots }, ladder);
  let cumValue = 0;
  let best = 0;
  for (let k = 1; k <= hardMax; k++) {
    cumValue += Number(valuesDesc[k - 1]) || 0;
    const charges = table.at(k);
    // The roster cannot absorb this many, and it never will for larger k.
    if (charges === null) break;
    if (cumValue - charges.replacement - charges.displacement > 0) best = k;
  }
  return best;
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
    waiverLadder = null,
    strategy = DEFAULT_STRATEGY,
  } = input || {};

  // Two exact modes, and which one is live depends only on whether the backend
  // supplied a ladder.  With it, replacement is a cardinality term W(k); the
  // item value is the plain (tilted) board value.  Without it — an older
  // roster-context payload — each item carries its own flat positional charge,
  // which is the previous model.  Both feed one dynamic program.
  const ladder = Array.isArray(waiverLadder) && waiverLadder.length ? waiverLadder : null;

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
      surplus: ladder
        ? tiltedBoardValue(r, strategy)
        : surplusOverReplacement(r, waiverValues, strategy),
    });
  }

  const B = Math.max(0, Math.floor(Number(budget) || 0));
  const affordable = pool.filter((r) => r.price <= B && r.surplus > 0);
  const valuesDesc = affordable.map((r) => r.surplus).sort((a, b) => b - a);
  const pricesAsc = affordable.map((r) => r.price).sort((a, b) => a - b);

  const kMax = Math.max(
    0,
    maxUsefulK(valuesDesc, cutLadder, openRosterSpots, B, pricesAsc, ladder),
  );

  const frontier = [];
  // k = 0 is always a legitimate candidate: the team is never required to
  // spend, and "no rookie creates positive value" must be expressible.
  frontier.push({
    k: 0,
    players: [],
    grossSurplus: 0,
    replacement: 0,
    displacement: 0,
    netValue: 0,
    spend: 0,
  });

  if (kMax > 0 && affordable.length > 0) {
    const { F, took, width, B: bb } = solveKnapsack(affordable, B, kMax);
    const charges0 = buildChargeTable({ cutLadder, openRosterSpots }, ladder);
    for (let k = 1; k <= kMax; k++) {
      const charges = charges0.at(k);
      if (charges === null) break;
      const { replacement: repl, displacement: disp } = charges;
      const { value, b } = bestAtK(F, k, bb);
      if (!Number.isFinite(value) || b < 0) continue;
      const players = reconstruct(affordable, took, width, bb, k, b);
      if (!players) continue;
      frontier.push({
        k,
        players: ladder ? assignLadderRungs(players, ladder, openRosterSpots) : players,
        grossSurplus: value,
        replacement: repl,
        displacement: disp,
        netValue: value - repl - disp,
        spend: players.reduce((s, p) => s + p.price, 0),
      });
    }
  }

  frontier.sort((a, b) => b.netValue - a.netValue || a.spend - b.spend);
  return { frontier, excluded, kMax, budget: B, poolSize: affordable.length };
}

/**
 * Pair each chosen rookie with the ladder rung his roster spot forgoes.
 *
 * The plan total does not depend on the pairing — any bijection sums to `W(k)`
 * — but a per-row display does, so the best rookie is set against the best free
 * agent and so on down. That keeps the panel's arithmetic legible: each row's
 * `surplus - forgone` sums exactly to the plan's gross-minus-replacement.
 */
function assignLadderRungs(players, ladder, openRosterSpots = Infinity) {
  const k = players.length;
  const open = Number.isFinite(Number(openRosterSpots))
    ? Math.max(0, Math.floor(Number(openRosterSpots)))
    : k;
  // R(k) charges the LAST `min(k, open)` rungs the team would have signed, so
  // the rungs actually forgone start at index `open - used`.
  const used = Math.min(k, open);
  const firstRung = Math.max(0, open - used);
  const order = players
    .map((p, i) => [i, Number(p.surplus) || 0])
    .sort((a, b) => b[1] - a[1]);
  const out = players.slice();
  order.forEach(([idx], n) => {
    const v = n < used ? Number(ladder[firstRung + n]) : 0;
    out[idx] = { ...players[idx], replacementForgone: Number.isFinite(v) && v > 0 ? v : 0 };
  });
  return out;
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
 * Log-space price dispersion assumed before this draft has taught us anything.
 *
 * A DECLARED PRIOR, not a measurement — the same posture as BDVM's
 * `params_v1.json`.  Nothing in this repo has a completed rookie auction to fit
 * it against; the number is a plausible starting width (an IQR of roughly
 * x0.79 to x1.27 around the expected price) chosen so the band is neither
 * absurdly tight nor uninformative.  It is shrunk away as real picks land, and
 * `priceSigmaByTier(...).measured` reports which regime a band is in so a
 * prior-dominated band is never presented as an observation.  Replace it with
 * a fit the first time an auction is recorded end to end.
 */
export const PRICE_DISPERSION_PRIOR = 0.35;

/**
 * Per-tier price sigma with two levels of shrinkage.
 *
 * A tier with three sales says more about that tier than the board-wide sample
 * does; a tier with one says nothing.  So each tier's own dispersion shrinks
 * toward the board-wide dispersion, and the board-wide dispersion shrinks
 * toward `PRICE_DISPERSION_PRIOR` — both on the `n / minSamples` weight the
 * board's tier-heat model already uses, so the page carries one confidence
 * concept rather than three.
 *
 * Returns sigmas keyed by tier plus `global`, and `measured` — false while the
 * prior is still doing the work, which is what the UI needs to avoid
 * presenting an assumption as an observation.
 */
export function priceSigmaByTier(
  { tierPriceRatios = {}, allPriceRatios = [] } = {},
  { minSamples = 3, prior = PRICE_DISPERSION_PRIOR } = {},
) {
  const global = logPriceDispersion(allPriceRatios, { globalPrior: prior, minSamples });
  const byTier = {};
  for (const [tier, ratios] of Object.entries(tierPriceRatios || {})) {
    byTier[tier] = logPriceDispersion(ratios, { globalPrior: global, minSamples });
  }
  const n = (allPriceRatios || []).filter((r) => Number.isFinite(Number(r)) && Number(r) > 0).length;
  return { ...byTier, global, measured: n >= minSamples, sampleCount: n };
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
export function logPriceDispersion(ratios, { globalPrior = PRICE_DISPERSION_PRIOR, minSamples = 3 } = {}) {
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

/**
 * Per-player value sigma for the confidence bootstrap.
 *
 * The board publishes `marketDispersionCV` — the coefficient of variation of a
 * player's normalized values across the sites that cover him.  Two things about
 * it are load-bearing here:
 *
 *   * **It is absent, not zero, when it cannot be measured.**  The scraper's
 *     dispersion is undefined below two comparable site values, and the server
 *     nulls it rather than shipping a `0.0` that would read as "every source
 *     agreed".  On the 2026-08-04 board that is 31 of the top 72 rookies, and
 *     they are precisely the thinnest-covered rows.  Treating them as certain
 *     would invert the truth.
 *   * **So the fallback must be pessimistic, and it should be measured.**  A
 *     row whose dispersion is unobservable is placed at the p90 of the
 *     dispersion actually observed across this pool — the pessimistic end of
 *     the real distribution rather than a declared constant.  With too few
 *     observations to form a p90, `defaultCv` is the last resort.
 *
 * `singleSource` (the pipeline's semantic single-source flag, which already
 * carries a 30% value haircut) floors the sigma independently.
 */
export function valueSigmas(plans, { defaultCv = 0.08, singleSourceFloor = 0.35 } = {}) {
  const observed = [];
  const players = new Map();
  for (const plan of plans || []) {
    for (const p of plan?.players || []) {
      if (players.has(p.id)) continue;
      players.set(p.id, p);
      const cv = Number(p.marketDispersionCV);
      if (Number.isFinite(cv) && cv > 0) observed.push(cv);
    }
  }
  observed.sort((a, b) => a - b);
  // Needs enough observations for a p90 to mean anything; below that the
  // declared default is more honest than a percentile of two numbers.
  const unobservedCv =
    observed.length >= 3 ? observed[Math.min(observed.length - 1, Math.floor(0.9 * observed.length))] : defaultCv;

  const sigmas = new Map();
  for (const [id, p] of players) {
    const cv = Number(p.marketDispersionCV);
    const base = Number.isFinite(cv) && cv > 0 ? cv : unobservedCv;
    sigmas.set(id, p.singleSource ? Math.max(base, singleSourceFloor) : base);
  }
  return { sigmas, unobservedCv, observedCount: observed.length };
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

/** The ladder actually in play for an input, or null for the flat model. */
function ladderOf(input) {
  const l = input?.waiverLadder;
  return Array.isArray(l) && l.length ? l : null;
}

/**
 * Precomputed cardinality charges, under whichever model is live.
 *
 * Flat model: replacement is already inside each item's value, and the cut side
 * is ECC (also measured over waiver) — the two waiver terms cancel.
 * Ladder model: item value is the raw board value, replacement is `R(k)`, and
 * cuts cost their full release value. Mixing the two halves is the one thing
 * that must not happen; keeping the choice in one place is how.
 *
 * Built ONCE per solve rather than per query, and that is not a micro-
 * optimization: `computeMaxBid` evaluates its indifference price over every
 * dollar from the budget down to zero, times every cardinality, times every
 * recommended rookie. Sorting the release ladder inside that loop measured
 * 1129 ms on the live board against 327 ms before — roughly 460,000 sorts of
 * the same thirty numbers. The table makes each lookup an array index.
 */
function buildChargeTable(input, ladder) {
  const { cutLadder = [], openRosterSpots = 0 } = input || {};
  const rungs = Array.isArray(cutLadder) ? cutLadder : [];
  const open = Math.max(0, Math.floor(Number(openRosterSpots) || 0));
  const kMaxAbsorbable = open + rungs.length;

  // Release costs, cheapest first, as a prefix sum. Exact rather than a
  // heuristic ordering: the backend's rungs are jointly droppable, so every
  // subset of them is a legal cut-set and the j cheapest are the minimum-weight
  // one of that size.
  const sortedReleases = rungs.map(releaseCost).sort((a, b) => a - b);
  const releasePrefix = [0];
  for (let i = 0; i < sortedReleases.length; i++) {
    releasePrefix.push(releasePrefix[i] + sortedReleases[i]);
  }

  const eccPrefix = [0];
  for (let i = 0; i < rungs.length; i++) {
    eccPrefix.push(eccPrefix[i] + (Number(rungs[i]?.effectiveCutCost) || 0));
  }

  return {
    kMaxAbsorbable,
    /** `null` when the roster cannot absorb `k`. */
    at(k) {
      const n = Math.max(0, Math.floor(Number(k) || 0));
      const cuts = Math.max(0, n - open);
      if (cuts > rungs.length) return null;
      if (!ladder) return { replacement: 0, displacement: eccPrefix[cuts] };
      return {
        replacement: replacementCost(n, ladder, open),
        displacement: releasePrefix[cuts],
      };
    },
  };
}

function buildItems(input) {
  const { rookies = [], budget = 0, waiverValues = {}, strategy = DEFAULT_STRATEGY } = input || {};
  const B = Math.max(0, Math.floor(Number(budget) || 0));
  const ladder = ladderOf(input);
  return rookies
    .filter((r) => r && !r.drafted)
    .map((r) => ({
      ...r,
      price: Math.max(0, Math.round(Number(r.price))),
      surplus: ladder
        ? tiltedBoardValue(r, strategy)
        : surplusOverReplacement(r, waiverValues, strategy),
    }))
    .filter((r) => Number.isFinite(r.price) && r.price <= B && r.surplus > 0);
}

/** Best achievable net value over a set of items, plus the winning plan. */
function bestNetOver(items, input, kCap, precomputed = null) {
  const { budget = 0 } = input || {};
  const B = Math.max(0, Math.floor(Number(budget) || 0));
  const ladder = ladderOf(input);
  let best = { netValue: 0, players: [], k: 0, spend: 0 };
  if (!items.length || kCap <= 0) return best;
  const { F, took, width } = precomputed || solveKnapsack(items, B, kCap);
  const table = buildChargeTable(input, ladder);
  for (let k = 1; k <= kCap; k++) {
    const charges = table.at(k);
    if (charges === null) break;
    const { value, b } = bestAtK(F, k, B);
    if (!Number.isFinite(value) || b < 0) continue;
    const net = value - charges.replacement - charges.displacement;
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
export function computeMaxBid(input, rookieId, { bid = null } = {}) {
  const items = buildItems(input);
  const target = items.find((r) => r.id === rookieId);
  const { cutLadder = [], openRosterSpots = 0 } = input || {};
  const B = Math.max(0, Math.floor(Number(input?.budget) || 0));
  const others = items.filter((r) => r.id !== rookieId);

  const ladder = ladderOf(input);
  const kCapAll = Math.max(
    1,
    maxUsefulK(
      items.map((r) => r.surplus).sort((a, b) => b - a),
      cutLadder,
      openRosterSpots,
      B,
      items.map((r) => r.price).sort((a, b) => a - b),
      ladder,
    ),
  );

  // ONE knapsack over `others`, shared by both users of it. `bestNetOver`
  // used to build its own and this line rebuilt an argument-identical copy
  // six lines later — `Math.max(0, kCapAll - 1) + 1 === kCapAll` because
  // kCapAll is floored at 1 above. That doubled the cost of every max-bid,
  // and there is one max-bid per recommended rookie.
  const solved = solveKnapsack(others, B, kCapAll);
  const without = bestNetOver(others, input, kCapAll, solved);
  if (!target) {
    return { planMaxBid: 0, netWith: null, netWithout: without.netValue, pivot: without };
  }

  // Phi(q): best net over plans containing the target priced at q.
  const { F } = solved;
  const table = buildChargeTable(input, ladder);
  const phi = (q) => {
    const rem = B - q;
    if (rem < 0) return -Infinity;
    let best = -Infinity;
    for (let k = 1; k <= kCapAll; k++) {
      const charges = table.at(k);
      if (charges === null) break;
      const { value } = bestAtK(F, k - 1, rem);
      if (!Number.isFinite(value)) continue;
      best = Math.max(best, value + target.surplus - charges.replacement - charges.displacement);
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
  const askedBid = Number(bid);
  const atBid = Number.isFinite(askedBid) && askedBid >= 0 ? phi(Math.round(askedBid)) : null;
  return {
    planMaxBid: maxBid,
    netWith: phi(target.price),
    netWithout: without.netValue,
    // Only present when a live bid was supplied: the best plan you can still
    // build if you win him AT THAT PRICE, rather than at the price the board
    // expected. The two diverge exactly when it matters — mid-auction, with
    // the bid climbing past expectations.
    netAtBid: atBid,
    pivot: without,
  };
}

/**
 * "The bidding is at $X — do I go?"
 *
 * The question a live auction actually asks, and it is not the one
 * `planMaxBid` alone answers. `planMaxBid` is the indifference price computed
 * against the board's expected prices for everyone else; what a bidder needs
 * in the moment is the comparison between two concrete futures: win him at
 * this number, or lose him and run the pivot plan.
 *
 * Both branches come free from the same solve `computeMaxBid` already does —
 * `phi(bid)` is the best plan containing him at that price, and
 * `bestNetWithout` is the pivot. No new model, no second price concept.
 *
 * `verdict` is deliberately coarse (`"go"` / `"limit"` / `"stop"`), because the
 * underlying numbers carry uncertainty the panel already reports separately and
 * a false precision here would read as more confidence than exists.
 */
export function evaluateBid(input, rookieId, bid) {
  const q = Math.max(0, Math.round(Number(bid) || 0));
  const { planMaxBid, netWithout, netAtBid, pivot } = computeMaxBid(input, rookieId, { bid: q });
  const winning = Number.isFinite(netAtBid) ? netAtBid : null;
  const gain = winning === null ? null : winning - netWithout;
  let verdict = "stop";
  if (planMaxBid > 0 && q <= planMaxBid) verdict = q >= planMaxBid * 0.9 ? "limit" : "go";
  return {
    bid: q,
    planMaxBid,
    netIfWon: winning,
    netIfLost: netWithout,
    // What this specific purchase is worth relative to walking away. Negative
    // means the pivot plan is better — the honest "let him go" signal.
    gain,
    pivot,
    verdict,
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
 * Value sigma comes from `valueSigmas` above — the board's own
 * `marketDispersionCV` where it exists, a measured pessimistic stand-in where
 * it does not, and a floor for single-source rows.
 *
 * Price risk enters as **feasibility** risk, which is the only way it can enter
 * honestly: surplus is value over replacement and does not depend on what the
 * rookie cost, so a price draw cannot move a plan's net value.  What it can do
 * is push a plan's spend past the budget, and a plan that cannot be bought is
 * not the best plan.  A plan resting well under the budget is untouched by
 * this; a plan spending to the ceiling loses confidence, which is the whole
 * point.  When every candidate is unaffordable in a draw the honest outcome is
 * "buy nothing", so that draw is credited to no plan and still counts in the
 * denominator — confidence is `P(best AND affordable)`, which is what a bidder
 * needs mid-auction.  In practice `optimizeDraft` passes a frontier that
 * already carries an empty `k = 0` plan, so "buy nothing" competes as a plan
 * and `infeasibleDraws` stays at zero; the counter is for callers assessing a
 * hand-built list without one.
 *
 * `priceSigmaFor` returns a log-space sigma per rookie (see
 * `logPriceDispersion`).  It defaults to no price risk so that a caller who
 * has no realized auction history to measure from gets the value-only
 * behaviour rather than an invented spread.
 */
export function assessPlans(
  frontier,
  { draws = 200, seed = 12345, defaultCv = 0.08, budget = Infinity, priceSigmaFor = null } = {},
) {
  const plans = (frontier || []).slice(0, 8);
  if (plans.length === 0) return { confidence: null, nearTies: [], plans: [] };

  const { sigmas, unobservedCv, observedCount } = valueSigmas(plans, { defaultCv });
  const B = Number.isFinite(Number(budget)) ? Number(budget) : Infinity;
  const priceSigma = (p) => {
    if (typeof priceSigmaFor !== "function") return 0;
    const s = Number(priceSigmaFor(p));
    return Number.isFinite(s) && s > 0 ? s : 0;
  };
  const priceRisk =
    B !== Infinity && plans.some((plan) => (plan?.players || []).some((p) => priceSigma(p) > 0));

  // With one candidate there is nothing to be uncertain BETWEEN, and the
  // affordability draw below would be comparing it against itself.  Its
  // confidence is 1 by construction — but only when price cannot make it
  // unaffordable; otherwise it still has to survive the draws.
  if (plans.length === 1 && !priceRisk) {
    return {
      confidence: 1,
      nearTies: [],
      plans: [{ ...plans[0], winProbability: 1 }],
      meta: { unobservedCv, observedCount, infeasibleDraws: 0 },
    };
  }

  const rand = mulberry32(seed);
  const wins = new Array(plans.length).fill(0);
  let infeasibleDraws = 0;

  for (let d = 0; d < draws; d++) {
    // One shock per distinct player, shared across every plan containing him —
    // two plans differing by a single swap must move together.
    const valueShocks = new Map();
    const priceShocks = new Map();
    const shockFor = (p) => {
      if (!valueShocks.has(p.id)) {
        valueShocks.set(p.id, Math.exp(gauss(rand) * (sigmas.get(p.id) ?? defaultCv)));
      }
      return valueShocks.get(p.id);
    };
    const paidFor = (p) => {
      if (!priceShocks.has(p.id)) {
        const s = priceSigma(p);
        priceShocks.set(p.id, (Number(p.price) || 0) * (s > 0 ? Math.exp(gauss(rand) * s) : 1));
      }
      return priceShocks.get(p.id);
    };

    let bestIdx = -1;
    let bestVal = -Infinity;
    for (let i = 0; i < plans.length; i++) {
      const plan = plans[i];
      const players = plan.players || [];
      if (priceRisk) {
        let spend = 0;
        for (const p of players) spend += paidFor(p);
        if (spend > B) continue;
      }
      let gross = 0;
      for (const p of players) gross += p.surplus * shockFor(p);
      // BOTH cardinality charges, or the bootstrap ranks plans on a different
      // objective than the solver did. Under the ladder model `p.surplus` is
      // the raw board value, so omitting `replacement` leaves the k-dependent
      // waiver charge out entirely and systematically flatters large plans.
      const net = gross - (plan.replacement || 0) - (plan.displacement || 0);
      if (net > bestVal) {
        bestVal = net;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) infeasibleDraws++;
    else wins[bestIdx]++;
  }

  const scored = plans.map((p, i) => ({ ...p, winProbability: wins[i] / draws }));
  const top = scored[0];
  // A rival plan winning a quarter of the scenarios is a genuine coin-flip,
  // and the UI says so rather than presenting a false single answer.
  const nearTies = scored.slice(1).filter((p) => p.winProbability >= 0.25);
  return {
    confidence: top.winProbability,
    nearTies,
    plans: scored,
    meta: { unobservedCv, observedCount, infeasibleDraws },
  };
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
  const planLadder = ladderOf(input);
  for (const rec of recommendations) {
    const players = (input.rookies || [])
      .filter((r) => rec.pivot.players.some((q) => q.id === r.id))
      .map((r) => ({
        ...r,
        price: Math.max(0, Math.round(Number(r.price))),
        surplus: planLadder
          ? tiltedBoardValue(r, input.strategy)
          : surplusOverReplacement(r, input.waiverValues || {}, input.strategy),
      }));
    const charges = buildChargeTable(input, planLadder).at(players.length) || {
      replacement: 0,
      displacement: 0,
    };
    const plan = {
      k: players.length,
      players: planLadder
        ? assignLadderRungs(players, planLadder, input.openRosterSpots)
        : players,
      replacement: charges.replacement,
      displacement: charges.displacement,
      spend: players.reduce((s, q) => s + q.price, 0),
    };
    plan.grossSurplus = players.reduce((s, q) => s + q.surplus, 0);
    plan.netValue = plan.grossSurplus - plan.replacement - plan.displacement;
    const key = planKey(plan);
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(plan);
  }
  candidates.sort((a, b) => b.netValue - a.netValue || a.spend - b.spend);

  const priceSigmaFor = typeof input?.priceSigmaFor === "function" ? input.priceSigmaFor : null;
  const assessed = assessPlans(candidates, {
    draws: input?.draws || 200,
    seed: input?.seed || 12345,
    budget,
    priceSigmaFor,
  });

  // What the recommended plan costs if every rookie in it goes at the top of
  // his band rather than the middle.  A plan can be comfortably affordable at
  // the expected price and unbuyable at p75, and that is the single most
  // actionable uncertainty number during a live auction: it answers "do I have
  // room to be outbid on all of these, or am I counting on catching a break?"
  const Z75 = 0.674;
  const spendAtP75 = priceSigmaFor
    ? (bestPlan.players || []).reduce((s, p) => {
        const sig = Number(priceSigmaFor(p));
        const mult = Number.isFinite(sig) && sig > 0 ? Math.exp(Z75 * sig) : 1;
        return s + (Number(p.price) || 0) * mult;
      }, 0)
    : null;

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
      // Null when no price sigma was supplied — "not measured" and "no risk"
      // must not render identically.
      spendAtP75,
      budgetHeadroomAtP75: spendAtP75 == null ? null : budget - spendAtP75,
      valueScale: "rankDerivedValue",
      strategy: input?.strategy || DEFAULT_STRATEGY,
      // How much of the confidence number rests on measured dispersion versus
      // the stand-in for rows the board could not measure.
      valueSigma: {
        unobservedCv: assessed.meta?.unobservedCv ?? null,
        observedCount: assessed.meta?.observedCount ?? 0,
      },
      infeasibleDraws: assessed.meta?.infeasibleDraws ?? 0,
    },
  };
}

// ── Live draft progress ────────────────────────────────────────────────────

/**
 * Advance the roster context past the rookies this team has ALREADY bought.
 *
 * The roster context is a snapshot of the roster as it stood before the draft:
 * `openRosterSpots` and the cut ladder both describe that starting state, and
 * neither moves when a rookie sells. Consuming them here is what makes the
 * recommendation *the remaining plan* rather than a stale opening plan.
 *
 * Without this, two things go wrong the moment you buy anything:
 *
 *   * roster room is double-counted — buy three rookies into one open spot and
 *     the model still believes that spot is free, so it under-charges the next
 *     three additions;
 *   * the ladder re-offers rungs those purchases already consumed, i.e. it
 *     recommends releasing the same player twice.
 *
 * Each rookie bought fills an open spot first, then takes the cheapest
 * remaining rung — the same order the plan itself assumes, so the accounting
 * stays consistent with how the cost was quoted at the time.
 *
 * "Cheapest" must mean the same thing here as it does in `buildChargeTable`,
 * and under the ladder model it does NOT mean the backend's order.  The
 * backend ships rungs ascending by ECC (value over waiver level); the ladder
 * model charges the cheapest by `releaseCost` (the whole value).  Those
 * orderings are unrelated — a rung with an ECC of 0 can have the largest
 * release cost on the board.  Consuming the ECC head while charging the
 * release-cheapest re-offers one player as a cut on purchase after purchase
 * and never charges another at all, which is precisely the failure the
 * paragraph above says this function exists to prevent.
 *
 * `ladderExhausted` matters for display: a plan of zero because there is no
 * modelled room left reads identically to a plan of zero because nothing is
 * worth buying, and those call for opposite actions.
 */
export function applyDraftProgress({
  openRosterSpots = 0,
  cutLadder = [],
  rookiesBought = 0,
  waiverLadder = null,
} = {}) {
  const open = Math.max(0, Number(openRosterSpots) || 0);
  const ladder = consumptionOrder(cutLadder, waiverLadder);
  const bought = Math.max(0, Number(rookiesBought) || 0);

  const spotsUsed = Math.min(bought, open);
  const rungsUsed = Math.min(ladder.length, Math.max(0, bought - open));
  const remainingLadder = ladder.slice(rungsUsed);

  return {
    openRosterSpots: open - spotsUsed,
    cutLadder: remainingLadder,
    spotsUsed,
    rungsUsed,
    // True once purchases have eaten the whole modelled ladder AND there is no
    // open spot left — at that point the model has nothing left to charge, and
    // says so rather than quietly recommending nothing.
    ladderExhausted: remainingLadder.length === 0 && open - spotsUsed === 0 && bought > 0,
  };
}

/**
 * Which phase of the draft the plan describes.
 *
 * The three states mean genuinely different things — an opening plan is a
 * theory, a live plan is a decision, and a finished draft is a record — and the
 * panel should not present them in the same voice.
 */
export function draftPhase(stats) {
  const made = Number(stats?.totalPicksMade) || 0;
  const pool = Number(stats?.rookiePoolSize) || 0;
  if (made <= 0) return "pre";
  if (pool > 0 && made >= pool) return "complete";
  return "live";
}

/**
 * What this team has actually bought so far, valued the same way the plan
 * values a prospective purchase.
 *
 * Surplus uses each rookie's board value over replacement; the cost side is the
 * ladder rungs those purchases consumed (`applyDraftProgress` says how many).
 * Reusing both primitives is deliberate — a separate "results" formula would
 * drift from the plan's and the two numbers would stop being comparable.
 */
export function realizedResults({
  stats,
  waiverValues = {},
  waiverLadder = null,
  cutLadder = [],
  openRosterSpots = 0,
  strategy = DEFAULT_STRATEGY,
} = {}) {
  // `mine` is stamped per-row by computeDraftStats, so the team is already
  // resolved here — `stats` itself carries no myTeamIdx.
  const bought = (stats?.enrichedPlayers || []).filter((p) => p?.drafted && p?.mine);
  const { rungsUsed } = applyDraftProgress({
    openRosterSpots,
    cutLadder,
    waiverLadder,
    rookiesBought: bought.length,
  });

  // Same two modes as the plan side, for the same reason: a results figure
  // computed on a different definition of replacement would not be comparable
  // to the plan it is meant to be scored against.
  const ladder = Array.isArray(waiverLadder) && waiverLadder.length ? waiverLadder : null;
  const grossSurplus = bought.reduce(
    (s, p) =>
      s +
      (ladder
        ? tiltedBoardValue(p, strategy)
        : surplusOverReplacement(p, waiverValues, strategy)),
    0,
  );
  const replacement = ladder ? replacementCost(bought.length, ladder, openRosterSpots) : 0;
  // The SAME cost and the SAME order the plan was charged on. Taking ECC here
  // while the plan takes releaseCost made "what you bought" and "what the plan
  // would buy" incomparable — which is the one thing this function exists to
  // be. On the live board 23 of 30 rungs have an ECC of 0, so realized
  // displacement was ~0 against a plan charged thousands.
  const displacement = consumptionOrder(cutLadder, waiverLadder)
    .slice(0, rungsUsed)
    .reduce((s, r) => s + (ladder ? releaseCost(r) : Number(r?.effectiveCutCost) || 0), 0);
  const spend = bought.reduce((s, p) => s + (Number(p?.pick?.amount) || 0), 0);

  return {
    count: bought.length,
    spend,
    grossSurplus,
    replacement,
    displacement,
    netValue: grossSurplus - replacement - displacement,
    players: bought,
  };
}

// ── Positional balance ─────────────────────────────────────────────────────

/**
 * Slot names that are not positions.
 *
 * The registry's `starters` block mixes real positions (`QB`, `RB`) with FLEX
 * slots that several positions can fill.  Counting `FLEX: 2` as a requirement
 * for two players "at position FLEX" would invent a need nobody can fill, so
 * flex slots are excluded from the per-position requirement and reported
 * separately as spare capacity.
 */
const FLEX_SLOTS = new Set(["FLEX", "SUPER_FLEX", "SFLEX", "IDP_FLEX", "REC_FLEX", "WRT"]);

/**
 * Positions where this roster cannot fill its own starting lineup.
 *
 * Deliberately measured against the league's OWN `starters` block rather than
 * a constant: `DEFAULT_POSITION_MINS` in `draft-logic.js` is a hand-tuned
 * shape for a generic superflex league, and this league's registry entry says
 * exactly what it starts. A threshold that disagrees with the league is worse
 * than no threshold.
 *
 * Returns `{ needs, counts, requirements }`; `needs` is `{POS: shortfall}` and
 * is empty when the roster already covers every starting slot — which is the
 * usual case on a 58-man roster, and the honest answer when it happens.
 */
export function positionalNeeds({ rosterByPosition = {}, startersByPosition = {} } = {}) {
  const counts = {};
  for (const [pos, n] of Object.entries(rosterByPosition || {})) {
    const k = String(pos).toUpperCase();
    counts[k] = Number(n) || 0;
  }
  const requirements = {};
  for (const [slot, n] of Object.entries(startersByPosition || {})) {
    const k = String(slot).toUpperCase();
    if (FLEX_SLOTS.has(k)) continue;
    const v = Number(n) || 0;
    if (v > 0) requirements[k] = v;
  }
  const needs = {};
  for (const [pos, req] of Object.entries(requirements)) {
    const have = counts[pos] || 0;
    if (have < req) needs[pos] = req - have;
  }
  return { needs, counts, requirements };
}

/**
 * How a plan changes the roster's positional shape.
 *
 * Reporting, not optimization, and that is a deliberate boundary. Folding a
 * positional minimum into the objective would need per-position counts in the
 * dynamic program's state — the product of every requirement — which is what
 * the `k`-only decomposition exists to avoid. So the plan is scored on value
 * and the positional consequence is stated beside it, where a human can weigh
 * it against a number the model is not pretending to have priced.
 */
export function planPositionBalance(plan, context) {
  const { needs, counts, requirements } = positionalNeeds(context || {});
  const added = {};
  for (const p of plan?.players || []) {
    const pos = String(p?.pos || "").toUpperCase();
    if (pos) added[pos] = (added[pos] || 0) + 1;
  }
  const unmet = {};
  for (const [pos, short] of Object.entries(needs)) {
    const remaining = short - (added[pos] || 0);
    if (remaining > 0) unmet[pos] = remaining;
  }
  const filled = Object.keys(needs).filter((pos) => (added[pos] || 0) > 0);
  return { needs, counts, requirements, added, unmet, filled };
}

// ── Opponent-aware pricing ─────────────────────────────────────────────────

export const PRICE_BASES = ["fair", "contested"];

/**
 * What a rookie costs to actually win, given who else can bid.
 *
 * An auction settles one dollar above the last rival still in, so a rookie
 * nobody can afford is cheap however he is valued. `bayesianTopCompetitor`
 * (`draft-logic.js`) already computes the richest rival's effective budget
 * weighted by that rival's demonstrated interest in this player's tier — it
 * has been computed on every board render since it was written and read by
 * nothing outside its own tests.
 *
 * `"fair"` is the default and is the shipped behaviour: the board's
 * inflation-adjusted fair price. `"contested"` caps that at what the room can
 * actually pay. The cap only ever LOWERS a price, so a contested plan is never
 * more optimistic about affordability than a fair one — it just stops
 * pretending you must outbid budgets that no longer exist, which is the whole
 * late-draft failure mode.
 */
export function contestedPrice(rookie, basis = "fair") {
  const fair = Math.max(0, Math.round(Number(rookie?.price) || 0));
  if (basis !== "contested") return fair;
  const raw = rookie?.bayesianTopCompetitor;
  // `Number(null) === 0` — the same trap that once made every player with no
  // `yearsExp` read as a rookie. An absent opponent estimate means UNKNOWN,
  // and capping an unknown at $1 would recommend the whole board for a dollar.
  if (raw === null || raw === undefined || raw === "") return fair;
  const rival = Number(raw);
  if (!Number.isFinite(rival) || rival < 0) return fair;
  // One dollar beats the field; never below $1, which is the auction minimum.
  return Math.max(1, Math.min(fair, Math.floor(rival) + 1));
}
