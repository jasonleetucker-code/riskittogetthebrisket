"use client";

import { PageHeader, EmptyState } from "@/components/ui";

/**
 * Trade History — placeholder route.
 * Will be fully implemented in Phase 2 migration.
 */
export default function TradesPage() {
  return (
    <section className="card">
      <PageHeader
        title="Trade History"
        subtitle="Grade and analyze your league's trades using the stud exponent formula."
      />
      <EmptyState
        title="Coming soon"
        message="Trade history analysis is being migrated to the new frontend. Check back shortly."
      />
    </section>
  );
}
