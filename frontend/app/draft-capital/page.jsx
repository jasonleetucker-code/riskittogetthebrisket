"use client";

import { PageHeader, EmptyState } from "@/components/ui";

/**
 * Draft Capital — placeholder route.
 * Will be fully implemented in Phase 2 migration.
 * This is a public page (no auth required).
 */
export default function DraftCapitalPage() {
  return (
    <section className="card">
      <PageHeader
        title="Draft Capital"
        subtitle="Auction-dollar pick values from the dynasty draft curve. Pick ownership from Sleeper."
      />
      <EmptyState
        title="Coming soon"
        message="Draft capital viewer is being migrated to the new frontend. Check back shortly."
      />
    </section>
  );
}
