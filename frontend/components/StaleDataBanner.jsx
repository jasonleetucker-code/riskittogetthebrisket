"use client";

import { useEffect, useState } from "react";

/**
 * Top-of-app banner that warns when the backend's scraped data has
 * aged past the expected refresh interval.
 *
 * The server's ``/api/health`` endpoint already surfaces:
 *   - ``data_age_hours``    — hours since the last successful scrape
 *   - ``data_stale``        — server's own stale flag (age > 3× interval)
 *   - ``scrape_stalled``    — scrape has been running > stall threshold
 *   - ``last_scrape``       — ISO timestamp of last successful scrape
 *
 * We poll this endpoint every 60s from every page in the app.  The
 * banner's severity tier depends on ``data_age_hours``:
 *
 *   - Missing / unknown       → no banner (still booting or endpoint down)
 *   - age ≤ 6h  → no banner (scrape runs every 2h, 3× = 6h freshness budget)
 *   - age 6-24h  → warning (amber) "Data is X hours old"
 *   - age > 24h  → critical (red) "Data hasn't refreshed in N days"
 *
 * A separate critical banner fires when ``scrape_stalled`` is true
 * regardless of age — that's a background-worker hang the operator
 * needs to see immediately.
 */
const POLL_MS = 60_000;
const WARNING_HOURS = 6;
const CRITICAL_HOURS = 24;


function formatAgo(iso) {
  if (!iso) return "unknown";
  try {
    const then = new Date(iso);
    const now = new Date();
    const secs = Math.round((now.getTime() - then.getTime()) / 1000);
    if (secs < 60) return `${secs}s ago`;
    if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
    if (secs < 86_400) return `${Math.round(secs / 3600)}h ago`;
    const days = Math.round(secs / 86_400);
    return `${days}d ago`;
  } catch {
    return "unknown";
  }
}


export default function StaleDataBanner() {
  const [health, setHealth] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const r = await fetch("/api/health", { cache: "no-store" });
        if (!r.ok && r.status !== 503) {
          // 503 is the server's "degraded" state and STILL returns a
          // valid JSON body with the freshness numbers we care about.
          // Anything else (404, 5xx without body) means the health
          // endpoint is itself broken — don't flash a misleading
          // "data stale" banner because of that; just skip.
          return;
        }
        const data = await r.json();
        if (!cancelled) setHealth(data);
      } catch {
        // Network error; leave the last known health state alone so
        // flaky wifi doesn't spontaneously surface a stale banner.
      }
    }
    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  if (!health) return null;

  const age = typeof health.data_age_hours === "number"
    ? health.data_age_hours
    : null;
  const lastScrape = health.last_scrape || null;
  const stalled = Boolean(health.scrape_stalled);
  const hasData = Boolean(health.has_data);

  // Stalled scrape takes precedence — operator needs to see that the
  // background worker is wedged, not just that data is getting old.
  if (stalled) {
    return (
      <BannerShell severity="critical">
        <strong>Scrape worker stalled.</strong>{" "}
        Data refresh is hung — background worker has not heartbeat-updated
        in over 15 minutes.{" "}
        {lastScrape && <span>Last successful scrape: {formatAgo(lastScrape)}.</span>}
      </BannerShell>
    );
  }

  // No health data at all means we haven't successfully loaded any
  // /api/data payload — don't double-warn because the "no players"
  // state has its own dedicated banner.
  if (!hasData) return null;

  if (age === null || age <= WARNING_HOURS) return null;

  if (age >= CRITICAL_HOURS) {
    const days = Math.round(age / 24);
    return (
      <BannerShell severity="critical">
        <strong>Data is {days}d old.</strong>{" "}
        No successful scrape in {Math.round(age)}h.{" "}
        {lastScrape && <span>Last refresh: {formatAgo(lastScrape)}.</span>}{" "}
        Something is probably broken — check the{" "}
        <a href="/settings" className="stale-banner-link">Settings</a>{" "}
        page for details.
      </BannerShell>
    );
  }

  return (
    <BannerShell severity="warning">
      <strong>Data is {Math.round(age)}h old.</strong>{" "}
      The next scheduled scrape should land soon (every 2 hours).{" "}
      {lastScrape && <span>Last refresh: {formatAgo(lastScrape)}.</span>}
    </BannerShell>
  );
}


function BannerShell({ severity, children }) {
  // Inline styles keep this component self-contained.  Colors match
  // the existing amber/red palette used for tier highlights in the
  // rankings board.
  const palette = severity === "critical"
    ? {
        bg: "#4a1515",
        border: "#8b2a2a",
        text: "#ffdede",
        icon: "!",
      }
    : {
        bg: "#3a2e0b",
        border: "#856100",
        text: "#ffe9a0",
        icon: "⚠",
      };
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`stale-data-banner stale-data-banner-${severity}`}
      style={{
        width: "100%",
        padding: "10px 16px",
        background: palette.bg,
        borderBottom: `1px solid ${palette.border}`,
        color: palette.text,
        fontSize: "0.85rem",
        lineHeight: 1.5,
        textAlign: "center",
        zIndex: 40,
      }}
    >
      <span
        aria-hidden="true"
        style={{ marginRight: 8, fontWeight: 700 }}
      >
        {palette.icon}
      </span>
      {children}
      <style jsx>{`
        .stale-banner-link {
          color: inherit;
          text-decoration: underline;
          font-weight: 600;
        }
        .stale-banner-link:hover {
          opacity: 0.85;
        }
      `}</style>
    </div>
  );
}
