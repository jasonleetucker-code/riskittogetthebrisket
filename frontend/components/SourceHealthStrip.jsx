"use client";

import { useEffect, useMemo, useState } from "react";

/**
 * SourceHealthStrip — compact "last scraped" indicator per source.
 *
 * Renders a row of dots + source labels + age (e.g. ``DLF 4h ·
 * KTC 12m · FP 2d ⚠``).  One dot color:
 *
 *   green:  last run was OK and recent (<4h)
 *   amber:  last run partial OR age is 4-12h
 *   red:    last run failed OR age >12h OR never completed
 *
 * Clicking the strip expands a details panel with per-source
 * record counts + failure reasons.  Hidden entirely when the
 * ``/api/status`` fetch fails (we don't want a broken-status card
 * cluttering an otherwise-functional page).
 */
const REFRESH_INTERVAL_MS = 60_000;

async function fetchStatus() {
  try {
    const res = await fetch("/api/status", {
      credentials: "same-origin",
      headers: { "Cache-Control": "no-store" },
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

function ageLabel(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return null;
  const diffMs = Date.now() - t;
  if (diffMs < 60_000) return `${Math.max(1, Math.round(diffMs / 1000))}s`;
  const minutes = diffMs / 60_000;
  if (minutes < 60) return `${Math.round(minutes)}m`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.round(hours)}h`;
  const days = hours / 24;
  return `${Math.round(days)}d`;
}

function toneFor(source, runtime, ageHours) {
  // Hard signals first.
  if (runtime?.failed_sources?.includes(source)) return "down";
  if (runtime?.partial_sources?.includes(source)) return "warn";
  // Age-based fallback.
  if (ageHours == null) return "flat";
  if (ageHours >= 12) return "down";
  if (ageHours >= 4) return "warn";
  return "up";
}

export default function SourceHealthStrip({ variant = "inline" }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function pull() {
      const data = await fetchStatus();
      if (cancelled) return;
      setStatus(data);
      setLoading(false);
    }
    pull();
    const id = setInterval(pull, REFRESH_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const summary = useMemo(() => {
    if (!status) return null;
    const health = status.source_health || {};
    const runtime = health.source_runtime || {};
    const finishedAt = runtime.finished_at;
    const finishedMs = finishedAt ? Date.parse(finishedAt) : null;
    const ageHours =
      Number.isFinite(finishedMs) && finishedMs > 0
        ? (Date.now() - finishedMs) / (60 * 60 * 1000)
        : null;
    const enabled = Array.isArray(runtime.enabled_sources) ? runtime.enabled_sources : [];
    const counts = health.source_counts || {};
    // Per-source freshness map: stamped by ``server._per_source_freshness``,
    // shape ``{src: {lastFetched, ageHours}}``.  Lets us render a per-source
    // age next to each row instead of one aggregate "last scrape" age.
    const perSource = (health.sources && typeof health.sources === "object")
      ? health.sources
      : {};
    const entries = enabled.map((src) => {
      const meta = perSource[src] || {};
      const srcAgeHours = Number.isFinite(meta.ageHours)
        ? Number(meta.ageHours)
        : ageHours;
      // Per-source age trumps the aggregate when available — gives a
      // truer per-source health signal.
      const tone = toneFor(src, runtime, srcAgeHours);
      const ageLbl = meta.lastFetched ? ageLabel(meta.lastFetched) : null;
      return {
        source: src,
        count: Number(counts[src] || counts[src.toLowerCase()] || 0),
        tone,
        ageLabel: ageLbl,
        ageHours: srcAgeHours,
        failedReason:
          (health.source_failures || []).find(
            (f) => f.source === src,
          )?.details?.message || null,
      };
    });
    return {
      entries,
      ageLabel: ageLabel(finishedAt),
      overall: runtime.overall_status || "unknown",
      failures: (health.source_failures || []).length,
      missing: health.missing_sources || [],
    };
  }, [status]);

  if (loading) return null;
  if (!summary) return null;
  if (summary.entries.length === 0) return null;

  const overallTone =
    summary.overall === "complete"
      ? "up"
      : summary.overall === "partial"
      ? "warn"
      : "down";

  return (
    <div
      className={`source-health-strip source-health-strip--${variant} source-health-strip--${overallTone}`}
      role="region"
      aria-label="Scrape source health"
    >
      <button
        type="button"
        className="source-health-toggle"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        title={
          summary.overall === "complete"
            ? "All sources scraped cleanly"
            : summary.overall === "partial"
            ? "Some sources partially completed — click for details"
            : "Scrape failed or is mid-run"
        }
      >
        <span className={`source-health-dot source-health-dot--${overallTone}`} aria-hidden="true" />
        <span className="source-health-summary">
          Sources · {summary.entries.length}
          {summary.ageLabel ? ` · ${summary.ageLabel} ago` : ""}
          {summary.failures > 0 ? ` · ${summary.failures} issue${summary.failures === 1 ? "" : "s"}` : ""}
        </span>
        <span className="source-health-caret" aria-hidden="true">{expanded ? "▴" : "▾"}</span>
      </button>
      {expanded && (
        <div className="source-health-detail">
          {summary.entries.map((e) => (
            <div key={e.source} className={`source-health-row source-health-row--${e.tone}`}>
              <span className={`source-health-dot source-health-dot--${e.tone}`} aria-hidden="true" />
              <span className="source-health-name">{e.source}</span>
              <span className="source-health-count">
                {e.count > 0 ? `${e.count.toLocaleString()} rows` : "—"}
              </span>
              {e.ageLabel && (
                <span className="source-health-age" title="CSV file mtime — when this source last refreshed">
                  {e.ageLabel} ago
                </span>
              )}
              {e.failedReason && (
                <span className="source-health-reason" title={e.failedReason}>
                  {e.failedReason}
                </span>
              )}
            </div>
          ))}
          {summary.missing.length > 0 && (
            <div className="source-health-missing">
              Missing: {summary.missing.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
