// Legacy /draft-capital route — redirects to the Draft Capital tab
// under /league so old bookmarks and shared links still work.  The
// actual rendering now lives in
// frontend/app/league/sections/draft-capital.jsx and is reachable at
// /league (it's the default tab) or explicitly /league?tab=draft-capital.

import { redirect } from "next/navigation";

export default function DraftCapitalLegacyRedirect() {
  redirect("/league?tab=draft-capital");
}
