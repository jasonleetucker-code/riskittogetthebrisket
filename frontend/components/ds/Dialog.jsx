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
 *   initialFocus optional ref — element to receive initial focus
 *                (default: first focusable, e.g. the close button)
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

// Module-level overlay registry. Stacked dialogs (Modal over Drawer) each
// register a document-capture keydown listener, and stopPropagation does
// NOT stop sibling listeners on the same target — so without coordination
// one Escape closes every open overlay, and competing scroll-lock
// cleanups can strand body overflow.
//
// Topmost-ness is derived from DOCUMENT ORDER, not registration order:
// React runs a child's effect before its parent's, so a Modal nested in
// a Drawer's children would register FIRST and a push-order stack would
// wrongly crown the Drawer. Document order is the paint order for the
// same-z overlay roots (later sibling paints above; a nested overlay is
// a descendant and always follows its host), so "last connected overlay
// element in document order" is the visually topmost dialog in every
// composition. The scroll lock is reference-counted: body overflow is
// saved at the first registration and restored only when the registry
// empties.
const overlayRegistry = new Set();
let savedBodyOverflow = null;

function registerOverlay(token) {
  if (overlayRegistry.size === 0) {
    savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
  }
  overlayRegistry.add(token);
}

function unregisterOverlay(token) {
  overlayRegistry.delete(token);
  if (overlayRegistry.size === 0) {
    document.body.style.overflow = savedBodyOverflow ?? "";
    savedBodyOverflow = null;
  }
}

function isTopOverlay(token) {
  let top = null;
  let topEl = null;
  for (const t of overlayRegistry) {
    const el = t.getEl();
    if (!el || !el.isConnected) continue;
    if (
      !topEl ||
      topEl.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING
    ) {
      top = t;
      topEl = el;
    }
  }
  return top === token;
}

function useDialog({ open, onClose, panelRef, initialFocusRef }) {
  const restoreRef = useRef(null);
  // Hold onClose in a ref so an inline callback from a re-rendering
  // parent never restarts the open-lifecycle effect below (which would
  // steal focus from a controlled input inside the dialog on every
  // keystroke: cleanup restores focus to the opener, setup refocuses
  // the first control). The effect depends on [open] + stable refs only.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return undefined;
    const token = { getEl: () => panelRef.current };
    registerOverlay(token);
    restoreRef.current = document.activeElement;
    const panel = panelRef.current;
    // initial focus: caller-designated element (initialFocus prop, e.g.
    // a palette's input), else first focusable, else the panel itself
    const preferred = initialFocusRef?.current;
    const first = panel?.querySelector(FOCUSABLE);
    (preferred || first || panel)?.focus();

    const onKeyDown = (e) => {
      // Only the TOPMOST overlay reacts — a stacked Modal's Escape must
      // not also close the Drawer beneath it.
      if (!isTopOverlay(token)) return;
      if (e.key === "Escape") {
        e.stopPropagation();
        onCloseRef.current?.();
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
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      unregisterOverlay(token); // releases the scroll lock only when registry empties
      restoreRef.current?.focus?.();
    };
  }, [open, panelRef]);
}

function DialogShell({
  open,
  onClose,
  title,
  srOnlyTitle = false,
  variant, // "modal" | "drawer"
  initialFocus = null, // optional ref: element to receive initial focus
  closeLabel = "Close", // accessible name for the close button
  className = "", // extra class on the panel (width overrides etc.)
  children,
}) {
  const panelRef = useRef(null);
  const titleId = useId();
  useDialog({ open, onClose, panelRef, initialFocusRef: initialFocus });

  if (!open) return null;

  const panel = (
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      className={`${variant === "drawer" ? "ds-drawer" : "ds-modal__panel"} ${className}`.trim()}
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
          <Icon name="close" size={16} label={closeLabel} />
        </button>
      </header>
      <div className="ds-dialog__body">{children}</div>
    </div>
  );

  // ONE root per overlay = one stacking context holding BOTH the backdrop
  // and the panel. With the old flat structure every panel shared
  // --z-modal and every backdrop --z-overlay, so a sibling Modal's
  // backdrop painted BELOW an earlier Drawer's panel, leaving the covered
  // Drawer clickable. Same-z sibling roots paint in document order (later
  // root — backdrop included — above the entire earlier overlay), and a
  // nested overlay is a descendant of its host's root, so it always
  // paints above the host. This matches the document-order authority
  // isTopOverlay() uses for Escape.
  return (
    <div className="ds-overlay-root">
      <div className="ds-backdrop" onClick={onClose} aria-hidden="true" />
      {variant === "drawer" ? (
        panel
      ) : (
        <div className="ds-modal">{panel}</div>
      )}
    </div>
  );
}

export function Modal(props) {
  return <DialogShell {...props} variant="modal" />;
}

export function Drawer(props) {
  return <DialogShell {...props} variant="drawer" />;
}
