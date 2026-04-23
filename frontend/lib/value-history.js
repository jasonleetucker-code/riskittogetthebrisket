"use client";

/**
 * value-history — client-side reader for /api/data/rank-history plus
 * derived metrics (window trend, volatility) and SVG sparkline paths.
 *
 * One fetch serves the whole landing page.  The module keeps a
 * single-entry cache keyed by ``days`` so the ticker, movers table,
 * and team chart all share the same response.  Callers pass an
 * AbortSignal so unmount mid-flight doesn't leak a promise.
 *
 * The backend returns ``{ days, history: { <canonicalName>: [{date, rank}, ...] } }``.
 * We keep the shape intact but add fast lookup helpers.
 */

// Single-flight cache: { [daysKey]: { promise, result, expires } }
const CACHE = new Map();
const CACHE_TTL_MS = 60_000;

function now() { return Date.now(); }

export function invalidateHistoryCache() {
  CACHE.clear();
}

/**
 * Fetch rank history for all players over the last N days.
 * Returns { days, history: { name: [{date, rank}, ...] }, fetchedAt }.
 * Shared across callers within a 60s window.
 */
export async function fetchRankHistory({ days = 30, signal } = {}) {
  const key = String(Math.max(1, Math.min(180, Math.floor(days))));
  const cached = CACHE.get(key);
  if (cached && cached.result && cached.expires > now()) {
    return cached.result;
  }
  if (cached && cached.promise) {
    return cached.promise;
  }

  const url = `/api/data/rank-history?days=${key}`;
  const entry = { promise: null, result: null, expires: 0 };
  entry.promise = fetch(url, { credentials: "same-origin", signal })
    .then(async (res) => {
      if (!res.ok) throw new Error(`rank-history ${res.status}`);
      const data = await res.json();
      const result = {
        days: Number(data?.days) || Number(key),
        history: (data && typeof data.history === "object" && data.history) || {},
        fetchedAt: now(),
      };
      entry.result = result;
      entry.expires = now() + CACHE_TTL_MS;
      entry.promise = null;
      return result;
    })
    .catch((err) => {
      CACHE.delete(key);
      throw err;
    });
  CACHE.set(key, entry);
  return entry.promise;
}

/**
 * Normalize a history list to numeric {date, rank} points, sorted
 * ascending by date.  Missing ranks are dropped (not interpolated).
 */
export function normalizePoints(rawPoints) {
  if (!Array.isArray(rawPoints)) return [];
  const points = [];
  for (const p of rawPoints) {
    const rank = Number(p?.rank);
    if (!Number.isFinite(rank) || rank <= 0) continue;
    const t = Date.parse(p?.date);
    if (!Number.isFinite(t)) continue;
    points.push({ date: p.date, t, rank });
  }
  points.sort((a, b) => a.t - b.t);
  return points;
}

/**
 * Rank delta over a window (in days), measured as
 * ``rank_N_days_ago - rank_now`` so a POSITIVE number means the
 * player rose on the consensus board (rank got smaller / better).
 * Returns null if the window has no coverage.
 */
export function computeWindowTrend(points, windowDays) {
  if (!points || points.length === 0) return null;
  const latest = points[points.length - 1];
  const cutoff = latest.t - windowDays * 86400_000;
  // Find the earliest point within the window (or the oldest overall).
  let baseline = null;
  for (const p of points) {
    if (p.t >= cutoff) { baseline = p; break; }
  }
  if (!baseline) return null;
  if (baseline === latest) return 0;
  return baseline.rank - latest.rank;
}

/**
 * Volatility over a window, using MAD (median absolute deviation)
 * of consecutive rank deltas — robust to a single outlier day.
 * Returns { mad, label } where label ∈ {"low","med","high"}.
 * Null coverage returns null.
 */
export function computeVolatility(points, windowDays = 30) {
  if (!points || points.length < 3) return null;
  const latest = points[points.length - 1];
  const cutoff = latest.t - windowDays * 86400_000;
  const window = points.filter((p) => p.t >= cutoff);
  if (window.length < 3) return null;

  const deltas = [];
  for (let i = 1; i < window.length; i++) {
    deltas.push(Math.abs(window[i].rank - window[i - 1].rank));
  }
  const med = median(deltas);
  const devs = deltas.map((d) => Math.abs(d - med));
  const mad = median(devs);

  let label;
  if (mad <= 1) label = "low";
  else if (mad <= 4) label = "med";
  else label = "high";

  return { mad, label };
}

function median(arr) {
  const xs = [...arr].sort((a, b) => a - b);
  if (xs.length === 0) return 0;
  const mid = Math.floor(xs.length / 2);
  return xs.length % 2 === 0 ? (xs[mid - 1] + xs[mid]) / 2 : xs[mid];
}

/**
 * Build an SVG path ``d`` string for a rank-series sparkline.
 * Lower rank = better, so we invert Y so "up" visually means rising.
 * Returns null when there aren't enough points to plot.
 */
export function buildSparklinePath(points, { width = 64, height = 20, padding = 1 } = {}) {
  if (!Array.isArray(points) || points.length < 2) return null;
  const usableW = width - padding * 2;
  const usableH = height - padding * 2;

  // X axis: time. Y axis: rank (inverted).
  const tMin = points[0].t;
  const tMax = points[points.length - 1].t;
  const tSpan = tMax - tMin || 1;

  let rMin = Infinity;
  let rMax = -Infinity;
  for (const p of points) {
    if (p.rank < rMin) rMin = p.rank;
    if (p.rank > rMax) rMax = p.rank;
  }
  const rSpan = rMax - rMin || 1;

  const parts = [];
  for (let i = 0; i < points.length; i++) {
    const p = points[i];
    const x = padding + ((p.t - tMin) / tSpan) * usableW;
    // Invert: best rank (lowest number) → highest pixel (smallest y)
    const y = padding + ((p.rank - rMin) / rSpan) * usableH;
    parts.push(`${i === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return parts.join(" ");
}

/**
 * Compute per-roster aggregate value series for a team-level chart.
 * Inputs: list of roster player names, history map, and a value-from-
 * rank function (the caller supplies this to keep the Hill curve
 * abstraction in the contract rather than duplicated here).
 *
 * Returns an array of {date, t, value} with one entry per date for
 * which EVERY roster player had coverage (so the aggregate is an
 * apples-to-apples sum, not a drifting denominator).
 */
export function computeTeamValueSeries({ rosterNames, history, valueFromRank }) {
  if (!Array.isArray(rosterNames) || rosterNames.length === 0) return [];
  if (!history || typeof history !== "object") return [];
  if (typeof valueFromRank !== "function") return [];

  // Build per-player sorted point lists, keyed by lowercased name.
  const byName = new Map();
  for (const name of rosterNames) {
    const key = String(name).toLowerCase();
    if (byName.has(key)) continue;
    const raw = history[name] || history[key] || findCaseInsensitive(history, name);
    byName.set(key, normalizePoints(raw));
  }

  // Find the intersection of dates across all players with coverage.
  const dateSets = [];
  for (const pts of byName.values()) {
    if (!pts.length) continue;
    dateSets.push(new Set(pts.map((p) => p.date)));
  }
  if (dateSets.length === 0) return [];

  const commonDates = [...dateSets.reduce((acc, s) => {
    const next = new Set();
    for (const d of acc) if (s.has(d)) next.add(d);
    return next;
  }, dateSets[0])];

  if (commonDates.length === 0) return [];

  // Sum values per common date.
  const series = commonDates
    .map((date) => {
      const t = Date.parse(date);
      let total = 0;
      let coverage = 0;
      for (const pts of byName.values()) {
        const hit = pts.find((p) => p.date === date);
        if (!hit) continue;
        total += valueFromRank(hit.rank);
        coverage += 1;
      }
      return { date, t, value: Math.round(total), coverage };
    })
    .sort((a, b) => a.t - b.t);

  return series;
}

function findCaseInsensitive(obj, name) {
  const needle = String(name).toLowerCase();
  for (const key of Object.keys(obj)) {
    if (key.toLowerCase() === needle) return obj[key];
  }
  return null;
}

/**
 * Cheap Hill-curve approximation matching the canonical backend
 * formula in src/canonical/player_valuation.py.  Used for the
 * team-value series so the frontend can sum values from a rank
 * series without a second API call per history point.
 *
 * Backend constants (k=45, exponent=1.10, floor=1, ceiling=9999)
 * are duplicated here.  If they drift backend-side, the team chart
 * goes out of calibration until this is retuned — flagged for the
 * follow-up step that pulls these constants from the contract's
 * ``methodology`` or ``hillCurves`` field.
 */
export function valueFromRank(rank) {
  const r = Number(rank);
  if (!Number.isFinite(r) || r <= 0) return 0;
  const K = 45;
  const EXP = 1.1;
  const CEIL = 9999;
  return Math.round(1 + CEIL / (1 + Math.pow((r - 1) / K, EXP)));
}
