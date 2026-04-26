/**
 * movers — pure helpers for the /trending page.
 *
 * Pulls per-player rank/value movement out of the canonical contract
 * rows and computes window-bounded changes.  Matches the convention
 * used elsewhere: positive ``rankChange`` means the player improved
 * (moved toward rank #1), negative means they fell.
 *
 * No I/O — caller passes rows + rankHistory and gets sortable
 * mover records back.  Callable in tests without a render layer.
 */
import { computeWindowTrend, normalizePoints } from "@/lib/value-history";

export const WINDOW_OPTIONS = Object.freeze([
  { key: "1d", label: "1 day", days: 1 },
  { key: "7d", label: "7 days", days: 7 },
  { key: "30d", label: "30 days", days: 30 },
]);

export const DIRECTION_OPTIONS = Object.freeze([
  { key: "all", label: "All movers" },
  { key: "gainers", label: "Gainers" },
  { key: "losers", label: "Losers" },
]);

const POS_FAMILY = {
  QB: "QB", RB: "RB", FB: "RB", WR: "WR", TE: "TE",
  K: "K", DEF: "DEF",
  DL: "DL", DT: "DL", DE: "DL", EDGE: "DL", NT: "DL",
  LB: "LB", ILB: "LB", OLB: "LB", MLB: "LB",
  DB: "DB", CB: "DB", S: "DB", FS: "DB", SS: "DB",
};

export function familyOf(pos) {
  return POS_FAMILY[String(pos || "").toUpperCase()] || "OTHER";
}

/**
 * Compute mover records for every row.  ``windowDays`` decides which
 * rank-history window the trend is taken from; the 1-day case uses
 * the contract's pre-stamped ``rankChange`` (which is the day-over-
 * day delta the backend already computes).
 *
 * Returns rows sorted by absolute delta DESC, with ties broken by
 * higher absolute value (so a top-50 player moving 5 spots ranks
 * above a top-300 player moving the same amount).
 */
export function computeMovers(rows, { windowDays = 7, direction = "all", limit = 100 } = {}) {
  if (!Array.isArray(rows)) return [];
  const out = [];
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;

    let delta = null;
    if (windowDays <= 1) {
      const rc = Number(r.rankChange);
      delta = Number.isFinite(rc) ? rc : null;
    } else {
      const points = normalizePoints(r.rankHistory);
      const trend = computeWindowTrend(points, windowDays);
      delta = Number.isFinite(trend) ? trend : null;
    }
    if (delta == null || delta === 0) continue;

    if (direction === "gainers" && delta <= 0) continue;
    if (direction === "losers" && delta >= 0) continue;

    out.push({
      name: r.name,
      pos: r.pos,
      family: familyOf(r.pos),
      teamAbbr: r.teamAbbr || r.team || "",
      sleeperId: r.sleeperId || null,
      currentRank: Number(r.canonicalConsensusRank) || null,
      delta,
      absDelta: Math.abs(delta),
      value: Number(r.rankDerivedValue || r.values?.full || 0),
      rankHistory: r.rankHistory || null,
    });
  }
  out.sort((a, b) => {
    if (b.absDelta !== a.absDelta) return b.absDelta - a.absDelta;
    return b.value - a.value;
  });
  return out.slice(0, limit);
}

export function filterByFamily(movers, family) {
  if (!family || family === "ALL") return movers;
  return movers.filter((m) => m.family === family);
}

export function fmtDelta(v) {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "·";
  return v > 0 ? `+${v}` : String(v);
}
