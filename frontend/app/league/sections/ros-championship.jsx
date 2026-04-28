"use client";

// ROS Championship Odds — Monte Carlo through the bracket using
// ROS-blended weekly score distributions.  Lazy-fetched from
// /api/public/league/rosChampionship; module-level cache avoids
// re-running the (slow) sim on tab-switch.

import { useEffect, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";

const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, error: null, inflight: null, fetchedAt: 0 };

async function _fetchOnce(url, cache) {
  const fresh = cache.data && Date.now() - cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: cache.data, error: null };
  if (cache.inflight) return cache.inflight;
  const promise = fetch(url)
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

function fmtPct(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

const TIER_COLORS = {
  Favorite: "var(--cyan)",
  "Serious Contender": "var(--cyan)",
  "Dangerous Playoff Team": "var(--green)",
  "Fringe Playoff Team": "var(--amber)",
  "Long Shot": "var(--subtext)",
  "Rebuilder / Seller": "var(--red)",
};

export default function RosChampionshipSection() {
  const [data, setData] = useState(() => _cache.data);
  const [error, setError] = useState(_cache.error);
  const [loading, setLoading] = useState(!_cache.data);

  useEffect(() => {
    let active = true;
    _fetchOnce("/api/public/league/rosChampionship", _cache).then(
      ({ data: d, error: e }) => {
        if (!active) return;
        setData(d);
        setError(e);
        setLoading(false);
      },
    );
    return () => {
      active = false;
    };
  }, []);

  if (loading && !data) {
    return <LoadingState message="Running championship Monte Carlo..." />;
  }
  if (error && !data) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="Championship odds unavailable" message={error} />
      </div>
    );
  }
  const rows = data?.championshipOdds || [];
  if (!rows.length) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState
          title="No championship odds yet"
          message="Need at least a partial regular season to simulate the bracket."
        />
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        ROS Championship Odds
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
        {data.n_simulations?.toLocaleString() || "—"} Monte Carlo runs ·{" "}
        {data.playoffSeeds || 6} playoff seeds · {data.byeSeeds || 2} byes ·{" "}
        {data.rosStrengthAvailable
          ? "ROS roster strength blended into weekly score distributions"
          : "Empirical-only mode (no ROS roster snapshot)"}
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
            <th style={{ textAlign: "left", padding: "4px 0" }}>Owner</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Champ</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Finals</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Semis</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Playoff</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Exp Finish</th>
            <th style={{ textAlign: "left", padding: "4px 0" }}>Tier</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={row.ownerId || i}>
              <td style={{ fontWeight: 600 }}>{row.displayName || row.ownerId || "—"}</td>
              <td
                style={{
                  textAlign: "right",
                  fontFamily: "var(--mono)",
                  fontWeight: 700,
                  color: "var(--cyan)",
                }}
              >
                {fmtPct(row.championshipOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPct(row.finalsOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPct(row.semifinalOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPct(row.playoffOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {row.expectedFinish?.toFixed(1) ?? "—"}
              </td>
              <td
                style={{
                  fontSize: "0.74rem",
                  color: TIER_COLORS[row.contenderTier] || "var(--subtext)",
                }}
              >
                {row.contenderTier}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
