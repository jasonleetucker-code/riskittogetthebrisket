"use client";

import { useRef, useState } from "react";

export default function ScreenshotFab() {
  const [capturing, setCapturing] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const btnRef = useRef(null);

  function closePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
  }

  async function takeScreenshot() {
    if (capturing) return;
    setCapturing(true);
    if (btnRef.current) btnRef.current.style.visibility = "hidden";
    try {
      const { default: html2canvas } = await import("html2canvas");

      // Keep canvas within Safari/WKWebView's practical ~5 MP limit.
      // allowTaint omitted (default false) — tainted canvases block toBlob().
      const MAX_CANVAS_AREA = 5_000_000;
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

      await new Promise((resolve, reject) => {
        canvas.toBlob(async (blob) => {
          if (!blob) { reject(new Error("canvas toBlob returned null")); return; }
          const filename = `brisket-${new Date().toISOString().slice(0, 10)}.png`;
          const file = new File([blob], filename, { type: "image/png" });

          // Try Web Share API with files first (iOS 15+ / Android).
          // The native share sheet includes "Save Image" → camera roll.
          if (navigator.share && navigator.canShare?.({ files: [file] })) {
            try {
              await navigator.share({ files: [file], title: "Brisket Rankings" });
              resolve();
              return;
            } catch (err) {
              if (err.name === "AbortError") { resolve(); return; }
              // Non-abort error — fall through to overlay
            }
          }

          // Fallback path:
          // iOS: a.download just opens the file in the browser and doesn't
          // save to camera roll. Instead, show the image in an overlay —
          // the user can long-press it → "Save to Photos".
          // Desktop: trigger a normal file download.
          const url = URL.createObjectURL(blob);
          const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
            (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
          if (isIOS) {
            setPreviewUrl(url);
          } else {
            const a = document.createElement("a");
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
          }
          resolve();
        }, "image/png");
      });
    } catch (err) {
      console.error("Screenshot failed:", err);
    } finally {
      if (btnRef.current) btnRef.current.style.visibility = "";
      setCapturing(false);
    }
  }

  return (
    <>
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

      {previewUrl && (
        <div className="screenshot-preview-overlay" onClick={closePreview}>
          <div className="screenshot-preview-inner" onClick={(e) => e.stopPropagation()}>
            <p className="screenshot-preview-hint">
              Hold the image &rarr; &ldquo;Save to Photos&rdquo;
            </p>
            <img
              src={previewUrl}
              alt="Page screenshot"
              className="screenshot-preview-img"
            />
            <button
              type="button"
              className="screenshot-preview-close"
              onClick={closePreview}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </>
  );
}
