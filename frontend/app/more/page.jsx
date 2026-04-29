"use client";

import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";

/**
 * More — mobile navigation hub.
 * Provides access to all destinations not in the mobile bottom nav.
 * On desktop this page is accessible but the top nav already covers everything.
 *
 * Section structure mirrors the desktop nav grouping:
 *   * Trade workflow — the four trade-related tools that live under
 *     the "Trade ▾" dropdown on desktop
 *   * Signals — Edge (source-disagreement)
 *   * League — public-facing surfaces
 *   * Other — Rosters, Settings, etc.
 */
const SECTIONS = [
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
];

export default function MorePage() {
  const { authenticated, logout } = useAuthContext();

  return (
    <section>
      <div className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h1 className="page-title">More</h1>
        <p className="muted text-sm" style={{ marginTop: 4 }}>
          All tools and surfaces in one place.
        </p>
      </div>

      {SECTIONS.map((section) => (
        <div key={section.title} style={{ marginBottom: "var(--space-lg)" }}>
          <div className="label" style={{ marginBottom: "var(--space-sm)" }}>{section.title}</div>
          <div className="list">
            {section.items.map((item) => (
              <Link key={item.href} href={item.href} className="card more-item" style={{ display: "block" }}>
                <div style={{ fontWeight: 600, fontSize: "0.88rem" }}>{item.label}</div>
                <div className="muted text-xs" style={{ marginTop: 2 }}>{item.desc}</div>
              </Link>
            ))}
          </div>
        </div>
      ))}

      {authenticated && (
        <div style={{ marginTop: "var(--space-lg)", paddingTop: "var(--space-md)", borderTop: "1px solid var(--border)" }}>
          <button className="button button-danger" onClick={logout} style={{ width: "100%" }}>
            Sign out
          </button>
        </div>
      )}
    </section>
  );
}
