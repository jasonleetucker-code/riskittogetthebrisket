"use client";

// ROS Data Health — diagnostic view of the ROS scrape pipeline.
// Reads /api/ros/health (a combined snapshot of per-source status +
// aggregate + sims + team-strength) and /api/ros/sources for the
// registry, then renders top-level pipeline health plus per-source
// last-run state.  Includes a "scrape now" button hitting POST
// /api/ros/refresh (admin-gated).

import { useEffect, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { fetchRosSources, fetchRosHealth } from "@/lib/ros-data";

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

function ageFromSeconds(seconds) {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

function ageColor(seconds, thresholds = { green: 6 * 3600, amber: 24 * 3600 }) {
  if (seconds == null) return "var(--subtext)";
  if (seconds < thresholds.green) return "var(--green)";
  if (seconds < thresholds.amber) return "var(--amber)";
  return "var(--red)";
}

function statusColor(status, ageHours) {
  if (status === "failed") return "var(--red)";
  if (status === "partial") return "var(--amber)";
  if (ageHours != null && ageHours > 12) return "var(--amber)";
  return "var(--green)";
}

export default function RosDataHealthPage() {
  const [sources, setSources] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);

  const load = async () => {
    try {
      const [src, hl] = await Promise.all([fetchRosSources(), fetchRosHealth()]);
      setSources(src.sources || []);
      setHealth(hl);
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

  const statusBySource = (health?.sources || {});
  const aggregate = health?.aggregate || {};
  const teamStrength = health?.teamStrength || {};
  const sims = health?.sims || {};

  const statTile = (label, value, subtext, color) => (
    <div
      style={{
        flex: 1,
        minWidth: 140,
        padding: "10px 12px",
        background: "rgba(255, 255, 255, 0.02)",
        border: "1px solid rgba(255, 255, 255, 0.05)",
        borderRadius: 6,
      }}
    >
      <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: "1.05rem", fontWeight: 700, marginTop: 2, color: color || "inherit" }}>
        {value}
      </div>
      {subtext && (
        <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>
          {subtext}
        </div>
      )}
    </div>
  );

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
            Last rebuilt: {ageDescriptor(health?.rebuiltAt)} ·{" "}
            Overall freshness: {health?.freshness || "unknown"}
          </span>
        </div>
        {error && (
          <div style={{ color: "var(--red)", fontSize: "0.78rem", marginBottom: 8 }}>
            {error}
          </div>
        )}

        {/* Pipeline health summary tiles */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginBottom: 14 }}>
          {statTile(
            "Aggregate Players",
            aggregate.playerCount?.toLocaleString() ?? "—",
            `${aggregate.sourceCount ?? "?"} sources · ${ageFromSeconds(aggregate.ageSeconds)}`,
            ageColor(aggregate.ageSeconds),
          )}
          {statTile(
            "Team Strength",
            teamStrength.teamCount ?? "—",
            teamStrength.teamCount
              ? `${teamStrength.unmappedTotal ?? 0} unmapped roster slots`
              : "no snapshot",
            teamStrength.teamCount ? "var(--green)" : "var(--red)",
          )}
          {statTile(
            "Playoff Sim",
            sims.playoffExists ? "cached" : "missing",
            ageFromSeconds(sims.playoffAgeSeconds),
            sims.playoffExists ? ageColor(sims.playoffAgeSeconds) : "var(--red)",
          )}
          {statTile(
            "Championship Sim",
            sims.championshipExists ? "cached" : "missing",
            ageFromSeconds(sims.championshipAgeSeconds),
            sims.championshipExists ? ageColor(sims.championshipAgeSeconds) : "var(--red)",
          )}
        </div>
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

        {teamStrength.perTeam && teamStrength.perTeam.length > 0 && (
          <div style={{ marginTop: 22 }}>
            <h3 style={{ fontSize: "0.86rem", marginBottom: 6 }}>
              Roster coverage
            </h3>
            <p className="muted" style={{ fontSize: "0.7rem", marginTop: 0, marginBottom: 8 }}>
              How many roster slots on each team aren&apos;t covered by any
              ROS source.  High counts usually mean deep IDPs / aging
              veterans below the cutoff of all six adapters.
            </p>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
              <thead>
                <tr style={{ color: "var(--subtext)", fontSize: "0.66rem", textTransform: "uppercase" }}>
                  <th style={{ textAlign: "left", padding: "3px 0" }}>Team</th>
                  <th style={{ textAlign: "right", padding: "3px 8px" }}>Strength</th>
                  <th style={{ textAlign: "right", padding: "3px 0" }}>Unmapped</th>
                </tr>
              </thead>
              <tbody>
                {teamStrength.perTeam
                  .slice()
                  .sort((a, b) => (b.unmappedPlayerCount || 0) - (a.unmappedPlayerCount || 0))
                  .map((t) => (
                    <tr key={t.teamName}>
                      <td>{t.teamName || "—"}</td>
                      <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                        {t.teamRosStrength?.toFixed(1) ?? "—"}
                      </td>
                      <td style={{
                        textAlign: "right",
                        fontFamily: "var(--mono)",
                        color: (t.unmappedPlayerCount ?? 0) > 3 ? "var(--amber)" : "var(--subtext)",
                      }}>
                        {t.unmappedPlayerCount ?? 0}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
