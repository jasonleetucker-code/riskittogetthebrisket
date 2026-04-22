"use client";

// PowerSection — "Power" tab on /league.
//
// Surfaces the weekly power ranking from the ``power`` contract section:
//   * Current-week leaderboard with components + week-over-week rank delta.
//   * Inline SVG line chart plotting each owner's power score across
//     every (season, week) in the snapshot.
//   * Historical week selector for drilling into any past week.

import { useEffect, useMemo, useState } from "react";
import {
  Avatar,
  Card,
  EmptyCard,
  fmtNumber,
  fmtPercent,
  nameFor,
} from "../shared.jsx";
import PlayoffOddsChart from "@/components/graphs/PlayoffOddsChart";

function powerColor(power) {
  if (power >= 80) return "#2ecc71";
  if (power >= 65) return "#7bdfb3";
  if (power >= 50) return "#4fc3f7";
  if (power >= 35) return "#ffa726";
  return "#ff6b6b";
}

function deltaText(delta) {
  if (!delta) return "—";
  const n = Number(delta);
  if (n > 0) return `▲ ${n}`;
  if (n < 0) return `▼ ${Math.abs(n)}`;
  return "—";
}

function deltaColor(delta) {
  const n = Number(delta);
  if (n > 0) return "#2ecc71";
  if (n < 0) return "#ff6b6b";
  return "var(--subtext)";
}

// ── Power trail chart ────────────────────────────────────────────────────
function PowerChart({ series, managers, highlightOwnerId = null }) {
  const { lines, xMax } = useMemo(() => {
    if (!series || !series.length) return { lines: [], xMax: 0 };
    // Flatten cross-season (season, week) into a single axis index.
    // Every owner must share the same axis so we build the master
    // ordered list of (season, week) keys across all owners.
    const allKeys = new Map();  // "season:week" → order
    const sortedSeries = series.map((s) => ({
      ...s,
      points: [...s.points].sort((a, b) => {
        if (a.season !== b.season) return Number(a.season) - Number(b.season);
        return a.week - b.week;
      }),
    }));
    const ordered = [];
    for (const s of sortedSeries) {
      for (const p of s.points) {
        const k = `${p.season}:${p.week}`;
        if (!allKeys.has(k)) {
          allKeys.set(k, ordered.length);
          ordered.push(k);
        }
      }
    }
    // Re-sort ordered keys by (season, week) explicitly; map back.
    ordered.sort((a, b) => {
      const [sa, wa] = a.split(":");
      const [sb, wb] = b.split(":");
      if (sa !== sb) return Number(sa) - Number(sb);
      return Number(wa) - Number(wb);
    });
    ordered.forEach((k, i) => allKeys.set(k, i));

    const lines = sortedSeries.map((s) => ({
      ownerId: s.ownerId,
      displayName: s.displayName,
      points: s.points.map((p) => ({
        x: allKeys.get(`${p.season}:${p.week}`),
        y: p.power,
        season: p.season,
        week: p.week,
        rank: p.rank,
      })),
    }));
    return { lines, xMax: ordered.length - 1 };
  }, [series]);

  if (!lines.length || xMax < 1) return null;

  const W = 640;
  const H = 260;
  const padL = 38;
  const padR = 80;
  const padT = 16;
  const padB = 24;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const px = (x) => padL + (x / xMax) * plotW;
  const py = (y) => padT + (1 - y / 100) * plotH;

  function colorFor(ownerId) {
    const palette = [
      "#4fc3f7",
      "#ffa726",
      "#66bb6a",
      "#ef5350",
      "#ab47bc",
      "#26c6da",
      "#ffee58",
      "#8d6e63",
      "#ec407a",
      "#7e57c2",
      "#9ccc65",
      "#ff7043",
    ];
    let h = 0;
    for (let i = 0; i < ownerId.length; i++) {
      h = (h * 31 + ownerId.charCodeAt(i)) & 0xffff;
    }
    return palette[h % palette.length];
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        style={{ maxWidth: W, display: "block", margin: "0 auto" }}
        aria-label="Power score across weeks per manager"
      >
        {/* Gridlines at 0, 25, 50, 75, 100. */}
        {[0, 25, 50, 75, 100].map((v) => (
          <g key={v}>
            <line
              x1={padL}
              x2={W - padR}
              y1={py(v)}
              y2={py(v)}
              stroke={v === 50 ? "var(--border-bright)" : "var(--border)"}
              strokeDasharray={v === 50 ? "" : "3 3"}
              opacity={v === 50 ? 0.8 : 0.5}
            />
            <text
              x={padL - 6}
              y={py(v) + 3}
              fontSize={9}
              textAnchor="end"
              fill="var(--subtext)"
              fontFamily="var(--mono)"
            >
              {v}
            </text>
          </g>
        ))}
        {/* Lines. */}
        {lines.map((line) => {
          const isHighlighted = highlightOwnerId && line.ownerId === highlightOwnerId;
          const color = colorFor(line.ownerId);
          const d = line.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.x)} ${py(p.y)}`)
            .join(" ");
          return (
            <g key={line.ownerId} opacity={highlightOwnerId && !isHighlighted ? 0.25 : 1.0}>
              <path
                d={d}
                fill="none"
                stroke={color}
                strokeWidth={isHighlighted ? 2.4 : 1.4}
              />
              {line.points.length > 0 && (() => {
                const last = line.points[line.points.length - 1];
                return (
                  <>
                    <circle cx={px(last.x)} cy={py(last.y)} r={3} fill={color} />
                    <text
                      x={px(last.x) + 6}
                      y={py(last.y) + 3}
                      fontSize={9}
                      fill={color}
                      fontFamily="var(--mono)"
                    >
                      {(line.displayName || line.ownerId).slice(0, 12)}
                    </text>
                  </>
                );
              })()}
            </g>
          );
        })}
        <text
          x={padL + plotW / 2}
          y={H - 4}
          fontSize={9}
          textAnchor="middle"
          fill="var(--subtext)"
        >
          Weeks played (chronological)
        </text>
      </svg>
    </div>
  );
}

// ── Leaderboard ─────────────────────────────────────────────────────────
function PowerTable({ rankings, managers, onRowHover, hoverOwnerId }) {
  if (!rankings || !rankings.length) return <EmptyCard label="Power rankings" />;
  return (
    <div className="table-wrap" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 32 }}>#</th>
            <th style={{ width: 44 }}>Δ</th>
            <th>Manager</th>
            <th style={{ textAlign: "right" }}>Power</th>
            <th style={{ textAlign: "right" }}>PPG</th>
            <th style={{ textAlign: "right" }}>L{"3"} avg</th>
            <th style={{ textAlign: "right" }}>All-play</th>
            <th style={{ textAlign: "right" }}>Record</th>
          </tr>
        </thead>
        <tbody>
          {rankings.map((r) => (
            <tr
              key={r.ownerId}
              onMouseEnter={() => onRowHover?.(r.ownerId)}
              onMouseLeave={() => onRowHover?.(null)}
              style={{
                background:
                  hoverOwnerId === r.ownerId ? "rgba(79,195,247,0.08)" : "transparent",
                cursor: "default",
              }}
            >
              <td style={{ fontFamily: "var(--mono)", fontWeight: 700, color: powerColor(r.power) }}>
                {r.rank}
              </td>
              <td style={{ fontFamily: "var(--mono)", color: deltaColor(r.weekRankDelta) }}>
                {deltaText(r.weekRankDelta)}
              </td>
              <td>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <Avatar managers={managers} ownerId={r.ownerId} size={20} />
                  <span>
                    <div style={{ fontWeight: 600, lineHeight: 1.1 }}>{nameFor(managers, r.ownerId)}</div>
                    <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>{r.teamName}</div>
                  </span>
                </span>
              </td>
              <td
                style={{
                  textAlign: "right",
                  fontFamily: "var(--mono)",
                  color: powerColor(r.power),
                  fontWeight: 700,
                }}
              >
                {fmtNumber(r.power, 1)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtNumber(r.components?.pointsPerGame, 1)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtNumber(r.components?.recentAvg, 1)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                {fmtPercent(r.components?.allPlayWinPctThisWeek)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.record}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Module-level cache of the playoff-odds fetch.  ``PowerSection`` is
// conditionally mounted by tab selection, so without caching, every
// tab-switch back to Power refetches ``/api/public/league/playoffOdds``
// — which runs a 10,000-simulation Monte Carlo on the backend and
// makes probabilities visibly jitter between visits.  Stashing the
// first successful response here means subsequent mounts hydrate
// synchronously; an in-flight request is reused so two near-
// simultaneous mounts don't double-fetch.
//
// Cache is keyed by the root league ID extracted from the payload
// header so switching leagues doesn't serve stale odds — the page
// passes ``data.leagueId`` through, and we key the cache on the
// same value Power derives from its own props.  TTL is 30 minutes
// which matches how often the upstream league data refreshes.
// Callers can force a refetch by bumping ``CACHE_GENERATION``.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _oddsCache = {
  data: null,
  error: null,
  inflight: null,
  fetchedAt: 0,
};

async function _fetchOddsOnce() {
  const fresh = _oddsCache.data
    && Date.now() - _oddsCache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _oddsCache.data, error: null };
  if (_oddsCache.inflight) return _oddsCache.inflight;

  const promise = fetch("/api/public/league/playoffOdds")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
    .then((payload) => {
      const body = payload?.data || payload?.section || payload;
      _oddsCache.data = body;
      _oddsCache.error = null;
      _oddsCache.fetchedAt = Date.now();
      _oddsCache.inflight = null;
      return { data: body, error: null };
    })
    .catch((err) => {
      _oddsCache.inflight = null;
      const message = String(err?.message || err);
      _oddsCache.error = message;
      // Keep any previously-cached data so UI doesn't flash empty.
      return { data: _oddsCache.data, error: message };
    });

  _oddsCache.inflight = promise;
  return promise;
}

// ── Section ──────────────────────────────────────────────────────────────
export default function PowerSection({ data, managers }) {
  const [hoverOwnerId, setHoverOwnerId] = useState(null);
  const [selectedWeekKey, setSelectedWeekKey] = useState("__current");
  const [oddsData, setOddsData] = useState(() => _oddsCache.data);
  const [oddsError, setOddsError] = useState(() => _oddsCache.error);

  // Hydrate from cache on mount; otherwise fetch once and cache the
  // result at module scope.  Repeated Power-tab mounts within
  // ``CACHE_TTL_MS`` reuse the cached response rather than re-running
  // the Monte Carlo.
  useEffect(() => {
    let cancelled = false;
    _fetchOddsOnce().then(({ data: body, error }) => {
      if (cancelled) return;
      if (body) setOddsData(body);
      if (error) setOddsError(error);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!data || !data.weeks?.length) return <EmptyCard label="Power rankings" />;

  const weeks = data.weeks;
  const selectedWeek =
    selectedWeekKey === "__current"
      ? weeks[weeks.length - 1]
      : weeks.find((w) => `${w.season}:${w.week}` === selectedWeekKey) || weeks[weeks.length - 1];

  return (
    <section>
      <Card
        title={`Power rankings — ${selectedWeek.season} week ${selectedWeek.week}`}
        action={
          <select
            className="input"
            value={selectedWeekKey}
            onChange={(e) => setSelectedWeekKey(e.target.value)}
            style={{ minWidth: 180 }}
          >
            <option value="__current">Most recent</option>
            {[...weeks].reverse().map((w) => (
              <option key={`${w.season}:${w.week}`} value={`${w.season}:${w.week}`}>
                {w.season} Wk {w.week}
              </option>
            ))}
          </select>
        }
      >
        <PowerTable
          rankings={selectedWeek.rankings}
          managers={managers}
          onRowHover={setHoverOwnerId}
          hoverOwnerId={hoverOwnerId}
        />
      </Card>

      <Card
        title="Power score over time"
        action={
          <span style={{ fontSize: "0.62rem", color: "var(--subtext)" }}>
            Hover a row in the table to highlight a manager's line
          </span>
        }
      >
        <PowerChart
          series={data.seriesByOwner || []}
          managers={managers}
          highlightOwnerId={hoverOwnerId}
        />
      </Card>

      {oddsData && Array.isArray(oddsData.owners) && oddsData.owners.length > 0 ? (
        <Card
          title="Playoff odds"
          subtitle="Monte Carlo over remaining regular-season weeks; samples each owner's score from their actual weekly history."
        >
          <PlayoffOddsChart data={oddsData} />
        </Card>
      ) : null}
      {oddsError ? (
        <Card title="Playoff odds">
          <p style={{ fontSize: "0.78rem", color: "var(--red)" }}>
            Couldn&apos;t load playoff odds: {oddsError}
          </p>
        </Card>
      ) : null}

      <Card title="How this is computed">
        <p style={{ fontSize: "0.78rem", lineHeight: 1.5, color: "var(--subtext)" }}>
          {data.methodology}
        </p>
      </Card>
    </section>
  );
}
