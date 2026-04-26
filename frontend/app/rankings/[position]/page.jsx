"use client";

import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

// Per-position rankings drill-down route.
//
// Maps ``/rankings/qb`` → the standard /rankings page filtered to QBs.
// Same trick for /rb /wr /te /dl /lb /db /k, plus aliases:
//   * /rankings/offense  → all offensive players
//   * /rankings/idp      → all defensive players
//   * /rankings/picks    → draft picks only
//   * /rankings/rookies  → first-year players only
//
// Implementation: client-side redirect to ``/rankings?pos=<X>``.  The
// rankings page reads the ``?pos`` query param on first load and seeds
// its filter dropdown — see ``frontend/app/rankings/page.jsx``.
//
// Why redirect instead of forking the rankings page?  The rankings
// surface is huge (lens picker, methodology, edge rail, tier
// segmenting, sort, share, etc).  Maintaining two near-identical
// implementations would drift; a 1-line filter pre-seed reuses the
// same code path with zero new chrome.

const POSITION_ALIASES = {
  qb: "QB",
  rb: "RB",
  wr: "WR",
  te: "TE",
  k: "K",
  dl: "DL",
  lb: "LB",
  db: "DB",
  // Family-level shortcuts.
  offense: "offense",
  idp: "idp",
  pick: "pick",
  picks: "pick",
  rookie: "rookie",
  rookies: "rookie",
};

export default function PositionRedirect() {
  const router = useRouter();
  const params = useParams();

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = String(params?.position || "").toLowerCase().trim();
    const target = POSITION_ALIASES[raw];
    if (!target) {
      // Unknown position — drop the user back on the unfiltered board
      // so they're never stranded on a 404 from a typo.
      router.replace("/rankings");
      return;
    }
    router.replace(`/rankings?pos=${encodeURIComponent(target)}`);
  }, [params, router]);

  return (
    <div style={{ padding: 24, color: "var(--subtext)", fontSize: "0.78rem" }}>
      Loading position view…
    </div>
  );
}
