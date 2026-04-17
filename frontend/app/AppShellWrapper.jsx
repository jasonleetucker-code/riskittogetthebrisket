"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, createContext, useContext } from "react";
import AppShell, { useApp } from "@/components/AppShell";
import { useAuth } from "@/components/useAuth";

// ── Route definitions ────────────────────────────────────────────────────
// Primary destinations shown in desktop top nav
const PRIMARY_NAV = [
  { href: "/rankings", label: "Rankings" },
  { href: "/trade", label: "Trade" },
  { href: "/edge", label: "Edge" },
  { href: "/finder", label: "Finder" },
  { href: "/league", label: "League" },
  { href: "/settings", label: "Settings" },
  { href: "/more", label: "More" },
];

// Mobile bottom nav — 4-tab model
const MOBILE_NAV = [
  { href: "/rankings", label: "Ranks", icon: "R" },
  { href: "/trade", label: "Trade", icon: "T" },
  { href: "/league", label: "League", icon: "L" },
  { href: "/more", label: "More", icon: "M" },
];

// Routes that do NOT require auth (public pages)
const PUBLIC_ROUTES = new Set(["/", "/login", "/draft-capital", "/trades"]);

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
                className={`nav-link${active ? " nav-active" : ""}`}
              >
                {item.label}
              </Link>
            );
          })}
          <button
            className="nav-link nav-search-btn"
            onClick={openSearch}
            title="Search players (press /)"
          >
            /
          </button>
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

  const visibleItems = MOBILE_NAV.filter(
    (item) => authenticated || PUBLIC_ROUTES.has(item.href),
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

  // Derive page title from current route
  const pageTitle = (() => {
    const route = pathname?.split("/")[1] || "";
    const titles = {
      "": "Home",
      rankings: "Rankings",
      trade: "Trade",
      edge: "Edge",
      finder: "Finder",
      league: "League",
      rosters: "Rosters",
      trades: "Trades",
      settings: "Settings",
      login: "Login",
      more: "More",
      "draft-capital": "Draft Capital",
    };
    return titles[route] || "Brisket";
  })();

  return (
    <header className="mobile-topbar mobile-only">
      <Link href="/" className="mobile-brand">Brisket</Link>
      <span className="mobile-page-title">{pageTitle}</span>
      <div className="mobile-topbar-actions">
        <button className="mobile-search-btn" onClick={openSearch} title="Search" aria-label="Search">
          /
        </button>
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
      <AppShell>
        <DesktopNav />
        <MobileTopBar />
        <main className="main-shell">{children}</main>
        <MobileNav />
      </AppShell>
    </AuthContext.Provider>
  );
}
