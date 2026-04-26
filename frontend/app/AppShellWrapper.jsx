"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useEffect, useRef, useState, createContext, useContext } from "react";
import AppShell, { useApp } from "@/components/AppShell";
import { useAuth } from "@/components/useAuth";
import ChatDrawer from "@/components/ChatDrawer";
import StaleDataBanner from "@/components/StaleDataBanner";
import TeamSwitcher from "@/components/TeamSwitcher";
import LeagueSwitcher from "@/components/LeagueSwitcher";

// ── Route definitions ────────────────────────────────────────────────────
// Primary destinations shown in desktop top nav.
//
// IA structure
// ────────────
// The four trade-related routes (Calculator / History / Arbitrage
// Finder / Counter-Pitch) used to live as four flat peers in the nav.
// They now collapse into a single parent ``Trade`` entry with a
// dropdown that lists the four sub-tools so the relationship is
// obvious without crowding the bar.  Direct URLs (/trade, /trades,
// /finder, /angle) all still work — the reorg is nav-only, no route
// changes.
//
// Mental model after this reorg:
//   Group 1 — daily workflow: Rankings, Trade ▾ (4 sub-tools), Draft
//   Group 2 — decision-support / discovery: Edge
//   Group 3 — public-facing: League
//   Group 4 — admin: Settings, More
//
// ``hint`` populates the browser's native title tooltip on hover.
// ``children`` makes an item a parent that opens a dropdown of its
// nested sub-routes.  Clicking the parent label still navigates to
// ``href`` (sensible default) — the dropdown surfaces the siblings.
const PRIMARY_NAV = [
  { href: "/rankings", label: "Rankings", hint: "Player value board" },
  { href: "/trending", label: "Trending", hint: "Biggest rank movers, last 1d/7d/30d" },
  {
    href: "/trade",
    label: "Trade",
    hint: "Trade workflow tools",
    children: [
      { href: "/trade", label: "Calculator", hint: "Build and grade a trade" },
      { href: "/trades", label: "History", hint: "Analyzed history of every league trade" },
      { href: "/finder", label: "Arbitrage Finder", hint: "Find KTC market gaps you can exploit" },
      { href: "/angle", label: "Counter-Pitch", hint: "Generate counter-package suggestions" },
    ],
  },
  { href: "/draft", label: "Draft", hint: "Rookie draft prep + ADP" },
  { href: "/edge", label: "Edge", hint: "Where sources disagree most", groupBreak: true },
  {
    href: "/league",
    label: "League",
    hint: "Public league hub",
    groupBreak: true,
    children: [
      { href: "/league", label: "Hub", hint: "League overview" },
      { href: "/league/activity", label: "Activity", hint: "Trades + news in one feed" },
      { href: "/league/phases", label: "Win-now vs Rebuild", hint: "Per-team phase classification + trade partners" },
    ],
  },
  { href: "/settings", label: "Settings", hint: "Source weights, TEP, profile", groupBreak: true },
  { href: "/more", label: "More", hint: "Rosters, tools, admin" },
];

// Routes that should mark the ``Trade`` parent as active in the
// dropdown UI.  Any pathname that starts with one of these prefixes
// counts as "we're inside the trade workflow group".
const TRADE_GROUP_PREFIXES = ["/trade", "/trades", "/finder", "/angle"];

// Mobile bottom nav — 3-tab model.  /league is intentionally NOT in
// this bar.  Users reach it via the More menu + desktop top nav; the
// league content (including Draft Capital) lives behind a single
// entry instead of a redundant bottom-row tab.
const MOBILE_NAV = [
  { href: "/rankings", label: "Ranks", icon: "R" },
  { href: "/trade", label: "Trade", icon: "T" },
  { href: "/more", label: "More", icon: "M" },
];

// Routes that do NOT require auth (public pages).  /league is backed
// by the isolated public pipeline in src/public_league/ and fetches
// only from /api/public/league — it never reads the private /api/data
// contract.
const PUBLIC_ROUTES = new Set(["/", "/login", "/draft-capital", "/trades", "/league"]);

// ── Auth context ─────────────────────────────────────────────────────────
const AuthContext = createContext({
  authenticated: null,
  checking: true,
  logout: () => {},
});

export function useAuthContext() {
  return useContext(AuthContext);
}

// ── Nav dropdown (used by the "Trade" parent in PRIMARY_NAV) ─────────────
function NavDropdown({ item, pathname, isActive }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);
  const closeTimer = useRef(null);

  // Hover dropdown with a 120 ms delay before close so a small
  // diagonal mouse drift between parent and a menu item doesn't snap
  // the menu shut.  Standard nav-menu behaviour.
  const handleEnter = useCallback(() => {
    if (closeTimer.current) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    setOpen(true);
  }, []);
  const handleLeave = useCallback(() => {
    closeTimer.current = setTimeout(() => setOpen(false), 120);
  }, []);

  // Close when focus leaves the wrapper (keyboard) and on Escape.
  const handleBlur = useCallback((e) => {
    if (!wrapRef.current) return;
    if (!wrapRef.current.contains(e.relatedTarget)) setOpen(false);
  }, []);
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Close the menu when the route actually changes (link click).
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  return (
    <span
      ref={wrapRef}
      className="nav-dropdown"
      onMouseEnter={handleEnter}
      onMouseLeave={handleLeave}
      onFocus={handleEnter}
      onBlur={handleBlur}
    >
      <Link
        href={item.href}
        title={item.hint || item.label}
        className={`nav-link nav-dropdown-trigger${isActive ? " nav-active" : ""}`}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {item.label}
        <span className="nav-dropdown-caret" aria-hidden="true">▾</span>
      </Link>
      {open && (
        <div role="menu" className="nav-dropdown-menu">
          {item.children.map((child) => {
            const childActive = pathname === child.href
              || pathname?.startsWith(child.href + "/");
            return (
              <Link
                key={child.href}
                href={child.href}
                role="menuitem"
                className={`nav-dropdown-item${childActive ? " nav-active" : ""}`}
              >
                <span className="nav-dropdown-item-label">{child.label}</span>
                {child.hint && (
                  <span className="nav-dropdown-item-hint">{child.hint}</span>
                )}
              </Link>
            );
          })}
        </div>
      )}
    </span>
  );
}

// ── Desktop top navigation bar ───────────────────────────────────────────
function DesktopNav() {
  const pathname = usePathname();
  const { openSearch } = useApp();
  const { authenticated, logout } = useContext(AuthContext);

  return (
    <header className="topbar desktop-only">
      <div className="topbar-inner">
        <Link href="/" className="brand">
          Risk It To Get The Brisket
        </Link>
        <nav className="nav">
          {(() => {
            const visible = PRIMARY_NAV.filter(
              (item) => authenticated || PUBLIC_ROUTES.has(item.href),
            );
            const out = [];
            visible.forEach((item, idx) => {
              if (item.groupBreak && idx > 0) {
                out.push(
                  <span
                    key={`sep-${item.href}`}
                    aria-hidden="true"
                    className="nav-group-sep"
                  />,
                );
              }
              if (item.children && item.children.length > 0) {
                // Parent item with a sub-menu — the parent's "active"
                // state fires for any path inside its child set so the
                // user always sees a highlighted top-level entry, even
                // on a deep child route.
                const groupActive = TRADE_GROUP_PREFIXES.some(
                  (prefix) =>
                    pathname === prefix || pathname?.startsWith(prefix + "/"),
                );
                out.push(
                  <NavDropdown
                    key={item.href}
                    item={item}
                    pathname={pathname}
                    isActive={groupActive}
                  />,
                );
                return;
              }
              const active = pathname === item.href || pathname?.startsWith(item.href + "/");
              out.push(
                <Link
                  key={item.href}
                  href={item.href}
                  title={item.hint || item.label}
                  className={`nav-link${active ? " nav-active" : ""}`}
                >
                  {item.label}
                </Link>,
              );
            });
            return out;
          })()}
          {authenticated && <LeagueSwitcher variant="desktop" />}
          {authenticated && <TeamSwitcher variant="desktop" />}
          {authenticated && (
            <button
              className="nav-link nav-search-btn"
              onClick={openSearch}
              title="Search players (press /)"
            >
              /
            </button>
          )}
          {authenticated && (
            <button className="nav-link nav-logout-btn" onClick={logout} title="Sign out">
              Sign out
            </button>
          )}
          {authenticated === false && (
            <Link href="/login" className="nav-link">
              Login
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}

// ── Mobile bottom navigation bar ─────────────────────────────────────────
function MobileNav() {
  const pathname = usePathname();
  const { authenticated } = useContext(AuthContext);

  const visibleItems = MOBILE_NAV.filter((item) =>
    authenticated || PUBLIC_ROUTES.has(item.href),
  );

  function isActive(href) {
    if (href === "/more") {
      const otherMobile = visibleItems.filter((n) => n.href !== "/more").map((n) => n.href);
      return !otherMobile.some(
        (h) => pathname === h || pathname?.startsWith(h + "/"),
      );
    }
    return pathname === href || pathname?.startsWith(href + "/");
  }

  return (
    <nav className="mobile-bottom-nav mobile-only" aria-label="Mobile Navigation">
      {visibleItems.map((item) => (
        <Link
          key={item.href}
          href={item.href}
          className={`mobile-nav-btn${isActive(item.href) ? " active" : ""}`}
        >
          <span className="mobile-nav-icon">{item.icon}</span>
          <span className="mobile-nav-label">{item.label}</span>
        </Link>
      ))}
    </nav>
  );
}

// ── Mobile top bar (compact header for mobile) ───────────────────────────
function MobileTopBar() {
  const pathname = usePathname();
  const { openSearch } = useApp();
  const { authenticated, logout } = useContext(AuthContext);

  // Derive page title from current route.  Top-level routes map to a
  // simple noun; deep routes under /league get a per-tab title so a
  // user landing on /league/franchise/<owner> sees "Franchise"
  // instead of the parent "League" — small but meaningful clarity
  // win for mobile, where the breadcrumb pattern doesn't fit.
  const pageTitle = (() => {
    const segments = (pathname || "").split("/").filter(Boolean);
    const top = segments[0] || "";
    const sub = segments[1] || "";
    if (top === "league" && sub) {
      const sublabels = {
        franchise: "Franchise",
        player: "Player",
        rivalry: "Rivalry",
        week: "Week recap",
        weekly: "Matchup",
      };
      if (sublabels[sub]) return sublabels[sub];
    }
    if (top === "tools" && sub) {
      const toolLabels = {
        "source-health": "Source health",
        "trade-coverage": "Trade coverage",
      };
      if (toolLabels[sub]) return toolLabels[sub];
    }
    const titles = {
      "": "Home",
      rankings: "Rankings",
      trade: "Trade",
      draft: "Draft",
      edge: "Edge",
      finder: "Finder",
      angle: "Angle",
      league: "League",
      rosters: "Rosters",
      trades: "Trades",
      settings: "Settings",
      login: "Login",
      more: "More",
      "draft-capital": "Draft Capital",
      tools: "Tools",
      admin: "Admin",
    };
    return titles[top] || "Brisket";
  })();

  return (
    <header className="mobile-topbar mobile-only">
      <Link href="/" className="mobile-brand">Brisket</Link>
      <span className="mobile-page-title">{pageTitle}</span>
      <div className="mobile-topbar-actions">
        {authenticated && <LeagueSwitcher variant="mobile" />}
        {authenticated && <TeamSwitcher variant="mobile" />}
        {authenticated && (
          <button className="mobile-search-btn" onClick={openSearch} title="Search" aria-label="Search">
            /
          </button>
        )}
        {authenticated && (
          <button
            className="mobile-signout-btn"
            onClick={logout}
            title="Sign out"
            aria-label="Sign out"
          >
            Sign out
          </button>
        )}
      </div>
    </header>
  );
}

// ── Main shell wrapper ───────────────────────────────────────────────────
export default function AppShellWrapper({ children }) {
  const auth = useAuth();

  return (
    <AuthContext.Provider value={auth}>
      <AppShell authenticated={auth.authenticated === true}>
        <DesktopNav />
        <MobileTopBar />
        <StaleDataBanner />
        <main className="main-shell">{children}</main>
        <MobileNav />
        <ChatDrawer />
      </AppShell>
    </AuthContext.Provider>
  );
}
