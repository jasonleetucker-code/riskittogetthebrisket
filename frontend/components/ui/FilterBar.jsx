"use client";

/**
 * FilterBar — horizontal row of filter controls (inputs, selects, buttons).
 * Wraps children in a standard flex row with consistent spacing.
 *
 * Props:
 *   children — form controls
 *   style    — optional additional styles
 */
export default function FilterBar({ children, style }) {
  return (
    <div className="filter-bar" style={style}>
      {children}
    </div>
  );
}
