"use client";

import { useEffect } from "react";

/**
 * Global error boundary — catches unhandled client-side exceptions and
 * renders a recovery UI instead of the generic Next.js crash page.
 *
 * Next.js App Router automatically wraps each route segment in a React
 * error boundary.  Placing this at app/error.jsx covers all pages.
 */
export default function GlobalError({ error, reset }) {
  useEffect(() => {
    // Log the error for debugging (visible in browser console)
    console.error("[GlobalError] Unhandled client error:", error);
  }, [error]);

  return (
    <section style={{ padding: "40px 20px", maxWidth: 600, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.3rem", marginBottom: 12 }}>Something went wrong</h1>
      <p style={{ color: "#999", fontSize: "0.88rem", marginBottom: 16 }}>
        A client-side error occurred. This is usually temporary.
      </p>

      {/* Show the actual error message for debugging */}
      <pre
        style={{
          background: "#1a1a1a",
          border: "1px solid #333",
          borderRadius: 6,
          padding: 12,
          fontSize: "0.76rem",
          color: "#f87171",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
          marginBottom: 16,
          maxHeight: 200,
          overflow: "auto",
        }}
      >
        {error?.message || "Unknown error"}
        {error?.digest ? `\nDigest: ${error.digest}` : ""}
      </pre>

      <div style={{ display: "flex", gap: 10 }}>
        <button
          onClick={reset}
          style={{
            padding: "8px 16px",
            borderRadius: 6,
            border: "1px solid #444",
            background: "#222",
            color: "#fff",
            cursor: "pointer",
            fontSize: "0.82rem",
          }}
        >
          Try again
        </button>
        <button
          onClick={() => (window.location.href = "/")}
          style={{
            padding: "8px 16px",
            borderRadius: 6,
            border: "1px solid #444",
            background: "transparent",
            color: "#999",
            cursor: "pointer",
            fontSize: "0.82rem",
          }}
        >
          Go home
        </button>
      </div>
    </section>
  );
}
