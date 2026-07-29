"use client";

/**
 * MobileChrome — the mobile shell (R1): compact top bar, five-slot
 * bottom tab bar, and a full-IA menu drawer.
 *
 * SAME information architecture as desktop, collapsed: the tab bar
 * carries the four highest-traffic destinations (from MOBILE_TABS) and
 * a Menu button that opens a ds Drawer rendering the complete
 * NAV_MODEL + SYSTEM_MODEL — one model, two viewports. This retires
 * the legacy 4-tab + /more-hub pattern (the /more route survives as a
 * site map derived from the same model).
 *
 * The page title derives from nav-model's pageTitleFor (longest-prefix
 * match) — the audit's hand-maintained 17-entry route→title map is gone.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Drawer, Icon } from "@/components/ds";
import TeamSwitcher from "@/components/TeamSwitcher";
import LeagueSwitcher from "@/components/LeagueSwitcher";
import {
  MOBILE_TABS,
  MOBILE_TABS_PUBLIC,
  NAV_MODEL,
  SYSTEM_MODEL,
  flattenNav,
  isNavActive,
  pageTitleFor,
  systemItemsFor,
} from "@/lib/nav-model";

function DrawerGroup({ label, items, pathname, onNavigate }) {
  return (
    <div className="shell-drawer-group">
      <p className="shell-drawer-group-label">{label}</p>
      <div className="shell-drawer-list">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className="shell-menu-item"
            aria-current={isNavActive(item.href, pathname) ? "page" : undefined}
            onClick={onNavigate}
          >
            <span>{item.label}</span>
            {item.hint ? (
              <span className="shell-menu-item-hint">{item.hint}</span>
            ) : null}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function MobileTopBar({ authenticated, onSearch }) {
  const pathname = usePathname();
  return (
    <header className="shell-mobile-topbar" data-html2canvas-ignore>
      <span className="shell-mobile-title">{pageTitleFor(pathname)}</span>
      <div className="shell-mobile-actions">
        {authenticated && <LeagueSwitcher variant="mobile" />}
        {authenticated && <TeamSwitcher variant="mobile" />}
        {authenticated && (
          <button
            type="button"
            className="shell-icon-btn"
            onClick={onSearch}
            aria-label="Search"
          >
            <Icon name="search" size={16} />
          </button>
        )}
      </div>
    </header>
  );
}

export function MobileTabBar({ authenticated, isAdmin, isPublic, onLogout }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the drawer whenever navigation lands.
  useEffect(() => {
    setMenuOpen(false);
  }, [pathname]);

  // Logged out, the authed tab set filtered by "is this public" left
  // Home and the Menu button — and no Sign in anywhere in the mobile
  // chrome, so the only way into the app from a phone was a button on
  // the landing page.  Logged-out visitors get their own three tabs.
  const tabs = authenticated ? MOBILE_TABS : MOBILE_TABS_PUBLIC;

  // Tab active state: longest-prefix winner among the tabs so /trade
  // lights Trade, not Home; the Menu button is active-by-none like the
  // legacy /more (but visually only, it is a button not a route).
  const activeTab = tabs.reduce((best, tab) => {
    if (!isNavActive(tab.href, pathname)) return best;
    if (!best || tab.href.length > best.href.length) return tab;
    return best;
  }, null);

  const groups = authenticated
    ? [...NAV_MODEL, { ...SYSTEM_MODEL, items: systemItemsFor({ isAdmin }) }]
    : NAV_MODEL.map((g) => {
        if (!g.items) return isPublic(g.href) ? g : null;
        const items = g.items.filter((i) => isPublic(i.href));
        return items.length ? { ...g, items } : null;
      }).filter(Boolean);

  return (
    <>
      <nav className="shell-tabbar" aria-label="Primary" data-html2canvas-ignore>
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="shell-tab"
            aria-current={activeTab?.href === tab.href ? "page" : undefined}
          >
            <Icon name={tab.icon} size={18} />
            {tab.label}
          </Link>
        ))}
        <button
          type="button"
          className="shell-tab"
          onClick={() => setMenuOpen(true)}
          aria-haspopup="dialog"
          aria-expanded={menuOpen}
        >
          <Icon name="menu" size={18} />
          Menu
        </button>
      </nav>

      <Drawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Menu">
        {groups.map((group) => (
          <DrawerGroup
            key={group.key}
            label={group.label}
            items={
              group.items && group.items.length
                ? group.items
                : flattenNav([group])
            }
            pathname={pathname}
            onNavigate={() => setMenuOpen(false)}
          />
        ))}
        {authenticated && (
          <div className="shell-drawer-footer">
            <button
              type="button"
              className="ds-btn ds-btn--secondary shell-drawer-signout"
              onClick={onLogout}
            >
              Sign out
            </button>
          </div>
        )}
      </Drawer>
    </>
  );
}
