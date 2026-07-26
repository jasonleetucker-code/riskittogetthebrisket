/**
 * Tabs — panel-switching navigation with real tablist semantics.
 * Replaces SubNav and every hand-rolled tab-chip row. For ≤5 exclusive
 * VALUE choices (not panels) use <SegmentedControl> instead.
 *
 * Usage:
 *   <Tabs
 *     label="League sections"
 *     tabs={[{ id: "overview", label: "Overview" }, …]}
 *     active={tab}
 *     onChange={setTab}
 *   />
 *   <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`}>…
 *
 * Props: tabs [{id, label, badge?}], active (id), onChange(id), label
 * (accessible name for the tablist).
 *
 * A11y: roving tabindex — one tab stop; Left/Right/Home/End move focus
 * and select; each button is aria-selected + aria-controls its panel id
 * (`panel-<id>` by convention). Overflow scrolls horizontally with no
 * visible scrollbar; tabs never wrap or truncate to a 21-item pile.
 */
"use client";

import React, { useRef } from "react";

export function Tabs({ tabs, active, onChange, label, className = "" }) {
  const refs = useRef([]);
  const activeIndex = Math.max(0, tabs.findIndex((t) => t.id === active));

  const focusSelect = (index) => {
    const next = (index + tabs.length) % tabs.length;
    onChange?.(tabs[next].id);
    refs.current[next]?.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      focusSelect(activeIndex + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      focusSelect(activeIndex - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      focusSelect(0);
    } else if (e.key === "End") {
      e.preventDefault();
      focusSelect(tabs.length - 1);
    }
  };

  return (
    <div
      role="tablist"
      aria-label={label}
      className={`ds-tabs ${className}`.trim()}
      onKeyDown={onKeyDown}
    >
      {tabs.map((tab, i) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={selected}
            aria-controls={`panel-${tab.id}`}
            tabIndex={i === activeIndex ? 0 : -1}
            className="ds-tab"
            onClick={() => onChange?.(tab.id)}
          >
            {tab.label}
            {tab.badge != null ? <> {tab.badge}</> : null}
          </button>
        );
      })}
    </div>
  );
}
