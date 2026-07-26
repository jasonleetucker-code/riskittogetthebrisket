/**
 * Icon — the design system's internal SVG glyph set.
 *
 * The audit found the app's iconography is ASCII ("H"/"R"/"T"/"M" nav
 * letters, "▲▼" sort glyphs, "+/−" toggles, 7 emoji). This module is the
 * replacement language: a tiny, stroke-based, currentColor glyph set.
 * No icon font, no external dependency, ~a few hundred bytes each.
 *
 * Usage:
 *   <Icon name="arrow-up" size={12} />
 *   <Icon name="close" label="Close" />   // labelled = role img
 *
 * Icons are decorative by default (aria-hidden). Pass `label` only when
 * the icon is the sole content of its control.
 */
"use client";

import React from "react";

const PATHS = {
  "arrow-up": <path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" />,
  "arrow-down": <path d="M8 3v10M3.5 8.5 8 13l4.5-4.5" />,
  "arrow-right": <path d="M3 8h10M8.5 3.5 13 8l-4.5 4.5" />,
  "chevron-down": <path d="M3.5 6 8 10.5 12.5 6" />,
  "chevron-up": <path d="M3.5 10 8 5.5 12.5 10" />,
  "chevron-right": <path d="M6 3.5 10.5 8 6 12.5" />,
  close: <path d="M4 4l8 8M12 4l-8 8" />,
  check: <path d="M3 8.5 6.5 12 13 4.5" />,
  dash: <path d="M4 8h8" />,
  search: (
    <>
      <circle cx="7" cy="7" r="4.25" />
      <path d="m10.5 10.5 3 3" />
    </>
  ),
  info: (
    <>
      <circle cx="8" cy="8" r="6.25" />
      <path d="M8 7.5V11M8 5.2v.1" />
    </>
  ),
  warning: (
    <>
      <path d="M8 2.5 14.5 13.5H1.5L8 2.5Z" />
      <path d="M8 6.8v3M8 12v.1" />
    </>
  ),
  // Shell / navigation glyphs (R1)
  home: <path d="M2.8 7.2 8 2.8l5.2 4.4V13a.8.8 0 0 1-.8.8H9.8V9.6H6.2v4.2H3.6a.8.8 0 0 1-.8-.8V7.2Z" />,
  board: (
    <>
      <path d="M2.5 4h11M2.5 8h11M2.5 12h11" />
    </>
  ),
  swap: (
    <>
      <path d="M2.8 5.5h9.4M9.8 3l2.8 2.5-2.8 2.5" />
      <path d="M13.2 10.5H3.8M6.2 8 3.4 10.5 6.2 13" />
    </>
  ),
  news: (
    <>
      <path d="M3 3h8.5v10H3.8A.8.8 0 0 1 3 12.2V3Z" />
      <path d="M11.5 6H13v6.2a.8.8 0 0 1-.8.8h-.7" />
      <path d="M5 6h4.5M5 8.5h4.5M5 11h3" />
    </>
  ),
  menu: <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />,
  star: (
    <path d="M8 1.8 9.9 5.7l4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6L8 1.8Z" />
  ),
  "star-filled": (
    <path
      d="M8 1.8 9.9 5.7l4.3.6-3.1 3 .7 4.3L8 11.6l-3.8 2 .7-4.3-3.1-3 4.3-.6L8 1.8Z"
      fill="currentColor"
    />
  ),
  gear: (
    <>
      <circle cx="8" cy="8" r="2.2" />
      <path d="M8 1.8v2M8 12.2v2M1.8 8h2M12.2 8h2M3.6 3.6l1.4 1.4M11 11l1.4 1.4M12.4 3.6 11 5M5 11l-1.4 1.4" />
    </>
  ),
};

export const ICON_NAMES = Object.keys(PATHS);

export function Icon({ name, size = 16, label, className, style }) {
  const glyph = PATHS[name];
  if (!glyph) return null;
  return (
    <svg
      viewBox="0 0 16 16"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={label ? undefined : "true"}
      role={label ? "img" : undefined}
      aria-label={label}
      className={className}
      style={style}
      focusable="false"
    >
      {glyph}
    </svg>
  );
}
