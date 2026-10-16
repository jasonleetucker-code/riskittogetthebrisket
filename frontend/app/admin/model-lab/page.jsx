import { Suspense } from "react";
// Direct module import, NOT the ds barrel, from a server component (same
// reason as /game-day and /dfs: a server import of the barrel makes every
// "use client" module it re-exports a client reference of this page).
import { PageHeader } from "@/components/ds/PageHeader";
import ModelLabWorkspace from "@/components/model-lab/ModelLabWorkspace";
import styles from "./model-lab-page.module.css";

export const metadata = { title: "Model Lab" };

/**
 * /admin/model-lab — the Model Lab (IC-6, PSI Direction A, Lane 6).
 *
 * PRIVATE AND ADMIN-ONLY.  Private by route (`lib/public-routes.js` lists
 * no `/admin` path, so `middleware.js` sends anonymous visitors to /login);
 * admin-only by the backend (`GET /api/model-lab` calls
 * `_require_admin_session`, so a signed-in non-admin gets a 403 that the
 * workspace renders as the shared "not available to this account" state).
 * Under `/admin`, so AppShell skips the player-data pipeline for it
 * (`NO_PLAYER_DATA_ROUTE_PREFIXES`) — the Lab reads only its own endpoint.
 *
 * READ-ONLY.  A view over the existing model owners
 * (`src/model_registry/model_lab.py`): it shows champions, challengers,
 * verdicts, what is served and how it would be rolled back, and offers no
 * control that changes any of them.
 */
export default function ModelLabPage() {
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow="Ops"
        title="Model Lab"
        description="Champion versus challengers for every model family: the evidence windows, sample sizes, verdicts, why the champion stands, what is served now and how it would be rolled back."
      />
      {/* `useSearchParams` inside the workspace requires a Suspense boundary
          during static prerender — same convention as /game-day. */}
      <Suspense fallback={null}>
        <ModelLabWorkspace />
      </Suspense>
    </section>
  );
}
