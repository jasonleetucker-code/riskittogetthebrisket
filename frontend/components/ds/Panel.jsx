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
 * Props:
 *   title      ReactNode — rendered as a heading (level via headingLevel, default h2)
 *   subtitle   ReactNode — one quiet line under the title
 *   actions    ReactNode — right-aligned header slot
 *   footer     ReactNode
 *   flush      boolean — zero body padding (tables, charts, lists)
 *   dense      boolean — tighter header/body padding for rail/grid use
 *   headingLevel 2|3|4 — keep the page outline honest
 *   as         element type (default "section")
 */
import React from "react";

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
  children,
  ...rest
}) {
  const Heading = `h${Math.min(6, Math.max(2, headingLevel))}`;
  const classes = [
    "ds-panel",
    dense ? "ds-panel--dense" : "",
    flush ? "ds-panel--flush" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <Tag className={classes} {...rest}>
      {title || actions ? (
        <header className="ds-panel__header">
          <div className="ds-panel__heading">
            {title ? <Heading className="ds-panel__title">{title}</Heading> : null}
            {subtitle ? <p className="ds-panel__subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="ds-panel__actions">{actions}</div> : null}
        </header>
      ) : null}
      <div className="ds-panel__body">{children}</div>
      {footer ? <footer className="ds-panel__footer">{footer}</footer> : null}
    </Tag>
  );
}
