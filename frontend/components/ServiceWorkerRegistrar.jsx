"use client";

import { useEffect } from "react";

/**
 * ServiceWorkerRegistrar — registers ``/sw.js`` and keeps an installed
 * PWA from getting stuck on a stale bundle after a deploy.
 *
 * Mount inside ``layout.jsx`` so it runs on every route.
 *
 * Why the update plumbing matters (iOS PWA):
 *   ``sw.js`` does ``skipWaiting()`` + ``clients.claim()`` and deletes
 *   prior caches on ``activate``.  Without a client-side reload, an
 *   already-open tab keeps its in-memory HTML pointing at the previous
 *   build's ``/_next/static`` chunk hashes — which the new SW has just
 *   evicted and the deploy has replaced — so components fail to load
 *   ("per-source table missing on mobile").  iOS Safari makes this
 *   worse by delaying SW activation until every PWA tab on the origin
 *   closes.  This component closes both gaps:
 *     1. reload once when a new SW takes control (controllerchange),
 *     2. force a SW update check when the PWA is foregrounded
 *        (visibilitychange) so a long-lived / backgrounded install
 *        picks up deploys without needing every tab closed first.
 *   This is the real fix for the bug the recurring manual
 *   ``CACHE_VERSION`` bumps in ``sw.js`` were only papering over.
 */
export default function ServiceWorkerRegistrar() {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!("serviceWorker" in navigator)) return;

    const sw = navigator.serviceWorker;

    // If the page is already SW-controlled, a later controllerchange
    // means a NEW version took over → the in-memory HTML now references
    // evicted chunk hashes, so reload once to pull the fresh bundle.
    // On a first-ever (uncontrolled) load we deliberately skip this so
    // the initial activation's controllerchange can't double-load.
    let reloading = false;
    const onControllerChange = () => {
      if (reloading) return;
      reloading = true;
      window.location.reload();
    };
    const wasControlled = Boolean(sw.controller);
    if (wasControlled) {
      sw.addEventListener("controllerchange", onControllerChange);
    }

    // Foregrounding the PWA forces a SW update check.  Without this an
    // installed iOS PWA can sit on a stale SW indefinitely (iOS only
    // activates a waiting SW once every origin tab closes).
    let registration = null;
    const onVisible = () => {
      if (document.visibilityState === "visible" && registration) {
        registration.update().catch(() => {});
      }
    };

    sw
      .register("/sw.js", { scope: "/" })
      .then((reg) => {
        registration = reg;
      })
      .catch(() => {
        // Silent failure: DevTools "Bypass for network", Firefox
        // private mode, or file:// origins.  None block the app.
      });

    document.addEventListener("visibilitychange", onVisible);

    return () => {
      sw.removeEventListener("controllerchange", onControllerChange);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);
  return null;
}
