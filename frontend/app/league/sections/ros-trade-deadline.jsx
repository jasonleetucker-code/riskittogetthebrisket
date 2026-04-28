"use client";

// Trade-deadline dashboard.  Combines ROS playoff/championship odds
// + team-strength + roster age into a per-team Buyer/Seller label.
// Read-only; no value math is exposed here beyond what the backend
// already computed.

import { useEffect, useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";

const CACHE_TTL_MS = 30 * 60 * 1000;
const _cache = { data: null, error: null, inflight: null, fetchedAt: 0 };

async function _fetchOnce() {
  const fresh = _cache.data && Date.now() - _cache.fetchedAt < CACHE_TTL_MS;
  if (fresh) return { data: _cache.data, error: null };
  if (_cache.inflight) return _cache.inflight;
  const promise = fetch("/api/public/league/rosTradeDeadline")
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

const LABEL_COLORS = {
  "Strong Buyer": "var(--cyan)",
  "Buyer": "var(--green)",
  "Selective Buyer": "var(--green)",
  "Hold / Evaluate": "var(--subtext)",
  "Selective Seller": "var(--amber)",
  "Seller": "var(--red)",
  "Strong Seller / Rebuilder": "var(--red)",
};

function fmtPct(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return `${(Number(v) * 100).toFixed(1)}%`;
}

export default function RosTradeDeadlineSection() {
  const [data, setData] = useState(() => _cache.data);
  const [error, setError] = useState(_cache.error);
  const [loading, setLoading] = useState(!_cache.data);

  useEffect(() => {
    let active = true;
    _fetchOnce().then(({ data: d, error: e }) => {
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
    return <LoadingState message="Loading trade-deadline dashboard..." />;
  }
  if (error && !data) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="Trade deadline unavailable" message={error} />
      </div>
    );
  }
  const teams = data?.teams || [];
  if (!teams.length) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState
          title="No trade-deadline data yet"
          message="Need ROS team-strength + a sim run to classify teams. Once ros-team-strength + rosChampionship cache populates, this view will fill in."
        />
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        Trade Deadline Dashboard
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
        Read-only Buyer/Seller direction per team based on ROS playoff +
        championship odds + team strength + roster age. Informational only —
        does not affect dynasty values or trade math.
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
            <th style={{ textAlign: "left", padding: "4px 0" }}>Team</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Champ</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Playoff</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Strength</th>
            <th style={{ textAlign: "left", padding: "4px 0" }}>Direction</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((row) => (
            <tr key={row.ownerId}>
              <td style={{ fontWeight: 600 }}>{row.displayName || row.ownerId}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPct(row.championshipOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPct(row.playoffOdds)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                {fmtPct(row.rosStrengthPercentile)}
              </td>
              <td>
                <div
                  style={{
                    fontWeight: 700,
                    color: LABEL_COLORS[row.label] || "var(--subtext)",
                  }}
                >
                  {row.label}
                </div>
                <div
                  style={{
                    fontSize: "0.7rem",
                    color: "var(--subtext)",
                    marginTop: 2,
                    lineHeight: 1.3,
                  }}
                >
                  {row.recommendation}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
