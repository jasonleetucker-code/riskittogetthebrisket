"use client";

import { useRef, useState } from "react";

export default function ScreenshotFab() {
  const [capturing, setCapturing] = useState(false);
  const btnRef = useRef(null);

  async function takeScreenshot() {
    if (capturing) return;
    setCapturing(true);
    try {
      const { default: html2canvas } = await import("html2canvas");

      // Hide the FAB itself so it doesn't appear in the capture
      if (btnRef.current) btnRef.current.style.visibility = "hidden";

      // Compute a scale that stays within the iOS canvas area limit (~16.8 MP).
      // allowTaint is intentionally omitted (default false) — a tainted canvas
      // cannot be exported via toBlob(), so we skip non-CORS images instead.
      const MAX_CANVAS_AREA = 16_777_216;
      const rawW = document.documentElement.scrollWidth;
      const rawH = document.body.scrollHeight;
      const dprScale = Math.min(window.devicePixelRatio || 1, 2);
      const areaScale = Math.sqrt(MAX_CANVAS_AREA / (rawW * rawH));
      const scale = Math.min(dprScale, areaScale);

      const canvas = await html2canvas(document.body, {
        useCORS: true,
        scale,
        logging: false,
      });

      if (btnRef.current) btnRef.current.style.visibility = "";

      await new Promise((resolve, reject) => {
        canvas.toBlob(async (blob) => {
          if (!blob) { reject(new Error("canvas toBlob returned null")); return; }
          const filename = `brisket-${new Date().toISOString().slice(0, 10)}.png`;
          const file = new File([blob], filename, { type: "image/png" });
          try {
            if (navigator.share && navigator.canShare?.({ files: [file] })) {
              // iOS/Android: share sheet offers "Save to Photos" / camera roll
              await navigator.share({ files: [file], title: "Brisket Rankings" });
            } else {
              // Desktop fallback: trigger download
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = filename;
              document.body.appendChild(a);
              a.click();
              document.body.removeChild(a);
              URL.revokeObjectURL(url);
            }
            resolve();
          } catch (err) {
            // AbortError = user dismissed the share sheet — not an error
            if (err.name === "AbortError") resolve();
            else reject(err);
          }
        }, "image/png");
      });
    } catch (err) {
      if (btnRef.current) btnRef.current.style.visibility = "";
      console.error("Screenshot failed:", err);
    } finally {
      setCapturing(false);
    }
  }

  return (
    <button
      ref={btnRef}
      type="button"
      className={`screenshot-fab${capturing ? " screenshot-fab--busy" : ""}`}
      onClick={takeScreenshot}
      disabled={capturing}
      aria-label="Save page as image"
      title="Screenshot this page"
    >
      <span className="screenshot-fab-icon" aria-hidden="true">
        {capturing ? (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 4V2A10 10 0 0 0 2 12h2a8 8 0 0 1 8-8z">
              <animateTransform attributeName="transform" type="rotate" from="0 12 12" to="360 12 12" dur="0.8s" repeatCount="indefinite"/>
            </path>
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M9 2L7.17 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2h-3.17L15 2H9zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/>
          </svg>
        )}
      </span>
      <span className="screenshot-fab-label">
        {capturing ? "Saving…" : "Save"}
      </span>
    </button>
  );
}
