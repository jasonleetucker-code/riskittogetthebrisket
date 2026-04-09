"use client";

/**
 * SubNav — horizontal tab bar for secondary navigation within a page.
 * Used for league sub-tabs, roster views, trade history views, etc.
 *
 * Props:
 *   items   — [{ key, label }]
 *   active  — current active key
 *   onChange — (key) => void
 */
export default function SubNav({ items = [], active, onChange }) {
  return (
    <div className="sub-nav">
      {items.map((item) => (
        <button
          key={item.key}
          className={`sub-nav-btn${active === item.key ? " active" : ""}`}
          onClick={() => onChange?.(item.key)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
