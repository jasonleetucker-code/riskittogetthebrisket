"use client";

/**
 * PageHeader — standard page title + subtitle block.
 *
 * Props:
 *   title     — h1 text
 *   subtitle  — optional description
 *   actions   — optional ReactNode rendered to the right
 */
export default function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="page-header">
      <div className="page-header-text">
        <h1 className="page-title">{title}</h1>
        {subtitle && <p className="page-subtitle muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-header-actions">{actions}</div>}
    </div>
  );
}
