"use client";

import { useEffect } from "react";

/**
 * ServiceWorkerRegistrar — registers ``/sw.js`` once per page load.
 *
 * Runs exactly once on mount.  If the browser doesn't support
 * service workers (older Safari, some corporate browser policies),
 * the registration silently no-ops — no error, no fallback UI.
 *
 * The SW handles caching for asset chunks and API-fallback for
 * offline.  It does NOT handle push notifications or background
 * sync; those are future additions.
 *
 * Mount inside ``layout.jsx`` so it runs on every route.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;
    // Register once per page load — the browser handles activation
    // and upgrades for subsequent versions.  We don't unregister
    // on unmount because the SW is a page-wide singleton.
    navigator.serviceWorker
      .register("/sw.js", { scope: "/" })
      .catch(() => {
        // Silent failure: common causes are DevTools "Bypass for
        // network" toggles, private browsing in Firefox, or file://
        // origins.  None of these block the regular app flow.
      });
  }, []);
  return null;
}
