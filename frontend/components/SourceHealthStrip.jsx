"use client";

import { useEffect, useMemo, useState } from "react";

/**
 * SourceHealthStrip — compact "last scraped" indicator per source.
 *
 * Renders a row of dots + source labels + age (e.g. ``DLF 4h ·
 * KTC 12m · FP 2d ⚠``).  One dot color:
 *
 *   green:  refreshed within 4h
 *   amber:  refreshed 4-12h ago
 *   red:    refreshed over 12h ago, or never
 *
 * That is FRESHNESS, and the distinction is load-bearing: a failed fetch
 * normally leaves the previous CSV in place, so a green dot means the
 * file is recent, NOT that the last run succeeded.  This docstring used
 * to say "last run was OK and recent", which the code could not deliver
 * — see attributionSplit for why, and for where run-state failures go
 * instead.
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

// Per-row tone.
//
// The two membership tests are kept and are CORRECT — they simply do not
// fire on today's payload, because the two sides speak different
// vocabularies (see attributionSplit below).  Left in place rather than
// deleted so that the day run state is published in registry keys, rows
// light up without touching this component.  What must not happen is a
// reader assuming they work now: they are pinned by a test either way.
function toneFor(source, runtime, ageHours) {
  // Hard signals first.
  if (runtime?.failed_sources?.includes(source)) return "down";
  if (runtime?.partial_sources?.includes(source)) return "warn";
  if (runtime?.timed_out_sources?.includes(source)) return "down";
  // Age-based fallback.  NOTE this is FRESHNESS, not run state: a failed
  // fetch normally leaves the previous CSV in place, so a recent file
  // does not mean a successful run.
  if (ageHours == null) return "flat";
  if (ageHours >= 12) return "down";
  if (ageHours >= 4) return "warn";
  return "up";
}

// Split the run's reported failures into the ones that name a row we are
// rendering, and the ones that name something else.
//
// F-12. Rows come from ``registered_sources`` — 21 ranking-registry keys
// (``ktcSfTep``, ``idpTradeCalc``, ``dlfSf``…).  ``failed_sources`` /
// ``partial_sources`` / ``timed_out_sources`` and every
// ``source_failures[].source`` come from the legacy scraper's
// ``source_enabled_map`` — 12 run names (``KTC``, ``IDPTradeCalc``,
// ``DLF_LocalCSV``…).  On real data the intersection is EMPTY, so every
// per-row lookup above was structurally dead and a source that
// hard-failed rendered green off its stale-but-recent CSV.
//
// These are not two spellings of one list.  One scraper step can feed
// several registry keys (KTC -> ``ktc`` + ``ktcSfTep``), and most
// registry sources are fetched by their own ``scripts/`` timers and
// appear in no scrape run at all.  A mapping therefore has to be
// DECLARED, by whoever owns source identity, at the one seam that holds
// both vocabularies (``server._source_health``) — inventing one here
// would make this component a second owner of it.
//
// So this does the part that needs no mapping: it stops throwing the
// unmatched failures away.  They are reported under their own names,
// with the run's own reason, and labelled as unattributable — which is
// the honest state, and is not the same as "everything is fine".
function attributionSplit(health, runtime, rowSources) {
  const known = new Set(rowSources);
  const failures = Array.isArray(health?.source_failures)
    ? health.source_failures
    : [];
  const seen = new Set();
  const unattributed = [];
  for (const f of failures) {
    const name = f?.source;
    if (!name || known.has(name) || seen.has(name)) continue;
    seen.add(name);
    unattributed.push({
      source: name,
      kind: f?.kind || "failed",
      reason: f?.details?.message || f?.details?.error || null,
    });
  }
  // Belt and braces: a name can appear in the runtime lists without a
  // ``source_failures`` row. Dropping it would be the same class of
  // silent loss this function exists to end.
  for (const [key, kind] of [
    ["failed_sources", "failed"],
    ["timed_out_sources", "timeout"],
    ["partial_sources", "partial"],
  ]) {
    for (const name of Array.isArray(runtime?.[key]) ? runtime[key] : []) {
      if (!name || known.has(name) || seen.has(name)) continue;
      seen.add(name);
      unattributed.push({ source: name, kind, reason: null });
    }
  }
  return unattributed;
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
    // The row list is the population we are ENTITLED TO EXPECT — the
    // ranking-source registry — not the sources one scrape happened to
    // enable.  ``runtime.enabled_sources`` carries the scraper's own
    // run names for the two ANCHOR markets (["KTC", "IDPTradeCalc"]),
    // so this page — whose subtitle promises "every ranking source in
    // the pipeline" — rendered 2 rows out of 21, and looked their
    // counts up under registry keys that did not match.  F-7.
    const registered = Array.isArray(health.registered_sources)
      ? health.registered_sources
      : [];
    const enabled = registered.length
      ? registered
      : Array.isArray(runtime.enabled_sources)
        ? runtime.enabled_sources
        : [];
    const counts = health.source_counts || {};
    // A source we were not given the served board for is UNKNOWN, not
    // zero — it renders as "—" like an empty source, but it must not be
    // accused of going silent.
    const unmeasured = new Set(
      Array.isArray(health.unmeasured_sources) ? health.unmeasured_sources : [],
    );
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
      const rawCount = counts[src] ?? counts[src.toLowerCase()];
      return {
        source: src,
        count: rawCount == null ? null : Number(rawCount),
        unmeasured: unmeasured.has(src),
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
      unattributed: attributionSplit(health, runtime, enabled),
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
      : "The scrape runtime reports no enabled sources.";
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
              <span className="source-health-name">{e.source}</span>
              {/* Three distinct states, and collapsing them is the
                  defect this page exists to avoid: a real count, a
                  source that voted on NOTHING, and a source we have no
                  measurement for at all. */}
              <span
                className="source-health-count"
                title={
                  e.unmeasured || e.count == null
                    ? "no served-board measurement available"
                    : e.count === 0
                      ? "registered, but contributed to no rows on the served board"
                      : undefined
                }
              >
                {e.unmeasured || e.count == null
                  ? "not measured"
                  : e.count > 0
                    ? `${e.count.toLocaleString()} rows`
                    : "no rows"}
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
          {summary.unattributed.length > 0 && (
            /* The scrape run reported these, and no row above is named by
               them.  Shown verbatim: renaming one to guess at a registry
               key would fabricate an attribution nothing supports. */
            <div className="source-health-unattributed">
              <div className="source-health-unattributed-head">
                {summary.unattributed.length} scrape
                {summary.unattributed.length === 1 ? "" : "s"} reported a problem
                that could not be matched to a source above
              </div>
              {summary.unattributed.map((u) => (
                <div
                  key={u.source}
                  /* Deliberately NOT ``source-health-row``: these are not
                     registered sources, and counting them as rows would
                     misreport the population the page is about. */
                  className={`source-health-unattributed-row source-health-unattributed-row--${
                    u.kind === "partial" ? "warn" : "down"
                  }`}
                >
                  <span
                    className={`source-health-dot source-health-dot--${
                      u.kind === "partial" ? "warn" : "down"
                    }`}
                    aria-hidden="true"
                  />
                  <span className="source-health-name">{u.source}</span>
                  <span className="source-health-count">{u.kind}</span>
                  {u.reason && (
                    <span className="source-health-reason" title={u.reason}>
                      {u.reason}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
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
