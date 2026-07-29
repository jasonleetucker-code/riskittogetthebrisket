import { SkeletonTable } from "@/components/ds/Skeleton";

/**
 * Root-segment loading UI.  Renders during the initial route-chunk
 * load for `/` and as the fallback for child segments that don't ship
 * their own loading.jsx.  Kept deliberately generic (the per-route
 * files carry route-shaped skeletons); the point is immediate visual
 * feedback instead of a blank viewport.
 */
export default function Loading() {
  return (
    <div style={{ padding: "16px" }} aria-busy="true" aria-live="polite">
      <SkeletonTable rows={10} columns={5} />
    </div>
  );
}
