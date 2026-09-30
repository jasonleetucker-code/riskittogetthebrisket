"use client";

/**
 * BestBallDetails — section 4 of Game Day, collapsed by default.
 *
 * The panel header renders with the page; its body (BestBallDetailsBody:
 * currently counting / projected lineup / could enter / game finished) is
 * code-split and loads on first open, since most visits never open it.
 * Once opened it stays mounted, so a background refresh keeps it open.
 */

import { Suspense, lazy } from "react";
import { CollapsiblePanel, SkeletonText } from "@/components/ds";

const BestBallDetailsBody = lazy(() => import("./BestBallDetailsBody"));

export default function BestBallDetails({ payload }) {
  if (!payload?.team) return null;
  // A managed league (lineage.bestBall === false) counts submitted
  // starters; calling its lineup "best ball" describes a rule it does not
  // play under.  Unknown keeps the historical title.
  const managed = payload.lineage?.bestBall === false;
  return (
    <CollapsiblePanel
      title={managed ? "Lineup details" : "Best-ball details"}
      subtitle="Who is counting, who could still enter, and whose game is over."
      defaultCollapsed
      mountCollapsedChildren={false}
    >
      <Suspense fallback={<SkeletonText lines={4} />}>
        <BestBallDetailsBody payload={payload} />
      </Suspense>
    </CollapsiblePanel>
  );
}
