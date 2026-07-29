"use client";

/**
 * AppShellWrapper — the app chrome (Redesign R1).
 *
 * Composes the R1 shell: skip link, desktop TopBar, mobile chrome
 * (top bar + tab bar + menu drawer), StaleDataBanner, main landmark,
 * ScreenshotFab. The navigation IA lives in lib/nav-model.js — ONE
 * model rendered per viewport, never two products.
 *
 * Unchanged contracts (R1 constraints):
 *   • PUBLIC_ROUTES — same set, same gating semantics: logged-out
 *     visitors see only public destinations plus Login.
 *   • AuthContext / useAuthContext — same shape, same consumers
 *     (login, draft, waivers pages).
 *   • AppShell mounts inside, providing data context + player popup +
 *     command palette exactly as before.
 *
 * A11y (R1): skip link as first focusable, <main id="main"> landmark
 * with focus moved onto it after client-side route changes (screen
 * readers announce the new page), aria-current on active nav.
 */
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef } from "react";
import AppShell, { useApp } from "@/components/AppShell";
import { useAuth } from "@/components/useAuth";
import ScreenshotFab from "@/components/ScreenshotFab";
import StaleDataBanner from "@/components/StaleDataBanner";
import TopBar from "@/components/shell/TopBar";
import { MobileTopBar, MobileTabBar } from "@/components/shell/MobileChrome";
import { isPublicPath } from "@/lib/public-routes";

// Which destinations a logged-out visitor sees in the nav.  The
// definition is shared with middleware.js and robots.js — see
// lib/public-routes.js for why it stopped living here as a local
// exact-match Set (`/league/activity` is public but was being hidden,
// and `/trades` was listed public while rendering private trade
// grades).
function isPublicRoute(href) {
  return isPublicPath(href);
}

// ── Auth context ─────────────────────────────────────────────────────────
const AuthContext = createContext({
  authenticated: null,
  isAdmin: false,
  checking: true,
  logout: () => {},
});

export function useAuthContext() {
  return useContext(AuthContext);
}

/**
 * Move focus to the main landmark after CLIENT-SIDE navigation (not on
 * initial load), so keyboard/screen-reader users land at the content
 * instead of deep inside the nav they just used.
 */
function RouteFocusManager({ mainRef }) {
  const pathname = usePathname();
  const firstRender = useRef(true);
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    mainRef.current?.focus({ preventScroll: false });
  }, [pathname, mainRef]);
  return null;
}

function ShellChrome({ children }) {
  const { authenticated, isAdmin, logout } = useAuthContext();
  const mainRef = useRef(null);

  // openSearch comes from AppShell's context — ShellChrome renders
  // INSIDE AppShell so the search affordances can reach it.
  return (
    <AppShellSearchBridge>
      {(openSearch) => (
        <>
          <a href="#main" className="shell-skip-link">
            Skip to content
          </a>
          <TopBar
            authenticated={authenticated}
            isAdmin={isAdmin}
            isPublic={isPublicRoute}
            onSearch={openSearch}
            onLogout={logout}
          />
          <MobileTopBar authenticated={authenticated} onSearch={openSearch} />
          <StaleDataBanner />
          <RouteFocusManager mainRef={mainRef} />
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            className="main-shell shell-main"
          >
            {children}
          </main>
          <MobileTabBar
            authenticated={authenticated}
            isAdmin={isAdmin}
            isPublic={isPublicRoute}
            onLogout={logout}
          />
          <ScreenshotFab />
        </>
      )}
    </AppShellSearchBridge>
  );
}

// Small bridge so the chrome (rendered inside AppShell) can hand the
// context's openSearch down to both nav bars without re-importing
// useApp in every shell component.
function AppShellSearchBridge({ children }) {
  const { openSearch } = useApp();
  return children(openSearch);
}

// ── Main shell wrapper ───────────────────────────────────────────────────
export default function AppShellWrapper({ children }) {
  const auth = useAuth();

  return (
    <AuthContext.Provider value={auth}>
      <AppShell authenticated={auth.authenticated === true}>
        <ShellChrome>{children}</ShellChrome>
      </AppShell>
    </AuthContext.Provider>
  );
}
