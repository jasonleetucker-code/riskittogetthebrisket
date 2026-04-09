"use client";

import { useEffect, useState } from "react";

/**
 * Toast — brief dismissable notification.
 *
 * Props:
 *   message  — text to display (null/empty hides)
 *   duration — ms before auto-dismiss (default 2500)
 *   variant  — "info" | "success" | "error" (default "info")
 */
export default function Toast({ message, duration = 2500, variant = "info" }) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!message) {
      setVisible(false);
      return;
    }
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), duration);
    return () => clearTimeout(timer);
  }, [message, duration]);

  if (!visible || !message) return null;

  const variantClass =
    variant === "success" ? "toast-success" : variant === "error" ? "toast-error" : "toast-info";

  return (
    <div className={`toast ${variantClass}`} role="status" aria-live="polite">
      {message}
    </div>
  );
}
