"use client";

/**
 * LoadingState — standard loading indicator for page/card content.
 *
 * Props:
 *   message — optional loading message (default: "Loading...")
 *   compact — if true, smaller inline variant
 */
export default function LoadingState({ message = "Loading...", compact = false }) {
  if (compact) {
    return <span className="loading-inline muted">{message}</span>;
  }
  return (
    <div className="loading-state">
      <div className="loading-spinner" />
      <p className="muted">{message}</p>
    </div>
  );
}
