"use client";

import { useTeam } from "@/components/useTeam";

function Stat({ label, value, hint }) {
  return (
    <div className="tc-stat">
      <span className="tc-stat-label">{label}</span>
      <span className="tc-stat-value">{value}</span>
      {hint && <span className="tc-stat-hint">{hint}</span>}
    </div>
  );
}

/**
 * Team Command Header — identity anchor.
 * Structural stub: displays the selected team name and placeholder
 * stats.  Real aggregates wire in at the data-integration step.
 */
export default function TeamCommandHeader() {
  const { selectedTeam, needsSelection } = useTeam();
  const teamName = selectedTeam?.name || (needsSelection ? "Pick your team" : "Loading…");

  return (
    <header className="tc-header panel panel--bare">
      <div className="tc-header-identity">
        <span className="tc-header-eyebrow">My Team</span>
        <h1 className="tc-header-team">{teamName}</h1>
      </div>
      <div className="tc-header-stats" aria-label="Team aggregates">
        <Stat label="Team Value" value="—" />
        <Stat label="Δ 24h" value="—" />
        <Stat label="Δ 7d" value="—" />
        <Stat label="Tiers" value="—" hint="E/H/M/D" />
      </div>
    </header>
  );
}
