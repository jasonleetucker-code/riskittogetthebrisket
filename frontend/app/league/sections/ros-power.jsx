"use client";

// ROS-driven Power Rankings (v2).  Side-by-side replacement for the
// existing power.jsx.  Lazy-fetched from /api/public/league/rosPower
// because the section reads the ROS team-strength snapshot and
// re-walks the snapshot each call — same lazy pattern as playoff
// odds.  When the snapshot has no ROS data yet (first deploy before
// the scrape lands), the section degrades cleanly to a v1-style
// formula with ROS components missing — see ``missingInputs`` field.

import { useEffect, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";
import { Card } from "../shared-server.jsx";

// Module-level cache so tab-switching doesn't re-fetch on every mount.
// Same pattern + 30-min TTL that power.jsx uses for playoff odds.
const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, error: null, inflight: null, fetchedAt: 0 };

async function _fetchRosPower() {
  const fresh = _cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _cache.data, error: null };
  if (_cache.inflight) return _cache.inflight;

  const promise = fetch("/api/public/league/rosPower")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
    .then((payload) => {
      const body = payload?.data || payload?.section || payload;
      _cache.data = body;
      _cache.error = null;
      _cache.fetchedAt = Date.now();
      _cache.inflight = null;
      return { data: body, error: null };
    })
    .catch((err) => {
      _cache.inflight = null;
      const message = String(err?.message || err);
      _cache.error = message;
      return { data: _cache.data, error: message };
    });

  _cache.inflight = promise;
  return promise;
}

function fmtScore(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Number(v).toFixed(1);
}

function fmtPct(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return `${Math.round(Number(v) * 100)}%`;
}

function ComponentBar({ label, value, weight }) {
  if (weight === 0) return null;
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

const COMPONENT_LABELS = {
  team_ros_strength: "ROS roster strength",
  ppg: "Points per game",
  recent: "Recent form",
  wl_record: "W/L record",
  all_play: "All-play record",
  streak: "Streak",
  schedule_adjusted: "Schedule-adjusted",
  roster_health: "Roster health",
  luck_regression: "Luck regression",
};

export default function RosPowerSection() {
  const [data, setData] = useState(() => _cache.data);
  const [error, setError] = useState(_cache.error);
  const [loading, setLoading] = useState(!_cache.data);
  const [expanded, setExpanded] = useState(null);

  useEffect(() => {
    let active = true;
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
      <Card title="ROS Power Rankings">
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
          title="ROS Power not ready"
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

  // Render the formula description from whichever weights are actually
  // applied so the UI doesn't claim "season PPG (18%)" when we're going
  // into a fresh year and that component has been routed through
  // ``missingInputs``.  Order by weight descending so the dominant
  // contributors lead the line.
  const formulaParts = Object.entries(effectiveWeights)
    .filter(([, w]) => Number(w) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .map(
      ([key, w]) =>
        `${COMPONENT_LABELS[key] || key} (${Math.round(Number(w) * 100)}%)`,
    );

  return (
    <Card title="ROS Power Rankings">
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
        {preseason && (
          <span style={{ color: "var(--cyan)" }}>
            Going into the new season — only forward-looking inputs are used.{" "}
          </span>
        )}
        {formulaParts.join(" + ")}
        {formulaParts.length > 0 && "."}
        {!rosAvailable && (
          <span style={{ color: "var(--amber)" }}>
            {" "}
            ROS roster strength not available yet.
          </span>
        )}
        {!preseason && missing.length > 0 && (
          <span>
            {" "}
            Missing inputs: {missing.join(", ")}.
          </span>
        )}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
        <thead>
          <tr
            style={{
              color: "var(--subtext)",
              fontSize: "0.7rem",
              textTransform: "uppercase",
            }}
          >
            <th style={{ textAlign: "right", padding: "4px 8px 4px 0" }}>#</th>
            <th style={{ textAlign: "left", padding: "4px 0" }}>Owner</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Power</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>ROS Pct</th>
          </tr>
        </thead>
        <tbody>
          {rankings.map((row, i) => (
            <RankingRow
              key={row.ownerId || i}
              row={row}
              weights={row.weightsApplied || effectiveWeights}
              expanded={expanded === i}
              onToggle={() => setExpanded(expanded === i ? null : i)}
            />
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function RankingRow({ row, weights, expanded, onToggle }) {
  return (
    <>
      <tr style={{ cursor: "pointer" }} onClick={onToggle} title="Click for component breakdown">
        <td style={{ textAlign: "right", paddingRight: 8, color: "var(--subtext)" }}>
          {row.rank}
        </td>
        <td style={{ fontWeight: 600 }}>{row.displayName || row.ownerId || "—"}</td>
        <td
          style={{
            textAlign: "right",
            fontFamily: "var(--mono)",
            fontWeight: 700,
            color: "var(--cyan)",
          }}
        >
          {fmtScore(row.powerScore)}
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
          {fmtPct(row.rosStrengthPercentile)}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={4} style={{ background: "rgba(255,255,255,0.02)", padding: "8px 12px" }}>
            <div style={{ fontSize: "0.72rem" }}>
              {Object.entries(COMPONENT_LABELS).map(([key, label]) => (
                <ComponentBar
                  key={key}
                  label={label}
                  value={row.components?.[key]}
                  weight={weights[key] ?? 0}
                />
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
