"use client";

const PLACEHOLDER_ITEMS = Array.from({ length: 12 }).map((_, i) => ({
  id: i,
  label: "—",
  delta: "—",
}));

/**
 * Market Ticker — horizontal pulse strip.
 * Structural stub: renders placeholder slots so the ticker zone
 * holds its height.  Auto-scroll + live deltas wire in later.
 */
export default function MarketTicker() {
  return (
    <div className="ticker" role="region" aria-label="Market ticker">
      <div className="ticker-scope">
        <span className="ticker-scope-label">Scope</span>
        <span className="ticker-scope-value">My Roster</span>
      </div>
      <div className="ticker-strip" aria-hidden="true">
        <ul className="ticker-track">
          {PLACEHOLDER_ITEMS.map((item) => (
            <li key={item.id} className="ticker-item">
              <span className="ticker-item-label">{item.label}</span>
              <span className="ticker-item-delta">{item.delta}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
