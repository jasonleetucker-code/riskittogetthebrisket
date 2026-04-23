"use client";

import Panel from "./Panel";

const POSITIONS = ["QB", "RB", "WR", "TE", "IDP", "PICK"];

/**
 * Portfolio Summary — asset allocation view.
 * Structural stub with position stack bars and top-holdings list.
 */
export default function PortfolioSummary() {
  return (
    <Panel
      title="Portfolio"
      subtitle="Positional allocation"
      className="panel--portfolio"
    >
      <div className="portfolio-stack" aria-hidden="true">
        {POSITIONS.map((pos, i) => (
          <div key={pos} className="portfolio-stack-row">
            <span className="portfolio-stack-label">{pos}</span>
            <div className="portfolio-stack-bar">
              <span
                className="portfolio-stack-fill skeleton-line"
                style={{ width: `${[75, 62, 88, 31, 22, 18][i]}%` }}
              />
            </div>
            <span className="portfolio-stack-value skeleton-line skeleton-line--xs" />
          </div>
        ))}
      </div>

      <div className="portfolio-top">
        <h3 className="portfolio-sub">Top Holdings</h3>
        <ul className="portfolio-top-list">
          {Array.from({ length: 5 }).map((_, i) => (
            <li key={i} className="portfolio-top-row" aria-hidden="true">
              <span className="portfolio-top-rank">{i + 1}</span>
              <span className="portfolio-top-name skeleton-line" />
              <span className="portfolio-top-value skeleton-line skeleton-line--sm" />
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
