"use client";

// ROS Roster Strength section — first surface of the new ROS engine.
// Reads /api/ros/team-strength and renders one row per team with the
// composite score + lineup vs depth split + a "why" expandable.
// Strictly informational; no value math is exposed beyond what the
// backend already computed.

import { useState } from "react";
import { LoadingState, EmptyState } from "@/components/ui";
import { EmptyCard } from "../shared.jsx";
import { useRosTeamStrength } from "@/lib/ros-data";

function fmtScore(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  return Math.round(Number(v)).toString();
}

function fmtConfidence(v) {
  if (v == null) return "—";
  return `${Math.round(Number(v) * 100)}%`;
}

function TeamRow({ team, expanded, onToggle }) {
  const composite = fmtScore(team.teamRosStrength);
  const starting = fmtScore(team.startingLineupScore);
  const depth = fmtScore(team.benchDepthScore);
  return (
    <>
      <tr
        onClick={onToggle}
        style={{ cursor: "pointer" }}
        title="Click to see starting lineup + depth breakdown"
      >
        <td style={{ textAlign: "right", paddingRight: 8, color: "var(--subtext)" }}>
          {team.rank}
        </td>
        <td style={{ fontWeight: 600 }}>{team.teamName || "—"}</td>
        <td
          style={{
            textAlign: "right",
            fontFamily: "var(--mono)",
            fontWeight: 700,
            color: "var(--cyan)",
          }}
        >
          {composite}
        </td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{starting}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{depth}</td>
        <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
          {team.unmappedPlayerCount > 0 ? `${team.unmappedPlayerCount}` : "0"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={6} style={{ background: "rgba(255,255,255,0.02)", padding: "8px 12px" }}>
            <div style={{ fontSize: "0.74rem" }}>
              <div style={{ marginBottom: 4 }}>
                <strong>Starting lineup ({fmtScore(team.startingLineupScore)}):</strong>{" "}
                {(team.startingLineup || []).map((row, i) => (
                  <span key={i} style={{ marginRight: 12 }}>
                    {row.slot}: {row.canonicalName} ({row.position}, {fmtScore(row.rosValue)})
                  </span>
                ))}
              </div>
              <div style={{ marginBottom: 4 }}>
                <strong>Bench depth ({fmtScore(team.benchDepthScore)}):</strong>{" "}
                {(team.benchDepth || []).map((row, i) => (
                  <span key={i} style={{ marginRight: 12 }}>
                    {row.canonicalName} ({row.position}, {fmtScore(row.depthContribution)})
                  </span>
                ))}
              </div>
              {team.unmappedPlayers && team.unmappedPlayers.length > 0 && (
                <div style={{ marginTop: 4, color: "var(--subtext)" }}>
                  Unmapped (no ROS read): {team.unmappedPlayers.join(", ")}
                  {team.unmappedPlayerCount > team.unmappedPlayers.length
                    ? ` … +${team.unmappedPlayerCount - team.unmappedPlayers.length} more`
                    : ""}
                </div>
              )}
              <div
                style={{
                  marginTop: 8,
                  fontSize: "0.68rem",
                  color: "var(--subtext)",
                }}
              >
                Composite ={" "}
                {Math.round((team.weights?.starting ?? 0.72) * 100)}% starting +{" "}
                {Math.round((team.weights?.depth ?? 0.18) * 100)}% best-ball depth +{" "}
                {Math.round((team.weights?.coverage ?? 0.05) * 100)}% positional coverage +{" "}
                {Math.round((team.weights?.health ?? 0.05) * 100)}% health/availability.
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function RosTeamStrengthSection({ leagueKey }) {
  const { data, loading, error } = useRosTeamStrength(leagueKey);
  const [expanded, setExpanded] = useState(null);

  if (loading) return <LoadingState message="Loading ROS roster strength..." />;
  if (error) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="ROS roster strength unavailable" message={error} />
      </div>
    );
  }
  if (!data) return <EmptyCard label="ROS roster strength" />;
  const teams = Array.isArray(data.teams) ? data.teams : [];
  if (teams.length === 0) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState
          title="ROS data not ready"
          message="The ROS pipeline hasn't produced a team-strength snapshot yet. The next scheduled scrape will populate it; admins can also POST /api/ros/refresh."
        />
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, marginBottom: 4 }}>ROS Roster Strength</div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
        Composite team strength for the rest of the season. 72% starting lineup + 18%
        best-ball depth + 5% positional coverage + 5% health. Read-only contender layer
        — does not affect dynasty values or trade math.
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.84rem" }}>
        <thead>
          <tr style={{ color: "var(--subtext)", fontSize: "0.7rem", textTransform: "uppercase" }}>
            <th style={{ textAlign: "right", padding: "4px 8px 4px 0" }}>#</th>
            <th style={{ textAlign: "left", padding: "4px 0" }}>Team</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Strength</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Starters</th>
            <th style={{ textAlign: "right", padding: "4px 8px" }}>Depth</th>
            <th style={{ textAlign: "right", padding: "4px 0" }}>Unmapped</th>
          </tr>
        </thead>
        <tbody>
          {teams.map((team, i) => (
            <TeamRow
              key={`${team.ownerId || team.rosterId || i}`}
              team={team}
              expanded={expanded === i}
              onToggle={() => setExpanded(expanded === i ? null : i)}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}
