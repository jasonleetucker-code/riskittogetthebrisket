/**
 * Help — on-demand explanation, so methodology stops eating the page.
 *
 * The product explains itself in permanent prose: a 365-line glossary
 * open by default on /draft, a 5-paragraph essay above a select on
 * /settings, eight footnotes on /edge, a 3-sentence description under
 * half the page titles.  All of it is worth keeping and none of it
 * needs to be on screen before the user asks.
 *
 * Two primitives, chosen by size:
 *
 *   <InfoTip>    a sentence or two — attaches to the thing it explains
 *                (a panel title, a column header, a control label).
 *   <HelpModal>  multi-section methodology — a labelled button that
 *                opens ds <Modal>.
 *
 * WHY NOT ds <Tooltip>: that one shows on hover and focus, which is
 * correct for supplementary hints on a control you can already use, but
 * a touch user cannot hover and the explanations being moved here are
 * the primary way to understand the number next to them.  InfoTip is
 * click/tap-driven with a real button, so every pointer type gets the
 * same affordance.  Hover-open is deliberately NOT added: a popover
 * that opens on hover and closes on mouse-out is unusable for the thing
 * people do with these — read a paragraph, then look back at the table.
 *
 * A11y: the trigger is a <button> carrying aria-expanded + aria-controls
 * and an explicit label ("What is <topic>?"), so a screen reader
 * announces purpose rather than "button, i".  Escape closes and returns
 * focus; an outside click closes.  The popover is a labelled region, not
 * role="tooltip" — tooltip semantics forbid the interactive content
 * (links to methodology pages) some of these carry.
 */
"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";
import { Modal } from "./Dialog";

/**
 * Props:
 *   label     what this explains — used to build the trigger's
 *             accessible name and the popover's heading (required)
 *   children  the explanation
 *   side      "top" | "bottom" — popover edge (default bottom)
 */
export function InfoTip({ label, children, side = "bottom", className = "" }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const triggerRef = useRef(null);

  const close = useCallback(
    ({ refocus = false } = {}) => {
      setOpen(false);
      if (refocus) triggerRef.current?.focus();
    },
    [],
  );

  // Outside click + Escape. Bound only while open so a page full of
  // InfoTips isn't a page full of idle document listeners.
  useEffect(() => {
    if (!open) return undefined;
    function onDocPointerDown(e) {
      if (!wrapRef.current?.contains(e.target)) setOpen(false);
    }
    function onDocKeyDown(e) {
      if (e.key === "Escape") {
        e.stopPropagation();
        close({ refocus: true });
      }
    }
    document.addEventListener("pointerdown", onDocPointerDown);
    document.addEventListener("keydown", onDocKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onDocPointerDown);
      document.removeEventListener("keydown", onDocKeyDown);
    };
  }, [open, close]);

  return (
    <span className={`ds-infotip ${className}`.trim()} ref={wrapRef}>
      <button
        ref={triggerRef}
        type="button"
        className="ds-infotip__trigger"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`What is ${label}?`}
        onClick={() => setOpen((v) => !v)}
      >
        <Icon name="info" size={12} aria-hidden="true" />
      </button>
      {open ? (
        <span
          id={id}
          role="region"
          aria-label={label}
          className={`ds-infotip__popover${side === "top" ? " ds-infotip__popover--top" : ""}`}
        >
          {children}
        </span>
      ) : null}
    </span>
  );
}

/**
 * HelpModal — a "How this works" button plus the dialog it opens.
 *
 * For explanations too long to read in a popover: the rankings
 * methodology, the draft glossary, per-source weighting.  ds <Modal>
 * already provides role=dialog, focus trap, Escape, scroll lock and
 * focus restore.
 *
 * Props:
 *   title     dialog heading (required)
 *   children  the explanation
 *   label     trigger text (default "How this works")
 *   variant / size  forwarded to Button (default ghost / sm)
 */
export function HelpModal({
  title,
  children,
  label = "How this works",
  variant = "ghost",
  size = "sm",
  className = "",
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant={variant}
        size={size}
        className={className}
        onClick={() => setOpen(true)}
        icon={<Icon name="info" size={12} aria-hidden="true" />}
      >
        {label}
      </Button>
      <Modal open={open} onClose={() => setOpen(false)} title={title}>
        <div className="ds-help-body">{children}</div>
      </Modal>
    </>
  );
}
