"use client";

import TeamCommandHeader from "./TeamCommandHeader";
import MarketTicker from "./MarketTicker";
import PlayerMarketMovement from "./PlayerMarketMovement";
import BuySellHold from "./BuySellHold";
import PortfolioSummary from "./PortfolioSummary";
import ScoutingIntel from "./ScoutingIntel";
import TeamNewsFeed from "./TeamNewsFeed";
import QuickActions from "./QuickActions";

/**
 * TerminalLayout — structural shell for the signed-in landing page.
 *
 * Grid strategy:
 *   - mobile (<720px):  single column; panels re-ordered via CSS
 *     ``order`` so the most actionable surfaces (signals, market
 *     movement) land above portfolio/scouting diagnostics.
 *   - tablet (720-1200): two columns; left rail stacks above the
 *     secondary rail.
 *   - desktop (≥1200px): three columns as designed (portfolio+
 *     scouting | movement+signals | news+actions).
 *
 * display:contents on the column wrappers at mobile/tablet lets each
 * panel participate directly in the outer flex/grid, which is what
 * lets CSS ``order`` do the reflow without duplicating JSX.
 */
export default function TerminalLayout() {
  return (
    <div className="terminal">
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
        </div>
        <div className="terminal-col terminal-col--right">
          <TeamNewsFeed />
          <QuickActions />
        </div>
      </div>
    </div>
  );
}
