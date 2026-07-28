import { SkeletonTable } from "@/components/ds/Skeleton";

/**
 * Route-level loading UI (/edge).  Rendered by the App Router the
 * instant a navigation starts, before the route segment's JS chunk
 * loads and the client page hydrates — the page previously showed
 * nothing during that window.  Uses the shared token-styled skeleton
 * so there is no layout shift when real content lands.
 */
export default function Loading() {
  return (
    <div style={{ padding: "16px" }} aria-busy="true" aria-live="polite">
      <SkeletonTable rows={10} columns={5} />
    </div>
  );
}
