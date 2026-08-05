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
    if (!res.ok) return { ok: false, reason: `HTTP ${res.status}`, data: null };
    return { ok: true, reason: null, data: await res.json() };
  } catch (err) {
    return { ok: false, reason: err?.message || "network error", data: null };
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

// Tone for one registry-keyed row from ``source_health.sources_detail``.
// The backend already decided the status (see server._source_health_rows);
// this only picks a colour, so the page and the API can't disagree about
// whether a source is healthy.
function toneForRow(row) {
  switch (row?.status) {
    case "failed":
      return "down";
    case "empty":
      return "down";
    case "stale":
      return "warn";
    case "ok":
      return "up";
    default:
      return "flat";
  }
}

export default function SourceHealthStrip({ variant = "inline" }) {
  const [status, setStatus] = useState(null);
  const [fetchError, setFetchError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function pull() {
      const result = await fetchStatus();
      if (cancelled) return;
      // Keep the last good payload on a transient blip so a 60s poll
      // failure doesn't blank a working strip; only report the error
      // when we have nothing to show.
      if (result.ok) {
        setStatus(result.data);
        setFetchError(null);
      } else {
        setFetchError(result.reason);
      }
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
    // Row set = ``source_health.sources_detail``: one entry per source
    // the pipeline INGESTS, registry-keyed, built by the backend's
    // single normalising helper.  It used to be
    // ``source_runtime.enabled_sources`` — the legacy scraper's own
    // four-name run plan — so this page, whose subtitle promises
    // "every ranking source in the pipeline", listed 4 of 21 and looked
    // healthy through a 17-source outage.  Counts came from a
    // ``counts[src] || counts[src.toLowerCase()]`` lookup across the two
    // vocabularies, which rendered IDPTradeCalc's 911 rows as an
    // em-dash.  Both are gone: no name is case-folded on the client and
    // no row set is invented here.
    const detail = Array.isArray(health.sources_detail) ? health.sources_detail : [];
    const entries = detail.map((row) => ({
      source: row.key,
      label: row.displayName || row.key,
      count: Number.isFinite(row.rows) ? Number(row.rows) : null,
      tone: toneForRow(row),
      status: row.status,
      ageLabel: row.lastFetched ? ageLabel(row.lastFetched) : null,
      ageHours: Number.isFinite(row.ageHours) ? Number(row.ageHours) : null,
      failedReason: row.reason || null,
    }));
    return {
      entries,
      ageLabel: ageLabel(finishedAt),
      overall: runtime.overall_status || "unknown",
      failures: (health.source_failures || []).length,
      missing: health.missing_sources || [],
    };
  }, [status]);

  if (loading) return null;

  // ── Nothing to show ───────────────────────────────────────────────
  // Inline: stay hidden.  A broken status card must not clutter an
  // otherwise-functional page — that is the documented intent.
  //
  // Page: this component IS /tools/source-health.  Returning null there
  // left the route rendering a legend for dots that weren't present,
  // with no way to distinguish "all sources healthy" from "the status
  // endpoint is down".  A failure the reader can't see is exactly what
  // CLAUDE.md's fail-fast convention forbids.
  const isPage = variant === "page";
  if (!summary || summary.entries.length === 0) {
    if (!isPage) return null;
    const detail = !summary
      ? `Couldn't reach /api/status${fetchError ? ` (${fetchError})` : ""}.`
      : "/api/status carries no per-source rows (source_health.sources_detail is empty).";
    return (
      <div
        className={`source-health-strip source-health-strip--${variant} source-health-strip--down`}
        role="status"
      >
        <span className="source-health-dot source-health-dot--down" aria-hidden="true" />
        <span className="source-health-summary">
          {summary ? "No sources reported" : "Source health unavailable"} — {detail}
        </span>
      </div>
    );
  }

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
              <span className="source-health-name" title={e.label}>{e.source}</span>
              {/* 0 rows is a source that has DIED; a null count is a
                  count we do not have (no contract primed yet).  They
                  must not render the same em-dash. */}
              <span className="source-health-count">
                {e.count == null ? "—" : `${e.count.toLocaleString()} rows`}
              </span>
              {e.ageLabel && (
                <span className="source-health-age" title="Last successful fetch for this source">
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
