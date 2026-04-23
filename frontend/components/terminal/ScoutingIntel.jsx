"use client";

import Panel from "./Panel";

/**
 * Scouting / Intel — metadata confidence layer.
 * Structural stub with distribution bars and diagnostic rows.
 */
export default function ScoutingIntel() {
  return (
    <Panel
      title="Scouting"
      subtitle="Data confidence + anomalies"
      className="panel--scouting"
      collapsible
      defaultCollapsed={false}
    >
      <div className="scouting-dist">
        <h3 className="scouting-sub">Confidence</h3>
        <div className="scouting-dist-bars" aria-hidden="true">
          <span className="scouting-dist-bar scouting-dist-bar--high" style={{ flex: 5 }} />
          <span className="scouting-dist-bar scouting-dist-bar--med" style={{ flex: 3 }} />
          <span className="scouting-dist-bar scouting-dist-bar--low" style={{ flex: 2 }} />
        </div>
        <div className="scouting-dist-legend">
          <span>High —</span>
          <span>Med —</span>
          <span>Low —</span>
        </div>
      </div>

      <div className="scouting-list">
        <h3 className="scouting-sub">Anomalies</h3>
        <ul className="scouting-rows">
          {Array.from({ length: 3 }).map((_, i) => (
            <li key={i} className="scouting-row" aria-hidden="true">
              <span className="scouting-row-name skeleton-line" />
              <span className="scouting-row-flag skeleton-line skeleton-line--xs" />
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}
