"use client";

import { PageHeader, EmptyState } from "@/components/ui";

/**
 * Roster Dashboard — placeholder route.
 * Will be fully implemented in Phase 2 migration.
 */
export default function RostersPage() {
  return (
    <section className="card">
      <PageHeader
        title="Roster Dashboard"
        subtitle="Team strength rankings with position breakdowns, waiver wire gems, and trade targets."
      />
      <EmptyState
        title="Coming soon"
        message="Roster dashboard is being migrated to the new frontend. Check back shortly."
      />
    </section>
  );
}
