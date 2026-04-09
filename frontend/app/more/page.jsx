"use client";

import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";

/**
 * More — mobile navigation hub.
 * Provides access to all destinations not in the mobile bottom nav.
 * On desktop this page is accessible but the top nav already covers everything.
 */
const SECTIONS = [
  {
    title: "Analysis",
    items: [
      { href: "/edge", label: "Edge Detection", desc: "Buy-low / sell-high signals from model vs market" },
      { href: "/finder", label: "Trade Finder", desc: "Arbitrage trades using board advantage" },
    ],
  },
  {
    title: "League",
    items: [
      { href: "/trades", label: "Trade History", desc: "Grade and analyze your league's trades" },
      { href: "/rosters", label: "Roster Dashboard", desc: "Team strength rankings with position breakdowns" },
      { href: "/league", label: "League Hub", desc: "Power rankings, team comparison, draft capital" },
      { href: "/draft-capital", label: "Draft Capital", desc: "Auction-dollar pick values and ownership" },
    ],
  },
  {
    title: "Tools",
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
