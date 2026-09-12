"use client";

import { useCallback, useRef } from "react";
import { useReportWebVitals } from "next/web-vitals";
import { vitalsRouteTemplate, webVitalsPayload } from "@/lib/web-vitals-report";

/** Document-navigation CWV. Keep the initial route: a late LCP/INP callback
 * after client navigation still belongs to the document that was measured.
 * Route-transition useful-state marks are a separate metric.
 */
export default function WebVitalsReporter() {
  const context = useRef(null);
  if (!context.current && typeof window !== "undefined") {
    context.current = {
      route: vitalsRouteTemplate(window.location.pathname),
      device: window.matchMedia?.("(max-width: 767px)").matches ? "mobile" : "desktop",
    };
  }
  const report = useCallback((metric) => {
    const payload = webVitalsPayload(metric, context.current || {});
    if (!payload) return;
    fetch("/api/telemetry/web-vitals", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
      credentials: "same-origin",
      // Same-origin Referer normally includes the query string. Telemetry
      // must not transport player IDs or private search parameters there.
      referrerPolicy: "no-referrer",
    }).catch(() => {});
  }, []);
  useReportWebVitals(report);
  return null;
}
