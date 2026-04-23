"use client";

import Panel from "./Panel";

const SCOPE_TABS = ["My Roster", "League", "All"];

/**
 * Team News Feed — narrative context.
 * Structural stub with explicit "no provider connected" empty state
 * so the panel doesn't fake data.  Real adapter ships later.
 */
export default function TeamNewsFeed() {
  return (
    <Panel
      title="News"
      subtitle="Roster-relevant headlines"
      className="panel--news"
      actions={
        <div className="panel-tabs" role="tablist" aria-label="News scope">
          {SCOPE_TABS.map((t, i) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={i === 0}
              className={`panel-tab${i === 0 ? " is-active" : ""}`}
              disabled
            >
              {t}
            </button>
          ))}
        </div>
      }
    >
      <div className="news-empty" role="status">
        <span className="news-empty-title">No news provider connected</span>
        <span className="news-empty-body">
          Adapters wire in at the ingestion step. Until then, this panel holds
          its slot without fabricating headlines.
        </span>
      </div>
    </Panel>
  );
}
