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
import { useEffect, useRef, useState } from "react";
import { Drawer, Icon } from "@/components/ds";
import TeamSwitcher from "@/components/TeamSwitcher";
import LeagueSwitcher from "@/components/LeagueSwitcher";
import {
  MOBILE_TABS,
  MOBILE_TABS_PUBLIC,
  MOBILE_TABS_UNKNOWN,
  SYSTEM_MODEL,
  flattenNav,
  navGroupsFor,
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

// See the note on TopBar: `searchEnabled` is not derivable from
// `authenticated`, because signed-in routes exist that load no player
// contract.  Defaults true so existing callers are unaffected.
export function MobileTopBar({ authenticated, onSearch, searchEnabled = true }) {
  const pathname = usePathname();
  return (
    <header className="shell-mobile-topbar psi-editorial" data-html2canvas-ignore>
      <span className="shell-mobile-title">{pageTitleFor(pathname)}</span>
      <div className="shell-mobile-actions">
        {authenticated && <LeagueSwitcher variant="mobile" />}
        {authenticated && <TeamSwitcher variant="mobile" />}
        {authenticated && searchEnabled && (
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

export function MobileTabBar({ authenticated, isAdmin, capabilities, isPublic, onLogout }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);
  const previousPathnameRef = useRef(pathname);

  // Close the drawer only when navigation ACTUALLY lands somewhere else.
  // A late shell mount/hydration effect must not race the Menu click and
  // immediately close a drawer that was just opened (V1-131 mobile L4).
  useEffect(() => {
    if (previousPathnameRef.current !== pathname) {
      previousPathnameRef.current = pathname;
      setMenuOpen(false);
    }
  }, [pathname]);

  // Logged out, the authed tab set filtered by "is this public" left
  // Home and the Menu button — and no Sign in anywhere in the mobile
  // chrome, so the only way into the app from a phone was a button on
  // the landing page.  Logged-out visitors get their own three tabs.
  //
  // ``authenticated`` is deliberately three-valued (useAuth.js): true /
  // false are answers from the server; null (or undefined, before the
  // first render settles) means "still checking, or a probe failed" —
  // and the hook's own contract is that this renders as NEUTRAL chrome,
  // "no authed surfaces, but no Login affordance either"
  // (useAuth.js:37-39). TopBar already keys its desktop nav on this
  // exact three-way split (TopBar.jsx::visibleGroups); this mirrors it
  // for the mobile tab set. Collapsing "still checking" into the same
  // branch as a confirmed sign-out put "Sign in" on screen for an
  // already-signed-in visitor for as long as the auth probe took, then
  // swapped to the real tab set the moment it resolved (V1-131 mobile
  // L4 residual — a different mechanism than the pathname-close race
  // #1149 fixed). MOBILE_TABS_UNKNOWN carries no claim in either
  // direction.
  const tabs =
    authenticated === true
      ? MOBILE_TABS
      : authenticated === false
        ? MOBILE_TABS_PUBLIC
        : MOBILE_TABS_UNKNOWN;

  // Tab active state: longest-prefix winner among the tabs so /trade
  // lights Trade, not Home; the Menu button is active-by-none like the
  // legacy /more (but visually only, it is a button not a route).
  const activeTab = tabs.reduce((best, tab) => {
    if (!isNavActive(tab.href, pathname)) return best;
    if (!best || tab.href.length > best.href.length) return tab;
    return best;
  }, null);

  // Capability gating first, and for BOTH branches — the drawer is a nav
  // offer surface exactly like the desktop menus, so a destination whose
  // endpoints all 503 must not appear here either (V1-131).  Fails
  // closed on an unresolved capability.
  const model = navGroupsFor({ capabilities });

  const groups = authenticated
    ? [...model, { ...SYSTEM_MODEL, items: systemItemsFor({ isAdmin }) }]
    : model.map((g) => {
        if (!g.items) return isPublic(g.href) ? g : null;
        const items = g.items.filter((i) => isPublic(i.href));
        return items.length ? { ...g, items } : null;
      }).filter(Boolean);

  return (
    <>
      <nav className="shell-tabbar psi-editorial" aria-label="Primary" data-html2canvas-ignore>
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

      <Drawer
        open={menuOpen}
        onClose={() => setMenuOpen(false)}
        title="Menu"
        className="psi-editorial"
      >
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
