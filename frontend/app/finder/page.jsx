"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Legacy /finder route — the board screener merged into /rankings.
//
// /finder rendered a second copy of the rankings table with five saved
// filters ("WR Gaps", "Stable IDP", "1-Source Risk", "Rookie Spread",
// "All Players").  It computed nothing the board could not express:
// every workflow was a filter over the same rows, from the same
// contract, with the same values.  What it did do was fork the table —
// so the screener never gained the source columns, tier segmenting,
// CSV export, watchlist or player popup that /rankings has, and a user
// who found a player here had to go look him up again over there.
//
// The five workflows now live on the board itself as the "Screens"
// dropdown beside the lens tabs, carried over VERBATIM (their
// thresholds differ from the lenses — WR Gaps cuts at spread > 15 and
// rank <= 250, Disagreements at a different number — so mapping them
// onto existing lenses would have silently changed the answers).
//
// This shim maps the old workflow keys onto the new ones so bookmarks
// and the nav's old keywords keep working.  Same trick, same reasoning
// as /rankings/[position]: a filter pre-seed reuses one code path
// instead of maintaining two near-identical boards that drift.

const WORKFLOW_ALIASES = {
  "wr-gaps": "wr-gaps",
  "stable-idp": "stable-idp",
  "single-risk": "single-risk",
  "rookie-spread": "rookie-spread",
  // "All Players" was the unfiltered board — that is the default lens.
  all: "consensus",
};

export default function FinderLegacyRedirect() {
  const router = useRouter();

  // Read the query string from window rather than useSearchParams():
  // that hook forces the route out of static prerendering unless it is
  // wrapped in a Suspense boundary, and this shim renders one line.
  // /rankings reads its own ?pos= the same way.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const requested = (params.get("workflow") || "").trim().toLowerCase();
    const screen = WORKFLOW_ALIASES[requested];
    router.replace(screen ? `/rankings?screen=${screen}` : "/rankings");
  }, [router]);

  return <p className="muted">Opening the board…</p>;
}
