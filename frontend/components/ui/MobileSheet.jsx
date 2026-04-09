"use client";

import { useCallback, useEffect, useRef } from "react";

/**
 * MobileSheet — bottom sheet overlay for mobile interactions.
 * Used for filter panels, sort options, editors, confirmations.
 *
 * Props:
 *   isOpen   — whether the sheet is visible
 *   onClose  — () => void
 *   title    — optional header text
 *   children — sheet content
 */
export default function MobileSheet({ isOpen, onClose, title, children }) {
  const sheetRef = useRef(null);

  const handleOverlayClick = useCallback(
    (e) => {
      if (e.target === e.currentTarget) onClose?.();
    },
    [onClose],
  );

  useEffect(() => {
    if (!isOpen) return;
    function onKey(e) {
      if (e.key === "Escape") onClose?.();
    }
    document.addEventListener("keydown", onKey);
    // Prevent body scroll while sheet is open
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div className="sheet-overlay" onClick={handleOverlayClick}>
      <div className="sheet" ref={sheetRef} role="dialog" aria-label={title || "Panel"}>
        <div className="sheet-handle" />
        {title && <div className="sheet-title">{title}</div>}
        <div className="sheet-body">{children}</div>
      </div>
    </div>
  );
}
