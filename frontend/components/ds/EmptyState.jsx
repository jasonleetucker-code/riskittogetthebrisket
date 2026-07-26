/**
 * EmptyState — the "nothing here" primitive. One quiet, consistent voice
 * for empty tables, empty searches, and not-yet-configured features.
 *
 * Usage:
 *   <EmptyState title="No trades yet"
 *               description="Analyzed league trades will appear here."
 *               action={<Button variant="secondary">Import history</Button>} />
 *
 * Props: title (required), description, action (ONE action max — an empty
 * state is not a menu), icon (optional <Icon/> slot).
 *
 * Supersedes components/ui/EmptyState.jsx at migration time.
 */
import React from "react";

export function EmptyState({ title, description, action, icon, className = "" }) {
  return (
    <div className={`ds-empty ${className}`.trim()}>
      {icon}
      <h3 className="ds-empty__title">{title}</h3>
      {description ? (
        <p className="ds-empty__description">{description}</p>
      ) : null}
      {action}
    </div>
  );
}
