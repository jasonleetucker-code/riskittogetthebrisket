// Waiver Wire Comparison — UNLISTED page (owner request 2026-10-21).
//
// Reachable by anyone with the exact link (lib/public-routes.js
// `isUnlistedPagePath`), linked from nowhere, absent from robots.txt's
// allowlist and the sitemap, and noindexed here as well.

import WaiverCompareClient from "./WaiverCompareClient";

export const metadata = {
  title: "Waiver Wire Comparison",
  description: "Compare your roster's dynasty values with the best available waiver-wire players.",
  robots: { index: false, follow: false, nocache: true, googleBot: { index: false, follow: false } },
};

export default function WaiverComparePage() {
  return <WaiverCompareClient />;
}
