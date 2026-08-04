"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
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
// `ssr: false` because both are interaction-only surfaces with no
// server-rendered content to hydrate. Pattern matches
// app/league/sections/draft-capital.jsx.
const PlayerPopup = dynamic(() => import("@/components/PlayerPopup"), {
  ssr: false,
});
const CommandPalette = dynamic(
  () => import("@/components/shell/CommandPalette"),
  { ssr: false },
);

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
      {privateDataEnabled && popupRow && (
        <PlayerPopup
          row={popupRow}
          siteKeys={siteKeys}
          onClose={() => setPopupRow(null)}
          onAddToTrade={addToTradeRef.current ? handleAddToTrade : null}
        />
      )}

      {searchEnabled && searchOpen && (
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
