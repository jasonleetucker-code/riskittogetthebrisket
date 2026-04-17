"use client";

// PUBLIC /league page.
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
// Data source: /api/public/league → fetchPublicLeague().

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  SubNav,
  PageHeader,
  LoadingState,
  EmptyState,
} from "@/components/ui";
import {
  PUBLIC_SECTION_KEYS,
  fetchPublicLeague,
} from "@/lib/public-league-data";

const SUB_TABS = [
  { key: "overview", label: "Home" },
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

// Next.js requires useSearchParams to be used inside a Suspense boundary
// at the component level to keep pre-render aware.
export default function LeaguePageRoute() {
  return (
    <Suspense fallback={<LoadingState message="Loading league data..." />}>
      <LeaguePage />
    </Suspense>
  );
}

function LeaguePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlTab = searchParams.get("tab");
  const urlOwner = searchParams.get("owner") || "";
  const urlWeek = searchParams.get("week") || "";

  const [activeTab, setActiveTabState] = useState(
    urlTab && VALID_TABS.has(urlTab) ? urlTab : "overview",
  );
  const [state, setState] = useState({ loading: true, error: "", contract: null });

  // Keep tab in sync with ?tab= on back/forward navigation.
  useEffect(() => {
    if (urlTab && VALID_TABS.has(urlTab) && urlTab !== activeTab) {
      setActiveTabState(urlTab);
    }
  }, [urlTab, activeTab]);

  const setActiveTab = useCallback((key, extraParams = {}) => {
    setActiveTabState(key);
    const params = new URLSearchParams(searchParams.toString());
    if (key === "overview") {
      params.delete("tab");
    } else {
      params.set("tab", key);
    }
    // Apply/clear extra params (owner, week).
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
  }, []);

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
  const seasonLabel = overview.seasonRangeLabel
    || (league.seasonsCovered || []).join(", ")
    || "—";

  return (
    <section>
      <div className="card">
        <PageHeader
          title={league.leagueName || "League"}
          subtitle={
            `Seasons: ${seasonLabel}` +
            ` · ${(league.managers || []).length} managers` +
            ` · Last 2 dynasty seasons`
          }
        />
        <SubNav items={SUB_TABS} active={activeTab} onChange={(key) => setActiveTab(key)} />
      </div>

      {activeTab === "overview" && (
        <OverviewSection
          managers={managers}
          data={overview}
          onNavigate={setActiveTab}
        />
      )}
      {activeTab === "history" && <HistorySection managers={managers} data={sections.history} onNavigate={setActiveTab} />}
      {activeTab === "rivalries" && <RivalriesSection managers={managers} data={sections.rivalries} onNavigate={setActiveTab} />}
      {activeTab === "awards" && <AwardsSection managers={managers} data={sections.awards} onNavigate={setActiveTab} />}
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
      {activeTab === "activity" && <ActivitySection managers={managers} data={sections.activity} onNavigate={setActiveTab} />}
      {activeTab === "draft" && <DraftSection data={sections.draft} initialOwner={urlOwner} setOwner={(owner) => setActiveTab("draft", { owner })} />}
      {activeTab === "weekly" && (
        <WeeklySection
          data={sections.weekly}
          managers={managers}
          onNavigate={setActiveTab}
          initialWeek={urlWeek}
          setWeek={(week) => setActiveTab("weekly", { week })}
        />
      )}
      {activeTab === "superlatives" && <SuperlativesSection managers={managers} data={sections.superlatives} />}
      {activeTab === "archives" && <ArchivesSection data={sections.archives} />}
    </section>
  );
}

// ── Helpers ──────────────────────────────────────────────────────────────
function buildManagerLookup(league) {
  const map = new Map();
  for (const m of league?.managers || []) {
    map.set(String(m.ownerId), m);
  }
  return map;
}

function nameFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  return mgr?.displayName || mgr?.currentTeamName || ownerId || "Unknown";
}

function avatarUrlFor(managers, ownerId) {
  const mgr = managers.get(String(ownerId));
  if (!mgr || !mgr.avatar) return "";
  // Sleeper avatars are keyed by a 32-char hash served from their CDN.
  // If Sleeper ever surfaces a full URL we pass it through untouched.
  const avatar = String(mgr.avatar);
  if (avatar.startsWith("http")) return avatar;
  if (!avatar) return "";
  return `https://sleepercdn.com/avatars/thumbs/${avatar}`;
}

function fmtNumber(n, digits = 0) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtPoints(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return Number(n).toFixed(1);
}

function fmtPercent(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  return `${Math.round(Number(n) * 100)}%`;
}

function Avatar({ managers, ownerId, size = 24, title }) {
  const url = avatarUrlFor(managers, ownerId);
  const name = nameFor(managers, ownerId);
  const initials = name.split(/\s+/).map((w) => w[0] || "").join("").slice(0, 2).toUpperCase();
  const style = {
    width: size,
    height: size,
    borderRadius: "50%",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    background: "var(--bg-soft)",
    border: "1px solid var(--border)",
    fontSize: Math.max(10, Math.floor(size * 0.42)),
    fontWeight: 700,
    overflow: "hidden",
    flexShrink: 0,
    verticalAlign: "middle",
  };
  if (url) {
    return (
      <img
        src={url}
        alt=""
        loading="lazy"
        width={size}
        height={size}
        style={{ ...style, background: "transparent" }}
        title={title || name}
      />
    );
  }
  return (
    <span style={style} title={title || name} aria-hidden>
      {initials || "?"}
    </span>
  );
}

function ManagerInline({ managers, ownerId, onClick, compact = false }) {
  const name = nameFor(managers, ownerId);
  return (
    <span
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: onClick ? "pointer" : "default",
        color: onClick ? "var(--cyan)" : "inherit",
      }}
    >
      <Avatar managers={managers} ownerId={ownerId} size={compact ? 18 : 22} />
      <span>{name}</span>
    </span>
  );
}

function Card({ title, subtitle, action, children, id }) {
  return (
    <div className="card" id={id} style={{ marginTop: "var(--space-md)" }}>
      {(title || action) && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            marginBottom: 10,
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <div>
            {title && <div style={{ fontWeight: 700 }}>{title}</div>}
            {subtitle && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
                {subtitle}
              </div>
            )}
          </div>
          {action}
        </div>
      )}
      <div>{children}</div>
    </div>
  );
}

function Stat({ label, value, sub }) {
  return (
    <div
      style={{
        padding: "10px 12px",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        background: "rgba(15, 28, 59, 0.45)",
      }}
    >
      <div
        style={{
          fontSize: "0.65rem",
          color: "var(--subtext)",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: "1.05rem",
          fontWeight: 700,
          fontFamily: "var(--mono)",
          marginTop: 2,
        }}
      >
        {value}
      </div>
      {sub && (
        <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function LinkButton({ onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: "transparent",
        border: "1px solid var(--border-bright)",
        borderRadius: 6,
        color: "var(--cyan)",
        padding: "4px 10px",
        fontSize: "0.7rem",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function EmptyCard({ label, message }) {
  return (
    <Card>
      <EmptyState
        title={`${label} coming online`}
        message={
          message ||
          "Sleeper hasn't surfaced enough data for this section yet. It will fill in as games finish, trades complete, and drafts are held."
        }
      />
    </Card>
  );
}

// ── OVERVIEW ──────────────────────────────────────────────────────────────
function OverviewSection({ managers, data, onNavigate }) {
  if (!data || Object.keys(data).length === 0) return <EmptyCard label="Overview" />;

  const champ = data.currentChampion;
  const rivalry = data.featuredRivalry;
  const records = data.topRecordCallouts || [];
  const recent = data.recentTrades || [];
  const draftLeader = data.draftCapitalLeader;
  const recap = data.latestWeeklyRecap;
  const decorated = data.mostDecoratedFranchise;
  const chaos = data.mostChaoticManager;
  const hottest = data.hottestRace;
  const vitals = data.leagueVitals || {};
  const hottestTrade = data.hottestTrade;

  return (
    <>
      <Card title="At a glance" subtitle="Public snapshot across the last 2 dynasty seasons">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10 }}>
          <Stat label="Seasons" value={vitals.seasonsCovered ?? "—"} sub={data.seasonRangeLabel} />
          <Stat label="Managers" value={vitals.managers ?? "—"} />
          <Stat label="Trades" value={vitals.totalTrades ?? "—"} />
          <Stat label="Waivers" value={vitals.totalWaivers ?? "—"} />
          <Stat label="Scored weeks" value={vitals.totalScoredWeeks ?? "—"} />
        </div>
      </Card>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {champ && (
          <div className="card" style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Defending champion
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={champ.ownerId} size={42} />
              <div>
                <div style={{ fontSize: "1.3rem", fontWeight: 800, lineHeight: 1.15 }}>
                  {champ.displayName}
                </div>
                <div style={{ fontSize: "0.78rem", color: "var(--subtext)" }}>
                  {champ.teamName} · {champ.season} title
                </div>
              </div>
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("history")}>View championship history →</LinkButton>
            </div>
          </div>
        )}
        {rivalry && (
          <div className="card" style={{ flex: "1 1 280px", minWidth: 240 }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Featured rivalry · hottest index
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={rivalry.ownerIds[0]} size={28} />
              <span style={{ color: "var(--subtext)", fontWeight: 700 }}>vs</span>
              <Avatar managers={managers} ownerId={rivalry.ownerIds[1]} size={28} />
              <span style={{ fontSize: "1rem", fontWeight: 800, marginLeft: 6 }}>
                {nameFor(managers, rivalry.ownerIds[0])} vs {nameFor(managers, rivalry.ownerIds[1])}
              </span>
            </div>
            <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginTop: 4 }}>
              {rivalry.totalMeetings} meetings · {rivalry.playoffMeetings} playoff · Rivalry Index {rivalry.rivalryIndex}
            </div>
            <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 4 }}>
              Series: {rivalry.winsA}–{rivalry.winsB}{rivalry.ties ? `–${rivalry.ties}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("rivalries")}>Explore rivalries →</LinkButton>
            </div>
          </div>
        )}
      </div>

      {records.length > 0 && (
        <Card title="Headline records" subtitle="Biggest numbers in the last 2 seasons">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
            {records.map((r, i) => (
              <div key={i} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
                <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                  {r.label}
                </div>
                <div style={{ fontSize: "1.1rem", fontWeight: 700, fontFamily: "var(--mono)" }}>
                  {r.formattedValue}
                </div>
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 2 }}>
                  <ManagerInline managers={managers} ownerId={r.ownerId} compact />
                  {r.season ? <span style={{ marginLeft: 4 }}>· {r.season}</span> : null}
                  {r.week ? <span style={{ marginLeft: 4 }}>· Wk {r.week}</span> : null}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10 }}>
            <LinkButton onClick={() => onNavigate("records")}>Full record book →</LinkButton>
          </div>
        </Card>
      )}

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {hottest && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Hot race · season to date
            </div>
            <div style={{ fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>{hottest.label}</div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>{hottest.description}</div>
            <div style={{ marginTop: 10, fontSize: "0.9rem", fontWeight: 700 }}>
              <ManagerInline managers={managers} ownerId={hottest.topLeader?.ownerId} />
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("awards")}>See all races →</LinkButton>
            </div>
          </div>
        )}
        {decorated && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Most decorated franchise
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={decorated.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{decorated.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              {decorated.championships}× champ · {decorated.finalsAppearances} finals · {decorated.playoffAppearances} playoffs
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("franchise", { owner: decorated.ownerId })}>
                Open franchise page →
              </LinkButton>
            </div>
          </div>
        )}
        {chaos && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Most chaotic manager
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={chaos.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{chaos.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              Chaos score {chaos.score ?? "—"}{chaos.season ? ` · ${chaos.season}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("activity")}>See trade activity →</LinkButton>
            </div>
          </div>
        )}
      </div>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        {draftLeader && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Best draft stockpile
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 6 }}>
              <Avatar managers={managers} ownerId={draftLeader.ownerId} size={36} />
              <div style={{ fontSize: "1.05rem", fontWeight: 800 }}>{draftLeader.displayName}</div>
            </div>
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 4 }}>
              {draftLeader.totalPicks} picks · Weighted score {draftLeader.weightedScore}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("draft", { owner: draftLeader.ownerId })}>
                Full draft center →
              </LinkButton>
            </div>
          </div>
        )}
        {recap && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Latest weekly recap
            </div>
            <div style={{ fontSize: "1.05rem", fontWeight: 800, marginTop: 4 }}>
              {recap.season} · Week {recap.week}{recap.isPlayoff ? " (playoffs)" : ""}
            </div>
            {recap.gameOfTheWeek && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 4 }}>
                Game of the week: {recap.gameOfTheWeek.home?.displayName} vs {recap.gameOfTheWeek.away?.displayName} (margin {fmtPoints(recap.gameOfTheWeek.margin)})
              </div>
            )}
            {recap.highestScorer && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
                Top scorer: {recap.highestScorer.displayName} ({fmtPoints(recap.highestScorer.points)})
              </div>
            )}
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("weekly", { week: `${recap.season}:${recap.week}` })}>
                Open weekly recap →
              </LinkButton>
            </div>
          </div>
        )}
        {hottestTrade && (
          <div className="card" style={{ flex: "1 1 280px" }}>
            <div style={{ fontSize: "0.66rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
              Hottest trade · biggest blockbuster
            </div>
            <div style={{ fontSize: "0.94rem", fontWeight: 700, marginTop: 4 }}>
              {hottestTrade.sides.map((s) => s.displayName).join(" ↔ ")}
            </div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
              {hottestTrade.totalAssets} total assets · {hottestTrade.season} {hottestTrade.week ? `Wk ${hottestTrade.week}` : ""}
            </div>
            <div style={{ marginTop: 10 }}>
              <LinkButton onClick={() => onNavigate("activity")}>Open trade center →</LinkButton>
            </div>
          </div>
        )}
      </div>

      {recent.length > 0 && (
        <Card title="Recent trades" subtitle="Last 5 completed deals">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {recent.map((t) => (
              <div
                key={t.transactionId}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}
              >
                <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
                  {t.season} · Week {t.week ?? "—"} · {t.totalAssets} asset{t.totalAssets === 1 ? "" : "s"}
                </div>
                <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 4 }}>
                  {t.sides.map((s, i) => (
                    <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <Avatar managers={managers} ownerId={s.ownerId} size={18} />
                      <span style={{ fontWeight: 700 }}>{s.displayName}</span>
                      <span style={{ color: "var(--subtext)", marginLeft: 2, fontSize: "0.7rem" }}>
                        received {s.receivedPlayerCount} players · {s.receivedPickCount} picks
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 10 }}>
            <LinkButton onClick={() => onNavigate("activity")}>View all trades →</LinkButton>
          </div>
        </Card>
      )}
    </>
  );
}

// ── HISTORY / HALL OF FAME ────────────────────────────────────────────────
function HistorySection({ managers, data, onNavigate }) {
  const hof = data?.hallOfFame || [];
  const seasons = data?.seasons || [];
  const champs = data?.championsBySeason || [];
  if (!hof.length && !seasons.length) return <EmptyCard label="Hall of Fame" />;

  const byPoints = [...hof].sort((a, b) => b.pointsFor - a.pointsFor);
  const byPlayoffs = [...hof].sort((a, b) => b.playoffAppearances - a.playoffAppearances);
  const byFinals = [...hof].sort((a, b) => b.finalsAppearances - a.finalsAppearances);

  return (
    <>
      {champs.length > 0 && (
        <Card title="Champion timeline" subtitle="Winners of the final playoff matchup">
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {champs.map((c) => (
              <div
                key={c.season}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius)",
                  padding: 10,
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  cursor: "pointer",
                }}
                onClick={() => onNavigate("franchise", { owner: c.ownerId })}
              >
                <Avatar managers={managers} ownerId={c.ownerId} size={36} />
                <div>
                  <div style={{ fontSize: "0.66rem", color: "var(--subtext)" }}>{c.season}</div>
                  <div style={{ fontWeight: 700, fontSize: "1rem" }}>{c.displayName}</div>
                  <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>{c.teamName}</div>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card title="Hall of Fame" subtitle="Cumulative stats across the last 2 seasons">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Manager</th>
                <th style={{ textAlign: "right" }}>Seasons</th>
                <th style={{ textAlign: "right" }}>Record</th>
                <th style={{ textAlign: "right" }}>Titles</th>
                <th style={{ textAlign: "right" }}>Finals</th>
                <th style={{ textAlign: "right" }}>Playoffs</th>
                <th style={{ textAlign: "right" }}>Reg 1st</th>
                <th style={{ textAlign: "right" }}>Points</th>
              </tr>
            </thead>
            <tbody>
              {hof.map((row) => (
                <tr
                  key={row.ownerId}
                  onClick={() => onNavigate("franchise", { owner: row.ownerId })}
                  style={{ cursor: "pointer" }}
                >
                  <td style={{ fontWeight: 600 }}>
                    <ManagerInline managers={managers} ownerId={row.ownerId} compact />
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.seasonsPlayed}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.championships || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.finalsAppearances || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.playoffAppearances || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.regularSeasonFirstPlace || 0}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsFor, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="row" style={{ marginTop: "var(--space-md)", gap: 14 }}>
        <MiniLeaderboard
          managers={managers}
          title="Points leaders"
          rows={byPoints}
          metric={(r) => fmtNumber(r.pointsFor, 1)}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
        <MiniLeaderboard
          managers={managers}
          title="Playoff appearances"
          rows={byPlayoffs}
          metric={(r) => r.playoffAppearances || 0}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
        <MiniLeaderboard
          managers={managers}
          title="Finals appearances"
          rows={byFinals}
          metric={(r) => r.finalsAppearances || 0}
          onRowClick={(ownerId) => onNavigate("franchise", { owner: ownerId })}
        />
      </div>

      {seasons.map((s) => (
        <Card
          key={s.leagueId}
          title={`${s.season} season`}
          subtitle={[
            s.champion ? `Champion: ${s.champion.displayName}` : null,
            s.topSeed ? `Top seed: ${s.topSeed.displayName}` : null,
            s.regularSeasonPointsLeader ? `Points leader: ${s.regularSeasonPointsLeader.displayName}` : null,
          ].filter(Boolean).join(" · ")}
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Team</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Seed</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(s.standings || []).map((row) => (
                  <tr
                    key={row.ownerId}
                    onClick={() => onNavigate("franchise", { owner: row.ownerId })}
                    style={{ cursor: "pointer" }}
                  >
                    <td style={{ fontWeight: 600 }}>
                      <ManagerInline managers={managers} ownerId={row.ownerId} compact />
                      <span style={{ marginLeft: 6, color: "var(--subtext)", fontSize: "0.7rem" }}>
                        {row.teamName}
                      </span>
                      {row.madePlayoffs && (
                        <span style={{ marginLeft: 6, fontSize: "0.65rem", color: "var(--green)" }}>★</span>
                      )}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {row.wins}-{row.losses}{row.ties ? `-${row.ties}` : ""}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsFor, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(row.pointsAgainst, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.standing}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.finalPlace ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </>
  );
}

function MiniLeaderboard({ managers, title, rows, metric, onRowClick }) {
  if (!rows || !rows.length) return null;
  return (
    <div className="card" style={{ flex: "1 1 260px" }}>
      <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {rows.slice(0, 5).map((r, i) => (
          <div
            key={r.ownerId || i}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              fontSize: "0.74rem",
              cursor: onRowClick ? "pointer" : "default",
            }}
            onClick={() => onRowClick?.(r.ownerId)}
          >
            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", minWidth: 16 }}>{i + 1}.</span>
              {managers ? <Avatar managers={managers} ownerId={r.ownerId} size={18} /> : null}
              {r.displayName || r.currentTeamName || r.ownerId}
            </span>
            <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{metric(r)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── RIVALRIES ──────────────────────────────────────────────────────────────
function RivalriesSection({ managers, data, onNavigate }) {
  const rows = data?.rivalries || [];
  const [selected, setSelected] = useState(0);
  if (!rows.length) return <EmptyCard label="Rivalries" />;

  const featured = rows.slice(0, 3);
  const detail = rows[selected] || null;

  return (
    <>
      <Card title="Top rivalries" subtitle="Ranked by rivalry index (playoffs + close games + splits + meetings)">
        <div className="row">
          {featured.map((r, i) => (
            <div
              key={i}
              className="card"
              style={{
                flex: "1 1 240px",
                cursor: "pointer",
                borderColor: selected === i ? "var(--cyan)" : "var(--border)",
              }}
              onClick={() => setSelected(i)}
            >
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)" }}>Rivalry Index {r.rivalryIndex}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4 }}>
                <Avatar managers={managers} ownerId={r.ownerIds[0]} size={22} />
                <span style={{ fontWeight: 700, fontSize: "0.9rem" }}>
                  {nameFor(managers, r.ownerIds[0])} vs {nameFor(managers, r.ownerIds[1])}
                </span>
                <Avatar managers={managers} ownerId={r.ownerIds[1]} size={22} />
              </div>
              <div style={{ fontSize: "0.74rem", color: "var(--subtext)", marginTop: 2 }}>
                {r.totalMeetings} meet · {r.playoffMeetings} playoff · Split seasons {r.seasonsWhereSeriesSplit}
              </div>
              <div style={{ fontSize: "0.72rem", marginTop: 4 }}>
                Series: {r.winsA}–{r.winsB}{r.ties ? `–${r.ties}` : ""}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {detail && (
        <Card
          title={`${nameFor(managers, detail.ownerIds[0])} vs ${nameFor(managers, detail.ownerIds[1])}`}
          subtitle="Head-to-head detail"
          action={
            <div style={{ display: "flex", gap: 6 }}>
              <LinkButton onClick={() => onNavigate("franchise", { owner: detail.ownerIds[0] })}>
                {nameFor(managers, detail.ownerIds[0])} page →
              </LinkButton>
              <LinkButton onClick={() => onNavigate("franchise", { owner: detail.ownerIds[1] })}>
                {nameFor(managers, detail.ownerIds[1])} page →
              </LinkButton>
            </div>
          }
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 10, marginBottom: 14 }}>
            <Stat label="Meetings" value={detail.totalMeetings} sub={`${detail.regularSeasonMeetings} reg · ${detail.playoffMeetings} playoff`} />
            <Stat label="Series" value={`${detail.winsA}–${detail.winsB}${detail.ties ? `–${detail.ties}` : ""}`} />
            <Stat label="Points" value={`${fmtPoints(detail.pointsA)} / ${fmtPoints(detail.pointsB)}`} />
            <Stat label="Close (≤5 pts)" value={detail.gamesDecidedByFive} sub="most decisive closeness band" />
            <Stat label="Close (≤10 pts)" value={detail.gamesDecidedByTen} />
          </div>

          <div style={{ fontWeight: 600, marginBottom: 6 }}>Memorable meetings</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
            <MeetingCard label="Closest" meeting={detail.closestGame} />
            <MeetingCard label="Biggest blowout" meeting={detail.biggestBlowout} />
            <MeetingCard label="Last meeting" meeting={detail.lastMeeting} />
          </div>

          {detail.seasonSplits && Object.keys(detail.seasonSplits).length > 0 && (
            <>
              <div style={{ fontWeight: 600, marginTop: 14, marginBottom: 6 }}>Season splits</div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Season</th>
                      <th style={{ textAlign: "right" }}>{nameFor(managers, detail.ownerIds[0])} wins</th>
                      <th style={{ textAlign: "right" }}>{nameFor(managers, detail.ownerIds[1])} wins</th>
                      <th style={{ textAlign: "right" }}>Ties</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(detail.seasonSplits).map(([season, split]) => (
                      <tr key={season}>
                        <td>{season}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.winsA}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.winsB}</td>
                        <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{split.ties}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      )}

      <Card title="All rivalries" subtitle="Every pair that has met">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Pair</th>
                <th style={{ textAlign: "right" }}>Index</th>
                <th style={{ textAlign: "right" }}>Meet</th>
                <th style={{ textAlign: "right" }}>Playoff</th>
                <th style={{ textAlign: "right" }}>Series</th>
                <th style={{ textAlign: "right" }}>Points</th>
                <th style={{ textAlign: "right" }}>Closest</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} style={{ cursor: "pointer" }} onClick={() => setSelected(i)}>
                  <td style={{ fontWeight: 600 }}>
                    {nameFor(managers, r.ownerIds[0])} vs {nameFor(managers, r.ownerIds[1])}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.rivalryIndex}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.totalMeetings}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.playoffMeetings}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.winsA}-{r.winsB}{r.ties ? `-${r.ties}` : ""}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {fmtPoints(r.pointsA)} / {fmtPoints(r.pointsB)}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                    {r.closestGame ? fmtPoints(r.closestGame.margin) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function MeetingCard({ label, meeting }) {
  if (!meeting) return null;
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.86rem", fontWeight: 700, marginTop: 2 }}>
        {meeting.season} · Wk {meeting.week}{meeting.isPlayoff ? " (P)" : ""}
      </div>
      <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginTop: 2 }}>
        Margin {fmtPoints(meeting.margin)} · {fmtPoints(meeting.pointsA)} / {fmtPoints(meeting.pointsB)}
      </div>
    </div>
  );
}

// ── AWARDS ────────────────────────────────────────────────────────────────
function AwardsSection({ managers, data, onNavigate }) {
  const seasons = data?.bySeason || [];
  const races = data?.awardRaces || [];
  if (!seasons.length && !races.length) return <EmptyCard label="Awards" />;

  return (
    <>
      {races.length > 0 && (
        <Card
          title="Award races · season to date"
          subtitle={`Top 3 for every live race${data.currentSeason ? ` · ${data.currentSeason} in progress` : ""}`}
        >
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
            {races.map((race) => (
              <div
                key={race.key}
                style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 12 }}
              >
                <div style={{ fontWeight: 700 }}>{race.label}</div>
                <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 2, marginBottom: 8, lineHeight: 1.4 }}>
                  {race.description}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                  {race.leaders.map((leader) => (
                    <div
                      key={leader.ownerId}
                      style={{ display: "flex", justifyContent: "space-between", alignItems: "center", fontSize: "0.78rem" }}
                    >
                      <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", minWidth: 16 }}>
                          {leader.rank}.
                        </span>
                        <Avatar managers={managers} ownerId={leader.ownerId} size={18} />
                        <span
                          style={{ cursor: "pointer", color: "var(--cyan)" }}
                          onClick={() => onNavigate("franchise", { owner: leader.ownerId })}
                        >
                          {leader.displayName}
                        </span>
                      </span>
                      <span style={{ fontFamily: "var(--mono)", color: "var(--text)" }}>
                        {renderAwardValue(race.key, leader.value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {seasons.map((s) => (
        <Card
          key={s.leagueId}
          title={`${s.season} award winners`}
          subtitle={s.isComplete ? "Season complete" : "Season in progress"}
        >
          {s.hasPlayerScoring === false && (
            <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 8 }}>
              Trader / Waiver / Playoff MVP awards depend on per-player scoring that
              Sleeper didn't surface for this season — some awards may be skipped.
            </div>
          )}
          {(s.awards || []).length === 0 ? (
            <EmptyState
              title="No awards yet"
              message="Awards will appear once the season has enough games / transactions / trades on record."
            />
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10 }}>
              {(s.awards || []).map((a) => (
                <div
                  key={a.key}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: "var(--radius)",
                    padding: 12,
                    background: "rgba(15, 28, 59, 0.45)",
                  }}
                >
                  <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                    {a.label}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                    {a.ownerId && <Avatar managers={managers} ownerId={a.ownerId} size={24} />}
                    <div>
                      <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{a.displayName}</div>
                      {a.teamName && a.teamName !== a.displayName && (
                        <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>{a.teamName}</div>
                      )}
                    </div>
                  </div>
                  {a.value && (
                    <div style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--cyan)", marginTop: 6 }}>
                      {renderAwardValue(a.key, a.value)}
                    </div>
                  )}
                  {a.description && (
                    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 8, lineHeight: 1.4 }}>
                      {a.description}
                    </div>
                  )}
                  {a.ownerId && (
                    <div style={{ marginTop: 8 }}>
                      <LinkButton onClick={() => onNavigate("franchise", { owner: a.ownerId })}>
                        Franchise page →
                      </LinkButton>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>
      ))}
    </>
  );
}

function renderAwardValue(key, value) {
  if (!value) return "";
  switch (key) {
    case "champion":
    case "runner_up":
    case "toilet_bowl":
      return "";
    case "top_seed":
      return `Win% ${fmtPercent(value.winPct)}`;
    case "regular_season_crown":
      return value.record || "";
    case "points_king":
      return `${fmtNumber(value.pointsFor, 1)} PF`;
    case "points_black_hole":
      return `${fmtNumber(value.pointsAgainst, 1)} PA`;
    case "highest_single_week":
    case "lowest_single_week":
      return `Wk ${value.week} · ${fmtPoints(value.points)} pts`;
    case "trader_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.trades} trades`;
    case "best_trade_of_the_year":
      return `+${fmtPoints(value.pointsGained)} pts · Wk ${value.week}`;
    case "waiver_king":
      return `+${fmtPoints(value.pointsGained)} pts · ${value.adds} adds`;
    case "chaos_agent":
      return `Score ${value.score} · ${value.trades} trades · ${value.partners} partners`;
    case "most_active":
      return `${value.total} moves`;
    case "silent_assassin":
      return `${fmtPercent(value.winPct)} in ${value.closeGames} close games`;
    case "weekly_hammer":
      return `${value.highScoreFinishes} high-score wks`;
    case "playoff_mvp":
      return `${fmtPoints(value.playoffPoints)} playoff pts`;
    case "bad_beat":
      return `${fmtPoints(value.points)} in loss · Wk ${value.week}`;
    case "best_rebuild":
      return `Composite ${value.compositeScore}`;
    case "rivalry_of_the_year":
      return `${value.displayNames[0]} vs ${value.displayNames[1]} · Index ${value.rivalryIndex}`;
    case "pick_hoarder":
      return `Weighted ${value.weightedScore} · ${value.totalPicks} picks`;
    default:
      return "";
  }
}

// ── RECORDS ────────────────────────────────────────────────────────────────
function RecordsSection({ data }) {
  if (!data) return <EmptyCard label="Records" />;

  const groups = [
    { title: "Highest single-week scores", key: "singleWeekHighest" },
    { title: "Lowest single-week scores", key: "singleWeekLowest" },
    { title: "Biggest margin of victory", key: "biggestMargin" },
    { title: "Narrowest victories", key: "narrowestVictory" },
    { title: "Most points in a loss", key: "mostPointsInLoss" },
    { title: "Fewest points in a win", key: "fewestPointsInWin" },
  ];

  return (
    <>
      <Card title="Record book" subtitle="Single-game extremes across the last 2 seasons">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 10 }}>
          {groups.map((g) => (
            <div key={g.key} style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
              <div style={{ fontWeight: 700, marginBottom: 6, fontSize: "0.86rem" }}>{g.title}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                {(data[g.key] || []).slice(0, 5).map((r, i) => (
                  <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.74rem" }}>
                    <span>
                      <span style={{ color: "var(--subtext)", marginRight: 4 }}>{i + 1}.</span>
                      {r.teamName}
                    </span>
                    <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>
                      {r.margin !== undefined && g.key.toLowerCase().includes("margin")
                        ? `${fmtPoints(r.margin)} (${fmtPoints(r.points)})`
                        : fmtPoints(r.points)}
                    </span>
                  </div>
                ))}
                {(data[g.key] || []).length === 0 && (
                  <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>—</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <Card title="Season totals" subtitle="Most points scored / allowed in a single season">
        <div className="row">
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points in a season</div>
            {(data.mostPointsInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{fmtNumber(r.totalPoints, 1)}</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points against in a season</div>
            {(data.mostPointsAgainstInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span>
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--red)" }}>{fmtNumber(r.totalPointsAgainst, 1)}</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Streaks" subtitle="Longest consecutive wins / losses (ties end streaks)">
        <div className="row">
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Longest win streaks</div>
            {(data.longestWinStreaks || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName}
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--green)" }}>{r.length} wins</span>
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 260px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Longest losing streaks</div>
            {(data.longestLossStreaks || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                <span>
                  <span style={{ color: "var(--subtext)", fontFamily: "var(--mono)", marginRight: 6 }}>{i + 1}.</span>
                  {r.displayName}
                </span>
                <span style={{ fontFamily: "var(--mono)", color: "var(--red)" }}>{r.length} losses</span>
              </div>
            ))}
          </div>
        </div>
      </Card>

      <Card title="Transactions & FAAB" subtitle="Season-level activity records">
        <div className="row">
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most trades in a season</div>
            {(data.mostTradesInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                {r.season}: <strong>{r.tradeCount}</strong> trades
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Most waivers in a season</div>
            {(data.mostWaiversInSeason || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                {r.season}: <strong>{r.waiverCount}</strong> waivers
              </div>
            ))}
          </div>
          <div className="card" style={{ flex: "1 1 220px" }}>
            <div style={{ fontWeight: 700, marginBottom: 8 }}>Largest FAAB bids</div>
            {(data.largestFaabBid || []).slice(0, 5).map((r, i) => (
              <div key={i} style={{ fontSize: "0.74rem", padding: "2px 0" }}>
                ${r.bid} · {r.displayName} · {r.playerName || r.playerId}
              </div>
            ))}
            {(!data.largestFaabBid || data.largestFaabBid.length === 0) && (
              <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>No FAAB bids on file.</div>
            )}
          </div>
        </div>
      </Card>

      {data.playoffRecords && (
        <Card title="Playoff records">
          <div className="row">
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Most points in playoffs</div>
              {(data.playoffRecords.mostPointsInPlayoffs || []).slice(0, 5).map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                  <span>{r.teamName}</span>
                  <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{fmtPoints(r.points)}</span>
                </div>
              ))}
            </div>
            <div className="card" style={{ flex: "1 1 260px" }}>
              <div style={{ fontWeight: 700, marginBottom: 8 }}>Most playoff wins in a season</div>
              {(data.playoffRecords.mostPlayoffWinsInSeason || []).slice(0, 5).map((r, i) => (
                <div key={i} style={{ display: "flex", justifyContent: "space-between", fontSize: "0.76rem", padding: "2px 0" }}>
                  <span>{r.displayName} <span style={{ color: "var(--subtext)" }}>({r.season})</span></span>
                  <span style={{ fontFamily: "var(--mono)", color: "var(--cyan)" }}>{r.playoffWins}</span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </>
  );
}

// ── FRANCHISES ────────────────────────────────────────────────────────────
function FranchiseSection({ managers, data, onNavigate, initialOwner, setOwner }) {
  const index = data?.index || [];
  const detail = data?.detail || {};
  const initial = initialOwner && detail[initialOwner] ? initialOwner : (index[0]?.ownerId || "");
  const [selected, setSelectedInner] = useState(initial);

  // If the URL owner changes externally (back nav), reflect it.
  useEffect(() => {
    if (initialOwner && detail[initialOwner] && initialOwner !== selected) {
      setSelectedInner(initialOwner);
    }
  }, [initialOwner]); // eslint-disable-line react-hooks/exhaustive-deps

  function selectOwner(ownerId) {
    setSelectedInner(ownerId);
    if (setOwner) setOwner(ownerId);
  }

  if (!index.length) return <EmptyCard label="Franchises" />;
  const fr = detail[selected] || null;

  return (
    <>
      <Card title="Franchise index" subtitle="Sorted by titles, then best finish, then wins">
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
          {index.map((row) => (
            <div
              key={row.ownerId}
              onClick={() => selectOwner(row.ownerId)}
              style={{
                border: "1px solid",
                borderColor: selected === row.ownerId ? "var(--cyan)" : "var(--border)",
                borderRadius: "var(--radius)",
                padding: 10,
                cursor: "pointer",
                background: selected === row.ownerId ? "rgba(86, 214, 255, 0.08)" : "transparent",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Avatar managers={managers} ownerId={row.ownerId} size={28} />
                <div>
                  <div style={{ fontWeight: 700 }}>{row.displayName}</div>
                  <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{row.currentTeamName}</div>
                </div>
              </div>
              <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginTop: 6 }}>
                {row.championships}× ★ · {row.wins}-{row.losses} · {row.seasonsPlayed} seasons
              </div>
            </div>
          ))}
        </div>
      </Card>

      {fr && (
        <Card
          title={fr.displayName}
          subtitle={`Current: ${fr.currentTeamName || "—"}${fr.currentLeagueId ? ` · League id ${fr.currentLeagueId.slice(-6)}` : ""}`}
          action={
            fr.topRival && (
              <span style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
                Top rival:{" "}
                <strong style={{ color: "var(--cyan)", cursor: "pointer" }} onClick={() => onNavigate("rivalries")}>
                  {fr.topRival.displayName}
                </strong>{" "}
                · Index {fr.topRival.rivalryIndex}
              </span>
            )
          }
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
            <Avatar managers={managers} ownerId={selected} size={56} />
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
              Owner ID: <span style={{ fontFamily: "var(--mono)" }}>{selected}</span>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 14 }}>
            <Stat label="Seasons" value={fr.cumulative.seasonsPlayed} />
            <Stat
              label="Record"
              value={`${fr.cumulative.wins}-${fr.cumulative.losses}${fr.cumulative.ties ? `-${fr.cumulative.ties}` : ""}`}
            />
            <Stat label="Points for" value={fmtNumber(fr.cumulative.pointsFor, 1)} />
            <Stat
              label="Titles"
              value={fr.cumulative.championships}
              sub={`${fr.cumulative.finalsAppearances} finals`}
            />
            <Stat
              label="Playoffs"
              value={fr.cumulative.playoffAppearances}
              sub={`${fr.cumulative.regularSeasonFirstPlace} reg 1st`}
            />
            <Stat
              label="Trades"
              value={fr.tradeCount}
              sub={`${fr.waiverCount} waivers`}
            />
          </div>

          {fr.draftCapital && (
            <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10, marginBottom: 14 }}>
              <div style={{ fontWeight: 700, marginBottom: 6 }}>Draft capital</div>
              <div style={{ fontSize: "0.78rem", color: "var(--subtext)", marginBottom: 6 }}>
                Weighted score {fr.draftCapital.weightedScore} · {fr.draftCapital.totalPicks} owned picks
              </div>
              {(fr.draftCapital.picks || []).length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                  {(fr.draftCapital.picks || []).map((p, i) => (
                    <span
                      key={i}
                      style={{
                        fontFamily: "var(--mono)",
                        fontSize: "0.7rem",
                        border: "1px solid var(--border)",
                        padding: "2px 6px",
                        borderRadius: 4,
                        color: p.isTraded ? "var(--amber)" : "var(--text)",
                      }}
                    >
                      {p.label}{p.isTraded ? "*" : ""}
                    </span>
                  ))}
                </div>
              )}
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
                * acquired via trade
              </div>
            </div>
          )}

          <div style={{ fontWeight: 600, marginBottom: 6 }}>Season results</div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Season</th>
                  <th>Team</th>
                  <th style={{ textAlign: "right" }}>W-L-T</th>
                  <th style={{ textAlign: "right" }}>PF</th>
                  <th style={{ textAlign: "right" }}>PA</th>
                  <th style={{ textAlign: "right" }}>Seed</th>
                  <th style={{ textAlign: "right" }}>Final</th>
                </tr>
              </thead>
              <tbody>
                {(fr.seasonResults || []).map((r, i) => (
                  <tr key={i}>
                    <td>{r.season}</td>
                    <td style={{ fontWeight: 600 }}>{r.teamName}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {r.wins}-{r.losses}{r.ties ? `-${r.ties}` : ""}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsFor, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsAgainst, 1)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.standing}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {(fr.aliases || []).length > 1 && (
            <div style={{ marginTop: 14, fontSize: "0.72rem", color: "var(--subtext)" }}>
              Team-name history: {(fr.aliases || []).map((a) => `${a.teamName} (${a.season})`).join(" → ")}
            </div>
          )}
        </Card>
      )}
    </>
  );
}

// ── TRADE ACTIVITY CENTER ──────────────────────────────────────────────────
function ActivitySection({ managers, data, onNavigate }) {
  const feed = data?.feed || [];
  const [filter, setFilter] = useState("");
  if (!feed.length && !data?.totalCount) return <EmptyCard label="Trade activity" />;

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return feed;
    return feed.filter((t) => {
      const tokens = [
        t.season,
        t.week,
        ...(t.sides || []).map((s) => s.displayName),
        ...(t.sides || []).flatMap((s) => (s.receivedAssets || []).map((a) => a.playerName || "")),
      ].filter(Boolean).join(" ").toLowerCase();
      return tokens.includes(q);
    });
  }, [feed, filter]);

  return (
    <>
      <Card title="Trade activity" subtitle={`${data.totalCount} completed trades across the last 2 seasons`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 12 }}>
          <Stat label="Picks moved" value={data.picksMovedCount || 0} />
          <Stat label="Players moved" value={data.playersMovedCount || 0} />
          <Stat
            label="Most active trader"
            value={data.mostActiveTrader?.displayName || "—"}
            sub={data.mostActiveTrader ? `${data.mostActiveTrader.trades} trades` : ""}
          />
          <Stat
            label="Top partner pair"
            value={data.mostFrequentPartnerPair?.displayNames?.join(" + ") || "—"}
            sub={data.mostFrequentPartnerPair ? `${data.mostFrequentPartnerPair.trades} deals` : ""}
          />
        </div>
      </Card>

      {data.biggestBlockbusters && data.biggestBlockbusters.length > 0 && (
        <Card title="Biggest blockbusters" subtitle="Sorted by total assets moved">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
            {data.biggestBlockbusters.map((t) => (
              <TradeCard key={t.transactionId} trade={t} managers={managers} onNavigate={onNavigate} />
            ))}
          </div>
        </Card>
      )}

      {data.positionMixMoved && Object.keys(data.positionMixMoved).length > 0 && (
        <Card title="Position mix moved" subtitle="Players moved by position in completed trades">
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {Object.entries(data.positionMixMoved).sort(([, a], [, b]) => b - a).map(([pos, n]) => (
              <div
                key={pos}
                style={{
                  border: "1px solid var(--border)",
                  padding: "6px 12px",
                  borderRadius: 6,
                  fontSize: "0.78rem",
                }}
              >
                <strong>{pos}</strong>: {n}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card
        title="Trade timeline"
        subtitle="Filter by team name, player, or season"
        action={
          <input
            className="input"
            placeholder="Filter trades..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ minWidth: 220 }}
          />
        }
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((t) => (
            <TradeCard key={t.transactionId} trade={t} managers={managers} onNavigate={onNavigate} />
          ))}
          {filtered.length === 0 && (
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
              No trades match that filter.
            </div>
          )}
        </div>
      </Card>
    </>
  );
}

function TradeCard({ trade, managers, onNavigate }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
        {trade.season} · Week {trade.week ?? "—"} · {trade.totalAssets} assets
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${Math.max(1, (trade.sides || []).length)}, 1fr)`,
          gap: 8,
          marginTop: 6,
        }}
      >
        {(trade.sides || []).map((side, i) => (
          <div key={i} style={{ minWidth: 0 }}>
            <div
              style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: "0.86rem" }}
              onClick={() => onNavigate && side.ownerId && onNavigate("franchise", { owner: side.ownerId })}
            >
              <Avatar managers={managers} ownerId={side.ownerId} size={20} />
              <span style={{ cursor: side.ownerId ? "pointer" : "default", color: side.ownerId ? "var(--cyan)" : "var(--text)" }}>
                {side.displayName || side.teamName || nameFor(managers, side.ownerId)}
              </span>
            </div>
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>Received:</div>
            <ul style={{ paddingInlineStart: 16, margin: "4px 0 0", fontSize: "0.72rem" }}>
              {(side.receivedAssets || []).map((a, j) => (
                <li key={j}>
                  {a.kind === "player" ? (
                    <>
                      {a.playerName || "Player"}
                      <span style={{ color: "var(--subtext)", marginLeft: 4 }}>({a.position || "?"})</span>
                    </>
                  ) : (
                    <>{a.label || `${a.season} R${a.round}`}</>
                  )}
                </li>
              ))}
              {(side.receivedAssets || []).length === 0 && (
                <li style={{ color: "var(--subtext)" }}>—</li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── DRAFT CENTER ──────────────────────────────────────────────────────────
function DraftSection({ data, initialOwner, setOwner }) {
  if (!data) return <EmptyCard label="Drafts" />;
  const board = data.stockpileLeaderboard || [];
  const ownership = data.pickOwnership || {};
  const defaultOwner = board.find((r) => r.ownerId === initialOwner)?.ownerId
    || board[0]?.ownerId
    || "";
  const [selectedOwner, setSelectedOwnerInner] = useState(defaultOwner);
  useEffect(() => {
    if (initialOwner && ownership[initialOwner] && initialOwner !== selectedOwner) {
      setSelectedOwnerInner(initialOwner);
    }
  }, [initialOwner]); // eslint-disable-line react-hooks/exhaustive-deps
  function selectOwner(ownerId) {
    setSelectedOwnerInner(ownerId);
    if (setOwner) setOwner(ownerId);
  }
  const drafts = data.drafts || [];
  const ownerPicks = ownership[selectedOwner] || [];

  return (
    <>
      <Card title="Weighted pick stockpile" subtitle="1st round = 4 pts, 2nd = 3, 3rd = 2, 4th+ = 1">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Manager</th>
                <th style={{ textAlign: "right" }}>Total picks</th>
                <th style={{ textAlign: "right" }}>Weighted</th>
              </tr>
            </thead>
            <tbody>
              {board.map((row, i) => (
                <tr
                  key={row.ownerId}
                  onClick={() => selectOwner(row.ownerId)}
                  style={{
                    cursor: "pointer",
                    background: selectedOwner === row.ownerId ? "rgba(86, 214, 255, 0.08)" : "transparent",
                  }}
                >
                  <td style={{ fontWeight: 600 }}>
                    <span style={{ color: "var(--subtext)", marginRight: 6, fontFamily: "var(--mono)" }}>{i + 1}.</span>
                    {row.displayName}
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{row.totalPicks}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--cyan)" }}>{row.weightedScore}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {selectedOwner && (
        <Card
          title="Pick inventory"
          subtitle={`Picks owned by ${board.find((r) => r.ownerId === selectedOwner)?.displayName || "this manager"}`}
        >
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {ownerPicks.length === 0 && (
              <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>No tracked picks.</div>
            )}
            {ownerPicks.map((p, i) => (
              <span
                key={i}
                style={{
                  fontFamily: "var(--mono)",
                  fontSize: "0.72rem",
                  border: "1px solid var(--border)",
                  padding: "3px 8px",
                  borderRadius: 4,
                  color: p.isTraded ? "var(--amber)" : "var(--text)",
                }}
              >
                {p.label}{p.isTraded ? "*" : ""}
              </span>
            ))}
          </div>
          <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 6 }}>
            Amber picks (*) were acquired via trade.
          </div>
        </Card>
      )}

      {data.mostTradedPick && (
        <Card title="Most-traded pick">
          <div>
            <div style={{ fontWeight: 700, fontSize: "0.94rem" }}>{data.mostTradedPick.label}</div>
            <div style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
              Changed hands {data.mostTradedPick.moveCount} time{data.mostTradedPick.moveCount === 1 ? "" : "s"}
            </div>
          </div>
        </Card>
      )}

      {drafts.map((d) => (
        <Card
          key={d.draftId}
          title={`${d.season} rookie draft`}
          subtitle={`${d.status} · ${d.rounds || "?"} rounds · ${(d.picks || []).length} picks`}
        >
          {d.firstRoundRecap && d.firstRoundRecap.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>First round recap</div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 6 }}>
                {d.firstRoundRecap.map((p, i) => (
                  <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 6, padding: 8 }}>
                    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", fontFamily: "var(--mono)" }}>
                      {d.season} 1.{String(p.pickNo).padStart(2, "0")}
                    </div>
                    <div style={{ fontWeight: 700 }}>{p.playerName || "Unknown"}</div>
                    <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
                      {p.position || "?"}{p.nflTeam ? ` · ${p.nflTeam}` : ""} · {p.teamName}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ textAlign: "right" }}>Pick</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>NFL</th>
                  <th>Team</th>
                </tr>
              </thead>
              <tbody>
                {(d.picks || []).map((p, i) => (
                  <tr key={i}>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                      {p.round}.{String(p.pickNo).padStart(2, "0")}
                    </td>
                    <td>{p.playerName || "—"}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.position || ""}</td>
                    <td style={{ fontFamily: "var(--mono)" }}>{p.nflTeam || ""}</td>
                    <td>{p.teamName}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </>
  );
}

// ── WEEKLY RECAP ──────────────────────────────────────────────────────────
function WeeklySection({ data, managers, onNavigate, initialWeek, setWeek }) {
  const weeks = data?.weeks || [];
  const defaultKey = weeks[0] ? `${weeks[0].season}:${weeks[0].week}` : "";
  const initialKey = initialWeek && weeks.some((w) => `${w.season}:${w.week}` === initialWeek)
    ? initialWeek
    : defaultKey;
  const [selected, setSelectedInner] = useState(initialKey);
  useEffect(() => {
    if (initialWeek && weeks.some((w) => `${w.season}:${w.week}` === initialWeek) && initialWeek !== selected) {
      setSelectedInner(initialWeek);
    }
  }, [initialWeek]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!weeks.length) return <EmptyCard label="Weekly recap" />;
  const active = weeks.find((w) => `${w.season}:${w.week}` === selected) || weeks[0];
  const h = active.highlights || {};

  function changeWeek(key) {
    setSelectedInner(key);
    if (setWeek) setWeek(key);
  }

  return (
    <>
      <Card
        title={`${active.season} · Week ${active.week}${active.isPlayoff ? " (playoffs)" : ""}`}
        action={
          <select
            className="input"
            value={`${active.season}:${active.week}`}
            onChange={(e) => changeWeek(e.target.value)}
            style={{ minWidth: 180 }}
          >
            {weeks.map((w) => (
              <option key={`${w.season}:${w.week}`} value={`${w.season}:${w.week}`}>
                {w.season} Wk {w.week}{w.isPlayoff ? " (P)" : ""}
              </option>
            ))}
          </select>
        }
      >
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 10, marginBottom: 14 }}>
          <HighlightCard
            label="Game of the week"
            caption={h.gameOfTheWeek ? `margin ${fmtPoints(h.gameOfTheWeek.margin)}` : "—"}
            teams={h.gameOfTheWeek ? [h.gameOfTheWeek.home, h.gameOfTheWeek.away] : null}
          />
          <HighlightCard
            label="Blowout of the week"
            caption={h.blowoutOfTheWeek ? `margin ${fmtPoints(h.blowoutOfTheWeek.margin)}` : "—"}
            teams={h.blowoutOfTheWeek ? [h.blowoutOfTheWeek.home, h.blowoutOfTheWeek.away] : null}
          />
          <HighlightCard
            label="Upset of the week"
            caption={h.upsetOfTheWeek
              ? `winner ${h.upsetOfTheWeek.winnerOwnerId ? nameFor(managers, h.upsetOfTheWeek.winnerOwnerId) : "—"}`
              : "No upsets"}
            teams={h.upsetOfTheWeek ? [h.upsetOfTheWeek.home, h.upsetOfTheWeek.away] : null}
          />
          <SingleHighlight
            label="Highest scorer"
            value={h.highestScorer ? `${h.highestScorer.displayName} (${fmtPoints(h.highestScorer.points)})` : "—"}
          />
          <SingleHighlight
            label="Lowest scorer"
            value={h.lowestScorer ? `${h.lowestScorer.displayName} (${fmtPoints(h.lowestScorer.points)})` : "—"}
          />
          {h.standingsMover && (
            <SingleHighlight
              label="Biggest standings mover"
              value={`${nameFor(managers, h.standingsMover.ownerId)} (${h.standingsMover.preRank} → ${h.standingsMover.postRank})`}
              sub={`Δ ${h.standingsMover.delta > 0 ? "+" : ""}${h.standingsMover.delta}`}
            />
          )}
          {h.rivalryResult && (
            <SingleHighlight
              label="Rivalry meeting"
              value={`${h.rivalryResult.home?.displayName} vs ${h.rivalryResult.away?.displayName}`}
              sub={`margin ${fmtPoints(h.rivalryResult.margin)}`}
            />
          )}
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Home</th>
                <th style={{ textAlign: "right" }}>Score</th>
                <th style={{ textAlign: "right" }}>Margin</th>
                <th style={{ textAlign: "right" }}>Score</th>
                <th>Away</th>
              </tr>
            </thead>
            <tbody>
              {(active.matchups || []).map((m, i) => {
                const winnerIsHome = m.winnerOwnerId === m.home?.ownerId;
                const winnerIsAway = m.winnerOwnerId === m.away?.ownerId;
                return (
                  <tr key={i}>
                    <td style={{ fontWeight: 600, color: winnerIsHome ? "var(--green)" : "var(--text)" }}>{m.home?.displayName}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(m.home?.points)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>{fmtPoints(m.margin)}</td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(m.away?.points)}</td>
                    <td style={{ fontWeight: 600, color: winnerIsAway ? "var(--green)" : "var(--text)" }}>{m.away?.displayName}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div style={{ marginTop: 12 }}>
          <LinkButton onClick={() => onNavigate("archives")}>Open matchup archive →</LinkButton>
        </div>
      </Card>
    </>
  );
}

function HighlightCard({ label, caption, teams }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.84rem", fontWeight: 700, marginTop: 2 }}>
        {teams && teams[0] && teams[1]
          ? `${teams[0].displayName} vs ${teams[1].displayName}`
          : "—"}
      </div>
      <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>{caption}</div>
    </div>
  );
}

function SingleHighlight({ label, value, sub }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.62rem", color: "var(--subtext)", textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: "0.84rem", fontWeight: 700, marginTop: 2 }}>{value}</div>
      {sub && <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

// ── SUPERLATIVES ──────────────────────────────────────────────────────────
function SuperlativesSection({ managers, data }) {
  if (!data) return <EmptyCard label="Superlatives" />;

  const blocks = [
    { key: "mostQbHeavy", label: "Most QB-heavy", caption: "Most quarterbacks rostered" },
    { key: "mostRbHeavy", label: "Most RB-heavy", caption: "Most running backs rostered" },
    { key: "mostWrHeavy", label: "Most WR-heavy", caption: "Most wide receivers rostered" },
    { key: "mostTeHeavy", label: "Most TE-heavy", caption: "Most tight ends rostered" },
    { key: "mostIdpHeavy", label: "Most IDP-heavy", caption: "Most defenders rostered" },
    { key: "mostPickHeavy", label: "Biggest pick stockpile", caption: "Highest weighted pick score" },
    { key: "mostRookieHeavy", label: "Most rookies", caption: "Most first-year players rostered" },
    { key: "mostBalanced", label: "Most balanced", caption: "Lowest variance across QB/RB/WR/TE" },
    { key: "mostActive", label: "Most active franchise", caption: "Most trades + waivers combined" },
    { key: "mostFutureFocused", label: "Most future-focused", caption: "Blend of pick stockpile + rookies" },
  ];

  return (
    <Card
      title="Superlatives"
      subtitle="Fun, public-safe roster-composition awards across the 2-season window"
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
        {blocks.map((b) => {
          const block = data[b.key];
          if (!block || !block.winner) return null;
          const w = block.winner;
          return (
            <div
              key={b.key}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: 12,
                background: "rgba(15, 28, 59, 0.45)",
              }}
            >
              <div
                style={{
                  fontSize: "0.62rem",
                  color: "var(--subtext)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                {b.label}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <Avatar managers={managers} ownerId={w.ownerId} size={24} />
                <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{w.displayName}</div>
              </div>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 2, marginBottom: 8 }}>
                {b.caption}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 6,
                  fontSize: "0.7rem",
                  fontFamily: "var(--mono)",
                }}
              >
                <span>QB: {w.qb}</span>
                <span>RB: {w.rb}</span>
                <span>WR: {w.wr}</span>
                <span>TE: {w.te}</span>
                <span>IDP: {w.idp}</span>
                <span>Rook: {w.rookies}</span>
                <span>Trades: {w.trades}</span>
                <span>Picks: {w.weightedPickScore}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// ── ARCHIVES ──────────────────────────────────────────────────────────────
const ARCHIVE_KINDS = [
  { key: "trades", label: "Trades" },
  { key: "waivers", label: "Waivers / FA" },
  { key: "weeklyMatchups", label: "Matchups" },
  { key: "rookieDrafts", label: "Rookie drafts" },
  { key: "seasonResults", label: "Season results" },
  { key: "managers", label: "Managers" },
];

function ArchivesSection({ data }) {
  const [kind, setKind] = useState("trades");
  const [query, setQuery] = useState("");
  const [season, setSeason] = useState("all");
  if (!data) return <EmptyCard label="Archives" />;

  const seasonsCovered = data.seasonsCovered || [];
  const rows = useMemo(() => data[kind] || [], [data, kind]);
  const filtered = useMemo(() => {
    let out = rows;
    if (season !== "all") {
      out = out.filter((r) => String(r.season || "") === season);
    }
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => archiveSearchTokens(r).includes(q));
    }
    return out.slice(0, 500);
  }, [rows, query, season]);

  return (
    <Card
      title="Public archives"
      subtitle="Full searchable history of trades, waivers, matchups, drafts, and season results"
    >
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        {ARCHIVE_KINDS.map((k) => (
          <button
            key={k.key}
            type="button"
            onClick={() => setKind(k.key)}
            style={{
              padding: "6px 10px",
              fontSize: "0.74rem",
              border: "1px solid",
              borderColor: kind === k.key ? "var(--cyan)" : "var(--border)",
              background: kind === k.key ? "rgba(86, 214, 255, 0.12)" : "transparent",
              borderRadius: 6,
              color: "var(--text)",
              cursor: "pointer",
            }}
          >
            {k.label} ({(data[k.key] || []).length})
          </button>
        ))}
      </div>

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
        <input
          className="input"
          placeholder="Search..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          style={{ minWidth: 240 }}
        />
        <select
          className="input"
          value={season}
          onChange={(e) => setSeason(e.target.value)}
          style={{ minWidth: 140 }}
        >
          <option value="all">All seasons</option>
          {seasonsCovered.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <div style={{ fontSize: "0.7rem", color: "var(--subtext)", marginBottom: 6 }}>
        {filtered.length} result{filtered.length === 1 ? "" : "s"}
        {rows.length > filtered.length ? ` of ${rows.length}` : ""}
      </div>

      <div className="table-wrap">
        <ArchiveTable kind={kind} rows={filtered} />
      </div>
    </Card>
  );
}

function archiveSearchTokens(row) {
  const parts = [];
  for (const [, v] of Object.entries(row)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) {
      parts.push(
        v.map((x) => (typeof x === "object" && x !== null ? Object.values(x).join(" ") : x)).join(" "),
      );
    } else if (typeof v === "object") {
      parts.push(Object.values(v).join(" "));
    } else {
      parts.push(String(v));
    }
  }
  return parts.join(" ").toLowerCase();
}

function ArchiveTable({ kind, rows }) {
  if (!rows.length) {
    return (
      <div style={{ fontSize: "0.74rem", color: "var(--subtext)", padding: 10 }}>
        No records match.
      </div>
    );
  }
  if (kind === "trades") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Teams</th>
            <th>Assets</th>
            <th>Positions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week ?? "—"}</td>
              <td>{(r.ownerIds || []).join(" ↔ ")}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.totalAssets}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.positions || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "waivers") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Type</th>
            <th>Manager</th>
            <th>Bid</th>
            <th>Added</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week ?? "—"}</td>
              <td style={{ fontFamily: "var(--mono)", fontSize: "0.7rem" }}>{r.type}</td>
              <td>{r.ownerId || "—"}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.bid ?? "—"}</td>
              <td style={{ fontSize: "0.72rem" }}>
                {(r.added || []).map((p) => `${p.playerName} (${p.position || "?"})`).join(", ")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "weeklyMatchups") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Wk</th>
            <th>Home</th>
            <th style={{ textAlign: "right" }}>Score</th>
            <th style={{ textAlign: "right" }}>Score</th>
            <th>Away</th>
            <th>Tags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.week}</td>
              <td>{r.homeOwnerId || "—"}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(r.homePoints)}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtPoints(r.awayPoints)}</td>
              <td>{r.awayOwnerId || "—"}</td>
              <td style={{ fontSize: "0.7rem" }}>{(r.tags || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "rookieDrafts") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Pick</th>
            <th>Player</th>
            <th>Pos</th>
            <th>NFL</th>
            <th>Drafted by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontFamily: "var(--mono)" }}>
                {r.round}.{String(r.pickNo).padStart(2, "0")}
              </td>
              <td style={{ fontWeight: 600 }}>{r.playerName}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.position || ""}</td>
              <td style={{ fontFamily: "var(--mono)" }}>{r.nflTeam || ""}</td>
              <td>{r.teamName}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "seasonResults") {
    return (
      <table>
        <thead>
          <tr>
            <th>Season</th>
            <th>Team</th>
            <th style={{ textAlign: "right" }}>W-L-T</th>
            <th style={{ textAlign: "right" }}>PF</th>
            <th style={{ textAlign: "right" }}>Seed</th>
            <th style={{ textAlign: "right" }}>Final</th>
            <th>Tags</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              <td style={{ fontWeight: 600 }}>{r.teamName}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {r.wins}-{r.losses}{r.ties ? `-${r.ties}` : ""}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtNumber(r.pointsFor, 1)}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.standing}</td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{r.finalPlace ?? "—"}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.tags || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (kind === "managers") {
    return (
      <table>
        <thead>
          <tr>
            <th>Manager</th>
            <th>Current team</th>
            <th>Aliases</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td style={{ fontWeight: 600 }}>{r.displayName}</td>
              <td>{r.currentTeamName}</td>
              <td style={{ fontSize: "0.72rem" }}>{(r.aliases || []).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }
  return null;
}

// Expose available section keys for external consumers / tests.
export const LEAGUE_PAGE_SECTIONS = PUBLIC_SECTION_KEYS;
