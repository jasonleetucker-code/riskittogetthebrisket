"use client";

import { PageHeader } from "@/components/ui";
import SourceHealthStrip from "@/components/SourceHealthStrip";

/**
 * Source Health — full-page diagnostic view of scraper status.
 *
 * Reads from /api/status and renders per-source record counts,
 * last-run age, failure reasons, and timing.  The compact strip
 * version of this also appears in the terminal for at-a-glance
 * awareness; this page is the "I want to see everything" view.
 *
 * Auth-gated: /api/status is authed on the frontend anyway, and
 * the scraper diagnostics aren't useful to anonymous visitors.
 */
export default function SourceHealthPage() {
  return (
    <section>
      <div className="card">
        <PageHeader
          title="Source Health"
          subtitle="Scraper status for every ranking source in the pipeline."
        />
        <SourceHealthStrip variant="page" />
        <p className="muted" style={{ marginTop: 14, fontSize: "0.72rem" }}>
          Auto-refreshes every 60 seconds.  Green dot = last run OK and
          recent (&lt;4h).  Amber = partial run OR stale (4-12h).
          Red = failed or older than 12h.  Click the header to
          expand per-source details.
        </p>
      </div>
    </section>
  );
}
