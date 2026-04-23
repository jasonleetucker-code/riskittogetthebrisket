"use client";

import { useState } from "react";

/**
 * Panel — terminal-layout primitive.
 *
 * Every landing-page section renders inside a Panel so the chrome,
 * title rhythm, and responsive collapse behavior live in one place.
 * This step ships structure only; visual polish happens later.
 *
 * Props:
 *   - title            (required) section label, rendered as h2
 *   - subtitle         optional helper line under the title
 *   - actions          slot rendered on the right of the panel header
 *   - className        extra class for the outer <section> (e.g. panel--news)
 *   - variant          "default" | "bare" — "bare" drops the outer border
 *   - collapsible      mobile-collapsible affordance
 *   - defaultCollapsed initial collapsed state when collapsible
 *   - padded           include the default body padding (default true)
 */
export default function Panel({
  title,
  subtitle,
  actions,
  className = "",
  variant = "default",
  collapsible = false,
  defaultCollapsed = false,
  padded = true,
  children,
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);

  const classes = [
    "panel",
    `panel--${variant}`,
    collapsible ? "panel--collapsible" : "",
    collapsed ? "panel--collapsed" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const bodyClasses = ["panel-body", padded ? "" : "panel-body--flush"]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={classes}>
      {(title || actions || collapsible) && (
        <header className="panel-head">
          <div className="panel-head-text">
            {title && <h2 className="panel-title">{title}</h2>}
            {subtitle && <p className="panel-subtitle">{subtitle}</p>}
          </div>
          <div className="panel-head-actions">
            {actions}
            {collapsible && (
              <button
                type="button"
                className="panel-collapse-btn"
                aria-expanded={!collapsed}
                aria-label={collapsed ? "Expand section" : "Collapse section"}
                onClick={() => setCollapsed((v) => !v)}
              >
                {collapsed ? "+" : "−"}
              </button>
            )}
          </div>
        </header>
      )}
      {!collapsed && <div className={bodyClasses}>{children}</div>}
    </section>
  );
}

/**
 * PanelPlaceholder — intentional "content coming" state for stub
 * sections.  Renders dimmed skeleton rows so the layout holds its
 * shape and a reader can tell the section is deliberately empty, not
 * broken.
 */
export function PanelPlaceholder({ label = "Wiring pending", rows = 3, dense = false }) {
  return (
    <div className={`panel-placeholder${dense ? " panel-placeholder--dense" : ""}`}>
      <span className="panel-placeholder-label">{label}</span>
      <div className="panel-placeholder-rows" aria-hidden="true">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="panel-placeholder-row" />
        ))}
      </div>
    </div>
  );
}
