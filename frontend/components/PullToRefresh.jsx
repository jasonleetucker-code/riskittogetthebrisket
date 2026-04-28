"use client";

import { useEffect, useRef, useState } from "react";

// iOS Safari has a native pull-to-refresh in browser chrome, but
// when the site is launched from the home screen as a PWA the
// gesture is gone — the rubber-band overscroll just snaps back.
// This shim restores it for standalone mode and stays out of
// regular Safari's way (where the native one already works).

const THRESHOLD = 70;        // px past which release triggers a refresh
const MAX_PULL = 120;        // visual ceiling so the indicator can't run off
const ACTIVATION_SLOP = 8;   // ignore tiny finger drift before committing

export default function PullToRefresh() {
  const [pullDistance, setPullDistance] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [enabled, setEnabled] = useState(false);

  const pullRef = useRef(0);
  const startYRef = useRef(null);
  const trackingRef = useRef(false);
  const committedRef = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const standalone =
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator?.standalone === true;
    setEnabled(Boolean(standalone));
  }, []);

  useEffect(() => {
    if (!enabled) return undefined;

    function reset() {
      trackingRef.current = false;
      committedRef.current = false;
      startYRef.current = null;
      pullRef.current = 0;
      setPullDistance(0);
    }

    function onTouchStart(e) {
      if (refreshing) return;
      // Only start tracking when the page is genuinely at the top.
      if ((window.scrollY || window.pageYOffset || 0) > 0) return;
      const t = e.touches?.[0];
      if (!t) return;
      startYRef.current = t.clientY;
      trackingRef.current = true;
      committedRef.current = false;
    }

    function onTouchMove(e) {
      if (!trackingRef.current || refreshing) return;
      if ((window.scrollY || window.pageYOffset || 0) > 0) {
        reset();
        return;
      }
      const t = e.touches?.[0];
      if (!t) return;
      const delta = t.clientY - startYRef.current;
      if (delta <= ACTIVATION_SLOP) {
        // Either pulling up or below the slop threshold — let the
        // browser handle scroll normally.
        if (committedRef.current) {
          pullRef.current = 0;
          setPullDistance(0);
        }
        return;
      }
      committedRef.current = true;
      // Damped pull so the indicator slows down as the finger
      // travels — feels closer to native PTR than a 1:1 mapping.
      const damped = Math.min(MAX_PULL, Math.pow(delta, 0.85));
      pullRef.current = damped;
      setPullDistance(damped);
      // Suppress rubber-band overscroll while we're handling the pull.
      if (e.cancelable) e.preventDefault();
    }

    function onTouchEnd() {
      if (!trackingRef.current || refreshing) {
        reset();
        return;
      }
      const distance = pullRef.current;
      trackingRef.current = false;
      committedRef.current = false;
      startYRef.current = null;
      if (distance >= THRESHOLD) {
        setRefreshing(true);
        // Brief delay so the user sees the indicator settle into the
        // "refreshing" state before the page tears down.
        setTimeout(() => {
          try {
            window.location.reload();
          } catch {
            window.location.assign(window.location.href);
          }
        }, 120);
      } else {
        pullRef.current = 0;
        setPullDistance(0);
      }
    }

    window.addEventListener("touchstart", onTouchStart, { passive: true });
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("touchend", onTouchEnd, { passive: true });
    window.addEventListener("touchcancel", onTouchEnd, { passive: true });

    return () => {
      window.removeEventListener("touchstart", onTouchStart);
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("touchend", onTouchEnd);
      window.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [enabled, refreshing]);

  if (!enabled) return null;

  const armed = pullDistance >= THRESHOLD;
  const visible = pullDistance > 0 || refreshing;
  const translate = refreshing ? Math.max(pullDistance, THRESHOLD) : pullDistance;
  const opacity = refreshing ? 1 : Math.min(1, pullDistance / THRESHOLD);
  const rotation = refreshing ? 0 : Math.min(360, (pullDistance / THRESHOLD) * 270);

  return (
    <div
      aria-hidden={!visible}
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        height: 0,
        zIndex: 1000,
        pointerEvents: "none",
        display: "flex",
        justifyContent: "center",
      }}
    >
      <div
        style={{
          transform: `translateY(${translate}px)`,
          transition: refreshing || pullDistance === 0 ? "transform 180ms ease-out" : "none",
          opacity,
          marginTop: 8,
          width: 36,
          height: 36,
          borderRadius: "50%",
          background: "var(--bg-elevated, #1a1a24)",
          boxShadow: "0 4px 12px rgba(0,0,0,0.35)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke={armed || refreshing ? "var(--amber, #f5b342)" : "var(--text, #e7e7ee)"}
          strokeWidth="2.4"
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{
            transform: `rotate(${rotation}deg)`,
            transition: refreshing ? "none" : "transform 60ms linear",
            animation: refreshing ? "ptr-spin 0.9s linear infinite" : "none",
          }}
        >
          <path d="M21 12a9 9 0 1 1-3-6.7" />
          <path d="M21 4v5h-5" />
        </svg>
      </div>
      <style jsx global>{`
        @keyframes ptr-spin {
          from { transform: rotate(0deg); }
          to   { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
