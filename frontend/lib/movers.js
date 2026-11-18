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
import { familyOf } from "@/lib/position-family";

// Re-exported so existing ``@/lib/movers`` importers keep working; the
// map itself lives in lib/position-family (shared with activity-feed).
export { familyOf };

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

/**
 * Compute mover records for every row.  ``windowDays`` decides which
 * rank-history window the trend is taken from; the 1-day case uses
 * the contract's pre-stamped ``rankChange`` (which is the day-over-
 * day delta the backend already computes).
 *
 * Returns rows sorted by absolute delta DESC, with ties broken by
 * higher absolute value (so a top-50 player moving 5 spots ranks
 * above a top-300 player moving the same amount).
 *
 * A player OFF the board — no current backend rank — is not a mover: a
 * rank change needs a rank now.  Such rows used to be listed with Value
 * ``0`` (a missing value coerced to zero) and the stale delta from
 * whenever their history ended.  They are excluded, and a multi-day
 * trend is anchored at the board's latest snapshot so a history that
 * stopped early cannot pass for a current move.
 */
export function computeMovers(rows, { windowDays = 7, direction = "all", limit = 100 } = {}) {
  if (!Array.isArray(rows)) return [];
  const multiDay = windowDays > 1;
  const pointsByRow = new Map();
  let boardAsOf = null;
  if (multiDay) {
    for (const r of rows) {
      if (!r || typeof r !== "object") continue;
      const points = normalizePoints(r.rankHistory);
      pointsByRow.set(r, points);
      const last = points[points.length - 1];
      if (last && (boardAsOf == null || last.t > boardAsOf)) boardAsOf = last.t;
    }
  }
  const out = [];
  for (const r of rows) {
    if (!r || typeof r !== "object") continue;
    const rank = Number(r.canonicalConsensusRank);
    if (!Number.isFinite(rank) || rank <= 0) continue;

    let delta = null;
    if (!multiDay) {
      const rc = Number(r.rankChange);
      delta = r.rankChange == null || !Number.isFinite(rc) ? null : rc;
    } else {
      const trend = computeWindowTrend(pointsByRow.get(r) || [], windowDays, {
        asOf: boardAsOf ?? undefined,
      });
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
      currentRank: rank,
      delta,
      absDelta: Math.abs(delta),
      value: positiveOrNull(r.rankDerivedValue) ?? positiveOrNull(r.values?.full),
      rankHistory: r.rankHistory || null,
    });
  }
  out.sort((a, b) => {
    if (b.absDelta !== a.absDelta) return b.absDelta - a.absDelta;
    // A missing value sorts last; it is never treated as a real 0.
    const av = a.value ?? -Infinity;
    const bv = b.value ?? -Infinity;
    if (av === bv) return 0;
    return bv > av ? 1 : -1;
  });
  return out.slice(0, limit);
}

function positiveOrNull(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
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
