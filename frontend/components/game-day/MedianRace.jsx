"use client";

/**
 * MedianRace — the Live Median Race (owner directive 2026-09-26).
 *
 * Section 2 of Game Day, directly after the matchup hero: the whole selected
 * league against this week's median.  The hero answers "how is this matchup
 * going?"; this answers "where is the median going to land, who is likely
 * to beat it, and who is fighting around the cutoff right now?".
 *
 * DISPLAY ONLY.  Reads `payload.medianRace` verbatim — the joint simulation's
 * own M(d) distribution, each team's same-draw beat-median probability and
 * margin, the backend's rank and bubble, movement against the superseded
 * comparable generation.  No median, probability or rank is computed here.
 *
 * Rows are buttons: choosing one switches Game Day to that team through the
 * existing `?team=` mechanism (the same handler the team picker uses), so the
 * hero, the picker and this board stay one state.  The selected row is marked
 * with text and weight, never colour alone.  No categorical probability
 * colours (#1428 is a separate owner decision): order, numbers, words and
 * the existing movement arrows carry the meaning.
 */

import { Movement } from "@/components/ds";
import {
  MEDIAN_RESULT_WORDS,
  currentMedianText,
  formatPct,
  formatPoints,
  formatSignedPoints,
  medianRaceStateText,
} from "@/lib/game-day-view";
import styles from "./median-race.module.css";

function teamLabel(t) {
  return t.teamName || t.displayName || `Roster ${t.rosterId}`;
}

function movementNode(pp) {
  if (typeof pp !== "number" || !Number.isFinite(pp)) return null;
  const magnitude = `${Math.abs(pp).toFixed(1)}pp`;
  return (
    <Movement
      delta={pp}
      format={() => magnitude}
      srLabel={
        pp === 0 ? "unchanged since the last update" : `${pp > 0 ? "up" : "down"} ${magnitude} since the last update`
      }
      className={styles.move}
    />
  );
}

function Summary({ race, final }) {
  const names = new Map(race.teams.map((t) => [t.rosterId, t]));
  return (
    <dl className={styles.summary}>
      {final ? (
        <div>
          <dt>Final median</dt>
          <dd className={styles.bigNum}>{formatPoints(race.finalMedian) ?? "—"}</dd>
        </div>
      ) : (
        <>
          <div>
            <dt>Current median</dt>
            <dd className={styles.bigNum}>{currentMedianText(race) ?? "—"}</dd>
          </div>
          <div>
            <dt>Projected final</dt>
            <dd className={styles.bigNum}>{formatPoints(race.projectedMedianMean) ?? "—"}</dd>
          </div>
          <div>
            <dt>Likely range</dt>
            <dd>
              {race.projectedMedianP10 != null && race.projectedMedianP90 != null
                ? `${formatPoints(race.projectedMedianP10)}–${formatPoints(race.projectedMedianP90)}`
                : "—"}
              {race.projectedMedianP10 != null ? <span className={styles.note}> (80%)</span> : null}
            </dd>
          </div>
          {race.bubble?.length ? (
            <div className={styles.bubble}>
              <dt>On the bubble</dt>
              <dd>
                {race.bubble
                  .map((rid) => names.get(rid))
                  .filter(Boolean)
                  .map((t) => `${teamLabel(t)} ${formatPct(t.beatMedianPct)}`)
                  .join(" · ")}
              </dd>
            </div>
          ) : null}
        </>
      )}
    </dl>
  );
}

function Row({ t, selected, final, onSelect }) {
  const pct = formatPct(t.beatMedianPct);
  const label = teamLabel(t);
  const outcome = final ? MEDIAN_RESULT_WORDS[t.finalResult] || "—" : pct ?? "—";
  const accessible = [
    `Rank ${t.rank}`,
    label,
    final ? outcome : pct ? `${pct} to beat the median` : "chance to beat the median unavailable",
    `score now ${formatPoints(final ? t.finalScore : t.scoreNow) ?? "unavailable"}`,
    !final && t.projectedMean != null ? `projected ${formatPoints(t.projectedMean)}` : null,
    !final && typeof t.movementPp === "number" && Number.isFinite(t.movementPp)
      ? t.movementPp === 0
        ? "unchanged since the last update"
        : `${t.movementPp > 0 ? "up" : "down"} ${Math.abs(t.movementPp).toFixed(1)}pp since the last update`
      : null,
    selected ? "currently viewing" : null,
  ]
    .filter(Boolean)
    .join(", ");
  const cells = (
    <>
      <span className={styles.rank} aria-hidden="true">
        {t.rank}
      </span>
      <span className={styles.team} aria-hidden="true">
        <span className={styles.teamName}>{label}</span>
        {t.displayName && t.displayName !== label ? (
          <span className={styles.manager}>{t.displayName}</span>
        ) : null}
        {selected ? <span className={styles.viewing}>Viewing</span> : null}
      </span>
      <span className={styles.num} aria-hidden="true" data-col="now">
        {formatPoints(final ? t.finalScore : t.scoreNow) ?? "—"}
      </span>
      {!final ? (
        <>
          <span className={styles.num} aria-hidden="true" data-col="projected">
            {formatPoints(t.projectedMean) ?? "—"}
          </span>
          <span className={styles.num} aria-hidden="true" data-col="edge">
            {formatSignedPoints(t.medianMarginMean) ?? "—"}
          </span>
        </>
      ) : null}
      <span className={styles.pct} aria-hidden="true" data-col="beat">
        {outcome}
        {!final ? movementNode(t.movementPp) : null}
      </span>
    </>
  );
  return (
    <li className={`${styles.row} ${selected ? styles.selected : ""}`.trim()} data-roster-id={t.rosterId}>
      {t.ownerId && onSelect ? (
        <button
          type="button"
          className={styles.rowButton}
          aria-label={accessible}
          aria-current={selected ? "true" : undefined}
          onClick={() => onSelect(t.ownerId)}
        >
          {cells}
        </button>
      ) : (
        <div className={styles.rowButton} role="group" aria-label={accessible}>
          {cells}
        </div>
      )}
    </li>
  );
}

export default function MedianRace({ race, week, onSelectTeam }) {
  if (!race || !Array.isArray(race.teams)) return null;
  const final = race.state === "final";
  const stateText = medianRaceStateText(race);
  const showRows = race.state !== "not_applicable";
  return (
    <section className={styles.race} aria-labelledby="median-race-title" data-median-race={race.state}>
      <header className={styles.head}>
        <h2 id="median-race-title" className={styles.title}>
          {final ? "Median race — final" : "Live median race"}
        </h2>
        {week ? <span className={styles.week}>Week {week}</span> : null}
      </header>
      {stateText ? <p className={styles.note}>{stateText}</p> : null}
      {race.state !== "not_applicable" ? <Summary race={race} final={final} /> : null}
      {showRows ? (
        <>
          <div className={styles.columns} aria-hidden="true">
            <span>#</span>
            <span>Team</span>
            <span className={styles.num}>{final ? "Final" : "Now"}</span>
            {!final ? (
              <>
                <span className={styles.num}>Projected</span>
                <span className={styles.num}>vs median</span>
              </>
            ) : null}
            <span className={styles.num}>{final ? "Result" : "Beat median"}</span>
          </div>
          <ol className={`${styles.list} ${final ? styles.finalList : ""}`.trim()} aria-label={final ? "Teams by final score" : "Teams ranked by chance to beat the median"}>
            {race.teams.map((t) => (
              <Row
                key={t.rosterId}
                t={t}
                final={final}
                selected={t.rosterId === race.selectedRosterId}
                onSelect={onSelectTeam}
              />
            ))}
          </ol>
        </>
      ) : null}
    </section>
  );
}
