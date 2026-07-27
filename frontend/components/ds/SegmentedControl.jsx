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
 *
 * INDETERMINATE STATE (contract, relied on by callers): a `value`
 * matching no option leaves every option unchecked rather than
 * highlighting the first one. `/rankings` and `/trade` pass `null`
 * deliberately while `useSettings` is still hydrating, so the control
 * never claims a value basis the user did not choose. The DOM and its
 * dimensions are unchanged, so nothing shifts when the real value lands.
 *
 * `checkedIndex` and `activeIndex` are separate on purpose and the
 * distinction is easy to collapse by accident. `aria-checked` (and the
 * styling that hangs off it) follows `checkedIndex`, which is -1 when
 * nothing matches. `activeIndex` is only the roving-tabindex landing
 * spot and floors at 0, so an indeterminate group still has exactly one
 * tab stop instead of becoming keyboard-unreachable. Wiring
 * `aria-checked` to `activeIndex` would look like a tidy-up and would
 * silently reintroduce a confident highlight on an unknown value.
 */
"use client";

import React, { useRef } from "react";

export function SegmentedControl({ options, value, onChange, label, className = "" }) {
  const refs = useRef([]);
  const checkedIndex = options.findIndex((o) => o.value === value);
  // Focus/arrow-key math still needs a landing spot when nothing is
  // checked, so the roving tabindex falls to the first option — the
  // control stays keyboard-reachable while indeterminate.
  const activeIndex = checkedIndex >= 0 ? checkedIndex : 0;

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
        const checked = i === checkedIndex;
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
