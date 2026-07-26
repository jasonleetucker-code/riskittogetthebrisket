"use client";

import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import { MORE_SECTIONS } from "@/lib/more-sections";

/**
 * More — mobile navigation hub.
 * Provides access to all destinations not in the mobile bottom nav.
 * On desktop this page is accessible but the top nav already covers everything.
 *
 * The section registry lives in ``frontend/lib/more-sections.js``
 * (pure data) so tests can pin that every non-bottom-nav destination
 * — e.g. /news — stays reachable from this hub.
 */
const SECTIONS = MORE_SECTIONS;

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
