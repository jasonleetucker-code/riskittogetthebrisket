"use client";

import { PageHeader } from "@/components/ui";
import { InfoTip, Panel } from "@/components/ds";
import SourceHealthStrip from "@/components/SourceHealthStrip";
import SourceWeightingTable from "@/components/SourceWeightingTable";
import styles from "./source-health.module.css";

/**
 * Source Health — full-page diagnostic view of every ranking source.
 *
 * Two different questions, kept on two different surfaces because they
 * have different answers:
 *
 *   1. Freshness and weighting (SourceWeightingTable, /api/sources/weighting)
 *      — the pipeline's own verdict: content age against each source's
 *      expected cadence, the freshness factor, health, coverage and the
 *      weight the blend actually applied.  A quarantined source shows here.
 *   2. Fetch recency (SourceHealthStrip, /api/status) — when each file was
 *      last fetched, plus run failures.  Fixed 4h/12h bands; a recent fetch
 *      of unchanged vendor content is still green there, which is exactly
 *      why it is not the freshness verdict.
 *
 * Auth-gated: both endpoints sit behind the session gate.
 */
export default function SourceHealthPage() {
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        title="Source Health"
        subtitle="Is each ranking source current, and how much does it count?"
      />
      <SourceWeightingTable />
      <Panel
        title="Fetch recency"
        headingLevel={2}
        subtitle="When each source file was last fetched, and any run failures."
      >
        <SourceHealthStrip variant="page" />
        <p className="muted" style={{ marginTop: 14, fontSize: "0.72rem" }}>
          Auto-refreshes every 60 seconds.
          <InfoTip label="the status dots">
            <p>
              These dots report <strong>fetch recency</strong> — how long ago each
              source file was last fetched — not whether its content is current.
              A fetch can succeed against a vendor that has not published anything
              new; the Freshness and weighting table above is the verdict on that.
              A failed fetch usually leaves the previous file in place, so a recent
              file is not proof of a clean run either.
            </p>
            <p>
              <strong>Green</strong> — fetched within 4h.
            </p>
            <p>
              <strong>Amber</strong> — fetched 4–12h ago.
            </p>
            <p>
              <strong>Red</strong> — fetched over 12h ago.
            </p>
            <p>
              <strong>Grey</strong> — no per-source fetch time is known, or the
              served board declares the source absent by design (seasonally
              inactive, or a private source this host does not carry). Unknown is
              not fresh, and absent by design is not a failure.
            </p>
            <p>
              Run failures are listed separately at the foot of the detail panel,
              under the names the scrape run itself used.
            </p>
            <p>Click a header to expand that source&apos;s detail.</p>
          </InfoTip>
        </p>
      </Panel>
    </section>
  );
}
