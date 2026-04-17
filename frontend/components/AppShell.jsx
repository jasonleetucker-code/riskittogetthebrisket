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
export default function AppShell({ children }) {
  const pathname = usePathname();
  const privateDataEnabled = !isPublicOnlyRoute(pathname);

  return privateDataEnabled ? (
    <PrivateAppShell>{children}</PrivateAppShell>
  ) : (
    <PublicAppShell>{children}</PublicAppShell>
  );
}

function PrivateAppShell({ children }) {
  const { loading, error, rows, siteKeys, rawData } = useDynastyData();
  return (
    <InnerAppShell
      loading={loading}
      error={error}
      rows={rows}
      siteKeys={siteKeys}
      rawData={rawData}
      privateDataEnabled={true}
    >
      {children}
    </InnerAppShell>
  );
}

function PublicAppShell({ children }) {
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
    >
      {children}
    </InnerAppShell>
  );
}

function InnerAppShell({ loading, error, rows, siteKeys, rawData, privateDataEnabled, children }) {
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
      // Look up by name
      const found = rows.find((r) => r.name === row);
      if (found) setPopupRow(found);
    } else {
      setPopupRow(row);
    }
  }, [rows, privateDataEnabled]);

  const openSearch = useCallback(() => {
    if (!privateDataEnabled) return;
    setSearchOpen(true);
  }, [privateDataEnabled]);

  // Global "/" keyboard shortcut for search
  useEffect(() => {
    if (!privateDataEnabled) return undefined;
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
  }, [privateDataEnabled]);

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
        <>
          <PlayerPopup
            row={popupRow}
            siteKeys={siteKeys}
            onClose={() => setPopupRow(null)}
            onAddToTrade={addToTradeRef.current ? handleAddToTrade : null}
          />

          <GlobalSearch
            rows={rows}
            isOpen={searchOpen}
            onClose={() => setSearchOpen(false)}
            onSelect={(row) => openPlayerPopup(row)}
          />
        </>
      )}
    </AppContext.Provider>
  );
}
