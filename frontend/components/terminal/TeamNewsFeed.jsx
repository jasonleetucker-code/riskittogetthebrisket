"use client";

import { useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { useNews } from "@/components/useNews";
import Panel from "./Panel";
import { filterByScope, timeAgo } from "@/lib/news-service";

const SCOPE_TABS = [
  { key: "roster", label: "My Roster" },
  { key: "league", label: "League" },
  { key: "all", label: "All" },
];

const MAX_ITEMS = 12;

function useLeagueNames(sleeperTeams) {
  return useMemo(() => {
    const names = [];
    if (!Array.isArray(sleeperTeams)) return names;
    for (const t of sleeperTeams) {
      if (Array.isArray(t?.players)) names.push(...t.players);
    }
    return names;
  }, [sleeperTeams]);
}

export default function TeamNewsFeed() {
  const { rawData, openPlayerPopup, rows } = useApp();
  const { selectedTeam } = useTeam();
  const sleeperTeams = rawData?.sleeper?.teams;
  const leagueNames = useLeagueNames(sleeperTeams);
  const rosterNames = selectedTeam?.players || [];

  const [scope, setScope] = useState("roster");
  const news = useNews({ rosterNames, leagueNames });

  // Build a name → {fitDelta, fitConfidence, onRoster} lookup so we
  // can enrich each news item's player list with lens context.
  // Pure transform — no extra fetches needed; ``rows`` is already
  // available from useApp.
  const fitByName = useMemo(() => {
    const out = new Map();
    if (!Array.isArray(rows)) return out;
    const rosterLower = new Set(
      (rosterNames || []).map((n) => String(n).trim().toLowerCase())
    );
    for (const r of rows) {
      const key = String(r?.name || "").trim().toLowerCase();
      if (!key) continue;
      out.set(key, {
        fitDelta: typeof r.idpScoringFitDelta === "number" ? r.idpScoringFitDelta : null,
        fitConfidence: r.idpScoringFitConfidence || null,
        onRoster: rosterLower.has(key),
      });
    }
    return out;
  }, [rows, rosterNames]);

  // Enrich + filter.  Each player on each news item gets fit data
  // attached so ``NewsItem`` can render the lens-context badge.
  const scopedItems = useMemo(() => {
    if (news.loading || news.items.length === 0) return [];
    const filtered = filterByScope(news.scored, scope).slice(0, MAX_ITEMS);
    return filtered.map((item) => ({
      ...item,
      players: (item.players || []).map((p) => {
        const key = String(p?.name || "").trim().toLowerCase();
        const fit = fitByName.get(key);
        return fit ? { ...p, ...fit } : p;
      }),
    }));
  }, [news, scope, fitByName]);

  const isMock = news.source === "mock";

  return (
    <Panel
      title="News"
      subtitle={isMock ? "Demo feed — backend adapter pending" : "Roster-relevant headlines"}
      className="panel--news"
      actions={
        <div className="panel-tabs" role="tablist" aria-label="News scope">
          {SCOPE_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={scope === t.key}
              className={`panel-tab${scope === t.key ? " is-active" : ""}`}
              onClick={() => setScope(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      }
    >
      {isMock && (
        <div className="news-demo-badge" role="note" aria-label="Demo data notice">
          DEMO · Using bundled fixture until backend /api/news lands
        </div>
      )}

      {news.loading && <NewsSkeleton rows={4} />}

      {!news.loading && news.unavailable && (
        <div className="news-empty" role="status">
          <span className="news-empty-title">News unavailable</span>
          <span className="news-empty-body">
            {humanizeReason(news.reason)}
          </span>
        </div>
      )}

      {!news.loading && !news.unavailable && scopedItems.length === 0 && (
        <div className="news-empty" role="status">
          <span className="news-empty-title">
            {scope === "roster"
              ? "No roster-relevant headlines"
              : "No matching news"}
          </span>
          <span className="news-empty-body">
            {scope === "roster"
              ? "Switch scope to League or All to see broader coverage."
              : "Try a wider scope."}
          </span>
        </div>
      )}

      {!news.loading && !news.unavailable && scopedItems.length > 0 && (
        <ul className="news-feed">
          {scopedItems.map((item) => (
            <NewsItem
              key={item.id || `${item.ts}-${item.headline}`}
              item={item}
              onPlayerClick={openPlayerPopup}
            />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function NewsItem({ item, onPlayerClick }) {
  const matched = Array.isArray(item.__matchedOn) ? item.__matchedOn : [];
  const primary = matched.find((m) => m.scope === "roster") || matched[0] || null;
  const sevClass = `news-item--sev-${item.severity || "info"}`;
  const rosterClass =
    item.__relevance >= 100 ? " news-item--roster" : "";

  // Lens-context badge: when the news mentions a player who's
  // fit-positive (lens says undervalued vs market) and they're on
  // the user's roster, surface that on the headline.  Defensive
  // value — don't lose a buy-low to a news cycle.
  const fitContext = (() => {
    if (!Array.isArray(item.players) || item.players.length === 0) return null;
    const fitPlayers = item.players.filter(
      (p) => p && typeof p.fitDelta === "number"
            && Math.abs(p.fitDelta) >= 1500
            && (p.fitConfidence === "high" || p.fitConfidence === "medium"),
    );
    if (fitPlayers.length === 0) return null;
    const top = fitPlayers.sort(
      (a, b) => Math.abs(b.fitDelta) - Math.abs(a.fitDelta),
    )[0];
    return {
      name: top.name,
      delta: top.fitDelta,
      onRoster: !!top.onRoster,
    };
  })();

  return (
    <li className={`news-item ${sevClass}${rosterClass}`}>
      <div className="news-item-meta">
        <span className="news-item-time">{timeAgo(item.ts)}</span>
        <span className="news-item-provider">{item.providerLabel || item.provider || "—"}</span>
        {item.severity && (
          <span className={`news-item-severity news-item-severity--${item.severity}`}>
            {item.severity}
          </span>
        )}
      </div>
      <h3 className="news-item-headline">{item.headline}</h3>
      {fitContext && (
        <div
          style={{
            fontSize: "0.66rem",
            margin: "2px 0 4px",
            padding: "2px 6px",
            display: "inline-block",
            borderRadius: 3,
            background: "rgba(34, 211, 238, 0.12)",
            color: "var(--cyan, #22d3ee)",
            fontWeight: 600,
          }}
          title={`${fitContext.name} is ${fitContext.delta > 0 ? "fit-positive" : "fit-negative"} ${Math.round(fitContext.delta).toLocaleString()} under your league's scoring${fitContext.onRoster ? " (on your roster)" : ""}`}
        >
          ⚡ Lens: {fitContext.name} {fitContext.delta > 0 ? "+" : ""}{Math.round(fitContext.delta).toLocaleString()}
          {fitContext.onRoster ? " · your roster" : ""}
        </div>
      )}
      {item.body && <p className="news-item-body">{item.body}</p>}
      <div className="news-item-foot">
        {matched.length > 0 ? (
          <div className="news-item-players">
            {matched.map((m) => (
              <button
                key={m.name + m.scope}
                type="button"
                className={`news-item-player news-item-player--${m.scope}`}
                onClick={() => onPlayerClick?.(m.name)}
                title={`Open ${m.name}`}
              >
                {m.name}
              </button>
            ))}
          </div>
        ) : (
          <span className="news-item-players-empty">General</span>
        )}
        {item.kind && <span className="news-item-kind">{item.kind}</span>}
      </div>
    </li>
  );
}

function NewsSkeleton({ rows = 3 }) {
  return (
    <ul className="news-feed news-feed--skeleton" aria-hidden="true">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="news-item news-item--skeleton">
          <div className="news-item-meta">
            <span className="skeleton-line skeleton-line--xs" />
            <span className="skeleton-line skeleton-line--xs" />
          </div>
          <span className="skeleton-line skeleton-line--wide" />
          <span className="skeleton-line skeleton-line--wide" />
        </li>
      ))}
    </ul>
  );
}

function humanizeReason(reason) {
  switch (reason) {
    case "fetch_failed":
      return "Could not reach the news endpoint. Check network and try again.";
    case "no_provider_configured":
      return "No provider is configured yet; panel will populate when one is.";
    default:
      return "News provider returned an unexpected response.";
  }
}
