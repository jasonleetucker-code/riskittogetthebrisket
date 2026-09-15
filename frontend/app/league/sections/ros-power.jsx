"use client";

// ROS-driven Power Rankings (v2). The ONLY power-ranking engine — V1-52
// retired ``power.py``/``power.jsx`` (the pre-existing v1 engine and its
// renderer) once the census showed every field it displayed is either
// already published here or recoverable from data this engine already
// computes, without a second computation. Lazy-fetched from
// /api/public/league/rosPower because the section reads the ROS
// team-strength snapshot and re-walks the snapshot each call — same
// lazy pattern as playoff odds. Missing weighted inputs stay missing and
// the canonical forward/results masses renormalize without inventing zeroes.

import { useEffect, useMemo, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";
import { Card } from "../shared-server.jsx";
import { Avatar, nameFor } from "../shared.jsx";
import PlayoffOddsChart from "@/components/graphs/PlayoffOddsChart";

// Module-level cache so tab-switching doesn't re-fetch on every mount.
// Same pattern + 30-min TTL that the retired power.jsx used for playoff
// odds.
//
// One league-facing canonical answer plus a results-only diagnostic.
// The backend still accepts "forward_looking" as a compatibility alias,
// but the UI no longer presents it as a competing Power Ranking.
const CACHE_TTL_MS = 30 * 60 * 1000;
export const LENS_CANONICAL = "canonical";
export const LENS_FORWARD_LOOKING = "forward_looking";
export const LENS_RESULTS_ONLY = "results_only";
const _caches = {
  [LENS_CANONICAL]: { data: null, error: null, inflight: null, fetchedAt: 0 },
  [LENS_RESULTS_ONLY]: { data: null, error: null, inflight: null, fetchedAt: 0 },
};

async function _fetchRosPower(lens) {
  const cache = _caches[lens] || _caches[LENS_CANONICAL];
  const fresh = cache.data && Date.now() - cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: cache.data, error: null };
  if (cache.inflight) return cache.inflight;

  const qs = lens && lens !== LENS_CANONICAL ? `?lens=${encodeURIComponent(lens)}` : "";
  const promise = fetch(`/api/public/league/rosPower${qs}`)
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
    .then((payload) => {
      const body = payload?.data || payload?.section || payload;
      cache.data = body;
      cache.error = null;
      cache.fetchedAt = Date.now();
      cache.inflight = null;
      return { data: body, error: null };
    })
    .catch((err) => {
      cache.inflight = null;
      const message = String(err?.message || err);
      cache.error = message;
      return { data: cache.data, error: message };
    });

  cache.inflight = promise;
  return promise;
}

// Module-level cache of the playoff-odds fetch, ported unchanged from the
// retired power.jsx. ``RosPowerSection`` is conditionally mounted by tab
// selection, so without caching, every tab-switch back to Power refetches
// /api/public/league/playoffOdds — which runs a 10,000-simulation Monte
// Carlo on the backend and makes probabilities visibly jitter between
// visits. Same v1 data source as before: retiring the power-RANKING
// engine does not touch playoff-odds methodology.
const ODDS_CACHE_TTL_MS = 30 * 60 * 1000;
const _oddsCache = {
  data: null,
  error: null,
  inflight: null,
  fetchedAt: 0,
};

async function _fetchOddsOnce() {
  const fresh = _oddsCache.data && Date.now() - _oddsCache.fetchedAt < ODDS_CACHE_TTL_MS;
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
      return { data: _oddsCache.data, error: message };
    });

  _oddsCache.inflight = promise;
  return promise;
}

// Rank delta between two already-computed rank values. Historical selector
// rows use the diagnostic results-only series; the live canonical table gets
// its movement directly from immutable official snapshots. ``null`` for
// either input propagates to ``null`` — missing history is not "flat".
function rankDelta(priorRank, currentRank) {
  if (priorRank == null || currentRank == null) return null;
  return priorRank - currentRank; // positive = moved up (lower rank number)
}

// Delta for one specific historical week in ``trend.weeks``, against the
// nearest PRECEDING week IN THE SAME SEASON that lists the same owner (an
// owner can be absent from a week — e.g. joined the league later). Same
// underlying diagnostic quantity generalized to any historical week the
// reader picks. Nothing new is computed; every rank is already on trend.weeks.
//
// The season guard is load-bearing. ``trend.weeks`` chains every tracked
// season onto one sequential list (power_v2.py's ``week_states`` loops over
// ``seasons_sorted``), so without it the first week of a season compares
// against the LAST week of the previous season — a different league state,
// a different roster set, and in the results-only lens a standings-derived
// ranking. That is what produced movement nobody could reconcile against the
// published baseline. A season's first week has no in-season predecessor, so
// the honest answer is ``null``, not a number borrowed from last year.
function weekDelta(weeks, weekIndex, ownerId) {
  if (weekIndex <= 0) return null;
  const currentWeek = weeks[weekIndex];
  const currentRow = (currentWeek?.rankings || []).find((r) => r.ownerId === ownerId);
  if (!currentRow) return null;
  for (let i = weekIndex - 1; i >= 0; i--) {
    if (String(weeks[i]?.season) !== String(currentWeek?.season)) return null;
    const priorRow = (weeks[i]?.rankings || []).find((r) => r.ownerId === ownerId);
    if (priorRow) return rankDelta(priorRow.rank, currentRow.rank);
  }
  return null;
}

function fmtScore(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(1);
}

function fmtPct(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return `${Math.round(Number(v) * 100)}%`;
}

function fmtRaw(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(1);
}

function ComponentBar({ label, value, weight }) {
  if (!weight) return null;
  const pct = Math.max(0, Math.min(1, Number(value || 0)));
  return (
    <div style={{ marginBottom: 4, fontSize: "0.7rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span style={{ color: "var(--subtext)" }}>
          {label} ({Math.round(weight * 100)}%)
        </span>
        <span style={{ fontFamily: "var(--mono)" }}>{fmtPct(pct)}</span>
      </div>
      <div
        style={{
          height: 4,
          background: "rgba(255,255,255,0.1)",
          borderRadius: 2,
          marginTop: 2,
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct * 100}%`,
            background: "var(--cyan)",
            borderRadius: 2,
          }}
        />
      </div>
    </div>
  );
}

// Weighted components only -- ``pointsPerGame``/``recentAvg`` are
// display-only raw magnitudes (never in ``weightsApplied``) and get
// their own dedicated table columns instead, the same treatment
// power.py's renderer gave them.
const COMPONENT_LABELS = {
  team_ros_strength: "Forward-looking ROS strength",
  all_play: "Season all-play",
  recent: "Recent form (last 4)",
  team_vorp: "Realized lineup VORP/PAR",
  wl_record: "Official record",
};

// Compact labels for the per-row composition line. Deliberately shorter than
// COMPONENT_LABELS: this renders inline under every owner, not in an expanded
// panel, so it has to survive a phone width.
const COMPONENT_RANK_LABELS = {
  team_ros_strength: "ROS",
  all_play: "All-play",
  recent: "Last 4",
  team_vorp: "VORP",
  wl_record: "Record",
};

// Sub-ranks come from the backend (`power_v2._attach_component_ranks`) and are
// rendered verbatim. Computing them here would be a frontend ranking engine
// over a league-wide population, which CLAUDE.md forbids. An absent key means
// the component was UNMEASURED that week and is simply not shown — never
// rendered as a worst-place finish.
function composition(row) {
  const ranks = row.componentRanks || {};
  return Object.keys(COMPONENT_RANK_LABELS)
    .filter((key) => ranks[key] != null)
    .map((key) => `${COMPONENT_RANK_LABELS[key]} #${ranks[key]}`)
    .join(" · ");
}

const CURRENT_WEEK_KEY = "__current";

// ── Power trail chart ────────────────────────────────────────────────────
// Ported from the retired power.jsx unchanged in shape -- reads
// ``trend.seriesByOwner`` (``{season, week, powerScore, rank}[]`` per
// owner), the canonical engine's own already-published time series.
// No computation happens here beyond building one shared chronological
// axis across owners, exactly what the retired chart did with its own
// ``seriesByOwner``. Unlike the retired chart, points with a ``null``
// ``powerScore`` (a results-only week can itself be unrankable) are
// filtered out of each line rather than plotted as 0.
function PowerChart({ series, highlightOwnerId = null }) {
  // trend.seriesByOwner chains every tracked season's played weeks onto one
  // sequential axis (see power_v2.py's week_states loop over seasons_sorted),
  // so a 3-season history can show most of its visible swings from COMPLETED
  // past seasons while the current season has only just started. Without a
  // season boundary a reader has no way to tell "that dramatic movement was
  // 2024" from "that's this week" — exactly what produced the "the score
  // moved but the rankings didn't" confusion this fixes. Boundaries are
  // display-only: they never change xMax, the line geometry, or the data.
  const { lines, xMax, seasonBoundaries } = useMemo(() => {
    if (!series || !series.length) return { lines: [], xMax: 0, seasonBoundaries: [] };
    const allKeys = new Map(); // "season:week" → order
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
    ordered.sort((a, b) => {
      const [sa, wa] = a.split(":");
      const [sb, wb] = b.split(":");
      if (sa !== sb) return Number(sa) - Number(sb);
      return Number(wa) - Number(wb);
    });
    ordered.forEach((k, i) => allKeys.set(k, i));

    const seasonBoundaries = [];
    let lastSeason = null;
    ordered.forEach((k, i) => {
      const season = k.split(":")[0];
      if (season !== lastSeason) {
        seasonBoundaries.push({ x: i, season });
        lastSeason = season;
      }
    });

    const lines = sortedSeries.map((s) => ({
      ownerId: s.ownerId,
      displayName: s.displayName,
      points: s.points
        .filter((p) => p.powerScore != null)
        .map((p) => ({
          x: allKeys.get(`${p.season}:${p.week}`),
          y: p.powerScore,
          season: p.season,
          week: p.week,
          rank: p.rank,
        })),
    }));
    return { lines, xMax: ordered.length - 1, seasonBoundaries };
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
      "#4fc3f7", "#ffa726", "#66bb6a", "#ef5350", "#ab47bc", "#26c6da",
      "#ffee58", "#8d6e63", "#ec407a", "#7e57c2", "#9ccc65", "#ff7043",
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
        {seasonBoundaries.map((b) => (
          <g key={`season-${b.season}`}>
            {b.x > 0 && (
              <line
                x1={px(b.x)}
                x2={px(b.x)}
                y1={padT}
                y2={padT + plotH}
                stroke="var(--border-bright)"
                strokeDasharray="2 4"
                opacity={0.6}
              />
            )}
            <text
              x={px(b.x) + (b.x > 0 ? 4 : 0)}
              y={padT + 9}
              fontSize={9}
              textAnchor="start"
              fill="var(--subtext)"
              fontFamily="var(--mono)"
            >
              {b.season}
            </text>
          </g>
        ))}
        {lines.map((line) => {
          const isHighlighted = highlightOwnerId && line.ownerId === highlightOwnerId;
          const color = colorFor(line.ownerId);
          const d = line.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.x)} ${py(p.y)}`)
            .join(" ");
          return (
            <g key={line.ownerId} opacity={highlightOwnerId && !isHighlighted ? 0.25 : 1.0}>
              <path d={d} fill="none" stroke={color} strokeWidth={isHighlighted ? 2.4 : 1.4} />
              {line.points.length > 0 && (() => {
                const last = line.points[line.points.length - 1];
                return (
                  <>
                    <circle cx={px(last.x)} cy={py(last.y)} r={3} fill={color} />
                    <text x={px(last.x) + 6} y={py(last.y) + 3} fontSize={9} fill={color} fontFamily="var(--mono)">
                      {(line.displayName || line.ownerId).slice(0, 12)}
                    </text>
                  </>
                );
              })()}
            </g>
          );
        })}
        <text x={padL + plotW / 2} y={H - 4} fontSize={9} textAnchor="middle" fill="var(--subtext)">
          Weeks played (chronological)
        </text>
      </svg>
    </div>
  );
}

function MovementMark({ value, emptyLabel = "—" }) {
  if (value == null) return <span style={{ color: "var(--subtext)" }}>{emptyLabel}</span>;
  if (Number(value) === 0) return <span style={{ color: "var(--subtext)" }}>—</span>;
  const up = Number(value) > 0;
  return (
    <span
      aria-label={up ? `up ${Math.abs(Number(value))}` : `down ${Math.abs(Number(value))}`}
      style={{
        fontFamily: "var(--mono)",
        fontWeight: 800,
        color: up ? "var(--positive, var(--cyan))" : "var(--negative, var(--amber))",
      }}
    >
      {up ? "▲" : "▼"} {Math.abs(Number(value))}
    </span>
  );
}

function LeaguePowerShareCard({ data, rankings, managers }) {
  const official = data?.shareSnapshot || data?.officialSnapshot || null;
  const rows = Array.isArray(official?.ranking) && official.ranking.length ? official.ranking : rankings;
  const week = official?.week ?? data?.asOfWeek ?? null;
  const season = official?.season ?? data?.asOfSeason ?? null;
  const isOfficial = !!official;

  return (
    <div
      data-testid="league-power-share-card"
      aria-label="League Power Rankings share card"
      style={{
        width: "min(100%, 520px)",
        margin: "10px auto 14px",
        padding: "14px 14px 10px",
        border: "1px solid var(--border-bright, var(--border))",
        borderRadius: 12,
        background: "var(--panel, rgba(12, 18, 28, 0.98))",
        boxShadow: "0 10px 30px rgba(0,0,0,0.22)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline", marginBottom: 8 }}>
        <div>
          <div style={{ fontSize: "1rem", fontWeight: 900, letterSpacing: "0.02em" }}>League Power Rankings</div>
          <div style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
            {season ? season : "Current season"}{week ? ` · Week ${week}` : ""}{isOfficial ? " · Official" : " · Current"}
          </div>
        </div>
        <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textAlign: "right" }}>
          Risk It To Get The Brisket
        </div>
      </div>

      <div style={{ display: "grid", gap: 2 }}>
        {rows.map((row, index) => {
          const movement = isOfficial ? row.rankDelta : row.weekRankDelta;
          const ownerName = managers
            ? nameFor(managers, row.ownerId)
            : row.displayName || row.ownerId || "—";
          return (
            <div
              key={row.ownerId || index}
              style={{
                display: "grid",
                gridTemplateColumns: "30px minmax(0,1fr) 58px",
                alignItems: "center",
                minHeight: 31,
                padding: "4px 6px",
                borderBottom: index === rows.length - 1 ? "none" : "1px solid var(--border)",
              }}
            >
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.82rem", fontWeight: 900, textAlign: "center" }}>
                {row.rank ?? "—"}
              </div>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: "0.82rem", fontWeight: 750, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {ownerName}
                </div>
                {row.teamName ? (
                  <div style={{ fontSize: "0.6rem", color: "var(--subtext)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {row.teamName}
                  </div>
                ) : null}
              </div>
              <div style={{ textAlign: "right", fontSize: "0.74rem" }}>
                <MovementMark value={movement} emptyLabel={week && Number(week) <= 1 ? "NEW" : "—"} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function RosPowerSection({ managers } = {}) {
  const [lens, setLens] = useState(LENS_CANONICAL);
  const [data, setData] = useState(() => _caches[LENS_CANONICAL].data);
  const [error, setError] = useState(_caches[LENS_CANONICAL].error);
  const [loading, setLoading] = useState(!_caches[LENS_CANONICAL].data);
  const [expanded, setExpanded] = useState(null);
  const [selectedWeekKey, setSelectedWeekKey] = useState(CURRENT_WEEK_KEY);
  const [hoverOwnerId, setHoverOwnerId] = useState(null);
  const [oddsData, setOddsData] = useState(() => _oddsCache.data);
  const [oddsError, setOddsError] = useState(() => _oddsCache.error);
  const [shareOpen, setShareOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(!_caches[lens]?.data);
    _fetchRosPower(lens).then(({ data: d, error: e }) => {
      if (!active) return;
      setData(d);
      setError(e);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, [lens]);

  // Playoff odds, ported unchanged from the retired power.jsx: fetch
  // once and cache at module scope so repeated Power-tab mounts within
  // ODDS_CACHE_TTL_MS reuse the cached response rather than re-running
  // the Monte Carlo.
  useEffect(() => {
    let cancelled = false;
    _fetchOddsOnce().then(({ data: body, error: err }) => {
      if (cancelled) return;
      if (body) setOddsData(body);
      if (err) setOddsError(err);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const lensToggle = (
    <div style={{ display: "flex", gap: 4, marginBottom: 8, fontSize: "0.72rem" }}>
      {[
        { key: LENS_CANONICAL, label: "Canonical" },
        { key: LENS_RESULTS_ONLY, label: "Results only" },
      ].map((opt) => (
        <button
          key={opt.key}
          type="button"
          onClick={() => {
            setLens(opt.key);
            if (opt.key !== LENS_CANONICAL) setShareOpen(false);
          }}
          aria-pressed={lens === opt.key}
          style={{
            padding: "3px 10px",
            borderRadius: 4,
            border: "1px solid var(--subtext)",
            background: lens === opt.key ? "var(--cyan)" : "transparent",
            color: lens === opt.key ? "#000" : "var(--subtext)",
            cursor: "pointer",
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );

  if (loading && !data) {
    return <LoadingState message="Loading ROS power rankings..." />;
  }
  if (error && !data) {
    return (
      <Card>
        <EmptyState title="ROS Power unavailable" message={error} />
      </Card>
    );
  }
  const rankings = data?.currentRanking || [];

  // The engine refused to rank, and that is a DIFFERENT state from
  // "not ready yet".  Every weighted component was unavailable, so
  // there is no quantity to rank on — the backend withholds the score
  // and the rank rather than publishing zeros in owner-id order.
  //
  // Rendering that as an empty table, or as a column of "—", would let
  // the reader assume the data is still loading and will arrive. It is
  // not loading: for the results-only lens in the offseason this state
  // is structural and persists until the season starts. Say which one
  // it is, and show the reason the backend gave.
  const unrankable = data?.unrankable;
  if (unrankable) {
    return (
      <Card title="Power Rankings">
        {lensToggle}
        <EmptyState
          title="Not enough to rank on"
          message={
            unrankable.explanation ||
            "Every weighted component is unavailable, so no ranking is published."
          }
        />
        {(unrankable.missingInputs || []).length > 0 && (
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 8 }}>
            Missing: {unrankable.missingInputs.join(", ")}
          </div>
        )}
        {rankings.length > 0 && (
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 8 }}>
            {rankings.length} managers listed without a score.
          </div>
        )}
      </Card>
    );
  }

  if (!rankings.length) {
    return (
      <Card>
        {lensToggle}
        <EmptyState
          title="Power rankings not ready"
          message="The league snapshot or ROS roster-strength data is missing. Once the next scheduled scrape lands, this view will populate."
        />
      </Card>
    );
  }

  const specWeights = data.weights || {};
  const effectiveWeights = data.effectiveWeights || specWeights;
  const missing = data.missingInputs || [];
  const rosAvailable = !!data.rosTeamStrengthAvailable;
  const preseason = !!data.preseason;
  const trend = data.trend || null;
  const trendWeeks = trend?.weeks || [];
  const blend = data.blend || {};
  const forwardPct = Math.round(Number(blend.forwardWeight || 0) * 100);
  const resultsPct = Math.round(Number(blend.resultsWeight || 0) * 100);

  // "Most recent" shows the currently-selected lens's headline ranking —
  // consistent with the table above it. Any specific historical week
  // shows ``trend.weeks``, which is ALWAYS results-only by construction
  // (team ROS strength has no per-week history to look back at — see
  // the backend's own comment). Labeled rather than silently switched,
  // so a reader who picks a past week is told which quantity they're
  // looking at.
  const selectedWeekIndex =
    selectedWeekKey === CURRENT_WEEK_KEY
      ? -1
      : trendWeeks.findIndex((w) => `${w.season}:${w.week}` === selectedWeekKey);
  const viewingHistory = selectedWeekIndex >= 0;
  const displayedRankings = viewingHistory
    ? trendWeeks[selectedWeekIndex]?.rankings || []
    : rankings;

  // The weights that produced THE WEEK ON SCREEN. A historical week is scored
  // with its own renormalized vector (no ROS, so the results components absorb
  // its mass), and showing the current week's blend beside those rows would
  // describe a calculation that did not produce them.
  const displayedEffectiveWeights = viewingHistory
    ? trendWeeks[selectedWeekIndex]?.effectiveWeights || {}
    : effectiveWeights;
  const displayedWeightsBase = viewingHistory ? {} : effectiveWeights;

  // Render the formula from the weights actually applied. Missing canonical
  // inputs (for example realized weekly VORP before its owner is ready) never
  // appear as fabricated zero-weight evidence. Order by weight descending.
  const formulaParts = Object.entries(displayedEffectiveWeights)
    .filter(([, w]) => Number(w) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([key, w]) => `${COMPONENT_LABELS[key] || key} (${Math.round(Number(w) * 100)}%)`);

  // A results-only reconstruction must never be served under the plain
  // canonical heading. The two answer different questions — the canonical
  // blend is 40% forward-looking roster strength, the reconstruction has none
  // of it and renormalizes onto results — and at week 1 the reconstruction is
  // close to a single-week points sort. Rendering that as "2026 Wk 1 Power
  // Rankings" is what made it read as a standings table.
  const historyTitle = viewingHistory
    ? `Power Rankings — diagnostic (results-only), ${trendWeeks[selectedWeekIndex]?.season} Wk ${trendWeeks[selectedWeekIndex]?.week}`
    : "Power Rankings";
  const historySubtitle = viewingHistory
    ? trend?.note ||
      "Reconstructed from results alone. Canonical ROS strength was never snapshotted for past weeks, so it is not back-filled — this is not the published canonical ranking for that week."
    : undefined;

  return (
    <section>
      <Card title={historyTitle} subtitle={historySubtitle}>
        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
          {lensToggle}
          {lens === LENS_CANONICAL ? (
            <button
              type="button"
              onClick={() => setShareOpen((open) => !open)}
              aria-expanded={shareOpen}
              aria-controls="league-power-share-card"
              style={{
                padding: "5px 11px",
                borderRadius: 6,
                border: "1px solid var(--border-bright, var(--subtext))",
                background: shareOpen ? "var(--cyan)" : "transparent",
                color: shareOpen ? "#000" : "var(--text)",
                cursor: "pointer",
                fontSize: "0.72rem",
                fontWeight: 700,
              }}
            >
              {shareOpen ? "Hide Share Card" : "Share Rankings"}
            </button>
          ) : null}
        </div>

        {shareOpen && lens === LENS_CANONICAL ? (
          <div id="league-power-share-card">
            <LeaguePowerShareCard data={data} rankings={rankings} managers={managers} />
            <div style={{ textAlign: "center", fontSize: "0.66rem", color: "var(--subtext)", margin: "-6px 0 10px" }}>
              Sized to fit all 12 teams in one phone screenshot. Official weekly cards stay frozen after publication.
            </div>
          </div>
        ) : null}

        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
          {/* The blend summary describes the CANONICAL calculation, so it is
              suppressed while a diagnostic week is on screen — that week has no
              forward-looking mass at all, and printing "40% forward-looking"
              above rows computed without it is the same conflation this view
              split exists to end. */}
          {viewingHistory ? (
            <span style={{ color: "var(--amber)" }}>
              Diagnostic results-only reconstruction — not the canonical ranking.{" "}
            </span>
          ) : lens === LENS_CANONICAL ? (
            <span style={{ color: "var(--cyan)" }}>
              Canonical blend: {forwardPct}% forward-looking strength + {resultsPct}% results.{" "}
            </span>
          ) : (
            <span style={{ color: "var(--subtext)" }}>Diagnostic results-only view.{" "}</span>
          )}
          {preseason && lens === LENS_CANONICAL && !viewingHistory ? (
            <span>Preseason uses only legitimate forward-looking evidence.{" "}</span>
          ) : null}
          {formulaParts.join(" + ")}
          {formulaParts.length > 0 && "."}
          {!rosAvailable && (
            <span style={{ color: "var(--amber)" }}> ROS roster strength not available yet.</span>
          )}
          {!preseason && missing.length > 0 && <span> Missing inputs: {missing.join(", ")}.</span>}
        </div>

        {trendWeeks.length > 0 && (
          <div style={{ marginBottom: 10 }}>
            <select
              className="input"
              value={selectedWeekKey}
              onChange={(e) => setSelectedWeekKey(e.target.value)}
              style={{ minWidth: 180, fontSize: "0.78rem" }}
            >
              <option value={CURRENT_WEEK_KEY}>Most recent (canonical)</option>
              {/* Every past week in this list is the results-only
                  reconstruction, so each option says so. A reader choosing a
                  past week should know before they read the numbers, not
                  after. */}
              {[...trendWeeks].reverse().map((w) => (
                <option key={`${w.season}:${w.week}`} value={`${w.season}:${w.week}`}>
                  {w.season} Wk {w.week} · diagnostic
                </option>
              ))}
            </select>
            {viewingHistory && (
              <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 4 }}>
                Movement compares against the previous week of this season only. A
                season&apos;s first week has no in-season predecessor, so it shows no
                movement rather than a comparison with last season.
              </div>
            )}
          </div>
        )}

        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
          <thead>
            <tr style={{ color: "var(--subtext)", fontSize: "0.7rem", textTransform: "uppercase" }}>
              <th style={{ textAlign: "right", padding: "4px 8px 4px 0" }}>#</th>
              <th style={{ textAlign: "left", padding: "4px 0" }}>Owner</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Power</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>PPG</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Recent</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>ROS Pct</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Record</th>
              <th
                style={{ textAlign: "right", padding: "4px 8px" }}
                title={viewingHistory ? "Results-only historical change" : "Current canonical rank vs. the previous official weekly snapshot"}
              >
                Move
              </th>
            </tr>
          </thead>
          <tbody>
            {displayedRankings.map((row, i) => (
              <RankingRow
                key={row.ownerId || i}
                row={row}
                managers={managers}
                weights={row.weightsApplied || displayedWeightsBase}
                expanded={expanded === `${selectedWeekKey}:${i}`}
                onToggle={() => setExpanded(expanded === `${selectedWeekKey}:${i}` ? null : `${selectedWeekKey}:${i}`)}
                onHover={setHoverOwnerId}
                hovered={hoverOwnerId === row.ownerId}
                trendDeltaValue={
                  viewingHistory
                    ? weekDelta(trendWeeks, selectedWeekIndex, row.ownerId)
                    : row.weekRankDelta
                }
              />
            ))}
          </tbody>
        </table>
      </Card>

      {trend?.seriesByOwner && (
        <Card
          title="Power score over time"
          subtitle="Diagnostic results-only history. Official canonical week-to-week movement is frozen in the weekly share snapshots."
        >
          <PowerChart
            series={Object.entries(trend.seriesByOwner).map(([ownerId, points]) => ({
              ownerId,
              displayName:
                rankings.find((r) => r.ownerId === ownerId)?.displayName || ownerId,
              points,
            }))}
            highlightOwnerId={hoverOwnerId}
          />
        </Card>
      )}

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
    </section>
  );
}

function TrendCell({ deltaValue }) {
  // Null means there is no legitimate previous official/diagnostic rank to
  // compare with. It is not a fabricated "flat" movement.
  if (deltaValue == null) {
    return (
      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
        —
      </td>
    );
  }
  if (deltaValue === 0) {
    return (
      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
        •
      </td>
    );
  }
  const up = deltaValue > 0;
  return (
    <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: up ? "var(--cyan)" : "var(--amber)" }}>
      {up ? "▲" : "▼"} {Math.abs(deltaValue)}
    </td>
  );
}

function RankingRow({ row, managers, weights, expanded, onToggle, trendDeltaValue, onHover, hovered }) {
  const c = row.components || {};
  return (
    <>
      <tr
        style={{ cursor: "pointer", background: hovered ? "rgba(79,195,247,0.08)" : "transparent" }}
        onClick={onToggle}
        onMouseEnter={() => onHover?.(row.ownerId)}
        onMouseLeave={() => onHover?.(null)}
        title="Click for component breakdown"
      >
        <td style={{ textAlign: "right", paddingRight: 8, color: "var(--subtext)" }}>{row.rank}</td>
        <td>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
            {managers && <Avatar managers={managers} ownerId={row.ownerId} size={20} />}
            <span>
              <div style={{ fontWeight: 600, lineHeight: 1.1 }}>
                {managers ? nameFor(managers, row.ownerId) : row.displayName || row.ownerId || "—"}
              </div>
              {row.teamName && (
                <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>{row.teamName}</div>
              )}
              {composition(row) && (
                <div
                  style={{ fontSize: "0.62rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}
                  title="Where this team ranks on each weighted component"
                >
                  {composition(row)}
                </div>
              )}
            </span>
          </span>
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 700, color: "var(--cyan)" }}>
          {fmtScore(row.powerScore)}
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtRaw(c.pointsPerGame)}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtRaw(c.recentAvg)}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
          {fmtPct(row.rosStrengthPercentile)}
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.record || "—"}</td>
        <TrendCell deltaValue={trendDeltaValue} />
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8} style={{ background: "rgba(255,255,255,0.02)", padding: "8px 12px" }}>
            <div style={{ fontSize: "0.72rem" }}>
              {Object.entries(COMPONENT_LABELS).map(([key, label]) => (
                <ComponentBar key={key} label={label} value={c[key]} weight={weights[key] ?? 0} />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
