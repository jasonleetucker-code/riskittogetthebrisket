/**
 * PageHeader — the ONE page-title pattern. Every page renders exactly one,
 * and it owns the page's single <h1> (the audit found 4 title systems and
 * 13 pages with no h1 at all).
 *
 * Usage:
 *   <PageHeader
 *     eyebrow="Market"
 *     title="Value board"
 *     description="Blended dynasty values across all sources."
 *     actions={<Button variant="primary">New trade</Button>}
 *   />
 *
 * Props: eyebrow (uppercase kicker, optional), title (required),
 * description, actions (right-aligned slot).
 *
 * Supersedes components/ui/PageHeader.jsx at migration time.
 */
import React from "react";

export function PageHeader({ eyebrow, title, description, actions, className = "" }) {
  return (
    <div className={`ds-page-header ${className}`.trim()}>
      <div>
        {eyebrow ? <p className="ds-page-header__eyebrow">{eyebrow}</p> : null}
        <h1 className="ds-page-header__title">{title}</h1>
        {description ? (
          <p className="ds-page-header__description">{description}</p>
        ) : null}
      </div>
      {actions ? <div className="ds-page-header__actions">{actions}</div> : null}
    </div>
  );
}
