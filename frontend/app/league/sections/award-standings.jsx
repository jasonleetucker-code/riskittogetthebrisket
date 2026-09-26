"use client";

// Expand standings — the ranking BEHIND one award (owner directive 2026-09-26).
//
// The collapsed card stays concise (the leader / top three). Expanding shows
// the award's canonical ranking for the current season, up to twelve rows,
// exactly as the backend published it in `standings` — this component
// sorts nothing, computes no metric and invents no rank. Fewer than twelve
// qualifying candidates means fewer rows, never padding.
//
// A row can be measured and still not be eligible to WIN (a season-scoped
// owner competition rule, e.g. 2026 Waiver King): it keeps its metric rank
// and value and carries its eligibility label; `awardRank` is the award
// order among eligible rows only.
//
// Award HISTORY (every season's winners and finalists) is a different
// question and stays on the award cards; this answers "who is where in this
// race right now".

import { useId, useState } from "react";

import { PlayerNameButton } from "@/components/ds/PlayerNameButton";

import styles from "./awards.module.css";

const ENTITY_NOUN = {
  player: ["player", "players"],
  manager: ["manager", "managers"],
  team: ["team", "teams"],
  nfl_team: ["NFL team", "NFL teams"],
  event: ["result", "results"],
};

function countText(entity, shown, total) {
  const [one, many] = ENTITY_NOUN[entity] || ENTITY_NOUN.manager;
  if (Number.isFinite(total) && total > shown) return `Top ${shown} of ${total} ${many}`;
  return `${shown} qualifying ${shown === 1 ? one : many}`;
}

function RowIdentity({ entity, row, onNavigate }) {
  const v = row.value || {};
  if (entity === "player") {
    const meta = [v.position, v.team, row.displayName ? `rostered by ${row.displayName}` : ""]
      .filter(Boolean)
      .join(" · ");
    return (
      <span className={styles.standingsIdentity}>
        <PlayerNameButton
          name={v.playerName || "Unknown player"}
          playerId={v.playerId || undefined}
          className={styles.standingsName}
        />
        {meta && <span className={styles.standingsMeta}>{meta}</span>}
      </span>
    );
  }
  if (entity === "nfl_team") {
    return (
      <span className={styles.standingsIdentity}>
        <span className={styles.standingsName}>{row.displayName}</span>
      </span>
    );
  }
  const meta = [row.teamName, row.detail].filter(Boolean).join(" · ");
  return (
    <span className={styles.standingsIdentity}>
      {row.ownerId && typeof onNavigate === "function" ? (
        <button
          type="button"
          className={`${styles.standingsName} ${styles.standingsOwner}`}
          onClick={() => onNavigate("franchise", { owner: row.ownerId })}
        >
          {row.displayName}
        </button>
      ) : (
        <span className={styles.standingsName}>{row.displayName}</span>
      )}
      {meta && <span className={styles.standingsMeta}>{meta}</span>}
    </span>
  );
}

export function AwardStandings({ award, formatMetric, onNavigate }) {
  const [open, setOpen] = useState(false);
  const listId = `award-standings-${useId().replace(/:/g, "")}`;
  const rows = Array.isArray(award?.standings) ? award.standings : null;
  if (!rows || rows.length === 0) return null;
  const entity = award.standingsEntity || "manager";
  const anyIneligible = rows.some((r) => r.eligible === false);
  const label = String(award.label || "Award").replace(/ Race$/, "");
  return (
    <div className={styles.standings} data-award-standings={award.key}>
      <button
        type="button"
        className={styles.standingsToggle}
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((o) => !o)}
        data-html2canvas-ignore
      >
        <span>{open ? "Collapse standings" : "Expand standings"}</span>
        <span className={styles.standingsCount}>
          {countText(entity, rows.length, award.standingsTotal)}
        </span>
      </button>
      <ol
        id={listId}
        className={styles.standingsList}
        aria-label={`${label} standings`}
        hidden={!open}
      >
        {rows.map((row) => (
          <li
            key={`${row.rank}-${row.ownerId || ""}-${row.value?.playerId || row.displayName}`}
            className={styles.standingsRow}
            data-eligible={row.eligible === false ? "false" : "true"}
          >
            <span className={styles.standingsRank}>
              {row.tied ? `T${row.rank}` : row.rank}
            </span>
            <RowIdentity entity={entity} row={row} onNavigate={onNavigate} />
            <span className={styles.standingsMetric}>{formatMetric(award.key, row.value || {})}</span>
            {(row.eligible === false || (anyIneligible && row.awardRank != null)) && (
              <span className={styles.standingsFlags}>
                {row.eligible === false ? (
                  <span className={styles.standingsIneligible}>
                    {row.ineligibleLabel || "Ineligible for this award"}
                  </span>
                ) : (
                  <span className={styles.standingsAwardRank}>Award rank {row.awardRank}</span>
                )}
              </span>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

export default AwardStandings;
