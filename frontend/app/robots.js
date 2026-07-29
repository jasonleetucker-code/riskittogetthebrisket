// Dynamic robots.txt.
//
// ALLOWLIST, not a denylist.  The previous version disallowed eight
// named private routes and allowed everything else — so every page
// added after it was written (/draft, /waivers, /bdvm, /intel,
// /trending, /angle, /arbitrage, /admin, /tools/*, /more,
// /players/compare, …) was crawlable by default.  A denylist has to be
// updated every time a page ships; an allowlist fails closed.
//
// The public set is the same one the app shell and middleware use —
// lib/public-routes.js — restated here in robots syntax because
// robots.txt has no import mechanism.  Keep them in sync.

import { PUBLIC_PREFIXES } from "@/lib/public-routes";

function _origin() {
  return (
    process.env.NEXT_PUBLIC_SITE_URL ||
    process.env.PUBLIC_SITE_URL ||
    "https://chaseupside.com"
  ).replace(/\/$/, "");
}

export default function robots() {
  const origin = _origin();
  return {
    rules: [
      {
        userAgent: "*",
        allow: [
          "/$", // the marketing landing page, exactly — not the whole tree
          "/login",
          // Public league hub + every share-friendly subtree beneath it
          // (franchises, players, rivalries, weekly recaps, articles).
          ...PUBLIC_PREFIXES.flatMap((p) => [p, `${p}/`]),
        ],
        disallow: ["/"],
      },
    ],
    sitemap: `${origin}/sitemap.xml`,
  };
}
