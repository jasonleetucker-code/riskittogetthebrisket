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
 * `idPrefix` is REQUIRED in practice: Tabs does not render tabpanels,
 * so the consumer always needs the prefix to build panel ids that match
 * each tab's aria-controls. Omitting it logs a dev-time warning and
 * falls back to a unique useId() prefix (collision-free, but the
 * aria-controls then point at panels you cannot construct — fix the
 * warning, don't ship it).
 *
 * Props: tabs [{id, label, badge?}], active (id), onChange(id), label
 * (accessible name for the tablist), idPrefix (required — see above).
 *
 * A11y: roving tabindex — one tab stop; Left/Right/Home/End move focus
 * and select; each button is aria-selected + aria-controls its panel id.
 * Overflow scrolls horizontally with no visible scrollbar; tabs never
 * wrap or truncate to a 21-item pile.
 */
"use client";

import React, { useEffect, useId, useRef } from "react";

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

  // idPrefix is required in practice: without it the consumer cannot
  // build panel ids matching aria-controls (Tabs renders no panels).
  // Warn loudly in dev; the useId fallback keeps ids collision-free so
  // nothing crashes while the warning is being fixed.
  useEffect(() => {
    if (!idPrefix && process.env.NODE_ENV !== "production") {
      console.warn(
        "ds/Tabs: `idPrefix` is missing. Pass idPrefix and build your " +
          "tabpanel ids with tabPanelId(idPrefix, tab.id) so aria-controls " +
          "points at a real element."
      );
    }
  }, [idPrefix]);

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
