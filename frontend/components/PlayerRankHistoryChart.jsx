"use client";

import { useEffect, useMemo, useRef, useState } from "react";

/**
 * PlayerRankHistoryChart — 180-day rank-history line chart.
 *
 * Reads ``row.rankHistory`` when the contract stamped it (the
 * default) and falls back to ``/api/data/rank-history?days=180`` with
 * a case-insensitive name match when it didn't (e.g. runtime-view
 * payloads that strip ``playersArray``).
 *
 * Y-axis is rank (inverted — lower rank = up = visually better).
 * X-axis is date.  We render three windows worth of reference tags
 * (30d / 90d / 180d lines) so a viewer can eyeball "how much has he
 * moved in the last month vs the last six months".
 *
 * No external chart library — SVG path primitives only.  Under 150
 * lines, renders sub-millisecond for a 180-point series.
 */

const CACHE = new Map(); // { [nameLower]: { result, expires } }
const CACHE_TTL_MS = 120_000;

async function fetchAllHistory(signal) {
  const now = Date.now();
  const cached = CACHE.get("__all__");
  if (cached && cached.expires > now) return cached.result;
  const res = await fetch("/api/data/rank-history?days=180", {
    credentials: "same-origin",
    signal,
  });
  if (!res.ok) throw new Error(`rank-history ${res.status}`);
  const body = await res.json();
  const history = body?.history && typeof body.history === "object" ? body.history : {};
  // The backend stores entries with composite keys like ``Ja'Marr
  // Chase::offense``.  Flatten to lower-cased display names so the
  // chart can look up by row.name alone.
  const flat = {};
  for (const key of Object.keys(history)) {
    const series = history[key];
    if (!Array.isArray(series)) continue;
    const [namePart] = String(key).split("::");
    const norm = String(namePart || key).toLowerCase().trim();
    if (!norm) continue;
    // If two asset classes share a name, keep whichever has more
    // points — the common case is picks vs offense colliding on
    // generic names; rank-relevant series will have more coverage.
    const prev = flat[norm];
    if (!prev || series.length > prev.length) {
      flat[norm] = series;
    }
  }
  const result = flat;
  CACHE.set("__all__", { result, expires: Date.now() + CACHE_TTL_MS });
  return result;
}

function normalizePoints(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const p of raw) {
    if (!p || typeof p !== "object") continue;
    const rank = Number(p.rank);
    if (!Number.isFinite(rank) || rank <= 0) continue;
    const t = Date.parse(p.date);
    if (!Number.isFinite(t)) continue;
    out.push({ date: p.date, t, rank });
  }
  out.sort((a, b) => a.t - b.t);
  return out;
}

export default function PlayerRankHistoryChart({
  row,
  width = 520,
  height = 140,
}) {
  const stamped = Array.isArray(row?.rankHistory) ? row.rankHistory : null;
  const [remote, setRemote] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    // Only fall back to the network when the row didn't carry a
    // stamped series.  This keeps the popup fast in the common case
    // (full contract view) and correct in the fallback case (runtime
    // view / the occasional unstamped row).
    if (stamped && stamped.length > 0) return undefined;
    if (!row?.name) return undefined;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetchAllHistory(controller.signal)
      .then((all) => {
        if (!mounted.current) return;
        const key = String(row.name).toLowerCase().trim();
        setRemote(all[key] || []);
        setLoading(false);
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!mounted.current) return;
        setError(err?.message || "rank-history fetch failed");
        setLoading(false);
      });
    return () => controller.abort();
  }, [stamped, row?.name]);

  const points = useMemo(() => normalizePoints(stamped || remote), [stamped, remote]);

  const geometry = useMemo(() => {
    if (points.length < 2) return null;
    const padX = 8;
    const padY = 10;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;

    const tFirst = points[0].t;
    const tLast = points[points.length - 1].t;
    const tSpan = tLast - tFirst || 1;

    let rMin = Infinity;
    let rMax = -Infinity;
    for (const p of points) {
      if (p.rank < rMin) rMin = p.rank;
      if (p.rank > rMax) rMax = p.rank;
    }
    // Give the plot 1 rank of headroom either side so a flat series
    // doesn't collapse to a single horizontal line at the edge.
    const rPad = Math.max(1, Math.round((rMax - rMin) * 0.1));
    rMin = Math.max(1, rMin - rPad);
    rMax += rPad;
    const rSpan = rMax - rMin || 1;

    const toX = (t) => padX + ((t - tFirst) / tSpan) * usableW;
    // Invert Y: lower rank (better) renders at TOP of plot.
    const toY = (r) => padY + ((r - rMin) / rSpan) * usableH;

    const parts = points.map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.t).toFixed(1)},${toY(p.rank).toFixed(1)}`);
    const pathD = parts.join(" ");
    const areaD = `${pathD} L${toX(tLast).toFixed(1)},${(height - padY).toFixed(1)} L${toX(tFirst).toFixed(1)},${(height - padY).toFixed(1)} Z`;

    // Axis reference: the baseline (oldest) vs latest rank and the
    // 30d / 90d midpoints.  We return the concrete (date, rank) pairs
    // so the caller can show small tick labels next to them.
    const latest = points[points.length - 1];
    const pickBack = (days) => {
      const cutoff = latest.t - days * 86_400_000;
      let chosen = null;
      for (const p of points) {
        if (p.t >= cutoff) {
          chosen = p;
          break;
        }
      }
      return chosen || points[0];
    };
    const back30 = pickBack(30);
    const back90 = pickBack(90);
    const back180 = points[0];
    const delta30 = back30.rank - latest.rank;
    const delta90 = back90.rank - latest.rank;
    const delta180 = back180.rank - latest.rank;

    return {
      pathD,
      areaD,
      firstRank: points[0].rank,
      lastRank: latest.rank,
      minRank: rMin,
      maxRank: rMax,
      deltas: { d30: delta30, d90: delta90, d180: delta180 },
      firstDate: points[0].date,
      lastDate: latest.date,
    };
  }, [points, width, height]);

  if (!row) return null;

  if (loading && !geometry) {
    return (
      <div className="player-rank-chart player-rank-chart--loading" aria-busy="true">
        Loading rank history…
      </div>
    );
  }
  if (error) {
    return (
      <div className="player-rank-chart player-rank-chart--error" role="status">
        Rank history unavailable.
      </div>
    );
  }
  if (!geometry) {
    return (
      <div className="player-rank-chart player-rank-chart--empty" role="status">
        Not enough rank history yet (need at least two snapshots).
      </div>
    );
  }

  const { pathD, areaD, firstRank, lastRank, deltas, firstDate, lastDate } = geometry;
  const trend180 = deltas.d180; // positive = improved rank
  const trendTone = trend180 > 0 ? "up" : trend180 < 0 ? "down" : "flat";

  return (
    <div className="player-rank-chart" role="group" aria-label="Rank history over the last 180 days">
      <div className="player-rank-chart-head">
        <span className="player-rank-chart-label">Rank history · 180d</span>
        <span className={`player-rank-chart-delta player-rank-chart-delta--${trendTone}`}>
          {trend180 === 0 ? "No change" : trend180 > 0 ? `▲ ${trend180} ranks better` : `▼ ${Math.abs(trend180)} ranks worse`}
        </span>
      </div>
      <svg
        className="player-rank-chart-svg"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        aria-hidden="true"
        focusable="false"
        preserveAspectRatio="none"
      >
        <path d={areaD} fill={trend180 >= 0 ? "rgba(52, 211, 153, 0.15)" : "rgba(248, 113, 113, 0.15)"} />
        <path
          d={pathD}
          fill="none"
          stroke={trend180 >= 0 ? "var(--green)" : "var(--red)"}
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <div className="player-rank-chart-legend">
        <span>
          <strong>Then</strong> #{firstRank} ({firstDate})
        </span>
        <span>
          <strong>Now</strong> #{lastRank} ({lastDate})
        </span>
        <span>
          30d {fmtSigned(deltas.d30)} · 90d {fmtSigned(deltas.d90)} · 180d {fmtSigned(deltas.d180)}
        </span>
      </div>
    </div>
  );
}

function fmtSigned(v) {
  if (!Number.isFinite(v) || v === 0) return "·";
  return v > 0 ? `+${v}` : `${v}`;
}
