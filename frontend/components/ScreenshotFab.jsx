"use client";

import { useState } from "react";
import Toast from "@/components/ui/Toast";

function canShareFiles(file) {
  // navigator.canShare can throw synchronously on some iOS PWA contexts.
  // Swallow that — feature-detection must never propagate.
  try {
    return !!(navigator.share && navigator.canShare?.({ files: [file] }));
  } catch {
    return false;
  }
}

function isIOSDevice() {
  if (typeof navigator === "undefined") return false;
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

export default function ScreenshotFab() {
  const [capturing, setCapturing] = useState(false);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [toast, setToast] = useState({ message: null, nonce: 0 });

  function showToast(message) {
    setToast({ message, nonce: Date.now() });
  }

  function closePreview() {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
  }

  async function takeScreenshot() {
    if (capturing) return;
    setCapturing(true);
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
        imageTimeout: 5000,
      });

      // Resolve toBlob as a simple awaitable. All share/fallback logic
      // lives in the outer try below so synchronous throws (e.g. iOS
      // canShare) always reach the outer catch and the finally block.
      const blob = await new Promise((resolve, reject) => {
        canvas.toBlob(
          (b) => (b ? resolve(b) : reject(new Error("canvas toBlob returned null"))),
          "image/png",
        );
      });

      const filename = `chaseupside-${new Date().toISOString().slice(0, 10)}.png`;
      const file = new File([blob], filename, { type: "image/png" });

      // Prefer Web Share API with files (iOS 15+ / Android — share sheet
      // includes "Save Image" → camera roll).
      if (canShareFiles(file)) {
        try {
          await navigator.share({ files: [file], title: "Chase Upside Rankings" });
          return;
        } catch (err) {
          if (err?.name === "AbortError") return; // user dismissed
          // Other errors — fall through to in-app overlay so the user
          // always has a way to save.
        }
      }

      const url = URL.createObjectURL(blob);
      if (isIOSDevice()) {
        // a.download doesn't save to camera roll on iOS — it just opens
        // the file in the browser. Show the image inline so the user
        // can long-press → "Save to Photos".
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
    } catch (err) {
      console.error("Screenshot failed:", err);
      showToast("Screenshot failed — try again");
    } finally {
      setCapturing(false);
    }
  }

  return (
    <>
      <button
        type="button"
        className={`screenshot-fab${capturing ? " screenshot-fab--busy" : ""}`}
        onClick={takeScreenshot}
        disabled={capturing}
        aria-label="Save page as image"
        title="Screenshot this page"
        data-html2canvas-ignore
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
        <div
          className="screenshot-preview-overlay"
          onClick={closePreview}
          data-html2canvas-ignore
        >
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

      <Toast
        key={toast.nonce}
        message={toast.message}
        variant="error"
        duration={3500}
      />
    </>
  );
}
