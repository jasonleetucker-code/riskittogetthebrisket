/**
 * more-sections — the mobile "More" hub's navigation registry.
 *
 * Pure data, extracted from ``frontend/app/more/page.jsx`` so tests
 * can pin coverage invariants (every desktop-nav destination that is
 * NOT in the 4-tab mobile bottom nav must be reachable from here)
 * without importing the page component's context/next chain.
 *
 * Section structure mirrors the desktop nav grouping:
 *   * News — aggregated player news (desktop group 1; the mobile
 *     bottom nav is fixed at four tabs, so this is the mobile entry
 *     point)
 *   * Trade workflow — the four trade-related tools that live under
 *     the "Trade ▾" dropdown on desktop
 *   * Signals — Edge (source-disagreement)
 *   * League — public-facing surfaces
 *   * Other — Rosters, Settings, etc.
 */
export const MORE_SECTIONS = [
  {
    title: "Trade workflow",
    items: [
      { href: "/trade", label: "Calculator", desc: "Build and grade a trade" },
      { href: "/trades", label: "History", desc: "Analyzed history of every league trade" },
      { href: "/finder", label: "Arbitrage Finder", desc: "Find KTC market gaps you can exploit" },
      { href: "/angle", label: "Counter-Pitch", desc: "Pick a player on your team; get targets that win on your rankings but look fair-or-better on KTC" },
    ],
  },
  {
    title: "News",
    items: [
      { href: "/news", label: "News", desc: "Aggregated player news, articles, and trending signals across every source" },
    ],
  },
  {
    title: "Roster",
    items: [
      { href: "/waivers", label: "Waivers", desc: "Add/drop analysis vs your roster" },
    ],
  },
  {
    title: "Signals",
    items: [
      { href: "/edge", label: "Edge", desc: "Where ranking sources agree, disagree, and flag issues" },
    ],
  },
  {
    title: "League",
    items: [
      { href: "/rosters", label: "Roster Dashboard", desc: "Team strength rankings with position breakdowns" },
      { href: "/league", label: "League Hub", desc: "Champions, rivalries, awards, records, draft capital, weekly recaps, and more" },
    ],
  },
  {
    title: "Settings",
    items: [
      { href: "/settings", label: "Settings", desc: "Tuning controls for valuations and display" },
    ],
  },
  {
    title: "Lab",
    items: [
      { href: "/idptc-rookies", label: "Rookie Board (IDPTC + KTC)", desc: "Every rookie on IDPTC or KTC, sorted by max value, with fantasy blurbs + CSV/Markdown export" },
    ],
  },
];
