"use client";

// Client-only shared primitives for /league sections.
//
// Re-exports:
//   * pure helpers — from ./shared-helpers.js (no "use client")
//   * server-safe primitives (Avatar, Card, Stat, MeetingCard) — from
//     ./shared-server.jsx (also no "use client")
//
// Adds client-only primitives that rely on onClick closures:
//   ManagerInline, LinkButton, EmptyCard, MiniLeaderboard,
//   HighlightCard, SingleHighlight, renderAwardValue
//
// Server components under /league/franchise, /league/rivalry,
// /league/player, /league/weekly/[...] should import from
// ``shared-server.jsx`` + ``shared-helpers.js`` directly rather than
// from this file.

import { Button } from "@/components/ds";
import { EmptyState } from "@/components/ui";
import styles from "./league-shared.module.css";

export {
  buildManagerLookup,
  nameFor,
  avatarUrlFor,
  fmtNumber,
  fmtPoints,
  fmtPercent,
} from "./shared-helpers.js";
export {
  Avatar,
  Card,
  Stat,
  MeetingCard,
} from "./shared-server.jsx";

import { nameFor, fmtPoints, fmtNumber, fmtPercent } from "./shared-helpers.js";
import { Avatar, Card } from "./shared-server.jsx";

export function ManagerInline({ managers, ownerId, onClick, compact = false }) {
  const name = nameFor(managers, ownerId);
  return (
    <span
      onClick={onClick}
      className={onClick ? `${styles.managerInline} ${styles["managerInline--clickable"]}` : styles.managerInline}
    >
      <Avatar managers={managers} ownerId={ownerId} size={compact ? 18 : 22} />
      <span>{name}</span>
    </span>
  );
}

/**
 * Thin adapter over ds `Button` (ghost variant — borderless, for dense
 * inline navigation like "View full history"). Same `onClick`/`children`
 * call sites as before.
 */
export function LinkButton({ onClick, children }) {
  return (
    <Button type="button" variant="ghost" size="sm" onClick={onClick}>
      {children}
    </Button>
  );
}

export function EmptyCard({ label, message }) {
  return (
    <Card>
      <EmptyState
        title={`${label} coming online`}
        message={
          message ||
          "Sleeper hasn't surfaced enough data for this section yet. It will fill in as games finish, trades complete, and drafts are held."
        }
      />
    </Card>
  );
}

export function MiniLeaderboard({ managers, title, rows, metric, onRowClick }) {
  if (!rows || !rows.length) return null;
  return (
    <div className={`${styles.miniCard} ${styles.leaderboard}`}>
      <div className={styles.leaderboardTitle}>{title}</div>
      <div className={styles.leaderboardRows}>
        {rows.slice(0, 5).map((r, i) => (
          <div
            key={r.ownerId || i}
            className={onRowClick ? `${styles.leaderboardRow} ${styles["leaderboardRow--clickable"]}` : styles.leaderboardRow}
            onClick={() => onRowClick?.(r.ownerId)}
          >
            <span className={styles.leaderboardEntry}>
              <span className={styles.leaderboardRank}>{i + 1}.</span>
              {managers ? <Avatar managers={managers} ownerId={r.ownerId} size={18} /> : null}
              {r.displayName || r.currentTeamName || r.ownerId}
            </span>
            <span className={styles.leaderboardMetric}>{metric(r)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function HighlightCard({ label, caption, teams }) {
  return (
    <div className={styles.miniCard}>
      <div className={styles.miniCardLabel}>{label}</div>
      <div className={styles.miniCardValue}>
        {teams && teams[0] && teams[1]
          ? `${teams[0].displayName} vs ${teams[1].displayName}`
          : "—"}
      </div>
      <div className={styles.miniCardSub}>{caption}</div>
    </div>
  );
}

export function SingleHighlight({ label, value, sub }) {
  return (
    <div className={styles.miniCard}>
      <div className={styles.miniCardLabel}>{label}</div>
      <div className={styles.miniCardValue}>{value}</div>
      {sub && <div className={styles.miniCardSub}>{sub}</div>}
    </div>
  );
}

export function renderAwardValue(key, value) {
  if (!value) return "";
  switch (key) {
    case "champion":
      return "";
    case "regular_season_crown":
      return value.record || "";
    case "points_king":
      return `${fmtNumber(value.pointsFor, 1)} PF`;
    case "highest_single_week":
    case "lowest_single_week":
      return `Wk ${value.week} · ${fmtPoints(value.points)} pts`;
    case "trader_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.trades} trades`;
    case "best_trade_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · Wk ${value.week}`;
    case "waiver_king":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.adds} adds`;
    case "silent_assassin":
      return `${fmtPercent(value.winPct)} in ${value.closeGames} close games`;
    case "weekly_hammer":
      return `${value.highScoreFinishes} high-score wks`;
    case "playoff_mvp": {
      if (value.playerName) {
        return `${value.playerName} (${value.position}) · VORP ${fmtPoints(value.vorp)}`;
      }
      return `${fmtPoints(value.playoffPoints)} playoff pts`;
    }
    case "bad_beat":
      return `${fmtPoints(value.points)} in loss · Wk ${value.week}`;
    case "mr_consistent":
      return `CV ${fmtNumber(value.cv, 3)} · ${fmtNumber(value.meanScore, 1)} avg · ${value.weeks} wks`;
    case "best_rebuild":
      return `Composite ${value.compositeScore}`;
    case "rivalry_of_the_year":
      return `${value.displayNames[0]} vs ${value.displayNames[1]} · Index ${value.rivalryIndex}`;
    // ── Manager awards ──
    case "top_offense":
      return `${fmtNumber(value.offensePoints, 1)} starter pts`;
    case "top_defense":
      return `${fmtNumber(value.defensePoints, 1)} starter pts`;
    case "top_nfl_team":
      return `${value.team} · ${fmtNumber(value.points, 1)} starter pts`;
    case "manager_of_the_year": {
      const finish = value.finishRank ? ` · #${value.finishRank} finish` : "";
      return `Score ${fmtNumber(value.compositeScore, 3)}${finish} · ${value.wins}-${value.losses} · ${fmtNumber(value.pointsFor, 1)} PF`;
    }
    // ── Player awards ──
    case "top_qb":
    case "top_rb":
    case "top_wr":
    case "top_te":
    case "top_k":
    case "top_dl":
    case "top_lb":
    case "top_db":
      return value.playerName
        ? `${value.playerName} · ${fmtPoints(value.starterPoints)} pts in ${value.gamesStarted} starts`
        : `${fmtPoints(value.starterPoints)} pts`;
    case "league_mvp":
    case "off_mvp":
    case "def_mvp":
    case "off_roy":
    case "def_roy":
      return value.playerName
        ? `${value.playerName} (${value.position}) · VORP ${fmtPoints(value.vorp)}`
        : `VORP ${fmtPoints(value.vorp)}`;
    default:
      return "";
  }
}
