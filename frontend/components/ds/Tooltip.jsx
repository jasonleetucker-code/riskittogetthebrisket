/**
 * Tooltip — supplementary text on hover AND keyboard focus. For anything
 * interactive-in-the-tooltip, use a popover/Dialog instead — tooltips are
 * text-only by design.
 *
 * Usage:
 *   <Tooltip content="Blended value across enabled sources">
 *     <Button variant="ghost" size="sm">Value</Button>
 *   </Tooltip>
 *
 * Props: content (text/inline nodes), side "top"|"bottom" (default top),
 * children — a single focusable element.
 *
 * A11y: links via aria-describedby (role=tooltip), shows on focus,
 * hides on Escape/blur; pointer-events none so it never traps the mouse.
 * If the wrapped control already carries aria-describedby (e.g. a Field
 * hint/error), the tooltip id is MERGED onto it while open — existing
 * guidance is never disconnected — and the original value is restored
 * on close.
 */
"use client";

import React, { useId, useState } from "react";

export function Tooltip({ content, side = "top", children }) {
  const id = useId();
  const [open, setOpen] = useState(false);

  const child = React.Children.only(children);
  const existingDescribedBy = child.props["aria-describedby"];
  const trigger = React.cloneElement(child, {
    "aria-describedby": open
      ? [existingDescribedBy, id].filter(Boolean).join(" ")
      : existingDescribedBy,
    onMouseEnter: (e) => {
      child.props.onMouseEnter?.(e);
      setOpen(true);
    },
    onMouseLeave: (e) => {
      child.props.onMouseLeave?.(e);
      setOpen(false);
    },
    onFocus: (e) => {
      child.props.onFocus?.(e);
      setOpen(true);
    },
    onBlur: (e) => {
      child.props.onBlur?.(e);
      setOpen(false);
    },
    onKeyDown: (e) => {
      child.props.onKeyDown?.(e);
      if (e.key === "Escape") setOpen(false);
    },
  });

  return (
    <span className="ds-tooltip-anchor">
      {trigger}
      <span
        role="tooltip"
        id={id}
        className={[
          "ds-tooltip",
          side === "bottom" ? "ds-tooltip--bottom" : "",
          open ? "ds-tooltip--visible" : "",
        ]
          .filter(Boolean)
          .join(" ")}
        hidden={!open || undefined}
      >
        {content}
      </span>
    </span>
  );
}
