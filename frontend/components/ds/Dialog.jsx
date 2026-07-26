/**
 * Modal + Drawer — the overlay primitives, with the dialog semantics the
 * audit found missing app-wide (PlayerPopup/GlobalSearch ship overlay divs
 * with no role, no focus trap, no restore).
 *
 * <Modal>  — centered dialog for focused decisions/confirmation.
 * <Drawer> — right-edge sheet for detail inspection (player detail,
 *            trade breakdown) where underlying context still matters.
 *
 * Shared props:
 *   open, onClose (required)
 *   title        ReactNode — dialog heading (required for a11y; pass
 *                srOnlyTitle to hide it visually)
 *   srOnlyTitle  boolean
 *   children     body content (scrolls)
 *
 * Behavior/a11y (both):
 *   - role="dialog" aria-modal="true", labelled by the title
 *   - focus moves into the dialog on open, Tab is trapped, focus RESTORES
 *     to the opener on close
 *   - Escape and backdrop click close; body scroll is locked while open
 *   - close button is a labelled icon button
 */
"use client";

import React, { useEffect, useId, useRef } from "react";
import { Icon } from "./Icon";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

function useDialog({ open, onClose, panelRef }) {
  const restoreRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    restoreRef.current = document.activeElement;
    const panel = panelRef.current;
    // initial focus: first focusable, else the panel itself
    const first = panel?.querySelector(FOCUSABLE);
    (first || panel)?.focus();

    const onKeyDown = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose?.();
        return;
      }
      if (e.key !== "Tab" || !panel) return;
      const nodes = Array.from(panel.querySelectorAll(FOCUSABLE)).filter(
        (n) => n.offsetParent !== null || n === document.activeElement
      );
      if (nodes.length === 0) {
        e.preventDefault();
        return;
      }
      const firstNode = nodes[0];
      const lastNode = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === firstNode) {
        e.preventDefault();
        lastNode.focus();
      } else if (!e.shiftKey && document.activeElement === lastNode) {
        e.preventDefault();
        firstNode.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      document.body.style.overflow = prevOverflow;
      restoreRef.current?.focus?.();
    };
  }, [open, onClose, panelRef]);
}

function DialogShell({
  open,
  onClose,
  title,
  srOnlyTitle = false,
  variant, // "modal" | "drawer"
  children,
}) {
  const panelRef = useRef(null);
  const titleId = useId();
  useDialog({ open, onClose, panelRef });

  if (!open) return null;

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className={variant === "drawer" ? "ds-drawer" : "ds-modal__panel"}
      tabIndex={-1}
    >
      <header className="ds-dialog__header">
        <h2
          id={titleId}
          className={
            srOnlyTitle ? "ds-visually-hidden" : "ds-dialog__title"
          }
        >
          {title}
        </h2>
        <button
          type="button"
          className="ds-dialog__close ds-focusable"
          onClick={onClose}
        >
          <Icon name="close" size={16} label="Close" />
        </button>
      </header>
      <div className="ds-dialog__body">{children}</div>
    </div>
  );

  return (
    <>
      <div className="ds-backdrop" onClick={onClose} aria-hidden="true" />
      {variant === "drawer" ? (
        panel
      ) : (
        <div className="ds-modal">{panel}</div>
      )}
    </>
  );
}

export function Modal(props) {
  return <DialogShell {...props} variant="modal" />;
}

export function Drawer(props) {
  return <DialogShell {...props} variant="drawer" />;
}
