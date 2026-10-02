"use client";

/**
 * PortfolioSummary — what a multi-lineup build actually contains: team and
 * game exposure, stack shapes, salary spread, distinct players.  Counts from
 * the server (src/dfs/portfolio.py); nothing estimated.  Lazily loaded.
 */

import React from "react";
import { DataTable } from "@/components/ds";
import { formatSalary } from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

const COLUMNS = (label) => [
  { key: "key", header: label },
  { key: "lineups", header: "Lineups", numeric: true },
  { key: "share", header: "Share", numeric: true, render: (r) => `${Math.round(r.share * 100)}%` },
];

export default function PortfolioSummary({ portfolio: p }) {
  if (!p) return null;
  return (
    <div className={styles.result}>
      <p className={styles.note}>
        {p.lineups} lineups use {p.distinctPlayers} different players; salary {formatSalary(p.salary.min)}–
        {formatSalary(p.salary.max)}.
        {p.lineupsWithUnknownGame ? ` ${p.lineupsWithUnknownGame} lineup(s) include a player with an unknown game.` : ""}{" "}
        {p.note}
      </p>
      <div className={styles.importGrid}>
        <DataTable caption="Team exposure across the built lineups" columns={COLUMNS("Team")} rows={p.teams} rowKey={(r) => r.key} density="compact" />
        <DataTable caption="Game exposure across the built lineups" columns={COLUMNS("Game")} rows={p.games} rowKey={(r) => r.key} density="compact" />
        <DataTable
          caption="Stack shapes (players per team, largest first)"
          columns={COLUMNS("Shape")}
          rows={p.stackShapes}
          rowKey={(r) => r.key}
          density="compact"
        />
      </div>
    </div>
  );
}
