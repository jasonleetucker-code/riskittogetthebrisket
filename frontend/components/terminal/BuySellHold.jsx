"use client";

import { useState } from "react";
import Panel from "./Panel";

const SIGNAL_TABS = [
  { key: "buy", label: "Buy" },
  { key: "sell", label: "Sell" },
  { key: "hold", label: "Hold" },
];

function SignalCard() {
  return (
    <article className="signal-card" aria-hidden="true">
      <div className="signal-card-head">
        <span className="signal-card-name skeleton-line" />
        <span className="signal-card-tag skeleton-line skeleton-line--xs" />
      </div>
      <div className="signal-card-body">
        <span className="signal-card-rationale skeleton-line skeleton-line--wide" />
        <span className="signal-card-rationale skeleton-line skeleton-line--wide" />
      </div>
      <div className="signal-card-foot">
        <span className="signal-card-cta skeleton-line skeleton-line--sm" />
      </div>
    </article>
  );
}

/**
 * Buy / Sell / Hold Signals — decision layer.
 * Structural stub with tabs and skeleton signal cards.
 */
export default function BuySellHold() {
  const [active, setActive] = useState("buy");
  return (
    <Panel title="Signals" subtitle="Buy / Sell / Hold" className="panel--signals">
      <div className="signal-tabs" role="tablist" aria-label="Signal kind">
        {SIGNAL_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={active === t.key}
            className={`signal-tab${active === t.key ? " is-active" : ""}`}
            onClick={() => setActive(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div className="signal-cards">
        {Array.from({ length: 3 }).map((_, i) => (
          <SignalCard key={i} />
        ))}
      </div>
    </Panel>
  );
}
