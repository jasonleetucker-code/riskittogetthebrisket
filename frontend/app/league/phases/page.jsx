"use client";

import Link from "next/link";
import { PageHeader } from "@/components/ui";
import TeamPhasePanel from "@/components/TeamPhasePanel";

export default function LeaguePhasesPage() {
  return (
    <section>
      <div style={{ fontSize: "0.72rem", marginBottom: 6 }}>
        <Link href="/league" style={{ color: "var(--cyan)" }}>← League home</Link>
      </div>
      <PageHeader
        title="Win-now vs Rebuild"
        subtitle="Each team in your league classified by top-25 roster value × median age, with natural trade-partner suggestions for your franchise."
      />
      <TeamPhasePanel />
    </section>
  );
}
