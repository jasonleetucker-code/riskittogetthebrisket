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
import { SYSTEM_MODEL, flattenNav, navGroupsFor, systemItemsFor } from "@/lib/nav-model";

export default function MorePage() {
  const { authenticated, isAdmin, features, logout } = useAuthContext();
  // "Every surface" means every surface we are willing to OFFER.  This
  // page is a nav surface like the menus and the palette, so a
  // destination whose endpoints all 503 is omitted here too (V1-131) —
  // listing it as a live link on the site map would reintroduce exactly
  // the dead-end the gate removes.
  //
  // The System group goes through the same admin filter as the menus
  // (`systemItemsFor`): Ops pages are admin-only on the server, so the
  // site map does not offer them to anyone else.
  const groups = [
    ...navGroupsFor({ capabilities: features }),
    { ...SYSTEM_MODEL, items: systemItemsFor({ isAdmin: authenticated && isAdmin }) },
  ];

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
