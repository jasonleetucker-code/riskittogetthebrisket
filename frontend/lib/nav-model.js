/**
 * nav-model.js — THE navigation information architecture.
 *
 * Single source of truth for every navigation surface: the desktop top
 * bar, the mobile tab bar + menu drawer, the /more site-map page, and
 * the command palette's "Go to" targets all derive from this data. One
 * IA, collapsed differently per viewport — never two products.
 *
 * Pure data (no React, no next imports) so tests can pin the coverage
 * invariant: every routable surface stays reachable.
 *
 * Grouping rationale (R1 redesign):
 *   Rankings + News ride top-level — the two daily-checkin surfaces.
 *   Everything else folds into four intentional groups ordered by
 *   usage: Trade (the workflow), Roster (your team ops), Intel
 *   (market signals), League (public hub + comparisons). System
 *   (settings/ops/admin) hangs off the right cluster, out of the
 *   content path. Direct URLs are unchanged — this is nav-only.
 *
 * Item shape: { href, label, hint, keywords?, section? }
 *   keywords — extra command-palette match terms
 *   section  — optional sub-heading inside a group menu
 */

export const NAV_MODEL = [
  {
    key: "rankings",
    label: "Rankings",
    href: "/rankings",
    hint: "Player value board",
    keywords: ["board", "values", "ranks"],
  },
  {
    key: "news",
    label: "News",
    href: "/news",
    hint: "Aggregated player news + digests across sources",
    keywords: ["articles", "digest", "headlines"],
  },
  {
    key: "trade",
    label: "Trade",
    href: "/trade",
    hint: "Trade workflow tools",
    items: [
      { href: "/trade", label: "Calculator", hint: "Build and grade a trade", keywords: ["simulate"] },
      { href: "/trades", label: "History", hint: "Analyzed history of every league trade" },
      { href: "/finder", label: "Arbitrage Finder", hint: "Find KTC market gaps you can exploit", keywords: ["market gaps"] },
      { href: "/angle", label: "Counter-Pitch", hint: "Generate counter-package suggestions", keywords: ["packages"] },
    ],
  },
  {
    key: "roster",
    label: "Roster",
    href: "/draft",
    hint: "Draft prep, waivers, team strength",
    items: [
      { href: "/draft", label: "Draft Board", hint: "Rookie/auction draft prep + ADP", keywords: ["adp", "auction", "rookie draft"] },
      { href: "/waivers", label: "Waivers", hint: "Add/drop analysis vs your roster", keywords: ["faab", "free agents"] },
      { href: "/rosters", label: "Team Strength", hint: "Roster dashboard with position breakdowns", keywords: ["depth"] },
    ],
  },
  {
    key: "intel",
    label: "Intel",
    href: "/edge",
    hint: "Market signals and source intelligence",
    items: [
      { href: "/trending", label: "Trending", hint: "Biggest rank movers, last 1d/7d/30d", keywords: ["movers", "risers", "fallers"] },
      { href: "/edge", label: "Edge", hint: "Where ranking sources disagree most", keywords: ["signals", "disagreement"] },
      { href: "/intel", label: "Sharp Tracker", hint: "What league-mates buy/sell across their leagues", keywords: ["sleeper intelligence"] },
      { href: "/idptc-rookies", label: "Rookie Lab", hint: "Rookie board (IDPTC + KTC) with blurbs + export", keywords: ["rookies", "idptc"] },
    ],
  },
  {
    key: "league",
    label: "League",
    href: "/league",
    hint: "Public league hub",
    items: [
      { href: "/league", label: "Hub", hint: "Champions, records, power, draft capital, recaps" },
      { href: "/league/activity", label: "Activity", hint: "Trades + news in one feed" },
      { href: "/league/phases", label: "Win-now vs Rebuild", hint: "Per-team phase classification + trade partners", keywords: ["contention"] },
      { href: "/league-comparison", label: "League Comp", hint: "Your league scoring vs a standard baseline", keywords: ["scoring comparison", "baseline"] },
    ],
  },
];

/**
 * System cluster — right-aligned, out of the content path. Includes the
 * operator surfaces the old IA left in NO navigation at all (/admin,
 * /tools/*): reachable now, quietly.
 */
export const SYSTEM_MODEL = {
  key: "system",
  label: "System",
  hint: "Settings, tools, operations",
  items: [
    { href: "/settings", label: "Settings", hint: "Source weights, TEP, profile", keywords: ["sources", "weights", "tep"] },
    { href: "/more", label: "All destinations", hint: "Every surface on one page", keywords: ["site map", "menu"] },
    { href: "/tools/source-health", label: "Source Health", hint: "Scraper diagnostics", section: "Ops", keywords: ["scraper"] },
    { href: "/tools/ros-data-health", label: "ROS Data Health", hint: "Rest-of-season pipeline health", section: "Ops" },
    { href: "/tools/trade-coverage", label: "Trade Coverage", hint: "Per-team terminal coverage audit", section: "Ops" },
    { href: "/admin", label: "Admin", hint: "Operator flags + actions", section: "Ops" },
  ],
};

/**
 * Mobile bottom tabs — the same IA collapsed to five slots: the three
 * highest-traffic destinations plus Home, with the full NAV_MODEL one
 * tap away behind Menu (a drawer, not a separate second IA — the
 * legacy /more hub page pattern is retired; the route lives on as a
 * site map derived from this same model).
 * icon: ds Icon glyph name.
 */
export const MOBILE_TABS = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/rankings", label: "Ranks", icon: "board" },
  { href: "/trade", label: "Trade", icon: "swap" },
  { href: "/news", label: "News", icon: "news" },
  // The fifth slot is the Menu button (drawer) — rendered by the tab
  // bar itself, not a route entry.
];

/**
 * Extra command-palette navigation targets that intentionally live in
 * no menu (reached contextually in the UI) but must stay reachable.
 */
export const PALETTE_EXTRA_TARGETS = [
  { href: "/players/compare", label: "Compare Players", hint: "Two-player side-by-side", keywords: ["vs", "h2h"] },
  { href: "/", label: "Home", hint: "Terminal dashboard", keywords: ["dashboard", "terminal"] },
];

/** Flatten a group tree into leaf destinations. */
export function flattenNav(groups) {
  const out = [];
  for (const g of groups) {
    if (g.items && g.items.length) {
      for (const item of g.items) out.push({ ...item, group: g.label });
    } else {
      out.push({ href: g.href, label: g.label, hint: g.hint, keywords: g.keywords, group: null });
    }
  }
  return out;
}

/** Every destination the command palette can navigate to. */
export function paletteTargets() {
  const seen = new Set();
  const out = [];
  for (const item of [
    ...flattenNav(NAV_MODEL),
    ...SYSTEM_MODEL.items.map((i) => ({ ...i, group: "System" })),
    ...PALETTE_EXTRA_TARGETS.map((i) => ({ ...i, group: null })),
  ]) {
    if (seen.has(item.href)) continue;
    seen.add(item.href);
    out.push(item);
  }
  return out;
}

/**
 * Is `href` the best active match for `pathname`?  Longest-prefix wins
 * so /league/activity lights "Activity", not "Hub"; "/" matches only
 * exactly.
 */
export function isNavActive(href, pathname) {
  if (!pathname) return false;
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}

/**
 * Active state for a GROUP: any of its leaf hrefs (or the group href)
 * matches the pathname.
 */
export function isGroupActive(group, pathname) {
  if (!group.items || group.items.length === 0) return isNavActive(group.href, pathname);
  return group.items.some((i) => isNavActive(i.href, pathname));
}

/** Page title for the mobile top bar, derived from the model (replaces
 * the legacy hardcoded 17-entry route→title map). Deep public-league
 * routes keep their contextual labels. */
const DEEP_TITLES = {
  "/league/franchise": "Franchise",
  "/league/player": "Player",
  "/league/rivalry": "Rivalry",
  "/league/week": "Week Recap",
  "/league/weekly": "Matchup",
  "/league/articles": "Articles",
};

export function pageTitleFor(pathname) {
  if (!pathname || pathname === "/") return "Home";
  for (const [prefix, label] of Object.entries(DEEP_TITLES)) {
    if (pathname === prefix || pathname.startsWith(prefix + "/")) return label;
  }
  const all = [
    ...flattenNav(NAV_MODEL),
    ...SYSTEM_MODEL.items,
    ...PALETTE_EXTRA_TARGETS,
    { href: "/login", label: "Login" },
    { href: "/draft-capital", label: "Draft Capital" },
  ];
  let best = null;
  for (const item of all) {
    if (!isNavActive(item.href, pathname)) continue;
    if (!best || item.href.length > best.href.length) best = item;
  }
  return best ? best.label : "Brisket";
}
