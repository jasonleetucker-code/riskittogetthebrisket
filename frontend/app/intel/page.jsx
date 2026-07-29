import { redirect } from "next/navigation";

// ── /intel is retired ────────────────────────────────────────────────
// It shipped one feature under two product names: Sharp Tracker's name
// and board on Insider Trading's cohort (your league-mates).  Those are
// now two separate products:
//
//   /league/insider-trading  — league-scoped trade leads from your
//                              league-mates' activity elsewhere
//   /market/sharp-tracker    — global market signal from a qualified
//                              manager cohort, not tied to any league
//
// The old path carried the league-mate BOARD, so it redirects to the
// product that inherited that substance.  Permanent: bookmarks, the
// command palette, and any external link should settle on the new URL.
export default function IntelRedirect() {
  redirect("/league/insider-trading");
}
