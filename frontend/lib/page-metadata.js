/**
 * page-metadata.js — per-route browser-tab titles.
 *
 * The label for a route comes from nav-model's `pageTitleFor` (the one
 * owner of page names).  Only routes that are in NO navigation surface
 * (auction rooms, manager sub-pages, redirects…) get an entry in
 * ROUTE_TITLE_OVERRIDES below; nothing here duplicates a nav label.
 *
 * Consumed by server-side `layout.js` files, one per route segment, so
 * the title is correct on direct load (SSR) and on client navigation and
 * adds no client JavaScript.  Pure data/functions — no React, no next.
 */
import { pageTitleFor } from "./nav-model.js";

export const TITLE_SUFFIX = "Chase Upside";
export const GENERIC_TITLE = TITLE_SUFFIX;

// Routes that exist but are in no nav surface, so pageTitleFor can only
// answer with the longest-prefix group (or nothing).
export const ROUTE_TITLE_OVERRIDES = {
  "/admin/sharp-identities": "Sharp Identity Review",
  "/auction": "Rookie Auction",
  "/auction/join": "Join Auction Room",
  "/auction/notifications": "Auction Phone Alerts",
  "/auction/reset": "Reset Auction Password",
  "/auction/[roomId]": "Auction Room",
  "/finder": "Rankings",
  "/intel": "Insider Trading",
  "/managers/compare": "Compare Managers",
  "/managers/leaderboards": "Manager Leaderboards",
  "/managers/league/[leagueId]": "League Managers",
  "/market/sharp-people/[personId]": "Sharp Profile",
  "/players/[playerId]": "Player Profile",
  "/waiver-wire/r7k4q9m2": "Waiver Wire Comparison",
};

/** Bare label for a route pattern (e.g. "/auction/[roomId]"). */
export function routeLabel(route) {
  return ROUTE_TITLE_OVERRIDES[route] || pageTitleFor(route);
}

/** Full tab title: "<Page> — Chase Upside". */
export function pageTitle(route) {
  const label = routeLabel(route);
  return !label || label === GENERIC_TITLE ? GENERIC_TITLE : `${label} — ${TITLE_SUFFIX}`;
}

/** The `metadata` object a route-segment layout exports. */
export function pageMetadata(route) {
  return { title: pageTitle(route) };
}
