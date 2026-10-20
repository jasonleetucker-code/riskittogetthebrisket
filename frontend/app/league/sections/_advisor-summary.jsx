"use client";

// The consolidated trade summary (directive §12: make clear who sends, who
// receives and the full structure).  The same team-by-team layout for any
// team count: every team's sends with their destination (→) and receives
// with their origin (←).  Text arrows, so no SVG is needed on a phone.
// Labels only — no values.

import { tradeSummary } from "@/lib/trade-advisor";
import styles from "./trade-advisor.module.css";

function Items({ items, empty = "Nothing yet" }) {
  if (!items.length) return <p className={`${styles.summaryList} ${styles.summaryNone}`}>{empty}</p>;
  return (
    <ul className={styles.summaryList}>
      {items.map((it) => (
        <li key={it.key}>
          {it.label} <span className={styles.summaryRoute}>{it.route}</span>
        </li>
      ))}
    </ul>
  );
}

/** One team's block; also used by the result's per-team panel. */
export function TeamFlows({ team, headingLevel = 3, showName = true }) {
  const H = `h${headingLevel}`;
  const S = `h${Math.min(6, headingLevel + 1)}`;
  return (
    <div className={styles.summaryTeam} data-testid={`advisor-flows-${team.rosterId}`}>
      {showName ? (
        <H className={styles.summaryTeamName}>
          {team.name}
          {team.isYou ? " (your team)" : ""}
        </H>
      ) : null}
      <div className={styles.summaryGrid}>
        <div className={styles.summaryCol}>
          <S className={styles.summaryHead}>Sends</S>
          <Items
            items={team.sends.map((s) => ({
              key: s.id,
              label: s.label,
              route: `→ ${s.toName || "choose a team"}`,
            }))}
          />
        </div>
        <div className={styles.summaryCol}>
          <S className={styles.summaryHead}>Receives</S>
          <Items items={team.receives.map((r) => ({ key: r.id, label: r.label, route: `← ${r.fromName}` }))} />
        </div>
      </div>
    </div>
  );
}

export function AdvisorSummary({ state, teams }) {
  const summary = tradeSummary(state, teams);
  return (
    <div className={styles.summaryTeams} data-testid="advisor-summary" data-count={summary.teams.length}>
      {summary.teams.map((t) => (
        <TeamFlows key={t.rosterId} team={t} />
      ))}
    </div>
  );
}
