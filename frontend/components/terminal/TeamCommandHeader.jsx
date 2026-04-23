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
 *
 * Label logic distinguishes four states so the header never displays
 * a perpetual "Loading…" that could mask a real data error:
 *   - needsSelection  → "Pick your team"  (data loaded, user must pick)
 *   - selectedTeam    → team name         (resolved selection)
 *   - loading         → "Loading team…"   (fetch in flight)
 *   - else            → "No team data"    (loaded, but no teams and
 *                                          nothing selected — league
 *                                          fetch failed, empty roster
 *                                          set, or private-data off)
 */
export default function TeamCommandHeader() {
  const { selectedTeam, needsSelection, loading, privateDataEnabled } = useTeam();

  let teamName;
  let nameVariant = "ready";
  if (needsSelection) {
    teamName = "Pick your team";
    nameVariant = "needs";
  } else if (selectedTeam?.name) {
    teamName = selectedTeam.name;
  } else if (loading) {
    teamName = "Loading team…";
    nameVariant = "loading";
  } else if (!privateDataEnabled) {
    teamName = "Team data unavailable";
    nameVariant = "error";
  } else {
    teamName = "No team data";
    nameVariant = "error";
  }

  return (
    <header className="tc-header panel panel--bare">
      <div className="tc-header-identity">
        <span className="tc-header-eyebrow">My Team</span>
        <h1 className={`tc-header-team tc-header-team--${nameVariant}`}>{teamName}</h1>
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
