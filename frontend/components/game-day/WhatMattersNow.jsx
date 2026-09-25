"use client";

/**
 * WhatMattersNow — section 2 of Game Day: three to five evidence-backed
 * items, each read from one backend field:
 *
 *   game         team.outcome.gameLeverage[] (backend order, strongest
 *                first): win chance when that game goes each way
 *   could enter  team.players[].finalLineupPct for players outside the
 *                current (or, pregame, the illustrative) lineup
 *   at risk      a currently counting player whose finalLineupPct < 100
 *   opponent     the opponent's likeliest "could enter" player
 *
 * Items the payload cannot support are not rendered; when none are, the
 * section says so in one line instead of disappearing into a blank.
 */

import { whatMattersNow } from "@/lib/game-day-view";
import styles from "./game-day.module.css";

const KIND_LABEL = {
  game: "Key game",
  "could-enter": "Could enter",
  "at-risk": "Could be displaced",
  opponent: "Opponent",
};

export default function WhatMattersNow({ payload }) {
  if (!payload || payload.mode === "final") return null;
  const items = whatMattersNow(payload);
  return (
    <section className={styles.section} aria-labelledby="game-day-matters-title">
      <div className={styles.sectionHead}>
        <h2 id="game-day-matters-title" className={styles.sectionTitle}>
          What matters now
        </h2>
      </div>
      {items.length ? (
        <ol className={styles.matters}>
          {items.map((item) => (
            <li key={item.key} className={styles.mattersItem}>
              <span className={styles.mattersTitle}>
                {item.title}
                {item.meta ? <span className={styles.muted}> · {item.meta}</span> : null}
              </span>
              <span className={styles.mattersKind}>
                {KIND_LABEL[item.kind]}
                {item.status ? ` · ${item.status}` : ""}
              </span>
              <span className={styles.mattersDetail}>{item.detail}</span>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.note}>
          Nothing to single out yet: the simulation has not published game leverage or lineup
          chances for this matchup.
        </p>
      )}
    </section>
  );
}
