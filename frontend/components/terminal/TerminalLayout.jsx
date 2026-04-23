"use client";

import { useTeam } from "@/components/useTeam";
import { useTerminal } from "@/components/useTerminal";
import TeamCommandHeader from "./TeamCommandHeader";
import MarketTicker from "./MarketTicker";
import PlayerMarketMovement from "./PlayerMarketMovement";
import BuySellHold from "./BuySellHold";
import PortfolioSummary from "./PortfolioSummary";
import ScoutingIntel from "./ScoutingIntel";
import TeamNewsFeed from "./TeamNewsFeed";
import QuickActions from "./QuickActions";
import WatchlistPanel from "./WatchlistPanel";
import StaleBanner from "./StaleBanner";

/**
 * TerminalLayout — structural shell for the signed-in landing page.
 *
 * Top-level `useTerminal` fetch primes the module-level cache so
 * every descendant component that calls ``useTerminal(...)`` with a
 * matching ``(ownerId, windowDays)`` returns instantly from cache.
 * Individual components still do local derivations for anything the
 * server doesn't compute (starter/bench split, per-player
 * sparklines, signal dismissal UI), but the big-ticket aggregates
 * (team value, deltas with coverage detail, portfolio byPosition /
 * byAge / volExposure, watchlist, scouting insights) all come from
 * one network call.
 *
 * ``StaleBanner`` renders above the grid when the terminal endpoint
 * falls back to an on-disk cached contract because the live scrape
 * hasn't landed yet; otherwise it returns null.
 *
 * Grid strategy:
 *   - mobile (<720px):  single column; panels re-ordered via CSS
 *     ``order`` so the most actionable surfaces (signals, market
 *     movement) land above portfolio/scouting diagnostics.
 *   - tablet (720-1200): two columns; left rail stacks above the
 *     secondary rail.
 *   - desktop (≥1200px): three columns as designed (portfolio+
 *     scouting | movement+signals+watchlist | news+actions).
 */
export default function TerminalLayout() {
  const { selectedTeam } = useTeam();
  // Prime the cache so every useTerminal(...) inside child panels
  // is a no-op read.  We don't use the return value here — each
  // panel re-calls the hook with the same key.
  useTerminal({
    ownerId: String(selectedTeam?.ownerId || ""),
    teamName: selectedTeam?.name || "",
    windowDays: 30,
  });

  return (
    <div className="terminal">
      <StaleBanner />
      <TeamCommandHeader />
      <MarketTicker />

      <div className="terminal-grid">
        <div className="terminal-col terminal-col--left">
          <PortfolioSummary />
          <ScoutingIntel />
        </div>
        <div className="terminal-col terminal-col--center">
          <PlayerMarketMovement />
          <BuySellHold />
          <WatchlistPanel />
        </div>
        <div className="terminal-col terminal-col--right">
          <TeamNewsFeed />
          <QuickActions />
        </div>
      </div>
    </div>
  );
}
