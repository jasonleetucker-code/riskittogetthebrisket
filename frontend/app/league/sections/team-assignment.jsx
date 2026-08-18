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
//
// ─────────────────────────────────────────────────────────────────────
// COMPATIBILITY REPAIR (#815) — owned by the UI lane, not the roster
// lane that made it.
//
// The roster-intelligence lane changed the SERVER contract so a
// degraded snapshot stops rendering as a real empty result, adding
// ``available`` / ``unavailableReason`` / ``rosterScoringAvailable`` and
// per-assignment ``rosterScored``.  This file had to change with it for
// one reason only: it previously printed a CAUSE it had not measured
// ("current season has no rosters yet") for every empty payload, so
// leaving it alone would have kept the defect visible to users while
// the API underneath was correct.
//
// Deliberately scoped to truthfulness: consume the new fields, stop
// asserting an unmeasured cause.  A section-level styled banner was
// written and then REMOVED as presentation — the per-card
// ``rosterScored === false`` note already carries the same fact on
// every affected card.  No layout, styling, component or copy work
// beyond that; the Premium UI treatment of these states is the UI
// lane's call to make.
// ─────────────────────────────────────────────────────────────────────

import { useState } from "react";
import NflTeamLogo from "@/components/ui/NflTeamLogo";
import { Avatar, EmptyCard, nameFor } from "../shared.jsx";

// Machine-readable reason (from ``src/api/team_assignment.py``) → the
// sentence a reader can act on.  Kept as a lookup so an unknown reason
// falls back to an honest generic rather than to a fabricated cause.
const UNAVAILABLE_MESSAGES = {
  no_current_season:
    "Assignment is unavailable — Sleeper has not returned a current season for this league yet. This is a data-availability state, not an empty league.",
  no_rosters:
    "Assignment is unavailable — the current season carries no rosters yet.",
};

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
      {assignment.rosterScored === false ? (
        <div
          className="muted"
          style={{ fontSize: "0.78rem", padding: "4px 0" }}
        >
          Roster-based assignment unavailable — Sleeper&apos;s player
          directory could not be read, so only a configured favorite can
          be shown. This is not a claim that no roster team qualified.
        </div>
      ) : null}
      {teams.length === 0 && assignment.rosterScored !== false ? (
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

  // #815: an empty ``assignments`` list is only a real answer when the
  // server says the section is available.  This branch used to assert a
  // cause it had not measured ("current season has no rosters yet") for
  // every empty payload, including a degraded/seasonless snapshot.
  //
  // ``available === undefined`` is an OLD payload from a server that
  // predates the flag, not a claim of health — treated as unknown so a
  // rolling deploy degrades honestly rather than confidently.
  if (data.available === false) {
    return (
      <EmptyCard
        label="Team Assignment"
        message={UNAVAILABLE_MESSAGES[data.unavailableReason] ||
          "Assignment is currently unavailable. It will return once Sleeper's league data is readable again."}
      />
    );
  }

  const assignments = Array.isArray(data.assignments) ? data.assignments : [];
  if (assignments.length === 0) {
    return (
      <EmptyCard
        label="Team Assignment"
        message={
          data.available === true
            ? "No assignments yet — the current season has no rosters."
            : "Assignment status is unknown for this response. Refresh to retry."
        }
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
