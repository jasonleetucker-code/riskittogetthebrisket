/**
 * Select — styled native <select> (keeps OS behavior, keyboard, mobile
 * pickers) with a CSS-drawn chevron. Pair with <Field> for labelling.
 *
 * Usage:
 *   <Field label="Position">
 *     <Select value={pos} onChange={...} options={[
 *       { value: "QB", label: "Quarterback" },
 *       { value: "RB", label: "Running back" },
 *     ]} />
 *   </Field>
 *
 * Props: options [{value, label, disabled?}] OR <option> children; any
 * native select prop forwards.
 */
"use client";

import React from "react";

export function Select({ options, className = "", children, ...rest }) {
  return (
    <span className="ds-select-wrap">
      <select className={`ds-select ${className}`.trim()} {...rest}>
        {options
          ? options.map((opt) => (
              <option
                key={String(opt.value)}
                value={opt.value}
                disabled={opt.disabled}
              >
                {opt.label ?? opt.value}
              </option>
            ))
          : children}
      </select>
    </span>
  );
}
