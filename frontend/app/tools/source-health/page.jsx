"use client";

import { PageHeader } from "@/components/ui";
import { InfoTip } from "@/components/ds";
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
          Auto-refreshes every 60 seconds.
          <InfoTip label="the status dots">
            <p>
              The dots report <strong>freshness</strong> — how long ago each
              source last refreshed — not whether the last scrape of it
              succeeded. A failed fetch usually leaves the previous file in
              place, so a recent file is not proof of a clean run.
            </p>
            <p>
              <strong>Green</strong> — refreshed within 4h.
            </p>
            <p>
              <strong>Amber</strong> — refreshed 4–12h ago.
            </p>
            <p>
              <strong>Red</strong> — refreshed over 12h ago, or never.
            </p>
            <p>
              Run failures are listed separately at the foot of the detail
              panel, under the names the scrape run itself used.
            </p>
            <p>Click a header to expand that source&apos;s detail.</p>
          </InfoTip>
        </p>
      </div>
    </section>
  );
}
