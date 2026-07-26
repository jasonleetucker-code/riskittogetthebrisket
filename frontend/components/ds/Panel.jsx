/**
 * Panel — THE container primitive. Replaces all three legacy container
 * systems (`.card` ×187, terminal Panel, league Card). If content needs a
 * box, it goes in a Panel; there is no second container.
 *
 * Anatomy: header (title + subtitle + actions) / body / footer — all
 * optional except body. Vertical rhythm between panels belongs to the
 * PAGE (grid/stack gap), never to the panel (the audit found
 * `style={{marginTop:"var(--space-md)"}}` pasted 26×).
 *
 * Usage:
 *   <Panel title="Roster movers" subtitle="7-day value change"
 *          actions={<Button size="sm" variant="ghost">Export</Button>}>
 *     …content…
 *   </Panel>
 *   <Panel flush title="Value board">   // table bleeds to panel edge
 *     <DataTable … />
 *   </Panel>
 *
 *   <Panel collapsible title="Scouting">  // user can fold it away
 *     …long diagnostics…
 *   </Panel>
 *
 * Props:
 *   title      ReactNode — rendered as a heading (level via headingLevel, default h2)
 *   subtitle   ReactNode — one quiet line under the title
 *   actions    ReactNode — right-aligned header slot
 *   footer     ReactNode
 *   flush      boolean — zero body padding (tables, charts, lists)
 *   dense      boolean — tighter header/body padding for rail/grid use
 *   headingLevel 2|3|4 — keep the page outline honest
 *   as         element type (default "section")
 *   collapsible boolean — header renders a disclosure toggle that folds
 *              the body (and footer) away.  CONTROLLED: pass `collapsed`
 *              and `onToggleCollapsed`.  Requires a `title` — a
 *              disclosure with no label is unusable, so it no-ops
 *              without one.  For the usual "just let the user fold it"
 *              case use <CollapsiblePanel>, which owns the state.
 *   collapsed  boolean — folded state (controlled)
 *   onToggleCollapsed () => void — invoked by the disclosure button
 *   bodyId     string — id for the body region, needed for the
 *              disclosure's aria-controls.  CollapsiblePanel supplies
 *              one via useId.
 *
 * A11y: the toggle is a real <button> wrapping the heading text, with
 * aria-expanded + aria-controls pointing at the body region, so screen
 * readers announce the state and the relationship.  Collapsing hides
 * the body from the a11y tree rather than just visually.
 *
 * ── SERVER-SAFE: DO NOT ADD HOOKS TO THIS FILE ────────────────────────
 * Panel is THE container primitive, which makes it the one component
 * most likely to be rendered from a React Server Component — the
 * /league routes render `shared-server.jsx::Card` from seven RSCs
 * today, and that Card is slated to become a Panel.  This module has no
 * "use client" directive, so it adopts its importer's environment; a
 * single useState/useId here turns every server consumer into a
 * render-time crash.  That is exactly what happened when `collapsible`
 * was first added, which is why the state now lives in
 * CollapsiblePanel below the boundary instead.
 * Pinned by __tests__/components/ds/panel-server-safe.test.js.
 */
import React from "react";
import { Icon } from "./Icon";

export function Panel({
  title,
  subtitle,
  actions,
  footer,
  flush = false,
  dense = false,
  headingLevel = 2,
  as: Tag = "section",
  className = "",
  collapsible = false,
  collapsed = false,
  onToggleCollapsed,
  bodyId,
  children,
  ...rest
}) {
  const Heading = `h${Math.min(6, Math.max(2, headingLevel))}`;
  // A disclosure with nothing to label it is worse than none at all.
  const canCollapse = collapsible && Boolean(title);
  const isCollapsed = canCollapse && collapsed;
  const classes = [
    "ds-panel",
    dense ? "ds-panel--dense" : "",
    flush ? "ds-panel--flush" : "",
    isCollapsed ? "ds-panel--collapsed" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const headingNode = title ? (
    <Heading className="ds-panel__title">
      {canCollapse ? (
        <button
          type="button"
          className="ds-panel__disclosure"
          aria-expanded={!isCollapsed}
          aria-controls={bodyId}
          onClick={onToggleCollapsed}
        >
          <Icon
            name="chevron-down"
            size={10}
            className="ds-panel__disclosure-glyph"
          />
          {title}
        </button>
      ) : (
        title
      )}
    </Heading>
  ) : null;

  return (
    <Tag className={classes} {...rest}>
      {title || actions ? (
        <header className="ds-panel__header">
          <div className="ds-panel__heading">
            {headingNode}
            {subtitle && !isCollapsed ? (
              <p className="ds-panel__subtitle">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="ds-panel__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="ds-panel__body" id={bodyId} hidden={isCollapsed || undefined}>
        {children}
      </div>
      {footer && !isCollapsed ? (
        <footer className="ds-panel__footer">{footer}</footer>
      ) : null}
    </Tag>
  );
}
