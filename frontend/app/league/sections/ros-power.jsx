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
// ONE league-facing ranking. The engine still accepts ``?lens=results_only``
// as an analytical diagnostic (spec section 3), and ``forward_looking`` as a
// compatibility alias, but this page does not present either as a competing
// Power Ranking — so there is one cache, not one per lens.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, error: null, inflight: null, fetchedAt: 0 };

async function _fetchRosPower() {
  const cache = _cache;
  const fresh = cache.data && Date.now() - cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: cache.data, error: null };
  if (cache.inflight) return cache.inflight;

  const promise = fetch("/api/public/league/rosPower")
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

// Movement is BACKEND-OWNED. ``row.weekRankDelta`` is computed by
// ``power_snapshots.movement_against_previous`` against exactly week N-1's
// immutable publication, and the share card reads the frozen ``rankDelta`` off
// the snapshot itself. This file deliberately has no rank-delta arithmetic:
// a second definition of "how far did they move" is how the page ended up
// disagreeing with the card it was next to.
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

// ── Rank history chart ──────────────────────────────────────────────────
// Reads ``officialHistory`` — the immutable weekly publications, and nothing
// else. Every point is a week that was actually published, so this chart and
// the arrows on the share card can never disagree.
//
// It plots RANK, not Power score, for a reason: an owner-attested baseline week
// records the order the site published and carries no Power score at all
// (``rankSource: owner_attested_published_card``). Rank is the quantity every
// published week has. Plotting the score instead would silently drop the
// baseline off the left edge of the chart.
//
// The old chart read ``trend.seriesByOwner`` — the results-only reconstruction
// chained across every tracked season. That is a different ranking from the one
// the page publishes, and rendering it beside the canonical table is what made
// the page look like it had three answers. It is gone from this page; the
// diagnostic lens still exists in the engine (``?lens=results_only``).
function RankHistoryChart({ history, managers, highlightOwnerId = null }) {
  const { lines, weeks, maxRank } = useMemo(() => {
    const ordered = [...(history || [])]
      .filter((w) => Number.isFinite(Number(w?.week)))
      .sort((a, b) => Number(a.week) - Number(b.week));
    const byOwner = new Map();
    let maxRank = 0;
    ordered.forEach((week, x) => {
      for (const row of week.ranking || []) {
        if (row?.ownerId == null || row?.rank == null) continue;
        const rank = Number(row.rank);
        if (!Number.isFinite(rank)) continue;
        maxRank = Math.max(maxRank, rank);
        const key = String(row.ownerId);
        if (!byOwner.has(key)) byOwner.set(key, []);
        byOwner.get(key).push({ x, y: rank, week: week.week });
      }
    });
    return {
      lines: [...byOwner.entries()].map(([ownerId, points]) => ({ ownerId, points })),
      weeks: ordered,
      maxRank,
    };
  }, [history]);

  // One published week is a dot, not a history. Say so rather than rendering a
  // chart with nothing to compare against.
  if (weeks.length < 2 || !lines.length || maxRank < 1) {
    return (
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", padding: "6px 2px" }}>
        Rank history begins once a second week is published.
      </div>
    );
  }

  const W = 640;
  const H = 260;
  const padL = 30;
  const padR = 80;
  const padT = 16;
  const padB = 24;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;
  const xMax = weeks.length - 1;

  const px = (x) => padL + (x / xMax) * plotW;
  // Rank 1 sits at the TOP. The axis is inverted relative to a score axis,
  // which is the whole point: up on this chart means up in the rankings.
  const py = (rank) => padT + ((rank - 1) / Math.max(1, maxRank - 1)) * plotH;

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

  const rankTicks = [1, ...(maxRank > 2 ? [Math.round((maxRank + 1) / 2)] : []), maxRank];

  return (
    <div style={{ overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        style={{ maxWidth: W, display: "block", margin: "0 auto" }}
        aria-label="Published rank by week per manager"
      >
        {rankTicks.map((r) => (
          <g key={r}>
            <line
              x1={padL}
              x2={W - padR}
              y1={py(r)}
              y2={py(r)}
              stroke="var(--border)"
              strokeDasharray="3 3"
              opacity={0.5}
            />
            <text
              x={padL - 6}
              y={py(r) + 3}
              fontSize={9}
              textAnchor="end"
              fill="var(--subtext)"
              fontFamily="var(--mono)"
            >
              {r}
            </text>
          </g>
        ))}
        {weeks.map((w, x) => (
          <text
            key={`wk-${w.week}`}
            x={px(x)}
            y={H - 12}
            fontSize={9}
            textAnchor="middle"
            fill="var(--subtext)"
            fontFamily="var(--mono)"
          >
            {w.preseason ? "Pre" : `Wk ${w.week}`}
          </text>
        ))}
        {lines.map((line) => {
          const isHighlighted = highlightOwnerId && line.ownerId === highlightOwnerId;
          const color = colorFor(line.ownerId);
          const d = line.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.x)} ${py(p.y)}`)
            .join(" ");
          const last = line.points[line.points.length - 1];
          const label = managers ? nameFor(managers, line.ownerId) : line.ownerId;
          return (
            <g key={line.ownerId} opacity={highlightOwnerId && !isHighlighted ? 0.25 : 1.0}>
              <path d={d} fill="none" stroke={color} strokeWidth={isHighlighted ? 2.4 : 1.4} />
              <circle cx={px(last.x)} cy={py(last.y)} r={3} fill={color} />
              <text
                x={px(last.x) + 6}
                y={py(last.y) + 3}
                fontSize={9}
                fill={color}
                fontFamily="var(--mono)"
              >
                {String(label || line.ownerId).slice(0, 12)}
              </text>
            </g>
          );
        })}
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

  // Name the week the arrows are measured against, so "no movement" and
  // "no baseline to move against" cannot read the same on a screenshot.
  // Taken from the published history, never inferred from the week number:
  // a league whose baseline was never published must not claim one.
  const baseline = (data?.officialHistory || [])
    .filter((w) => week != null && Number(w?.week) === Number(week) - 1)
    .at(0);
  const baselineLabel = baseline
    ? `vs ${baseline.preseason ? "preseason" : `Week ${baseline.week}`}`
    : null;

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
            {baselineLabel ? ` · ${baselineLabel}` : ""}
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
                <MovementMark value={movement} emptyLabel={row.priorRank == null ? "NEW" : "—"} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function RosPowerSection({ managers } = {}) {
  const [data, setData] = useState(() => _cache.data);
  const [error, setError] = useState(_cache.error);
  const [loading, setLoading] = useState(!_cache.data);
  const [expanded, setExpanded] = useState(null);
  const [hoverOwnerId, setHoverOwnerId] = useState(null);
  const [oddsData, setOddsData] = useState(() => _oddsCache.data);
  const [oddsError, setOddsError] = useState(() => _oddsCache.error);
  const [shareOpen, setShareOpen] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(!_cache.data);
    _fetchRosPower().then(({ data: d, error: e }) => {
      if (!active) return;
      setData(d);
      setError(e);
      setLoading(false);
    });
    return () => {
      active = false;
    };
  }, []);

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
  // not loading: in the preseason, with no forward-looking input yet,
  // this state is structural and persists until the season starts. Say
  // which one it is, and show the reason the backend gave.
  const unrankable = data?.unrankable;
  if (unrankable) {
    return (
      <Card title="Power Rankings">
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
  const officialHistory = data.officialHistory || [];
  const blend = data.blend || {};
  const scoredGames = Number(blend.scoredGames || 0);
  const medianGameEnabled = data.medianGameEnabled;
  const forwardPct = Math.round(Number(blend.forwardWeight || 0) * 100);
  const resultsPct = Math.round(Number(blend.resultsWeight || 0) * 100);

  // Render the formula from the weights actually applied. Missing canonical
  // inputs (for example realized weekly VORP before its owner is ready) never
  // appear as fabricated zero-weight evidence. Order by weight descending.
  const formulaParts = Object.entries(effectiveWeights)
    .filter(([, w]) => Number(w) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(([key, w]) => `${COMPONENT_LABELS[key] || key} (${Math.round(Number(w) * 100)}%)`);

  return (
    <section>
      <Card title="Power Rankings">
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, flexWrap: "wrap", alignItems: "center" }}>
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
        </div>

        {shareOpen ? (
          <div id="league-power-share-card">
            <LeaguePowerShareCard data={data} rankings={rankings} managers={managers} />
            <div style={{ textAlign: "center", fontSize: "0.66rem", color: "var(--subtext)", margin: "-6px 0 10px" }}>
              Sized to fit all 12 teams in one phone screenshot. Official weekly cards stay frozen after publication.
            </div>
          </div>
        ) : null}

        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
          <span style={{ color: "var(--cyan)" }}>
            Blend: {forwardPct}% forward-looking strength + {resultsPct}% results.{" "}
          </span>
          {preseason ? (
            <span>Preseason uses only legitimate forward-looking evidence.{" "}</span>
          ) : null}
          {formulaParts.join(" + ")}
          {formulaParts.length > 0 && "."}
          {!rosAvailable && (
            <span style={{ color: "var(--amber)" }}> ROS roster strength not available yet.</span>
          )}
          {!preseason && missing.length > 0 && <span> Missing inputs: {missing.join(", ")}.</span>}
        </div>

        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
          <thead>
            <tr style={{ color: "var(--subtext)", fontSize: "0.7rem", textTransform: "uppercase" }}>
              <th style={{ textAlign: "right", padding: "4px 8px 4px 0" }}>#</th>
              <th style={{ textAlign: "left", padding: "4px 0" }}>Owner</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Power</th>
              <th
                style={{ textAlign: "right", padding: "4px 8px" }}
                title={
                  scoredGames > 0
                    ? `Points per game, averaged over the ${scoredGames} league week${scoredGames === 1 ? "" : "s"} every team has finished`
                    : "No completed league week yet"
                }
              >
                {scoredGames > 0 ? `PPG (${scoredGames} wk)` : "PPG"}
              </th>
              <th
                style={{ textAlign: "right", padding: "4px 8px" }}
                title="Trailing 4-game average. Reads the same as PPG until the 4th game — that is the window filling, not a display error."
              >
                {scoredGames > 0 ? `Recent (${Math.min(scoredGames, 4)} of 4)` : "Recent"}
              </th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>ROS Pct</th>
              <th
                style={{ textAlign: "right", padding: "4px 8px" }}
                title={
                  medianGameEnabled === true
                    ? "This league counts a league-average game alongside head-to-head, so Record can show more games than PPG's denominator — that is expected, not a mismatch."
                    : medianGameEnabled === false
                      ? "Head-to-head only."
                      : "Whether this league counts a league-average game is unverified."
                }
              >
                Record
              </th>
              <th
                style={{ textAlign: "right", padding: "4px 8px" }}
                title="Current rank vs. the previous official weekly snapshot"
              >
                Move
              </th>
            </tr>
          </thead>
          <tbody>
            {rankings.map((row, i) => (
              <RankingRow
                key={row.ownerId || i}
                row={row}
                managers={managers}
                weights={row.weightsApplied || effectiveWeights}
                expanded={expanded === i}
                onToggle={() => setExpanded(expanded === i ? null : i)}
                onHover={setHoverOwnerId}
                hovered={hoverOwnerId === row.ownerId}
                trendDeltaValue={row.weekRankDelta}
                sectionGamesUsed={scoredGames}
              />
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="Rank history"
        subtitle="Official published weeks only. Each point is a week that was actually published, so this agrees with the share card by construction."
      >
        <RankHistoryChart
          history={officialHistory}
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

function RankingRow({
  row,
  managers,
  weights,
  expanded,
  onToggle,
  trendDeltaValue,
  onHover,
  hovered,
  sectionGamesUsed,
}) {
  const c = row.components || {};
  // A row with no games counted has nothing to average -- fmtRaw already
  // renders null as "—", so this only needs to name a row whose count
  // disagrees with the table's shared denominator, which the completed-week
  // gate should make impossible on a healthy board.
  const rowGames = row.gamesUsed;
  const gamesMismatch =
    rowGames != null && sectionGamesUsed != null && rowGames !== sectionGamesUsed;
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
        <td
          style={{ textAlign: "right", fontFamily: "var(--mono)" }}
          title={gamesMismatch ? `${rowGames} game${rowGames === 1 ? "" : "s"} counted for this team` : undefined}
        >
          {fmtRaw(c.pointsPerGame)}
          {gamesMismatch && (
            <span style={{ color: "var(--amber)", fontSize: "0.62rem" }}> ({rowGames}g)</span>
          )}
        </td>
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
