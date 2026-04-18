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
      { href: "/edge", label: "Edge — Source Signals", desc: "Where ranking sources agree, disagree, and flag issues" },
      { href: "/finder", label: "Finder — Player Discovery", desc: "Surface players by source signal patterns and opportunity type" },
    ],
  },
  {
    title: "League",
    items: [
      { href: "/trades", label: "Trade History", desc: "Grade and analyze your league's trades" },
      { href: "/rosters", label: "Roster Dashboard", desc: "Team strength rankings with position breakdowns" },
      { href: "/league", label: "League Hub", desc: "Champions, rivalries, awards, records, draft capital, weekly recaps, and more" },
    ],
  },
  {
    title: "Tools",
    items: [
      { href: "/tools/idp-calibration", label: "IDP Calibration Lab", desc: "Internal: calibrate DL/LB/DB multipliers from two Sleeper leagues across 2022–2025, then promote to production" },
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
