"use client";

/**
 * /more — site map (R1).
 *
 * The legacy mobile "More hub" pattern is retired: mobile navigation
 * now runs through the tab bar + menu drawer, which render the full
 * nav model. This route survives (bookmarks, muscle memory, System
 * menu "All destinations") as a flat site map derived from the SAME
 * lib/nav-model.js data — it can never drift from the real navigation.
 */
import Link from "next/link";
import { useAuthContext } from "@/app/AppShellWrapper";
import { PageHeader, Panel } from "@/components/ds";
import { NAV_MODEL, SYSTEM_MODEL, flattenNav } from "@/lib/nav-model";

export default function MorePage() {
  const { authenticated, logout } = useAuthContext();
  const groups = [...NAV_MODEL, SYSTEM_MODEL];

  return (
    <section>
      <PageHeader
        title="All destinations"
        description="Every surface, grouped the same way as the navigation."
      />
      {groups.map((group) => (
        <Panel key={group.key} title={group.label} dense className="shell-sitemap-panel">
          <div className="shell-drawer-list">
            {(group.items && group.items.length
              ? group.items
              : flattenNav([group])
            ).map((item) => (
              <Link key={item.href} href={item.href} className="shell-menu-item">
                <span>{item.label}</span>
                {item.hint ? (
                  <span className="shell-menu-item-hint">{item.hint}</span>
                ) : null}
              </Link>
            ))}
          </div>
        </Panel>
      ))}
      {authenticated && (
        <div className="shell-drawer-footer">
          <button
            type="button"
            className="ds-btn ds-btn--secondary shell-drawer-signout"
            onClick={logout}
          >
            Sign out
          </button>
        </div>
      )}
    </section>
  );
}
