"use client";

// ROS Data Health — diagnostic view of the ROS scrape pipeline.
// Reads /api/ros/status + /api/ros/sources to render last-run state
// per ROS source, plus a "scrape now" button hitting POST
// /api/ros/refresh (admin-gated).

import { useEffect, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { fetchRosSources, fetchRosStatus } from "@/lib/ros-data";

const REFRESH_INTERVAL_MS = 60 * 1000;

function ageDescriptor(timestamp) {
  if (!timestamp) return "—";
  const ms = Date.now() - new Date(timestamp).getTime();
  if (Number.isNaN(ms)) return "—";
  const hours = ms / (3600 * 1000);
  if (hours < 1) return `${Math.round(ms / (60 * 1000))}m ago`;
  if (hours < 48) return `${hours.toFixed(1)}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function statusColor(status, ageHours) {
  if (status === "failed") return "var(--red)";
  if (status === "partial") return "var(--amber)";
  if (ageHours != null && ageHours > 12) return "var(--amber)";
  return "var(--green)";
}

export default function RosDataHealthPage() {
  const [sources, setSources] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [src, st] = await Promise.all([fetchRosSources(), fetchRosStatus()]);
      setSources(src.sources || []);
      setStatus(st);
      setError("");
    } catch (err) {
      setError(err?.message || "Failed to load ROS health.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  const triggerRefresh = async () => {
    setRefreshing(true);
    try {
      const res = await fetch("/api/ros/refresh", { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      await load();
    } catch (err) {
      setError(err?.message || "Refresh failed (admin session required).");
    } finally {
      setRefreshing(false);
    }
  };

  if (loading) return <LoadingState message="Loading ROS data health..." />;
  if (error && !sources.length) {
    return (
      <section>
        <div className="card">
          <PageHeader title="ROS Data Health" />
          <EmptyState title="ROS health unavailable" message={error} />
        </div>
      </section>
    );
  }

  const statusBySource = (status?.sources || {});

  return (
    <section>
      <div className="card">
        <PageHeader
          title="ROS Data Health"
          subtitle="Per-source scrape status for the Rest-of-Season pipeline. Auto-refreshes every 60 seconds."
        />
        <div style={{ display: "flex", gap: 12, alignItems: "center", marginBottom: 14 }}>
          <button
            type="button"
            className="button button-primary"
            onClick={triggerRefresh}
            disabled={refreshing}
          >
            {refreshing ? "Refreshing..." : "Refresh now (admin)"}
          </button>
          <span style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
            Last rebuilt: {ageDescriptor(status?.rebuiltAt)} ·{" "}
            Overall freshness: {status?.freshness || "unknown"}
          </span>
        </div>
        {error && (
          <div style={{ color: "var(--red)", fontSize: "0.78rem", marginBottom: 8 }}>
            {error}
          </div>
        )}
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
          <thead>
            <tr style={{ color: "var(--subtext)", fontSize: "0.7rem", textTransform: "uppercase" }}>
              <th style={{ textAlign: "left", padding: "4px 0" }}>Source</th>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Type</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Players</th>
              <th style={{ textAlign: "right", padding: "4px 8px" }}>Last Run</th>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Status</th>
              <th style={{ textAlign: "left", padding: "4px 0" }}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {sources.map((src) => {
              const runMeta = statusBySource[src.key] || {};
              const ageH = runMeta.completed_at
                ? (Date.now() - new Date(runMeta.completed_at).getTime()) / 3600000
                : null;
              return (
                <tr key={src.key}>
                  <td>
                    <div style={{ fontWeight: 600 }}>{src.displayName || src.key}</div>
                    <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
                      {src.key} · weight {src.baseWeight ?? src.base_weight ?? "?"}
                    </div>
                  </td>
                  <td style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
                    {src.sourceType || src.source_type || "—"}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {runMeta.player_count ?? "—"}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                    {ageDescriptor(runMeta.completed_at)}
                  </td>
                  <td style={{ color: statusColor(runMeta.status, ageH), fontWeight: 600 }}>
                    {runMeta.status || "no run"}
                  </td>
                  <td style={{ fontSize: "0.7rem", color: "var(--subtext)", maxWidth: 360 }}>
                    {runMeta.error || (src.effectivelyEnabled ? "" : "Disabled by user override")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
