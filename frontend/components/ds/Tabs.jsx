/**
 * Tabs — panel-switching navigation with real tablist semantics.
 * Replaces SubNav and every hand-rolled tab-chip row. For ≤5 exclusive
 * VALUE choices (not panels) use <SegmentedControl> instead.
 *
 * Ids are instance-scoped: every generated id is prefixed so two Tabs
 * with the same logical tab ids (e.g. two "overview" tablists on one
 * page) never emit duplicate DOM ids or cross-wired aria-controls.
 * Wire your panels with the exported helpers:
 *
 *   <Tabs idPrefix="league" label="League sections"
 *         tabs={[{ id: "overview", label: "Overview" }, …]}
 *         active={tab} onChange={setTab} />
 *   <div role="tabpanel"
 *        id={tabPanelId("league", tab)}
 *        aria-labelledby={tabId("league", tab)}>…
 *
 * Pass `idPrefix` whenever you render the panel yourself (you need the
 * prefix to build the panel id). When omitted, a unique useId() prefix
 * is generated — ids stay collision-free, but external code can't
 * reconstruct them, so omit it only for self-contained usages.
 *
 * Props: tabs [{id, label, badge?}], active (id), onChange(id), label
 * (accessible name for the tablist), idPrefix (see above).
 *
 * A11y: roving tabindex — one tab stop; Left/Right/Home/End move focus
 * and select; each button is aria-selected + aria-controls its panel id.
 * Overflow scrolls horizontally with no visible scrollbar; tabs never
 * wrap or truncate to a 21-item pile.
 */
"use client";

import React, { useId, useRef } from "react";

/** DOM id of the tab button for `tabId` under `idPrefix`. */
export function tabId(idPrefix, id) {
  return `${idPrefix}-tab-${id}`;
}

/** DOM id the matching tabpanel must use. */
export function tabPanelId(idPrefix, id) {
  return `${idPrefix}-panel-${id}`;
}

export function Tabs({ tabs, active, onChange, label, idPrefix, className = "" }) {
  const refs = useRef([]);
  const autoPrefix = useId();
  const prefix = idPrefix || `ds-tabs${autoPrefix}`;
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
            id={tabId(prefix, tab.id)}
            aria-selected={selected}
            aria-controls={tabPanelId(prefix, tab.id)}
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
