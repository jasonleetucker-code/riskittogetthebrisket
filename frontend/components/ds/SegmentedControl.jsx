/**
 * SegmentedControl — exclusive choice among 2-5 short options (view
 * density, time window, position filter). For >5 options use <Select>;
 * for navigation between panels use <Tabs>.
 *
 * Usage:
 *   <SegmentedControl
 *     label="Window"
 *     value={win}
 *     onChange={setWin}
 *     options={[{ value: "1d" }, { value: "7d" }, { value: "30d" }]}
 *   />
 *
 * Props: options [{value, label?}], value, onChange(value), label
 * (accessible name for the group), size.
 *
 * A11y: radiogroup semantics — one tab stop, Arrow keys move + select,
 * aria-checked marks the active option (styling hangs off it).
 */
"use client";

import React, { useRef } from "react";

export function SegmentedControl({ options, value, onChange, label, className = "" }) {
  const refs = useRef([]);
  const activeIndex = Math.max(
    0,
    options.findIndex((o) => o.value === value)
  );

  const move = (delta) => {
    const next = (activeIndex + delta + options.length) % options.length;
    onChange?.(options[next].value);
    refs.current[next]?.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      move(1);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      move(-1);
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`ds-segmented ${className}`.trim()}
      onKeyDown={onKeyDown}
    >
      {options.map((opt, i) => {
        const checked = opt.value === value;
        return (
          <button
            key={String(opt.value)}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={i === activeIndex ? 0 : -1}
            className="ds-segmented__option"
            onClick={() => onChange?.(opt.value)}
          >
            {opt.label ?? opt.value}
          </button>
        );
      })}
    </div>
  );
}
