"use client";

// PUBLIC /league client shell (tabbed container).
//
// Wrapped by ./page.jsx — which is a server component that pre-fetches
// the public contract so the first paint already has real data (no
// "Loading league data..." flash).  We accept an ``initialContract``
// prop and skip the client fetch if it's provided.
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
// via fetchPublicLeague() as client fallback.
//
// Section renderers live under ./sections/<name>.jsx so Next.js can
// code-split each tab.  Shared primitives (Avatar, Card, Stat, format
// helpers) live in shared.jsx and are imported by both tabbed and
// dedicated routes.

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SubNav, PageHeader, LoadingState, EmptyState } from "@/components/ui";
import {
  PUBLIC_SECTION_KEYS,
  fetchPublicLeague,
} from "@/lib/public-league-data";
import { buildManagerLookup } from "./shared.jsx";

import DraftCapitalSection from "./sections/draft-capital.jsx";
import OverviewSection from "./sections/overview.jsx";
import HistorySection from "./sections/history.jsx";
import RivalriesSection from "./sections/rivalries.jsx";
import AwardsSection from "./sections/awards.jsx";
import RecordsSection from "./sections/records.jsx";
import FranchiseSection from "./sections/franchise.jsx";
import ActivitySection from "./sections/activity.jsx";
import DraftSection from "./sections/draft.jsx";
import WeeklySection from "./sections/weekly.jsx";
import SuperlativesSection from "./sections/superlatives.jsx";
import ArchivesSection from "./sections/archives.jsx";
import LuckSection from "./sections/luck.jsx";
import StreaksSection from "./sections/streaks.jsx";
import PowerSection from "./sections/power.jsx";
import RosTeamStrengthSection from "./sections/ros-team-strength.jsx";
import MatchupPreviewSection from "./sections/matchup-preview.jsx";
import WeeklyRecapSection from "./sections/weekly-recap.jsx";

// Tab order + labels for the /league section nav.
// "Draft Capital" is first so it's the default landing on mobile,
// which is what public (unauth) visitors most commonly arrive to see.
const SUB_TABS = [
  { key: "draft-capital", label: "Draft Capital" },
  { key: "overview", label: "Home" },
  { key: "matchupPreview", label: "This Week" },
  { key: "power", label: "Power" },
  { key: "rosTeamStrength", label: "ROS Strength" },
  { key: "luck", label: "Luck" },
  { key: "streaks", label: "Streaks" },
  { key: "weeklyRecap", label: "Recaps" },
  { key: "history", label: "History" },
  { key: "rivalries", label: "Rivalries" },
  { key: "awards", label: "Awards" },
  { key: "records", label: "Records" },
  { key: "franchise", label: "Franchises" },
  { key: "activity", label: "Trades" },
  { key: "draft", label: "Draft" },
  { key: "weekly", label: "Weekly" },
  { key: "superlatives", label: "Superlatives" },
  { key: "archives", label: "Archives" },
];

const VALID_TABS = new Set(SUB_TABS.map((t) => t.key));
const DEFAULT_TAB = "draft-capital";

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
  const urlTab = searchParams.get("tab");
  const urlOwner = searchParams.get("owner") || "";
  const urlWeek = searchParams.get("week") || "";

  const [activeTab, setActiveTabState] = useState(
    urlTab && VALID_TABS.has(urlTab)
      ? urlTab
      : (initialTab && VALID_TABS.has(initialTab) ? initialTab : DEFAULT_TAB),
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

  const setActiveTab = useCallback((key, extraParams = {}) => {
    setActiveTabState(key);
    const params = new URLSearchParams(searchParams.toString());
    // Omit ``?tab=`` from the URL when on the default tab for a
    // cleaner shareable link.
    if (key === DEFAULT_TAB) {
      params.delete("tab");
    } else {
      params.set("tab", key);
    }
    for (const [k, v] of Object.entries(extraParams)) {
      if (v === null || v === undefined || v === "") {
        params.delete(k);
      } else {
        params.set(k, String(v));
      }
    }
    const qs = params.toString();
    router.replace(qs ? `/league?${qs}` : "/league", { scroll: false });
  }, [router, searchParams]);

  useEffect(() => {
    // Server-rendered page already handed us the contract — skip.
    if (initialContract) return undefined;
    let active = true;
    (async () => {
      try {
        const contract = await fetchPublicLeague();
        if (!active) return;
        if (
          !contract ||
          typeof contract !== "object" ||
          !contract.sections ||
          !contract.league
        ) {
          setState({
            loading: false,
            error: "Public contract missing required shape.",
            contract: null,
          });
          return;
        }
        setState({ loading: false, error: "", contract });
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
      {activeTab === "power" && (
        <PowerSection data={sections.power} managers={managers} />
      )}
      {activeTab === "rosTeamStrength" && <RosTeamStrengthSection />}
      {activeTab === "matchupPreview" && (
        <MatchupPreviewSection
          data={sections.matchupPreview}
          managers={managers}
          onNavigate={setActiveTab}
        />
      )}
      {activeTab === "weeklyRecap" && (
        <WeeklyRecapSection
          data={sections.weeklyRecap}
          managers={managers}
        />
      )}
    </section>
  );
}

// Expose available section keys for external consumers / tests.
export const LEAGUE_PAGE_SECTIONS = PUBLIC_SECTION_KEYS;
