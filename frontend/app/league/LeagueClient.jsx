"use client";

// PUBLIC /league client shell (tabbed container).
//
// Wrapped by ./page.jsx — which is a server component that pre-fetches
// the sections the LANDING TAB needs so the first paint already has
// real data (no "Loading league data..." flash).  We accept that
// partial ``initialContract`` as a prop and fetch each remaining
// section only when the visitor opens the tab that renders it.
//
// Partial by design: the aggregate contract is 2.01 MB across 17
// sections, this page renders one tab at a time, and the prop is
// serialized into the RSC flight payload — so shipping all of it made
// the /league document 2.38 MB to render 7.6 KB of overview.  Two of
// those sections (``weeklyRecap``, ``matchupPreview``) are not read by
// this page at all since the AI-article tabs replaced those views.
//
// Critical isolation rules (enforced by AppShell.PUBLIC_ONLY_ROUTE_PREFIXES):
//   * NO imports from @/components/AppShell.useApp — the public route
//     runs inside PublicAppShell, which refuses to hydrate
//     useDynastyData.  Calling useApp here would still return empty
//     arrays, but importing the hook anywhere public makes it
//     trivially easy to accidentally leak private state later.
//   * NO imports from @/lib/league-analysis — that module operates on
//     the private canonical contract.  Everything here fetches the
//     public contract shape defined in src/public_league/public_contract.py.
//   * NO imports from @/lib/dynasty-data, @/lib/trade-logic, @/lib/edge-helpers.
//
// Data source: initialContract (server-rendered) OR /api/public/league
// via fetchPublicSection() — for the landing tab when SSR failed, and
// for every other tab on open.
//
// Section renderers live under ./sections/<name>.jsx so Next.js can
// code-split each tab.  Shared primitives (Avatar, Card, Stat, format
// helpers) live in shared.jsx and are imported by both tabbed and
// dedicated routes.

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { useRouter, useSearchParams } from "next/navigation";
import ResilientSection from "@/components/ResilientSection";
import { PageHeader, Tabs, tabId, tabPanelId, Select } from "@/components/ds";
import { LoadingState, EmptyState } from "@/components/ui";
import { PUBLIC_SECTION_KEYS, fetchPublicSection } from "@/lib/public-league-data";
import {
  DRAFT_CAPITAL_YEAR_PARAM,
  serializeDraftCapitalYear,
} from "@/lib/draft-capital-years";
import { buildManagerLookup } from "./shared.jsx";
import OverviewSection from "./sections/overview.jsx";
import leagueNavStyles from "./league-shared.module.css";
import {
  OVERVIEW_TAB,
  PIECE_OF_SHIT_RANKINGS_TAB,
  SECTION_FOR_TAB,
  TRADE_ADVISOR_SUBTITLE,
  TRADE_ADVISOR_TAB,
  TRADE_ADVISOR_TITLE,
  VALID_TABS,
  leagueTabHref,
  normalizeTabKey,
  resolveTab,
  visibleTabs,
} from "./tabs.js";


// Section code is split per tab.  Exactly ONE section is mounted at a
// time (see the `activeTab === …` chain below), but all 21 used to be
// statically imported, so /league shipped every section's code — 254 KB
// of source plus five hand-rolled SVG charts each reachable from a
// single tab — to render whichever one tab the visitor opened.
//
// `ssr: false` because the shell already server-renders the header and
// nav; a section is behind a tab the server cannot know the visitor will
// pick.  This composes with the per-section data fetching added in #652:
// the CODE for a tab and the DATA for a tab now both arrive on open.
//
// OverviewSection is deliberately NOT split — exactly as on main.  With
// the advisor switched off it is DEFAULT_TAB's fallback landing view, and
// an off flag must change nothing: same server-rendered markup (first
// paint, SEO) and the same bytes (flag-off /league was measured against
// origin/main; splitting Overview into its own preloaded chunks cost
// ~1.6 KB gzip of chunk overhead for no flag-off gain).  The advisor's
// team step is the split one instead (TradeAdvisorShell, below): it is
// only ever rendered while the advisor is served.
//
// Pattern (dynamic + `_`-prefixed siblings) matches
// ./sections/draft-capital.jsx, which already splits its own two heavy
// panels this way.
//
// KNOWN GAP, not fixed here (found 2026-09-06 investigating a W1-12
// production failure): none of the 20 `lazySection`-mounted tabs below
// are wrapped in an error boundary. A failed dynamic `import()` (e.g. a
// ChunkLoadError from a non-atomic deploy overwriting `.next/` while
// `next start` is serving — the exact class `next.config.mjs` already
// documents) or any render throw inside a lazy section falls through to
// the route-wide `app/error.jsx`, blanking the ENTIRE page rather than
// just that tab. `PreviewsSection` below is wrapped in `ResilientSection`
// because a real failure was observed reaching it via the Home tab's
// "Full H2H preview" link; the other 19 share the identical structural
// gap and are not fixed here — wrapping all of them is a separate,
// larger change than the one defect this fixes.
const sectionLoading = () => <LoadingState message="Loading section..." />;

// Section components whose code has already arrived, keyed by tab.  Filled
// only by `preloadSectionCode` (client effects, never the server), so the
// server render and hydration see an empty map and load exactly as before.
// Bounded by the fixed tab list; never invalidated because a loaded module
// does not change.
const loadedSectionCode = {};

// A thenable that is already settled and calls back SYNCHRONOUSLY.
function settledThenable(value) {
  return {
    then(onFulfilled) {
      return settledThenable(onFulfilled ? onFulfilled(value) : value);
    },
  };
}

// One lazily-loaded tab section: `dynamic(…, { ssr: false })` as before,
// with one difference in its loader.  When the tab's code has already been
// loaded (by `preloadSectionCode`) at the moment the section first renders,
// the loader answers with an already-settled thenable, so the `React.lazy`
// inside `dynamic()` resolves during that render instead of suspending.
//
// Why (Workstream H, 2026-10-27, measured locally and on production): a
// lazy boundary suspends on its first render even when the module is in
// memory (a native promise settles a tick later), and React throttles the
// reveal of a suspended boundary (~300 ms).  With the data AND the code both
// present, a tab still sat on "Loading section..." for ~340 ms.  If a later
// Next version stops calling `.then` on the loader's result this degrades to
// exactly the previous behaviour (one suspension); nothing else changes.
const lazySection = (tab) =>
  dynamic(
    () => {
      const ready = loadedSectionCode[tab];
      return ready ? settledThenable({ default: ready }) : SECTION_CODE_FOR_TAB[tab]();
    },
    { ssr: false, loading: sectionLoading },
  );

// The Brisket Trade Advisor's team step: split the same way as Overview —
// its own chunk, still SERVER-RENDERED whenever the advisor tab renders
// (it is DEFAULT_TAB while the advisor is served, so the landing paints
// the real team picker with no loading flash; Next preloads the chunk).
// With the advisor switched off the tab never renders, so /league
// references no advisor chunk at all (byte parity with main).  The
// builder, picker and result are the shell's own lazy chunks.  See
// ./sections/trade-advisor-shell.jsx.
const TradeAdvisorShell = dynamic(() => import("./sections/trade-advisor-shell.jsx"), {
  ssr: true,
  loading: sectionLoading,
});
// Each lazily-mounted tab's code loader, keyed by TAB.  The same function
// is handed to `dynamic()` below and to `preloadSectionCode`, so the
// preload and the render resolve one module (webpack de-duplicates the
// chunk request; nothing is loaded twice).
//
// Why a preload exists (Workstream H, 2026-10-27, measured on production):
// a tab whose data the shell fetches rendered its loading state until that
// fetch resolved, and only THEN mounted the section — which is when
// `dynamic()` first asked for the section's code.  Data and code were a
// serial waterfall: clicking "Records" fetched the section (~450 ms), then
// started the 6245 chunk (~135 ms), then rendered.  Starting the code
// request when the tab becomes active overlaps the two.  It changes no
// data path, no loading/error state and no deadline: the section still
// renders only when its data is present, exactly as before.
const SECTION_CODE_FOR_TAB = {
  "draft-capital": () => import("./sections/draft-capital.jsx"),
  history: () => import("./sections/history.jsx"),
  rivalries: () => import("./sections/rivalries.jsx"),
  awards: () => import("./sections/awards.jsx"),
  records: () => import("./sections/records.jsx"),
  franchise: () => import("./sections/franchise.jsx"),
  activity: () => import("./sections/activity.jsx"),
  draft: () => import("./sections/draft.jsx"),
  weekly: () => import("./sections/weekly.jsx"),
  superlatives: () => import("./sections/superlatives.jsx"),
  archives: () => import("./sections/archives.jsx"),
  luck: () => import("./sections/luck.jsx"),
  streaks: () => import("./sections/streaks.jsx"),
  [PIECE_OF_SHIT_RANKINGS_TAB]: () => import("./sections/conduct.jsx"),
  rosTeamStrength: () => import("./sections/ros-team-strength.jsx"),
  power: () => import("./sections/ros-power.jsx"),
  rosChampionship: () => import("./sections/ros-championship.jsx"),
  rosTradeDeadline: () => import("./sections/ros-trade-deadline.jsx"),
  recaps: () => import("./sections/articles.jsx"),
  previews: () => import("./sections/matchup-previews.jsx"),
  teamAssignment: () => import("./sections/team-assignment.jsx"),
};

/**
 * Start loading the active tab's section code without waiting for its
 * data, and remember the component once it lands (see `lazySection`).
 * Best effort by construction: a failed preload is swallowed here and the
 * real `dynamic()` load retries and reports through the existing error
 * path (webpack forgets a failed chunk, so it is not poisoned).  Tabs with
 * no lazily-loaded code (Overview, the advisor) are a no-op.
 */
export function preloadSectionCode(tab) {
  const load = SECTION_CODE_FOR_TAB[tab];
  if (!load) return null;
  const pending = load().then((mod) => {
    const Component = mod?.default;
    if (Component) loadedSectionCode[tab] = Component;
    return Component;
  });
  pending.catch(() => {});
  return pending;
}

const DraftCapitalSection = lazySection("draft-capital");
const HistorySection = lazySection("history");
const RivalriesSection = lazySection("rivalries");
const AwardsSection = lazySection("awards");
const RecordsSection = lazySection("records");
const FranchiseSection = lazySection("franchise");
const ActivitySection = lazySection("activity");
const DraftSection = lazySection("draft");
const WeeklySection = lazySection("weekly");
const SuperlativesSection = lazySection("superlatives");
const ArchivesSection = lazySection("archives");
const LuckSection = lazySection("luck");
const StreaksSection = lazySection("streaks");
const ConductSection = lazySection(PIECE_OF_SHIT_RANKINGS_TAB);
const RosTeamStrengthSection = lazySection("rosTeamStrength");
const RosPowerSection = lazySection("power");
const RosChampionshipSection = lazySection("rosChampionship");
const RosTradeDeadlineSection = lazySection("rosTradeDeadline");
const ArticlesSection = lazySection("recaps");
// The Previews tab composes the structured current-week head-to-head
// block with the article slate; the Recaps tab stays the bare article
// list, because a scored week is owned by the recap surfaces.
const PreviewsSection = lazySection("previews");
const TeamAssignmentSection = lazySection("teamAssignment");

// SUB_TABS / VALID_TABS / DEFAULT_TAB / normalizeTabKey / SECTION_FOR_TAB
// now live in ./tabs.js so ./page.jsx (a server component) can read the
// same tab→section map when deciding which sections to server-render.
// A "use client" module's plain exports are client references and
// cannot be called on the server, so the map could not stay here.

// A full document's first League mount shares the navigation clock, including
// SSR. Subsequent SPA mounts get a new intent clock. Commit this marker only
// in an effect so abandoned renders and StrictMode replay cannot consume it.
let committedDocumentOrigin = null;
const RESOLVED_DEADLINE_MS = 5000;
function initialIntent(tab) {
  const navigation = typeof window !== "undefined"
    ? performance.getEntriesByType?.("navigation")?.[0]
    : null;
  const documentLeague = navigation && new URL(navigation.name).pathname === "/league";
  const initialDocument = documentLeague && committedDocumentOrigin !== performance.timeOrigin;
  return {
    tab,
    deadline: (initialDocument ? 0 : performance.now()) + RESOLVED_DEADLINE_MS,
    documentOrigin: initialDocument ? performance.timeOrigin : null,
  };
}

export default function LeagueClient({ initialContract = null, initialTab = null, initialAdvisor = null }) {
  return (
    <Suspense fallback={<LoadingState message="Loading league data..." />}>
      <LeaguePage initialContract={initialContract} initialTab={initialTab} initialAdvisor={initialAdvisor} />
    </Suspense>
  );
}

function LeaguePage({ initialContract = null, initialTab = null, initialAdvisor = null }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Apply the tab-key alias on read so legacy ``?tab=matchupPreview``
  // and ``?tab=weeklyRecap`` URLs land on the new Previews/Recaps
  // tabs instead of falling through to the default.
  const rawUrlTab = searchParams.get("tab");
  const urlTab = normalizeTabKey(rawUrlTab);
  const urlOwner = searchParams.get("owner") || "";
  const urlWeek = searchParams.get("week") || "";
  // Draft Capital year selector — the URL is the source of truth, so the
  // selection survives reload, back/forward and direct links.  Validation
  // against the seasons the payload carries happens in the section.
  const urlYear = searchParams.get(DRAFT_CAPITAL_YEAR_PARAM) || "";
  const normalizedInitialTab = normalizeTabKey(initialTab);

  // Is the Brisket Trade Advisor served?  The server read the advisor's
  // teams endpoint, and ONLY a confirmed "ready" offers the advisor (R2-9):
  // "disabled" (flag off → 503 advisor_unavailable/disabled, or 404),
  // "unknown" (no answer, or 503 not_ready while the launch gate is closed)
  // and a missing bootstrap all mean the hub behaves exactly as before the
  // advisor — Overview lands, no advisor tab.  An off flag, a closed launch
  // gate or a backend outage must never turn unfinished functionality into
  // the public landing tab.  Same rule as the landing page and the sitemap
  // (./advisor-bootstrap.js `advisorConfirmedServed`).  While served, a
  // later "disabled" answer from the browser still withdraws the tab
  // (`markAdvisorUnavailable`).
  const [advisorAvailable, setAdvisorAvailable] = useState(initialAdvisor?.state === "ready");
  const markAdvisorUnavailable = useCallback(() => setAdvisorAvailable(false), []);

  // The tab the visitor asked for (URL, or the server's view of it on the
  // first render); `resolveTab` turns it into the tab actually shown.
  const [requestedTab, setRequestedTab] = useState(urlTab || normalizedInitialTab || null);
  const activeTab = resolveTab(requestedTab, { advisorAvailable });
  const [initialRequestIntent] = useState(() => initialIntent(activeTab));
  const intentRef = useRef(initialRequestIntent);
  useEffect(() => {
    if (initialRequestIntent.documentOrigin !== null) {
      committedDocumentOrigin = initialRequestIntent.documentOrigin;
    }
  }, [initialRequestIntent]);
  useEffect(() => {
    if (intentRef.current.tab !== activeTab) {
      intentRef.current = { tab: activeTab, deadline: performance.now() + RESOLVED_DEADLINE_MS };
    }
  }, [activeTab]);
  const [state, setState] = useState(
    initialContract
      ? { loading: false, error: "", contract: initialContract }
      : { loading: true, error: "", contract: null },
  );

  // URL → tab.
  //
  // Advisor served: tab clicks PUSH history entries, so Back / Forward
  // change `?tab=` (including to no tab at all, which is the default
  // landing); every change of the URL's tab — never a re-render with the
  // same one — re-resolves the requested tab.
  //
  // Advisor NOT served: main's rule, verbatim — a valid `?tab=` that
  // differs from the shown tab is adopted; no `?tab=` changes nothing.
  const prevRawUrlTabRef = useRef(rawUrlTab);
  useEffect(() => {
    if (!advisorAvailable) {
      prevRawUrlTabRef.current = rawUrlTab;
      if (urlTab && resolveTab(urlTab, { advisorAvailable }) === urlTab && urlTab !== activeTab) {
        setRequestedTab(urlTab);
      }
      return;
    }
    if (prevRawUrlTabRef.current === rawUrlTab) return;
    prevRawUrlTabRef.current = rawUrlTab;
    setRequestedTab(urlTab || null);
  }, [advisorAvailable, rawUrlTab, urlTab, activeTab]);

  useEffect(() => {
    // Keep old shared links working, then replace the legacy query value
    // with the canonical slug so copied URLs always use the current name.
    if (!rawUrlTab || rawUrlTab === urlTab || !VALID_TABS.has(urlTab)) return;
    router.replace(leagueTabHref(urlTab, searchParams.toString(), {}, { advisorAvailable }), {
      scroll: false,
    });
  }, [advisorAvailable, rawUrlTab, router, searchParams, urlTab]);

  // `mode`: "push" for navigation between tabs (a real history entry, so
  // Back returns to the previous tab), "replace" for a section's own
  // selectors (owner / week / year) so changing a filter never stacks
  // history entries.  With the advisor NOT served every write is a
  // replace, exactly as on main before the advisor: an off flag adds no
  // history entries.
  const setActiveTab = useCallback((key, extraParams = {}, mode = "push") => {
    // Normalize on write so internal CTAs that still pass legacy
    // keys (overview.jsx → onNavigate("matchupPreview")) route to
    // the renamed tabs instead of into a blank-content state.
    const normalized = normalizeTabKey(key);
    if (intentRef.current.tab !== normalized) {
      intentRef.current = { tab: normalized, deadline: performance.now() + RESOLVED_DEADLINE_MS };
    }
    setRequestedTab(normalized);
    // `?year=` belongs to the Draft Capital tab only; leaving it drops it.
    const params =
      normalized === "draft-capital"
        ? extraParams
        : { [DRAFT_CAPITAL_YEAR_PARAM]: null, ...extraParams };
    const href = leagueTabHref(normalized, searchParams.toString(), params, { advisorAvailable });
    // The ref tracks what WE wrote, so the URL→tab effect does not echo it.
    prevRawUrlTabRef.current = new URLSearchParams(href.split("?")[1] || "").get("tab");
    if (mode === "replace" || !advisorAvailable) router.replace(href, { scroll: false });
    else router.push(href, { scroll: false });
  }, [advisorAvailable, router, searchParams]);

  // `?year=` for the Draft Capital tab; null (All Years) removes the param.
  const setDraftCapitalYear = useCallback(
    (year) =>
      setActiveTab(
        "draft-capital",
        { [DRAFT_CAPITAL_YEAR_PARAM]: serializeDraftCapitalYear(year) },
        "replace",
      ),
    [setActiveTab],
  );
  const openOverview = useCallback(() => setActiveTab(OVERVIEW_TAB), [setActiveTab]);

  useEffect(() => {
    // Server-rendered page already handed us the contract — skip.
    if (initialContract) return undefined;
    let active = true;
    const controller = new AbortController();
    (async () => {
      try {
        // The OVERVIEW section, not the aggregate contract.  Every
        // section response carries the ``league`` block, so one 15 KB
        // request bootstraps the header, the manager lookup and the
        // landing tab — where the aggregate was 2.01 MB.  This is the
        // SSR-failed fallback path; the tab effect below fills in
        // whatever else the visitor opens.
        const payload = await fetchPublicSection("overview", { deadline: initialRequestIntent.deadline, signal: controller.signal });
        if (!active) return;
        if (!payload || typeof payload !== "object" || !payload.league) {
          setState({
            loading: false,
            error: "Public contract missing required shape.",
            contract: null,
          });
          return;
        }
        setState({
          loading: false,
          error: "",
          contract: {
            contractVersion: payload.contractVersion,
            league: payload.league,
            sections: { overview: payload.data },
          },
        });
      } catch (err) {
        if (!active) return;
        setState({
          loading: false,
          error: err?.message || "Failed to load public league data",
          contract: null,
        });
      }
    })();
    return () => {
      active = false;
      controller.abort();
    };
  }, [initialContract, initialRequestIntent]);

  const { loading, error, contract } = state;
  const sections = contract?.sections || {};
  const league = contract?.league || null;

  // Which section the active tab needs, or null when the tab fetches
  // its own data (articles, Power, the other ROS tabs, draft-capital).
  const neededSection = SECTION_FOR_TAB[activeTab] || null;
  const haveSection = !neededSection || sections[neededSection] !== undefined;

  // Lazily pull the section the visitor just opened.  ``inflightRef``
  // (not state) guards against a double-fetch across the re-render that
  // marking it pending would itself cause.
  const [sectionErrors, setSectionErrors] = useState({});
  const sectionError = sectionErrors[neededSection] || "";
  const inflightRef = useRef({});
  const mountedRef = useRef(false);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // StrictMode immediately replays setup. Only a real unmount retires the
      // shell-owned requests; tab changes still populate their section cache.
      queueMicrotask(() => {
        if (!mountedRef.current) {
          for (const controller of Object.values(inflightRef.current)) controller.abort();
        }
      });
    };
  }, []);
  // Ask for the active tab's CODE as soon as the tab is active, in
  // parallel with the data fetch below (see SECTION_CODE_FOR_TAB).
  useEffect(() => {
    preloadSectionCode(activeTab);
  }, [activeTab]);
  useEffect(() => {
    if (!contract) return undefined;
    if (!neededSection || haveSection) return undefined;
    if (inflightRef.current[neededSection]) return undefined;
    const controller = new AbortController();
    inflightRef.current[neededSection] = controller;
    setSectionErrors((previous) => ({ ...previous, [neededSection]: "" }));
    (async () => {
      try {
        const payload = await fetchPublicSection(neededSection, { deadline: intentRef.current.deadline, signal: controller.signal });
        // The shell owns its section cache, not whichever tab was active
        // when this request began. Switching tabs must not discard it.
        if (!mountedRef.current) return;
        if (!payload || typeof payload !== "object") {
          throw new Error(`Empty payload for section ${neededSection}`);
        }
        setSectionErrors((previous) => ({ ...previous, [neededSection]: "" }));
        // Merge, never replace: other sections already fetched stay.
        setState((prev) =>
          prev.contract
            ? {
                ...prev,
                contract: {
                  ...prev.contract,
                  sections: {
                    ...prev.contract.sections,
                    [neededSection]: payload.data,
                  },
                },
              }
            : prev,
        );
      } catch (err) {
        if (!mountedRef.current) return;
        setSectionErrors((previous) => ({ ...previous, [neededSection]: err?.message || `Failed to load ${neededSection}` }));
      } finally {
        delete inflightRef.current[neededSection];
      }
    })();
    return undefined;
  }, [contract, neededSection, haveSection]);

  const managers = useMemo(() => buildManagerLookup(league), [league]);

  // The public-league contract's loading / failure / empty states.
  //
  // Advisor NOT served: returned as the WHOLE page — main's three early
  // returns, same elements — so a missing contract blanks the hub exactly
  // as it did before the advisor.  (No hook runs below this point.)
  //
  // Advisor served: the advisor does not read that contract, so the
  // failure is an in-panel state for the tabs that do, and the landing
  // advisor keeps working.
  const contractGate = loading ? (
    <LoadingState message="Loading league data..." />
  ) : error ? (
    <div className="card">
      <EmptyState title="League data unavailable" message={error} />
    </div>
  ) : !league ? (
    <div className="card">
      <EmptyState title="No public league data" message="Public contract empty." />
    </div>
  ) : null;
  if (!advisorAvailable && contractGate) return contractGate;

  const advisorTab = activeTab === TRADE_ADVISOR_TAB;
  const tabs = visibleTabs({ advisorAvailable });
  const overview = sections.overview || {};
  const seasonLabel =
    overview.seasonRangeLabel ||
    (league?.seasonsCovered || []).join(", ") ||
    "—";

  return (
    <section>
      {advisorTab ? (
        <PageHeader
          eyebrow={league?.leagueName || "Chase Upside League"}
          title={TRADE_ADVISOR_TITLE}
          description={TRADE_ADVISOR_SUBTITLE}
        />
      ) : (
        <PageHeader
          eyebrow="Chase Upside League"
          title={league?.leagueName || "League"}
          description={
            league
              ? `Seasons: ${seasonLabel}` +
                ` · ${(league.managers || []).length} managers` +
                ` · Last ${(league.seasonsCovered || []).length || 2} dynasty season${(league.seasonsCovered || []).length === 1 ? "" : "s"}`
              : undefined
          }
        />
      )}
      <div className={leagueNavStyles.nav}>
        {/* Mobile: a dropdown selector so all 20 sections stay reachable
            without needing a horizontally-scrolled tab row. */}
        <div className={`mobile-only ${leagueNavStyles.mobileNav}`}>
          <label className={leagueNavStyles.mobileNavLabel} htmlFor="league-section-select">
            Section
          </label>
          <Select
            id="league-section-select"
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            aria-label="Select league section"
            options={tabs.map((t) => ({ value: t.key, label: t.label }))}
          />
        </div>
        <div className="desktop-only">
          <Tabs
            idPrefix="league"
            label="League sections"
            tabs={tabs.map((t) => ({ id: t.key, label: t.label }))}
            active={activeTab}
            onChange={(key) => setActiveTab(key)}
          />
        </div>
      </div>

      <div
        role="tabpanel"
        id={tabPanelId("league", activeTab)}
        aria-labelledby={tabId("league", activeTab)}
      >
      {/* The tab's section is fetched on open (see the effect above), so
          a tab the server did not pre-render shows its own loading /
          error state under the header and nav rather than blanking the
          page.  Tabs that fetch their own data have no section and skip
          this entirely. */}
      {advisorTab ? (
        <ResilientSection name="Trade Advisor">
          <TradeAdvisorShell
            bootstrap={initialAdvisor}
            onUnavailable={markAdvisorUnavailable}
            onOpenOverview={openOverview}
          />
        </ResilientSection>
      ) : contractGate ? (
        contractGate
      ) : !haveSection ? (
        sectionError ? (
          <div className="card">
            <EmptyState title="Section unavailable" message={sectionError} />
          </div>
        ) : (
          <LoadingState message="Loading section..." />
        )
      ) : (
        <>
      {activeTab === "draft-capital" && (
        <DraftCapitalSection
          yearParam={urlYear}
          setYear={setDraftCapitalYear}
        />
      )}
      {activeTab === "overview" && (
        <OverviewSection managers={managers} data={overview} onNavigate={setActiveTab} />
      )}
      {activeTab === "history" && (
        <HistorySection managers={managers} data={sections.history} onNavigate={setActiveTab} />
      )}
      {activeTab === "rivalries" && (
        <RivalriesSection managers={managers} data={sections.rivalries} onNavigate={setActiveTab} />
      )}
      {activeTab === "awards" && (
        <AwardsSection managers={managers} data={sections.awards} onNavigate={setActiveTab} />
      )}
      {activeTab === "records" && <RecordsSection data={sections.records} />}
      {activeTab === "franchise" && (
        <FranchiseSection
          managers={managers}
          data={sections.franchise}
          onNavigate={setActiveTab}
          initialOwner={urlOwner}
          setOwner={(owner) => setActiveTab("franchise", { owner }, "replace")}
        />
      )}
      {activeTab === "activity" && (
        <ActivitySection
          managers={managers}
          data={sections.activity}
          onNavigate={setActiveTab}
        />
      )}
      {activeTab === "draft" && (
        <DraftSection
          data={sections.draft}
          initialOwner={urlOwner}
          setOwner={(owner) => setActiveTab("draft", { owner }, "replace")}
        />
      )}
      {activeTab === "weekly" && (
        <WeeklySection
          data={sections.weekly}
          managers={managers}
          onNavigate={setActiveTab}
          initialWeek={urlWeek}
          setWeek={(week) => setActiveTab("weekly", { week }, "replace")}
        />
      )}
      {activeTab === "superlatives" && (
        <SuperlativesSection managers={managers} data={sections.superlatives} />
      )}
      {activeTab === "archives" && <ArchivesSection data={sections.archives} />}
      {activeTab === "luck" && (
        <LuckSection data={sections.luck} managers={managers} />
      )}
      {activeTab === "streaks" && (
        <StreaksSection data={sections.streaks} managers={managers} />
      )}
      {activeTab === PIECE_OF_SHIT_RANKINGS_TAB && (
        <ConductSection data={sections.conduct} managers={managers} />
      )}
      {activeTab === "power" && <RosPowerSection managers={managers} />}
      {activeTab === "rosTeamStrength" && <RosTeamStrengthSection />}
      {activeTab === "rosChampionship" && <RosChampionshipSection />}
      {activeTab === "rosTradeDeadline" && <RosTradeDeadlineSection />}
      {activeTab === "previews" && (
        <ResilientSection name="Previews">
          <PreviewsSection />
        </ResilientSection>
      )}
      {activeTab === "recaps" && <ArticlesSection mode="recap" />}
      {activeTab === "teamAssignment" && (
        <TeamAssignmentSection managers={managers} />
      )}
        </>
      )}
      </div>
    </section>
  );
}

// Expose available section keys for external consumers / tests.
export const LEAGUE_PAGE_SECTIONS = PUBLIC_SECTION_KEYS;
