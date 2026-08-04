"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useDynastyData } from "@/components/useDynastyData";
import { buildTeamByPlayer } from "@/lib/waiver-logic";
// Both live in the ROOT LAYOUT, so a static import puts them in the
// chunk set every one of ~90 routes downloads and parses — 69 KB of it,
// measured. Neither is reachable until the user acts: PlayerPopup needs
// a player click, CommandPalette needs "/" or the search button.
//
// On /league it is worse than deferred, it is dead: `privateDataEnabled`
// is false there (PUBLIC_ONLY_ROUTE_PREFIXES below), so PlayerPopup was
// provably unreachable on the route with the largest bundle.
//
// ⚠ DO NOT "SIMPLIFY" THIS BACK TO `dynamic()`. It looks like the obvious
// tool and it silently duplicates every page in the app.
//
// `dynamic()` is `React.lazy`, which needs a Suspense boundary. AppShell
// has no local one, so the nearest ancestor is the App Router's — and
// `{children}`, the entire page, renders inside it. Every route's content
// then became deferred streaming content: emitted into React's
// `<div id="S:1">` staging container, moved into place, and the staged
// copy left behind. /waivers served three <main> elements: the shell's,
// the page's, and a hidden second full copy of the page.
//
// The duplicate has no client rects and never reaches the accessibility
// tree, so it is invisible in a screenshot, in the a11y snapshot, and to
// a human clicking around. It is still duplicate DOM, duplicate element
// ids, and every page's markup rendered twice — a regression in the exact
// dimension this split exists to improve. The only thing that caught it
// was a Playwright strict-mode violation ("resolved to 2 elements"), and
// that suite does not run on PRs.
//
// Measured on Next 16.2.12, /waivers:
//   static imports                 1 copy, +69 KB on every route
//   dynamic() bare                 2 copies on EVERY load, 3 <main>, #S:1 present
//   dynamic() + local <Suspense>   1 copy
//   imperative import (this)       1 copy, split preserved
// It reproduces with and without `ssr: false` — that flag was a red herring.
//
// One caveat, so nobody re-opens this on a red CI run: the app has an
// AMBIENT version of the same race that predates all of this, measured at
// 1/45 loads on /waivers and 1/15 on /arbitrage — identical rates on a
// build of main and a build of this branch. What `dynamic()` did was turn
// that occasional race into a certainty on every load of every route.
// Fixing it here does not fix the ambient one, which is its own defect.
//
// So the boundary must not exist. Loading the module imperatively is the
// idiom this repo already uses for exactly this (components/ScreenshotFab.jsx
// does `const { default: html2canvas } = await import("html2canvas")`):
// there is no lazy component, nothing suspends, and webpack still emits a
// separate chunk — the whole 69 KB win with none of the streaming
// machinery.
//
// app/league/sections/*.jsx keep using dynamic() and are fine: those
// boundaries wrap only their own section, never the page.

/**
 * Load a module's default export on demand, once, and return it (null
 * until it lands). `enabled` gates the fetch so the chunk is requested
 * the first time the surface is actually needed, not on mount.
 *
 * Deliberately NOT React.lazy — see the note above.
 */
function useLazyComponent(enabled, loader) {
  const [Component, setComponent] = useState(null);
  const loaderRef = useRef(loader);
  useEffect(() => {
    if (!enabled || Component) return undefined;
    let alive = true;
    loaderRef
      .current()
      // Stored via an updater fn: setState treats a bare function as a
      // reducer, and a component IS a function.
      .then((mod) => { if (alive) setComponent(() => mod.default); })
      .catch(() => { /* chunk fetch failed; the surface stays closed */ });
    return () => { alive = false; };
  }, [enabled, Component]);
  return Component;
}

// ── App-wide context for popup and search ────────────────────────────────
const AppContext = createContext({
  rows: [],
  siteKeys: [],
  rawData: null,
  loading: true,
  error: "",
  openPlayerPopup: () => {},
  openSearch: () => {},
  registerAddToTrade: () => {},
  privateDataEnabled: true,
});

export function useApp() {
  return useContext(AppContext);
}

// Routes that render on a PUBLIC-only data pipeline.  AppShell must
// NOT hydrate useDynastyData() for these paths because the private
// contract on /api/data leaks private rankings, edge signals, trade
// targets, and source-override state that public visitors must not
// see.  The public /league page hydrates from /api/public/league
// through its own dedicated fetch — see frontend/lib/public-league-data.js.
const PUBLIC_ONLY_ROUTE_PREFIXES = ["/league"];

function isPublicOnlyRoute(pathname) {
  if (!pathname) return false;
  return PUBLIC_ONLY_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/"),
  );
}

/**
 * AppShell provides app-wide data, player popup, and global search.
 * Wrap children in layout.jsx.
 *
 * For PUBLIC-only routes, AppShell refuses to hydrate private data.
 * See PUBLIC_ONLY_ROUTE_PREFIXES above.
 */
export default function AppShell({ children, authenticated = false }) {
  const pathname = usePathname();
  const privateDataEnabled = !isPublicOnlyRoute(pathname);

  return privateDataEnabled ? (
    <PrivateAppShell authenticated={authenticated}>{children}</PrivateAppShell>
  ) : (
    <PublicAppShell authenticated={authenticated}>{children}</PublicAppShell>
  );
}

function PrivateAppShell({ children, authenticated }) {
  const { loading, error, rows, siteKeys, rawData } = useDynastyData();
  return (
    <InnerAppShell
      loading={loading}
      error={error}
      rows={rows}
      siteKeys={siteKeys}
      rawData={rawData}
      privateDataEnabled={true}
      authenticated={authenticated}
    >
      {children}
    </InnerAppShell>
  );
}

function PublicAppShell({ children, authenticated }) {
  // No useDynastyData call — the public page pipeline must never
  // hydrate from /api/data.  The search + popup components render
  // against an empty rows list so they simply no-op rather than
  // leaking private identifiers into the public DOM.
  return (
    <InnerAppShell
      loading={false}
      error=""
      rows={[]}
      siteKeys={[]}
      rawData={null}
      privateDataEnabled={false}
      authenticated={authenticated}
    >
      {children}
    </InnerAppShell>
  );
}

function InnerAppShell({ loading, error, rows, siteKeys, rawData, privateDataEnabled, authenticated, children }) {
  // Player search requires an authenticated session.  Search against
  // the private contract leaks ranking data and private identifiers
  // to logged-out visitors on otherwise-public surfaces.
  const searchEnabled = privateDataEnabled && authenticated;
  // Player popup state
  const [popupRow, setPopupRow] = useState(null);

  // Global search state
  const [searchOpen, setSearchOpen] = useState(false);

  // Both chunks are fetched on first need and kept thereafter.
  const PlayerPopup = useLazyComponent(
    privateDataEnabled && Boolean(popupRow),
    () => import("@/components/PlayerPopup"),
  );
  const CommandPalette = useLazyComponent(
    searchEnabled && searchOpen,
    () => import("@/components/shell/CommandPalette"),
  );

  // Add-to-trade callback (registered by trade page when mounted)
  const addToTradeRef = useRef(null);
  const registerAddToTrade = useCallback((fn) => { addToTradeRef.current = fn; }, []);
  const handleAddToTrade = useCallback((row) => {
    if (addToTradeRef.current) addToTradeRef.current(row);
  }, []);

  const openPlayerPopup = useCallback((row) => {
    if (!privateDataEnabled) return;
    if (typeof row === "string") {
      // Look up by name (case-insensitive).  When the same display
      // name resolves to multiple universes (rare offense/IDP
      // collision), this picks the first row encountered — callers
      // that care should pass ``{ name, assetClass }`` instead.
      const lowered = row.toLowerCase();
      const found = rows.find((r) => String(r.name).toLowerCase() === lowered);
      if (found) setPopupRow(found);
      return;
    }
    if (!row || typeof row !== "object") return;
    // When the caller supplies ``{ name, assetClass }`` (e.g. the
    // movers panel surfacing a scoped rank-history entry) and no
    // contract data, resolve to the matching live row using both
    // name + assetClass so offense/IDP collisions land on the right
    // universe.  When the caller already has a full contract row we
    // skip the lookup.
    const looksLikeFullRow =
      row.rankDerivedValue != null ||
      row.values != null ||
      row.canonicalConsensusRank != null;
    if (!looksLikeFullRow && row.name) {
      const lowered = String(row.name).toLowerCase();
      const ac = row.assetClass != null ? String(row.assetClass).toLowerCase() : "";
      const found = rows.find((r) => {
        if (String(r.name).toLowerCase() !== lowered) return false;
        if (!ac) return true;
        return String(r.assetClass || "").toLowerCase() === ac;
      });
      if (found) {
        setPopupRow(found);
        return;
      }
    }
    setPopupRow(row);
  }, [rows, privateDataEnabled]);

  const openSearch = useCallback(() => {
    if (!searchEnabled) return;
    setSearchOpen(true);
  }, [searchEnabled]);

  // League-scoped ownership index for the command palette's owner: tokens.
  // Rows are scoring-profile-scoped and never carry the owner; the
  // join happens here at render time (CLAUDE.md split).
  const teamByPlayer = useMemo(
    () => buildTeamByPlayer(rawData?.sleeper?.teams || []),
    [rawData?.sleeper?.teams],
  );

  // Global keyboard shortcuts for search: "/" (legacy, preserved) and
  // Cmd/Ctrl+K (the standard command-palette chord — R1 additive).
  useEffect(() => {
    if (!searchEnabled) return undefined;
    function onKeyDown(e) {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setSearchOpen(true);
        return;
      }
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [searchEnabled]);

  return (
    <AppContext.Provider
      value={{
        rows,
        siteKeys,
        rawData,
        loading,
        error,
        openPlayerPopup,
        openSearch,
        registerAddToTrade,
        privateDataEnabled,
      }}
    >
      {children}

      {/* Gated on `popupRow` / `searchOpen`, not just the enable flags —
          and that is what makes the dynamic import above pay. A
          `dynamic()` component fetches its chunk when it RENDERS, so
          rendering it unconditionally would merely move 69 KB off the
          critical path instead of off the page. Both gates are
          behaviour-preserving: PlayerPopup already rendered a
          `<Drawer open={Boolean(row)}>` (null without a row) and
          CommandPalette a dialog that returns null while closed, so the
          rendered output is identical either way.

          The "/" shortcut lives here in AppShell (see the keydown
          handler above), not inside CommandPalette, so gating on
          `searchOpen` cannot break the way it is opened. */}
      {/* `PlayerPopup &&` is the load gate, not a style choice: the
          component is null until its chunk lands. That gap is a frame or
          two on a warm connection and is invisible — the drawer animating
          in is the feedback either way. */}
      {privateDataEnabled && popupRow && PlayerPopup && (
        <PlayerPopup
          row={popupRow}
          siteKeys={siteKeys}
          onClose={() => setPopupRow(null)}
          onAddToTrade={addToTradeRef.current ? handleAddToTrade : null}
        />
      )}

      {searchEnabled && searchOpen && CommandPalette && (
        <CommandPalette
          rows={rows}
          teamByPlayer={teamByPlayer}
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onSelect={(row) => openPlayerPopup(row)}
        />
      )}
    </AppContext.Provider>
  );
}
