"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { RANKING_SOURCES } from "@/lib/dynasty-data";

/**
 * PlayerRankHistoryChart — 180-day per-source + blended value chart.
 *
 * Renders one thin line per ranking source (the value each source
 * cast into the blend on each scrape date) plus one thicker, bolder
 * line for OUR blended value.  A shared Y axis (1–9999 value scale)
 * lets the viewer see at a glance which sources disagree, which
 * have drifted, and where the blended line lands relative to the
 * extremes.
 *
 * Data source: ``GET /api/data/player-source-history?name=...`` which
 * reads ``data/source_value_history.jsonl`` on the backend.  A
 * backfill mined the existing ``data/dynasty_data_*.json`` daily
 * exports so the chart has ~28 days of per-source history on day
 * one; new snapshots are appended on every scrape.
 *
 * The blended line may be marked ``derived`` for historical dates
 * that pre-date the contract-builder pipeline — in that case we
 * show the median-of-sources approximation and note it in the
 * legend.
 *
 * No external chart library — pure SVG.  ~200 lines, renders <1ms
 * for a 28-point × 10-source series.
 */

const CACHE = new Map(); // { [nameLower]: { result, expires } }
const CACHE_TTL_MS = 120_000;

async function fetchPlayerHistory(name, signal) {
  const key = String(name).toLowerCase().trim();
  if (!key) return { dates: [], blended: [], sources: {}, sourceRanks: {} };
  const now = Date.now();
  const cached = CACHE.get(key);
  if (cached && cached.expires > now) return cached.result;
  const url = `/api/data/player-source-history?name=${encodeURIComponent(name)}&days=180`;
  const res = await fetch(url, { credentials: "same-origin", signal });
  if (!res.ok) throw new Error(`player-source-history ${res.status}`);
  const body = await res.json();
  const result = {
    dates: Array.isArray(body?.dates) ? body.dates : [],
    blended: Array.isArray(body?.blended) ? body.blended : [],
    sources: body?.sources && typeof body.sources === "object" ? body.sources : {},
    sourceRanks:
      body?.sourceRanks && typeof body.sourceRanks === "object"
        ? body.sourceRanks
        : {},
  };
  CACHE.set(key, { result, expires: Date.now() + CACHE_TTL_MS });
  return result;
}

function parseMs(date) {
  const t = Date.parse(date);
  return Number.isFinite(t) ? t : null;
}

// Palette for source lines.  Non-saturated so the bold blended line
// remains the visual focal point.  Colors are repeated in a stable
// order so the same source gets the same color across re-renders.
const SOURCE_PALETTE = [
  "#60a5fa", // blue
  "#a78bfa", // violet
  "#f472b6", // pink
  "#fbbf24", // amber
  "#34d399", // emerald (dupe of blended; intentional — not used first)
  "#fb923c", // orange
  "#22d3ee", // cyan
  "#a3e635", // lime
  "#f87171", // red
  "#818cf8", // indigo
  "#fde047", // yellow
  "#4ade80", // green
];

function colorForSource(key, index) {
  return SOURCE_PALETTE[index % SOURCE_PALETTE.length];
}

// Source label lookup: prefer the display label from the registry,
// fall back to the raw key.  Keeps the legend readable.
const SOURCE_LABELS = (() => {
  const map = {};
  for (const s of RANKING_SOURCES) {
    map[s.key] = s.columnLabel || s.displayName || s.key;
  }
  // Legacy keys from pre-contract-builder exports (camelCase).
  map.fantasyCalc = "FantasyCalc";
  map.dlfSf = "DLF SF";
  map.dynastyDaddy = "Dynasty Daddy";
  map.draftSharks = "Draft Sharks";
  map.draftSharksIdp = "Draft Sharks IDP";
  map.fantasyPros = "FantasyPros";
  map.idpTradeCalc = "IDPTC";
  map.yahoo = "Yahoo";
  map.ktc = "KTC";
  return map;
})();

function labelForSource(key) {
  return SOURCE_LABELS[key] || key;
}

function buildPath({ points, toX, toY }) {
  const parts = [];
  let open = false;
  for (const p of points) {
    if (!Number.isFinite(p.value) || p.value <= 0) {
      open = false;
      continue;
    }
    const x = toX(p.t).toFixed(1);
    const y = toY(p.value).toFixed(1);
    parts.push(`${open ? "L" : "M"}${x},${y}`);
    open = true;
  }
  return parts.join(" ");
}

export default function PlayerRankHistoryChart({
  row,
  width = 520,
  height = 180,
}) {
  const [state, setState] = useState({
    loading: true,
    error: null,
    dates: [],
    blended: [],
    sources: {},
    sourceRanks: {},
  });
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!row?.name) return undefined;
    const controller = new AbortController();
    setState((prev) => ({ ...prev, loading: true, error: null }));
    fetchPlayerHistory(row.name, controller.signal)
      .then((res) => {
        if (!mounted.current) return;
        setState({ loading: false, error: null, ...res });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        if (!mounted.current) return;
        setState({
          loading: false,
          error: err?.message || "fetch failed",
          dates: [],
          blended: [],
          sources: {},
          sourceRanks: {},
        });
      });
    return () => controller.abort();
  }, [row?.name]);

  const geometry = useMemo(() => {
    const blended = (state.blended || [])
      .map((p) => ({ t: parseMs(p.date), value: Number(p.value), derived: !!p.derived }))
      .filter((p) => p.t != null);
    const sources = {};
    for (const [key, series] of Object.entries(state.sources || {})) {
      if (!Array.isArray(series)) continue;
      sources[key] = series
        .map((p) => ({ t: parseMs(p.date), value: Number(p.value) }))
        .filter((p) => p.t != null);
    }
    // Collect all points for Y-axis domain.
    const allValues = [];
    for (const p of blended) if (Number.isFinite(p.value) && p.value > 0) allValues.push(p.value);
    for (const key of Object.keys(sources)) {
      for (const p of sources[key]) if (Number.isFinite(p.value) && p.value > 0) allValues.push(p.value);
    }
    if (allValues.length < 2) return null;

    const allTimes = [];
    for (const p of blended) allTimes.push(p.t);
    for (const key of Object.keys(sources)) for (const p of sources[key]) allTimes.push(p.t);
    const tMin = Math.min(...allTimes);
    const tMax = Math.max(...allTimes);
    const tSpan = tMax - tMin || 1;

    let vMin = Math.min(...allValues);
    let vMax = Math.max(...allValues);
    // Pad the Y domain 5% either side so lines at the extremes
    // don't sit right on the frame.
    const vPad = Math.max(50, Math.round((vMax - vMin) * 0.05));
    vMin = Math.max(0, vMin - vPad);
    vMax += vPad;
    const vSpan = vMax - vMin || 1;

    const padX = 8;
    const padY = 12;
    const usableW = width - padX * 2;
    const usableH = height - padY * 2;
    const toX = (t) => padX + ((t - tMin) / tSpan) * usableW;
    const toY = (v) => padY + (1 - (v - vMin) / vSpan) * usableH;

    const sourcePaths = [];
    const sourceKeys = Object.keys(sources).sort();
    sourceKeys.forEach((key, index) => {
      sourcePaths.push({
        key,
        label: labelForSource(key),
        color: colorForSource(key, index),
        path: buildPath({ points: sources[key], toX, toY }),
        first: sources[key][0]?.value ?? null,
        last: sources[key][sources[key].length - 1]?.value ?? null,
      });
    });

    const blendedPath = buildPath({ points: blended, toX, toY });
    const blendedFirst = blended.find((p) => Number.isFinite(p.value) && p.value > 0);
    const blendedLast = [...blended].reverse().find((p) => Number.isFinite(p.value) && p.value > 0);
    const blendedDelta =
      blendedFirst && blendedLast ? blendedLast.value - blendedFirst.value : 0;
    const anyDerived = blended.some((p) => p.derived);

    return {
      blendedPath,
      blendedDelta,
      blendedFirst,
      blendedLast,
      anyDerived,
      sourcePaths,
      firstDate: state.dates[0] || null,
      lastDate: state.dates[state.dates.length - 1] || null,
    };
  }, [state, width, height]);

  /* ── Rank-history geometry (companion to the value chart) ────────
     Renders ``Our rank`` as a bold line + one thin line per source
     on an inverted RANK axis (rank 1 at top, rank N at bottom).
     Mirror of the value chart's ``Our blend`` + per-source layering.

     Renders only when at least one of the two SERIES has 2+ data
     points — otherwise the SVG would draw single-point ``M`` moves
     with no ``L`` segments and look empty.  Per-source ranks started
     persisting 2026-04-29; until the rolling window has 2+ snapshots
     for SOMETHING, we surface the empty-state copy below the title
     instead of an empty axis. */
  const rankGeometry = useMemo(() => {
    const sourceRanks = {};
    for (const [key, series] of Object.entries(state.sourceRanks || {})) {
      if (!Array.isArray(series)) continue;
      sourceRanks[key] = series
        .map((p) => ({ t: parseMs(p.date), rank: Number(p.rank) }))
        .filter((p) => p.t != null && Number.isFinite(p.rank) && p.rank > 0);
    }
    // Our (blended) rank — the bold main line, mirroring "Our blend"
    // on the value chart.  ``state.blended[].rank`` is the
    // backend-stamped consensus rank for each historical snapshot;
    // present alongside ``value`` since the schema's earliest write.
    const blendedRanks = (state.blended || [])
      .map((p) => ({ t: parseMs(p.date), rank: Number(p.rank) }))
      .filter((p) => p.t != null && Number.isFinite(p.rank) && p.rank > 0);

    const allTimes = [];
    const allRanks = [];
    for (const key of Object.keys(sourceRanks)) {
      for (const p of sourceRanks[key]) {
        allTimes.push(p.t);
        allRanks.push(p.rank);
      }
    }
    for (const p of blendedRanks) {
      allTimes.push(p.t);
      allRanks.push(p.rank);
    }
    // Empty-state guard: need at least one series with 2+ points or
    // rendering produces invisible single-pixel "M" moves.
    const blendedHasLine = blendedRanks.length >= 2;
    const anySourceHasLine = Object.values(sourceRanks).some(
      (series) => series.length >= 2,
    );
    if (!blendedHasLine && !anySourceHasLine) return null;

    const tMin = Math.min(...allTimes);
    const tMax = Math.max(...allTimes);
    const tSpan = tMax - tMin || 1;
    let rMin = Math.min(...allRanks);
    let rMax = Math.max(...allRanks);
    // Pad rank range a bit so lines don't sit on the frame.  Keep
    // rMin >= 1 so "rank 1" is interpretable.
    const rPad = Math.max(2, Math.round((rMax - rMin) * 0.05));
    rMin = Math.max(1, rMin - rPad);
    rMax += rPad;
    const rSpan = rMax - rMin || 1;
    const padX = 8;
    const padY = 12;
    const usableW = width - padX * 2;
    // Rank chart uses ~75% of the value chart's height — secondary
    // information, doesn't deserve full real estate.
    const chartH = Math.max(80, Math.round(height * 0.75));
    const usableH = chartH - padY * 2;
    const toX = (t) => padX + ((t - tMin) / tSpan) * usableW;
    // Inverted Y: rank 1 at TOP, rank N at BOTTOM.  Mirror image of
    // the value chart where the highest value sits at the top.
    const toY = (r) => padY + ((r - rMin) / rSpan) * usableH;

    const buildRankPath = (points) => {
      const parts = [];
      let open = false;
      for (const p of points) {
        if (!Number.isFinite(p.rank) || p.rank <= 0) {
          open = false;
          continue;
        }
        const x = toX(p.t).toFixed(1);
        const y = toY(p.rank).toFixed(1);
        parts.push(`${open ? "L" : "M"}${x},${y}`);
        open = true;
      }
      return parts.join(" ");
    };

    const sourcePaths = [];
    const sourceKeys = Object.keys(sourceRanks).sort();
    sourceKeys.forEach((key, index) => {
      const series = sourceRanks[key];
      // Skip sources with fewer than 2 points — would render as an
      // invisible single move on the SVG and clutter the legend
      // with "→" no-change rows.
      if (series.length < 2) return;
      sourcePaths.push({
        key,
        label: labelForSource(key),
        color: colorForSource(key, index),
        path: buildRankPath(series),
        first: series[0]?.rank ?? null,
        last: series[series.length - 1]?.rank ?? null,
      });
    });

    const blendedPath = blendedHasLine ? buildRankPath(blendedRanks) : null;
    const blendedFirst = blendedHasLine ? blendedRanks[0].rank : null;
    const blendedLast = blendedHasLine
      ? blendedRanks[blendedRanks.length - 1].rank
      : null;
    // Direction matters: rank GETTING BETTER means the number got
    // smaller (#15 → #8).  Mirror the value chart's green-up /
    // red-down convention by inverting the sign.
    const blendedDelta = blendedHasLine
      ? blendedFirst - blendedLast  // positive = improved (rank ↓)
      : 0;

    return {
      sourcePaths,
      blendedPath,
      blendedFirst,
      blendedLast,
      blendedDelta,
      chartH,
      rMin,
      rMax,
    };
  }, [state, width, height]);

  if (!row) return null;

  if (state.loading && !geometry) {
    return <div className="player-rank-chart player-rank-chart--loading">Loading value history…</div>;
  }
  if (state.error) {
    return <div className="player-rank-chart player-rank-chart--error">Value history unavailable.</div>;
  }
  if (!geometry) {
    return (
      <div className="player-rank-chart player-rank-chart--empty">
        Not enough value history yet (need at least two snapshots).
      </div>
    );
  }

  const { blendedPath, blendedDelta, blendedFirst, blendedLast, anyDerived, sourcePaths, firstDate, lastDate } = geometry;
  const trendTone = blendedDelta > 0 ? "up" : blendedDelta < 0 ? "down" : "flat";

  return (
    <div className="player-rank-chart" role="group" aria-label="Per-source value history over the last 180 days">
      <div className="player-rank-chart-head">
        <span className="player-rank-chart-label">
          Value history · 180d
          {anyDerived && <span className="player-rank-chart-asterisk" title="Historical blended line is the median of per-source values — true blend started persisting on 2026-04-23"> *</span>}
        </span>
        <span className={`player-rank-chart-delta player-rank-chart-delta--${trendTone}`}>
          {blendedDelta === 0
            ? "No change"
            : blendedDelta > 0
            ? `▲ ${blendedDelta.toLocaleString()} value`
            : `▼ ${Math.abs(blendedDelta).toLocaleString()} value`}
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
        {/* Thin per-source lines first so the blended line overlays */}
        {sourcePaths.map((s) => (
          <path
            key={s.key}
            d={s.path}
            fill="none"
            stroke={s.color}
            strokeWidth={1}
            strokeOpacity={0.55}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        ))}
        {/* Bold blended line on top */}
        {blendedPath && (
          <path
            d={blendedPath}
            fill="none"
            stroke={blendedDelta >= 0 ? "var(--green)" : "var(--red)"}
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
      </svg>
      <div className="player-rank-chart-legend">
        <span className="player-rank-chart-legend-blended">
          <span
            className="player-rank-chart-swatch"
            style={{
              background: blendedDelta >= 0 ? "var(--green)" : "var(--red)",
              height: 3,
            }}
            aria-hidden="true"
          />
          <strong>Our blend</strong>
          {blendedFirst && blendedLast && (
            <span className="player-rank-chart-legend-range">
              {blendedFirst.value.toLocaleString()} → {blendedLast.value.toLocaleString()}
            </span>
          )}
        </span>
        {sourcePaths.map((s) => (
          <span key={s.key} className="player-rank-chart-legend-source">
            <span
              className="player-rank-chart-swatch"
              style={{ background: s.color, opacity: 0.55 }}
              aria-hidden="true"
            />
            <span>{s.label}</span>
            {Number.isFinite(s.first) && Number.isFinite(s.last) && (
              <span className="player-rank-chart-legend-range">
                {s.first?.toLocaleString?.() ?? s.first} → {s.last?.toLocaleString?.() ?? s.last}
              </span>
            )}
          </span>
        ))}
      </div>
      {/* ── Rank history (companion panel) ─────────────────────────
          Same X axis (time) as the value chart above, inverted Y
          axis where rank 1 sits at the top.  ``Our rank`` is the
          bold main line (mirrors ``Our blend`` on the value chart);
          per-source ranks are thin layered lines.  Rendered only
          when at least one series has 2+ snapshots; per-source
          ranks started persisting 2026-04-29 so the rolling window
          fills in over time. */}
      {rankGeometry ? (
        <>
          <div
            className="player-rank-chart-head player-rank-chart-head--rank"
            style={{ marginTop: 12 }}
          >
            <span className="player-rank-chart-label">
              Rank history · 180d (per source)
            </span>
            <span
              className={`player-rank-chart-delta player-rank-chart-delta--${
                rankGeometry.blendedDelta > 0
                  ? "up"
                  : rankGeometry.blendedDelta < 0
                  ? "down"
                  : "flat"
              }`}
            >
              {rankGeometry.blendedDelta === 0
                ? "rank 1 = top"
                : rankGeometry.blendedDelta > 0
                ? `▲ ${rankGeometry.blendedDelta} ranks`
                : `▼ ${Math.abs(rankGeometry.blendedDelta)} ranks`}
            </span>
          </div>
          <svg
            className="player-rank-chart-svg player-rank-chart-svg--rank"
            width={width}
            height={rankGeometry.chartH}
            viewBox={`0 0 ${width} ${rankGeometry.chartH}`}
            aria-hidden="true"
            focusable="false"
            preserveAspectRatio="none"
          >
            {/* Thin per-source lines first so the blended line overlays */}
            {rankGeometry.sourcePaths.map((s) => (
              <path
                key={s.key}
                d={s.path}
                fill="none"
                stroke={s.color}
                strokeWidth={1.25}
                strokeOpacity={0.55}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
            {/* Bold "Our rank" line on top */}
            {rankGeometry.blendedPath && (
              <path
                d={rankGeometry.blendedPath}
                fill="none"
                stroke={
                  rankGeometry.blendedDelta >= 0
                    ? "var(--green)"
                    : "var(--red)"
                }
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            )}
          </svg>
          <div className="player-rank-chart-legend">
            {/* Our rank (bold, first row mirrors the value chart) */}
            {rankGeometry.blendedPath && (
              <span className="player-rank-chart-legend-blended">
                <span
                  className="player-rank-chart-swatch"
                  style={{
                    background:
                      rankGeometry.blendedDelta >= 0
                        ? "var(--green)"
                        : "var(--red)",
                    height: 3,
                  }}
                  aria-hidden="true"
                />
                <strong>Our rank</strong>
                <span className="player-rank-chart-legend-range">
                  #{rankGeometry.blendedFirst} → #{rankGeometry.blendedLast}
                </span>
              </span>
            )}
            {rankGeometry.sourcePaths.map((s) => (
              <span
                key={`rank-${s.key}`}
                className="player-rank-chart-legend-source"
              >
                <span
                  className="player-rank-chart-swatch"
                  style={{ background: s.color, opacity: 0.55 }}
                  aria-hidden="true"
                />
                <span>{s.label}</span>
                {Number.isFinite(s.first) && Number.isFinite(s.last) && (
                  <span className="player-rank-chart-legend-range">
                    #{s.first} → #{s.last}
                  </span>
                )}
              </span>
            ))}
          </div>
        </>
      ) : (
        <div
          className="muted"
          style={{ fontSize: "0.7rem", marginTop: 10 }}
        >
          Rank history fills in over time — needs at least two daily
          snapshots before lines render.  Per-source ranks first
          persisted on 2026-04-29; earlier dates carry value data only.
        </div>
      )}
      <div className="player-rank-chart-footer">
        <span>
          <strong>Then</strong> {firstDate}
        </span>
        <span>
          <strong>Now</strong> {lastDate}
        </span>
        {anyDerived && (
          <span className="player-rank-chart-note">
            * Historical blend approximated from per-source median
          </span>
        )}
      </div>
    </div>
  );
}
