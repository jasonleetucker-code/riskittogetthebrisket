"use client";

// The consolidated trade summary (directive Phase 4: "the user should never
// have to guess which players they are sending or receiving").  Two teams
// read as You send / You receive; 3-4 teams list what every team sends and
// receives, with destinations.  Labels only — no values.

import { tradeSummary } from "@/lib/trade-advisor";
import styles from "./trade-advisor.module.css";

function Names({ items, empty = "Nothing yet" }) {
  if (!items.length) return <p className={`${styles.summaryList} ${styles.summaryNone}`}>{empty}</p>;
  return (
    <ul className={styles.summaryList}>
      {items.map((text, i) => (
        <li key={`${text}-${i}`}>{text}</li>
      ))}
    </ul>
  );
}

export function AdvisorSummary({ state, teams, youLabel = "You" }) {
  const summary = tradeSummary(state, teams);
  const plural = youLabel === "You";
  if (state.teamCount === 2) {
    return (
      <div className={styles.summary} data-testid="advisor-summary">
        <div className={styles.summaryCol}>
          <h3 className={styles.summaryHead}>{youLabel} {plural ? "send" : "sends"}</h3>
          <Names items={summary.youSend} />
        </div>
        <div className={styles.summaryCol}>
          <h3 className={styles.summaryHead}>{youLabel} {plural ? "receive" : "receives"}</h3>
          <Names items={summary.youReceive} />
        </div>
      </div>
    );
  }
  return (
    <div data-testid="advisor-summary">
      {summary.teams.map((t) => (
        <div key={t.rosterId} className={styles.summaryTeam}>
          <h3 className={styles.summaryTeamName}>
            {t.name}
            {t.isYou ? " (your team)" : ""}
          </h3>
          <div className={styles.summaryGrid}>
            <div className={styles.summaryCol}>
              <h4 className={styles.summaryHead}>Sends</h4>
              <Names items={t.sends.map((s) => `${s.label} → ${s.toName || "choose a team"}`)} />
            </div>
            <div className={styles.summaryCol}>
              <h4 className={styles.summaryHead}>Receives</h4>
              <Names items={t.receives.map((r) => `${r.label} ← ${r.fromName}`)} />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
