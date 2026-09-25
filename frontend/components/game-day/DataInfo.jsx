"use client";

/**
 * DataInfo — section 5 of Game Day, collapsed by default: sources,
 * coverage, timestamps and method behind every number on the page.
 *
 * Same split as BestBallDetails: the header renders with the page, the
 * body (DataInfoBody) loads on first open and then stays mounted.
 */

import { Suspense, lazy } from "react";
import { CollapsiblePanel, SkeletonText } from "@/components/ds";

const DataInfoBody = lazy(() => import("./DataInfoBody"));

export default function DataInfo({ payload }) {
  if (!payload) return null;
  return (
    <CollapsiblePanel
      title="Data info"
      subtitle="Sources, coverage, timestamps and method behind every number on this page."
      defaultCollapsed
      mountCollapsedChildren={false}
    >
      <Suspense fallback={<SkeletonText lines={4} />}>
        <DataInfoBody payload={payload} />
      </Suspense>
    </CollapsiblePanel>
  );
}
