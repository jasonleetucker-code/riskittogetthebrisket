"use client";

/**
 * EmptyState — shown when a list or table has no data.
 *
 * Props:
 *   title   — heading text
 *   message — explanatory text
 *   action  — optional { label, onClick } for a CTA button
 */
export default function EmptyState({ title = "No data", message, action }) {
  return (
    <div className="empty-state">
      <p className="empty-state-title">{title}</p>
      {message && <p className="muted">{message}</p>}
      {action && (
        <button className="button" onClick={action.onClick} style={{ marginTop: 10 }}>
          {action.label}
        </button>
      )}
    </div>
  );
}
