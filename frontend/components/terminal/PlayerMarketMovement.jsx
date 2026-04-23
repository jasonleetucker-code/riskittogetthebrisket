"use client";

import Panel from "./Panel";

const SCOPE_TABS = ["My Roster", "Watchlist", "League", "By Pos"];
const WINDOW_TABS = ["24h", "7d", "30d"];

function SkeletonRow() {
  return (
    <li className="pmm-row" aria-hidden="true">
      <span className="pmm-col pmm-col--name skeleton-line" />
      <span className="pmm-col pmm-col--pos skeleton-line skeleton-line--xs" />
      <span className="pmm-col pmm-col--value skeleton-line skeleton-line--sm" />
      <span className="pmm-col pmm-col--delta skeleton-line skeleton-line--sm" />
      <span className="pmm-col pmm-col--spark skeleton-line" />
      <span className="pmm-col pmm-col--conf skeleton-line skeleton-line--xs" />
    </li>
  );
}

/**
 * Player Market Movement — primary analytical surface.
 * Structural stub with scope/window tabs and a skeleton table.
 */
export default function PlayerMarketMovement() {
  return (
    <Panel
      title="Player Market Movement"
      subtitle="Value changes across the window"
      className="panel--movement"
      actions={
        <div className="panel-tabs" role="tablist" aria-label="Movement window">
          {WINDOW_TABS.map((t, i) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={i === 1}
              className={`panel-tab${i === 1 ? " is-active" : ""}`}
              disabled
            >
              {t}
            </button>
          ))}
        </div>
      }
    >
      <nav className="pmm-scope" role="tablist" aria-label="Movement scope">
        {SCOPE_TABS.map((t, i) => (
          <button
            key={t}
            type="button"
            role="tab"
            aria-selected={i === 0}
            className={`pmm-scope-tab${i === 0 ? " is-active" : ""}`}
            disabled
          >
            {t}
          </button>
        ))}
      </nav>
      <div className="pmm-table">
        <div className="pmm-head" aria-hidden="true">
          <span className="pmm-col pmm-col--name">Player</span>
          <span className="pmm-col pmm-col--pos">Pos</span>
          <span className="pmm-col pmm-col--value">Value</span>
          <span className="pmm-col pmm-col--delta">Δ</span>
          <span className="pmm-col pmm-col--spark">Trend</span>
          <span className="pmm-col pmm-col--conf">Conf</span>
        </div>
        <ul className="pmm-body">
          {Array.from({ length: 6 }).map((_, i) => (
            <SkeletonRow key={i} />
          ))}
        </ul>
      </div>
    </Panel>
  );
}
