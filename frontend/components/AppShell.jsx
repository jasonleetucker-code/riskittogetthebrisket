"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useDynastyData } from "@/components/useDynastyData";
import PlayerPopup from "@/components/PlayerPopup";
import GlobalSearch from "@/components/GlobalSearch";

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

  // Global "/" keyboard shortcut for search
  useEffect(() => {
    if (!searchEnabled) return undefined;
    function onKeyDown(e) {
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

      {privateDataEnabled && (
        <PlayerPopup
          row={popupRow}
          siteKeys={siteKeys}
          onClose={() => setPopupRow(null)}
          onAddToTrade={addToTradeRef.current ? handleAddToTrade : null}
        />
      )}

      {searchEnabled && (
        <GlobalSearch
          rows={rows}
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onSelect={(row) => openPlayerPopup(row)}
        />
      )}
    </AppContext.Provider>
  );
}
