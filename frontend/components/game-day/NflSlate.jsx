"use client";

/**
 * NflSlate — section 3 of Game Day: every NFL game this week, in the
 * backend's chronological order (`nflSlate.games`, never re-sorted), one
 * compact row each.
 *
 * Per game, from the payload:
 *   status     phase / period / clockSeconds (observed live feed) or the
 *              schedule's state, named as such — `gameStatusText`
 *   teams      awayTeam @ homeTeam
 *   relevance  how many of this matchup's players are in it, per side, and
 *              whether it is one of team.outcome.gameLeverage's top three
 *              (backend order) — emphasis without reordering
 *   detail     (expandable) each player's points scored, remaining
 *              projection (projectedRemaining / remainingBasis, or the
 *              named reason it is unavailable) and final-lineup chance,
 *              plus the game's two conditional win chances
 *
 * No per-game point totals are summed here: a raw sum of roster
 * projections is not best-ball contribution (owner contract §C).
 * Expansion state lives in this component, so a background refresh that
 * re-renders the rows keeps whatever the reader opened.
 */

import { Suspense, lazy, useCallback, useMemo, useState } from "react";
import { NflTeamLogo } from "@/components/ui";
import { SkeletonText } from "@/components/ds";
import { formatPct, gameLabel, gamePhaseKind, gameStatusText, playerIndex } from "@/lib/game-day-view";
import styles from "./game-day.module.css";

// The per-game player table (DataTable) loads on first expansion: every row
// starts collapsed, so it is never needed for the first paint.
const GamePlayers = lazy(() => import("./GamePlayers"));

export default function NflSlate({ payload }) {
  const slate = payload?.nflSlate;
  const [open, setOpen] = useState(() => new Set());
  const toggle = useCallback((gameId) => {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(gameId)) next.delete(gameId);
      else next.add(gameId);
      return next;
    });
  }, []);
  const index = useMemo(() => playerIndex(payload), [payload]);
  const leverage = useMemo(() => {
    const out = new Map();
    const rows = (payload?.team?.outcome?.gameLeverage || []).filter(
      (r) => typeof r.leverage === "number",
    );
    rows.forEach((r, i) => out.set(r.gameId, { ...r, rank: i }));
    return out;
  }, [payload]);

  if (!slate) return null;
  const teamName = payload?.team?.displayName;
  const opponentName = payload?.opponent?.displayName;

  return (
    <section className={styles.section} aria-labelledby="game-day-slate-title">
      <div className={styles.sectionHead}>
        <h2 id="game-day-slate-title" className={styles.sectionTitle}>
          NFL slate
        </h2>
        <span className={styles.sectionHint}>Kickoff order · key games marked</span>
      </div>
      {slate.scheduleState !== "available" ? (
        <p className={styles.note}>
          NFL schedule unavailable
          {slate.scheduleUnavailableReason ? ` (${slate.scheduleUnavailableReason})` : ""}.
        </p>
      ) : (
        <ul className={styles.slate}>
          {slate.games.map((game) => {
            const mine = game.players.filter((p) => p.side === "team").length;
            const theirs = game.players.filter((p) => p.side === "opponent").length;
            const relevant = mine + theirs > 0;
            const lev = leverage.get(game.gameId);
            const key = lev && lev.rank < 3;
            const kind = gamePhaseKind(game);
            const detailId = `game-day-slate-${game.gameId}`;
            const expanded = open.has(game.gameId);
            const rowClass = [styles.gameRow, key ? styles.keyGame : "", relevant ? "" : styles.gameIdle]
              .filter(Boolean)
              .join(" ");
            return (
              <li key={game.gameId} className={rowClass} data-game-id={game.gameId}>
                <div className={styles.gameLine}>
                  <span
                    className={`${styles.gameStatus} ${kind === "live" ? styles.gameLiveStatus : ""}`.trim()}
                  >
                    {gameStatusText(game)}
                  </span>
                  <span className={styles.gameTeams}>
                    <NflTeamLogo team={game.awayTeam} size={16} showAbbr />
                    <span className={styles.gameAt}>@</span>
                    <NflTeamLogo team={game.homeTeam} size={16} showAbbr />
                  </span>
                  <span className={styles.gameRelevance}>
                    {key ? <span className={styles.heroEyebrow}>Key game</span> : null}
                    {relevant ? (
                      <span>
                        {mine} yours · {theirs} theirs
                      </span>
                    ) : (
                      <span>No players in this matchup</span>
                    )}
                    {relevant ? (
                      <button
                        type="button"
                        className={styles.gameToggle}
                        aria-expanded={expanded}
                        aria-controls={detailId}
                        onClick={() => toggle(game.gameId)}
                      >
                        {expanded ? "Hide players" : "Players"}
                        <span className="ds-visually-hidden"> in {gameLabel(game)}</span>
                      </button>
                    ) : null}
                  </span>
                </div>
                {relevant ? (
                  <div id={detailId} className={styles.gameDetail} hidden={!expanded}>
                    {expanded ? (
                      <>
                        {lev ? (
                          <p className={styles.note}>
                            Win chance {formatPct(lev.winPctWhenGameFavorsTeam) ?? "—"} if this game
                            goes your way, {formatPct(lev.winPctWhenGameFavorsOpponent) ?? "—"} if it
                            goes theirs.
                          </p>
                        ) : null}
                        <Suspense fallback={<SkeletonText lines={2} />}>
                          <GamePlayers
                            game={game}
                            index={index}
                            teamName={teamName}
                            opponentName={opponentName}
                          />
                        </Suspense>
                      </>
                    ) : null}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
      {slate.byeWeek?.length > 0 ? (
        <p className={styles.slateFoot}>On bye: {slate.byeWeek.map((p) => p.name).join(", ")}.</p>
      ) : null}
      {slate.unattributed?.length > 0 ? (
        <p className={styles.slateFoot}>
          No NFL game on file for: {slate.unattributed.map((p) => p.name).join(", ")}.
        </p>
      ) : null}
    </section>
  );
}
