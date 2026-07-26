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
 * state sets aria-busy and disables activation. When `as` renders a link
 * (or any non-button), disabled/loading make it genuinely inert, not just
 * aria-labelled: activation is intercepted (no navigation, no consumer
 * onClick), tabIndex={-1} removes it from the tab order per WAI-ARIA
 * practices for disabled links, and a plain <a> additionally drops its
 * href (custom link components like Next <Link> keep href because they
 * require it, but the click interception blocks their navigation).
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
  onClick,
  href,
  tabIndex,
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
  const inert = Boolean(disabled || loading);
  const inertNonButton = !isButton && inert;

  const handleClick = inertNonButton
    ? (e) => {
        // Disabled link: swallow activation entirely.
        e.preventDefault();
        e.stopPropagation();
      }
    : onClick;

  return (
    <Tag
      className={classes}
      disabled={isButton ? inert : undefined}
      aria-disabled={inertNonButton ? true : undefined}
      aria-busy={loading || undefined}
      type={isButton ? type || "button" : undefined}
      onClick={handleClick}
      // Plain <a> can safely lose its href (also drops it from the tab
      // order natively); custom components (Next Link) require href, so
      // they keep it and rely on the interception + tabIndex.
      href={inertNonButton && Tag === "a" ? undefined : href}
      tabIndex={inertNonButton ? -1 : tabIndex}
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
