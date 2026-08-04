/**
 * League analysis utilities — shared by trades, rosters, league hub.
 * Pure functions, no React dependencies.
 */

import {
  effectiveValue,
  TRADE_ALPHA,
  parsePickToken,
  getPlayerEdge,
  resolvePickRow,
  ktcAdjustPackage,
} from "@/lib/trade-logic";
import { normalizePos } from "@/lib/dynasty-data";

// ── Position Group Helpers ──────────────────────────────────────────────
export const POS_GROUPS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "PICKS"];
export const OFFENSE_GROUPS = ["QB", "RB", "WR", "TE"];

export const POS_GROUP_COLORS = {
  QB: "#e74c3c",
  RB: "#27ae60",
  WR: "#3498db",
  TE: "#e67e22",
  DL: "#9b59b6",
  LB: "#8e44ad",
  DB: "#16a085",
  PICKS: "#f39c12",
};

export const POS_GROUP_LABELS = {
  QB: "Quarterbacks",
  RB: "Running Backs",
  WR: "Wide Receivers",
  TE: "Tight Ends",
  DL: "Defensive Line",
  LB: "Linebackers",
  DB: "Defensive Backs",
  PICKS: "Draft Picks",
};

const STARTER_SLOTS = { QB: 2, RB: 3, WR: 4, TE: 2, DL: 2, LB: 2, DB: 2 };

export function posGroup(pos) {
  if (!pos) return "Other";
  const p = normalizePos(pos);
  if (["QB", "RB", "WR", "TE"].includes(p)) return p;
  if (["DL", "DE", "DT", "EDGE", "NT"].includes(p)) return "DL";
  if (["LB", "OLB", "ILB"].includes(p)) return "LB";
  if (["DB", "CB", "S", "FS", "SS"].includes(p)) return "DB";
  return "Other";
}

// ── Timestamp Helpers ───────────────────────────────────────────────────
export function normalizeTradeTimestampMs(ts) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return null;
  return n < 1_000_000_000_000 ? n * 1000 : n;
}

export function filterTradesToRollingWindow(trades, windowDays = 365) {
  if (!Array.isArray(trades) || !trades.length) return [];
  const cutoffMs = Date.now() - windowDays * 24 * 60 * 60 * 1000;
  return trades.filter((t) => {
    const ts = normalizeTradeTimestampMs(t?.timestamp);
    return Number.isFinite(ts) && ts >= cutoffMs;
  });
}

// ── Trade Grading ───────────────────────────────────────────────────────
export function gradeTradeHistorySide(pct, isWinner) {
  if (pct < 3) return { grade: "A", color: "var(--green)", label: "Fair trade" };
  if (isWinner) {
    if (pct < 8) return { grade: "A", color: "var(--green)", label: "Slight win" };
    if (pct < 15) return { grade: "A-", color: "var(--green)", label: "Good win" };
    if (pct < 25) return { grade: "B+", color: "#2ecc71", label: "Clear win" };
    return { grade: "A+", color: "#00ff88", label: "Big win" };
  }
  if (pct < 8) return { grade: "B+", color: "#2ecc71", label: "Slight overpay" };
  if (pct < 15) return { grade: "B", color: "var(--amber)", label: "Overpay" };
  if (pct < 25) return { grade: "C", color: "#e67e22", label: "Bad deal" };
  if (pct < 40) return { grade: "D", color: "var(--red)", label: "Robbery" };
  return { grade: "F", color: "#ff4444", label: "Fleeced" };
}

// ── Row Lookup Map ──────────────────────────────────────────────────────
export function buildRowLookup(rows) {
  const map = new Map();
  for (const r of rows) {
    map.set(r.name.toLowerCase(), r);
  }
  return map;
}

// ── Resolve Trade Item → Row Value ──────────────────────────────────────
/**
 * Resolve a trade item name to a value using the rows from useDynastyData.
 *
 * Picks need a multi-candidate lookup because Sleeper labels them as
 * "2026 1.04 (from Team X)" or "2027 Mid 1st (own)" while rankings
 * stores canonical rows as "2026 Pick 1.04" or "2027 Mid 1st".  The
 * `resolvePickRow` helper walks parsed candidates + backend alias map
 * so pick values surface correctly in trade history.
 */
export function resolveTradeItemValue(itemName, rowLookup, posMap, pickAliases) {
  if (!itemName) {
    return { name: itemName, value: 0, pos: "", isPick: false, playerId: "", team: "" };
  }
  const name = String(itemName).trim();
  const isPick = !!parsePickToken(name);

  if (isPick) {
    const row = resolvePickRow(name, rowLookup, pickAliases);
    if (row) {
      return {
        name,
        value: row.values?.full || 0,
        pos: "PICK",
        isPick: true,
        playerId: "",
        team: "",
      };
    }
    // No match — fall through to empty pick result below.
    return { name, value: 0, pos: "PICK", isPick: true, playerId: "", team: "" };
  }

  const key = name.toLowerCase();
  const row = rowLookup.get(key);
  if (row) {
    const baseVal = row.values?.full || 0;
    return {
      name,
      // When the user has Apply Scoring Fit on, IDP values shift by
      // ``delta × weight`` so historical trade grades reflect what
      // the deal looks like UNDER YOUR LEAGUE'S RULES, not just the
      // generic consensus.  Offense + picks pass through unchanged.
      value: baseVal,
      pos: row.pos || "",
      isPick: false,
      // Carry the Sleeper player id + NFL team forward so the trade
      // history view can render a player headshot via <PlayerImage>.
      // Both fields are best-effort: ``raw.playerId`` is stamped by
      // the contract for offensive/IDP rows; ``team`` is the NFL
      // abbreviation or empty for free agents.
      playerId: String(row.raw?.playerId || "") || "",
      team: row.team || "",
    };
  }

  // Try without parenthetical (e.g. "Jameson Williams (some annotation)")
  const stripped = name.replace(/\s*\([^)]*\)\s*$/, "").trim();
  if (stripped !== name) {
    const strippedRow = rowLookup.get(stripped.toLowerCase());
    if (strippedRow) {
      return {
        name,
        value: strippedRow.values?.full || 0,
        pos: strippedRow.pos || "",
        isPick: false,
        playerId: String(strippedRow.raw?.playerId || "") || "",
        team: strippedRow.team || "",
      };
    }
  }

  // Fallback — check position map
  const pos = posMap?.[name] || "";
  return { name, value: 0, pos, isPick: false, playerId: "", team: "" };
}

// ── Normalize Trade Asset Label ─────────────────────────────────────────
function normalizeTradeAssetLabel(raw) {
  if (!raw || typeof raw !== "string") return "";
  return raw.trim();
}

function getTradeSideItemLabels(items) {
  if (!Array.isArray(items)) return [];
  return items.map(normalizeTradeAssetLabel).filter(Boolean);
}

// ── Owner / Roster → current team name map ─────────────────────────────
/**
 * Build lookup maps from Sleeper identifiers to the CURRENT team name.
 *
 * Returns `{ byOwner, byRoster }`.  Both are lowercase-keyed Maps.
 * Callers should prefer owner_id (authoritative per-human) and fall
 * back to roster_id only when ownerId is missing on the source.
 *
 * Why owner-first:
 *   - Historical trades store the team name as it was at trade time.
 *     Grouping by that name splits a single manager's record when
 *     they rename their team (e.g. "Draft Daddies" → "Russini
 *     Panini").  Aggregating by owner_id unifies those cleanly.
 *   - Grouping by roster_id alone is WRONG for dynasty leagues that
 *     have had orphaned rosters change hands across seasons — the
 *     roster_id stays stable but the human behind it changed, so
 *     historical trades from the previous manager would be
 *     attributed to the new one.  Owner_id is stable per human
 *     across the league chain and splits manager changes correctly.
 */
export function buildSleeperIdentityMaps(sleeperTeams) {
  const byOwner = new Map();
  const byRoster = new Map();
  for (const t of sleeperTeams || []) {
    const name = String(t?.name || "");
    const oid = t?.ownerId;
    if (oid) byOwner.set(String(oid).toLowerCase(), name);
    const rid = t?.roster_id;
    if (rid != null) byRoster.set(String(rid), name);
  }
  return { byOwner, byRoster };
}

// Legacy export retained for any caller that still imports the old
// rosterId-only map.  Internal call sites should use
// ``buildSleeperIdentityMaps`` directly.
export function buildRosterIdNameMap(sleeperTeams) {
  return buildSleeperIdentityMaps(sleeperTeams).byRoster;
}

/**
 * Pick a stable aggregation key for a trade side.
 *
 * Preference order: `ownerId` (per-human, splits orphan takeovers) →
 * `rosterId` (per-roster, legacy fallback when the scraper did not
 * emit ownerId) → team name (last-resort fallback when neither id is
 * present on older scraper output).
 */
function sideAggregationKey(side) {
  if (side == null) return "";
  if (side.ownerId) return `oid:${String(side.ownerId).toLowerCase()}`;
  if (side.rosterId != null) return `rid:${side.rosterId}`;
  return `name:${side.team || ""}`;
}

/**
 * Resolve the display name for a trade side.
 *
 * Resolution order:
 *   1. If the side carries an ownerId and that owner still holds a
 *      team in the current league, use the CURRENT team name.  This
 *      unifies renamed teams under their current name.
 *   2. If the side carries an ownerId that is NOT in the current
 *      league (orphan takeover: this owner left and the roster was
 *      handed off to someone else), fall back to the HISTORICAL team
 *      name from the side — never to `byRoster`, because rosterId
 *      now resolves to the new manager and would mis-attribute the
 *      trade.
 *   3. If the side has no ownerId at all (legacy scraper data), use
 *      the rosterId map when present and finally the historical
 *      team name.
 */
function sideDisplayName(side, identityMaps) {
  if (side == null) return "";
  if (side.ownerId) {
    const current = identityMaps?.byOwner?.get(String(side.ownerId).toLowerCase());
    if (current) return current;
    // ownerId present but not in current league → orphan takeover.
    // Keep the historical team name rather than leaking the new
    // manager's name via rosterId.
    return side.team || "";
  }
  if (side.rosterId != null && identityMaps?.byRoster) {
    const current = identityMaps.byRoster.get(String(side.rosterId));
    if (current) return current;
  }
  return side.team || "";
}

// ── Analyze Sleeper Trade History ───────────────────────────────────────
/**
 * Analyze all Sleeper trades within the rolling window.
 * Returns { windowDays, analyzed, teamScores }.
 *
 * Each side carries both what that team GAVE and what they GOT, plus
 * per-side net gain on both the linear and alpha-weighted scales.  A
 * side's grade and pctGap are computed from its OWN net (gotWeighted
 * minus gaveWeighted) rather than compared against other sides'
 * received totals — this matters for 3+ team trades where each team's
 * sent and received pools don't pair up.  For 2-team trades the old
 * "compare received totals" math is algebraically equivalent, because
 * A.got = B.gave and vice versa.
 *
 * Aggregation is keyed by `ownerId` (Sleeper user id) so trades from
 * managers who renamed their team roll up under the current team
 * name, while trades from an orphaned roster that changed hands stay
 * split across the two owners.  Falls back to rosterId and then team
 * name for older scraper output that did not emit ownerId.
 */
// Resolve a list of raw item labels to { items, linear, weighted, values }.
// ``weighted`` uses the alpha exponent so a single star asset counts
// more than a pile of scrubs with the same linear sum.  ``values`` is
// the bare numeric array — needed by V12 VA which computes per-piece
// raw_adjustments based on the absolute KTC scale.
function resolveTradeSideList(rawList, ctx) {
  const { rowLookup, posMap, pickAliases, alpha } = ctx;
  const items = [];
  const values = [];
  let linear = 0;
  let weighted = 0;
  for (const rawItem of getTradeSideItemLabels(rawList)) {
    const resolved = resolveTradeItemValue(rawItem, rowLookup, posMap, pickAliases);
    const safeVal = Number.isFinite(resolved.value) ? Math.max(0, resolved.value) : 0;
    linear += safeVal;
    weighted += Math.pow(Math.max(safeVal, 1), alpha);
    if (safeVal > 0) values.push(safeVal);
    items.push({
      name: resolved.name,
      val: Math.round(safeVal),
      pos: resolved.pos,
      isPick: resolved.isPick,
      playerId: resolved.playerId,
      team: resolved.team,
    });
  }
  return { items, linear, weighted, values };
}

// KTC value adjustment for one team's "got vs gave" comparison —
// routes through ``ktcAdjustPackage``, the verbatim port of KTC's
// site.min.js algorithm (PR #335).  Treat got/gave as a 2-side trade:
// positive ``vaNet`` means this team RECEIVED the stud premium (got
// side wins on KTC's intensity-adjusted raw_adj); negative means they
// GAVE the studs away.  Pure: value arrays only, no React/row refs.
export function computeTradeVANet(gotValues, gaveValues) {
  if (!gotValues.length || !gaveValues.length) return 0;
  const result = ktcAdjustPackage(gotValues, gaveValues);
  if (!result.displayed || result.value <= 0) return 0;
  // ktcAdjustPackage's `side` follows KTC's team1/team2 convention.
  // We pass got=team1, gave=team2.  side=1 means got receives the VA
  // (positive); side=2 means gave receives it (penalty for got).
  return result.side === 1 ? result.value : -result.value;
}

// ── The canonical grade (twin: src/public_league/trade_grading.py) ──────
//
// A trade gets a letter grade in exactly two places: here, for the
// private /trades page, and in Python for the public /league activity
// timeline, which is server-rendered and cannot import this file.
// Until the 2026-08-04 math audit (finding C3) the public half used a
// DIFFERENT formula against the SAME band table — it summed
// ``max(value, 1) ** 1.65`` per received asset and compared side totals,
// which inflates a 10% linear edge into a ~16% one and pushed trades a
// full band up.  The two are now pinned together by a shared fixture,
// ``tests/fixtures/trade_grade_parity_cases.json``, asserted from both
// languages.  Keep the functions below and their Python twins in
// lockstep; the fixture is what notices when they drift.

/** Clamp one side's resolved asset values: finite, strictly positive. */
export function sanitizeSideValues(raw) {
  const out = [];
  for (const v of raw || []) {
    const num = Number(v);
    if (Number.isFinite(num) && num > 0) out.push(num);
  }
  return out;
}

/**
 * Grade ONE side from its OWN net, with the VA supplied by the caller.
 *
 * Split from ``gradeTradeSides`` so the shared parity fixture can pin
 * the ratio-and-band arithmetic against hand-computed numbers for an
 * arbitrary ``vaNet``, independently of the KTC VA engine.
 *
 * The denominator is the larger EFFECTIVE side total (linear + the VA
 * on whichever side earned it).  It deliberately does NOT include the
 * alpha-powered weighted sums — those dominate by an order of magnitude
 * and would crush all pcts toward the extremes of the band table.
 */
export function gradeTradeSide(gotValues, gaveValues, vaNet) {
  const gotLinear = gotValues.reduce((s, v) => s + v, 0);
  const gaveLinear = gaveValues.reduce((s, v) => s + v, 0);
  const netLinear = gotLinear - gaveLinear;
  const netAdjusted = netLinear + vaNet;
  const gotEffective = gotLinear + Math.max(0, vaNet);
  const gaveEffective = gaveLinear + Math.max(0, -vaNet);
  const scale = Math.max(gotEffective, gaveEffective, 1);
  const pctGap = (netAdjusted / scale) * 100;
  return {
    gotValue: gotLinear,
    gaveValue: gaveLinear,
    netValue: netLinear,
    vaNet,
    netAdjusted,
    pctGap,
    grade: gradeTradeHistorySide(Math.abs(pctGap), pctGap > 0),
  };
}

/**
 * Grade every side of one trade from ``[{got: number[], gave: number[]}]``.
 *
 * Each side is graded on its OWN net rather than against the other
 * sides' received totals — which is what makes 3+ team trades come out
 * right, since the sent and received pools don't pair up there.  For a
 * two-team trade the two are algebraically identical (A.got == B.gave).
 */
export function gradeTradeSides(sides) {
  return (sides || []).map(({ got, gave }) => {
    const gotValues = sanitizeSideValues(got);
    const gaveValues = sanitizeSideValues(gave);
    return gradeTradeSide(
      gotValues,
      gaveValues,
      computeTradeVANet(gotValues, gaveValues),
    );
  });
}

/**
 * Build the shared resolution context (row lookup, position map, pick
 * aliases, identity maps, alpha) used to value any single trade.
 * Extracted so both the rolling-window scan and the two-team combined
 * aggregator value assets through exactly the same pipeline.
 */
export function buildTradeAnalysisCtx(rawData, rows, alpha = TRADE_ALPHA) {
  return {
    rowLookup: buildRowLookup(rows),
    posMap: rawData?.sleeper?.positions || {},
    pickAliases: rawData?.pickAliases || null,
    identityMaps: buildSleeperIdentityMaps(rawData?.sleeper?.teams),
    alpha,
  };
}

/**
 * Analyze ONE raw trade ({week, timestamp, sides:[{team, got, gave,
 * ownerId?, rosterId?}]}) into the rendered card shape.  Pure given a
 * ctx from ``buildTradeAnalysisCtx``.  Does NOT touch teamScores —
 * the caller owns league-wide aggregation.
 */
export function analyzeRawTrade(trade, ctx) {
  const { identityMaps } = ctx;
  const ts = normalizeTradeTimestampMs(trade.timestamp);
  const date = ts ? new Date(ts).toLocaleDateString() : "?";
  const sides = [];

  const resolved = (trade.sides || []).map((side) => ({
    side,
    got: resolveTradeSideList(side?.got, ctx),
    gave: resolveTradeSideList(side?.gave, ctx),
  }));
  // ONE grading call for the whole trade, through the function the
  // public /league timeline's Python twin also implements.
  const graded = gradeTradeSides(
    resolved.map((r) => ({ got: r.got.values, gave: r.gave.values })),
  );

  for (let i = 0; i < resolved.length; i++) {
    const { side, got, gave } = resolved[i];
    const g = graded[i];
    const displayTeam = sideDisplayName(side, identityMaps);
    sides.push({
      team: displayTeam,
      historicalTeam: side.team || "",
      ownerId: side.ownerId || null,
      rosterId: side.rosterId ?? null,
      got: got.items,
      gave: gave.items,
      gotValue: got.linear,
      gotWeighted: got.weighted,
      gaveValue: gave.linear,
      gaveWeighted: gave.weighted,
      netValue: g.netValue,
      // Alpha-weighted net.  NOT a grading input — it survives only as
      // the magnitude ``teamScores.totalGain`` accumulates, where the
      // concentration premium is the point.
      netWeighted: got.weighted - gave.weighted,
      vaNet: g.vaNet,
      netAdjusted: g.netAdjusted,
      pctGap: g.pctGap,
      grade: g.grade,
    });
  }

  // ``winner``/``loser`` and ``headlineSide`` are the same question
  // asked two ways, so they have to read the same quantity: the
  // extremes of ``netAdjusted`` and the biggest |pctGap| are both the
  // canonical linear+VA net, ranked by sign and by magnitude.  Until
  // the 2026-08-04 audit ``winner`` sorted on ``netWeighted`` instead,
  // and those two orderings genuinely disagree on a stud-for-pile
  // trade: taking 5000+5000 for a 9000 is +1000 linear but ~−0.8M
  // alpha, so one card could name a winner its own grades called the
  // loser.  Headline still reflects the largest grievance — biggest
  // magnitude, winner or loser.
  const sortedByNet = [...sides].sort((a, b) => b.netAdjusted - a.netAdjusted);
  const winner = sortedByNet[0] || null;
  const loser = sortedByNet[sortedByNet.length - 1] || null;
  const headlineSide = sides.reduce(
    (best, s) => (Math.abs(s.pctGap) > Math.abs(best?.pctGap ?? 0) ? s : best),
    null,
  );
  const headlinePct = headlineSide ? Math.abs(headlineSide.pctGap) : 0;
  const headlineNet = headlineSide
    ? Math.abs(Math.round(headlineSide.netAdjusted ?? headlineSide.netValue))
    : 0;
  const headlineDirection =
    headlineSide && headlineSide.pctGap < 0 ? "overpaid" : "won";

  return {
    trade,
    date,
    sides,
    winner,
    loser,
    pctGap: headlinePct,
    headlineNet,
    headlineSide,
    headlineDirection,
    winnerGrade: winner ? winner.grade : null,
    loserGrade: loser && loser !== winner ? loser.grade : null,
  };
}

export function analyzeSleeperTradeHistory(rawData, rows, windowDays = 365, alpha = TRADE_ALPHA) {
  const trades = rawData?.sleeper?.trades;
  if (!Array.isArray(trades) || !trades.length) {
    return { windowDays, analyzed: [], teamScores: {} };
  }

  const filtered = filterTradesToRollingWindow(trades, windowDays);
  if (!filtered.length) return { windowDays, analyzed: [], teamScores: {} };

  const ctx = buildTradeAnalysisCtx(rawData, rows, alpha);
  const teamScores = {};
  const analyzed = [];

  for (const trade of filtered) {
    const entry = analyzeRawTrade(trade, ctx);

    // Per-side W/L for team scores.  3% is the fairness threshold —
    // any trade where every team's net rounds below 3% shouldn't
    // count as a win or loss for anyone.
    for (const s of entry.sides) {
      const key = sideAggregationKey(s);
      if (!teamScores[key]) {
        teamScores[key] = {
          displayName: s.team,
          ownerId: s.ownerId,
          rosterId: s.rosterId,
          won: 0,
          lost: 0,
          totalGain: 0,
          trades: 0,
        };
      }
      teamScores[key].trades++;
      if (s.pctGap >= 3) {
        teamScores[key].won++;
        teamScores[key].totalGain += s.netWeighted;
      } else if (s.pctGap <= -3) {
        teamScores[key].lost++;
        teamScores[key].totalGain += s.netWeighted;
      }
    }

    analyzed.push(entry);
  }

  return { windowDays, analyzed, teamScores };
}

// ── Two-Team Combined Trade History ─────────────────────────────────────
/**
 * Collapse the ENTIRE head-to-head trade history between two teams
 * into a SINGLE synthetic trade.  Only pure 2-team trades whose two
 * sides are exactly ``teamA`` and ``teamB`` are considered (3+ team
 * trades have ambiguous A↔B flow and are skipped).
 *
 * Net-flow rule, from team A's perspective: +1 every time A received
 * an asset, -1 every time A sent it.  An asset that bounced back and
 * forth therefore cancels — an even number of crossings nets to zero
 * (omitted entirely), an odd number collapses to a single instance in
 * its net direction.  Example: Dak going Brent→Roy, Roy→Brent, then
 * Brent→Roy again nets to Dak going Brent→Roy exactly once; a single
 * there-and-back cancels out.
 *
 * Returns an analyzed-trade entry (same shape as ``analyzeRawTrade``,
 * with ``combined: true`` plus ``teamA`` / ``teamB`` / ``tradeCount``),
 * ``{ wash: true, ... }`` when every asset cancelled, or ``null`` when
 * the two teams never traded head-to-head.
 */
export function buildCombinedPairTrade(analysis, teamA, teamB, rawData, rows, alpha = TRADE_ALPHA) {
  if (!teamA || !teamB || teamA === teamB) return null;
  const analyzed = analysis?.analyzed || [];
  const headToHead = analyzed.filter(
    (a) =>
      a.sides.length === 2 &&
      a.sides.some((s) => s.team === teamA) &&
      a.sides.some((s) => s.team === teamB),
  );
  if (!headToHead.length) return null;

  // asset label → net count from A's perspective (+got, -gave).
  // Keyed by the exact resolved label so a player/pick that bounced
  // back and forth between A and B cancels cleanly.
  const ledger = new Map();
  let latestTs = 0;
  for (const a of headToHead) {
    const sideA = a.sides.find((s) => s.team === teamA);
    if (!sideA) continue;
    const ts =
      normalizeTradeTimestampMs(a.trade?.timestamp) || Date.parse(a.date) || 0;
    if (Number.isFinite(ts) && ts > latestTs) latestTs = ts;
    for (const it of sideA.got || []) {
      ledger.set(it.name, (ledger.get(it.name) || 0) + 1);
    }
    for (const it of sideA.gave || []) {
      ledger.set(it.name, (ledger.get(it.name) || 0) - 1);
    }
  }

  const aGot = [];
  const aGave = [];
  for (const [name, net] of ledger) {
    if (!name) continue;
    if (net > 0) aGot.push(name);
    else if (net < 0) aGave.push(name);
  }

  if (!aGot.length && !aGave.length) {
    // Everything they swapped came back — a net wash.
    return { wash: true, teamA, teamB, tradeCount: headToHead.length };
  }

  const synthetic = {
    week: null,
    timestamp: latestTs || Date.now(),
    sides: [
      { team: teamA, got: aGot, gave: aGave },
      { team: teamB, got: aGave, gave: aGot },
    ],
  };
  const ctx = buildTradeAnalysisCtx(rawData, rows, alpha);
  const entry = analyzeRawTrade(synthetic, ctx);
  entry.combined = true;
  entry.teamA = teamA;
  entry.teamB = teamB;
  entry.tradeCount = headToHead.length;
  entry.date = `${headToHead.length} trade${headToHead.length === 1 ? "" : "s"} combined`;
  return entry;
}

// ── Build Player Meta Map ───────────────────────────────────────────────
/**
 * Build a lookup map: lowercase player name → { name, pos, group, meta, isPick }.
 * Uses row values from useDynastyData.
 */
export function buildPlayerMetaMap(rows) {
  const map = {};
  for (const r of rows) {
    if (r.pos === "PICK" || r.pos === "K") continue;
    const group = posGroup(r.pos);
    map[r.name.toLowerCase()] = {
      name: r.name,
      pos: r.pos,
      group,
      meta: r.values?.full || 0,
      isPick: false,
      // Carry the Sleeper player id + NFL team forward so the rosters
      // page (Trade Targets, Trade Chips, waiver gems) can render a
      // <PlayerImage> without re-looking-up the row in dynasty-data.
      // Rows missing these fields fall back to the position-tinted
      // initials chip — same fallback chain as everywhere else.
      playerId: String(r.raw?.playerId || "") || "",
      team: r.team || "",
    };
  }
  return map;
}

// ── Team Value Breakdown ────────────────────────────────────────────────
function sumTopN(values, n) {
  if (!Array.isArray(values) || n <= 0) return 0;
  return values
    .filter((v) => Number.isFinite(v) && v > 0)
    .sort((a, b) => b - a)
    .slice(0, n)
    .reduce((s, v) => s + v, 0);
}

/**
 * Compute per-position-group value breakdown for a team.
 * @param {object} team - { players: string[], picks: string[] }
 * @param {object} playerMeta - from buildPlayerMetaMap
 * @param {object[]} rows - all rows for pick value lookup
 * @param {string} assetScope - WHICH ASSETS to count: "full" (players +
 *   picks) | "players" | "starters".  NOT a valuation selector — note
 *   that `lib/trade-logic.js` exports a different `VALUE_MODES`
 *   ("full" | "raw") meaning which value NUMBER to read.  Both use the
 *   key "full", so mixing them up runs clean and returns wrong totals.
 * @param {object} [pickAliases] - optional backend alias map
 * @returns {{ total, byGroup, playerDetails, pickDetails }}
 */
export function buildTeamValueBreakdown(team, playerMeta, rows, assetScope = "full", pickAliases = null) {
  const byGroup = {};
  POS_GROUPS.forEach((g) => { byGroup[g] = 0; });
  const playerDetails = [];
  const buckets = { QB: [], RB: [], WR: [], TE: [], DL: [], LB: [], DB: [] };
  let pickValue = 0;
  const pickDetails = [];

  const teamPlayers = Array.isArray(team.players) ? team.players : [];
  const teamPicks = Array.isArray(team.picks) ? team.picks : [];

  // Build row lookup for pick resolution
  const rowLookup = buildRowLookup(rows);

  for (const pName of teamPlayers) {
    if (parsePickToken(pName)) continue;
    const key = pName.toLowerCase();
    const pm = playerMeta[key];
    if (!pm) continue;
    playerDetails.push(pm);
    if (assetScope !== "starters") {
      if (byGroup[pm.group] !== undefined) byGroup[pm.group] += pm.meta;
    }
    if (buckets[pm.group]) buckets[pm.group].push(pm.meta);
  }

  // Resolve pick values using multi-candidate lookup so Sleeper labels
  // like "2026 1.04 (from Team X)" resolve against rankings rows stored
  // as "2026 Pick 1.04".
  if (assetScope === "full") {
    const pickSources = teamPicks.length > 0 ? teamPicks : teamPlayers.filter((p) => parsePickToken(p));
    for (const pickName of pickSources) {
      if (!parsePickToken(pickName)) continue;
      const row = resolvePickRow(pickName, rowLookup, pickAliases);
      const val = row ? (row.values?.full || 0) : 0;
      pickValue += val;
      if (val > 0) {
        pickDetails.push({ name: pickName, meta: val, pos: "PICK", group: "PICKS", isPick: true });
      }
    }
  }

  if (assetScope === "starters") {
    Object.keys(buckets).forEach((g) => {
      byGroup[g] = sumTopN(buckets[g], STARTER_SLOTS[g] || 0);
    });
  }

  byGroup.PICKS = assetScope === "full" ? pickValue : 0;
  const total = POS_GROUPS.reduce((s, g) => s + (byGroup[g] || 0), 0);

  return { total, byGroup, playerDetails, pickDetails };
}

// ── Build All Team Summaries ────────────────────────────────────────────
/**
 * Build summary data for all teams in the league.
 * Returns sorted array of team objects with value breakdowns.
 */
export function buildAllTeamSummaries(sleeperTeams, playerMeta, rows, assetScope = "full", pickAliases = null) {
  const teams = (sleeperTeams || []).map((team) => {
    const breakdown = buildTeamValueBreakdown(team, playerMeta, rows, assetScope, pickAliases);
    return {
      name: team.name,
      roster_id: team.roster_id,
      total: breakdown.total,
      byGroup: breakdown.byGroup,
      playerCount: (team.players || []).length,
      pickCount: Array.isArray(team.picks) ? team.picks.length : 0,
      players: breakdown.playerDetails,
      pickDetails: breakdown.pickDetails,
    };
  });

  teams.sort((a, b) => b.total - a.total);
  return teams;
}

// ── Group Averages ──────────────────────────────────────────────────────
export function computeGroupAverages(teams) {
  const avg = {};
  POS_GROUPS.forEach((g) => {
    const vals = teams.map((t) => t.byGroup[g] || 0);
    avg[g] = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  });
  return avg;
}

// ── Position Ranks per Group ────────────────────────────────────────────
export function computePositionRanks(teams) {
  const ranks = {};
  POS_GROUPS.forEach((g) => {
    const sorted = teams.slice().sort((a, b) => (b.byGroup[g] || 0) - (a.byGroup[g] || 0));
    sorted.forEach((t, i) => {
      if (!ranks[t.name]) ranks[t.name] = {};
      ranks[t.name][g] = i + 1;
    });
  });
  return ranks;
}

// ── Heatmap Color ───────────────────────────────────────────────────────
export function heatmapColor(rank, total) {
  const p = (rank - 1) / Math.max(total - 1, 1);
  if (p <= 0.25) return `rgb(${(10 + (p / 0.25) * 20) | 0},${(80 + (p / 0.25) * 60) | 0},${(100 + (p / 0.25) * 40) | 0})`;
  if (p <= 0.5) { const t = (p - 0.25) / 0.25; return `rgb(${(30 + t * 30) | 0},${(140 - t * 40) | 0},${(140 - t * 20) | 0})`; }
  if (p <= 0.75) { const t = (p - 0.5) / 0.25; return `rgb(${(60 + t * 100) | 0},${(100 - t * 40) | 0},${(120 - t * 30) | 0})`; }
  const t = (p - 0.75) / 0.25;
  return `rgb(${(160 + t * 60) | 0},${(60 - t * 20) | 0},${(90 - t * 20) | 0})`;
}

export function heatmapTextColor(bgColor) {
  const m = String(bgColor || "").match(/rgb\(\s*(\d+),\s*(\d+),\s*(\d+)\s*\)/i);
  if (!m) return "#111";
  const r = Number(m[1]) || 0;
  const g = Number(m[2]) || 0;
  const b = Number(m[3]) || 0;
  const lum = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
  return lum < 0.54 ? "#f0f0f0" : "#111";
}

// ── Ordinal suffix ──────────────────────────────────────────────────────
export function ordinal(n) {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

// ── Waiver Wire Gems ────────────────────────────────────────────────────
/**
 * Find unrostered players with high trade value.
 * @param {object[]} rows - all player rows
 * @param {object[]} sleeperTeams - teams with .players arrays
 * @returns {object[]} Sorted array of { name, pos, value }
 */
export function findWaiverWireGems(rows, sleeperTeams) {
  const rosteredSet = new Set();
  for (const team of sleeperTeams || []) {
    for (const p of team.players || []) {
      rosteredSet.add(p.toLowerCase());
    }
  }

  const gems = [];
  for (const row of rows) {
    if (row.pos === "PICK" || row.pos === "K" || row.pos === "?") continue;
    if (rosteredSet.has(row.name.toLowerCase())) continue;
    if ((row.values?.full || 0) < 500) continue;
    gems.push({
      name: row.name,
      pos: row.pos,
      value: row.values?.full || 0,
      // Carry the Sleeper player id + NFL team forward so the waiver-
      // wire chip can render a <PlayerImage>.
      playerId: String(row.raw?.playerId || "") || "",
      team: row.team || "",
    });
  }

  gems.sort((a, b) => b.value - a.value);
  return gems.slice(0, 25);
}

// ── League Edge Map ─────────────────────────────────────────────────────
const MIN_EDGE_PCT = 3;

/**
 * Build league-wide edge analysis — per-team market overvalue/undervalue signals.
 * Uses getPlayerEdge from trade-logic.js for individual player edge signals.
 */
export function buildLeagueEdgeMap(rows, sleeperTeams, myTeamName = "") {
  const rowLookup = buildRowLookup(rows);
  const teamEdges = [];

  for (const team of sleeperTeams || []) {
    let totalSellEdge = 0;
    let totalBuyEdge = 0;
    let sellCount = 0;
    let buyCount = 0;
    const topSells = [];
    const topBuys = [];

    for (const pName of team.players || []) {
      if (parsePickToken(pName)) continue;
      const row = rowLookup.get(pName.toLowerCase());
      if (!row) continue;
      const edge = getPlayerEdge(row);
      if (!edge || !edge.signal) continue;

      if (edge.signal === "SELL") {
        totalSellEdge += edge.edgePct;
        sellCount++;
        topSells.push({ name: pName, pct: edge.edgePct });
      } else if (edge.signal === "BUY") {
        totalBuyEdge += edge.edgePct;
        buyCount++;
        topBuys.push({ name: pName, pct: edge.edgePct });
      }
    }

    topSells.sort((a, b) => b.pct - a.pct);
    topBuys.sort((a, b) => b.pct - a.pct);

    teamEdges.push({
      name: team.name,
      isMe: team.name === myTeamName,
      sellEdge: Math.round(totalSellEdge),
      buyEdge: Math.round(totalBuyEdge),
      sellCount,
      buyCount,
      topSells: topSells.slice(0, 3),
      topBuys: topBuys.slice(0, 3),
    });
  }

  // Sort by most exploitable (highest sell edge)
  teamEdges.sort((a, b) => b.sellEdge - a.sellEdge);
  return teamEdges;
}

// ── Trade Tendencies ────────────────────────────────────────────────────
/**
 * Analyze per-manager trading patterns: avg given/got, net, position bias.
 * @param {object} rawData - the rawData from useDynastyData
 * @param {object[]} rows - all player rows
 * @returns {object[]} Sorted array of { manager, trades, avgGiven, avgGot, net, tendency }
 */
export function analyzeTradeTendencies(rawData, rows) {
  const trades = rawData?.sleeper?.trades;
  if (!Array.isArray(trades) || !trades.length) return [];

  const rowLookup = buildRowLookup(rows);
  const posMap = rawData?.sleeper?.positions || {};
  const pickAliases = rawData?.pickAliases || null;
  const identityMaps = buildSleeperIdentityMaps(rawData?.sleeper?.teams);
  const managerStats = {};

  // Shared resolver that handles both players and pick labels, so trade
  // tendency totals include pick value rather than silently dropping
  // picks that fail a direct rowLookup hit.
  const resolveAssetValue = (name) => {
    if (!name) return 0;
    if (parsePickToken(name)) {
      const row = resolvePickRow(name, rowLookup, pickAliases);
      return row ? (row.values?.full || 0) : 0;
    }
    const row = rowLookup.get(String(name).toLowerCase());
    return row ? (row.values?.full || 0) : 0;
  };

  for (const trade of trades) {
    if (!trade.sides || trade.sides.length < 2) continue;
    for (const side of trade.sides) {
      // Key by ownerId (falls back to rosterId / team name) so
      // renamed teams roll up into a single row per human while
      // orphan takeovers stay split across owners.
      const key = sideAggregationKey(side);
      const displayName = sideDisplayName(side, identityMaps) || "Unknown";
      if (!managerStats[key]) {
        managerStats[key] = {
          manager: displayName,
          trades: 0,
          totalGiven: 0,
          totalGot: 0,
          posBias: {},
        };
      }
      const stats = managerStats[key];
      stats.trades++;

      let gotTotal = 0;
      let gaveTotal = 0;
      for (const name of side.got || []) {
        gotTotal += resolveAssetValue(name);
      }
      for (const name of side.gave || []) {
        gaveTotal += resolveAssetValue(name);
      }
      stats.totalGot += gotTotal;
      stats.totalGiven += gaveTotal;

      // Track position bias in acquisitions
      for (const name of side.got || []) {
        let pos = (posMap[name] || "").toUpperCase();
        if (!pos) continue;
        if (["LB", "DL", "DE", "DT", "CB", "S", "DB", "EDGE"].includes(pos)) pos = "IDP";
        stats.posBias[pos] = (stats.posBias[pos] || 0) + 1;
      }
    }
  }

  return Object.entries(managerStats)
    .map(([key, s]) => {
      const avgGiven = Math.round(s.totalGiven / Math.max(s.trades, 1));
      const avgGot = Math.round(s.totalGot / Math.max(s.trades, 1));
      const net = avgGot - avgGiven;
      const topPos = Object.entries(s.posBias).sort((a, b) => b[1] - a[1])[0];
      const tendency = topPos ? `Targets ${topPos[0]}s` : "\u2014";
      // `id` is the ownerId-first aggregation key so the React table
      // can key rows uniquely even when two managers happen to share
      // a display name.
      return { id: key, manager: s.manager, trades: s.trades, avgGiven, avgGot, net, tendency };
    })
    .sort((a, b) => b.trades - a.trades);
}

// ── Contender / Rebuilder Tiers ─────────────────────────────────────────
/**
 * Score and tier all teams: contender / mid-tier / rebuilder.
 *
 *   score = 0.7 × starterValue + 0.2 × depthValue − 0.1 × pickValue
 *
 * Starter value = the team's top 10 OFFENSIVE players.
 * Depth        = every other player the team owns — picks excluded.
 * Picks        = pick capital, penalized at −10% (rebuild signal).
 *
 * Picks sit OUTSIDE depthValue deliberately.  Depth used to be
 * `totalValue − starterValue`, and totalValue includes pick capital, so
 * every pick dollar earned +0.2 as depth and paid −0.1 as pick surplus
 * for a NET +0.1: the "penalty" REWARDED hoarding picks, the opposite
 * of the documented intent, and a pick-rich rebuilder could out-score a
 * contender.  Each dollar of a roster now feeds exactly one term.
 *
 * The three coefficients do not sum to 1 and don't need to — the score
 * is an ordinal ranking key (the sorted list is cut into thirds), so
 * only the RATIOS between the terms move a team's tier.
 */
export function scoreTeamTiers(sleeperTeams, playerMeta, rows, pickAliases = null) {
  const rowLookup = buildRowLookup(rows);

  const scored = (sleeperTeams || []).map((team) => {
    let totalValue = 0;
    const topPlayers = [];
    let pickValue = 0;

    for (const pName of team.players || []) {
      if (parsePickToken(pName)) continue;
      const pm = playerMeta[(pName || "").toLowerCase()];
      if (!pm) continue;
      totalValue += pm.meta;
      if (OFFENSE_GROUPS.includes(pm.group)) {
        topPlayers.push(pm.meta);
      }
    }

    // Picks — use multi-candidate lookup so Sleeper labels resolve
    // against canonical rankings rows.
    for (const pickName of team.picks || []) {
      const row = resolvePickRow(pickName, rowLookup, pickAliases);
      const val = row ? (row.values?.full || 0) : 0;
      totalValue += val;
      pickValue += val;
    }

    topPlayers.sort((a, b) => b - a);
    const starterValue = topPlayers.slice(0, 10).reduce((s, v) => s + v, 0);
    // Players only: totalValue carries pick capital too, and picks are
    // scored by their own term below.
    const depthValue = totalValue - starterValue - pickValue;
    const score = starterValue * 0.7 + depthValue * 0.2 + (pickValue > 0 ? -pickValue * 0.1 : 0);

    return {
      name: team.name,
      score,
      totalValue,
      starterValue,
      depthValue,
      pickValue,
    };
  });

  scored.sort((a, b) => b.score - a.score);
  const n = scored.length;
  const top = Math.ceil(n / 3);
  const bot = n - top;

  return scored.map((t, i) => ({
    ...t,
    tier: i < top ? "contender" : i >= bot ? "rebuilder" : "middle",
    tierLabel: i < top ? "Contender" : i >= bot ? "Rebuilder" : "Mid-Tier",
    rank: i + 1,
  }));
}
