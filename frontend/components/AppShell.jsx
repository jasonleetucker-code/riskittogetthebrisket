"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
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
});

export function useApp() {
  return useContext(AppContext);
}

/**
 * AppShell provides app-wide data, player popup, and global search.
 * Wrap children in layout.jsx.
 */
export default function AppShell({ children }) {
  const { loading, error, rows, siteKeys, rawData } = useDynastyData();

  // Player popup state
  const [popupRow, setPopupRow] = useState(null);

  // Global search state
  const [searchOpen, setSearchOpen] = useState(false);

  const openPlayerPopup = useCallback((row) => {
    if (typeof row === "string") {
      // Look up by name
      const found = rows.find((r) => r.name === row);
      if (found) setPopupRow(found);
    } else {
      setPopupRow(row);
    }
  }, [rows]);

  const openSearch = useCallback(() => setSearchOpen(true), []);

  // Global "/" keyboard shortcut for search
  useEffect(() => {
    function onKeyDown(e) {
      // Don't trigger if typing in an input/textarea/select
      const tag = e.target?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        setSearchOpen(true);
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, []);

  return (
    <AppContext.Provider value={{ rows, siteKeys, rawData, loading, error, openPlayerPopup, openSearch }}>
      {children}

      {/* Player popup (app-wide) */}
      <PlayerPopup
        row={popupRow}
        siteKeys={siteKeys}
        onClose={() => setPopupRow(null)}
        onAddToTrade={null}
      />

      {/* Global search (app-wide) */}
      <GlobalSearch
        rows={rows}
        isOpen={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelect={(row) => openPlayerPopup(row)}
      />
    </AppContext.Provider>
  );
}
