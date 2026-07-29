"use client";

/**
 * TopBar — the desktop shell header (R1).
 *
 * Layout decision (documented in shell.css + docs/DESIGN-SYSTEM.md):
 * a top bar, not a left rail — tables are the product and keep every
 * horizontal pixel; the grouped IA fits six top-level entries; the
 * command palette is the power-user accelerator.
 *
 * Left → right: brand · NAV_MODEL (direct links + group menus) ·
 * league/team switchers · search affordance · System menu (settings,
 * ops, sign out). Auth gating preserves the legacy semantics: an
 * unauthenticated visitor sees only PUBLIC_ROUTES destinations plus
 * Login; group menus filter to their public children.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon } from "@/components/ds";
import NavMenu from "@/components/shell/NavMenu";
import TeamSwitcher from "@/components/TeamSwitcher";
import LeagueSwitcher from "@/components/LeagueSwitcher";
import {
  NAV_MODEL,
  SYSTEM_MODEL,
  isGroupActive,
  isNavActive,
  systemItemsFor,
} from "@/lib/nav-model";

function visibleGroups(authenticated, isPublic) {
  if (authenticated) return NAV_MODEL;
  // ``authenticated`` is tri-state: null means "not resolved yet".  The
  // public subset is the answer for a KNOWN signed-out visitor, not a
  // safe default for an unknown one — every other consumer in this file
  // already gates on the explicit booleans (`authenticated &&` for the
  // switchers, `authenticated === false &&` for Login), and the nav was
  // the one place that guessed.  Guessing cost real layout: signed-in
  // users got a 2-item public nav on the first paint and then had four
  // items INSERTED into it, sliding "Trade" 185px→335px and "League"
  // 266px→586px (the horizontal half of /waivers' 0.180 CLS, and the
  // same shift on every route since this is the shell).  Rendering
  // nothing until we know is not a shift: the nav sits between a
  // left-aligned brand and a `margin-left: auto` right rail, so items
  // appearing fill their own space without moving either neighbour.
  if (authenticated === null || authenticated === undefined) return [];
  return NAV_MODEL.map((group) => {
    if (!group.items) return isPublic(group.href) ? group : null;
    const items = group.items.filter((i) => isPublic(i.href));
    if (items.length === 0) return null;
    return { ...group, items };
  }).filter(Boolean);
}

export default function TopBar({ authenticated, isAdmin, isPublic, onSearch, onLogout }) {
  const pathname = usePathname();
  const groups = visibleGroups(authenticated, isPublic);
  const systemItems = systemItemsFor({ isAdmin });

  return (
    <header className="shell-topbar" data-html2canvas-ignore>
      <div className="shell-topbar-inner">
        <Link href="/" className="shell-brand">
          <span className="shell-brand-mark" aria-hidden="true">
            ▪
          </span>
          Chase Upside
        </Link>
        <nav className="shell-nav" aria-label="Primary">
          {groups.map((group) =>
            group.items && group.items.length > 0 ? (
              <NavMenu
                key={group.key}
                label={group.label}
                href={group.href}
                items={group.items}
                active={isGroupActive(group, pathname)}
                pathname={pathname}
              />
            ) : (
              <Link
                key={group.key}
                href={group.href}
                title={group.hint || group.label}
                className="shell-nav-link"
                aria-current={isNavActive(group.href, pathname) ? "page" : undefined}
              >
                {group.label}
              </Link>
            )
          )}
        </nav>
        <div className="shell-nav-right">
          {authenticated && <LeagueSwitcher variant="desktop" />}
          {authenticated && <TeamSwitcher variant="desktop" />}
          {authenticated && (
            <button
              type="button"
              className="shell-search-btn"
              onClick={onSearch}
              title="Search players, picks, and pages"
            >
              <Icon name="search" size={12} />
              Search
              <span className="shell-kbd" aria-hidden="true">
                /
              </span>
            </button>
          )}
          {authenticated && (
            <NavMenu
              label={SYSTEM_MODEL.label}
              items={systemItems}
              active={systemItems.some((i) => isNavActive(i.href, pathname))}
              pathname={pathname}
              align="right"
              renderExtra={
                <button
                  type="button"
                  role="menuitem"
                  className="shell-menu-item"
                  onClick={onLogout}
                >
                  Sign out
                </button>
              }
            />
          )}
          {authenticated === false && (
            <Link href="/login" className="shell-nav-link">
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}
