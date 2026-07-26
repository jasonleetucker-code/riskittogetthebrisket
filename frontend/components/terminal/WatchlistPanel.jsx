"use client";

import { useMemo } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import { useUserState } from "@/components/useUserState";
import { EmptyState, Movement, Panel } from "@/components/ds";
import styles from "./terminal.module.css";

/**
 * WatchlistPanel — user-curated list of players to keep an eye on.
 *
 * Backed by ``useUserState.watchlist`` (SQLite on the server for
 * authenticated users, localStorage for anonymous).  The terminal
 * endpoint enriches each watchlist entry with value / rank / trend
 * / volatility so the panel renders movement at a glance.
 *
 * Add / remove affordance: clicking a player name in this panel
 * does nothing by default — the row is read-only.  Add is
 * performed elsewhere (the star button on PlayerPopup, or the
 * per-row action on rankings/roster views).  The panel shows an
 * empty-state message with instructions when the list is empty.
 *
 * The panel is intentionally lightweight:
 *   - No roster-only / league-only toggle (watchlist is global).
 *   - No sort options (chronological by add-time).
 *   - No windowed trend selector — defaults to 30d from the
 *     terminal payload.
 */
export default function WatchlistPanel() {
  const { openPlayerPopup } = useApp();
  const { selectedTeam } = useTeam();
  const { state: userState, toggleWatchlist, serverBacked } = useUserState();
  const { watchlist: serverWatchlist = [] } = useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  // Use the server-enriched watchlist when available, fall back to
  // names-only from useUserState so the panel at least shows the
  // list (with "—" placeholders) while the terminal fetch resolves.
  const entries = useMemo(() => {
    if (Array.isArray(serverWatchlist) && serverWatchlist.length > 0) {
      return serverWatchlist;
    }
    const names = Array.isArray(userState?.watchlist) ? userState.watchlist : [];
    return names.map((name) => ({
      name,
      pos: "—",
      value: null,
      rank: null,
      rankChange: null,
      trend7: null,
      trend30: null,
      trend90: null,
      trend180: null,
      volatility: null,
      onRoster: false,
    }));
  }, [serverWatchlist, userState?.watchlist]);

  const count = entries.length;

  return (
    <Panel
      title="Watchlist"
      subtitle={
        serverBacked
          ? "Synced across your devices"
          : "Saved locally — sign in to sync"
      }
      actions={
        count > 0 ? (
          <span className={styles.panelCount}>
            {count} player{count === 1 ? "" : "s"}
          </span>
        ) : null
      }
    >
      {count === 0 ? (
        <EmptyState
          title="No players on your watchlist yet"
          description="Use the star on any player profile to add them. Watchlist entries show value plus 7/30/90/180-day trends at a glance."
        />
      ) : (
        <ul className="watchlist-list">
          {entries.map((e) => (
            <li key={e.name} className={`watchlist-row${e.onRoster ? " watchlist-row--roster" : ""}`}>
              <button
                type="button"
                className="watchlist-row-trigger"
                onClick={() => openPlayerPopup?.(e.name)}
                title={`Open ${e.name}`}
              >
                <span className="watchlist-col watchlist-col--name">
                  {e.onRoster && <span className="watchlist-row-dot" aria-hidden="true">●</span>}
                  {e.name}
                </span>
                <span className="watchlist-col watchlist-col--pos">{e.pos}</span>
                <span className="watchlist-col watchlist-col--value">
                  {Number.isFinite(Number(e.value)) ? Number(e.value).toLocaleString() : "—"}
                </span>
                <span className="watchlist-col watchlist-col--trend">
                  <TrendDelta label="7d" value={e.trend7} />
                  <TrendDelta label="30d" value={e.trend30} />
                  <TrendDelta label="90d" value={e.trend90} />
                  <TrendDelta label="180d" value={e.trend180} />
                </span>
              </button>
              <button
                type="button"
                className="watchlist-row-remove"
                onClick={() => toggleWatchlist(e.name)}
                title={`Remove ${e.name} from watchlist`}
                aria-label={`Remove ${e.name} from watchlist`}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function TrendDelta({ label, value }) {
  const n = Number(value);
  if (!Number.isFinite(n)) {
    return (
      <span className="watchlist-delta watchlist-delta--flat" title={`${label} trend unavailable`}>
        <span className="watchlist-delta-label">{label}</span>
        <span className="watchlist-delta-value">—</span>
      </span>
    );
  }
  const tone = n > 0 ? "up" : n < 0 ? "down" : "flat";
  return (
    <span
      className={`watchlist-delta watchlist-delta--${tone}`}
      title={`${label}: ${n > 0 ? "+" : ""}${n} ranks`}
    >
      <span className="watchlist-delta-label">{label}</span>
      <span className="watchlist-delta-value">
        {n === 0 ? (
          "—"
        ) : (
          <Movement delta={n} srLabel={`${label}: ${n > 0 ? "up" : "down"} ${Math.abs(n)} ranks`} />
        )}
      </span>
    </span>
  );
}
