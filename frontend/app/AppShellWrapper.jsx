"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, createContext, useContext } from "react";
import AppShell, { useApp } from "@/components/AppShell";
import { useAuth } from "@/components/useAuth";
import ChatDrawer from "@/components/ChatDrawer";
import StaleDataBanner from "@/components/StaleDataBanner";
import TeamSwitcher from "@/components/TeamSwitcher";
import LeagueSwitcher from "@/components/LeagueSwitcher";

// ── Route definitions ────────────────────────────────────────────────────
// Primary destinations shown in desktop top nav.  ``hint`` populates the
// browser's native title tooltip on hover so a user passing over "Trade"
// vs. "Trades" vs. "Finder" vs. "Angle" can tell which one solves which
// problem without having to click through.  The /more page already shows
// these descriptions on mobile.
const PRIMARY_NAV = [
  { href: "/rankings", label: "Rankings", hint: "Player value board" },
  { href: "/trade", label: "Trade", hint: "Build and grade a trade" },
  { href: "/draft", label: "Draft", hint: "Rookie draft prep + ADP" },
  { href: "/edge", label: "Edge", hint: "Where sources disagree most" },
  { href: "/finder", label: "Finder", hint: "Find KTC arbitrage trades" },
  { href: "/angle", label: "Angle", hint: "Counter-package generator" },
  { href: "/league", label: "League", hint: "Public league hub" },
  { href: "/settings", label: "Settings", hint: "Source weights, TEP, profile" },
  { href: "/more", label: "More", hint: "Trades history, rosters, tools" },
];

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
          {PRIMARY_NAV.filter((item) => authenticated || PUBLIC_ROUTES.has(item.href)).map((item) => {
            const active = pathname === item.href || pathname?.startsWith(item.href + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                title={item.hint || item.label}
                className={`nav-link${active ? " nav-active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
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
