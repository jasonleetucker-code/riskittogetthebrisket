// Legacy /league/phases route — redirects to /phases so old bookmarks
// and shared links still work.
//
// The page moved off the /league prefix because that prefix means
// "served by the public pipeline, never reads the private contract",
// and this page's TeamPhasePanel does read it.  See app/phases/page.jsx
// for the full rationale.

import { redirect } from "next/navigation";

export default function LeaguePhasesLegacyRedirect() {
  redirect("/phases");
}
