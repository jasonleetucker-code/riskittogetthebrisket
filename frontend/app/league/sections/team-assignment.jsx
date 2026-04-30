"use client";

// TeamAssignmentSection — "Team Assignment" tab on /league.
//
// Renders one card per fantasy team showing:
//   * Manager display name + avatar
//   * 1–3 NFL teams (favorite + roster-based qualifiers)
//   * Each NFL team chip with logo, full name, and tag
//     ("Favorite" / "Roster-Based" with point total)
//   * Optional "Show Scoring Breakdown" toggle that expands a
//     per-player point list per NFL team
//
// Reads strictly from ``sections.teamAssignment`` of the public
// contract.  Server-computed by ``src/api/team_assignment.py``;
// re-runs whenever the contract is re-built (per-request, cached
// at the public-league snapshot layer for 30 min).

import { useState } from "react";
import NflTeamLogo from "@/components/ui/NflTeamLogo";
import { Avatar, EmptyCard, nameFor } from "../shared.jsx";

function NflTeamChip({ team }) {
  return (
    <div
      className="card"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 12px",
        marginBottom: 6,
        borderLeft: team.isFavorite
          ? "3px solid var(--cyan)"
          : "3px solid var(--green)",
      }}
    >
      <NflTeamLogo team={team.abbr} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: "0.92rem" }}>
          {team.display}
        </div>
        <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
          {team.isFavorite ? (
            <span>
              <span
                style={{
                  color: "var(--cyan)",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Favorite
              </span>
              {Number.isFinite(Number(team.score)) && team.score > 0 ? (
                <span style={{ marginLeft: 8 }}>
                  · {team.score} pts from roster
                </span>
              ) : null}
            </span>
          ) : (
            <span>
              <span
                style={{
                  color: "var(--green)",
                  fontWeight: 700,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}
              >
                Roster-Based
              </span>
              <span style={{ marginLeft: 8 }}>· {team.score} pts</span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

function ScoringBreakdown({ team }) {
  const contributors = Array.isArray(team.contributors) ? team.contributors : [];
  if (!contributors.length) {
    return (
      <div
        className="muted"
        style={{ fontSize: "0.74rem", padding: "6px 10px" }}
      >
        No roster contribution.
      </div>
    );
  }
  // Sort by points desc so the biggest signals show first.
  const sorted = [...contributors].sort(
    (a, b) => (Number(b.points) || 0) - (Number(a.points) || 0),
  );
  return (
    <div
      style={{
        padding: "8px 12px 4px 40px",
        borderLeft: "1px dashed var(--border)",
        marginLeft: 14,
        marginBottom: 8,
      }}
    >
      <div
        style={{
          fontWeight: 700,
          fontSize: "0.74rem",
          color: "var(--subtext)",
          marginBottom: 4,
        }}
      >
        {team.display} — {team.score} pts
      </div>
      {sorted.map((c, idx) => (
        <div
          key={idx}
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontSize: "0.74rem",
            padding: "2px 0",
          }}
        >
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>
            {c.player}
          </span>
          <span style={{ fontFamily: "var(--mono)", marginLeft: 8 }}>
            <span
              style={{
                color: c.points > 0 ? "var(--green)" : "var(--subtext)",
              }}
            >
              +{c.points}
            </span>{" "}
            <span className="muted">{c.reason}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function ManagerCard({ assignment, managers, expanded, onToggle }) {
  const teams = Array.isArray(assignment.nflTeams) ? assignment.nflTeams : [];
  const hasContrib = teams.some(
    (t) => Array.isArray(t.contributors) && t.contributors.length,
  );
  return (
    <div
      className="card"
      style={{ marginBottom: 12, padding: "12px 14px" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 8,
        }}
      >
        <Avatar
          managers={managers}
          ownerId={assignment.ownerId}
          size={26}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 700, fontSize: "0.96rem" }}>
            {nameFor(managers, assignment.ownerId) || assignment.displayName}
          </div>
          {assignment.teamName ? (
            <div
              style={{
                fontSize: "0.7rem",
                color: "var(--subtext)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {assignment.teamName}
            </div>
          ) : null}
        </div>
        {hasContrib ? (
          <button
            type="button"
            onClick={onToggle}
            className="button"
            style={{
              fontSize: "0.7rem",
              padding: "3px 8px",
            }}
            title="Toggle per-player scoring breakdown"
          >
            {expanded ? "Hide breakdown" : "Show breakdown"}
          </button>
        ) : null}
      </div>
      {teams.length === 0 ? (
        <div
          className="muted"
          style={{ fontSize: "0.78rem", padding: "4px 0" }}
        >
          No NFL team assignments yet — favorite not configured and no
          roster team passed the threshold.
        </div>
      ) : (
        teams.map((t) => (
          <div key={t.abbr}>
            <NflTeamChip team={t} />
            {expanded ? <ScoringBreakdown team={t} /> : null}
          </div>
        ))
      )}
    </div>
  );
}

export default function TeamAssignmentSection({ data, managers }) {
  const [expandedOwner, setExpandedOwner] = useState(null);

  if (!data) {
    return (
      <EmptyCard
        label="Team Assignment"
        message="Section not loaded yet — refresh to retry."
      />
    );
  }

  const assignments = Array.isArray(data.assignments) ? data.assignments : [];
  if (assignments.length === 0) {
    return (
      <EmptyCard
        label="Team Assignment"
        message="No assignments available — current season has no rosters yet."
      />
    );
  }

  const threshold = data.config?.thresholds?.assignmentMinPoints ?? 15;

  return (
    <div>
      <div
        style={{
          fontSize: "0.72rem",
          color: "var(--subtext)",
          marginBottom: 12,
          lineHeight: 1.5,
        }}
      >
        Each manager is mapped to 1–3 NFL teams.  The first team is
        the manager's declared favorite from{" "}
        <code style={{ fontSize: "0.7rem" }}>config/team_assignment.json</code>.
        Additional teams are derived from roster composition: starting
        QBs, primary skill-position players, rookies with high draft
        capital, and (if IDP is enabled) starting defenders.  Teams
        scoring at least <strong>{threshold} pts</strong> qualify; max
        3 NFL teams per manager.  Click "Show breakdown" on any
        manager to see per-player point contributions.
      </div>

      {assignments.map((a) => (
        <ManagerCard
          key={a.ownerId}
          assignment={a}
          managers={managers}
          expanded={expandedOwner === a.ownerId}
          onToggle={() =>
            setExpandedOwner(expandedOwner === a.ownerId ? null : a.ownerId)
          }
        />
      ))}
    </div>
  );
}
