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
// Fixing it here does not fix the ambient one.
//
// AMENDED 2026-08-05: the ambient one is NOT "its own defect", which is
// what this comment used to say. It is React 19.2's deferred Suspense
// reveal, read from the pinned react-dom source: `$RC` stages the content
// in `<div hidden id="S:n">`, sets the boundary comment to "$~", and only
// `$RV` — scheduled on rAF, then throttled up to 300ms — moves it and
// deletes the container. A duplicate is SUPPOSED to exist for that window
// and no app change removes it; a user never sees it (no client rects,
// never in the accessibility tree). Reproduced locally at 2/25 loads on
// /waivers under CPU throttling. The E2E suite handles it with
// `awaitStreamSettled()` (tests/e2e/helpers/journey.js, added by #747).
//
// The distinction is the point: what `dynamic()` produced here was a
// PERMANENT duplicate, which React never cleans up. That is a real defect
// and is what the two strict locators exist to catch. Do not conflate them.
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
  // null means "no classified failure", which is NOT the same as a
  // failure of unknown kind — consumers must be able to tell those apart.
  failure: null,
  retry: () => {},
  openPlayerPopup: () => {},
  openSearch: () => {},
  registerAddToTrade: () => {},
  privateDataEnabled: true,
  searchEnabled: false,
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

// Routes that are PRIVATE but have no use for player data.  Deliberately
// a SECOND list rather than more entries in PUBLIC_ONLY_ROUTE_PREFIXES:
// that constant is a privacy boundary ("public visitors must not see the
// contract"), and every route below is one only a signed-in user reaches.
// Folding them together would make the next person auditing "what is
// public" read `/admin` off the public list and get a wrong answer.
//
// The win is real rather than bookkeeping: `prefetchBaseContract()` is
// called INSIDE useDynastyData (useDynastyData.js:111), which only
// PrivateAppShell mounts, so skipping that branch skips the multi-MB
// GET itself — not merely the ~1,100-row buildRows pass.
//
// Every entry was checked for `useApp()` / `useDynastyData()` consumers
// in its tree.  Two candidates were REJECTED and must stay off this list:
//   /settings              — calls useDynastyData() directly (page.jsx),
//                            so gating the shell would not even stop its
//                            fetch; it would only strip its search.
//   /tools/trade-coverage  — reads useApp().rawData to build the audit.
const NO_PLAYER_DATA_ROUTE_PREFIXES = [
  "/login",
  "/more",
  "/design",
  "/admin",
  "/tools/source-health",
  "/tools/ros-data-health",
];

function isNoPlayerDataRoute(pathname) {
  if (!pathname) return false;
  return NO_PLAYER_DATA_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(prefix + "/"),
  );
}

// Exported for direct unit testing — these are pure functions and cheap
// to pin, and a wrong entry breaks a page rather than slowing it.
export const __routeGates = {
  PUBLIC_ONLY_ROUTE_PREFIXES,
  NO_PLAYER_DATA_ROUTE_PREFIXES,
  isPublicOnlyRoute,
  isNoPlayerDataRoute,
};

/**
 * AppShell provides app-wide data, player popup, and global search.
 * Wrap children in layout.jsx.
 *
 * For PUBLIC-only routes, AppShell refuses to hydrate private data.
 * See PUBLIC_ONLY_ROUTE_PREFIXES above.
 */
export default function AppShell({ children, authenticated = false, capabilities = null }) {
  const pathname = usePathname();
  // Two INDEPENDENT reasons to skip the player pipeline, composed rather
  // than merged: one is a privacy boundary, one is "this page has no use
  // for it".  Each stays readable on its own.
  //
  // Gating on `authenticated` instead of a route list was considered and
  // rejected: useAuth is tri-state and AppShellWrapper passes
  // `authenticated === true`, so it is `false` during the auth probe.
  // That would serialize the contract fetch behind an auth round-trip on
  // EVERY page — trading a wasted fetch on /login for a slower first
  // paint everywhere.
  const privateDataEnabled =
    !isPublicOnlyRoute(pathname) && !isNoPlayerDataRoute(pathname);

  return privateDataEnabled ? (
    <PrivateAppShell authenticated={authenticated} capabilities={capabilities}>
      {children}
    </PrivateAppShell>
  ) : (
    <NoPlayerDataAppShell authenticated={authenticated} capabilities={capabilities}>
      {children}
    </NoPlayerDataAppShell>
  );
}

function PrivateAppShell({ children, authenticated, capabilities }) {
  const { loading, error, failure, retry, rows, siteKeys, rawData } =
    useDynastyData();
  return (
    <InnerAppShell
      loading={loading}
      error={error}
      failure={failure}
      retry={retry}
      rows={rows}
      siteKeys={siteKeys}
      rawData={rawData}
      privateDataEnabled={true}
      authenticated={authenticated}
      capabilities={capabilities}
    >
      {children}
    </InnerAppShell>
  );
}

// Serves BOTH reasons above: the public /league subtree, where hydrating
// /api/data would leak private data, and private routes that simply have
// no player data to show.  Named for what it does (no player data) rather
// than for either reason, since it now answers to two.
function NoPlayerDataAppShell({ children, authenticated, capabilities }) {
  // No useDynastyData call — the public page pipeline must never
  // hydrate from /api/data.  The search + popup components render
  // against an empty rows list so they simply no-op rather than
  // leaking private identifiers into the public DOM.
  return (
    <InnerAppShell
      loading={false}
      error=""
      failure={null}
      retry={() => {}}
      rows={[]}
      siteKeys={[]}
      rawData={null}
      privateDataEnabled={false}
      authenticated={authenticated}
      capabilities={capabilities}
    >
      {children}
    </InnerAppShell>
  );
}

function InnerAppShell({ loading, error, failure, retry, rows, siteKeys, rawData, privateDataEnabled, authenticated, capabilities, children }) {
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
        // `error` is the message string, kept because every existing
        // consumer reads it.  `failure` is the CLASSIFIED state — kind,
        // code, retryable — and `retry` the affordance that goes with it.
        // Both were added to useDynastyData when contract failures were
        // classified, and then stopped here: the context forwarded only
        // the string, so /rosters, /league and the player pages could not
        // tell a 503 from a 403 however well the hook classified it, and
        // kept rendering failures through the EMPTY primitive.
        failure,
        retry,
        openPlayerPopup,
        openSearch,
        registerAddToTrade,
        privateDataEnabled,
        // Exposed so the chrome can HIDE the search affordance rather
        // than render one that no-ops.  openSearch() returns early when
        // this is false, but TopBar/MobileTopBar gated the button on
        // `authenticated` alone — so a signed-in user on /league has been
        // seeing a dead search button, and gating more routes would have
        // spread that.  Search genuinely cannot work without the
        // contract (it searches players), so hiding it is the honest
        // outcome, not a compromise.
        searchEnabled,
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
          // Nav offers in the palette obey the same capability gate as
          // the menus — hiding an entry from the drawer while ⌘K still
          // routes there would leave V1-131 half-fixed.
          capabilities={capabilities}
          isOpen={searchOpen}
          onClose={() => setSearchOpen(false)}
          onSelect={(row) => openPlayerPopup(row)}
        />
      )}
    </AppContext.Provider>
  );
}
