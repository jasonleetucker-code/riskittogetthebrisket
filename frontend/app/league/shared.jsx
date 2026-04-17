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

import { EmptyState } from "@/components/ui";

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
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: onClick ? "pointer" : "default",
        color: onClick ? "var(--cyan)" : "inherit",
      }}
    >
      <Avatar managers={managers} ownerId={ownerId} size={compact ? 18 : 22} />
      <span>{name}</span>
    </span>
  );
}

export function LinkButton({ onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: "transparent",
        border: "1px solid var(--border-bright)",
        borderRadius: 6,
        color: "var(--cyan)",
        padding: "4px 10px",
        fontSize: "0.7rem",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
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
    <div className="card" style={{ flex: "1 1 260px" }}>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.slice(0, 5).map((r, i) => (
          <div
            key={r.ownerId || i}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: "0.74rem",
              cursor: onRowClick ? "pointer" : "default",
            }}
            onClick={() => onRowClick?.(r.ownerId)}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", minWidth: 16 }}>{i + 1}.</span>
              {managers ? <Avatar managers={managers} ownerId={r.ownerId} size={18} /> : null}
              {r.displayName || r.currentTeamName || r.ownerId}
            </span>
            <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{metric(r)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function HighlightCard({ label, caption, teams }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.84rem", fontWeight: 700, marginTop: 2 }}>
        {teams && teams[0] && teams[1]
          ? `${teams[0].displayName} vs ${teams[1].displayName}`
          : "—"}
      </div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>{caption}</div>
    </div>
  );
}

export function SingleHighlight({ label, value, sub }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.84rem", fontWeight: 700, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export function renderAwardValue(key, value) {
  if (!value) return "";
  switch (key) {
    case "champion":
    case "runner_up":
    case "toilet_bowl":
      return "";
    case "top_seed":
      return `Win% ${fmtPercent(value.winPct)}`;
    case "regular_season_crown":
      return value.record || "";
    case "points_king":
      return `${fmtNumber(value.pointsFor, 1)} PF`;
    case "points_black_hole":
      return `${fmtNumber(value.pointsAgainst, 1)} PA`;
    case "highest_single_week":
    case "lowest_single_week":
      return `Wk ${value.week} · ${fmtPoints(value.points)} pts`;
    case "trader_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.trades} trades`;
    case "best_trade_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · Wk ${value.week}`;
    case "waiver_king":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.adds} adds`;
    case "chaos_agent":
      return `Score ${value.score} · ${value.trades} trades · ${value.partners} partners`;
    case "most_active":
      return `${value.total} moves`;
    case "silent_assassin":
      return `${fmtPercent(value.winPct)} in ${value.closeGames} close games`;
    case "weekly_hammer":
      return `${value.highScoreFinishes} high-score wks`;
    case "playoff_mvp":
      return `${fmtPoints(value.playoffPoints)} playoff pts`;
    case "bad_beat":
      return `${fmtPoints(value.points)} in loss · Wk ${value.week}`;
    case "best_rebuild":
      return `Composite ${value.compositeScore}`;
    case "rivalry_of_the_year":
      return `${value.displayNames[0]} vs ${value.displayNames[1]} · Index ${value.rivalryIndex}`;
    case "pick_hoarder":
      return `Weighted ${value.weightedScore} · ${value.totalPicks} picks`;
    default:
      return "";
  }
}
