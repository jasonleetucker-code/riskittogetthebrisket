/**
 * Button — the one interactive-action primitive.
 *
 * Variants (visual weight, not color soup):
 *   primary   — gold fill. ONE per view region; the single most important
 *               action on screen. Never two primaries side-by-side.
 *   secondary — outlined. Default for everything else.
 *   ghost     — borderless. Toolbars, table row actions, dense UI.
 *   danger    — destructive confirmation only (outlined red, calm).
 *
 * Props:
 *   variant   "primary" | "secondary" | "ghost" | "danger"   (secondary)
 *   size      "md" | "sm"                                     (md)
 *   loading   boolean — shows spinner, disables, keeps width stable
 *   icon      ReactNode — leading glyph slot (use <Icon />)
 *   as        element type override (e.g. Next <Link>) — keeps styling
 *   ...rest   forwarded to the underlying element (type defaults "button")
 *
 * A11y: real <button> by default; focus ring via :focus-visible; loading
 * state sets aria-busy and disables activation.
 */
"use client";

import React from "react";

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon = null,
  as: Tag = "button",
  className = "",
  children,
  disabled,
  type,
  ...rest
}) {
  const classes = [
    "ds-btn",
    `ds-btn--${variant}`,
    size === "sm" ? "ds-btn--sm" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");
  const isButton = Tag === "button";
  return (
    <Tag
      className={classes}
      disabled={isButton ? disabled || loading : undefined}
      aria-disabled={!isButton && (disabled || loading) ? true : undefined}
      aria-busy={loading || undefined}
      type={isButton ? type || "button" : undefined}
      {...rest}
    >
      {loading ? (
        <span className="ds-btn__spinner" aria-hidden="true" />
      ) : (
        icon
      )}
      {children}
    </Tag>
  );
}
