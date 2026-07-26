/**
 * Banner — inline alert strip for surface-level conditions (stale data,
 * degraded source, action results). Calm by design: left-edge semantic
 * rule + icon, panel-toned body — never a full-bleed color slab.
 *
 * Usage:
 *   <Banner tone="warning" title="Data is stale">
 *     Last scrape finished 26 hours ago.
 *   </Banner>
 *   <Banner tone="negative" onDismiss={hide}>Save failed.</Banner>
 *
 * Props:
 *   tone      "info" | "positive" | "warning" | "negative"  (info)
 *   title     optional bold first line
 *   onDismiss optional — renders a labelled close button
 *   children  body text
 *
 * A11y: warning/negative render role="alert" (assertive); info/positive
 * render role="status" (polite). This is the live-region wiring the audit
 * found missing on StaleDataBanner/Toast.
 */
"use client";

import React from "react";
import { Icon } from "./Icon";
import { Button } from "./Button";

const TONE_ICON = {
  info: "info",
  positive: "check",
  warning: "warning",
  negative: "warning",
};

export function Banner({ tone = "info", title, onDismiss, className = "", children }) {
  const urgent = tone === "warning" || tone === "negative";
  return (
    <div
      role={urgent ? "alert" : "status"}
      className={`ds-banner ds-banner--${tone} ${className}`.trim()}
    >
      <Icon
        name={TONE_ICON[tone]}
        size={15}
        style={{ color: `var(--${tone})`, flexShrink: 0, marginTop: 2 }}
      />
      <div className="ds-banner__body">
        {title ? <p className="ds-banner__title">{title}</p> : null}
        {children}
      </div>
      {onDismiss ? (
        <span className="ds-banner__dismiss">
          <Button
            variant="ghost"
            size="sm"
            onClick={onDismiss}
            icon={<Icon name="close" size={12} />}
            aria-label="Dismiss"
          />
        </span>
      ) : null}
    </div>
  );
}
