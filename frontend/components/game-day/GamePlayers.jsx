/**
 * GamePlayers — one NFL game's players in this matchup (the expandable
 * detail of a Game Day slate row). Loaded on first expansion.
 *
 * Per player, verbatim from the payload: points scored (pointsScored),
 * remaining projection (projectedRemaining — or, when it is withheld, the
 * named progressUnavailableReason) and the final-lineup chance
 * (finalLineupPct from the side's player row).
 */

import { useMemo } from "react";
import { DataTable, PlayerNameButton } from "@/components/ds";
import {
  formatLineupPct,
  formatPoints,
  gameLabel,
  playerStateText,
  positionLabel,
  reasonText,
} from "@/lib/game-day-view";
import styles from "./game-day.module.css";

function remainingCell(player, detail, pending) {
  if (player.state === "completed" || player.state === "inactive") return "None left";
  // PENDING deliberately withholds projectedRemaining (matchup_intel):
  // not computed yet is not "no projection".
  if (pending && detail?.projectedRemaining == null) return "Computing";
  const value = formatPoints(player.projectedRemaining);
  if (value !== null) return value;
  const why = reasonText(detail?.progressUnavailableReason);
  if (why) {
    return (
      <span>
        Paused<span className={styles.numNote}>{why}</span>
      </span>
    );
  }
  if (player.state === "unknown") return "Unknown";
  return "No projection";
}

function scoredCell(player) {
  if (player.state === "not_started") return "—";
  return formatPoints(player.pointsScored) ?? "Unavailable";
}

export default function GamePlayers({ game, index, teamName, opponentName, pending = false }) {
  const rows = useMemo(
    () =>
      [...game.players]
        .sort((a, b) => (a.side === b.side ? 0 : a.side === "team" ? -1 : 1))
        .map((p) => ({ ...p, detail: index.get(p.playerId)?.player || null })),
    [game.players, index],
  );
  // Four columns so the table fits a phone without a sideways scroll
  // region: the fantasy side and game status ride in the player cell.
  const columns = [
    {
      key: "name",
      header: "Player",
      render: (p) => (
        <span>
          <PlayerNameButton name={p.name} playerId={p.playerId} />
          {positionLabel(p) ? <span className={styles.muted}> · {positionLabel(p)}</span> : null}
          <span className={styles.numNote}>
            {p.side === "team" ? teamName || "Selected team" : opponentName || "Opponent"} ·{" "}
            {playerStateText(p.state)}
          </span>
        </span>
      ),
    },
    { key: "scored", header: "Scored", numeric: true, render: (p) => scoredCell(p) },
    {
      key: "remaining",
      header: "Left",
      headerInfo:
        "Projected points still to come: the weekly projection locked at kickoff (the preseason average when there is no weekly line) times the share of regulation left on the observed game clock. A player whose game has not started keeps his full projection.",
      headerInfoLabel: "Projected points left",
      numeric: true,
      render: (p) => remainingCell(p, p.detail, pending),
    },
    {
      key: "lineup",
      header: "Final lineup",
      numeric: true,
      render: (p) => formatLineupPct(p.detail?.finalLineupPct) ?? "—",
    },
  ];
  return (
    <DataTable
      caption={`${gameLabel(game)} players in this matchup`}
      columns={columns}
      rows={rows}
      rowKey="playerId"
      density="compact"
    />
  );
}

