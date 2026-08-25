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
import { SubNav, PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { PUBLIC_SECTION_KEYS, fetchPublicSection } from "@/lib/public-league-data";
import { buildManagerLookup } from "./shared.jsx";
import {
  DEFAULT_TAB,
  PIECE_OF_SHIT_RANKINGS_TAB,
  SECTION_FOR_TAB,
  SUB_TABS,
  VALID_TABS,
  leagueTabHref,
  normalizeTabKey,
} from "./tabs.js";

import OverviewSection from "./sections/overview.jsx";

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
// OverviewSection is deliberately NOT split — it is DEFAULT_TAB, so
// splitting it would trade a bundle win for a loading flash on the
// landing view that every visitor sees.
//
// Pattern (dynamic + `_`-prefixed siblings) matches
// ./sections/draft-capital.jsx, which already splits its own two heavy
// panels this way.
const sectionLoading = () => <LoadingState message="Loading section..." />;
const lazySection = (loader) =>
  dynamic(loader, { ssr: false, loading: sectionLoading });

const DraftCapitalSection = lazySection(() => import("./sections/draft-capital.jsx"));
const HistorySection = lazySection(() => import("./sections/history.jsx"));
const RivalriesSection = lazySection(() => import("./sections/rivalries.jsx"));
const AwardsSection = lazySection(() => import("./sections/awards.jsx"));
const RecordsSection = lazySection(() => import("./sections/records.jsx"));
const FranchiseSection = lazySection(() => import("./sections/franchise.jsx"));
const ActivitySection = lazySection(() => import("./sections/activity.jsx"));
const DraftSection = lazySection(() => import("./sections/draft.jsx"));
const WeeklySection = lazySection(() => import("./sections/weekly.jsx"));
const SuperlativesSection = lazySection(() => import("./sections/superlatives.jsx"));
const ArchivesSection = lazySection(() => import("./sections/archives.jsx"));
const LuckSection = lazySection(() => import("./sections/luck.jsx"));
const StreaksSection = lazySection(() => import("./sections/streaks.jsx"));
const ConductSection = lazySection(() => import("./sections/conduct.jsx"));
const RosTeamStrengthSection = lazySection(() => import("./sections/ros-team-strength.jsx"));
const RosPowerSection = lazySection(() => import("./sections/ros-power.jsx"));
const RosChampionshipSection = lazySection(() => import("./sections/ros-championship.jsx"));
const RosTradeDeadlineSection = lazySection(() => import("./sections/ros-trade-deadline.jsx"));
const ArticlesSection = lazySection(() => import("./sections/articles.jsx"));
const TeamAssignmentSection = lazySection(() => import("./sections/team-assignment.jsx"));

// SUB_TABS / VALID_TABS / DEFAULT_TAB / normalizeTabKey / SECTION_FOR_TAB
// now live in ./tabs.js so ./page.jsx (a server component) can read the
// same tab→section map when deciding which sections to server-render.
// A "use client" module's plain exports are client references and
// cannot be called on the server, so the map could not stay here.

export default function LeagueClient({ initialContract = null, initialTab = DEFAULT_TAB }) {
  return (
    <Suspense fallback={<LoadingState message="Loading league data..." />}>
      <LeaguePage initialContract={initialContract} initialTab={initialTab} />
    </Suspense>
  );
}

function LeaguePage({ initialContract = null, initialTab = DEFAULT_TAB }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Apply the tab-key alias on read so legacy ``?tab=matchupPreview``
  // and ``?tab=weeklyRecap`` URLs land on the new Previews/Recaps
  // tabs instead of falling through to the default.
  const rawUrlTab = searchParams.get("tab");
  const urlTab = normalizeTabKey(rawUrlTab);
  const urlOwner = searchParams.get("owner") || "";
  const urlWeek = searchParams.get("week") || "";
  const normalizedInitialTab = normalizeTabKey(initialTab);

  const [activeTab, setActiveTabState] = useState(
    urlTab && VALID_TABS.has(urlTab)
      ? urlTab
      : (normalizedInitialTab && VALID_TABS.has(normalizedInitialTab)
          ? normalizedInitialTab
          : DEFAULT_TAB),
  );
  const [state, setState] = useState(
    initialContract
      ? { loading: false, error: "", contract: initialContract }
      : { loading: true, error: "", contract: null },
  );

  useEffect(() => {
    if (urlTab && VALID_TABS.has(urlTab) && urlTab !== activeTab) {
      setActiveTabState(urlTab);
    }
  }, [urlTab, activeTab]);

  useEffect(() => {
    // Keep old shared links working, then replace the legacy query value
    // with the canonical slug so copied URLs always use the current name.
    if (!rawUrlTab || rawUrlTab === urlTab || !VALID_TABS.has(urlTab)) return;
    router.replace(leagueTabHref(urlTab, searchParams.toString()), { scroll: false });
  }, [rawUrlTab, router, searchParams, urlTab]);

  const setActiveTab = useCallback((key, extraParams = {}) => {
    // Normalize on write so internal CTAs that still pass legacy
    // keys (overview.jsx → onNavigate("matchupPreview")) route to
    // the renamed tabs instead of into a blank-content state.
    const normalized = normalizeTabKey(key);
    setActiveTabState(normalized);
    router.replace(
      leagueTabHref(normalized, searchParams.toString(), extraParams),
      { scroll: false },
    );
  }, [router, searchParams]);

  useEffect(() => {
    // Server-rendered page already handed us the contract — skip.
    if (initialContract) return undefined;
    let active = true;
    (async () => {
      try {
        // The OVERVIEW section, not the aggregate contract.  Every
        // section response carries the ``league`` block, so one 15 KB
        // request bootstraps the header, the manager lookup and the
        // landing tab — where the aggregate was 2.01 MB.  This is the
        // SSR-failed fallback path; the tab effect below fills in
        // whatever else the visitor opens.
        const payload = await fetchPublicSection("overview");
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
    };
  }, [initialContract]);

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
  const [sectionError, setSectionError] = useState("");
  const inflightRef = useRef({});
  useEffect(() => {
    if (!contract) return undefined;
    if (!neededSection || haveSection) return undefined;
    if (inflightRef.current[neededSection]) return undefined;
    inflightRef.current[neededSection] = true;
    let active = true;
    (async () => {
      try {
        const payload = await fetchPublicSection(neededSection);
        if (!active) return;
        if (!payload || typeof payload !== "object") {
          throw new Error(`Empty payload for section ${neededSection}`);
        }
        setSectionError("");
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
        if (!active) return;
        setSectionError(err?.message || `Failed to load ${neededSection}`);
      } finally {
        delete inflightRef.current[neededSection];
      }
    })();
    return () => {
      active = false;
    };
  }, [contract, neededSection, haveSection]);

  const managers = useMemo(() => buildManagerLookup(league), [league]);

  if (loading) return <LoadingState message="Loading league data..." />;
  if (error) {
    return (
      <div className="card">
        <EmptyState title="League data unavailable" message={error} />
      </div>
    );
  }
  if (!league) {
    return (
      <div className="card">
        <EmptyState title="No public league data" message="Public contract empty." />
      </div>
    );
  }

  const overview = sections.overview || {};
  const seasonLabel =
    overview.seasonRangeLabel ||
    (league.seasonsCovered || []).join(", ") ||
    "—";

  return (
    <section>
      <div className="card">
        <PageHeader
          title={league.leagueName || "League"}
          subtitle={
            `Seasons: ${seasonLabel}` +
            ` · ${(league.managers || []).length} managers` +
            ` · Last ${(league.seasonsCovered || []).length || 2} dynasty season${(league.seasonsCovered || []).length === 1 ? "" : "s"}`
          }
        />
        {/* Mobile: a dropdown selector so all 12 sections stay reachable
            without needing a horizontally-scrolled tab row. */}
        <div className="mobile-only" style={{ marginBottom: "var(--space-sm)" }}>
          <label
            style={{
              display: "block",
              fontSize: "0.66rem",
              color: "var(--subtext)",
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              marginBottom: 4,
            }}
          >
            Section
          </label>
          <select
            className="input"
            value={activeTab}
            onChange={(e) => setActiveTab(e.target.value)}
            aria-label="Select league section"
            style={{ width: "100%" }}
          >
            {SUB_TABS.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
        <div className="desktop-only">
          <SubNav items={SUB_TABS} active={activeTab} onChange={(key) => setActiveTab(key)} />
        </div>
      </div>

      {/* The tab's section is fetched on open (see the effect above), so
          a tab the server did not pre-render shows its own loading /
          error state under the header and nav rather than blanking the
          page.  Tabs that fetch their own data have no section and skip
          this entirely. */}
      {!haveSection ? (
        sectionError ? (
          <div className="card">
            <EmptyState title="Section unavailable" message={sectionError} />
          </div>
        ) : (
          <LoadingState message="Loading section..." />
        )
      ) : (
        <>
      {activeTab === "draft-capital" && <DraftCapitalSection />}
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
          setOwner={(owner) => setActiveTab("franchise", { owner })}
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
          setOwner={(owner) => setActiveTab("draft", { owner })}
        />
      )}
      {activeTab === "weekly" && (
        <WeeklySection
          data={sections.weekly}
          managers={managers}
          onNavigate={setActiveTab}
          initialWeek={urlWeek}
          setWeek={(week) => setActiveTab("weekly", { week })}
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
      {activeTab === "previews" && <ArticlesSection mode="preview" />}
      {activeTab === "recaps" && <ArticlesSection mode="recap" />}
      {activeTab === "teamAssignment" && (
        <TeamAssignmentSection
          data={sections.teamAssignment}
          managers={managers}
        />
      )}
        </>
      )}
    </section>
  );
}

// Expose available section keys for external consumers / tests.
export const LEAGUE_PAGE_SECTIONS = PUBLIC_SECTION_KEYS;
