"use client";

// One-click "Share this" button that copies the canonical page URL
// (and optional share-text snippet) to the clipboard.  Used on
// franchise, rivalry, matchup, and player routes — pairs with the
// OG metadata those routes already emit so Slack/iMessage/Twitter
// previews render a rich card.
//
// Falls back to a prompt() if clipboard API is unavailable (older
// browsers or non-HTTPS contexts).

import { useCallback, useState } from "react";

export default function ShareButton({
  label = "Share",
  path = "",
  text = "",
  style,
}) {
  const [state, setState] = useState("idle"); // idle | copied | error

  const handleClick = useCallback(async () => {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    const url = path ? `${origin}${path}` : (typeof window !== "undefined" ? window.location.href : "");
    const payload = text ? `${text}\n${url}` : url;

    try {
      if (typeof navigator !== "undefined" && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(payload);
      } else if (typeof window !== "undefined") {
        // Fallback for non-secure contexts.
        window.prompt("Copy this link:", payload);
      }
      setState("copied");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
  }, [path, text]);

  const displayLabel =
    state === "copied" ? "Copied!" : state === "error" ? "Copy failed" : label;
  const color =
    state === "copied" ? "var(--green)" : state === "error" ? "var(--red)" : "var(--cyan)";

  return (
    <button
      type="button"
      onClick={handleClick}
      aria-live="polite"
      style={{
        background: "transparent",
        border: "1px solid var(--border-bright)",
        borderRadius: 6,
        color,
        padding: "4px 10px",
        fontSize: "0.72rem",
        fontWeight: 600,
        cursor: "pointer",
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        ...(style || {}),
      }}
      title="Copy shareable link"
    >
      <span aria-hidden style={{ opacity: 0.8 }}>↗</span>
      {displayLabel}
    </button>
  );
}
