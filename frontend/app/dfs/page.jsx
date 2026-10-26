import { Suspense } from "react";
// Direct import, NOT the ds barrel, from a server component (same reason as /game-day).
import { PageHeader } from "@/components/ds/PageHeader";
import DfsWorkspace from "@/components/dfs/DfsWorkspace";
import styles from "./dfs-page.module.css";

export const metadata = { title: "DFS Workspace" };

/**
 * /dfs — Daily Fantasy Sports workspace (owner directive 2026-09-30,
 * docs/dfs/README.md). Private by default (frontend/middleware.js).
 * Everything the workspace shows is computed by /api/dfs/*.
 */
export default function DfsPage() {
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow="DFS"
        title="DFS Workspace"
        description="Import a platform salary file and your projections, set your rules, and build legal lineups. Today's builds maximize projected points only — they are not contest-evaluated."
      />
      <Suspense fallback={null}>
        <DfsWorkspace />
      </Suspense>
    </section>
  );
}
