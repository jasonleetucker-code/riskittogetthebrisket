"use client";

import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import TeamCommandHeader from "./TeamCommandHeader";
import MarketTicker from "./MarketTicker";
import TopSignalsRail from "./TopSignalsRail";
import PlayerMarketMovement from "./PlayerMarketMovement";
import BuySellHold from "./BuySellHold";
import MoversPanel from "./MoversPanel";
import PortfolioSummary from "./PortfolioSummary";
import ScoutingIntel from "./ScoutingIntel";
import TeamNewsFeed from "./TeamNewsFeed";
import QuickActions from "./QuickActions";
import WatchlistPanel from "./WatchlistPanel";
import StaleBanner from "./StaleBanner";
import styles from "./terminal.module.css";

/**
 * TerminalLayout — the daily-checkin war room (Redesign R3).
 *
 * The page answers one question in reading order: **what changed, and
 * what do I do about it?**
 *
 *   1. Command bar   — who you are and what your team is worth now
 *                      (identity, value, the four deltas, tier mix,
 *                      value trend).
 *   2. Ticker        — the market moving underneath you, right now.
 *   3. Signals rail  — the specific "act on this" list for YOUR
 *                      roster. Highest-value content on the page, so
 *                      nothing sits above it but context.
 *   4. Working grid  — the deeper surfaces you drill into once the
 *                      rail has pointed somewhere:
 *                        left   diagnostics (portfolio, scouting)
 *                        center market movement (movers, movement,
 *                               full signal book, watchlist)
 *                        right  intel + jumping-off points (news,
 *                               quick actions)
 *
 * Column assignment is by information role, not by what fits — the
 * grid is explicit per breakpoint (see terminal.module.css).
 *
 * The top-level ``useTerminal`` call primes the module-level cache so
 * every descendant calling ``useTerminal(...)`` with a matching
 * ``(ownerId, windowDays)`` returns instantly from cache. Panels still
 * do local derivations for anything the server doesn't compute
 * (starter/bench split, per-player sparklines, signal dismissal UI),
 * but the big aggregates come from that one network call.
 */
export default function TerminalLayout() {
  const { selectedTeam, loading: teamLoading } = useTeam();
  // Prime the cache — the return value is intentionally unused; each
  // panel re-calls the hook with the same key.
  useTerminal({
    // Hold the fetch until team identity resolves from the contract
    // (prevents the discarded ownerId:"" duplicate call).
    skip: teamLoading,
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  return (
    <div className={styles.page}>
      <StaleBanner />
      <TeamCommandHeader />
      <MarketTicker />
      <TopSignalsRail />

      <div className={styles.grid}>
        <div className={styles.col}>
          <PortfolioSummary />
          <ScoutingIntel />
        </div>
        <div className={styles.col}>
          <MoversPanel />
          <PlayerMarketMovement />
          <BuySellHold />
          <WatchlistPanel />
        </div>
        <div className={`${styles.col} ${styles.colRight}`}>
          <TeamNewsFeed />
          <QuickActions />
        </div>
      </div>
    </div>
  );
}
