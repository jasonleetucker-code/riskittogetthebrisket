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
 * Grouping rationale: each top-level entry answers a question a
 * dynasty manager actually asks, and every group label is clickable —
 * it goes to the group's primary page (see NavMenu's split trigger),
 * so grouping a page costs no extra click.
 *
 *   Rankings — "what is a player worth?"  The board plus every other
 *              view of player value.
 *   News     — "what happened?"  Daily check-in, stays top-level.
 *   Trades   — "should I make this deal, and who with?"
 *   My Team  — "what do I do with my roster?"
 *   Market   — "what is the market doing that I can exploit?"
 *   League   — "how is my league doing?"  Public, community-facing.
 *
 * This replaced a grouping that had drifted: three tools whose names
 * all meant "finder" sat adjacent in one menu, player-value views
 * (Trending, rookies, compare, fundamentals) were scattered under a
 * catch-all called "Intel", and /players/compare was reachable only
 * from the command palette.  Six top-level entries either way — the
 * change is which things sit together and what they are called.
 *
 * NAMING RULE, load-bearing: a leaf's label here is the SAME string as
 * the page's <h1>, as pageTitleFor's answer, and as any in-app link to
 * it.  Eight pages used to disagree with their own nav entry
 * ("Counter-Pitch" → a page titled "Trade Finder"), which is how a
 * user ends up unable to tell two tools apart.  __tests__/nav-model
 * pins the canon; if you rename one, rename all of them.
 *
 * Group shape: { key, label, href, hint, items? }
 *   href — the group's primary destination; MUST be one of its items
 * Item shape: { href, label, hint, keywords?, section? }
 *   keywords — extra command-palette match terms
 *   section  — optional sub-heading inside a group menu
 */

export const NAV_MODEL = [
  {
    key: "rankings",
    label: "Rankings",
    href: "/rankings",
    hint: "What players are worth",
    items: [
      {
        href: "/rankings",
        label: "Rankings",
        hint: "The blended dynasty value board",
        keywords: [
          "board",
          "values",
          "ranks",
          // The /finder screener merged in here as the Screens
          // dropdown; keep its vocabulary searchable.
          "screener",
          "screen",
          "filter",
          "signal blotter",
        ],
      },
      {
        href: "/trending",
        label: "Trending",
        hint: "Biggest value movers over 1d/7d/30d",
        keywords: ["movers", "risers", "fallers"],
      },
      {
        href: "/idptc-rookies",
        label: "Rookie Board",
        hint: "Rookies only, with blurbs and export",
        keywords: ["rookies", "idptc", "rookie lab"],
      },
      {
        href: "/players/compare",
        label: "Compare Players",
        hint: "Two players side by side",
        keywords: ["vs", "h2h", "comparison"],
      },
      {
        href: "/bdvm",
        label: "Fundamental Values",
        hint: "Projection-driven values vs the market price",
        keywords: ["bdvm", "fundamental", "projections", "buy low"],
      },
    ],
  },
  {
    key: "news",
    label: "News",
    href: "/news",
    hint: "Player news and digests across sources",
    keywords: ["articles", "digest", "headlines", "wire"],
  },
  {
    key: "trades",
    label: "Trades",
    href: "/trade",
    hint: "Build, find and review trades",
    items: [
      {
        href: "/trade",
        label: "Trade Calculator",
        hint: "Build and grade a specific trade",
        keywords: ["simulate", "builder", "fairness"],
      },
      // These two are genuinely different engines and their old names
      // hid that.  /arbitrage is the board-vs-market engine
      // (src/trade/finder.py); /angle builds return packages against a
      // counterparty (src/trade/angle).  They used to be called
      // "Arbitrage Finder" and "Counter-Pitch" while a THIRD page,
      // /finder, was called "Signal Blotter" and titled "Finder" —
      // three tools, four "finder" labels, one menu.
      {
        href: "/angle",
        label: "Package Builder",
        hint: "Build return packages a counterparty might accept",
        keywords: ["packages", "counter-pitch", "counter offer", "angle"],
      },
      {
        href: "/arbitrage",
        label: "Arbitrage",
        hint: "Trades that gain on our board but read as fair on theirs",
        keywords: ["market gaps", "mispricing"],
      },
      {
        href: "/trades",
        label: "Trade History",
        hint: "Analyzed history of every league trade",
        keywords: ["ledger", "past trades", "winners"],
      },
    ],
  },
  {
    key: "myteam",
    label: "My Team",
    href: "/rosters",
    hint: "Your roster, waivers and draft",
    items: [
      {
        href: "/rosters",
        label: "Team Strength",
        hint: "Every team ranked, with position breakdowns",
        keywords: ["depth", "roster dashboard", "power"],
      },
      {
        href: "/waivers",
        label: "Waivers",
        hint: "Add/drop analysis against your roster",
        keywords: ["faab", "free agents", "claims"],
      },
      {
        href: "/draft",
        label: "Draft Board",
        hint: "Rookie and auction draft prep",
        keywords: ["adp", "auction", "rookie draft", "war room"],
      },
      {
        href: "/phases",
        label: "Win-now vs Rebuild",
        hint: "Which teams are contending, and who to trade with",
        keywords: ["contention", "rebuild", "phases", "trade partners"],
      },
    ],
  },
  {
    key: "market",
    label: "Market",
    href: "/edge",
    hint: "Where the market disagrees with itself",
    items: [
      {
        href: "/edge",
        label: "Source Disagreement",
        hint: "Where the ranking sources agree, disagree and flag issues",
        keywords: ["edge", "signals", "spread", "gaps"],
      },
      // Sharp Tracker sits in Market, not League, and that placement is
      // load-bearing rather than cosmetic: it is a GLOBAL cohort signal
      // and `/api/sharp/cohort` deliberately takes no `leagueKey`. Its
      // league-scoped sibling, Insider Trading, lives under League.
      // The two shipped as one entry — Sharp Tracker's name on Insider
      // Trading's cohort — and separating them is the point of #626.
      {
        href: "/market/sharp-tracker",
        label: "Sharp Tracker",
        hint: "What qualified dynasty managers are buying and selling",
        keywords: ["sharp", "market intelligence", "smart money", "cohort"],
      },
    ],
  },
  {
    key: "league",
    label: "League",
    href: "/league",
    hint: "Your league's hub, history and activity",
    items: [
      { href: "/league", label: "Hub", hint: "Champions, records, power, draft capital, recaps" },
      { href: "/league/activity", label: "Activity", hint: "Trades and news in one feed" },
      {
        href: "/league/insider-trading",
        label: "Insider Trading",
        hint: "Trade leads from what your league-mates do elsewhere",
        keywords: ["league mates", "trade leads", "insider", "sleeper intelligence"],
      },
      {
        href: "/league-comparison",
        label: "Scoring Comparison",
        hint: "Your league's scoring vs a standard baseline",
        keywords: ["league comp", "baseline", "settings"],
      },
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
    // Ops surfaces are ADMIN-ONLY in the nav.  The server has always
    // enforced this (403 unless the username is on
    // PRIVATE_APP_ALLOWED_USERNAMES), but the menu showed all four to
    // every signed-in user — so a guest-pass holder saw a "Admin"
    // entry, clicked it, and got a wall.  Offering a door that is
    // always locked is worse than not showing the door.
    { href: "/tools/source-health", label: "Source Health", hint: "Scraper diagnostics", section: "Ops", adminOnly: true, keywords: ["scraper"] },
    { href: "/tools/ros-data-health", label: "ROS Data Health", hint: "Rest-of-season pipeline health", section: "Ops", adminOnly: true },
    { href: "/tools/trade-coverage", label: "Trade Coverage", hint: "Per-team coverage audit", section: "Ops", adminOnly: true },
    { href: "/admin", label: "Admin", hint: "Operator flags + actions", section: "Ops", adminOnly: true },
  ],
};

/**
 * System menu items visible to this viewer.  Non-admins get the two
 * everyday entries; the Ops section is admin-only.
 */
export function systemItemsFor({ isAdmin = false } = {}) {
  return SYSTEM_MODEL.items.filter((i) => !i.adminOnly || isAdmin);
}

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
 * Logged-out mobile tabs.
 *
 * MOBILE_TABS filtered by "is this public" left exactly two live tabs
 * — Home and Menu — and no Sign in anywhere in the mobile chrome, so a
 * logged-out phone visitor had no visible way to log in at all (the
 * only path was a button on the landing page).  This is the honest
 * logged-out set: the public content, and the way in.
 */
export const MOBILE_TABS_PUBLIC = [
  { href: "/", label: "Home", icon: "home" },
  { href: "/league", label: "League", icon: "star" },
  { href: "/login", label: "Sign in", icon: "arrow-right" },
];

/**
 * Extra command-palette navigation targets that intentionally live in
 * no menu (reached contextually in the UI) but must stay reachable.
 */
export const PALETTE_EXTRA_TARGETS = [
  // /players/compare graduated out of this list into the Rankings
  // group — it was palette-only, which meant the only way to find it
  // was to already know it existed.
  { href: "/", label: "Home", hint: "Your dashboard", keywords: ["dashboard", "terminal"] },
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
    { href: "/login", label: "Sign in" },
    { href: "/draft-capital", label: "Draft Capital" },
  ];
  let best = null;
  for (const item of all) {
    if (!isNavActive(item.href, pathname)) continue;
    if (!best || item.href.length > best.href.length) best = item;
  }
  return best ? best.label : "Chase Upside";
}
